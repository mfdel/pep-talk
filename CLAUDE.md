# CLAUDE.md

This repo turns a topic into a spoken pep talk: `/pep-talk [theme] [sleep|wake] [mock] <topic>`.
The skill lives in `.claude/skills/pep-talk/SKILL.md`; follow it step by step.

- Writing rules: `themes/guide.md` (shared) and `themes/<theme>.md` (one per theme).
- The listener's context is read only by the context-brief subagent (`themes/brief.md`), from
  `context/profile.md` and the sources in `context/sources.md`. Do not read those files in the
  main session unless the user asks.
- Renderer and delivery: `sh scripts/pep_talk.sh build | telegram | pr | doctor`. Stdlib Python;
  ffmpeg is the only dependency and the wrapper installs it.
- Tests: `python3 -m unittest discover -s tests -v`. No network, no API key needed.
- `speeches/`, `out/`, `.cache/`, `.env` and `context/profile.md` are gitignored on purpose: they
  hold personal material. Never commit them to a public repo.
