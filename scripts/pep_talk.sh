#!/bin/sh
# Entry point for building and delivering a pep talk; installs ffmpeg first if it is missing.
#
# scripts/pep_talk.py is stdlib-only, so a bare python3 runs it; ffmpeg is its one real
# dependency for audio. On a Mac install it once with Homebrew. A fresh Linux container
# (a Claude Code cloud session, CI) usually starts without it, so the first build installs it
# with apt instead of every session paying for it up front.
#
# Idempotent: a warm run is one `command -v` and then the Python build.
#
#     sh scripts/pep_talk.sh build examples/sample.md --dry-run
#     sh scripts/pep_talk.sh build examples/sample.md --mock
#     sh scripts/pep_talk.sh build speeches/20261018_review_wake.md
#     sh scripts/pep_talk.sh telegram out/20261018_review_wake.mp3 speeches/20261018_review_wake.md
#     sh scripts/pep_talk.sh pr out/20261018_review_wake.mp3 speeches/20261018_review_wake.md
#     sh scripts/pep_talk.sh doctor [--offline]
#
# Every argument is passed straight through to scripts/pep_talk.py. telegram, pr and doctor
# skip the ffmpeg install: ffprobe only adds the duration, which is left out without it, and
# doctor reports a missing ffmpeg rather than fixing it. telegram and pr exit 3 when they are
# not set up; pr exits 4 when it pushed the branch but has no gh to open the pull request.

set -eu

REPO=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

usage() {
    echo "usage: sh scripts/pep_talk.sh build <speech.md> [--dry-run | --mock] [--out FILE] [--voice ID]" >&2
    echo "       sh scripts/pep_talk.sh telegram <file.mp3> <speech.md> [--dry-run]" >&2
    echo "       sh scripts/pep_talk.sh pr <file.mp3> <speech.md> [--base BRANCH] [--remote NAME] [--allow-public] [--dry-run]" >&2
    echo "       sh scripts/pep_talk.sh doctor [--offline]" >&2
    echo "run with -h after a command for every flag" >&2
}

if [ "$#" -eq 0 ]; then
    usage
    exit 2
fi

case "$1" in
    telegram|pr|doctor|-h|--help) exec python3 "$REPO/scripts/pep_talk.py" "$@" ;;
    build) ;;
    *) usage; exit 2 ;;
esac

# A dry run needs neither ffmpeg nor the network.
for arg in "$@"; do
    case "$arg" in
        --dry-run|-h|--help) exec python3 "$REPO/scripts/pep_talk.py" "$@" ;;
    esac
done

# ---------------------------------------------------------------------------------------
# ffmpeg
# ---------------------------------------------------------------------------------------
# Debian/Ubuntu's ffmpeg package ships ffprobe and libmp3lame. Install needs root: a cloud
# container runs as root; elsewhere passwordless sudo is accepted, a password prompt is not.
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    SUDO=
    if [ "$(uname)" = "Linux" ] && command -v apt-get >/dev/null 2>&1; then
        if [ "$(id -u)" -ne 0 ]; then
            if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
                SUDO="sudo -n"
            else
                echo "ffmpeg missing and no root or passwordless sudo to install it." >&2
                echo "Run: sudo apt-get install -y ffmpeg" >&2
                exit 1
            fi
        fi
        echo "==> installing ffmpeg (apt)" >&2
        $SUDO apt-get update -qq
        $SUDO env DEBIAN_FRONTEND=noninteractive \
            apt-get install -y -qq --no-install-recommends ffmpeg >/dev/null
    elif [ "$(uname)" = "Darwin" ]; then
        echo "ffmpeg not found. Install it with: brew install ffmpeg" >&2
        exit 1
    else
        echo "ffmpeg not found. Install ffmpeg (with ffprobe and libmp3lame) and run again." >&2
        exit 1
    fi
fi

exec python3 "$REPO/scripts/pep_talk.py" "$@"
