# Demo script

Four minutes, one take, covering every clause of the claim in
[RIME_EVIDENCE.md](RIME_EVIDENCE.md) and every item the event brief requires a
demo to show.

Read the **bold** lines aloud. Everything else is what should happen.

---

## Before you press record

- [ ] Agent running: `uv run python -m app.agent dev` — wait for `registered worker`
- [ ] Interface running: `uv run python scripts/serve_web.py`
- [ ] <http://localhost:8080> open, showing the three interviewers
- [ ] A terminal visible somewhere on screen — the log lines are part of the evidence
- [ ] **No `.env` open, no dashboard with a key on screen, no browser tab showing one.**
      The rules name recordings explicitly: an exposed credential is an
      eligibility failure, not a deduction.
- [ ] Headphones on, so the panel's own voice does not reach your microphone

Raise `LOOKUP_DELAY_SECONDS` in `.env` to `6.0` if the interruption window feels
tight to hit by hand. Restart the agent after changing it.

---

## 0:00 — Who this is for

> **"Anyone preparing for a product interview can rehearse questions. Nobody can
> rehearse a panel — three interviewers who talk over you, hand off to each
> other, and follow up on the number you just said. That's what this is."**

> **"Every voice you hear is Rime. There is no fallback provider, so if Rime is
> down this product is silent. Three interviewers, three Rime speakers, one
> connection, switched per turn."**

Point at the three cards: Maya `argon`, Noah `arcade`, Priya `astra`.

*Covers: target user and problem; which speech provider is active.*

---

## 0:30 — The normal flow

Click **Join the panel**. Maya opens, unprompted, in her own voice.

Answer her:

> **"I shipped a proactive recommendation feature for premium card members.
> We rebuilt onboarding around it."**

A different interviewer takes over in a different voice. Point at the italic
line under the cards — the panel says *why* it picked them:

> **"It didn't take turns. It chose Noah because the answer moved onto product
> sense ground, and it says so."**

*Covers: normal end-to-end flow.*

---

## 1:15 — Name a number

This line matters. It must contain **a metric word and a number**, or the
lookup has nothing to find.

> **"We moved retention by four percent with that onboarding experiment."**

Priya takes the floor and the **lookup indicator** appears — she is checking the
benchmark before deciding whether four percent is impressive. It waits on
purpose.

*Covers: conversation continues while a tool runs.*

---

## 1:40 — The stress case

**While Priya is still speaking, or while the lookup is still spinning, talk
straight over her:**

> **"Sorry — I meant activation, not retention."**

Do not wait for a pause. Cutting in mid-clause is the entire point.

*Covers: the deliberate stress case.*

---

## 2:00 — What just happened, on screen

Point at the red-bordered turn:

> **"The words I actually heard are on the left. The struck-through words are
> the rest of her sentence — they were generated, and never spoken. They are not
> in the transcript, because this product scores you on a transcript, and a
> sentence you never heard must never become evidence about you."**

Then the cut marker:

> **"Cut at 4,820 milliseconds. That's not an estimate. Rime reports a timestamp
> per word, so we know exactly which word you heard last."**

Then the discarded lookup:

> **"And the benchmark lookup was still running when I changed the question. It
> came back, and it was thrown away rather than spoken by whoever took over. A
> stale answer must never arrive in a different interviewer's voice."**

*Covers: the hard voice problem, and the result.*

---

## 2:45 — The measurement

Switch to the terminal:

```
interrupted analytics at 4820ms; heard '...', dropped '...'
discarded stale lookup of 'retention...' from gen 4
committed gen 5 after 3609ms of audio: ...
```

> **"Every turn reports how many milliseconds of audio actually played. If that
> ever reads zero, the word timings are gone and the cut point is guesswork — so
> it warns. That check is what caught two real bugs during this build."**

Then run:

```bash
uv run pytest -q
```

> **"Ninety-two tests. Fifty-three of them cover this one claim, and the
> acceptance test was written before the implementation."**

*Covers: the result or measurement; evidence and reproducibility.*

---

## 3:30 — Close

> **"The hard part isn't stopping the audio. It's that interrupting a panel
> means someone else takes over, and everything belonging to the abandoned turn
> — the half-spoken sentence, the tool result still in flight — has to be fenced
> so it can't come back in the new speaker's voice. That's what the generation
> fence in floor.py does, and that's what those tests prove."**

---

## If it goes wrong mid-take

| What you see | What to do |
| --- | --- |
| Nobody speaks after Join | Check the agent terminal says `registered worker`. Rejoin. |
| The lookup says no benchmark | Your line had no metric word. Say "retention", "activation", "conversion", "engagement" or "churn" with a number. |
| `heard ''` on the interruption | You cut in before any audio played. Let them get four words out first. |
| A Windows "Assertion failed" dialog | Abort it, restart the agent, rejoin. Report it — this should be fixed. |

---

## Optional: showing more of the lookup

Only if you have time to spare. Each of these makes `check_benchmark` return a
different band, all with the same interruptible delay:

| Say | Returns |
| --- | --- |
| "retention went up four percent" | typical 2–3% per quarter, strong above 5% |
| "activation is at thirty percent" | typical 30–40% of signups, strong above 55% |
| "conversion sits around two percent" | typical 2–4% of visitors, strong above 8% |
| "our DAU to MAU ratio is twenty percent" | typical near 20%, strong above 35% |
| "churn is about five percent monthly" | typical 4–6% self-serve, strong below 2% |

A metric outside that list is answered honestly — the interviewer says no
benchmark is available and asks how it was measured, rather than inventing a
number.
