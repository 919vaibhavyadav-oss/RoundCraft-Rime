"""The acceptance test for the hard voice problem.

Written before the LiveKit wiring exists, deliberately: the event rules ask for
the acceptance test to be defined ahead of the demo rather than assembled
afterwards to match whatever the product happened to do.

The claim under test: when a candidate interrupts one interviewer and another
takes the floor, the abandoned sentence is never spoken, never recorded as
evidence, and never reaches the director.
"""

from app.panel.floor import FloorGuard, SpokenWord


def words(*pairs: tuple[str, int]) -> list[SpokenWord]:
    return [SpokenWord(text=text, start_ms=start) for text, start in pairs]


SENTENCE = words(
    ("You", 0),
    ("called", 180),
    ("pulse", 400),
    ("feedback", 620),
    ("a", 900),
    ("guardrail", 1000),
)


def test_the_floor_starts_empty() -> None:
    guard = FloorGuard()

    assert guard.speaker_id is None
    assert guard.accepts(0) is False


def test_taking_the_floor_returns_a_generation_that_is_accepted() -> None:
    guard = FloorGuard()

    generation = guard.take_floor("analytics")

    assert guard.speaker_id == "analytics"
    assert guard.accepts(generation) is True


def test_an_interrupt_keeps_only_what_was_heard() -> None:
    guard = FloorGuard()
    generation = guard.take_floor("analytics")
    guard.note_spoken(generation, SENTENCE)

    cut = guard.interrupt(at_ms=700)

    assert cut is not None
    assert cut.heard == "You called pulse feedback"
    assert cut.unheard == "a guardrail"
    assert cut.cut_mid_sentence is True
    assert cut.panelist_id == "analytics"


def test_the_abandoned_response_can_no_longer_be_spoken() -> None:
    """The fence. This is the property the whole feature exists for."""
    guard = FloorGuard()
    stale = guard.take_floor("analytics")
    guard.note_spoken(stale, SENTENCE)
    guard.interrupt(at_ms=700)

    # The model finally returns interviewer A's full answer, too late.
    assert guard.accepts(stale) is False

    # And a different interviewer now holds the floor.
    fresh = guard.take_floor("product-sense")
    assert fresh != stale
    assert guard.accepts(fresh) is True
    assert guard.accepts(stale) is False


def test_a_late_arriving_result_cannot_pollute_the_new_turn() -> None:
    guard = FloorGuard()
    stale = guard.take_floor("analytics")
    guard.interrupt(at_ms=0)
    fresh = guard.take_floor("product-sense")

    # A straggler from the interrupted turn tries to record speech.
    guard.note_spoken(stale, words(("stale", 0), ("sentence", 100)))

    cut = guard.interrupt(at_ms=5_000)
    assert cut is not None
    assert cut.generation == fresh
    assert cut.heard == ""


def test_interrupting_silence_does_nothing() -> None:
    """A stray barge-in must not invent an empty turn in the transcript."""
    guard = FloorGuard()

    assert guard.interrupt(at_ms=400) is None


def test_an_interrupt_before_the_first_word_leaves_nothing_heard() -> None:
    guard = FloorGuard()
    generation = guard.take_floor("hiring-manager")
    guard.note_spoken(generation, SENTENCE)

    cut = guard.interrupt(at_ms=0)

    assert cut is not None
    assert cut.heard == ""
    assert cut.unheard.startswith("You called")


def test_an_interrupt_after_the_last_word_is_not_a_mid_sentence_cut() -> None:
    guard = FloorGuard()
    generation = guard.take_floor("hiring-manager")
    guard.note_spoken(generation, SENTENCE)

    cut = guard.interrupt(at_ms=9_999)

    assert cut is not None
    assert cut.unheard == ""
    assert cut.cut_mid_sentence is False
    assert cut.heard.endswith("guardrail")


def test_releasing_the_floor_normally_clears_the_speaker() -> None:
    guard = FloorGuard()
    generation = guard.take_floor("analytics")

    guard.release(generation)

    assert guard.speaker_id is None
    assert guard.accepts(generation) is False


def test_a_stale_release_cannot_clear_the_current_speaker() -> None:
    guard = FloorGuard()
    stale = guard.take_floor("analytics")
    guard.interrupt(at_ms=0)
    fresh = guard.take_floor("product-sense")

    guard.release(stale)

    assert guard.speaker_id == "product-sense"
    assert guard.accepts(fresh) is True


def test_each_handover_is_a_new_generation() -> None:
    guard = FloorGuard()

    seen = [guard.take_floor("analytics")]
    guard.interrupt(at_ms=100)
    seen.append(guard.take_floor("product-sense"))
    guard.interrupt(at_ms=100)
    seen.append(guard.take_floor("hiring-manager"))

    assert len(set(seen)) == len(seen), "generations must never repeat"
    assert seen == sorted(seen), "generations must move forward"
