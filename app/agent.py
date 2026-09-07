"""The LiveKit agent: one voice session carrying three interviewers.

This module is deliberately thin. Everything that can be decided without a
network — who speaks next, which voice they speak in, what counts as heard after
an interruption — lives in `app.panel` and is unit-tested there. What remains
here is wiring, which can only be proven by running it.

The shape of a turn:

    candidate speaks
      -> Deepgram transcribes
      -> the director scores the panel and picks one interviewer
      -> Rime's speaker is switched to that interviewer, per turn
      -> the language model writes their question
      -> Rime speaks it, reporting word timestamps as it goes

and on a barge-in, the floor guard fences everything belonging to the abandoned
turn so it can never arrive late in the next interviewer's voice.
"""

import logging

from livekit import agents
from livekit.agents import Agent, AgentSession, RoomInputOptions
from livekit.plugins import deepgram, openai, rime, silero

from app.config import get_settings
from app.panel import director
from app.panel.floor import FloorGuard, SpokenWord
from app.panel.roster import PANEL
from app.panel.voices import DEFAULT_LANG, DEFAULT_MODEL, voice_for

logger = logging.getLogger("roundcraft")

PANEL_BRIEF = "\n".join(f"- {member.name}, {member.role}: {member.brief}" for member in PANEL)

SYSTEM_PROMPT = f"""You are one interviewer on a panel of three conducting a live
mock interview. The panel is:

{PANEL_BRIEF}

You will be told which interviewer you are speaking as, and what this turn is
for. Speak only as that person. Ask one question, in one or two sentences, and
stop. Never narrate the panel, never mention that you are an AI, and never
answer your own question.
"""


class PanelAgent(Agent):
    """Holds the panel state across turns and swaps voice per interviewer."""

    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self.state = director.PanelState()
        self.floor = FloorGuard()

    def open_turn(self, candidate_text: str) -> tuple[director.Decision, int]:
        """Choose the next interviewer and take the floor in their name.

        Returns the decision and the generation that owns this turn. Anything
        produced for an older generation is stale and must not be spoken.
        """
        decision = director.choose_next(self.state, candidate_text)
        generation = self.floor.take_floor(decision.speaker.id)
        logger.info(
            "floor -> %s (gen %s): %s", decision.speaker.name, generation, decision.rationale
        )
        return decision, generation

    def turn_instruction(self, decision: director.Decision) -> str:
        """What this one interviewer is trying to get at, this turn."""
        return (
            f"Speak now as {decision.speaker.name}, the {decision.speaker.role}. "
            f"Objective ({decision.action}): {decision.objective}"
        )

    def commit_turn(self, decision: director.Decision, generation: int) -> None:
        """Record a turn that actually reached the candidate."""
        if not self.floor.accepts(generation):
            # The candidate interrupted. This turn never happened as far as the
            # transcript and the director are concerned.
            logger.info("discarded stale turn for %s (gen %s)", decision.speaker.id, generation)
            return
        self.state = director.record(self.state, decision)
        self.floor.release(generation)

    def note_words(self, generation: int, words: list[SpokenWord]) -> None:
        """Record what Rime reported as played, for the turn holding the floor."""
        self.floor.note_spoken(generation, words)

    def barge_in(self, at_ms: int) -> None:
        """The candidate cut in. Keep only what they actually heard."""
        cut = self.floor.interrupt(at_ms)
        if cut is None:
            return
        logger.info(
            "interrupted %s at %sms; heard %r, dropped %r",
            cut.panelist_id,
            cut.at_ms,
            cut.heard,
            cut.unheard,
        )


def build_session(settings: object | None = None) -> AgentSession:
    """Assemble the voice pipeline.

    Rime is the primary spoken output: every word the candidate hears comes from
    it. The initial speaker is the first interviewer's; it is switched per turn
    through the plugin's update_options.
    """
    config = get_settings()
    del settings
    opening = voice_for(PANEL[0].id)
    return AgentSession(
        stt=deepgram.STT(model=config.deepgram_model),
        llm=openai.LLM(
            model=config.llm_model,
            base_url=config.llm_base_url or None,
            api_key=config.llm_api_key or None,
        ),
        tts=rime.TTS(
            model=config.rime_model or DEFAULT_MODEL,
            speaker=opening.speaker,
            lang=config.rime_lang or DEFAULT_LANG,
            speed_alpha=opening.speed_alpha,
            sample_rate=config.rime_sample_rate,
            use_websocket=config.rime_use_websocket,
        ),
        vad=silero.VAD.load(),
    )


async def entrypoint(ctx: agents.JobContext) -> None:
    config = get_settings()
    missing = config.missing()
    if missing:
        # Fail loudly at startup rather than halfway through an interview.
        raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")

    agent = PanelAgent()
    session = build_session()

    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=RoomInputOptions(),
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
