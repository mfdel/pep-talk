"""The speech file: front matter, segments and pauses, estimates, and the talk's facts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .common import PepTalkError

MAX_SEGMENT_CHARS = 10_000  # per-request character limit of the ElevenLabs v4 model
COST_PER_1K_CHARS = 0.08  # USD, used for the dry-run estimate only
CHAR_BUDGET = 5_500  # a 6-10 minute talk; above this it runs long and costs more
CHARS_PER_SECOND = 14.0  # calm guided speech, tags excluded

PAUSE_RE = re.compile(r"\[\[\s*PAUSE\s+(\d+(?:\.\d+)?)\s*\]\]", re.IGNORECASE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TAG_RE = re.compile(r"\[[^\[\]]*\]")
STEM_DATE_RE = re.compile(r"^(\d{8})_")


# ---------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Speech:
    """One segment of text, sent to the API as a single request."""

    text: str


@dataclass(frozen=True)
class Pause:
    """Silence, in seconds."""

    seconds: float


Item = Speech | Pause


def _strip_inline_comment(value: str) -> str:
    """Drop a trailing ``# comment`` (a '#' preceded by whitespace) and surrounding quotes."""
    value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Split ``key: value`` front matter between ``---`` fences from the body.

    Returns an empty dict and the whole text when there is no front matter.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            break
    else:
        raise PepTalkError("front matter opened with '---' but never closed")

    meta: dict[str, str] = {}
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise PepTalkError(f"front matter line is not 'key: value': {line!r}")
        key, value = stripped.split(":", 1)
        meta[key.strip().lower()] = _strip_inline_comment(value)
    return meta, "\n".join(lines[end + 1 :])


def theme_of(meta: dict[str, str]) -> str | None:
    """The theme id; ``style`` is the old name for the same key."""
    return meta.get("theme") or meta.get("style") or None


def _clean_text(chunk: str) -> str:
    """Drop blank lines and '#' label lines, keep the rest joined by newlines."""
    kept = []
    for line in chunk.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            kept.append(stripped)
    return "\n".join(kept)


def parse_body(body: str) -> list[Item]:
    """Turn the speech body into a timeline of Speech and Pause items.

    Consecutive pauses (including ones separated only by labels or comments) are merged.
    """
    body = COMMENT_RE.sub("", body)
    parts = PAUSE_RE.split(body)
    items: list[Item] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            seconds = float(part)
            if items and isinstance(items[-1], Pause):
                items[-1] = Pause(items[-1].seconds + seconds)
            else:
                items.append(Pause(seconds))
            continue
        text = _clean_text(part)
        if text:
            items.append(Speech(text))

    for n, item in enumerate(s for s in items if isinstance(s, Speech)):
        if len(item.text) > MAX_SEGMENT_CHARS:
            raise PepTalkError(
                f"segment {n + 1} is {len(item.text):,} characters; the limit per request is "
                f"{MAX_SEGMENT_CHARS:,}. Split it with a [[PAUSE n]] marker."
            )
    if not any(isinstance(i, Speech) for i in items):
        raise PepTalkError("the speech has no text to read")
    return items


def plain_text(body: str) -> str:
    """The speech as a reader sees it: no comments, labels, pause markers or audio tags.

    Paragraphs keep the author's line breaks; a pause becomes a paragraph break.
    """
    body = PAUSE_RE.sub("\n\n", COMMENT_RE.sub("", body))
    lines = []
    for line in body.splitlines():
        if line.strip().startswith("#"):
            continue
        lines.append(re.sub(r"[ \t]{2,}", " ", TAG_RE.sub("", line)).strip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


@dataclass(frozen=True)
class SpeechFile:
    """A parsed speech file."""

    meta: dict[str, str]
    items: list[Item]

    @property
    def segments(self) -> list[Speech]:
        return [i for i in self.items if isinstance(i, Speech)]

    @property
    def pause_seconds(self) -> float:
        return sum(i.seconds for i in self.items if isinstance(i, Pause))


def load_speech(path: Path) -> SpeechFile:
    """Read and parse a speech file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PepTalkError(f"cannot read speech file {path}: {exc}") from exc
    meta, body = parse_front_matter(text)
    mode = meta.get("mode", "sleep")
    if mode not in ("sleep", "wake"):
        raise PepTalkError(f"front matter mode must be 'sleep' or 'wake', got {mode!r}")
    return SpeechFile(meta=meta, items=parse_body(body))


# ---------------------------------------------------------------------------------------
# Estimates
# ---------------------------------------------------------------------------------------


def spoken_chars(text: str) -> int:
    """Characters that are actually spoken: audio tags removed."""
    return len(TAG_RE.sub("", text).strip())


def spoken_words(text: str) -> int:
    """Words that are actually spoken: audio tags removed."""
    return len(TAG_RE.sub("", text).split())


def estimate_seconds(text: str) -> float:
    """Rough spoken duration of one segment."""
    return max(spoken_chars(text) / CHARS_PER_SECOND, 0.5)


def fmt_duration(seconds: float) -> str:
    """Format seconds as m:ss."""
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}"


@dataclass(frozen=True)
class Estimate:
    segments: int
    words: int
    chars: int  # what ElevenLabs bills: tags included
    cost_usd: float
    spoken_s: float
    silence_s: float
    total_s: float


def estimate(speech: SpeechFile, lead_in: float, tail: float) -> Estimate:
    """Numbers the dry run prints. Silence covers pauses, lead-in and the fade-out tail."""
    chars = sum(len(s.text) for s in speech.segments)
    spoken = sum(estimate_seconds(s.text) for s in speech.segments)
    silence = speech.pause_seconds + lead_in + tail
    return Estimate(
        segments=len(speech.segments),
        words=sum(spoken_words(s.text) for s in speech.segments),
        chars=chars,
        cost_usd=chars / 1000 * COST_PER_1K_CHARS,
        spoken_s=spoken,
        silence_s=silence,
        total_s=spoken + silence,
    )


# ---------------------------------------------------------------------------------------
# Talk metadata (shared by Telegram and pull requests)
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TalkMeta:
    """What the caption and the pull request say about one talk."""

    title: str
    day: date | None
    theme: str | None
    mode: str | None
    topic: str


def talk_meta(stem: str, meta: dict[str, str]) -> TalkMeta:
    """Fields from the front matter, the rest from the file stem.

    Stems look like ``YYYYMMDD_<topic-slug>_<mode>[_<suffix>]``. A leading date becomes
    the talk's date (the first one, if there are several); ``topic`` in the front matter
    beats the slug, ``mode`` in the front matter beats the stem.
    """
    rest, day = stem, None
    while m := STEM_DATE_RE.match(rest):
        if day is None:
            raw = m.group(1)
            try:
                day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
            except ValueError:
                pass
        rest = rest[m.end():]
    parts = rest.split("_")
    mode = meta.get("mode")
    for i, part in enumerate(parts[1:], 1):
        if part in ("sleep", "wake"):
            mode = mode or part
            parts = parts[:i]
            break
    slug = "_".join(parts) or stem
    topic = meta.get("topic") or slug.replace("-", " ").replace("_", " ")
    return TalkMeta(title=meta.get("title") or topic, day=day, theme=theme_of(meta),
                    mode=mode, topic=topic)


def read_talk(mp3: Path, speech: Path) -> tuple[TalkMeta, str]:
    """Check both files exist; return the talk's metadata and the speech body."""
    if mp3.suffix.lower() != ".mp3" or not mp3.is_file():
        raise PepTalkError(f"no such MP3: {mp3}")
    try:
        meta, body = parse_front_matter(speech.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PepTalkError(f"cannot read speech file {speech}: {exc}") from exc
    return talk_meta(mp3.stem, meta), body
