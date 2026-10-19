"""The local git repository and its GitHub remote: remote parsing, fetches, commits, pushes.

Everything here runs plain ``git``; the GitHub CLI lives in github_pr.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .common import NotConfigured, PepTalkError, log

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


def safe_url(url: str) -> str:
    """A remote URL with any user:password@ part removed, fit to print."""
    return re.sub(r"//[^@/]+@", "//", url)


def capture(cmd: list[str], cwd: Path, env: dict[str, str] | None = None
        ) -> subprocess.CompletedProcess[str]:
    """Run a command in ``cwd`` and capture its output; the caller checks the return code."""
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


def git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    proc = capture(["git", *args], repo, env)
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
    if capture(["git", "rev-parse", "--git-dir"], repo).returncode != 0:
        raise NotConfigured(f"{repo} is not a git repository. {SETUP_HINT}")
    url = capture(["git", "config", "--get", f"remote.{remote}.url"], repo).stdout.strip()
    if not url:
        raise NotConfigured(f"no git remote {remote!r}. {SETUP_HINT}")
    gh_repo = parse_github_remote(url)
    if gh_repo is None:
        raise NotConfigured(
            f"remote {remote!r} is not on github.com ({safe_url(url)}); pull request "
            "delivery only knows GitHub (directly, or through a Claude Code cloud git proxy)."
        )
    return gh_repo


def default_branch(repo: Path, remote: str) -> str:
    """The remote's default branch: the local origin/HEAD, else ask the remote, else main."""
    proc = capture(["git", "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD"], repo)
    prefix = f"refs/remotes/{remote}/"
    if proc.returncode == 0 and proc.stdout.strip().startswith(prefix):
        return proc.stdout.strip()[len(prefix):]
    proc = capture(["git", "ls-remote", "--symref", remote, "HEAD"], repo)
    m = re.search(r"^ref: refs/heads/(\S+)\s+HEAD$", proc.stdout, re.MULTILINE)
    return m.group(1) if m else "main"


def current_branch(repo: Path) -> str | None:
    """The checked-out branch, or None when HEAD is detached."""
    proc = capture(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], repo)
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def _identity_env(repo: Path) -> dict[str, str]:
    """os.environ plus a fallback git identity when none is configured (fresh containers)."""
    env = dict(os.environ)
    if not capture(["git", "config", "user.email"], repo).stdout.strip():
        env.update(FALLBACK_IDENTITY)
    return env


def fetch_base(repo: Path, remote: str, base: str) -> str:
    """Fetch ``remote/base`` and return its commit id; NotConfigured if it does not exist."""
    tracking = f"refs/remotes/{remote}/{base}"
    proc = capture(["git", "fetch", "-q", remote, f"+refs/heads/{base}:{tracking}"], repo)
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


def push_commit(repo: Path, remote: str, commit: str, branch: str
                ) -> subprocess.CompletedProcess[str]:
    """Force-push ``commit`` to ``remote``'s ``branch``; the caller handles a refusal."""
    log(f"pushing {commit[:12]} to {remote}/{branch}")
    return capture(["git", "push", "--force", "-q", remote, f"{commit}:refs/heads/{branch}"],
                   repo)


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
    git(repo, "add", "-f", "--", folder)  # -f: *.mp3 may be gitignored
    if capture(["git", "diff", "--cached", "--quiet", "HEAD", "--", folder], repo).returncode:
        git(repo, "commit", "-q", "-m", message, "--", folder, env=_identity_env(repo))
    else:
        log(f"{folder} is already committed on {branch} unchanged")
    log(f"pushing {branch} to {remote}")
    proc = capture(["git", "push", "-q", remote, "HEAD"], repo)
    if proc.returncode != 0:
        raise PepTalkError(f"git push of {branch} to {remote} failed: {proc.stderr.strip()}")
    return branch
