# Your context

A pep talk is only as good as what it knows about you. A talk built from nothing but the topic
sounds like a greeting card. A talk that remembers the Tuesday you stayed late to fix the launch,
the line you once wrote in your journal, and the thing you are actually working toward sounds like
someone who knows you. **The more personal the context, the better the talk.**

The speech writer never reads your notes directly. One brief agent reads them, picks out what is
relevant to today's topic, and writes a short brief (`themes/brief.md`). The speech is written from
that brief only.

## Set it up in three steps

1. **Copy the profile.** `cp context/profile.example.md context/profile.md` and fill it in. Ten
   minutes is enough; it grows over time. `profile.md` is gitignored. When a note disagrees with the
   profile, the profile wins.
2. **List your sources** in `context/sources.md`: folders, files, other repositories, URLs or
   connectors. The defaults already point at your profile, `context/private/` and your past talks.
3. **Optional: drop files** into `context/private/` (gitignored). Anything there is read.

## What counts as a source

| Source | Example | Good for |
|---|---|---|
| A folder of notes or a journal | an Obsidian vault, a Logseq graph, a folder of plain Markdown | recent days, inner critic lines, your own words |
| A wins or brag log | `wins.md`, one line per thing that went right | evidence for `evidence-reel`, `future-self` |
| A CV or LinkedIn export | `cv.pdf`, `Profile.pdf` | real episodes, keeping facts and numbers straight |
| Goals or OKR documents | `goals-2026.md`, a quarterly plan | `future-self`, `values-anchor` |
| Meeting transcripts | exported call notes | `rehearsal`, `debrief` |
| Therapy or coaching homework | worksheets, reflections | the critic, reframes, lines that help — *only if you are comfortable; it stays local* |
| Another git repository | `~/notes`, by absolute path | anything you already keep in a repo |
| `context/private/` | any file you drop in | quick, private, no setup |
| URLs | a public post you wrote, a talk page | episodes in your own words |
| MCP connectors in Claude Code | Notion, Google Drive, Granola, Gmail | notes and documents that live in apps |

The brief agent uses whatever tools the session has. If a source needs a connector that is not set
up, the brief lists it under Gaps and carries on; it never guesses.

## Privacy

- **Everything stays on your machine**, except two things: what Claude reads is sent to Anthropic as
  part of your Claude Code session, and the finished speech text is sent to ElevenLabs to be voiced.
  If you set up Telegram, the MP3 and the speech go to your own bot chat. If you use pull-request
  delivery, the speech and the MP3 are pushed to your GitHub repository, so use a private one.
- **Gitignored by default:** `context/profile.md`, `context/private/`, `speeches/`, `out/` and
  `.cache/` (where the briefs live). `context/sources.md` is committed: it holds paths, never
  content.
- **Sensitive material** (health, family, other people) is handled carefully by the brief agent:
  other people appear by role, not name, unless your profile allows names, and anything on your
  "never mention" list stays out of every talk.

## Cloud sessions from the Claude mobile app

A cloud session runs in a fresh copy of your repository on a remote machine. It cannot see your
laptop's folders or anything gitignored. So the context must be either:

- **in the repository itself**, which means a **private** copy of this repo with the gitignore
  lines for `context/profile.md` and `context/private/` removed. Never remove them in a public
  fork; or
- **reachable through a connector** (Notion, Google Drive, Granola, Gmail) that the cloud session
  has access to.

This is not therapy and not medical advice. If you are in crisis, contact your local emergency
services.
