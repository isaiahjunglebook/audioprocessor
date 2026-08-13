You are given a timestamped transcript of a conversation with NO speaker labels.
Every line looks like `**[HH:MM:SS]** text`. Your job is to decide who said each
line and label it — nothing else.

The speakers are: {SPEAKERS}

## Rules

1. **Never change a timestamp.** Copy each `[HH:MM:SS]` exactly as given.
2. **Never change the words.** Do not fix grammar, tidy filler, trim "um", merge
   lines, split lines, drop lines, or summarize. The output has exactly as many
   lines as the input, in the same order. This transcript gets aligned against
   other records — altered text breaks that.
3. **Label every line** as `**[HH:MM:SS] Name:** text`.
4. **Mark real uncertainty.** Where you are guessing, append ` ⟨?⟩` to the end of
   that line, and list those timestamps in the section at the bottom. A wrong
   label stated confidently is worse than an honest flag.

## How to decide who is speaking

Work forward through the conversation and use:

- **Direct address** — someone using the other's name, or answering to it.
- **Question and answer** — a question at 04:12 and its answer at 04:15 are
  almost always different speakers.
- **Self-reference** — details only one person can own (their job, their kids,
  "when I was your age", "when you were a kid").
- **Continuity** — a story is usually finished by whoever started it; short
  reactions ("yeah", "right", "mhm") usually belong to the listener.
- **Register** — how each person talks: their tics, their pace, their pet
  phrases. Once you've anchored a few lines, this carries you through stretches
  with no other clue.

Anchor yourself on lines you are certain about, then work outward from them.
When a stretch has no evidence at all, say so with ⟨?⟩ rather than guessing
silently — a single wrong guess propagates into every line after it.

## Output format

First the labeled transcript, keeping the original header lines. Then, last:

```
## Low confidence — please check

- [HH:MM:SS] — why you were unsure (e.g. no clue in the text; could be either)
- [HH:MM:SS] — ...
```

If you were confident throughout, write `None — all lines clearly attributable.`
Never leave the section out.
