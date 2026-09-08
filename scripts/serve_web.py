"""Serve the candidate's browser interface, and mint the token it joins with.

    uv run python scripts/serve_web.py

Deliberately the standard library and nothing else. Adding a web framework on
submission day to serve one page and one JSON endpoint would be a poor trade,
and this has no build step to go wrong while recording.

The LiveKit API secret never leaves this process: the browser receives a signed,
short-lived token scoped to a single room, which is what the event rules mean by
keeping credentials in server-side secrets rather than client code.
"""

import json
import os
import sys
import uuid
from collections.abc import Mapping
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PORT = int(os.environ.get("WEB_PORT", "8080"))

sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from livekit.api import AccessToken, VideoGrants  # noqa: E402

from app.panel.events import roster  # noqa: E402

# Long enough to record several takes without reissuing, short enough that a
# token left in a browser tab is not a standing credential.
TOKEN_TTL_SECONDS = 60 * 60


def mint_token(room: str, identity: str) -> str:
    """A join token for one room, signed here and never in the browser."""
    api_key = os.environ.get("LIVEKIT_API_KEY", "")
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "")
    if not api_key or not api_secret:
        raise RuntimeError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in .env")
    return (
        AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name("Candidate")
        .with_grants(VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
        .to_jwt()
    )


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(WEB), **kwargs)  # type: ignore[arg-type]

    def do_GET(self) -> None:  # noqa: N802  (stdlib naming)
        path = urlparse(self.path).path
        if path == "/api/join":
            self.serve_join()
            return
        if path == "/api/panel":
            # So the page can show who is on the panel before anyone joins,
            # taken from the roster rather than duplicated into the markup.
            self.send_json(roster())
            return
        super().do_GET()

    def send_json(self, payload: Mapping[str, object], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def serve_join(self) -> None:
        """Hand the page everything it needs to join, and nothing more."""
        # A fresh room per session, so a recording is never joined by a stale
        # participant from an earlier take.
        room = f"roundcraft-{uuid.uuid4().hex[:8]}"
        try:
            payload = {
                "url": os.environ["LIVEKIT_URL"],
                "token": mint_token(room, f"candidate-{uuid.uuid4().hex[:6]}"),
                "room": room,
            }
        except (KeyError, RuntimeError) as exc:
            self.send_error(500, str(exc))
            return
        self.send_json(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        # The default handler prints every asset request, which buries the one
        # line that matters while recording.
        first = str(args[0]) if args else ""
        if "/api/join" in first:
            sys.stderr.write("issued a join token\n")


def main() -> int:
    if not WEB.exists():
        print(f"missing {WEB}")
        return 2
    for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        if not os.environ.get(name):
            print(f"{name} is not set. Run: uv run python scripts/setup.py")
            return 1

    print(f"\n  RoundCraft is at  http://localhost:{PORT}\n")
    print("  Leave the agent running in its own terminal, then open that link")
    print("  and click Join. Ctrl+C here to stop.\n")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
