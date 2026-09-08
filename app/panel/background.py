"""What the candidate tells the panel about themselves, before it starts.

An interviewer who has read your CV asks different questions from one who has
not: they name the project you actually shipped rather than asking you to pick
one. That is the whole reason this exists.

It is also personal data, so the handling is deliberately narrow. The text is
held for the length of one session and nothing else: never written to disk,
never logged, never sent anywhere except the model that has to read it in order
to ask about it. A candidate who skips the field gets the same interview, asked
in general terms.

Nothing here touches the network, so what the model is told can be checked by
reading a test rather than by inspecting a request.
"""

import re

# Enough for a real CV, short of anything that would crowd out the panel's own
# instructions or make a turn slow to generate.
MAX_CHARS = 6000
MAX_LINES = 80

# Contact details are the part of a CV an interviewer never needs and the part
# most costly to leak, so they are removed before the text reaches the model.
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
_URL = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.IGNORECASE)


# A phone number carries at least this many digits. Below it, the match is far
# more likely to be a date range: "2021 - 2024" is eight digits with spacing and
# punctuation between them, and redacting those would remove the career timeline
# an interviewer most wants to ask about.
_MIN_PHONE_DIGITS = 9


def _looks_like_a_phone(match: re.Match[str]) -> str:
    found = match.group()
    digits = sum(character.isdigit() for character in found)
    return "[phone]" if digits >= _MIN_PHONE_DIGITS else found


def redact(text: str) -> str:
    """Strip contact details. An interviewer has no use for them.

    This is not anonymisation and does not pretend to be: a CV names its author
    in the first line. It removes the identifiers that serve no interview
    purpose, so they are not sitting in a model request for no reason.
    """
    text = _EMAIL.sub("[email]", text)
    text = _URL.sub("[link]", text)
    return _PHONE.sub(_looks_like_a_phone, text)


def condense(raw: str) -> str:
    """Trim a pasted CV to something a panel can hold in mind.

    Blank-line runs collapse, over-long documents are cut at a line boundary
    rather than mid-word, and the result is capped. Returning an empty string
    means the candidate gave nothing usable, and the panel proceeds without it.
    """
    if not raw or not raw.strip():
        return ""
    lines = [line.strip() for line in redact(raw).splitlines()]
    kept: list[str] = []
    for line in lines:
        if not line and (not kept or not kept[-1]):
            continue  # collapse runs of blank lines
        kept.append(line)
        if len(kept) >= MAX_LINES:
            break
    text = "\n".join(kept).strip()
    if len(text) > MAX_CHARS:
        cut = text.rfind("\n", 0, MAX_CHARS)
        text = text[: cut if cut > MAX_CHARS // 2 else MAX_CHARS].rstrip()
    return text


def briefing(condensed: str) -> str:
    """The instruction the panel is given about the candidate's background.

    Written as a direction rather than as data, because a model handed a block
    of someone's CV with no framing will sometimes read it back to them.
    """
    if not condensed:
        return ""
    return (
        "The candidate supplied this background. Use it to ask about work they "
        "actually did: name their projects, their metrics and their role. Never "
        "read it back to them, never quote it aloud, and never mention that you "
        "were given it. If it does not cover what you want to ask about, ask "
        "anyway.\n\n"
        "--- candidate background ---\n"
        f"{condensed}\n"
        "--- end ---"
    )
