---
title: An Ordinary Tuesday
mode: sleep                  # sleep = quiet brown-noise bed by default | wake = no bed
theme: gratitude-winddown    # a theme id from themes/guide.md §2, or custom
topic: winding down after an ordinary day
---
<!-- theme: gratitude-winddown — chosen because: ordinary evening, nothing to process -->
<!--
Format reference for scripts/pep_talk.py. A short sample, not a full-length talk. Writing rules:
themes/guide.md and the theme files in themes/. The listener "Alex" and the day are invented.

- Front matter: `key: value` lines between `---` fences; trailing `# comments` are stripped.
  Required: title (MP3 title tag, Telegram caption, PR title) and mode (sleep | wake).
  Optional: theme (theme id), topic (one line for the caption and PR body) and voice_id
  (an ElevenLabs voice). Without voice_id the renderer uses ELEVENLABS_VOICE_ID, else the
  default premade voice.
- `[[PAUSE n]]` on its own line inserts n seconds of silence and ends a segment. The text
  between two markers is one ElevenLabs request.
- Single-bracket tags like [softly], [slowly], [whispering], [sighing] and
  [sleepy drowsy voice] are ElevenLabs audio tags. They steer delivery and are not read
  aloud. Palette: themes/guide.md §5.
- Lines starting with '# ' are section labels for humans. HTML comments are dropped.

Build:
  sh scripts/pep_talk.sh build examples/sample.md --dry-run   # parse, count words, length, characters
  sh scripts/pep_talk.sh build examples/sample.md --mock      # full pipeline with placeholder audio, no credits
-->

# 1. Arrive
[softly] Alex. The day is done. Breathe in slowly… and let it go.
[sighing] Let your shoulders drop. Nothing more is asked of today.
[[PAUSE 6]]

# 2. Three good things
[slowly] Go back to this morning. The first coffee, warm in both hands, by the kitchen window.
You made that cup yourself, and you took the minute to drink it.
[[PAUSE 6]]

[softly] At lunch, a colleague told a story, and the whole table laughed.
You were the one who asked how the weekend was. That question started it.
[[PAUSE 6]]

[slowly] And the walk home, Alex. Cool air on your face. You took the long way, past the park.
The trees were already turning. You noticed, because you slowed down.
[[PAUSE 8]]

# 3. One thing you did
[softly] This afternoon you sent the email you had put off since Friday. Whatever the reply, it is sent.
Say it now, in your own voice. Out loud, or silently. I did that.
[[PAUSE 6]]

# 4. Let the day go
[softly] Small things, all of them. They do not need to be big to be real.
Let them sit with you for a breath.
[[PAUSE 6]]

[whispering] Three good things. One thing done. All of it yours to keep, Alex.
[[PAUSE 6]]

[sleepy drowsy voice] Breathe in… and out. The day can rest now. So can you.
[[PAUSE 30]]
