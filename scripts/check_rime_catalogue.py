"""Check our pinned speakers against Rime's live catalogue.

The event rules forbid shipping a stale speaker list: the catalogue must be
checked at submission time. Run this before recording the demo.

    RIME_API_KEY=... python scripts/check_rime_catalogue.py
"""

import os
import sys

import httpx

from app.panel.voices import verify_speakers

CATALOGUE_URL = "https://users.rime.ai/data/voices/voice-details.json"


def main() -> int:
    key = os.environ.get("RIME_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        response = httpx.get(CATALOGUE_URL, headers=headers, timeout=15)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Could not reach the Rime catalogue: {exc}", file=sys.stderr)
        return 2

    entries = payload if isinstance(payload, list) else payload.get("voices", [])
    live = {
        str(item.get("name") or item.get("speaker") or "")
        for item in entries
        if isinstance(item, dict)
    }
    live.discard("")
    if not live:
        print("The catalogue response held no speaker names; check the endpoint.", file=sys.stderr)
        return 2

    missing = verify_speakers(live)
    if missing:
        print("Pinned speakers missing from the live catalogue:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        return 1

    print(f"All pinned speakers are in the live catalogue ({len(live)} voices available).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
