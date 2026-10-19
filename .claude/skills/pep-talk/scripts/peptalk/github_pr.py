"""The ``pr`` command: deliver the MP3 and its speech as a pull request on your repository.

The talk goes in ``talks/<stem>/`` on a head branch; ``gh`` opens the pull request when it
is installed, and checks first that the repository is not public.
"""

from __future__ import annotations

import argparse
import shutil
import urllib.parse
from pathlib import Path

from .audio import audio_seconds
from .common import (
    EXIT_NO_GH,
    STATE_DIRNAME,
    NotConfigured,
    PepTalkError,
    log,
    make_dir,
    project_dir,
)
from .gitrepo import (
    GitHubRepo,
    capture,
    commit_on_current_branch,
    commit_talk,
    current_branch,
    default_branch,
    fetch_base,
    github_remote,
    push_commit,
)
from .speech import TalkMeta, fmt_duration, plain_text, read_talk


def gh_path() -> str | None:
    """The GitHub CLI, if installed. Swapped out by tests."""
    return shutil.which("gh")


def gh_logged_in(gh: str, repo: Path) -> bool:
    return capture([gh, "auth", "status", "--hostname", "github.com"], repo).returncode == 0


def gh_ready(repo: Path) -> str | None:
    """Path to ``gh`` when it is installed and logged in to github.com, else None."""
    gh = gh_path()
    if gh is None:
        return None
    if not gh_logged_in(gh, repo):
        log("gh is installed but not logged in (run: gh auth login); carrying on without it")
        return None
    return gh


def repo_visibility(gh: str, gh_repo: GitHubRepo, repo: Path) -> str:
    """PUBLIC, PRIVATE or INTERNAL, as gh reports it."""
    proc = capture([gh, "repo", "view", gh_repo.slug, "--json", "visibility",
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
    body_file = repo / STATE_DIRNAME / "cache" / "pr" / f"{stem}.md"

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
        proc = push_commit(repo, remote, commit_talk(repo, parent, files, message), head)
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

    seconds = audio_seconds(mp3)
    make_dir(body_file.parent)
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

    existing = capture([gh, "pr", "list", "--repo", gh_repo.slug, "--head", head,
                    "--state", "open", "--json", "url", "--jq", ".[0].url // empty"], repo)
    if existing.returncode == 0 and existing.stdout.strip():
        log("pull request already open; its branch is updated")
        print(f"pull_request: {existing.stdout.strip()}")
        return 0
    created = capture([gh, "pr", "create", "--repo", gh_repo.slug, "--base", base,
                   "--head", head, "--title", title, "--body-file", str(body_file)], repo)
    if created.returncode != 0:
        raise PepTalkError(
            f"{head} pushed, but gh pr create failed: {created.stderr.strip()}\n"
            f"Open it by hand: {compare_url(gh_repo, base, head)}"
        )
    print(f"pull_request: {created.stdout.strip().splitlines()[-1]}")
    return 0


def run(args: argparse.Namespace) -> int:
    return deliver_pr(Path(args.mp3), Path(args.speech), repo=project_dir(),
                      remote=args.remote, base=args.base, head=args.head,
                      allow_public=args.allow_public, dry_run=args.dry_run)
