# RoundCraft on Rime

An AI interview panel that shares one voice session. Two to five interviewers
speak one at a time, each in their own Rime voice, and a silent director decides
who responds to each answer.

**Rime is the primary spoken output.** Every word the candidate hears is
synthesised by Rime.

## The hard voice problem

Interrupting a panel is harder than interrupting a bot: cutting off one
interviewer hands the floor to another, so the abandoned sentence must never
arrive late in the new speaker's voice, and the transcript must record only what
was actually heard. See [RIME_EVIDENCE.md](RIME_EVIDENCE.md) for the claim, the
acceptance test, and the results.

## Rime configuration

The exact configuration used in the demo. Verified against the live catalogue
before submission.

| Setting | Value |
| --- | --- |
| Model | `coda` |
| Speakers | `argon` (Hiring Manager), `arcade` (Product Sense), `astra` (Analytics) |
| Language | `eng` |
| Endpoint | `wss://users-ws.rime.ai` (streaming). The HTTP path `https://users.rime.ai/v1/rime-tts` is not used in the demo |
| Region | Rime global endpoint; LiveKit Cloud project region `India South` |
| Audio format | PCM, 16-bit mono |
| Sample rate | 22050 Hz |
| Transport | Rime websocket streaming (`use_websocket=True`), carried to the browser over LiveKit WebRTC |
| Framework | `livekit-agents` 1.8.0 with `livekit-plugins-rime` 1.8.0 |
| Aligned transcript | Enabled. Requires **both** `use_websocket=True` and `AgentSession(use_tts_aligned_transcript=True)` |

Speaker is set per turn through the plugin's `update_options`, which is what
lets one session carry several interviewers on a single Rime connection.

Rime is the only speech output. There is no fallback provider, so if Rime is
unavailable the session surfaces the failure rather than substituting another
voice. The active provider is therefore unambiguous throughout the demo.

> Placeholders above are pinned in `app/panel/voices.py` and checked against the
> live Rime catalogue by `verify_speakers` before each demo recording.

## Architecture

```
browser ──WebRTC──> LiveKit ──> Deepgram STT
                                     │
                              Panel Director  (scores the panel, picks one speaker)
                                     │
                              language model  (writes that interviewer's question)
                                     │
                                Rime TTS  ──> LiveKit ──> browser
```

The floor guard (`app/panel/floor.py`) sits across the whole loop, fencing work
that belongs to an interrupted turn.

## Third-party services

- **Rime** — text to speech, the primary spoken output
- **LiveKit** — realtime transport, turn handling, barge-in
- **Deepgram** — speech recognition
- An OpenAI-compatible language model for interviewer questions

## Setup

```bash
uv python pin 3.12
uv sync --all-extras
uv run python scripts/setup.py
```

The last command does the rest: it creates `.env`, names every key that is
still blank and where to get it, then tests each service for real. Run it again
after filling anything in. It never prints a key value, so its output is safe to
share.

When everything passes:

```bash
uv run python -m app.agent dev
```

Then open [agents-playground.livekit.io](https://agents-playground.livekit.io),
point it at your LiveKit project, and join the room.

Credentials are read from the environment only. `.env` is gitignored,
`.env.example` holds placeholders alone, and CI fails the build if anything
key-shaped reaches the tree.

## Known limitations and failure behaviour

- If Rime is unavailable the session surfaces the failure rather than silently
  falling back to another voice provider. Any fallback added later will be
  disclosed here and made observable in the demo, per the event rules.
- The floor guard is pure logic covering what the application *chooses* to play;
  playback stop latency belongs to LiveKit and is measured in the evidence file.
- Word-level cut points need two settings, not one: `RIME_USE_WEBSOCKET` so Rime
  sends per-word offsets, and `use_tts_aligned_transcript` so LiveKit delivers
  them. The second defaults to off and fails silently, so the agent logs the
  audio each turn timed and warns on zero.
- Tested with three interviewers.

## Status

The panel runs live. A session dispatches to the worker, the hiring manager
opens in her own Rime voice, the director picks each next interviewer from what
the candidate actually said, and the voice switches per turn on one Rime
connection. 77 tests pass, 43 of them covering the interruption claim.

Three defects found by running it, each fixed and each now covered:

| Found | Cause |
| --- | --- |
| Every turn cost four model calls | Preemptive generation writing questions from partial transcripts |
| Turns timed 0ms of audio | `use_tts_aligned_transcript` defaults off, discarding Rime's alignment |
| A 13.5s greeting timed 5.1s | Rime's offsets restart per synthesis request, one per sentence |

None of them could fail a unit test: the tests were right about the code and
wrong about the world. What caught the last two was a runtime assertion that
reports how many milliseconds of audio each turn actually played, and warns on
zero. It is deliberately still in the code.

Outstanding: the live barge-in measurements in `RIME_EVIDENCE.md`, which need a
recorded session rather than more code.
