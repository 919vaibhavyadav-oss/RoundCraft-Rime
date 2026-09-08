"""Who holds the floor, and what the candidate actually heard.

Interrupting a single assistant is a solved problem: stop playback and move on.
Interrupting a *panel* is harder, and the difficulty is real rather than
manufactured.

When a candidate cuts across interviewer A, three things can go wrong that no
single-voice agent has to worry about:

1.  A's answer may still be in flight at the language model. If it arrives after
    the interrupt and is spoken, it lands in whatever voice now holds the floor —
    so the candidate hears interviewer B say interviewer A's sentence.
2.  The transcript records what was *generated*, not what was *heard*. Every
    score this product gives cites the transcript, so a sentence the candidate
    never heard must never become evidence against them.
3.  The next speaker is chosen from the candidate's answer. If the director reads
    the whole intended answer rather than the part that was actually delivered
    before the barge-in, it reasons about a conversation that did not happen.

This module is the guard for all three, and it is deliberately pure: no LiveKit,
no Rime, no network. That is what makes the acceptance test runnable from a
command rather than by listening.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SpokenWord:
    """One word Rime reported as played, with its offset into the utterance.

    Word-level timestamps come from Rime's websocket streaming mode. They are
    what let us say precisely where the candidate cut in, rather than guessing
    from elapsed time.
    """

    text: str
    start_ms: int


@dataclass(frozen=True, slots=True)
class Interruption:
    """What one barge-in actually did."""

    panelist_id: str
    generation: int
    heard: str
    unheard: str
    at_ms: int

    @property
    def cut_mid_sentence(self) -> bool:
        return bool(self.unheard)


@dataclass
class FloorGuard:
    """Tracks the current speaker and fences work belonging to older turns.

    A generation is bumped every time the floor changes hands. Anything produced
    for an older generation is stale by definition, so `accepts` is the single
    check every late-arriving result has to pass before it can be spoken or
    recorded.
    """

    generation: int = 0
    speaker_id: str | None = None
    _words: list[SpokenWord] = field(default_factory=list)

    def take_floor(self, panelist_id: str) -> int:
        """Hand the floor to an interviewer and return the generation it owns."""
        self.generation += 1
        self.speaker_id = panelist_id
        self._words = []
        return self.generation

    def note_spoken(self, generation: int, words: list[SpokenWord]) -> None:
        """Record what Rime reported as played for the turn holding the floor."""
        if not self.accepts(generation):
            return
        self._words.extend(words)

    @property
    def heard_ms(self) -> int:
        """Offset of the last word reported as played, or 0 if none has been.

        The live agent cuts an interruption here rather than measuring elapsed
        time, because a word only reaches it once it has actually been played.
        Whatever arrived is what was heard, by construction.
        """
        return max((word.start_ms for word in self._words), default=0)

    def accepts(self, generation: int) -> bool:
        """Whether work tagged with this generation is still current.

        The fence. A response that fails this check is discarded rather than
        spoken, which is what stops one interviewer's sentence arriving in
        another interviewer's voice.
        """
        return generation == self.generation and self.speaker_id is not None

    def interrupt(self, at_ms: int, intended: str | None = None) -> Interruption | None:
        """Cut the current speaker off, returning what was and was not heard.

        Returns None when nobody holds the floor, so a stray barge-in during
        silence cannot invent an empty turn in the transcript.

        `intended` is the full sentence the interviewer meant to say. It is
        needed because the words that were never played never reach us: this
        guard only ever learns about a word once it has been heard. Without it
        the abandoned half is not merely unknown, it is unrepresentable, and we
        could assert that nothing was dropped while a sentence was visibly cut
        off mid-clause.
        """
        if self.speaker_id is None:
            return None
        heard = [word for word in self._words if word.start_ms < at_ms]
        heard_text = " ".join(word.text for word in heard)
        interruption = Interruption(
            panelist_id=self.speaker_id,
            generation=self.generation,
            heard=heard_text,
            unheard=_remainder(intended, heard_text)
            if intended
            else " ".join(word.text for word in self._words if word.start_ms >= at_ms),
            at_ms=at_ms,
        )
        # Bumping here is what makes the in-flight response stale: whatever the
        # model returns for the old generation can no longer pass `accepts`.
        self.generation += 1
        self.speaker_id = None
        self._words = []
        return interruption

    def release(self, generation: int) -> None:
        """Give up the floor after speaking normally, without a barge-in."""
        if generation == self.generation:
            self.speaker_id = None
            self._words = []


def word_from_timing(text: str, start_s: object, end_s: object) -> SpokenWord | None:
    """Turn one timestamped word from Rime into a `SpokenWord`, or None if untimed.

    Rime's websocket mode reports a real start time per word. LiveKit's fallback
    synchroniser, used when alignment is unavailable, reports only an end time
    paced against playback. Either places the cut far better than elapsed-time
    estimation does, so we take whichever is offered and prefer the start.

    A word with no timing at all is dropped rather than recorded at zero, which
    would otherwise make every untimed word look like it was heard first. The
    timestamps are typed as `object` because that is what arrives: each vendor
    has its own sentinel for absent, and guessing which one is how a missing
    timestamp quietly becomes a word at 0ms.
    """
    stamp = start_s if isinstance(start_s, (int, float)) else end_s
    if not isinstance(stamp, (int, float)):
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    return SpokenWord(text=cleaned, start_ms=max(0, int(stamp * 1000)))


@dataclass
class WordTimeline:
    """Flattens per-request word offsets onto one timeline for a whole turn.

    Rime reports each word's offset relative to the synthesis request it came
    from, and LiveKit issues one request per sentence. So the clock restarts at
    zero at every sentence boundary: in a measured 13.5s greeting, the last word
    claimed to start at 3.4s.

    Left alone that does not merely misplace the cut, it scrambles it. `interrupt`
    keeps every word whose offset is below the cut, so a cut at three seconds
    would keep the opening of *every* sentence and drop the end of each, and the
    transcript would read as several interleaved half-sentences that the
    candidate never heard in that order.

    Within one request the words are contiguous - each starts exactly where the
    last one ended - so a word that starts *before* the current request has
    ended can only belong to a new request. Everything after that point is
    shifted past where the previous request's audio finished.
    """

    _base_ms: int = 0
    _request_end_ms: int = 0

    def place(self, text: str, start_s: object, end_s: object) -> SpokenWord | None:
        """Position one word on the turn's timeline, or None if it carries no timing."""
        word = word_from_timing(text, start_s, end_s)
        if word is None:
            return None
        if word.start_ms < self._request_end_ms:
            # It cannot start before the request it would belong to has ended,
            # so the clock has restarted. Shift it past the previous request.
            self._base_ms += self._request_end_ms
            self._request_end_ms = 0
        end_ms = int(end_s * 1000) if isinstance(end_s, (int, float)) else word.start_ms
        self._request_end_ms = max(self._request_end_ms, end_ms, word.start_ms)
        return SpokenWord(text=word.text, start_ms=self._base_ms + word.start_ms)


def _remainder(intended: str, heard: str) -> str:
    """The part of a sentence that was never played.

    Compared word by word rather than by character offset, because the words
    reported by the speech service carry their own spacing and punctuation and
    will not line up with a slice of the original string.
    """
    spoken = len(heard.split())
    return " ".join(intended.split()[spoken:])
