"""Shared plumbing: errors, logging, where files live, .env loading, HTTP retries."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
SKILL_DIR = SCRIPTS_DIR.parent  # the self-contained skill folder, copyable into any project
SKILL_ENV = SKILL_DIR / ".env"
STATE_DIRNAME = ".pep-talk"  # generated files, in the project; never inside .claude/

HTTP_TIMEOUT = 120
HTTP_TRIES = 3

EXIT_NOT_CONFIGURED = 3  # delivery not set up, or refused: the skill skips it and says so
EXIT_NO_GH = 4  # pr: branch pushed, pull request left for another tool to open

TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")

# Swapped out by tests so retries do not really wait.
_sleep = time.sleep


class PepTalkError(Exception):
    """A user-facing failure: printed without a traceback, exit code 1."""


class NotConfigured(PepTalkError):
    """A delivery channel is not set up, or refuses on purpose; exit code 3."""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------------------


def project_dir() -> Path:
    """The git work tree around the current directory, else the current directory."""
    cwd = Path.cwd()
    try:
        proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                              capture_output=True, text=True)
    except OSError:  # git not installed
        return cwd
    top = proc.stdout.strip()
    return Path(top) if proc.returncode == 0 and top else cwd


def state_dir() -> Path:
    """The project's ``.pep-talk/`` folder, where everything generated goes."""
    return project_dir() / STATE_DIRNAME


def make_dir(path: Path) -> Path:
    """``mkdir -p path``. Inside a ``.pep-talk/`` folder, first give that folder a
    ``.gitignore`` of ``*``: generated files stay out of git without touching the
    project's own .gitignore."""
    for folder in (path, *path.parents):
        if folder.name == STATE_DIRNAME:
            folder.mkdir(parents=True, exist_ok=True)
            ignore = folder / ".gitignore"
            if not ignore.exists():
                ignore.write_text("*\n", encoding="utf-8")
            break
    path.mkdir(parents=True, exist_ok=True)
    return path


def shown(path: Path) -> str:
    """``path`` for a message: relative to the project when inside it, else under ``~``."""
    path = path.resolve()
    for base, prefix in ((project_dir(), ""), (Path.home(), "~/")):
        try:
            return prefix + str(path.relative_to(base.resolve()))
        except ValueError:
            continue
    return str(path)


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


def env_files() -> list[Path]:
    """The .env files, strongest first: the skill folder's, then the project root's."""
    return [SKILL_ENV, project_dir() / ".env"]


def load_env() -> dict[str, str]:
    """The real environment over the skill's .env over the project's .env.

    An empty value never blanks out one from a weaker layer.
    """
    env: dict[str, str] = {}
    for layer in [*map(read_dotenv, reversed(env_files())), os.environ]:
        for key, value in layer.items():
            if value or key not in env:
                env[key] = value
    return env


def env_source(name: str) -> str:
    """Where a variable came from, for messages: never its value."""
    if os.environ.get(name):
        return "environment"
    for path in env_files():
        if read_dotenv(path).get(name):
            return shown(path)
    return ".env"


# ---------------------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------------------


def http_send(
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


def redact(text: str, token: str | None = None) -> str:
    """Hide a Telegram bot token: the exact value if known, and anything shaped like one."""
    if token:
        text = text.replace(token, "<token>")
    return TOKEN_RE.sub("bot<token>", text)
