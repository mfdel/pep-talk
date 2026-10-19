"""The ``doctor`` command: check the setup, one line per item, secrets never printed."""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from .audio import mp3_encoder_ok
from .common import (
    SCRIPTS_DIR,
    SKILL_DIR,
    STATE_DIRNAME,
    NotConfigured,
    env_source,
    load_env,
    project_dir,
    shown,
)
from .elevenlabs import key_hint, resolve_voice_id, subscription
from .github_pr import gh_logged_in, gh_path, repo_visibility
from .gitrepo import github_remote

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


def check_python() -> Check:
    v = sys.version_info
    ok = v >= (3, 10)
    return Check(OK if ok else FAIL, "python", f"{v.major}.{v.minor}.{v.micro}",
                 "" if ok else "install Python 3.10 or newer")


def check_ffmpeg() -> Check:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return Check(FAIL, "ffmpeg", "ffmpeg/ffprobe not found",
                     f"brew install ffmpeg (macOS); sh {shown(SCRIPTS_DIR / 'pep_talk.sh')} "
                     "build installs it on Debian/Ubuntu")
    if not mp3_encoder_ok():
        return Check(FAIL, "ffmpeg", "found, but without the libmp3lame MP3 encoder",
                     "install an ffmpeg build with libmp3lame")
    return Check(OK, "ffmpeg", "ffmpeg + ffprobe with libmp3lame")


def check_elevenlabs(env: dict[str, str], offline: bool) -> Check:
    key = env.get("ELEVENLABS_API_KEY", "").strip()
    name = "ElevenLabs key"
    if not key:
        return Check(SKIP, name, "ELEVENLABS_API_KEY not set; builds send no key, which works "
                                 "only if a proxy injects it (cloud network secret)", key_hint())
    where = f"set (from {env_source('ELEVENLABS_API_KEY')})"
    if offline:
        return Check(OK, name, f"{where}, not checked (--offline)")
    try:
        sub = subscription(key)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
        if exc.code == 401 and "missing_permissions" in body:
            return Check(OK, name, f"{where}; quota not readable (key lacks User read "
                                   "permission, rendering still works)")
        if exc.code == 401:
            return Check(FAIL, name, f"{where}, but ElevenLabs rejected it (HTTP 401)",
                         key_hint())
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
    hint = f"see {shown(SKILL_DIR / '.env.example')}"
    if len(missing) == 2:
        return Check(SKIP, "Telegram", "not set (optional); telegram delivery is skipped", hint)
    return Check(FAIL, "Telegram", f"{missing[0]} missing; both are needed", hint)


def check_github(repo: Path, remote: str, offline: bool) -> list[Check]:
    try:
        gh_repo = github_remote(repo, remote)
    except NotConfigured as exc:
        return [Check(SKIP, "git remote", f"{exc} (optional: needed for pr)")]
    checks = [Check(OK, "git remote", f"{remote} -> {gh_repo.slug}")]
    gh = gh_path()
    if gh is None:
        checks.append(Check(SKIP, "gh", "not installed; pr pushes the branch and prints a "
                                        "link to open it (exit 4)",
                            "https://cli.github.com"))
        return checks
    if not gh_logged_in(gh, repo):
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


def check_context(skill_dir: Path) -> list[Check]:
    context = skill_dir / "context"
    profile, sources = context / "profile.md", context / "sources.md"
    example = context / "profile.example.md"
    return [
        Check(OK, "profile", f"{shown(profile)} present") if profile.is_file() else
        Check(SKIP, "profile", f"{shown(profile)} missing",
              f"cp {shown(example)} {shown(profile)} and fill it in"),
        Check(OK, "sources", f"{shown(sources)} present") if sources.is_file() else
        Check(SKIP, "sources", f"{shown(sources)} missing",
              f"list where your notes live; see {shown(context / 'README.md')}"),
    ]


def check_project(project: Path) -> Check:
    """Where generated files go: decided by the current directory, so worth stating."""
    return Check(OK, "project", f"{project}; speeches, briefs, MP3s and caches go in "
                                f"{STATE_DIRNAME}/ there (ignored by git)")


def run(args: argparse.Namespace) -> int:
    env = load_env()
    project = project_dir()
    ffmpeg_check = check_ffmpeg()
    key_check = check_elevenlabs(env, args.offline)
    checks = [check_python(), ffmpeg_check, key_check, check_voice(env), check_telegram(env),
              *check_github(project, args.remote, args.offline), *check_context(SKILL_DIR),
              check_project(project)]
    for check in checks:
        print(check.line())
    ready = all(c.mark != FAIL for c in (checks[0], ffmpeg_check, key_check))
    print("ready to render" if ready else "not ready to render: fix the ✗ lines above")
    return 0 if ready else 1
