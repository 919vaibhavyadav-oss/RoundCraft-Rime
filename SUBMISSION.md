# RoundCraft — DataForge × Rime submission

**Track:** Rime AI
**Team:** LucidAero

| | |
| --- | --- |
| Live application | https://roundcraft-rime-web.onrender.com |
| Access code | `panel-2026` |
| Source repository | https://github.com/919vaibhavyadav-oss/RoundCraft-Rime |
| Demo recording | `Video Project 1.mp4`, included in this archive |
| Evidence | [RIME_EVIDENCE.md](RIME_EVIDENCE.md) |
| Setup and architecture | [README.md](README.md) |

> **The access code gates the endpoint that starts an interview**, because
> starting one spends real credit at Rime, Deepgram and the model provider. It is
> published here so judges can open the live application, and it is a gate rather
> than a secret: it protects a quota, not any data.

---

## What it is

A mock interview room where three interviewers share one voice session. They
hand off to each other, follow up on the numbers the candidate cites, and keep
going when the candidate talks over them. Each speaks in their own Rime voice,
switched per turn on a single connection.

Removing speech does not leave a lesser version of this product. It leaves
nothing: the thing being practised is being interrupted and interrupting.

## The hard voice problem

**Interrupting a panel is harder than interrupting an assistant.** When the
candidate cuts across one interviewer, a *different* one takes over, so three
things can go wrong that no single-voice agent faces:

1. The abandoned sentence can arrive in the new interviewer's voice.
2. The transcript can record words the candidate never heard, and this product
   assesses people from that transcript.
3. The director can choose the next speaker from an answer that was never
   delivered.

`app/panel/floor.py` is a generation fence covering all three. Every handover
increments a counter; anything tagged with an older generation is discarded
rather than spoken.

## Rime configuration used in the demo

| Setting | Value |
| --- | --- |
| Model | `coda` |
| Speakers | `argon` (Hiring Manager), `arcade` (Product Sense), `astra` (Analytics) |
| Language | `eng` |
| Endpoint | `wss://users-ws.rime.ai` (streaming) |
| Audio format | PCM, 16-bit mono, 48000 Hz |
| Transport | Rime websocket streaming, carried over LiveKit WebRTC |
| Aligned transcript | Enabled — needs both `use_websocket=True` and `use_tts_aligned_transcript=True` |

Rime is the only speech output. There is no fallback provider, so if Rime is
unavailable the session surfaces the failure rather than substituting a voice.

## Reproducing the claim

```bash
uv sync --all-extras
uv run pytest tests/test_floor.py tests/test_interruption_journey.py tests/test_benchmarks.py -q
```

127 tests in total; the acceptance test was written before the implementation,
as the brief requires.

Running it live needs two commands and the credentials in `.env.example`:

```bash
uv run python -m app.agent dev        # the panel, waiting for a room
uv run python scripts/serve_web.py    # the candidate's interface
```

Then open <http://localhost:8080>.

## What is not claimed

`RIME_EVIDENCE.md` carries the limitations in full. The short version: the floor
guard is pure logic and guarantees the application never *chooses* to play stale
audio; the stop latency itself belongs to LiveKit's playback pipeline. Word
timings require both settings above. An interruption is final rather than
provisional, which means a cough can end a question — a deliberate trade, since
the alternative is a transcript that is accurate about a conversation which did
not happen.
