"""The ``build`` command: speech file to one MP3, through a per-segment cache."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from .audio import (
    decode_pcm,
    loudnorm,
    make_mock_mp3,
    probe_duration,
    render,
    require_ffmpeg,
    silence_pcm,
    write_wav,
)
from .common import PepTalkError, load_env, log, make_dir, state_dir
from .elevenlabs import (
    DEFAULT_MODEL,
    VoiceConfig,
    build_request,
    cache_key,
    resolve_voice_id,
    synthesize,
)
from .speech import (
    CHAR_BUDGET,
    CHARS_PER_SECOND,
    COST_PER_1K_CHARS,
    Pause,
    SpeechFile,
    estimate,
    estimate_seconds,
    fmt_duration,
    load_speech,
)


def default_out(speech_path: Path) -> Path:
    """.pep-talk/out/<speech stem>.mp3 in the project."""
    return state_dir() / "out" / f"{speech_path.stem}.mp3"


def default_cache() -> Path:
    return state_dir() / "cache" / "segments"


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
        make_dir(cache_dir)
    for n, seg in enumerate(segments):
        label = f"  [{n + 1:>2}/{len(segments)}] {len(seg.text):>5} chars"
        if mock:
            path = work / f"mock_{n:03d}.mp3"
            make_mock_mp3(path, estimate_seconds(seg.text))
            log(f"{label}  mock")
            paths.append(path)
            continue
        assert cfg is not None
        path = cache_dir / f"{cache_key(cfg, seg.text)}.mp3"
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


def run(args: argparse.Namespace) -> int:
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
