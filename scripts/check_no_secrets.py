"""Fail the build if anything in the tree looks like a live credential.

The event rules are blunt about this: a submission that exposes a live
credential is not eligible for judging. That is worth a build step rather than
a habit, so this runs in CI and before the demo is recorded.

    python scripts/check_no_secrets.py

Exit codes: 0 clean, 1 something found, 2 could not run.
"""

import re
import subprocess
import sys
from pathlib import Path

# A credential is a long run of key characters carrying both letters and
# digits. Requiring both is what stops comment rules (--------) and
# underscore-separated identifiers matching.
CANDIDATE = re.compile(r"[A-Za-z0-9_\-]{28,}")
HAS_LETTER = re.compile(r"[A-Za-z]")
HAS_DIGIT = re.compile(r"[0-9]")

SCANNED_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".txt", ".sh", ".ts", ".tsx"}

# Words that mark a string as deliberately fake or structural rather than secret.
INNOCENT = (
    "your_",
    "placeholder",
    "example",
    "changeme",
    "xxxxxxxx",
    "abcdefgh",
    "livekit.cloud",
    "githubusercontent",
    "cloudfront",
)


def looks_like_a_key(token: str) -> bool:
    if not (HAS_LETTER.search(token) and HAS_DIGIT.search(token)):
        return False
    lowered = token.lower()
    if any(word in lowered for word in INNOCENT):
        return False
    # A long word made only of dictionary-ish characters separated by _ or -
    # is far more likely to be an identifier than a key.
    return not all(part.isalpha() for part in re.split(r"[_\-]", token) if part)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print("Not a git repository, or git is unavailable.", file=sys.stderr)
        raise SystemExit(2)
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    if Path(".env").exists() and ".env" in {str(p) for p in tracked_files()}:
        print("ERROR: .env is tracked. Remove it and rotate every key it held.", file=sys.stderr)
        return 1

    findings: list[str] = []
    for path in tracked_files():
        if path.suffix.lower() not in SCANNED_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith(("http://", "https://")):
                continue
            for token in CANDIDATE.findall(line):
                if looks_like_a_key(token):
                    findings.append(f"{path}:{number}: {token[:12]}… ({len(token)} chars)")

    if findings:
        print("ERROR: these look like credentials:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print(f"No credential-shaped strings in {len(tracked_files())} tracked files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
