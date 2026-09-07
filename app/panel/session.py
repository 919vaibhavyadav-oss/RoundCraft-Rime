"""One interview, as pure state.

The floor guard knows who is speaking and what was heard. The director knows who
should speak next. This ties them together into the thing the acceptance test
actually asserts about: a transcript that matches what happened in the room.

Nothing here touches LiveKit or Rime. That is the point — the claim in
RIME_EVIDENCE.md can then be proven by running the suite rather than by
listening to a recording and taking someone's word for it.
"""

from dataclasses import dataclass, field

from app.panel import director
from app.panel.floor import FloorGuard, Interruption, SpokenWord
from app.panel.roster import PANEL, Interviewer


@dataclass(frozen=True, slots=True)
class Turn:
    """One thing that was said, as the candidate experienced it."""

    speaker_id: str
    text: str
    interrupted: bool = False

    @property
    def by_candidate(self) -> bool:
        return self.speaker_id == "candidate"


@dataclass
class InterviewSession:
    """The live state of one interview.

    A turn is only written to the transcript once it has actually reached the
    candidate. An interviewer cut off mid-sentence contributes the words that
    were heard and nothing more, because every score this product gives cites a
    transcript turn, and a sentence nobody heard must never become evidence.
    """

    state: director.PanelState = field(default_factory=director.PanelState)
    floor: FloorGuard = field(default_factory=FloorGuard)
    transcript: list[Turn] = field(default_factory=list)
    _open: director.Decision | None = None
    _generation: int = 0

    # -- opening the room ----------------------------------------------------

    def panel_opened(self) -> director.Decision:
        """Seat the hiring manager to open, before the candidate has said anything.

        The director scores interviewers against what the candidate just said,
        which is nothing yet. Rather than let an empty string pick the opener by
        tie-break, the person who runs the room opens it, as they would in a real
        panel. Every turn after this one is chosen by the director as normal.
        """
        opener = PANEL[0]
        decision = director.Decision(
            speaker=opener,
            action="open",
            objective=(
                "Welcome the candidate, introduce the panel in one sentence, and "
                "ask them to walk through a product they shipped."
            ),
            rationale="the hiring manager opens the interview",
        )
        self._open = decision
        self._generation = self.floor.take_floor(opener.id)
        return decision

    # -- the candidate's side ------------------------------------------------

    def candidate_said(self, text: str) -> director.Decision:
        """Record a candidate answer and hand the floor to whoever should reply."""
        self.transcript.append(Turn(speaker_id="candidate", text=text))
        decision = director.choose_next(self.state, text)
        self._open = decision
        self._generation = self.floor.take_floor(decision.speaker.id)
        return decision

    def candidate_interrupted(self, at_ms: int) -> Interruption | None:
        """The candidate cut in. Keep only what they heard, and reopen the floor.

        The interrupted interviewer still counts as having spoken, because they
        did — the candidate heard part of it and is responding to that. What
        they do not get is credit for the part that never played.
        """
        cut = self.floor.interrupt(at_ms)
        if cut is None or self._open is None:
            self._open = None
            return cut
        if cut.heard:
            self.transcript.append(
                Turn(speaker_id=cut.panelist_id, text=cut.heard, interrupted=True)
            )
            self.state = director.record(self.state, self._open)
        self._open = None
        return cut

    # -- the panel's side ----------------------------------------------------

    def interviewer_spoke(self, generation: int, words: list[SpokenWord]) -> None:
        """Report what Rime played, so an interruption can be placed exactly."""
        self.floor.note_spoken(generation, words)

    def heard_ms(self) -> int:
        """How far into the current turn the candidate has actually heard."""
        return self.floor.heard_ms

    def interviewer_finished(self, generation: int, text: str) -> bool:
        """Commit a turn that reached the candidate whole. Returns whether it counted.

        A stale generation means the candidate interrupted while this answer was
        still in flight. It is dropped rather than spoken, which is what stops
        one interviewer's sentence arriving in another interviewer's voice.
        """
        if not self.floor.accepts(generation) or self._open is None:
            return False
        self.transcript.append(Turn(speaker_id=self._open.speaker.id, text=text))
        self.state = director.record(self.state, self._open)
        self.floor.release(generation)
        self._open = None
        return True

    # -- what the room shows -------------------------------------------------

    @property
    def current_speaker(self) -> Interviewer | None:
        return self._open.speaker if self._open else None

    @property
    def generation(self) -> int:
        return self._generation

    def heard_text(self) -> str:
        """The transcript as the candidate experienced it, newest last."""
        return "\n".join(f"{turn.speaker_id}: {turn.text}" for turn in self.transcript)
