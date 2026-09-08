"""Serve the candidate's browser interface, and mint the token it joins with.

    uv run python scripts/serve_web.py

Deliberately the standard library and nothing else. Adding a web framework on
submission day to serve one page and three JSON endpoints would be a poor trade,
and this has no build step to go wrong while recording.

The LiveKit API secret never leaves this process: the browser receives a signed,
short-lived token scoped to a single room, which is what the event rules mean by
keeping credentials in server-side secrets rather than client code.

Minting a token starts an interview, and an interview spends real money at Rime,
Deepgram and the model provider. So the endpoint that mints one is gated on a
shared access code, compared in constant time and rate limited per address. It
is not an account system and does not pretend to be: there are no passwords, no
stored personal data, and the code is checked here rather than in the browser.
"""

import hmac
import json
import os
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping
from datetime import timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
# Render (and most hosts) hand the port in and expect a bind on all
# interfaces. Locally the default keeps it off the network.
PORT = int(os.environ.get("PORT") or os.environ.get("WEB_PORT") or "8080")
HOST = os.environ.get("WEB_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")

sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from livekit.api import AccessToken, VideoGrants  # noqa: E402

from app.panel.events import roster  # noqa: E402

# Long enough to record several takes without reissuing, short enough that a
# token left in a browser tab is not a standing credential.
TOKEN_TTL_SECONDS = 60 * 60

ACCESS_CODE = os.environ.get("ACCESS_CODE", "").strip()
MAX_BODY_BYTES = 4096
# Enough for a demo and several retries, low enough that guessing the code by
# brute force is not worth attempting.
ATTEMPTS_PER_WINDOW = 12
WINDOW_SECONDS = 300

_attempts: dict[str, list[float]] = defaultdict(list)
_attempts_lock = Lock()


def rate_limited(client: str) -> bool:
    """Whether this address has had too many goes in the current window."""
    now = time.monotonic()
    with _attempts_lock:
        recent = [t for t in _attempts[client] if now - t < WINDOW_SECONDS]
        recent.append(now)
        _attempts[client] = recent
        return len(recent) > ATTEMPTS_PER_WINDOW


def code_accepted(supplied: str) -> bool:
    """Constant-time check, so a wrong code cannot be found a character at a time.

    An unset ACCESS_CODE allows anyone in. That is right for a laptop and wrong
    for a deployment, so `main` refuses to start unset when a host has handed us
    a port.
    """
    if not ACCESS_CODE:
        return True
    return hmac.compare_digest(supplied.strip(), ACCESS_CODE)


def clean_name(raw: str) -> str:
    """A display name, kept short and free of anything that could be markup."""
    name = " ".join(raw.split())[:40]
    return "".join(ch for ch in name if ch.isalnum() or ch in " '-.") or "Candidate"


def mint_token(room: str, identity: str, display: str) -> str:
    """A join token for one room, signed here and never in the browser."""
    api_key = os.environ.get("LIVEKIT_API_KEY", "")
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "")
    if not api_key or not api_secret:
        raise RuntimeError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in .env")
    token: str = (
        AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(display)
        .with_ttl(timedelta(seconds=TOKEN_TTL_SECONDS))
        .with_grants(VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
        .to_jwt()
    )
    return token


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(WEB), **kwargs)  # type: ignore[arg-type]

    # -- routing ---------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802  (stdlib naming)
        path = urlparse(self.path).path
        if path == "/api/panel":
            # So the page can show who is on the panel before anyone joins,
            # taken from the roster rather than duplicated into the markup.
            self.send_json(roster())
            return
        if path == "/api/session":
            self.send_json({"needs_code": bool(ACCESS_CODE)})
            return
        if path == "/api/join":
            # A join carries a code, and a code has no business in a URL where
            # it would be logged by every proxy in between.
            self.send_json({"error": "use POST"}, status=405)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802  (stdlib naming)
        if urlparse(self.path).path != "/api/join":
            self.send_json({"error": "not found"}, status=404)
            return
        self.serve_join()

    # -- the one endpoint that spends money ------------------------------

    def serve_join(self) -> None:
        client = self.client_address[0] if self.client_address else "unknown"
        if rate_limited(client):
            self.send_json({"error": "Too many attempts. Wait a few minutes."}, status=429)
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            self.send_json({"error": "request too large"}, status=413)
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError):
            self.send_json({"error": "could not read the request"}, status=400)
            return
        if not isinstance(body, dict):
            self.send_json({"error": "could not read the request"}, status=400)
            return

        if not code_accepted(str(body.get("code", ""))):
            # Deliberately says nothing about which part was wrong.
            self.send_json({"error": "That access code is not valid."}, status=401)
            return

        display = clean_name(str(body.get("name", "")))
        # A fresh room per session, so a recording is never joined by a stale
        # participant from an earlier take.
        room = f"roundcraft-{uuid.uuid4().hex[:8]}"
        try:
            payload = {
                "url": os.environ["LIVEKIT_URL"],
                "token": mint_token(room, f"candidate-{uuid.uuid4().hex[:6]}", display),
                "room": room,
                "name": display,
            }
        except (KeyError, RuntimeError) as exc:
            self.send_json({"error": str(exc)}, status=500)
            return
        self.send_json(payload)

    # -- plumbing --------------------------------------------------------

    def send_json(self, payload: Mapping[str, object], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        """Never let a browser keep the page.

        The static handler sends no cache headers, so a browser holds on to
        index.html and quietly serves an old copy after every edit. That is
        confusing during development and dangerous during a demo, where the
        page on screen would not be the page in the repository.
        """
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        # The default handler prints every asset request, which buries the one
        # line that matters while recording. Never log the body: it carries the
        # access code.
        first = str(args[0]) if args else ""
        if "/api/join" in first:
            sys.stderr.write(f"join request: {args[1] if len(args) > 1 else ''}\n")


def main() -> int:
    if not WEB.exists():
        print(f"missing {WEB}")
        return 2
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        if not os.environ.get(name):
            print(f"{name} is not set. Run: uv run python scripts/setup.py")
            return 1

    deployed = bool(os.environ.get("PORT"))
    if deployed and not ACCESS_CODE:
        # An open endpoint on a public URL spends someone else's money.
        print("ACCESS_CODE is not set. Refusing to serve a public instance without one.")
        return 1

    where = f"http://localhost:{PORT}" if HOST == "127.0.0.1" else f"{HOST}:{PORT}"
    print(f"\n  RoundCraft is at  {where}")
    print(f"  Access code: {'required' if ACCESS_CODE else 'not set (anyone can start one)'}\n")
    print("  Leave the agent running in its own terminal, then open that link")
    print("  and start an interview. Ctrl+C here to stop.\n")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
