#!/usr/bin/env python3
"""Render a pep-talk speech file to one MP3 with ElevenLabs, then deliver it.

The speech is Markdown with a small front matter block, ElevenLabs audio tags and pause
markers. examples/sample.md in the skill folder shows the whole format:

    ---
    title: Walking into the review
    mode: wake             # sleep | wake
    theme: future-self     # optional; `style` is accepted as an old alias
    topic: the quarterly review   # optional, shown in the caption and PR
    voice_id: abc123       # optional
    ---
    # Arrival              <- '#' lines are labels for humans, ignored
    [calm] Alex, breathe in... and let the morning settle.
    [[PAUSE 6]]
    [warm] You have done harder things than this.

Text between two ``[[PAUSE n]]`` markers is one segment, one API request. Single-bracket
tags like ``[calm]`` stay in the text: the model reads them as delivery directions.

Commands:

    build     speech -> .pep-talk/out/<stem>.mp3. --dry-run prints the budget, --mock uses tones
    telegram  send the MP3, then the speech as a reply, to your own Telegram bot chat
    pr        deliver the MP3 and speech as a pull request on your (private) GitHub repo
    doctor    check the setup, one line per item

    S=.claude/skills/pep-talk
    sh $S/scripts/pep_talk.sh build $S/examples/sample.md --dry-run
    sh $S/scripts/pep_talk.sh build $S/examples/sample.md --mock
    sh $S/scripts/pep_talk.sh build .pep-talk/speeches/20261018_review_wake.md
    sh $S/scripts/pep_talk.sh telegram .pep-talk/out/sample.mp3 $S/examples/sample.md [--dry-run]
    sh $S/scripts/pep_talk.sh pr .pep-talk/out/sample.mp3 $S/examples/sample.md [--dry-run]
    sh $S/scripts/pep_talk.sh doctor [--offline]

Where files live. The skill folder (the one holding this scripts/ folder) is self-contained:
copy it into any project's .claude/skills/. The project is the git work tree around the
current directory, else the current directory. Everything generated goes in the project's
``.pep-talk/`` folder, which carries its own ``.gitignore`` so git never sees it:
out/<stem>.mp3, cache/segments/ (one MP3 per segment, so a re-run bills only edited text),
cache/pr/<stem>.md (pull request bodies), and the speeches/ and briefs/ the skill writes.

Configuration comes from the environment, or from a ``.env`` file in the skill folder (see
.env.example there) or at the project root. The real environment wins over both, the
skill's .env over the project's: ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID,
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

Exit codes: 0 done, 1 error, 2 bad usage, 3 delivery not set up (or refused, for a public
repository), 4 ``pr`` pushed the branch but could not open the pull request (no ``gh``).

In a Claude Code cloud environment, api.elevenlabs.io and api.telegram.org must be allowed
in the environment's network access settings, or every request fails as blocked. There the
ElevenLabs key can also come from a network secret (header ``xi-api-key``) that the proxy
adds, so a build without ELEVENLABS_API_KEY still sends its requests. The session's git
proxy may only accept pushes to the session's own branch; ``pr`` then commits the talk
onto that branch instead of ``talk/<stem>``.

Stdlib only, so a bare ``python3`` (3.10+) runs it. ffmpeg and ffprobe are the only
external binaries for rendering; ``scripts/pep_talk.sh`` installs them on Debian/Ubuntu.
git and, optionally, the GitHub CLI ``gh`` are needed for ``pr``. The code lives in the
``peptalk`` package next to this file, one module per job; this file is the command line.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

# Run as a script from any directory: the peptalk package sits next to this file.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from peptalk import build, doctor, github_pr, telegram  # noqa: E402
from peptalk.common import EXIT_NOT_CONFIGURED, NotConfigured, PepTalkError, redact  # noqa: E402
from peptalk.elevenlabs import DEFAULT_MODEL, DEFAULT_VOICE_ID  # noqa: E402


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="speech Markdown -> MP3")
    b.add_argument("speech", help="speech Markdown file")
    b.add_argument("--out", help="output MP3 (default .pep-talk/out/<speech stem>.mp3)")
    b.add_argument("--voice", "--voice-id", dest="voice",
                   help="ElevenLabs voice id (else front matter voice_id, else "
                        f"$ELEVENLABS_VOICE_ID, else {DEFAULT_VOICE_ID})")
    b.add_argument("--model", help=f"model id (default $ELEVENLABS_MODEL or {DEFAULT_MODEL})")
    b.add_argument("--stability", type=float, default=0.5)
    b.add_argument("--similarity", type=float, default=0.8)
    b.add_argument("--style", type=float, default=None,
                   help="ElevenLabs style exaggeration 0-1 (older models only; not the theme)")
    b.add_argument("--no-stitch", action="store_true",
                   help="do not send previous_text/next_text")
    b.add_argument("--bed", help="brown | none | PATH to a looped audio file "
                   "(default brown for mode sleep, none for wake)")
    b.add_argument("--bed-db", type=float, default=-32.0, help="bed loudness, LUFS (default -32)")
    b.add_argument("--bitrate", default="96k")
    b.add_argument("--lead-in", type=float, default=2.0, help="seconds of silence at the start")
    b.add_argument("--fade-in", type=float, default=1.0)
    b.add_argument("--fade-out", type=float, default=4.0,
                   help="fade length; the same amount of silence is appended first")
    b.add_argument("--cache-dir", help="segment cache (default .pep-talk/cache/segments)")
    mode = b.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="estimate only, no network/ffmpeg")
    mode.add_argument("--mock", action="store_true",
                      help="placeholder tones instead of the API; no key needed")

    t = sub.add_parser("telegram", help="send an MP3 and its speech to your Telegram bot chat")
    t.add_argument("mp3", help="the built MP3")
    t.add_argument("speech", help="its speech Markdown file, sent as a reply to the audio")
    t.add_argument("--dry-run", action="store_true", help="print the request, send nothing")

    p = sub.add_parser("pr", help="deliver an MP3 and its speech as a GitHub pull request")
    p.add_argument("mp3", help="the built MP3")
    p.add_argument("speech", help="its speech Markdown file")
    p.add_argument("--base", help="branch to open the PR against (default: the remote's "
                                  "default branch, else main)")
    p.add_argument("--head", help="head branch (default talk/<stem>, force-pushed); naming "
                                  "the current branch commits the talk onto it instead")
    p.add_argument("--remote", default="origin", help="git remote to push to (default origin)")
    p.add_argument("--allow-public", action="store_true",
                   help="deliver even if the repository is public")
    p.add_argument("--dry-run", action="store_true", help="print the plan, push nothing")

    d = sub.add_parser("doctor", help="check the setup")
    d.add_argument("--offline", action="store_true", help="skip every network check")
    d.add_argument("--remote", default="origin", help="git remote used by pr (default origin)")
    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "build": build.run,
    "telegram": telegram.run,
    "pr": github_pr.run,
    "doctor": doctor.run,
}


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except NotConfigured as exc:
        print(f"pep_talk: {redact(str(exc))}", file=sys.stderr)
        return EXIT_NOT_CONFIGURED
    except PepTalkError as exc:
        print(f"pep_talk: {redact(str(exc))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
