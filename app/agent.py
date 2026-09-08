"""The LiveKit agent: one voice session carrying three interviewers.

This module is deliberately thin. Everything that can be decided without a
network -- who speaks next, which voice they speak in, what counts as heard
after an interruption -- lives in `app.panel` and is unit-tested there. What
remains here is wiring, which can only be proven by running it.

The shape of a turn:

    candidate speaks
      -> Deepgram transcribes
      -> the director scores the panel and picks one interviewer
      -> Rime's speaker is switched to that interviewer, per turn
      -> the language model writes their question
      -> Rime speaks it, reporting word timestamps as it goes

and on a barge-in, the floor guard fences everything belonging to the abandoned
turn so it can never arrive late in the next interviewer's voice.

The live session drives the *same* `InterviewSession` object the acceptance
tests drive. That is deliberate: a parallel reimplementation here would mean the
tested behaviour and the shipped behaviour are two different things, which is
the exact shape of the configuration drift that cost us a week on the other
build.
"""

import array
import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, cast

from dotenv import load_dotenv

# LiveKit's worker reads LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET from
# the process environment rather than through our Settings object, and the
# plugins do the same for their own vendor keys. Loading .env here, before the
# CLI starts, is what makes a local run work without exporting six variables by
# hand. In deployment the environment already carries them and this is a no-op.
load_dotenv()

from collections.abc import AsyncGenerator, AsyncIterable  # noqa: E402

from livekit import agents, rtc  # noqa: E402
from livekit.agents import (  # noqa: E402
    NOT_GIVEN,
    Agent,
    AgentSession,
    ChatContext,
    ChatMessage,
    ModelSettings,
    RoomInputOptions,
    RunContext,
    SpeechCreatedEvent,
    StopResponse,
    function_tool,
    llm,
    stt,
)
from livekit.agents.types import FlushSentinel  # noqa: E402
from livekit.agents.voice.io import TimedString  # noqa: E402
from livekit.plugins import deepgram, openai, rime, silero  # noqa: E402

from app.config import get_settings  # noqa: E402

if TYPE_CHECKING:
    from openai.types import ReasoningEffort
from app.panel import director, events  # noqa: E402
from app.panel.background import briefing, condense  # noqa: E402
from app.panel.benchmarks import find_benchmark  # noqa: E402
from app.panel.floor import WordTimeline  # noqa: E402
from app.panel.roster import PANEL, opening_line  # noqa: E402
from app.panel.session import InterviewSession  # noqa: E402
from app.panel.voices import DEFAULT_LANG, DEFAULT_MODEL, voice_for  # noqa: E402

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


def panel_instructions(background: str = "", turn: str = "") -> str:
    """Everything the model is told: who the panel is, who is speaking now, and
    what the candidate said about themselves. Empty parts are left out entirely,
    so a candidate who supplied no background gets no empty heading."""
    parts = (SYSTEM_PROMPT.strip(), briefing(background).strip(), turn.strip())
    return "\n\n".join(part for part in parts if part)


def turn_instruction(decision: director.Decision) -> str:
    """What this one interviewer is trying to get at, this turn."""
    return (
        f"Speak now as {decision.speaker.name}, the {decision.speaker.role}. "
        f"Objective ({decision.action}): {decision.objective}"
    )


class PanelAgent(Agent):
    """Binds the tested panel logic to LiveKit's turn and playback events."""

    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self.interview = InterviewSession()
        # The full text of the reply being generated, and the turn it belongs
        # to. Both, because a turn cut before its generation began would
        # otherwise inherit the previous interviewer's sentence.
        self._intended = ""
        self._intended_generation = -1
        # What the candidate told us about themselves, for this session only.
        # Never written anywhere, never logged: only its length is ever
        # reported, which is enough to know it arrived.
        self._background = ""
        # Set once the job starts. The interview does not depend on it: if the
        # browser is not listening, or publishing fails, nothing here changes.
        self.room: object | None = None

    def announce(self, event: dict[str, object]) -> None:
        """Tell the room what the panel just did, without ever blocking it."""
        try:
            # local_participant is a property that raises before the room is
            # connected rather than being absent, so getattr's default never
            # applies and this has to be a real try.
            publish = self.room.local_participant.publish_data  # type: ignore[union-attr]
        except Exception:
            return
        task = asyncio.create_task(
            publish(json.dumps(event), topic=events.TOPIC, reliable=True)
        )
        # A dropped frame in the UI must never surface as a failed interview.
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    def receive(self, packet: rtc.DataPacket) -> None:
        """Take the candidate's background, if they sent one.

        Bound to the room's data channel in `entrypoint`. The text itself is
        never logged and never leaves this process except to the model that has
        to read it in order to ask about the work: only its length is reported,
        which is enough to know it arrived.
        """
        if packet.topic != events.CANDIDATE_TOPIC:
            return
        try:
            message = json.loads(packet.data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(message, dict) or message.get("type") != "background":
            return
        self._background = condense(str(message.get("text", "")))
        logger.info(
            "candidate background received: %s characters after condensing",
            len(self._background),
        )

    # -- opening -------------------------------------------------------------

    async def on_enter(self) -> None:
        """Open the interview rather than waiting to be spoken to.

        A panel that joins in silence reads as broken. The hiring manager opens,
        in their own voice, and the floor is taken in their name so the very
        first sentence is interruptible on the same terms as every later one.

        Spoken rather than generated. Asking the model for this turn sends a
        request carrying only system messages, and the chat template rejects
        that outright with "No user query found in messages" - there is no
        candidate turn yet for it to answer. A fixed greeting also means every
        take of the demo opens identically, and costs nothing.
        """
        decision = self.interview.panel_opened()
        self._switch_voice(decision.speaker.id)
        logger.info(
            "floor -> %s (gen %s): opening",
            decision.speaker.name,
            self.interview.generation,
        )
        self.announce(events.roster())
        self.announce(
            events.floor_taken(
                decision.speaker.id,
                decision.speaker.name,
                self.interview.generation,
                decision.rationale,
            )
        )
        self.session.say(opening_line())

    # -- the candidate's turn ------------------------------------------------

    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: ChatMessage) -> None:
        """Pick the next interviewer, in their voice, before the model writes.

        By the time this runs, a barge-in has already happened physically:
        LiveKit stopped playback when the candidate started speaking. So the
        first thing to settle is the turn that was cut off, and only then does
        the director get to choose who answers.
        """
        if self.interview.current_speaker is not None:
            self._close_interrupted_turn()

        answer = (new_message.text_content or "").strip()
        if not answer:
            # Deepgram produced nothing usable. Say nothing rather than let the
            # director score an empty string and pick a speaker by tie-break.
            raise StopResponse

        decision = self.interview.candidate_said(answer)
        self._switch_voice(decision.speaker.id)
        logger.info(
            "floor -> %s (gen %s): %s",
            decision.speaker.name,
            self.interview.generation,
            decision.rationale,
        )
        self.announce(events.candidate_said(answer))
        self.announce(
            events.floor_taken(
                decision.speaker.id,
                decision.speaker.name,
                self.interview.generation,
                decision.rationale,
            )
        )
        # Steering goes into the instructions, not into the conversation. A live
        # session had an interviewer read the direction out loud, word for word:
        # "Speak now as Noah Williams, the Product Sense Interviewer. Objective
        # (clarify): ...". A message sitting after the candidate's turn looks
        # enough like something to continue that the model continued it.
        # Instructions are the one place the model treats as addressed to it.
        await self.update_instructions(f"{SYSTEM_PROMPT}\n\n{turn_instruction(decision)}")

    # -- the sentence the interviewer meant to say ---------------------------

    async def llm_node(
        self, chat_ctx: llm.ChatContext, tools: list[llm.Tool], model_settings: ModelSettings
    ) -> AsyncIterable[llm.ChatChunk | str | FlushSentinel]:
        """Keep the whole reply as it is generated, before playback truncates it.

        On an interruption LiveKit shortens the stored message to what was
        actually played, which is right for the transcript and useless for
        saying what was dropped: the two become identical and every cut reports
        that nothing was lost. The model finishes writing long before the audio
        finishes playing, so the complete sentence exists here and nowhere else
        by the time it is needed.
        """
        self._intended = ""
        self._intended_generation = self.interview.generation

        async def kept() -> AsyncGenerator[llm.ChatChunk | str | FlushSentinel, None]:
            stream = Agent.default.llm_node(self, chat_ctx, tools, model_settings)
            resolved = await stream if asyncio.iscoroutine(stream) else stream
            async for chunk in resolved:
                piece = getattr(getattr(chunk, "delta", None), "content", None)
                if isinstance(piece, str):
                    self._intended += piece
                elif isinstance(chunk, str):
                    self._intended += chunk
                yield chunk

        return kept()

    # -- is anything actually arriving ---------------------------------------

    async def stt_node(
        self, audio: AsyncIterable[rtc.AudioFrame], model_settings: ModelSettings
    ) -> AsyncIterable[stt.SpeechEvent | str]:
        """Report the level of the audio reaching recognition, then pass it on.

        Three sessions produced a greeting and then silence, with the speech
        service connected and the microphone track attached. Nothing in the
        system could say whether the frames arriving here carried sound, so two
        fixes were attempted on guesses and neither moved it.

        This measures. A peak near zero means nothing is reaching us and no
        change downstream can help; a healthy peak with no transcript means the
        fault is ours. Cheap enough to leave in: a few dozen samples per frame,
        summarised every couple of seconds.
        """

        async def measured() -> AsyncGenerator[rtc.AudioFrame, None]:
            peak = 0
            frames = 0
            rate = 0
            last = time.monotonic()
            async for frame in audio:
                frames += 1
                rate = frame.sample_rate
                samples = array.array("h")
                samples.frombytes(bytes(frame.data))
                if samples:
                    # Every sixteenth sample is plenty to know whether a person
                    # is speaking, and keeps this off the critical path.
                    peak = max(peak, max(abs(v) for v in samples[::16]))
                now = time.monotonic()
                if now - last >= 2.0:
                    logger.info(
                        "mic: peak %s/32768 over %s frames at %sHz%s",
                        peak,
                        frames,
                        rate,
                        "  <- SILENT, nothing is reaching the agent" if peak < 200 else "",
                    )
                    peak = frames = 0
                    last = now
                yield frame

        return Agent.default.stt_node(self, measured(), model_settings)

    # -- what the candidate actually heard -----------------------------------

    async def transcription_node(
        self, text: AsyncIterable[str | TimedString], model_settings: ModelSettings
    ) -> AsyncGenerator[str | TimedString, None]:
        """Record each word at the moment it reaches the candidate.

        This node sits after audio synchronisation, so a word arrives here only
        once it has been played. That is what makes the transcript a record of
        what was heard rather than what was generated: when the candidate cuts
        in, this stream simply stops, and the words that never arrived are
        exactly the words that were never spoken.
        """
        generation = self.interview.generation
        # One timeline per turn: Rime's offsets restart at every sentence, and
        # this is what puts them back on a single clock.
        timeline = WordTimeline()
        async for delta in text:
            if isinstance(delta, TimedString):
                word = timeline.place(str(delta), delta.start_time, delta.end_time)
                if word is not None:
                    self.interview.interviewer_spoke(generation, [word])
            yield delta

    # -- work the candidate can interrupt ------------------------------------

    @function_tool
    async def check_benchmark(self, context: RunContext[None], claim: str) -> str:
        """Look up the industry benchmark for a metric the candidate just cited.

        Call this ONLY when the candidate has stated a number for one of these
        metrics: retention, activation, conversion, engagement, churn. Do not
        call it for a product or feature description.

        Pass the metric claim itself, in their words, naming the metric: for
        example "retention went up four percent", not "our recommendation
        engine". A test keeps this list in step with the benchmark data.
        """
        # Captured before the wait, so a result arriving after a handover is
        # judged against the turn that asked for it rather than whichever turn
        # happens to be running by the time it returns.
        generation = self.interview.generation
        logger.info("lookup started for %r at gen %s", claim, generation)
        self.announce(events.lookup_started(claim, generation))

        # A fixed delay, as the brief's proof procedure requires, so there is a
        # real window in which the candidate can cut across work in flight.
        await asyncio.sleep(get_settings().lookup_delay_seconds)

        if not self.interview.floor.accepts(generation):
            # The candidate interrupted while this ran. The answer belongs to a
            # question they abandoned, so it must not be spoken as current, and
            # must not reach the model as context either.
            logger.info("discarded stale lookup of %r from gen %s", claim, generation)
            self.announce(events.lookup_discarded(claim, generation))
            raise StopResponse

        benchmark = find_benchmark(claim)
        if benchmark is None:
            logger.info("no benchmark for %r", claim)
            return (
                "No benchmark is available for that metric. Say so plainly and ask "
                "how they measured it instead of quoting a number."
            )
        logger.info("lookup returned %s for gen %s", benchmark.metric, generation)
        self.announce(events.lookup_returned(benchmark.metric, generation))
        return benchmark.spoken()

    # -- committing a turn ---------------------------------------------------

    def watch_speech(self, event: SpeechCreatedEvent) -> None:
        """Commit an interviewer's turn once it has finished playing out.

        Bound to the session's `speech_created` event in `entrypoint`. The
        generation is captured now, while this speech is the current turn, so a
        handle that completes late is judged against the turn it belonged to
        rather than against whatever is happening by then.
        """
        generation = self.interview.generation

        def committed(done: object) -> None:
            handle = done
            spoken = " ".join(
                item.text_content
                for item in getattr(handle, "chat_items", [])
                if isinstance(item, ChatMessage) and item.role == "assistant" and item.text_content
            ).strip()
            if getattr(handle, "interrupted", False):
                # The candidate cut across this. Truncate here rather than
                # later, because this is the only place the sentence the
                # interviewer *meant* to say is still available, and the words
                # that never played are otherwise unrepresentable: the timing
                # stream only ever reports a word once it has been heard.
                if self.interview.floor.accepts(generation):
                    # self._intended is the untruncated reply; `spoken` has
                    # already been shortened to what was played. Only use it if
                    # it belongs to this turn: a live session cut Priya off
                    # before her generation started and reported Noah's sentence
                    # as the words she never got to say, which is precisely the
                    # attribution this product exists to prevent.
                    mine = self._intended_generation == generation
                    self._close_interrupted_turn(
                        intended=(self._intended if mine else "") or spoken
                    )
                else:
                    logger.debug("speech handle discarded at gen %s", generation)
                return

            heard_ms = self.interview.heard_ms()
            if spoken and self.interview.interviewer_finished(generation, spoken):
                logger.info(
                    "committed gen %s after %sms of audio: %s", generation, heard_ms, spoken
                )
                self.announce(
                    events.turn_committed(
                        self.interview.transcript[-1].speaker_id, generation, spoken, heard_ms
                    )
                )
                if heard_ms == 0:
                    # Rime reported no word timings, so an interruption during
                    # this turn could not have been placed. Worth knowing.
                    logger.warning(
                        "no word timings for gen %s; needs RIME_USE_WEBSOCKET and "
                        "use_tts_aligned_transcript",
                        generation,
                    )

        event.speech_handle.add_done_callback(committed)

    # -- internals -----------------------------------------------------------

    def _close_interrupted_turn(self, intended: str | None = None) -> None:
        """Truncate the turn in progress to the words that were played."""
        # Every word this turn played arrived through `transcription_node`, so
        # cutting just past the last of them keeps exactly what was heard. There
        # is nothing to estimate here: the stream itself is the evidence.
        cut = self.interview.candidate_interrupted(
            at_ms=self.interview.heard_ms() + 1, intended=intended
        )
        if cut is None:
            return
        logger.info(
            "interrupted %s at %sms; heard %r, dropped %r",
            cut.panelist_id,
            cut.at_ms,
            cut.heard,
            cut.unheard,
        )
        self.announce(events.turn_interrupted(cut))

    def _switch_voice(self, panelist_id: str) -> None:
        """Point Rime at this interviewer's voice for the turn about to be spoken.

        Rime takes the speaker as a per-request parameter, so a handover costs
        one option update rather than a second synthesiser. This is the whole
        reason a panel can share a single voice session.
        """
        tts = self.session.tts
        if not isinstance(tts, rime.TTS):
            # Only Rime takes the speaker per request. Anything else keeps the
            # voice it was built with rather than failing the turn.
            return
        profile = voice_for(panelist_id)
        tts.update_options(speaker=profile.speaker, speed_alpha=profile.speed_alpha)


def build_session(settings: object | None = None) -> AgentSession[None]:
    """Assemble the voice pipeline.

    Rime is the primary spoken output: every word the candidate hears comes from
    it. The initial speaker is the first interviewer's; it is switched per turn
    through the plugin's update_options.
    """
    config = get_settings()
    del settings
    opening = voice_for(PANEL[0].id)
    return AgentSession[None](
        stt=deepgram.STT(model=config.deepgram_model, sample_rate=config.deepgram_sample_rate),
        llm=openai.LLM(
            model=config.llm_model,
            base_url=config.llm_base_url or NOT_GIVEN,
            api_key=config.llm_api_key or NOT_GIVEN,
            max_completion_tokens=config.llm_max_tokens,
            reasoning_effort=cast("ReasoningEffort", config.llm_reasoning_effort or None),
        ),
        tts=rime.TTS(
            model=config.rime_model or DEFAULT_MODEL,
            speaker=opening.speaker,
            lang=config.rime_lang or DEFAULT_LANG,
            speed_alpha=opening.speed_alpha,
            sample_rate=config.rime_sample_rate,
            # Word-level alignment is only available on the websocket transport,
            # and word-level alignment is what places an interruption exactly.
            use_websocket=config.rime_use_websocket,
        ),
        vad=silero.VAD.load(),
        # Without this, transcription_node is handed plain strings and Rime's
        # word alignment is discarded before it ever reaches us, so an
        # interruption has no timestamps to be placed against. It is the flag
        # the entire interruption claim rests on.
        use_tts_aligned_transcript=True,
        # Preemptive generation fires an LLM call on every partial transcript
        # and discards it if the candidate keeps talking - up to three per turn
        # by default. A first live session showed it generating full interview
        # questions from fragments like "on MX", so each answer cost four calls
        # rather than one. We are on a free tier, and an interviewer who thinks
        # for a moment before speaking is not a defect in this product.
        turn_handling={
            "preemptive_generation": {"enabled": False},
            # Voice activity rather than the adaptive detector. The adaptive one
            # streams microphone audio to a remote gateway every 100ms, which
            # means another resampler running beside silero's, and soxr aborts
            # the process when two of them start together. It also puts a
            # network round trip inside the barge-in path, which is the one
            # path in this product that must not wait on anything.
            #
            # resume_false_interruption defaults to true, and a live session
            # showed exactly what that means here: the candidate cut in, the
            # panel stopped, decided the interruption was not real, and finished
            # the sentence over them. It then counted as fully heard, so nothing
            # was recorded as dropped and the transcript was right about a
            # conversation that should not have happened.
            #
            # Resuming is the abandoned turn re-entering the conversation, which
            # is the failure this whole build exists to prevent. An interruption
            # here ends the turn.
            #
            # min_duration is the tail of the candidate's own answer, not their
            # barge-in. At 0.25s a live session killed two turns 94ms and 399ms
            # after they began, before either had played a word: the candidate
            # was still finishing a sentence when the panel took the floor, and
            # that trailing speech read as an interruption. 0.4s is long enough
            # to be someone deliberately cutting in and short enough that a real
            # barge-in still lands within a word or two.
            "interruption": {
                "mode": "vad",
                "resume_false_interruption": False,
                "min_duration": 0.4,
            },
        },
    )


async def entrypoint(ctx: agents.JobContext) -> None:
    config = get_settings()
    missing = config.missing()
    if missing:
        # Fail loudly at startup rather than halfway through an interview.
        raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")

    if not config.rime_use_websocket:
        logger.warning(
            "RIME_USE_WEBSOCKET is off, so words carry no start times and an "
            "interruption is placed by playback pacing alone."
        )

    agent = PanelAgent()
    agent.room = ctx.room
    # The candidate's background arrives over the data channel rather than in
    # the join token, so it never appears in a URL, a log line or a JWT that
    # outlives the session.
    ctx.room.on("data_received", agent.receive)
    session = build_session()
    session.on("speech_created", agent.watch_speech)

    await session.start(
        room=ctx.room,
        agent=agent,
        # The room's input rate is its own setting, not one it takes from the
        # speech recogniser. Left at its 24kHz default while Deepgram was told
        # 48000, it resampled the browser's audio down and then labelled it at
        # double its real rate, and Deepgram returned nothing at all for a whole
        # session. Voice activity kept firing, because it reads energy on a
        # separate path, so the room looked alive while hearing nothing.
        #
        # Setting both to what the browser already publishes means no resampling
        # and no mislabelling.
        room_input_options=RoomInputOptions(audio_sample_rate=config.deepgram_sample_rate),
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
