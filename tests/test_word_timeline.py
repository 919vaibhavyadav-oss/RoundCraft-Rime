"""Rime's clock restarts every sentence, and the cut depends on it not doing so.

Measured against the live service on 2026-09-08: synthesising the panel's
greeting produced 13.46s of audio and 32 timed words, but the offsets restarted
at zero at the sentence boundary, so the final word reported a start of 3.42s.

This matters more than a misplaced cut. `FloorGuard.interrupt` keeps every word
whose offset falls below the cut, so with a restarted clock a cut at three
seconds keeps the opening of *every* sentence and drops the end of each. The
transcript would then hold several interleaved half-sentences that were never
heard in that order, and this product cites the transcript as evidence.
"""

from app.panel.floor import FloorGuard, SpokenWord, WordTimeline

# The real thing, trimmed to the words either side of the boundary. Offsets are
# seconds, exactly as the Rime plugin reported them.
GREETING: list[tuple[str, float, float]] = [
    ("Hi, ", 0.0, 0.380),
    ("I'm ", 0.380, 0.570),
    ("Maya ", 0.570, 0.760),
    ("Chen, ", 0.760, 1.520),
    ("on ", 4.940, 5.130),
    ("analytics. ", 5.130, 6.841),
    # Second synthesis request; the clock starts again here.
    ("To ", 0.0, 0.190),
    ("get ", 0.190, 0.380),
    ("us ", 0.380, 0.570),
    ("started, ", 0.570, 1.900),
    ("shipped ", 3.230, 3.420),
    ("recently. ", 3.420, 4.940),
]


def place_all(rows: list[tuple[str, float, float]]) -> list[SpokenWord]:
    timeline = WordTimeline()
    placed = [timeline.place(text, start, end) for text, start, end in rows]
    return [word for word in placed if word is not None]


class TestWordTimeline:
    def test_a_single_request_passes_through_unchanged(self) -> None:
        words = place_all([("What", 0.0, 0.2), ("tradeoff", 0.2, 0.6)])
        assert [w.start_ms for w in words] == [0, 200]

    def test_the_whole_greeting_advances(self) -> None:
        """The property the cut relies on, stated directly."""
        starts = [word.start_ms for word in place_all(GREETING)]
        assert starts == sorted(starts), "offsets must never go backwards"

    def test_the_second_sentence_is_shifted_past_the_first(self) -> None:
        words = place_all(GREETING)
        # "analytics." ends the first request at 6.841s, so "To" follows it.
        assert words[5].text == "analytics."
        assert words[6].text == "To"
        assert words[6].start_ms == 6841

    def test_the_last_word_is_no_longer_earlier_than_the_first_sentence(self) -> None:
        """The symptom that exposed the bug: a 13s utterance ending at 3.4s."""
        words = place_all(GREETING)
        assert words[-1].text == "recently."
        assert words[-1].start_ms > words[5].start_ms
        assert words[-1].start_ms == 6841 + 3420

    def test_three_requests_accumulate(self) -> None:
        rows = [
            ("one", 0.0, 1.0),
            ("two", 0.0, 2.0),
            ("three", 0.0, 3.0),
        ]
        assert [w.start_ms for w in place_all(rows)] == [0, 1000, 3000]

    def test_an_untimed_word_does_not_shift_the_clock(self) -> None:
        timeline = WordTimeline()
        timeline.place("What", 0.0, 0.2)
        assert timeline.place("  ", 0.4, 0.5) is None
        placed = timeline.place("tradeoff", 0.4, 0.6)
        assert placed is not None
        assert placed.start_ms == 400

    def test_contiguous_words_are_one_request(self) -> None:
        """Each word starts exactly where the last ended. That is not a restart."""
        rows = [("a", 0.0, 0.2), ("b", 0.2, 0.4), ("c", 0.4, 0.5)]
        assert [w.start_ms for w in place_all(rows)] == [0, 200, 400]

    def test_a_word_with_only_an_end_time_still_advances(self) -> None:
        """LiveKit's fallback synchroniser reports end times alone."""
        timeline = WordTimeline()
        first = timeline.place("What", None, 0.3)
        second = timeline.place("tradeoff", None, 0.7)
        assert first is not None and second is not None
        assert (first.start_ms, second.start_ms) == (300, 700)


class TestCuttingTheFlattenedTimeline:
    """The bug end to end: what an interruption would have kept without this."""

    def test_a_cut_keeps_one_continuous_prefix(self) -> None:
        guard = FloorGuard()
        generation = guard.take_floor("hiring-manager")
        guard.note_spoken(generation, place_all(GREETING))

        cut = guard.interrupt(at_ms=7000)

        assert cut is not None
        assert cut.heard == "Hi, I'm Maya Chen, on analytics. To"
        assert cut.unheard == "get us started, shipped recently."

    def test_without_flattening_the_cut_interleaves_both_sentences(self) -> None:
        """Kept as the counter-example, so the regression is unmistakable."""
        raw = [SpokenWord(text=t.strip(), start_ms=int(s * 1000)) for t, s, _ in GREETING]
        guard = FloorGuard()
        generation = guard.take_floor("hiring-manager")
        guard.note_spoken(generation, raw)

        cut = guard.interrupt(at_ms=3000)

        assert cut is not None
        # Words from the *second* sentence survive a cut in the first, because
        # their offsets restarted. This is the transcript we must never produce.
        assert "To" in cut.heard.split()
        assert "started," in cut.heard.split()
