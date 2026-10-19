"""The ``telegram`` command: the MP3, then its speech as a reply, to your own bot chat."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
import uuid
from pathlib import Path

from .audio import audio_seconds
from .common import SKILL_ENV, NotConfigured, PepTalkError, http_send, load_env, log, redact, shown
from .speech import TalkMeta, read_talk

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
TELEGRAM_MAX_BYTES = 50 * 1024 * 1024  # Bot API upload limit
TELEGRAM_CAPTION_MAX = 1024
TELEGRAM_PERFORMER = "Pep Talk"

TELEGRAM_HINT = (
    "the request to api.telegram.org was blocked or could not connect. In a Claude Code cloud "
    "environment, allow api.telegram.org in the environment's network access settings, and "
    "set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as environment variables."
)


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
    shown_body = desc or body.strip()[:300]
    if code in (401, 404):
        return PepTalkError(
            f"Telegram rejected the bot token (HTTP {code}: {shown_body}). Set "
            "TELEGRAM_BOT_TOKEN to the token BotFather gave, shaped 123456789:AA..."
        )
    if code == 400 and desc and "chat not found" in desc.lower():
        return PepTalkError(
            f"Telegram: {desc}. Open the bot in Telegram and send it /start first, then check "
            "TELEGRAM_CHAT_ID against message.chat.id in "
            "https://api.telegram.org/bot<token>/getUpdates."
        )
    if code == 403 and desc is None:
        return PepTalkError(f"HTTP 403 from a proxy, not Telegram: {shown_body}\n{TELEGRAM_HINT}")
    if code == 403:
        return PepTalkError(
            f"Telegram refused (HTTP 403: {desc}). Unblock the bot and send it /start."
        )
    if code == 413:
        return PepTalkError("Telegram refused the upload as too large (HTTP 413); the Bot API "
                            "limit is 50 MB.")
    return PepTalkError(f"Telegram returned HTTP {code}: {shown_body}")


def telegram_call(
    token: str,
    method: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, str, bytes]],
) -> dict[str, object]:
    """Send one Bot API call; return its ``result``. Every error message is redacted."""
    req = build_telegram_request(token, method, fields, files)
    try:
        raw = http_send(req, "Telegram", TELEGRAM_HINT, _telegram_error)
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
            f"{' and '.join(missing)} not set, nothing sent. Set both in {shown(SKILL_ENV)} or "
            "in the environment; .env.example beside it says how to create the bot and find "
            "the chat id."
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
    seconds = audio_seconds(mp3)
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

    result = telegram_call(token, "sendAudio", {"chat_id": chat, **fields},
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


def run(args: argparse.Namespace) -> int:
    send_talk(Path(args.mp3), Path(args.speech), load_env(), dry_run=args.dry_run)
    return 0
