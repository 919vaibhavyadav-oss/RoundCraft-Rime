"""The agent's turn bookkeeping, tested without LiveKit or Rime.

`app.agent` imports the LiveKit plugins at module load, which are not installed
in a bare checkout. These tests exercise the same logic through the pure panel
modules the agent delegates to, so the acceptance test runs anywhere.
"""

from app.panel import director
from app.panel.floor import FloorGuard, SpokenWord
from app.panel.voices import voice_for


def test_a_completed_turn_advances_the_panel() -> None:
    state = director.PanelState()
    floor = FloorGuard()

    decision = director.choose_next(state, "We measured retention at 22 percent.")
    generation = floor.take_floor(decision.speaker.id)

    assert floor.accepts(generation)
    state = director.record(state, decision)
    floor.release(generation)

    assert state.question_counts[decision.speaker.id] == 1


def test_an_interrupted_turn_never_reaches_the_director() -> None:
    """The property that matters: a sentence nobody heard leaves no trace."""
    state = director.PanelState()
    floor = FloorGuard()

    decision = director.choose_next(state, "We measured retention at 22 percent.")
    generation = floor.take_floor(decision.speaker.id)
    floor.note_spoken(generation, [SpokenWord("How", 0), SpokenWord("did", 200)])
    floor.interrupt(at_ms=100)

    # The agent only records a turn the floor still accepts.
    if floor.accepts(generation):
        state = director.record(state, decision)

    assert state.question_counts == {}
    assert state.current_speaker_id is None


def test_each_interviewer_speaks_in_their_own_voice() -> None:
    speakers = {voice_for(member).speaker for member in ("hiring-manager", "product-sense", "analytics")}

    assert len(speakers) == 3


def test_the_voice_follows_whoever_the_director_picked() -> None:
    decision = director.choose_next(director.PanelState(), "The customer problem was onboarding.")

    profile = voice_for(decision.speaker.id)

    assert profile.speaker == "arcade"
