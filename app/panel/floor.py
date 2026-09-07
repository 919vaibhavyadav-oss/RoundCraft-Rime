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

    def accepts(self, generation: int) -> bool:
        """Whether work tagged with this generation is still current.

        The fence. A response that fails this check is discarded rather than
        spoken, which is what stops one interviewer's sentence arriving in
        another interviewer's voice.
        """
        return generation == self.generation and self.speaker_id is not None

    def interrupt(self, at_ms: int) -> Interruption | None:
        """Cut the current speaker off, returning what was and was not heard.

        Returns None when nobody holds the floor, so a stray barge-in during
        silence cannot invent an empty turn in the transcript.
        """
        if self.speaker_id is None:
            return None
        heard = [word for word in self._words if word.start_ms < at_ms]
        unheard = [word for word in self._words if word.start_ms >= at_ms]
        interruption = Interruption(
            panelist_id=self.speaker_id,
            generation=self.generation,
            heard=" ".join(word.text for word in heard),
            unheard=" ".join(word.text for word in unheard),
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
