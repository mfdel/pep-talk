"""ElevenLabs: voice settings, text-to-speech requests, and what their errors mean."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass

from .common import SKILL_DIR, PepTalkError, http_send, shown

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
SUBSCRIPTION_URL = "https://api.elevenlabs.io/v1/user/subscription"
DEFAULT_MODEL = "eleven_v4"
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # ElevenLabs premade voice "George"
STITCH_CHARS = 1_000  # max context sent as previous_text / next_text

NETWORK_HINT = (
    "the request to api.elevenlabs.io was blocked or could not connect. In a Claude Code cloud "
    "environment, allow api.elevenlabs.io in the environment's network access settings."
)


def key_hint() -> str:
    """How to set the key, naming the skill folder's .env wherever it lives."""
    return (
        f"copy {shown(SKILL_DIR / '.env.example')} to .env beside it and set "
        "ELEVENLABS_API_KEY to a key from https://elevenlabs.io/app/settings/api-keys"
    )


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


def synthesize(req: urllib.request.Request) -> bytes:
    """One ElevenLabs request."""
    return http_send(req, "ElevenLabs", NETWORK_HINT,
                     lambda code, body: PepTalkError(_http_error_message(code, body)))


def subscription(api_key: str) -> dict[str, object]:
    """GET /v1/user/subscription, one try. Raises urllib errors to the caller."""
    req = urllib.request.Request(SUBSCRIPTION_URL, headers={"xi-api-key": api_key})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())
