"""What the room is told about the panel, so a person can watch it happen.

The interruption claim is currently provable only by reading a log. That is
fine for a test and poor for a demo: the most important thing this product does
should be visible to the person it happens to, not reconstructed afterwards
from a terminal.

These are the messages the agent broadcasts over the LiveKit data channel. They
are plain dictionaries rather than a class hierarchy because they cross into
JavaScript, and they are built here rather than inline in the agent so their
shape is pinned by tests on both sides of that boundary.

Nothing here is required for the interview to work. If the browser is not
listening, or publishing fails, the interview carries on unchanged.
"""

from typing import Any

from app.panel.floor import Interruption
from app.panel.roster import PANEL
from app.panel.voices import voice_for

TOPIC = "roundcraft.panel"

# Bumped when a field changes meaning, so an old page open in a tab cannot
# quietly misread a new agent.
PROTOCOL = 1


def _base(kind: str) -> dict[str, Any]:
    return {"v": PROTOCOL, "type": kind}


def roster() -> dict[str, Any]:
    """Who is on the panel, sent once when the candidate joins."""
    event = _base("roster")
    event["panel"] = [
        {
            "id": member.id,
            "name": member.name,
            "role": member.role,
            "voice": voice_for(member.id).speaker,
        }
        for member in PANEL
    ]
    return event


def floor_taken(panelist_id: str, name: str, generation: int, rationale: str) -> dict[str, Any]:
    """An interviewer has the floor, and why they were chosen.

    The rationale is shown to the candidate deliberately. A panel that picks a
    speaker for a stated reason is reviewable; one that just picks is not.
    """
    event = _base("floor")
    event.update(
        speaker=panelist_id,
        name=name,
        generation=generation,
        rationale=rationale,
        voice=voice_for(panelist_id).speaker,
    )
    return event


def turn_committed(panelist_id: str, generation: int, text: str, heard_ms: int) -> dict[str, Any]:
    """A turn reached the candidate whole."""
    event = _base("committed")
    event.update(speaker=panelist_id, generation=generation, text=text, heard_ms=heard_ms)
    return event


def turn_interrupted(cut: Interruption) -> dict[str, Any]:
    """A turn was cut off, carrying both halves.

    `unheard` is sent so the page can show what was dropped. Displaying it is
    the point: a judge should be able to see that the abandoned words existed
    and were never spoken, rather than take our word for it.
    """
    event = _base("interrupted")
    event.update(
        speaker=cut.panelist_id,
        generation=cut.generation,
        heard=cut.heard,
        unheard=cut.unheard,
        at_ms=cut.at_ms,
    )
    return event


def candidate_said(text: str) -> dict[str, Any]:
    """What the candidate was heard to say."""
    event = _base("candidate")
    event["text"] = text
    return event


def lookup_started(claim: str, generation: int) -> dict[str, Any]:
    """A benchmark lookup is in flight, and can be interrupted."""
    event = _base("lookup_started")
    event.update(claim=claim, generation=generation)
    return event


def lookup_discarded(claim: str, generation: int) -> dict[str, Any]:
    """A lookup outlived its turn and will not be spoken."""
    event = _base("lookup_discarded")
    event.update(claim=claim, generation=generation)
    return event


def lookup_returned(metric: str, generation: int) -> dict[str, Any]:
    """A lookup came back inside its turn and is being used."""
    event = _base("lookup_returned")
    event.update(metric=metric, generation=generation)
    return event
