"""ffmpeg: mock tones, raw PCM and WAV, loudness, the noise bed, and the final MP3."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

from .common import SCRIPTS_DIR, PepTalkError, make_dir, shown

SAMPLE_RATE = 44_100


def ffmpeg_hint() -> str:
    return (
        f"ffmpeg/ffprobe not found. Run `sh {shown(SCRIPTS_DIR / 'pep_talk.sh')} ...`, which "
        "installs it on Debian/Ubuntu, or install it yourself (macOS: `brew install ffmpeg`)."
    )


def require_ffmpeg() -> None:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise PepTalkError(ffmpeg_hint())


def mp3_encoder_ok() -> bool:
    """True when the installed ffmpeg can encode MP3 (libmp3lame)."""
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    return proc.returncode == 0 and "libmp3lame" in proc.stdout


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


def audio_seconds(path: Path) -> int | None:
    """Whole seconds via ffprobe, or None when ffprobe is missing or fails."""
    if not shutil.which("ffprobe"):
        return None
    try:
        return round(probe_duration(path))
    except (PepTalkError, ValueError):
        return None


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
    make_dir(out.parent)
    ffmpeg(
        *args, "-filter_complex", graph, "-map", "[out]",
        "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "libmp3lame", "-b:a", bitrate,
        "-id3v2_version", "3", "-metadata", f"title={title}", str(out),
    )
