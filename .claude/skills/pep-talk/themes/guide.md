# Pep Talk Guide — Shared Rules for Every Theme

Audience: the model that writes the speech. Read this whole file, then the one theme file you route
to (§2), then the context brief (§4), before drafting. You read no raw notes.

Output: one Markdown speech file at `.pep-talk/speeches/YYYYMMDD_<slug>_<mode>.md`, rendered to a single MP3
by ElevenLabs and played before sleep (`mode: sleep`) or in the morning (`mode: wake`). Length 6–10
minutes depending on the theme.

Related: `themes/<id>.md` (one file per theme), `themes/brief.md` (what the context brief returns),
`context/` (where the listener's own material lives), `.pep-talk/affirmations.md` (the line log, §7).

Paths: `themes/`, `context/`, `examples/` and `scripts/` are inside the skill folder
`.claude/skills/pep-talk/`. `.pep-talk/` is at the project root; it holds every generated file
(speeches, briefs, MP3s, cache) and ignores itself in git.

**This is a practice tool, not therapy and not medical advice.** It rehearses a voice; it does not
treat anything. If you are in crisis, contact your local emergency services.

---

## 1. Purpose and principles

Most people are harsher with themselves than with anyone they care about. Each speech is a daily rep
of the opposite voice: warm, specific, accurate. Different days need different reps, so there are
several themes, each with its own arc and length, and each fits some situations and not others.
Whatever the theme, the frame is offered whole and sincerely. Do not debunk it, hedge it or add
"scientifically speaking". The rules below are the engineering that makes a frame pay off, not a
rebuttal of it.

Principles (all themes):

1. **Fair value, both directions.** Every line must pass the fair-value test (§7): accurate, not
   inflated, not shrunk. A careful listener rejects a line that fails their own accuracy standard,
   not one that is too big to imagine.
2. **The critic is a protector.** Thank it, slow it down, never fight or shame it.
3. **Distance by name.** The voice addresses the listener by first name and "you", never "I":
   "<name>, you…". Lines the listener says themselves in the silence (§4) keep their own wording.
4. **Import, do not invent.** Any future or ideal self is the listener, built from their own
   documented record. Never an admired figure, a hero, a mentor, an alter ego or any separate
   character who gets the credit.
5. **Real facts only.** Past and present facts come from the brief or the prompt. Only an
   explicitly imagined scene (a future, a rehearsal) may imagine.
6. **Fit the theme to the day.** A goal-pumping arc on a raw day after a setback does harm. When no
   theme is named, route with §2.
7. **The voice becomes theirs.** Each speech hands more of the work to the listener's own voice
   (§4). The recording is never needed before acting.

## 2. Themes and routing

| Theme id | File | Length | Best for | Not for | Default mode |
|---|---|---|---|---|---|
| `future-self` | `themes/future-self.md` | ~10 min | A goal weeks to months away; a day that needs direction | A raw day; low expectancy of success; a dated event in the next 7 days | sleep (wake for work goals) |
| `evidence-reel` | `themes/evidence-reel.md` | ~10 min | Self-diminishing or imposter feelings; before sending, pitching, publishing or asking. Week-reel variant: a quiet week where nothing came back | Grief or a fresh rejection; fewer than three real episodes in the brief | wake |
| `compassion` | `themes/compassion.md` | ~8 min | A harsh day; after a rejection, a mistake or a cringe moment; a loud inner critic | Goal pumping; planning; days that are merely flat | sleep |
| `debrief` | `themes/debrief.md` | ~6 min | The evening after a visible act: a talk, an interview, a post, a hard conversation, a first race | Days without a visible act; mornings | sleep |
| `rehearsal` | `themes/rehearsal.md` | ~7 min | One dated event: an interview, a presentation, an exam, a performance, a hard conversation | Vague goals; events with no known details; small reversible acts (a like, a comment); a second rehearsal of the same event | wake (sleep the night before) |
| `values-anchor` | `themes/values-anchor.md` | ~8 min | Comparison with others, a big decision or fork, a wobble about who you are, flatness at work | Doubt about one specific skill (use `evidence-reel`); a fresh rejection | sleep or wake |
| `gratitude-winddown` | `themes/gratitude-winddown.md` | ~6 min | Ordinary nights; rumination before sleep; no topic given | Mornings; a fresh rejection; a day with a visible act (use `debrief`) | sleep only |
| `custom` | — | as asked | A free-text theme request from the user | — | as asked |

**Situation routing table** (check this before the "Best for" column):

| Situation | Theme | Mode |
|---|---|---|
| An interview, presentation, exam, audition or hard conversation within 7 days | `rehearsal` | wake; sleep the night before |
| A season of interviews or applications, no date yet | `evidence-reel` | wake |
| A rejection, a ghosting or a public mistake in the last 72 hours | `compassion` | sleep |
| A hard day: friction with a colleague, harsh feedback, a loud critic | `compassion` | sleep |
| A quiet week: you put things out and nothing came back | `evidence-reel`, week-reel variant | wake |
| Imposter feelings, or about to send, publish, pitch or ask | `evidence-reel` (or `rehearsal` if it is a live event) | wake |
| The evening after a visible act | `debrief` | sleep |
| Comparison with someone else's path; feeling behind | `values-anchor` | either |
| A big decision: an offer, a move, a fork in the road | `values-anchor` | either |
| Flat or bored at work; going through the motions | `values-anchor` | either |
| A goal months away: what am I actually aiming at? | `future-self` | sleep (wake for work goals) |
| An ordinary night; the mind keeps replaying the day | `gratitude-winddown` | sleep |

**Routing rules:**

1. The main session proposes a theme from the topic with this section, then the brief returns.
2. If the user names a theme, use it. The brief never overrides it; mention any mismatch in the top
   HTML comment.
3. Else use the situation routing table, then the "Best for" column.
4. **Tie-break:** a dated event within 7 days → `rehearsal`. A season of interviews with no date →
   `evidence-reel`. A visible act today → `debrief`, not `gratitude-winddown`.
5. **Bad day → gentler.** When the user named no theme and the brief signals a bad day (routing
   note, or day state "fresh setback ≤ 72 h"), prefer the gentler theme: `compassion` > `debrief` >
   `values-anchor` > `evidence-reel` > `future-self`. Low expectancy of success → never
   `future-self`.
6. State the choice in one line in the speech's top HTML comment, in plain words (no clinical
   terms, no sensitive details; speech files may be shared):
   `<!-- theme: compassion — chosen because: rejection yesterday, raw day -->`
7. **Custom request** (free text, e.g. "a speech like a coach at half-time"): follow every shared
   rule in this file, design a custom arc in the spirit of the request with a section table and
   budgets like a theme file, put the arc in the top HTML comment, and set `theme: custom`. If the
   request conflicts with a guardrail (§3, §4), the guardrail wins; say so in the comment.
8. **No topic and no theme:** the brief returns the most live item and the next dated event; route
   from those. Nothing live: `gratitude-winddown` at night, `evidence-reel` in the morning.

## 3. Evidence guardrails (rules, not decoration)

| Rule | Applies to | Why (one line) | Source |
|---|---|---|---|
| Follow an imagined success scene with the **inner obstacle** and an **if-then plan** (WOOP order: Wish, Outcome, Obstacle, Plan) | any theme with a success scene | Pure positive fantasy lowers effort; in one study, job-seeking graduates who fantasised more got fewer offers and lower salaries | Oettingen & Mayer 2002; Oettingen, WOOP |
| Contrast only when **expectancy of success is reasonable** | future-self | Mental contrasting (setting the wish beside the obstacle) energises at reasonable expectancy and tends to disengage at low expectancy | Oettingen, WOOP |
| Write plans as "**When X happens, you do Y**" | all | If-then plans have a medium-to-large effect on goal attainment (meta-analytic d ≈ .65) | Gollwitzer 1999; Gollwitzer & Sheeran 2006 |
| Show the **steps**, not only the finish line | future-self, rehearsal | Picturing the process beats picturing only the outcome | Pham & Taylor 1999 |
| Imagined events include **one hiccup and a calm recovery** | rehearsal, future-self | Coping simulation prepares for the real problem; flawless imagery does not | Taylor, Pham, Rivkin & Armor 1998 |
| **No global self-praise** ("I am brilliant"). Use in-progress, specific, evidence or value lines | all | Global positive statements made low-self-esteem participants feel worse | Wood, Perunovic & Lee 2009 |
| **One "objection allowed" line** before any affirmation loop | all themes with a loop | Low-self-esteem participants did better when they could also consider how a statement was not true (Study 3) | Wood, Perunovic & Lee 2009 |
| Relive **real past episodes of choice or effort**, then name the skill as practised | evidence-reel, future-self (origin), debrief | Mastery experiences are the strongest source of self-efficacy; praising ability rather than effort undermined motivation after setbacks | Bandura 1977, 1997; Mueller & Dweck 1998 |
| Affirm **values**, and a value **unrelated to the threatened domain** | values-anchor, affirmations | Reflecting on core values buffers threat; effects in large replications are smaller and context-dependent, so the claim stays modest | Steele 1988; Cohen & Sherman 2014 |
| **Self-compassion, not self-criticism** | all; core of compassion | Self-compassion raises motivation to improve after failure; it does not breed complacency | Neff 2003; Breines & Chen 2012; Gilbert 2009 |
| Optional: one **interrogative** line ("Will you speak up today? Yes, because…") | wake speeches | Asking primed more goal-directed effort than declaring. The original used first person ("Will I…?"); second person here is untested. One small study: garnish | Senay, Albarracín & Noguchi 2010 |
| **"<name>, you…"** not "I…" | all | Name + second person cuts threat response under social stress, and was linked to less post-event processing (replaying the event afterwards) after a speech | Kross et al. 2014 |
| A **near, ordinary** future self, similar to now | future-self | Feeling connected to a vivid, similar future self supports present action (evidence mostly from saving decisions) | Hershfield et al. 2011 |
| Attention goes **outward**; **one rehearsal per event** | rehearsal | Self-focused attention and anticipatory processing (rehearsing worry beforehand) maintain social fear | Clark & Wells 1995 |
| Bedtime speeches end low-arousal, on something good and settled | all `sleep` | Pre-sleep cognitions affect sleep; worry before bed hurts it | Wood, Joseph, Lloyd & Atkins 2009 |

## 4. Content comes only from the brief

You read no raw notes. Every fact, line and moment comes from the context brief at
`.pep-talk/briefs/YYYYMMDD_<slug>.md`, or from the prompt itself. The brief follows `themes/brief.md`:
routing note and day state, the goal made concrete, real episodes, the event file, what happened,
the critic's lines, reframes, the listener's own lines, values, vetted affirmation candidates,
if-then plans, imagery, the never-mention and do-not-say lists.

**Precedence:** `context/profile.md` wins over every other source; the brief applies it. Its
never-mention and do-not-say lists are binding. A fact that is in neither the brief nor the prompt
does not go in the speech. If the brief says `INSUFFICIENT`, apply the theme file's fallback.

**The listener's own lines come before AI-written ones.** A line the listener wrote themselves has
already worked for them; an AI-written line can be filed by the critic as "the AI said it, not me".
The brief lists any such lines it found (brief §9), verbatim and self-authored, with where they fit
in the arc. Use them there. The spoken form may fix spelling and case only. **Never invent a quote
and attribute it to the listener**, and never present a composed line as their own words.

**Rules for every speech:**

- **One silence where the listener speaks.** Each speech has one beat where the voice invites the
  listener to say a line themselves, out loud or silently, followed by `[[PAUSE 5]]`–`[[PAUSE 8]]`.
  Prefer one of their own lines. Over weeks, more of the lines are theirs.
- **Never a prerequisite.** No speech frames itself as needed before acting. Now and then: "You do
  not need this recording to speak up. You never did."
- **Repeat-wound flag.** If the brief flags the same distressing topic 3+ times in 7 days, write the
  speech, and put the flag in the run report (never in the speech file): suggest talking it through
  with someone they trust or a professional.
- **Childhood and trauma:** never script the details, never childhood imagery, never inner-child
  rescripting. At most a plain label such as "the old alarm", once per speech.
- **Family** appears only as unconditional warmth: never a reward for success, never a witness of
  it ("your children are proud of you" is out).
- **No contempt** for an employer, a team or any person. State a mismatch as fact ("you work best
  with short feedback loops"); the value is building.
- **Future scenes show the role, never a named live company** or a named real person.
- **Numbers:** at most one per episode, in spoken form ("more than two hundred customers"), with the
  verb the source uses ("informed", not "drove", when the notes say informed).

**Content rules for common patterns** (the brief names the pattern; you apply the rule):

- **Comparison:** none with other people, not even favourable. The only reference is the listener's
  own past.
- **Specialness and the wrong scoreboard:** the payoff is never "strangers finally confirmed I am
  special". Pair any outcome (an offer, applause) with the **action scoreboard**: what the listener
  did, repeatedly, to get there. The scoreboard counts acts within their control that reach a person
  or ship a thing (messages sent, work shown, conversations held, sessions trained), not passive
  volume (applications fired off, hours logged).
- **Disowning:** any quality or skill named is **already theirs** ("It was always yours"). Wins are
  banked as earned, at fair value: "Luck can pick the timing. You did the work." / "The tool typed
  it. You decided what it should do, and you checked it."
- **Talent vs effort:** name skills as practised ("you trained this"), never as traits ("you're
  smart"). No talent markers such as exam ranks or "gifted".
- **Identity:** on a wobble about who they are, if the profile records a direction the listener has
  already chosen, restate it; do not reopen the question.
- **No hedges in the script** ("maybe", "kind of", "I think", "a little"). The speech models plain
  speech.

## 5. Markup spec (a parser depends on this — match exactly)

```
---
title: Short Title Here
mode: sleep
theme: future-self
topic: one line on what this talk is about
---
```

- **Front matter** is fenced by `---` lines, one `key: value` per line. A trailing `# comment` is
  stripped. Keys:
  - `title:` — required. Used as the MP3 title tag, the Telegram caption and the PR title.
  - `mode:` — required. `sleep` or `wake`. `sleep` adds a quiet brown-noise bed by default.
  - `theme:` — a theme id from §2, or `custom`. (`style:` is accepted as a legacy alias.)
  - `topic:` — optional. One line, shown in the Telegram caption and the PR body.
  - `voice_id:` — optional. Set it only when the profile or the user asks for a specific
    ElevenLabs voice. Without it the renderer uses the env var `ELEVENLABS_VOICE_ID`, else the
    default premade voice.
- **First line of the body:** the routing HTML comment (§2). HTML comments `<!-- … -->` are dropped
  and never spoken.
- **Section labels:** a line starting with `# ` is a label for humans. Not spoken. One per section:
  `# 1. Arrival` …
- **`[[PAUSE n]]` on its own line** = n seconds of real silence inserted by the pipeline, and a
  segment break. Write `n` as a whole number of seconds. This is the only way to get a pause over
  about 2 seconds.
- Text between two PAUSE markers is **one TTS request** (a chunk). Keep each chunk to **1–4
  sentences of one emotional tone**. Change tone → new chunk.
- **Start every chunk with one audio tag.** Each chunk is a fresh request, so tone does not carry
  across chunks. Within a chunk the tag carries forward. At most one or two extra tags mid-chunk,
  only where delivery shifts. Never stack conflicting tags.
- **Audio tags** are single square brackets (`[softly]`). They are sent to ElevenLabs, steer the
  delivery and are not read aloud. Square brackets are for audio tags only.
- Micro-pauses: ellipses `…`, em dashes `—` and the `[pause]` tag.
- There is no speed slider. Slowness comes from short sentences, ellipses, `[slowly]` and the PAUSE
  markers.
- Never put parentheses, braces, asterisks, bullets or Markdown emphasis in spoken text. They may be
  read aloud.
- **Budget:** characters including tags ≈ 6–7 × spoken words. ElevenLabs bills per character. Every
  speech stays at or under **5,500 characters**; each theme file gives its own range. Check before
  saving with `sh .claude/skills/pep-talk/scripts/pep_talk.sh build <speech> --dry-run`.

**Budgets per theme** (pace ≈ 130 words per minute):

| Theme | Total length | Spoken words | Pauses | Characters |
|---|---|---|---|---|
| `future-self` | ~9–10 min | 750–850 | ≈ 220 s | 4,500–5,500 |
| `evidence-reel` | ~10 min | 760–840 | ≈ 240 s | 4,600–5,500 |
| `compassion` | ~8 min | 600–660 | ≈ 190 s | 3,700–4,500 |
| `values-anchor` | ~8 min | 610–670 | ≈ 190 s | 3,800–4,600 |
| `rehearsal` | ~7 min | 540–590 | ≈ 160 s | 3,400–4,000 |
| `debrief` | ~6 min | 430–480 | ≈ 150 s | 2,700–3,300 |
| `gratitude-winddown` | ~6 min | 430–470 (invite mode ≈ 380) | ≈ 150 s (invite mode ≈ 190 s) | 2,700–3,300 |

**Tag palette.** These come from the ElevenLabs tag menu and are known to work. Write tags exactly
as listed (`[whispering]`, not `[whispers]`).

| Use | Tags | Notes |
|---|---|---|
| **Use** | `[softly]` `[slowly]` `[whispering]` `[pause]` | The default chunk openers |
| **Use** | `[sighing]` | As a release breath after a breathing cue, not as sadness |
| **Use, sparingly** | `[sharp exhale]` | Once per speech at most, e.g. letting the critic's words go |
| **Use, sleep only** | `[sleepy drowsy voice]` | Last one or two chunks of a `sleep` speech |
| **Use, wake only** | `[excited]` `[playful]` `[chuckling]` | Count-up and the closing action. Never in `sleep` |
| **Rare scene cue — max 2 per speech, test once** | `[heartbeat]` `[bell ringing]` `[knocking on door]` `[echoing]` `[keyboard typing]` (a work scene), `[crowd cheering]` / `[applause]` (one wake-mode success moment only) | Not `[rain falling]`: the pipeline already lays a brown-noise bed in sleep mode |
| **Never** | `[angry]` `[menacing]` `[scoffing]` `[bored]` `[weak]` `[tired]` `[witch voice]` `[drunken voice]` `[coughing]` `[sniffling]` `[gasping]` `[panting]` `[singing]` `[voice breaking]` `[laughing]` `[dog barking]` `[engine starting]` `[phone ringing]` `[drum roll]` | Off-tone, comic or distressing |

**Free-form tags** (`[warm]`, `[calm]`, `[gentle, reassuring]`, `[steady]`) are allowed, since the
expressive models accept descriptive tags, but **test once**: render a short dry run with `--mock`,
then a short real render, and listen before relying on one in a full speech. Palette tags first.

## 6. Language rules

- **Second person plus first name.** Open sections with "<name>…". **Use the name often:** at the
  start of every section, in at least one repetition of each affirmation, in the closing action, and
  about every 30–40 seconds of speech in between. Hearing your own name lands. The name comes from
  `name:` in `context/profile.md`; if the profile gives a pronunciation hint and the voice gets the
  name wrong, spell the name in the spoken text the way the hint says. No name in the profile or the
  prompt: write in second person without a name and say so in the run report.
- **Language:** write in the language the profile names (default English). The rules apply in
  spirit; audio tags stay in English.
- **Present tense inside any imagined scene:** "You are standing…", "You walk in…". Future tense
  only inside if-then plans.
- **Concrete over abstract:** light on a desk, the weight of a door, a voice in a room, a calendar
  entry. One sense at a time. No "success", "abundance", "greatness".
- **Every line is understood on first hearing, half awake.** The listener cannot scroll back, so:
  - **Name the referent in the same sentence.** No bare "the yes", "that voice", "it", "she" whose
    meaning sits in an earlier sentence or only in the brief. Bad: "The yes came by email." Good:
    "In this future, the job offer for this role arrives by email."
  - **Say who does what to whom** in any imagined scene. Bad: "Ask them one question." Good: "Now
    you, the Alex of today, ask the future Alex one question." Call the imagined self "the future
    <name>" or "this <name>", never a bare "they".
  - **Anchor every real act in where, when and what**, from the brief: the event, the day, the
    thing done. Bad: "You spoke up when nobody asked." Good: "At the team meeting on Monday the
    twelfth, the manager asked who would present the results. Nobody moved. You put your hand up."
    When an affirmation repeats a past act, speak the full anchor once just before the loop; the
    repeated line may then be short.
  - People and organisations from the past and present may be named only when the brief names them
    and the profile allows names; otherwise use roles ("your manager", "a friend from the running
    club"). Future scenes still show the role, never a named live company (§4).
- **Short arrival in every theme:** at most 70 words and about 20–25 s of pauses. Two breaths, one
  body cue, a short count. A long arrival drags. Words saved go to the concrete content sections.
- **Short sentences.** Most under 12 words. One idea per sentence.
- **No clichés:** "unleash", "limitless", "the universe has your back", "best version of yourself",
  "level up", "manifest your dreams", "you've got this", "crush it".
- **No medical or therapy claims** ("this heals", "this rewires your brain", "cures anxiety"). No
  diagnoses or clinical labels, in the speech or about the listener.
- **No fabricated facts.** Past events, people, numbers, organisations: only from the brief or the
  prompt. If a detail is missing (brief §16 "Gaps"), invite their own memory ("let the room come
  back") or use neutral sensory detail. Never invent an event.
- **No other-dependent acceptance lines** ("you belong in rooms like that", "people are glad you
  came"). They hand the verdict to strangers and guess at their minds.
- The topic comes from the prompt; see §2 when there is none.

## 7. Affirmations, anchor lines and the log

Each theme file says how many lines it uses: a loop of three, two or three evidence lines, or one
anchor line. Rules for every line:

- Process, evidence or value based. Never global praise. Never comparison.
- **Fair-value test:** would the listener sign this as an accurate report? Accurate, not inflated,
  not shrunk. If the critic's objection lands, make the line **more specific, never smaller**.
- The listener's own lines (§4) come first; composed lines only where none fits. Use only lines the
  brief vetted (brief §11) or their own.
- Before any loop, one "objection allowed" line: "Part of you may argue. Let it. Both can sit here."
- At most three repetitions per line.

| Bad (global, inflated, shrunk or hedged) | Good (fair value, specific) |
|---|---|
| "I am a confident, amazing speaker." | "Alex, you are becoming someone who speaks up first." |
| "Everyone will love my work." | "You describe your work at fair value. Nothing more, nothing less." |
| "I am fearless." | "The alarm can ring. You speak anyway. You have done it before." |
| "I deserve the perfect job." | "You are learning to let one rejection be one data point." |
| "I think I'm kind of good at this." | "You built it. You can say what it does." — only with the thing named from the brief |
| "It was nothing special." | "Shrinking it is not modesty. It is just another inaccuracy." |
| "You spoke up when nobody asked." (abstract: what, where, when?) | Anchor once: "At the team meeting on the twelfth, nobody offered to present. You put your hand up." Then loop: "You put your hand up when nobody moved. You did that." |

**After writing the speech:** append every affirmation or anchor line to `.pep-talk/affirmations.md`
in process-form first person ("I am learning to…", "I am becoming…"), because the listener may write
them by hand; the speech itself stays in "you". Mark each line `own words` or `composed`. Skip only
when the theme has none. Create the file if it does not exist.

```
## YYYY-MM-DD — <speech title> (<theme>, <mode>)
- <line 1> (own words | composed)
- <line 2> (own words | composed)
```

The log supports an optional written practice: pick one line, write it by hand about 100 times,
about 10 minutes a day for a week. This comes from a podcast anecdote, not from a study; offer it,
never prescribe it. Pick only lines that passed the fair-value test, ideally the listener's own. If
the handwriting stalls, that is common, not a failure; never escalate it into a "should".

The same-evening log after a visible act is the **4-line log**: Feared / Actual / Learned / I did
that. A speech prompts it; it never replaces it.

## 8. Pre-save checklist

- [ ] Front matter: `title`, `mode`, `theme`, `topic`; `voice_id` only if the profile or the user
      asked for a voice. No other keys.
- [ ] Top HTML comment states the theme and why (§2), in plain words.
- [ ] Section table of the theme file followed: words, pause total, characters in range, never over
      5,500 characters.
- [ ] Every chunk starts with a tag; only palette tags or tested free-form tags; no "never" tag; ≤ 2
      scene cues; no wake-only tag in `sleep`.
- [ ] ≤ 4 sentences per chunk, one tone per chunk.
- [ ] No global praise, hedges, clichés, comparison or other-dependent acceptance lines.
- [ ] Every past fact traceable to the brief or the prompt; nothing on the brief's never-mention or
      do-not-say lists; no live company or real person in a future scene.
- [ ] Every line understood on first hearing: referent named in the same sentence, who-does-what
      explicit in scenes, every real act anchored in where, when and what (§6).
- [ ] The listener's name at every section start, in each affirmation loop and in the closing
      action.
- [ ] Arrival ≤ 70 words, about 20–25 s of pauses.
- [ ] One silence where the listener speaks a line themselves.
- [ ] No quote attributed to the listener that the brief did not mark as their own words.
- [ ] No ideal self other than the listener; family only as unconditional warmth.
- [ ] `sleep` speech ends settled, never near an obstacle; ends on `[[PAUSE 30]]`.
- [ ] Lines appended to `.pep-talk/affirmations.md` with theme, mode and own words / composed.
- [ ] File name: `.pep-talk/speeches/YYYYMMDD_<slug>_<mode>.md`.
- [ ] `sh .claude/skills/pep-talk/scripts/pep_talk.sh build <file> --dry-run` parses and reports words, length and
      characters inside the theme's range.

## 9. Sources

- Quantum jumping, Mind Cafe (Medium): https://medium.com/mind-cafe/how-quantum-jumping-can-help-you-rewire-your-mind-and-your-life-40d499dc1504 — not accessed (HTTP 403); the technique is paraphrased from general knowledge of Burt Goldman's method. A guided-imagery frame, not evidence.
- Quantum jumping overview (search result, not fetched): https://www.vice.com/en/article/tiktok-meditation-quantum-jumping-rich-successful-productivity
- Handwritten affirmations (one line ~100 times, ~10 min a day for a week): a podcast anecdote, no study behind it.
- ElevenLabs, audio tags: https://elevenlabs.io/blog/elevenlabs-audio-tags-list — palette in §5 taken from the ElevenLabs tag menu.
- Bandura (1977), self-efficacy: https://doi.org/10.1037/0033-295X.84.2.191 · Bandura (1997), *Self-Efficacy: The Exercise of Control*, W. H. Freeman (book).
- Breines & Chen (2012), self-compassion and improvement motivation: https://doi.org/10.1177/0146167212445599
- Clark & Wells (1995), a cognitive model of social phobia. In Heimberg et al. (Eds.), *Social Phobia: Diagnosis, Assessment, and Treatment*, Guilford, pp. 69–93 (book chapter).
- Cohen & Sherman (2014), self-affirmation: https://doi.org/10.1146/annurev-psych-010213-115137
- Digdon & Koble (2011), gratitude and other pre-sleep interventions: https://doi.org/10.1111/j.1758-0854.2011.01049.x
- Driskell, Copper & Moran (1994), mental practice meta-analysis: https://doi.org/10.1037/0021-9010.79.4.481
- Gilbert (2009), compassion-focused therapy: https://doi.org/10.1192/apt.bp.107.005264
- Gollwitzer (1999), implementation intentions: https://doi.org/10.1037/0003-066X.54.7.493
- Gollwitzer & Sheeran (2006), meta-analysis: https://doi.org/10.1016/S0065-2601(06)38002-1
- Hershfield et al. (2011), age-progressed renderings of the future self and saving: https://doi.org/10.1509/jmkr.48.SPL.S23
- Kross et al. (2014), distanced self-talk: https://doi.org/10.1037/a0035173
- Mueller & Dweck (1998), praise for intelligence vs effort: https://doi.org/10.1037/0022-3514.75.1.33
- Neff (2003), self-compassion: https://doi.org/10.1080/15298860309032
- Oettingen & Mayer (2002), expectations vs fantasies: https://doi.org/10.1037/0022-3514.83.5.1198
- Oettingen, WOOP / mental contrasting: https://woopmylife.org
- Pham & Taylor (1999), process vs outcome simulation: https://doi.org/10.1177/0146167299025002010
- Seligman, Steen, Park & Peterson (2005), three good things: https://doi.org/10.1037/0003-066X.60.5.410
- Senay, Albarracín & Noguchi (2010), interrogative self-talk: https://doi.org/10.1177/0956797610364751
- Steele (1988), self-affirmation theory: https://doi.org/10.1016/S0065-2601(08)60229-4
- Taylor, Pham, Rivkin & Armor (1998), mental simulation and coping: https://doi.org/10.1037/0003-066X.53.4.429
- Wood, Joseph, Lloyd & Atkins (2009), gratitude and pre-sleep cognitions: https://doi.org/10.1016/j.jpsychores.2008.09.002
- Wood, Perunovic & Lee (2009), positive self-statements: https://doi.org/10.1111/j.1467-9280.2009.02370.x
