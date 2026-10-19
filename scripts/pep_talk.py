#!/usr/bin/env python3
"""Render a pep-talk speech file to one MP3 with ElevenLabs, then deliver it.

The speech is Markdown with a small front matter block, ElevenLabs audio tags and pause
markers. examples/sample.md shows the whole format:

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

    build     speech -> out/<stem>.mp3. --dry-run prints the budget, --mock uses tones
    telegram  send the MP3, then the speech as a reply, to your own Telegram bot chat
    pr        deliver the MP3 and speech as a pull request on your (private) GitHub repo
    doctor    check the setup, one line per item

    sh scripts/pep_talk.sh build examples/sample.md --dry-run
    sh scripts/pep_talk.sh build examples/sample.md --mock
    sh scripts/pep_talk.sh build examples/sample.md
    sh scripts/pep_talk.sh telegram out/sample.mp3 examples/sample.md [--dry-run]
    sh scripts/pep_talk.sh pr out/sample.mp3 examples/sample.md [--dry-run]
    sh scripts/pep_talk.sh doctor [--offline]

Configuration comes from the environment, or from a ``.env`` file at the repository root
(see .env.example); a variable set in the real environment wins over .env:
ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

Exit codes: 0 done, 1 error, 2 bad usage, 3 delivery not set up (or refused, for a public
repository), 4 ``pr`` pushed the branch but could not open the pull request (no ``gh``).

In a Claude Code cloud environment, api.elevenlabs.io and api.telegram.org must be allowed
in the environment's network access settings, or every request fails as blocked. There the
ElevenLabs key can also come from a network secret (header ``xi-api-key``) that the proxy
adds, so a build without ELEVENLABS_API_KEY still sends its requests. The session's git
proxy may only accept pushes to the session's own branch; ``pr`` then commits the talk
onto that branch instead of ``talk/<stem>``.

Stdlib only, so a bare ``python3`` (3.10+) runs it. ffmpeg and ffprobe are the only
external binaries for rendering; ``sh scripts/pep_talk.sh`` installs them on Debian/Ubuntu.
git and, optionally, the GitHub CLI ``gh`` are needed for ``pr``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env"

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
SUBSCRIPTION_URL = "https://api.elevenlabs.io/v1/user/subscription"
DEFAULT_MODEL = "eleven_v4"
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # ElevenLabs premade voice "George"
MAX_SEGMENT_CHARS = 10_000  # per-request character limit of the v4 model
STITCH_CHARS = 1_000  # max context sent as previous_text / next_text
COST_PER_1K_CHARS = 0.08  # USD, used for the dry-run estimate only
CHAR_BUDGET = 5_500  # a 6-10 minute talk; above this it runs long and costs more
CHARS_PER_SECOND = 14.0  # calm guided speech, tags excluded
SAMPLE_RATE = 44_100
HTTP_TIMEOUT = 120
HTTP_TRIES = 3

EXIT_NOT_CONFIGURED = 3  # delivery not set up, or refused: the skill skips it and says so
EXIT_NO_GH = 4  # pr: branch pushed, pull request left for another tool to open

PAUSE_RE = re.compile(r"\[\[\s*PAUSE\s+(\d+(?:\.\d+)?)\s*\]\]", re.IGNORECASE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TAG_RE = re.compile(r"\[[^\[\]]*\]")

FFMPEG_HINT = (
    "ffmpeg/ffprobe not found. Run `sh scripts/pep_talk.sh ...`, which installs it on "
    "Debian/Ubuntu, or install it yourself (macOS: `brew install ffmpeg`)."
)
KEY_HINT = (
    "copy .env.example to .env and set ELEVENLABS_API_KEY to a key from "
    "https://elevenlabs.io/app/settings/api-keys"
)

# Swapped out by tests so retries do not really wait.
_sleep = time.sleep


class PepTalkError(Exception):
    """A user-facing failure: printed without a traceback, exit code 1."""


class NotConfigured(PepTalkError):
    """A delivery channel is not set up, or refuses on purpose; exit code 3."""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------------------


def read_dotenv(path: Path) -> dict[str, str]:
    """Parse a ``.env`` file: ``KEY=VALUE`` lines, an optional ``export`` in front.

    Blank lines and ``#`` comments are skipped, as is a trailing `` # comment`` after an
    unquoted value. Matching single or double quotes around a value are stripped. Lines
    without ``=`` are ignored. A missing file is an empty dict.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if key:
            out[key] = value
    return out


def load_env() -> dict[str, str]:
    """.env values overlaid by the real environment. An empty real variable does not
    blank out a value from .env."""
    env = read_dotenv(ENV_FILE)
    for key, value in os.environ.items():
        if value or key not in env:
            env[key] = value
    return env


def env_source(name: str) -> str:
    """Where a variable came from, for messages: never its value."""
    return "environment" if os.environ.get(name) else ".env"


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
# ElevenLabs
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class VoiceConfig:
    voice_id: str
    model: str
    stability: float
    similarity: float
    style: float | None = None
    speaker_boost: bool = True

    def settings(self) -> dict[str, float | bool]:
        # Eleven v4 dropped the style slider, so it is sent only when asked for.
        out: dict[str, float | bool] = {
            "stability": self.stability,
            "similarity_boost": self.similarity,
            "use_speaker_boost": self.speaker_boost,
        }
        if self.style is not None:
            out["style"] = self.style
        return out


def resolve_voice_id(flag: str | None, meta: dict[str, str], env: dict[str, str]) -> str:
    """--voice beats front matter voice_id beats ELEVENLABS_VOICE_ID beats the default."""
    return flag or meta.get("voice_id") or env.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID


def cache_key(cfg: VoiceConfig, text: str) -> str:
    """Hash of everything that changes the audio of one segment, neighbours excluded.

    Request stitching context is left out on purpose: editing one paragraph re-bills only
    that paragraph, at the cost of its neighbours keeping their old stitching context.
    """
    fields = {"model": cfg.model, "voice_id": cfg.voice_id, "settings": cfg.settings(),
              "text": text}
    payload = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_request(
    cfg: VoiceConfig,
    text: str,
    previous_text: str | None,
    next_text: str | None,
    api_key: str | None,
) -> urllib.request.Request:
    """The text-to-speech request for one segment.

    ``xi-api-key`` is sent only when a key is known locally. In a cloud environment a
    network secret can have the proxy add it for api.elevenlabs.io instead.
    """
    body: dict[str, object] = {
        "text": text,
        "model_id": cfg.model,
        "voice_settings": cfg.settings(),
    }
    if previous_text:
        body["previous_text"] = previous_text[-STITCH_CHARS:]
    if next_text:
        body["next_text"] = next_text[:STITCH_CHARS]
    headers = {"Content-Type": "application/json", "Accept": "audio/mpeg"}
    if api_key:
        headers["xi-api-key"] = api_key
    return urllib.request.Request(
        API_URL.format(voice_id=cfg.voice_id),
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )


NETWORK_HINT = (
    "the request to api.elevenlabs.io was blocked or could not connect. In a Claude Code cloud "
    "environment, allow api.elevenlabs.io in the environment's network access settings."
)


def _http_error_message(code: int, body: str) -> str:
    if code == 401 and "quota_exceeded" in body:
        return (
            f"ElevenLabs credits used up: {body.strip()[:500]}\n"
            "Add credits or wait for the monthly reset; finished segments are cached, so a re-run "
            "only bills the rest."
        )
    if code == 401 and "missing_permissions" in body:
        return (
            f"the ElevenLabs key lacks a permission: {body.strip()[:500]}\n"
            "Edit the key at https://elevenlabs.io/app/settings/api-keys and allow Text to Speech."
        )
    if code == 401:
        return (
            "ElevenLabs rejected the request (HTTP 401): no valid key. Set ELEVENLABS_API_KEY "
            "in .env or the environment variables (key from "
            "https://elevenlabs.io/app/settings/api-keys), or, in a Claude Code cloud "
            "environment, add a network secret for api.elevenlabs.io with header xi-api-key."
        )
    if code == 402:
        return (
            f"ElevenLabs refused on plan grounds (HTTP 402): {body.strip()[:500]}\n"
            "The voice or model may need a paid plan: use a premade voice or upgrade."
        )
    if code == 403:
        return f"HTTP 403 from ElevenLabs or a proxy: {body.strip()[:500]}\n{NETWORK_HINT}"
    if code in (400, 422):
        return (
            f"ElevenLabs refused the request (HTTP {code}): {body.strip()[:1000]}\n"
            "If the model id is the problem, try --model eleven_v3 or "
            "--model eleven_multilingual_v2. If it complains about previous_text/next_text, "
            "add --no-stitch."
        )
    return f"ElevenLabs returned HTTP {code}: {body.strip()[:500]}"


def _send(
    req: urllib.request.Request,
    service: str,
    hint: str,
    error: Callable[[int, str], PepTalkError],
) -> bytes:
    """Send one request, retrying 429, 5xx and connection errors with backoff.

    ``error`` turns any other HTTP status and its body into the exception to raise.
    """
    last = ""
    for attempt in range(1, HTTP_TRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                data = resp.read()
            if not data:
                raise PepTalkError(f"{service} returned an empty response")
            return data
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace") if exc.fp else ""
            if exc.code == 429 or exc.code >= 500:
                last = f"HTTP {exc.code}: {body.strip()[:300]}"
            else:
                raise error(exc.code, body) from exc
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            # A proxy refusing the CONNECT is not transient; retrying only wastes time.
            if "403" in reason or "Tunnel connection failed" in reason:
                raise PepTalkError(f"{reason}\n{hint}") from exc
            last = f"connection error: {reason}"
        except TimeoutError:
            last = f"timed out after {HTTP_TIMEOUT} s"
        if attempt < HTTP_TRIES:
            wait = 2**attempt
            log(f"    retry {attempt}/{HTTP_TRIES - 1} in {wait} s ({last})")
            _sleep(wait)
    raise PepTalkError(f"{service} failed after {HTTP_TRIES} tries: {last}\n{hint}")


def synthesize(req: urllib.request.Request) -> bytes:
    """One ElevenLabs request."""
    return _send(req, "ElevenLabs", NETWORK_HINT,
                 lambda code, body: PepTalkError(_http_error_message(code, body)))


# ---------------------------------------------------------------------------------------
# ffmpeg
# ---------------------------------------------------------------------------------------


def require_ffmpeg() -> None:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise PepTalkError(FFMPEG_HINT)


def ffmpeg(*args: str) -> str:
    """Run ffmpeg quietly; return stderr (loudnorm writes its measurements there)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise PepTalkError(f"ffmpeg failed ({' '.join(cmd[:8])} ...):\n{tail}")
    return proc.stderr


def probe_duration(path: Path) -> float:
    """Duration of an audio file in seconds, via ffprobe."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise PepTalkError(f"ffprobe failed on {path}: {proc.stderr.strip()}")
    return float(proc.stdout.strip())


def make_mock_mp3(path: Path, seconds: float) -> None:
    """A quiet sine tone standing in for a generated segment."""
    ffmpeg(
        "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate={SAMPLE_RATE}:duration={seconds:.3f}",
        "-af", "volume=0.2", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "128k", str(path),
    )


def decode_pcm(path: Path) -> bytes:
    """Decode any audio file to raw 16-bit mono PCM at SAMPLE_RATE."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
           "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise PepTalkError(f"ffmpeg could not decode {path}: {proc.stderr.decode()[-500:]}")
    return proc.stdout


def silence_pcm(seconds: float) -> bytes:
    return b"\x00\x00" * round(seconds * SAMPLE_RATE)


def write_wav(path: Path, pcm: bytes) -> float:
    """Write mono 16-bit PCM to a WAV file; return its duration."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return len(pcm) / 2 / SAMPLE_RATE


def loudnorm(src: Path, dst: Path) -> None:
    """Two-pass EBU R128 normalisation to -16 LUFS, linear so pauses keep their shape.

    Falls back to single-pass if the first pass's measurements cannot be parsed.
    """
    target = "I=-16:TP=-1.5:LRA=11"
    err = ffmpeg("-i", str(src), "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-")
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", err)
    flt = f"loudnorm={target}"
    if match:
        m = json.loads(match.group(0))
        if m.get("input_i") not in (None, "-inf"):
            flt = (
                f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                f":offset={m['target_offset']}:linear=true"
            )
    ffmpeg("-i", str(src), "-af", flt, "-ar", str(SAMPLE_RATE), "-ac", "1", str(dst))


def bed_filter(bed: str, duration: float, bed_db: float, input_index: int) -> tuple[list[str], str]:
    """Input args and filter chain for the background bed, labelled [bed].

    ``bed_db`` is the bed's integrated loudness in LUFS, so -32 sits 16 LU under the voice
    whatever the source.
    """
    shape = (
        f"loudnorm=I={bed_db}:TP=-9:LRA=20,aresample={SAMPLE_RATE},"
        f"afade=t=in:st=0:d=5,afade=t=out:st={max(duration - 6, 0):.3f}:d=6"
    )
    if bed == "brown":
        inputs = ["-f", "lavfi", "-i",
                  f"anoisesrc=color=brown:sample_rate={SAMPLE_RATE}:amplitude=0.5"
                  f":duration={duration:.3f}"]
        chain = f"[{input_index}:a]lowpass=f=900,{shape}[bed]"
    else:
        inputs = ["-stream_loop", "-1", "-i", bed]
        chain = (
            f"[{input_index}:a]aformat=sample_rates={SAMPLE_RATE}:channel_layouts=mono,"
            f"atrim=0:{duration:.3f},asetpts=N/SR/TB,{shape}[bed]"
        )
    return inputs, chain


def render(
    voice_wav: Path,
    out: Path,
    duration: float,
    *,
    bed: str,
    bed_db: float,
    bitrate: str,
    title: str,
    fade_in: float,
    fade_out: float,
) -> None:
    """Mix the normalised voice with the bed, fade, and encode the final MP3."""
    fades = (
        f"afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={max(duration - fade_out, 0):.3f}:d={fade_out}"
    )
    args = ["-i", str(voice_wav)]
    if bed == "none":
        graph = f"[0:a]{fades}[out]"
    else:
        bed_inputs, bed_chain = bed_filter(bed, duration, bed_db, 1)
        args += bed_inputs
        graph = f"{bed_chain};[0:a][bed]amix=inputs=2:duration=first:normalize=0,{fades}[out]"
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(
        *args, "-filter_complex", graph, "-map", "[out]",
        "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "libmp3lame", "-b:a", bitrate,
        "-id3v2_version", "3", "-metadata", f"title={title}", str(out),
    )


# ---------------------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------------------


def default_out(speech_path: Path) -> Path:
    """out/<speech stem>.mp3 at the repository root."""
    return REPO / "out" / f"{speech_path.stem}.mp3"


def default_cache() -> Path:
    return REPO / ".cache" / "segments"


def fetch_segments(
    speech: SpeechFile,
    cfg: VoiceConfig | None,
    cache_dir: Path,
    work: Path,
    *,
    mock: bool,
    stitch: bool,
    api_key: str | None,
) -> tuple[list[Path], int]:
    """Get one MP3 per segment, from the cache, ElevenLabs, or a mock tone.

    Returns the paths in order and the number of characters billed this run.
    """
    segments = speech.segments
    paths: list[Path] = []
    billed = 0
    if not mock:
        cache_dir.mkdir(parents=True, exist_ok=True)
    for n, seg in enumerate(segments):
        label = f"  [{n + 1:>2}/{len(segments)}] {len(seg.text):>5} chars"
        if mock:
            path = work / f"mock_{n:03d}.mp3"
            make_mock_mp3(path, estimate_seconds(seg.text))
            log(f"{label}  mock")
            paths.append(path)
            continue
        assert cfg is not None
        path =cache_dir / f"{cache_key(cfg, seg.text)}.mp3"
        paths.append(path)
        if path.exists() and path.stat().st_size > 0:
            log(f"{label}  cached")
            continue
        prev_text = segments[n - 1].text if stitch and n > 0 else None
        next_text = segments[n + 1].text if stitch and n + 1 < len(segments) else None
        data = synthesize(build_request(cfg, seg.text, prev_text, next_text, api_key))
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        billed += len(seg.text)
        log(f"{label}  generated")
    return paths, billed


def voice_config(
    args: argparse.Namespace, meta: dict[str, str], env: dict[str, str]
) -> VoiceConfig:
    return VoiceConfig(
        voice_id=resolve_voice_id(args.voice, meta, env),
        model=args.model or env.get("ELEVENLABS_MODEL") or DEFAULT_MODEL,
        stability=args.stability,
        similarity=args.similarity,
        style=args.style,
    )


def print_dry_run(speech_path: Path, speech: SpeechFile, cfg: VoiceConfig, mode: str,
                  bed: str, lead_in: float, tail: float) -> None:
    est = estimate(speech, lead_in, tail)
    over = f"  OVER the {CHAR_BUDGET:,} budget: cut it" if est.chars > CHAR_BUDGET else (
        f"  (budget {CHAR_BUDGET:,})")
    print(f"speech:     {speech_path}  (mode {mode}, bed {bed})")
    print(f"voice:      {cfg.voice_id}  (model {cfg.model})")
    print(f"segments:   {est.segments}")
    print(f"words:      {est.words:,}  (spoken, tags excluded)")
    print(f"characters: {est.chars:,}{over}")
    print(f"est. cost:  ${est.cost_usd:.2f}  (at ${COST_PER_1K_CHARS}/1k chars)")
    print(f"spoken:     ~{fmt_duration(est.spoken_s)}  (at {CHARS_PER_SECOND:g} chars/s)")
    print(f"silence:    {fmt_duration(est.silence_s)}  (pauses, lead-in, tail)")
    print(f"total:      ~{fmt_duration(est.total_s)}")


def build(args: argparse.Namespace) -> int:
    speech_path = Path(args.speech)
    speech = load_speech(speech_path)
    meta = speech.meta
    mode = meta.get("mode", "sleep")
    bed = args.bed or ("brown" if mode == "sleep" else "none")
    if bed not in ("brown", "none") and not Path(bed).is_file():
        raise PepTalkError(f"--bed must be brown, none or an audio file; {bed!r} is none of these")
    tail = args.fade_out  # silence appended so the fade-out never eats the last words
    env = load_env()
    cfg = voice_config(args, meta, env)

    if args.dry_run:
        print_dry_run(speech_path, speech, cfg, mode, bed, args.lead_in, tail)
        return 0

    api_key = env.get("ELEVENLABS_API_KEY", "").strip() or None
    require_ffmpeg()
    if not args.mock and not api_key:
        log("ELEVENLABS_API_KEY not set; sending without it — fine only if a proxy injects "
            "the key")
    out = Path(args.out) if args.out else default_out(speech_path)
    cache_dir = Path(args.cache_dir) if args.cache_dir else default_cache()

    with tempfile.TemporaryDirectory(prefix="pep_talk_") as tmp:
        work = Path(tmp)
        if args.mock:  # no key, no network
            paths, billed = fetch_segments(speech, None, cache_dir, work, mock=True,
                                           stitch=False, api_key=None)
            used = "mock"
        else:
            log(f"voice {cfg.voice_id}, model {cfg.model}")
            paths, billed = fetch_segments(speech, cfg, cache_dir, work, mock=False,
                                           stitch=not args.no_stitch, api_key=api_key)
            used = f"{cfg.voice_id} ({cfg.model})"

        log("assembling")
        pcm = bytearray(silence_pcm(args.lead_in))
        seg_iter = iter(paths)
        for item in speech.items:
            if isinstance(item, Pause):
                pcm += silence_pcm(item.seconds)
            else:
                pcm += decode_pcm(next(seg_iter))
        pcm += silence_pcm(tail)
        raw_wav = work / "voice_raw.wav"
        duration = write_wav(raw_wav, bytes(pcm))

        log("normalising loudness")
        norm_wav = work / "voice_norm.wav"
        loudnorm(raw_wav, norm_wav)

        log(f"mixing (bed: {bed}) and encoding")
        render(
            norm_wav, out, duration,
            bed=bed, bed_db=args.bed_db, bitrate=args.bitrate,
            title=meta.get("title") or speech_path.stem,
            fade_in=args.fade_in, fade_out=args.fade_out,
        )

    final = probe_duration(out)
    print(f"{out}  {fmt_duration(final)}  ({final:.1f} s)  chars billed: {billed:,}  "
          f"voice: {used}")
    return 0


# ---------------------------------------------------------------------------------------
# Talk metadata (shared by Telegram and pull requests)
# ---------------------------------------------------------------------------------------

STEM_DATE_RE = re.compile(r"^(\d{8})_")


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


def _audio_seconds(path: Path) -> int | None:
    """Whole seconds via ffprobe, or None when ffprobe is missing or fails."""
    if not shutil.which("ffprobe"):
        return None
    try:
        return round(probe_duration(path))
    except (PepTalkError, ValueError):
        return None


# ---------------------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------------------

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
TELEGRAM_MAX_BYTES = 50 * 1024 * 1024  # Bot API upload limit
TELEGRAM_CAPTION_MAX = 1024
TELEGRAM_PERFORMER = "Pep Talk"

TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")

TELEGRAM_HINT = (
    "the request to api.telegram.org was blocked or could not connect. In a Claude Code cloud "
    "environment, allow api.telegram.org in the environment's network access settings, and "
    "set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as environment variables."
)


def redact(text: str, token: str | None = None) -> str:
    """Hide the bot token: the exact value if known, and anything shaped like one."""
    if token:
        text = text.replace(token, "<token>")
    return TOKEN_RE.sub("bot<token>", text)


def hashtag(word: str) -> str | None:
    """``future-self`` -> ``#future_self``. Telegram links only letters, digits, underscores."""
    tag = re.sub(r"\W+", "_", word.strip().lower()).strip("_")
    if not tag or tag.replace("_", "").isdigit():
        return None
    return f"#{tag}"


def build_caption(talk: TalkMeta) -> str:
    """Plain-text caption: title, date · theme · mode, topic, then hashtags.

    Over the 1,024-character limit, the text above the hashtags is cut; the hashtags stay.
    """
    facts = " · ".join(
        x for x in (talk.day.isoformat() if talk.day else None, talk.theme, talk.mode) if x
    )
    head = "\n".join(x for x in (talk.title, facts, f"Topic: {talk.topic}") if x)
    words = ("pep talk", talk.mode or "", talk.theme or "", talk.topic)
    tags = " ".join(dict.fromkeys(t for t in map(hashtag, words) if t))
    tail = f"\n\n{tags}"
    room = TELEGRAM_CAPTION_MAX - len(tail)
    if len(head) > room:
        head = head[: room - 1].rstrip() + "…"
    return head + tail


def encode_multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, str, bytes]],
    boundary: str | None = None,
) -> tuple[bytes, str]:
    """multipart/form-data body and its Content-Type. ``files``: name -> (filename, type, data)."""
    boundary = boundary or uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode("utf-8") + b"\r\n"
    for name, (filename, ctype, data) in files.items():
        safe = re.sub(r'["\r\n]', "_", filename)
        out += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{safe}"\r\nContent-Type: {ctype}\r\n\r\n'
        ).encode("utf-8")
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def build_telegram_request(
    token: str,
    method: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, str, bytes]],
) -> urllib.request.Request:
    """One Bot API call. The token is in the URL path, so the URL is never printed raw."""
    body, ctype = encode_multipart(fields, files)
    return urllib.request.Request(
        TELEGRAM_API.format(token=token, method=method),
        data=body,
        headers={"Content-Type": ctype},
        method="POST",
    )


def _telegram_error(code: int, body: str) -> PepTalkError:
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    desc = data.get("description") if isinstance(data, dict) else None
    shown = desc or body.strip()[:300]
    if code in (401, 404):
        return PepTalkError(
            f"Telegram rejected the bot token (HTTP {code}: {shown}). Set TELEGRAM_BOT_TOKEN "
            "to the token BotFather gave, shaped 123456789:AA..."
        )
    if code == 400 and desc and "chat not found" in desc.lower():
        return PepTalkError(
            f"Telegram: {desc}. Open the bot in Telegram and send it /start first, then check "
            "TELEGRAM_CHAT_ID against message.chat.id in "
            "https://api.telegram.org/bot<token>/getUpdates."
        )
    if code == 403 and desc is None:
        return PepTalkError(f"HTTP 403 from a proxy, not Telegram: {shown}\n{TELEGRAM_HINT}")
    if code == 403:
        return PepTalkError(
            f"Telegram refused (HTTP 403: {desc}). Unblock the bot and send it /start."
        )
    if code == 413:
        return PepTalkError("Telegram refused the upload as too large (HTTP 413); the Bot API "
                            "limit is 50 MB.")
    return PepTalkError(f"Telegram returned HTTP {code}: {shown}")


def telegram_call(
    token: str,
    method: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, str, bytes]],
) -> dict[str, object]:
    """Send one Bot API call; return its ``result``. Every error message is redacted."""
    req = build_telegram_request(token, method, fields, files)
    try:
        raw = _send(req, "Telegram", TELEGRAM_HINT, _telegram_error)
    except PepTalkError as exc:
        raise PepTalkError(redact(str(exc), token)) from None
    try:
        data = json.loads(raw)
    except ValueError:
        raise PepTalkError(f"Telegram {method} returned no JSON: {raw[:200]!r}") from None
    if not data.get("ok"):
        raise PepTalkError(redact(f"Telegram {method} failed: {data.get('description')}", token))
    return data.get("result") or {}


def telegram_config(env: dict[str, str]) -> tuple[str, str]:
    """Token and chat id from the environment, or NotConfigured naming what is missing."""
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = env.get("TELEGRAM_CHAT_ID", "").strip()
    missing = [n for n, v in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat)) if not v]
    if missing:
        raise NotConfigured(
            f"{' and '.join(missing)} not set, nothing sent. Set both in .env (see "
            ".env.example) or in the environment; the README explains how to create the bot "
            "and find the chat id."
        )
    return token, chat


def send_talk(mp3: Path, speech: Path, env: dict[str, str], *, dry_run: bool) -> None:
    """sendAudio, then the speech as a document replying to it.

    Missing configuration raises NotConfigured, in a dry run too, so a dry run answers
    "would this send?". A failed audio send raises. A failed speech send only warns:
    the talk got there.
    """
    token, chat = telegram_config(env)
    talk, _ = read_talk(mp3, speech)
    size = mp3.stat().st_size
    if size > TELEGRAM_MAX_BYTES:
        raise PepTalkError(
            f"{mp3} is {size / 1e6:.1f} MB; the Telegram Bot API takes at most 50 MB per "
            "upload. Rebuild with a lower --bitrate."
        )
    fields = {"title": talk.title, "performer": TELEGRAM_PERFORMER,
              "caption": build_caption(talk)}
    seconds = _audio_seconds(mp3)
    if seconds:
        fields["duration"] = str(seconds)
    doc_name = f"{mp3.stem}.md"  # named after the MP3, so the pair is easy to match

    if dry_run:
        print(f"POST       {TELEGRAM_API.format(token='<token>', method='sendAudio')}")
        print(f"chat_id:   {chat}")
        print(f"audio:     {mp3.name}  ({size / 1e6:.1f} MB)")
        for key in ("title", "performer", "duration"):
            if key in fields:
                print(f"{key + ':':<10} {fields[key]}")
        print("caption:")
        print("\n".join(f"    {line}" for line in fields["caption"].splitlines()))
        print(f"then:      sendDocument {doc_name} as a reply")
        print("dry run: nothing sent")
        return

    result =telegram_call(token, "sendAudio", {"chat_id": chat, **fields},
                           {"audio": (mp3.name, "audio/mpeg", mp3.read_bytes())})
    message_id = result.get("message_id")
    print(f"sent to Telegram: {mp3.name} (message {message_id})")
    reply = json.dumps({"message_id": message_id, "allow_sending_without_reply": True})
    try:
        telegram_call(token, "sendDocument", {"chat_id": chat, "reply_parameters": reply},
                      {"document": (doc_name, "text/markdown", speech.read_bytes())})
    except PepTalkError as exc:
        log(f"warning: audio sent, speech not attached: {exc}")
    else:
        print(f"  speech attached: {doc_name}")


def telegram(args: argparse.Namespace) -> int:
    send_talk(Path(args.mp3), Path(args.speech), load_env(), dry_run=args.dry_run)
    return 0


# ---------------------------------------------------------------------------------------
# GitHub pull request delivery
# ---------------------------------------------------------------------------------------

_OWNER_REPO = r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
GITHUB_REMOTE_RE = re.compile(
    r"^(?:(?:https?|ssh|git)://(?:[^@/]+@)?github\.com(?::\d+)?/"  # https://, ssh://
    r"|(?:[^@/:]+@)?github\.com:)"  # git@github.com:
    + _OWNER_REPO
)
# A Claude Code cloud session reaches GitHub through a local git proxy, e.g.
# http://local_proxy@127.0.0.1:12345/git/<owner>/<repo>. It may only accept pushes to the
# session's own branch, which is why `pr` can fall back to committing there.
PROXY_REMOTE_RE = re.compile(
    r"^https?://(?:[^@/]+@)?(?:127\.0\.0\.1|localhost)(?::\d+)?/git/" + _OWNER_REPO
)
FALLBACK_IDENTITY = {
    "GIT_AUTHOR_NAME": "pep-talk", "GIT_AUTHOR_EMAIL": "pep-talk@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "pep-talk", "GIT_COMMITTER_EMAIL": "pep-talk@users.noreply.github.com",
}
SETUP_HINT = (
    "Create a private GitHub repository, then: git remote add origin "
    "git@github.com:<you>/<repo>.git && git push -u origin main"
)


@dataclass(frozen=True)
class GitHubRepo:
    owner: str
    name: str
    proxy: bool = False  # reached through a local git proxy (Claude Code cloud session)

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.slug}"


def parse_github_remote(url: str) -> GitHubRepo | None:
    """owner/repo from an https or ssh github.com remote URL, or from a local git proxy's
    ``/git/<owner>/<repo>`` URL; None for any other host."""
    url = url.strip()
    if m := GITHUB_REMOTE_RE.match(url):
        return GitHubRepo(m["owner"], m["name"])
    if m := PROXY_REMOTE_RE.match(url):
        return GitHubRepo(m["owner"], m["name"], proxy=True)
    return None


def _safe_url(url: str) -> str:
    """A remote URL with any user:password@ part removed, fit to print."""
    return re.sub(r"//[^@/]+@", "//", url)


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None
         ) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    proc = _run(["git", *args], repo, env)
    if proc.returncode != 0:
        raise PepTalkError(f"git {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def github_remote(repo: Path, remote: str) -> GitHubRepo:
    """The GitHub repository behind ``remote``, or NotConfigured saying what is missing.

    Reads the configured URL, not ``git remote get-url``, so ``insteadOf`` rewrites
    do not hide which repository it is.
    """
    if not shutil.which("git"):
        raise NotConfigured("git is not installed, so there is nothing to push to.")
    if _run(["git", "rev-parse", "--git-dir"], repo).returncode != 0:
        raise NotConfigured(f"{repo} is not a git repository. {SETUP_HINT}")
    url = _run(["git", "config", "--get", f"remote.{remote}.url"], repo).stdout.strip()
    if not url:
        raise NotConfigured(f"no git remote {remote!r}. {SETUP_HINT}")
    gh_repo = parse_github_remote(url)
    if gh_repo is None:
        raise NotConfigured(
            f"remote {remote!r} is not on github.com ({_safe_url(url)}); pull request "
            "delivery only knows GitHub (directly, or through a Claude Code cloud git proxy)."
        )
    return gh_repo


def default_branch(repo: Path, remote: str) -> str:
    """The remote's default branch: the local origin/HEAD, else ask the remote, else main."""
    proc = _run(["git", "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD"], repo)
    prefix = f"refs/remotes/{remote}/"
    if proc.returncode == 0 and proc.stdout.strip().startswith(prefix):
        return proc.stdout.strip()[len(prefix):]
    proc = _run(["git", "ls-remote", "--symref", remote, "HEAD"], repo)
    m = re.search(r"^ref: refs/heads/(\S+)\s+HEAD$", proc.stdout, re.MULTILINE)
    return m.group(1) if m else "main"


def _gh_path() -> str | None:
    """The GitHub CLI, if installed. Swapped out by tests."""
    return shutil.which("gh")


def gh_ready(repo: Path) -> str | None:
    """Path to ``gh`` when it is installed and logged in to github.com, else None."""
    gh = _gh_path()
    if gh is None:
        return None
    if _run([gh, "auth", "status", "--hostname", "github.com"], repo).returncode != 0:
        log("gh is installed but not logged in (run: gh auth login); carrying on without it")
        return None
    return gh


def repo_visibility(gh: str, gh_repo: GitHubRepo, repo: Path) -> str:
    """PUBLIC, PRIVATE or INTERNAL, as gh reports it."""
    proc = _run([gh, "repo", "view", gh_repo.slug, "--json", "visibility",
                 "--jq", ".visibility"], repo)
    if proc.returncode != 0:
        raise NotConfigured(f"gh cannot see {gh_repo.slug}: {proc.stderr.strip()}")
    return proc.stdout.strip().upper()


def blob_url(gh_repo: GitHubRepo, branch: str, path: str) -> str:
    """Raw download link for a file on a branch; GitHub serves it to a logged-in browser."""
    return f"{gh_repo.url}/blob/{urllib.parse.quote(branch)}/{urllib.parse.quote(path)}?raw=true"


def compare_url(gh_repo: GitHubRepo, base: str, branch: str) -> str:
    """The page that opens a new pull request from ``branch`` into ``base``."""
    q = urllib.parse.quote
    return f"{gh_repo.url}/compare/{q(base)}...{q(branch)}?expand=1"


def build_pr_body(talk: TalkMeta, *, length: str | None, mp3_url: str, mp3_name: str,
                  speech_text: str) -> str:
    """Markdown body: the talk's facts, a link to the MP3, and the speech folded away."""
    facts = [
        ("Date", talk.day.isoformat() if talk.day else None),
        ("Theme", talk.theme),
        ("Mode", talk.mode),
        ("Topic", talk.topic),
        ("Length", length),
    ]
    lines = [f"## {talk.title}", ""]
    lines += [f"- **{k}:** {v}" for k, v in facts if v]
    lines += [
        "",
        f"**Listen:** [{mp3_name}]({mp3_url})",
        "",
        "<details>",
        "<summary>Speech</summary>",
        "",
        speech_text,
        "",
        "</details>",
        "",
    ]
    return "\n".join(lines)


def _identity_env(repo: Path) -> dict[str, str]:
    """os.environ plus a fallback git identity when none is configured (fresh containers)."""
    env = dict(os.environ)
    if not _run(["git", "config", "user.email"], repo).stdout.strip():
        env.update(FALLBACK_IDENTITY)
    return env


def current_branch(repo: Path) -> str | None:
    """The checked-out branch, or None when HEAD is detached."""
    proc = _run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], repo)
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def fetch_base(repo: Path, remote: str, base: str) -> str:
    """Fetch ``remote/base`` and return its commit id; NotConfigured if it does not exist."""
    tracking = f"refs/remotes/{remote}/{base}"
    proc = _run(["git", "fetch", "-q", remote, f"+refs/heads/{base}:{tracking}"], repo)
    if proc.returncode != 0:
        err = proc.stderr.strip()
        if "couldn't find remote ref" in err.lower():
            raise NotConfigured(
                f"branch {base!r} does not exist on {remote}. Push it first "
                f"(git push -u {remote} {base}), or pass --base."
            )
        raise PepTalkError(f"git fetch {remote} {base} failed: {err}")
    return git(repo, "rev-parse", f"{tracking}^{{commit}}")


def commit_talk(repo: Path, parent: str, files: dict[str, Path], message: str) -> str:
    """Commit ``files`` on top of ``parent`` without touching the working tree.

    Uses a throwaway index (GIT_INDEX_FILE), so the caller's index, working tree and
    current branch stay exactly as they were. Returns the new commit id.
    """
    with tempfile.TemporaryDirectory(prefix="pep_talk_pr_") as tmp:
        env = {**_identity_env(repo), "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(repo, "read-tree", parent, env=env)
        for path, src in files.items():
            blob = git(repo, "hash-object", "-w", "--", str(src.resolve()))
            git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = git(repo, "write-tree", env=env)
        return git(repo, "commit-tree", tree, "-p", parent, "-m", message, env=env)


def commit_on_current_branch(repo: Path, remote: str, base: str, files: dict[str, Path],
                             folder: str, message: str) -> str:
    """Commit ``files`` onto the checked-out branch and push it; return the branch name.

    For a git proxy that only accepts the session's own branch. Only ``folder`` goes into
    the commit: anything else staged or modified stays exactly as it was.
    """
    branch = current_branch(repo)
    if branch is None:
        raise PepTalkError("HEAD is detached, so there is no current branch to commit the "
                           "talk onto. Check out a branch first, or pass --head.")
    if branch == base:
        raise PepTalkError(
            f"the current branch is {base!r}, the pull request's base, so committing the talk "
            "there would leave nothing to review. Switch to a working branch first."
        )
    for path, src in files.items():
        dst = repo / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
    git(repo, "add", "-f", "--", folder)  # -f: *.mp3 is gitignored
    if _run(["git", "diff", "--cached", "--quiet", "HEAD", "--", folder], repo).returncode:
        git(repo, "commit", "-q", "-m", message, "--", folder, env=_identity_env(repo))
    else:
        log(f"{folder} is already committed on {branch} unchanged")
    log(f"pushing {branch} to {remote}")
    proc = _run(["git", "push", "-q", remote, "HEAD"], repo)
    if proc.returncode != 0:
        raise PepTalkError(f"git push of {branch} to {remote} failed: {proc.stderr.strip()}")
    return branch


def deliver_pr(
    mp3: Path,
    speech: Path,
    *,
    repo: Path,
    remote: str,
    base: str | None,
    head: str | None,
    allow_public: bool,
    dry_run: bool,
) -> int:
    """Put ``talks/<stem>/`` on a head branch and open a pull request for it.

    The head is ``talk/<stem>`` (or ``--head``), committed with plumbing on top of the
    base and force-pushed. When ``--head`` names the current branch, or a cloud git proxy
    refuses the push, the talk is committed onto the current branch instead.

    Returns 0 when the pull request is open (new or already there), EXIT_NO_GH when the
    branch is pushed but ``gh`` is missing, so the caller opens the PR another way.
    """
    talk, body = read_talk(mp3, speech)
    gh_repo = github_remote(repo, remote)
    stem = mp3.stem
    folder = f"talks/{stem}"
    files = {f"{folder}/{stem}.mp3": mp3, f"{folder}/{stem}.md": speech}
    base = base or default_branch(repo, remote)
    head = head or f"talk/{stem}"
    if head == base:
        raise PepTalkError(f"--head {head} is the base branch; a pull request needs two "
                           "different branches.")
    current = current_branch(repo)
    on_current = head == current
    title = talk.title
    message = f"talk: {title}"

    # Visibility before anything is pushed: the speech is built from personal notes.
    gh = gh_ready(repo)
    visibility = repo_visibility(gh, gh_repo, repo) if gh else None
    if visibility == "PUBLIC" and not allow_public:
        raise NotConfigured(
            f"{gh_repo.slug} is a PUBLIC repository, so nothing was pushed. A talk is "
            "written from your personal notes, and a branch or pull request there would "
            "publish it to anyone. Deliver to a private repository, or pass --allow-public "
            "if you really mean to share it."
        )
    body_file = repo / ".cache" / "pr" / f"{stem}.md"

    if dry_run:
        if on_current:
            route = f"{head}  (commit onto the current branch, then push it)"
        else:
            route = f"{head}  (force-pushed)"
            if gh_repo.proxy:
                route += f"; if the git proxy refuses, commit onto {current or '(detached)'}"
        print(f"repo:      {gh_repo.slug}  ({visibility or 'visibility not checked: no gh'})")
        print(f"base:      {base}  (from {remote})")
        print(f"head:      {route}")
        for path, src in files.items():
            print(f"file:      {path}  ({src.stat().st_size / 1e6:.1f} MB)")
        print(f"commit:    {message}")
        print(f"body:      {body_file}")
        print("then:      gh pr create" if gh else
              f"then:      no gh; open {compare_url(gh_repo, base, head)}")
        print("dry run: nothing pushed")
        return 0

    parent = fetch_base(repo, remote, base)
    if on_current:
        head = commit_on_current_branch(repo, remote, base, files, folder, message)
        delivery = "current-branch"
    else:
        commit = commit_talk(repo, parent, files, message)
        log(f"pushing {commit[:12]} to {remote}/{head}")
        proc = _run(["git", "push", "--force", "-q", remote, f"{commit}:refs/heads/{head}"],
                    repo)
        if proc.returncode == 0:
            delivery = "talk-branch"
        elif gh_repo.proxy:
            reason = (proc.stderr.strip().splitlines() or ["refused"])[-1]
            log(f"the git proxy refused {head} ({reason}); committing the talk onto the "
                "current branch instead")
            head = commit_on_current_branch(repo, remote, base, files, folder, message)
            delivery = "current-branch"
        else:
            raise PepTalkError(
                f"git push to {remote} failed: {proc.stderr.strip()}\n"
                f"Check that this machine can push to {gh_repo.slug}."
            )

    seconds = _audio_seconds(mp3)
    body_file.parent.mkdir(parents=True, exist_ok=True)
    body_file.write_text(build_pr_body(
        talk,
        length=fmt_duration(seconds) if seconds else None,
        mp3_url=blob_url(gh_repo, head, f"{folder}/{stem}.mp3"),
        mp3_name=mp3.name,
        speech_text=plain_text(body),
    ), encoding="utf-8")

    # Stable `key: value` lines: the skill parses them, above all on the exit-4 path.
    print(f"delivery: {delivery}")
    print(f"head: {head}")
    print(f"base: {base}")
    if gh is None:
        print(f"title: {title}")
        print(f"body_file: {body_file}")
        print(f"compare_url: {compare_url(gh_repo, base, head)}")
        log("gh is not available to open the pull request; repository visibility was not "
            "checked, so make sure it is private.")
        return EXIT_NO_GH

    existing = _run([gh, "pr", "list", "--repo", gh_repo.slug, "--head", head,
                     "--state", "open", "--json", "url", "--jq", ".[0].url // empty"], repo)
    if existing.returncode == 0 and existing.stdout.strip():
        log("pull request already open; its branch is updated")
        print(f"pull_request: {existing.stdout.strip()}")
        return 0
    created = _run([gh, "pr", "create", "--repo", gh_repo.slug, "--base", base,
                    "--head", head, "--title", title, "--body-file", str(body_file)], repo)
    if created.returncode != 0:
        raise PepTalkError(
            f"{head} pushed, but gh pr create failed: {created.stderr.strip()}\n"
            f"Open it by hand: {compare_url(gh_repo, base, head)}"
        )
    print(f"pull_request: {created.stdout.strip().splitlines()[-1]}")
    return 0


def pr(args: argparse.Namespace) -> int:
    return deliver_pr(Path(args.mp3), Path(args.speech), repo=REPO, remote=args.remote,
                      base=args.base, head=args.head, allow_public=args.allow_public,
                      dry_run=args.dry_run)


# ---------------------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------------------

OK, FAIL, SKIP = "✓", "✗", "–"


@dataclass(frozen=True)
class Check:
    mark: str
    name: str
    detail: str
    hint: str = ""

    def line(self) -> str:
        fix = f"  -> {self.hint}" if self.hint else ""
        return f"{self.mark} {self.name:<15} {self.detail}{fix}"


def _mp3_encoder_ok() -> bool:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    return proc.returncode == 0 and "libmp3lame" in proc.stdout


def elevenlabs_subscription(api_key: str) -> dict[str, object]:
    """GET /v1/user/subscription, one try. Raises urllib errors to the caller."""
    req = urllib.request.Request(SUBSCRIPTION_URL, headers={"xi-api-key": api_key})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def check_python() -> Check:
    v = sys.version_info
    ok = v >= (3, 10)
    return Check(OK if ok else FAIL, "python", f"{v.major}.{v.minor}.{v.micro}",
                 "" if ok else "install Python 3.10 or newer")


def check_ffmpeg() -> Check:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return Check(FAIL, "ffmpeg", "ffmpeg/ffprobe not found",
                     "brew install ffmpeg (macOS); sh scripts/pep_talk.sh build installs it "
                     "on Debian/Ubuntu")
    if not _mp3_encoder_ok():
        return Check(FAIL, "ffmpeg", "found, but without the libmp3lame MP3 encoder",
                     "install an ffmpeg build with libmp3lame")
    return Check(OK, "ffmpeg", "ffmpeg + ffprobe with libmp3lame")


def check_elevenlabs(env: dict[str, str], offline: bool) -> Check:
    key = env.get("ELEVENLABS_API_KEY", "").strip()
    name = "ElevenLabs key"
    if not key:
        return Check(SKIP, name, "ELEVENLABS_API_KEY not set; builds send no key, which works "
                                 "only if a proxy injects it (cloud network secret)", KEY_HINT)
    where = f"set (from {env_source('ELEVENLABS_API_KEY')})"
    if offline:
        return Check(OK, name, f"{where}, not checked (--offline)")
    try:
        sub = elevenlabs_subscription(key)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        if exc.code == 401 and "missing_permissions" in body:
            return Check(OK, name, f"{where}; quota not readable (key lacks User read "
                                   "permission, rendering still works)")
        if exc.code == 401:
            return Check(FAIL, name, f"{where}, but ElevenLabs rejected it (HTTP 401)", KEY_HINT)
        return Check(SKIP, name, f"{where}; quota check returned HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return Check(SKIP, name, f"{where}; could not reach api.elevenlabs.io ({reason})",
                     "Claude Code cloud: allow api.elevenlabs.io in network access")
    used, limit = sub.get("character_count"), sub.get("character_limit")
    if isinstance(used, int) and isinstance(limit, int):
        tier = sub.get("tier") or "?"
        return Check(OK, name, f"{where}; {limit - used:,} of {limit:,} characters left "
                               f"(tier {tier})")
    return Check(OK, name, f"{where}; accepted")


def check_voice(env: dict[str, str]) -> Check:
    voice = resolve_voice_id(None, {}, env)
    source = "ELEVENLABS_VOICE_ID" if env.get("ELEVENLABS_VOICE_ID") else "default, premade George"
    return Check(OK, "voice", f"{voice} ({source}); a speech's voice_id or --voice overrides it")


def check_telegram(env: dict[str, str]) -> Check:
    names = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    missing = [n for n in names if not env.get(n, "").strip()]
    if not missing:
        return Check(OK, "Telegram", "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID set")
    if len(missing) == 2:
        return Check(SKIP, "Telegram", "not set (optional); telegram delivery is skipped",
                     "see .env.example")
    return Check(FAIL, "Telegram", f"{missing[0]} missing; both are needed", "see .env.example")


def check_github(repo: Path, remote: str, offline: bool) -> list[Check]:
    try:
        gh_repo = github_remote(repo, remote)
    except NotConfigured as exc:
        return [Check(SKIP, "git remote", f"{exc} (optional: needed for pr)")]
    checks = [Check(OK, "git remote", f"{remote} -> {gh_repo.slug}")]
    gh = _gh_path()
    if gh is None:
        checks.append(Check(SKIP, "gh", "not installed; pr pushes the branch and prints a "
                                        "link to open it (exit 4)",
                            "https://cli.github.com"))
        return checks
    if _run([gh, "auth", "status", "--hostname", "github.com"], repo).returncode != 0:
        checks.append(Check(SKIP, "gh", "installed, not logged in", "gh auth login"))
        return checks
    checks.append(Check(OK, "gh", "logged in to github.com"))
    if offline:
        checks.append(Check(SKIP, "repo visibility", "not checked (--offline)"))
        return checks
    try:
        visibility = repo_visibility(gh, gh_repo, repo)
    except NotConfigured as exc:
        checks.append(Check(FAIL, "repo visibility", str(exc)))
        return checks
    if visibility == "PUBLIC":
        checks.append(Check(FAIL, "repo visibility", f"{gh_repo.slug} is PUBLIC; pr refuses "
                                                     "it, speeches are personal",
                            "deliver to a private repository"))
    else:
        checks.append(Check(OK, "repo visibility", visibility))
    return checks


def check_context(repo: Path) -> list[Check]:
    profile, sources = repo / "context" / "profile.md", repo / "context" / "sources.md"
    return [
        Check(OK, "profile", "context/profile.md present") if profile.is_file() else
        Check(SKIP, "profile", "context/profile.md missing",
              "cp context/profile.example.md context/profile.md and fill it in"),
        Check(OK, "sources", "context/sources.md present") if sources.is_file() else
        Check(SKIP, "sources", "context/sources.md missing",
              "list where your notes live; see context/README.md"),
    ]


def doctor(args: argparse.Namespace) -> int:
    env = load_env()
    ffmpeg_check = check_ffmpeg()
    key_check = check_elevenlabs(env, args.offline)
    checks = [check_python(), ffmpeg_check, key_check, check_voice(env), check_telegram(env),
              *check_github(REPO, args.remote, args.offline), *check_context(REPO)]
    for check in checks:
        print(check.line())
    ready = all(c.mark != FAIL for c in (checks[0], ffmpeg_check, key_check))
    print("ready to render" if ready else "not ready to render: fix the ✗ lines above")
    return 0 if ready else 1


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="speech Markdown -> MP3")
    b.add_argument("speech", help="speech Markdown file")
    b.add_argument("--out", help="output MP3 (default out/<speech stem>.mp3)")
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
    b.add_argument("--cache-dir", help="segment cache (default .cache/segments)")
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
    "build": build,
    "telegram": telegram,
    "pr": pr,
    "doctor": doctor,
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
