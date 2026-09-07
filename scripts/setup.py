"""Set up and check everything this project needs, in one command.

    uv run python scripts/setup.py

Creates .env if it is missing, tells you exactly which keys are still blank and
where to get each one, then tests every service for real. Never prints a key
value, so the output is safe to paste into chat or a screenshot.
"""

import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"

TICK = "[ok]"
CROSS = "[--]"
WARN = "[!!]"

WHERE = {
    "RIME_API_KEY": "rime.ai  ->  dashboard  ->  API keys",
    "LIVEKIT_URL": "cloud.livekit.io  ->  your project  ->  Settings  ->  Keys (starts wss://)",
    "LIVEKIT_API_KEY": "cloud.livekit.io  ->  same page",
    "LIVEKIT_API_SECRET": "cloud.livekit.io  ->  same page",
    "DEEPGRAM_API_KEY": "console.deepgram.com  ->  API keys",
    "LLM_API_KEY": "reuse the Groq key from the other project",
}

REQUIRED = tuple(WHERE)


def load_env() -> dict[str, str]:
    """Read .env without needing the app's dependencies to import cleanly."""
    values: dict[str, str] = {}
    if not ENV.exists():
        return values
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def is_placeholder(value: str) -> bool:
    """Whether a value is still the shipped example rather than a real one."""
    lowered = value.lower()
    if not lowered:
        return True
    # "your-project", "your_rime_api_key", "placeholder" - anything we shipped.
    return any(hint in lowered for hint in ("your_", "your-", "placeholder", "changeme"))


def step_env_file() -> bool:
    if ENV.exists():
        print(f"{TICK} .env exists")
        return True
    if not EXAMPLE.exists():
        print(f"{CROSS} .env.example is missing; cannot create .env")
        return False
    ENV.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"{TICK} created .env from .env.example")
    return True


def step_keys(values: dict[str, str]) -> list[str]:
    missing = [name for name in REQUIRED if is_placeholder(values.get(name, ""))]
    for name in REQUIRED:
        if name in missing:
            print(f"{CROSS} {name:<20} still blank   <- {WHERE[name]}")
        else:
            print(f"{TICK} {name:<20} set")
    return missing


def check_rime(key: str) -> tuple[bool, str]:
    """Ask Rime for the voice catalogue, which also validates the key."""
    try:
        response = httpx.get(
            "https://users.rime.ai/data/voices/voice-details.json",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        return False, f"could not reach Rime ({type(exc).__name__})"
    if response.status_code in (401, 403):
        return False, "Rime rejected the key"
    if response.status_code >= 400:
        return False, f"Rime returned {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        return False, "Rime returned something that was not JSON"
    entries = payload if isinstance(payload, list) else payload.get("voices", [])
    names = {
        str(item.get("name") or item.get("speaker") or "")
        for item in entries
        if isinstance(item, dict)
    }
    names.discard("")
    if not names:
        return False, "no speaker names in the catalogue response"

    from app.panel.voices import verify_speakers

    absent = verify_speakers(names)
    if absent:
        return False, f"{len(names)} voices available, but these are not among them: {', '.join(absent)}"
    return True, f"{len(names)} voices available, and all our speakers exist"


def check_deepgram(key: str) -> tuple[bool, str]:
    try:
        response = httpx.get(
            "https://api.deepgram.com/v1/projects",
            headers={"Authorization": f"Token {key}"},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        return False, f"could not reach Deepgram ({type(exc).__name__})"
    if response.status_code in (401, 403):
        return False, "Deepgram rejected the key"
    return response.status_code < 400, f"Deepgram returned {response.status_code}"


def check_llm(base_url: str, key: str, model: str) -> tuple[bool, str]:
    """Check the key works *and* that this account can actually see the model.

    A new account often carries a different model list, so a key that
    authenticates fine can still fail later inside a voice session. Cheaper to
    find out here.
    """
    url = (base_url or "https://api.groq.com/openai/v1").rstrip("/") + "/models"
    try:
        response = httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=15)
    except httpx.HTTPError as exc:
        return False, f"could not reach the model provider ({type(exc).__name__})"
    if response.status_code in (401, 403):
        return False, "the model provider rejected the key"
    if response.status_code >= 400:
        return False, f"model provider returned {response.status_code}"

    try:
        available = {
            str(item.get("id", "")) for item in response.json().get("data", []) if isinstance(item, dict)
        }
    except ValueError:
        return False, "the model list was not JSON"
    available.discard("")

    if not model or is_placeholder(model):
        return False, f"LLM_MODEL is not set. This account offers: {_sample(available)}"
    if model not in available:
        return False, f"this account cannot see '{model}'. It offers: {_sample(available)}"
    return True, f"key works and '{model}' is available"


def _sample(names: set[str], limit: int = 6) -> str:
    """A few real model ids, so a wrong one can be corrected without a browser."""
    if not names:
        return "no models listed"
    shown = sorted(names)[:limit]
    more = len(names) - len(shown)
    return ", ".join(shown) + (f", and {more} more" if more > 0 else "")


def check_livekit(url: str) -> tuple[bool, str]:
    if not url.startswith("wss://"):
        return False, "LIVEKIT_URL should start with wss://"
    return True, "looks well formed (the agent proves it for real on first run)"


def main() -> int:
    print("\nRoundCraft on Rime - setup check\n" + "=" * 46)

    if not step_env_file():
        return 2
    print()

    values = {**load_env(), **{k: v for k, v in os.environ.items() if k in REQUIRED}}
    missing = step_keys(values)

    if missing:
        print(
            f"\n{WARN} Open .env in an editor and fill in the {len(missing)} value(s) marked above,"
            "\n     then run this again. Nothing else is needed."
        )
        return 1

    print("\nTesting each service for real...\n" + "-" * 46)
    results = [
        ("Rime", *check_rime(values["RIME_API_KEY"])),
        ("Deepgram", *check_deepgram(values["DEEPGRAM_API_KEY"])),
        (
            "Model provider",
            *check_llm(
                values.get("LLM_BASE_URL", ""), values["LLM_API_KEY"], values.get("LLM_MODEL", "")
            ),
        ),
        ("LiveKit", *check_livekit(values["LIVEKIT_URL"])),
    ]
    for name, ok, detail in results:
        print(f"{TICK if ok else CROSS} {name:<16} {detail}")

    if all(ok for _, ok, _ in results):
        print("\nEverything is ready. Start the agent with:\n")
        print("    uv run python -m app.agent dev\n")
        print("Then open agents-playground.livekit.io, point it at your")
        print("LiveKit project, and join the room to talk to the panel.\n")
        return 0

    print("\nFix whatever is marked above, then run this again.\n")
    return 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
