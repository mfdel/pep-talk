# Context sources

The brief agent reads this file, then every source listed below, and finds what is relevant to the
topic of today's talk. It edits none of them. See `context/README.md` for what makes a good source.

Format: one bullet per source.

```
- `<path, URL or connector>` — <what it holds> — <when to use it>
```

- **Paths** can be files or folders (folders are searched, not read end to end), relative to this
  repo, absolute, or starting with `~`. Another git repository is just a folder path.
- **URLs** are fetched as pages.
- **Connectors** are written `mcp:<name>` plus what to look for, e.g. `mcp:notion pages tagged
  journal`. They work only if the session has that connector.
- A source that is missing or fails to load is listed under Gaps in the brief, never guessed.
- `context/profile.md` wins over every other source when facts disagree.

## Sources

- `context/profile.md` — who you are: name, goals, values, critic patterns, lines that help, wins,
  never-mention list — always; wins over every other source
- `context/private/` — anything you dropped in: notes, exports, documents — always; search for the
  topic
- `speeches/affirmations.md` — lines already used in past talks — always; avoid repeating a line
  used in the last 7 days
- `speeches/` — past talks — always; avoid repeating the same episodes and arcs, and flag the same
  hard topic requested 3+ times in 7 days

<!--
Examples. Copy a line above this comment and edit it to add a source.

- `~/notes` — a git repo of Markdown notes — any topic; check recent files first
- `~/Documents/journal` — daily journal entries — the last 14 days for the day state; older entries for episodes
- `~/Obsidian/Vault` — an Obsidian vault — search by topic; the `Daily/` folder for recent days
- `~/Documents/cv.pdf` — CV — work episodes and dates; keep numbers exactly as written
- `~/notes/wins.md` — wins log — evidence for evidence-reel and future-self
- `https://example.com/my-talk` — a talk page in my own words — episodes from that event
- `mcp:notion pages in the "Journal" database` — journal in Notion — recent days and own lines
- `mcp:granola meetings from the last 7 days` — meeting notes — rehearsal and debrief of work events
- `mcp:google-drive folder "Goals"` — goal documents — future-self and values-anchor
-->
