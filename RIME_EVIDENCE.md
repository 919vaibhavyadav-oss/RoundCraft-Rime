# Rime evidence

## The hard voice problem

**Interrupting a panel is harder than interrupting a bot.**

RoundCraft is a mock-interview room where two to five AI interviewers share one
voice session. Only one speaks at a time, and each speaks in their own Rime
voice. When the candidate cuts across whoever is speaking, a different
interviewer often takes the floor.

That makes barge-in structurally harder than it is for a single assistant, in
three ways that are properties of the whole application rather than of the
text-to-speech model:

1. **A stale sentence can arrive in the wrong voice.** The interrupted
   interviewer's answer may still be in flight at the language model. If it
   returns after the handover and is spoken, the candidate hears interviewer B
   deliver interviewer A's sentence.
2. **The transcript can record what was never heard.** Every score this product
   gives cites a transcript turn. A sentence the candidate never heard must
   never become evidence about them.
3. **The director can reason about a conversation that did not happen.** The
   next speaker is chosen from the candidate's answer. If selection reads the
   intended answer rather than the part actually delivered before the barge-in,
   it is reacting to audio nobody produced.

## The claim

When the candidate interrupts an interviewer mid-sentence:

- queued Rime audio stops, and no further audio for that turn is played
- the abandoned response is never spoken, in any voice
- the transcript records only the words the candidate actually heard
- the next interviewer is selected from that truncated text
- a barge-in during silence creates no turn at all

## Acceptance test

**Defined before the implementation, per the event rules.**

Run:

```bash
pytest tests/test_floor.py -q
```

The test covers the claim clause by clause:

| Clause | Test |
| --- | --- |
| Only heard words are kept | `test_an_interrupt_keeps_only_what_was_heard` |
| The abandoned response cannot be spoken | `test_the_abandoned_response_can_no_longer_be_spoken` |
| A late result cannot pollute the new turn | `test_a_late_arriving_result_cannot_pollute_the_new_turn` |
| Silence barge-in creates nothing | `test_interrupting_silence_does_nothing` |
| Boundaries: before first word, after last | `test_an_interrupt_before_the_first_word_leaves_nothing_heard`, `test_an_interrupt_after_the_last_word_is_not_a_mid_sentence_cut` |
| A stale release cannot clear a live speaker | `test_a_stale_release_cannot_clear_the_current_speaker` |
| Handovers never reuse a generation | `test_each_handover_is_a_new_generation` |

The mechanism under test is a generation fence in `app/panel/floor.py`. Every
handover of the floor increments a counter; any work tagged with an older
generation fails `accepts()` and is discarded rather than spoken. Word-level
timestamps from Rime's websocket streaming mode are what let the cut be placed
exactly, rather than estimated from elapsed time.

## Procedure for the live run

1. Start an interview and let one interviewer begin a long answer.
2. Introduce a fixed delay into a tool call so a response is genuinely in flight.
3. Interrupt mid-sentence and change one part of the request.
4. Observe: audio stops, a different interviewer answers the revised request,
   and the transcript ends where the interruption happened.
5. Confirm the abandoned sentence appears nowhere in the transcript or the
   evidence ledger.

## Results

**Not yet measured.** The pure-logic acceptance test passes (15 tests). The live
run against LiveKit and Rime is pending the wiring in `app/agent.py`.

To be filled in before submission, with cached and uncached measurements
labelled separately:

- Time from barge-in to audio stopping: _pending_
- Occurrences of a stale sentence being spoken across N interruptions: _pending_
- Transcript/heard-audio agreement across N interruptions: _pending_

## Limitations

- The floor guard is pure logic. It guarantees the application never *chooses*
  to play stale audio; the stop latency itself belongs to LiveKit's playback
  pipeline and is measured separately in the live run above.
- Word timestamps require Rime's websocket streaming mode. With
  `use_websocket=False` the cut point degrades to elapsed-time estimation, which
  we have not characterised.
- Tested with three interviewers. The mechanism is not sensitive to panel size,
  but we have not run five.
