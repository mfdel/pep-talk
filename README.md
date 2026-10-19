# Pep Talk

**Your own notes, turned into a 6–10 minute spoken pep talk that knows your life, delivered to your phone.**

`/pep-talk` is a [Claude Code](https://claude.com/claude-code) skill. Give it a topic ("interview
on Thursday", "rough day", "can't switch off"). It reads the context you point it at (journal,
wins log, goals, CV, meeting notes), writes a guided speech in one of seven evidence-based
themes, voices it with [ElevenLabs](https://elevenlabs.io), and sends the MP3 to your Telegram
and to a GitHub pull request.

```
/pep-talk interview with the platform team on Thursday at 10
/pep-talk compassion the launch slipped and I took it personally
/pep-talk gratitude-winddown
```

[![tests](https://github.com/mfdel/pep-talk/actions/workflows/tests.yml/badge.svg)](https://github.com/mfdel/pep-talk/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![deps](https://img.shields.io/badge/dependencies-stdlib%20%2B%20ffmpeg-lightgrey)
![license](https://img.shields.io/badge/license-MIT-green)

---

## Why it's different

Generic motivational audio fails on two counts. It doesn't know you, and much of it uses lines
that research shows can backfire ("I am brilliant, I am unstoppable").

- **It's built from your life.** Real episodes, real dates, your own words. The talk sounds like
  someone who was there, because it only uses what your notes say happened.
- **It follows the evidence.** Every theme obeys a set of guardrails from psychology research:
  if-then plans (Gollwitzer), mental contrasting after a success scene (Oettingen's WOOP), mastery
  episodes over talent praise (Bandura; Mueller & Dweck), no global self-praise (Wood et al.),
  self-compassion over self-criticism (Neff; Breines & Chen), and calm, low-arousal endings
  before sleep. Citations are in [`themes/guide.md`](themes/guide.md).
- **It sounds produced.** ElevenLabs audio tags steer delivery (`[softly]`, `[slowly]`,
  `[whispering]`). Timed pauses give you room to breathe, a quiet brown-noise bed plays under
  bedtime talks, and the audio is loudness-normalised.
- **It reaches you.** The talk lands in a Telegram chat with your own bot, so you build a library
  of past talks you can replay. A pull request archives the transcript and the MP3 in your private
  repo.

## How it works

```
 /pep-talk <topic>
        │
        ▼
 ┌──────────────┐   reads    ┌──────────────────────────────────────────┐
 │ brief agent  │ ─────────▶ │ your context: profile, notes, journal,   │
 │ (subagent)   │            │ wins log, CV, other repos, Notion, Drive │
 └──────┬───────┘            └──────────────────────────────────────────┘
        │ a short, cited brief (only what's relevant to today's topic)
        ▼
 ┌──────────────┐   theme rules + evidence guardrails (themes/)
 │ speech writer│ ─────────▶ speeches/20261019_interview_wake.md
 └──────┬───────┘
        ▼
 scripts/pep_talk.sh build   → budget check → ElevenLabs, one request per segment → ffmpeg mix
        ▼
 out/20261019_interview_wake.mp3 ──▶ Telegram bot chat
                                 └─▶ GitHub pull request (play link + transcript)
```

The main session never reads your raw notes. One brief agent reads them and hands back only what
today's talk needs, with a source for every fact. That keeps the speech grounded and keeps your
private files out of the main context.

## Themes

| Theme | Length | Default mode | Use it when |
|---|---|---|---|
| `rehearsal` | ~7 min | wake (sleep the night before) | One dated event is coming: an interview, a presentation, an exam, a hard conversation. You walk through it once, including one hiccup and a calm recovery. |
| `evidence-reel` | ~10 min | wake | Imposter feelings, or you're about to send, pitch or publish. It replays real moments where you already did the thing. A week-reel variant covers a quiet week where nothing came back. |
| `compassion` | ~8 min | sleep | A harsh day, a rejection, a mistake. It names the critic, then answers it in a compassionate voice. |
| `debrief` | ~6 min | sleep | The evening after a visible act. It banks the rep before your brain files it as a failure. |
| `values-anchor` | ~8 min | either | Comparing yourself with others, facing a big decision, or feeling flat at work. It brings you back to what you stand for. |
| `future-self` | ~10 min | sleep | A goal weeks or months away. A near, ordinary future you, then the obstacle and the plan. |
| `gratitude-winddown` | ~6 min | sleep only | Ordinary nights, or a mind that keeps replaying the day. Three good things and one thing you did. |
| `custom "<request>"` | as asked | as asked | Anything else, described in your own words. |

Without a theme, the skill picks one from the topic using the routing table in
[`themes/guide.md`](themes/guide.md). **`sleep`** talks slow down and end drowsy, over a quiet noise
bed. **`wake`** talks end on one concrete action for today.

---

## Quick start (5 minutes)

**You need:** [Claude Code](https://claude.com/claude-code), Python 3.10+, `ffmpeg` (installed
for you on Linux; on a Mac, `brew install ffmpeg`), and an ElevenLabs API key.

1. **Get your own copy.** Click **Use this template**, then **Create a new repository**, and set it
   to **Private**. Your copy will hold personal talks. Then clone it:

   ```sh
   git clone https://github.com/<you>/pep-talk.git && cd pep-talk
   ```

2. **Add your keys.**

   ```sh
   cp .env.example .env      # gitignored
   ```

   Set `ELEVENLABS_API_KEY`. Create one at
   [elevenlabs.io → API keys](https://elevenlabs.io/app/settings/api-keys) with Text to Speech
   permission. Optionally set `ELEVENLABS_VOICE_ID` to any voice from the
   [voice library](https://elevenlabs.io/app/voice-library); the default is the premade voice "George".

3. **Tell it who you are.**

   ```sh
   cp context/profile.example.md context/profile.md   # gitignored; 10 minutes is enough
   ```

4. **Check the setup, then try it for free.**

   ```sh
   sh scripts/pep_talk.sh doctor                                 # ✓ / ✗ per dependency, with fixes
   sh scripts/pep_talk.sh build examples/sample.md --mock        # full pipeline, placeholder audio, no credits
   ```

5. **Run it.** Open Claude Code in the repo and type:

   ```
   /pep-talk mock gratitude-winddown a normal Tuesday     # end-to-end test, no credits
   /pep-talk gratitude-winddown a normal Tuesday          # the real thing
   ```

---

## Hook in your context (this is the part that matters)

> **The more personal the context, the better the talk.** A talk built from the topic alone
> sounds like a greeting card. A talk that remembers the evening you stayed late to fix the
> release, a line from your journal, and what you're actually working toward sounds like
> someone who knows you.

The brief agent reads [`context/profile.md`](context/profile.example.md) first, then every source
listed in [`context/sources.md`](context/sources.md). Add one line per source:

```markdown
- `~/notes` — my Markdown notes repo — any topic; check recent files first
- `~/Documents/journal` — daily journal — last 14 days for how I'm doing; older entries for episodes
- `~/Obsidian/Vault/Daily` — Obsidian daily notes — the last week
- `~/notes/wins.md` — wins log — evidence for evidence-reel and future-self
- `~/Documents/cv.pdf` — CV — work episodes and dates; keep numbers exactly as written
- `mcp:notion pages in the "Journal" database` — journal in Notion — recent days, my own lines
- `mcp:granola meetings from the last 7 days` — meeting notes — rehearsal and debrief
- `mcp:google-drive folder "Goals"` — goal docs — future-self and values-anchor
```

Anything works: a folder of Markdown, **another git repository on your disk** (just give its path),
PDFs, a wins/brag log, goals or OKRs, meeting transcripts, coaching homework, a public post you
wrote, or any app that Claude Code reaches through an MCP connector. For quick, no-setup context,
drop files into `context/private/` (gitignored).

What makes a source good:
- **Episodes with dates.** "Shipped the migration on 3 March after two failed tries" beats "I'm good
  at migrations".
- **Your own words.** Lines you wrote to yourself are reused verbatim. They land harder than
  anything a writer can compose.
- **What drags you down, in your words.** The `compassion` theme answers your actual inner critic,
  not a generic one.
- **A never-mention list** in your profile. Those topics stay out of every talk.

**Alternative: bring the skill to your context.** If your notes already live in a repo, copy
`.claude/skills/pep-talk/`, `scripts/`, `themes/` and `context/` into it. The skill then runs
inside your notes, and `context/sources.md` can point at `.`.

More detail: [`context/README.md`](context/README.md).

---

## Delivery

Both channels are optional and independent. The skill runs each one that is set up and tells you
when one is skipped. Without either, the MP3 stays in `out/`.

### Telegram (recommended: every talk lands on your phone)

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the
   prompts. Copy the token into `TELEGRAM_BOT_TOKEN`.
2. Open your new bot and send it `/start`. A bot can't message a chat that never wrote to it.
3. Open `https://api.telegram.org/bot<token>/getUpdates` and copy `message.chat.id` into
   `TELEGRAM_CHAT_ID`.
4. Test: `sh scripts/pep_talk.sh telegram out/sample.mp3 examples/sample.md`

Each talk arrives as a playable audio message with its title, date, theme and topic in the
caption, plus the transcript as a reply.

### GitHub pull request (an archive in your private repo)

Each talk is pushed to its own `talk/<name>` branch: the MP3 and the speech under `talks/<name>/`.
A pull request then opens with a play link and the full transcript. Your working tree and current
branch are never touched. Merge it to keep the talk in `main`, or close it.

- Needs a GitHub `origin` remote. Opening the PR uses the [`gh` CLI](https://cli.github.com)
  (`gh auth login`). Without `gh`, the branch is still pushed, and the skill opens the PR through a
  GitHub connector or gives you the compare link.
- **It refuses to push to a public repository**, because the speech is about you. `--allow-public`
  overrides that, if you really mean it.

---

## Use it from your phone (Claude Code cloud sessions)

Start a cloud session from the Claude app on your phone, type `/pep-talk <topic>`, and the talk
arrives in Telegram. To set it up, in your cloud environment's settings:

1. **Environment variables:** `ELEVENLABS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. You
   can provide the ElevenLabs key as a network secret instead (host `api.elevenlabs.io`, header
   `xi-api-key`).
2. **Network access:** allow `api.elevenlabs.io` and `api.telegram.org`. ffmpeg comes from apt the
   first time a talk is built.
3. **Context:** a cloud session sees only what's in the repo, plus any connectors it has. In your
   **private** copy, remove the `context/profile.md` and `context/private/` lines from
   `.gitignore` and commit your context. Or keep the context in Notion or Drive and list it as an
   `mcp:` source. Never do this in a public fork.

The cloud git proxy often allows pushing only the session's own branch. When that happens, `pr`
commits the talk to the session branch, and that branch becomes the pull request.

---

## Reference

### Commands

```sh
sh scripts/pep_talk.sh build  <speech.md> [--dry-run | --mock] [--out FILE] [--voice ID] [--model ID]
                                          [--no-stitch] [--bed brown|none|FILE] [--bed-db DB]
sh scripts/pep_talk.sh telegram <file.mp3> <speech.md> [--dry-run]
sh scripts/pep_talk.sh pr       <file.mp3> <speech.md> [--base BRANCH] [--head BRANCH] [--allow-public] [--dry-run]
sh scripts/pep_talk.sh doctor   [--offline]
```

- `--dry-run` parses the speech and prints spoken words, estimated length and characters billed
  against the 5,500-character budget. No API call.
- `--mock` runs the whole pipeline with placeholder tones. No key, no credits.
- Exit codes: `0` done · `1` error · `2` bad usage · `3` channel not set up (or public repo
  refused) · `4` PR branch pushed, but no `gh` to open the PR.

Segments are cached in `.cache/segments/`, so a re-run after a failure only bills the segments
that didn't finish.

### Speech format

Write your own speeches by hand if you like. The renderer doesn't care who wrote them.

```markdown
---
title: An Ordinary Tuesday
mode: sleep                  # sleep (noise bed, drowsy ending) | wake
theme: gratitude-winddown
topic: winding down after an ordinary day
voice_id: JBFqnCBsd6RMkjVDRZzb   # optional
---
# 1. Arrive                         ← '#' lines are labels for humans, not read aloud
[softly] Alex. The day is done. Breathe in slowly… and let it go.
[[PAUSE 6]]                         ← 6 s of silence; also ends a segment (one API request)
[slowly] Go back to this morning. The first coffee, warm in both hands…
```

Single-bracket tags are [ElevenLabs audio tags](https://elevenlabs.io/docs/best-practices/prompting/eleven-v3).
They steer delivery and are not read aloud. The tags that are safe to use are listed in
[`themes/guide.md`](themes/guide.md) §5. A full example is in
[`examples/sample.md`](examples/sample.md).

### Repository layout

```
.claude/skills/pep-talk/SKILL.md   the skill: parse → brief → write → budget → render → deliver
themes/guide.md                    shared writing rules, routing, evidence guardrails, markup
themes/brief.md                    what the brief agent extracts from your context
themes/<theme>.md                  structure, timings and worked example per theme
context/                           your profile and source list (README inside)
scripts/pep_talk.py                renderer + delivery CLI (stdlib only)
scripts/pep_talk.sh                wrapper; installs ffmpeg on first use
tests/                             unittest suite, no network or key needed
```

### Cost

A talk is capped at about 5,500 characters, so one talk uses up to about 5,500 ElevenLabs
characters. Your plan's monthly quota sets how many talks you get. The dry run prints the exact
count before you spend anything.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `ELEVENLABS_API_KEY` / HTTP 401 | Key missing or wrong, in `.env` or the cloud environment variables. |
| HTTP 402 or `quota_exceeded` | Out of ElevenLabs characters for the month. |
| 400/422 mentioning stitching or the model | Retry with `--no-stitch`, then with `--model eleven_v3 --no-stitch`. |
| Connection blocked (cloud) | Allow `api.elevenlabs.io` / `api.telegram.org` in the environment's network access. |
| Telegram `chat not found` | Send `/start` to your bot first, and re-check `TELEGRAM_CHAT_ID`. |
| `pr` refuses: public repository | That's on purpose. Use a private copy, or pass `--allow-public`. |
| The talk feels generic | It's the context. Fill in `context/profile.md` and add real sources. |

Run `sh scripts/pep_talk.sh doctor` first. It checks every item above.

### Development

```sh
python3 -m unittest discover -s tests -v      # no network, no API key
```

CI runs the tests, a dry run and a mock end-to-end build on every push.

---

## Privacy

Your context and talks stay on your machine, with three exceptions. What Claude reads is sent to
Anthropic as part of your Claude Code session. The speech text is sent to ElevenLabs to be voiced.
And the MP3 goes to your own Telegram chat and your own GitHub repo, if you set those up.
`.env`, `context/profile.md`, `context/private/`, `speeches/`, `out/` and `.cache/` are gitignored.

## Not therapy

This is a tool for encouragement and rehearsal, not therapy or medical advice. If you're
struggling, talk to someone you trust or a professional. If you're in crisis, contact your local
emergency services.

## License

[MIT](LICENSE)
