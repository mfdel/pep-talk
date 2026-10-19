"""Tests for scripts/pep_talk.py.

    python3 -m unittest discover -s tests -v

No network and no API key: urllib is mocked. The pull request tests drive real git
against a bare repository in a temporary directory, with a fake ``gh`` script where gh
matters. Tests that render audio use --mock (sine tones) and skip without ffmpeg.
"""

from __future__ import annotations

import contextlib
import email.parser
import email.policy
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pep_talk as pt  # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
HAS_GIT = bool(shutil.which("git"))

CFG = pt.VoiceConfig(voice_id="v1", model="eleven_v4", stability=0.5, similarity=0.8, style=0.3)
TOKEN = "123456789:AAFakeTokenForTests_abc-XYZ"
TG_ENV = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "42"}
SPEECH_MD = (
    "---\ntitle: The Review\nmode: wake\ntheme: future-self\ntopic: the quarterly review\n"
    "---\n# Arrival\n[calm] Alex, breathe in.\n<!-- note -->\n[[PAUSE 3]]\n"
    "[warm] You are   ready.\n"
)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "msg", {}, io.BytesIO(body))


class Base(unittest.TestCase):
    """Isolates every test from the developer's .env and from real waits."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.patch(pt, "ENV_FILE", self.tmp / "no.env")
        self.patch(pt, "_sleep", lambda _s: None)

    def patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)

    def set_environ(self, env: dict[str, str]) -> None:
        """Replace os.environ as the script sees it (subprocesses are unaffected)."""
        self.patch(pt.os, "environ", dict(env))

    def run_main(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = pt.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def write(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


# --------------------------------------------------------------------------
# .env and voice resolution
# --------------------------------------------------------------------------


class EnvTests(Base):
    def test_dotenv_parsing(self):
        path = self.write(".env", (
            "# a comment\n"
            "\n"
            "ELEVENLABS_API_KEY=sk_123\n"
            "export ELEVENLABS_VOICE_ID = \"quoted id\"\n"
            "TELEGRAM_CHAT_ID='42'\n"
            "TELEGRAM_BOT_TOKEN=123:abc   # trailing comment\n"
            "WITH_EQUALS=a=b\n"
            "EMPTY=\n"
            "not a pair\n"
        ))
        self.assertEqual(pt.read_dotenv(path), {
            "ELEVENLABS_API_KEY": "sk_123",
            "ELEVENLABS_VOICE_ID": "quoted id",
            "TELEGRAM_CHAT_ID": "42",
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "WITH_EQUALS": "a=b",
            "EMPTY": "",
        })

    def test_missing_dotenv_is_empty(self):
        self.assertEqual(pt.read_dotenv(self.tmp / "nope"), {})

    def test_real_environment_wins_over_dotenv(self):
        self.patch(pt, "ENV_FILE", self.write(".env", "A=from_file\nB=from_file\nC=from_file\n"))
        self.set_environ({"A": "from_env", "C": ""})
        env = pt.load_env()
        self.assertEqual(env["A"], "from_env")
        self.assertEqual(env["B"], "from_file")
        self.assertEqual(env["C"], "from_file")  # an empty variable does not blank it

    def test_voice_id_precedence(self):
        meta = {"voice_id": "front"}
        env = {"ELEVENLABS_VOICE_ID": "env"}
        self.assertEqual(pt.resolve_voice_id("flag", meta, env), "flag")
        self.assertEqual(pt.resolve_voice_id(None, meta, env), "front")
        self.assertEqual(pt.resolve_voice_id(None, {}, env), "env")
        self.assertEqual(pt.resolve_voice_id(None, {}, {}), pt.DEFAULT_VOICE_ID)
        self.assertEqual(pt.DEFAULT_VOICE_ID, "JBFqnCBsd6RMkjVDRZzb")

    def test_voice_flag_and_alias(self):
        for flag in ("--voice", "--voice-id"):
            args = pt.make_parser().parse_args(["build", "x.md", flag, "abc"])
            self.assertEqual(args.voice, "abc")


# --------------------------------------------------------------------------
# front matter and segments
# --------------------------------------------------------------------------


class ParseTests(Base):
    def test_front_matter_parsed_with_comments_and_quotes(self):
        text = (
            "---\n"
            "title: \"Stepping in\"   # the title\n"
            "mode: sleep            # sleep | wake\n"
            "# voice_id: commented\n"
            "voice_id: abc123\n"
            "---\n"
            "[calm] Hello.\n"
        )
        meta, body = pt.parse_front_matter(text)
        self.assertEqual(meta, {"title": "Stepping in", "mode": "sleep", "voice_id": "abc123"})
        self.assertEqual(body.strip(), "[calm] Hello.")

    def test_no_front_matter_returns_whole_text(self):
        self.assertEqual(pt.parse_front_matter("Hello.\n"), ({}, "Hello.\n"))

    def test_unclosed_front_matter_is_an_error(self):
        with self.assertRaisesRegex(pt.PepTalkError, "never closed"):
            pt.parse_front_matter("---\ntitle: x\nHello.\n")

    def test_bad_mode_is_an_error(self):
        with self.assertRaisesRegex(pt.PepTalkError, "mode"):
            pt.load_speech(self.write("s.md", "---\nmode: nap\n---\nHello.\n"))

    def test_theme_and_legacy_style_alias(self):
        self.assertEqual(pt.theme_of({"theme": "compassion"}), "compassion")
        self.assertEqual(pt.theme_of({"style": "debrief"}), "debrief")
        self.assertEqual(pt.theme_of({"theme": "compassion", "style": "debrief"}), "compassion")
        self.assertIsNone(pt.theme_of({}))
        self.assertEqual(pt.talk_meta("20261018_x_wake", {"style": "debrief"}).theme, "debrief")

    def test_segments_drop_headings_comments_and_blank_lines(self):
        body = (
            "# Induction\n"
            "[calm] Alex. Breathe in...\n"
            "\n"
            "and let the day go.\n"
            "<!-- a note\nover two lines -->\n"
            "[[PAUSE 8]]\n"
            "[warm] You have been hard on yourself.\n"
        )
        self.assertEqual(pt.parse_body(body), [
            pt.Speech("[calm] Alex. Breathe in...\nand let the day go."),
            pt.Pause(8.0),
            pt.Speech("[warm] You have been hard on yourself."),
        ])

    def test_consecutive_pauses_add_up_even_across_labels(self):
        body = "One.\n[[PAUSE 3]]\n# label\n<!-- c -->\n[[PAUSE 4.5]]\nTwo.\n"
        self.assertEqual(pt.parse_body(body),
                         [pt.Speech("One."), pt.Pause(7.5), pt.Speech("Two.")])

    def test_leading_and_trailing_pauses_kept(self):
        self.assertEqual(pt.parse_body("[[PAUSE 2]]\nOne.\n[[pause 5]]\n"),
                         [pt.Pause(2.0), pt.Speech("One."), pt.Pause(5.0)])

    def test_audio_tags_stay_in_text(self):
        self.assertEqual(pt.parse_body("[whispers] Quiet. [long pause] Still here.\n"),
                         [pt.Speech("[whispers] Quiet. [long pause] Still here.")])

    def test_segment_over_limit_is_an_error(self):
        body = "x" * (pt.MAX_SEGMENT_CHARS + 1) + "\n[[PAUSE 1]]\nok\n"
        with self.assertRaisesRegex(pt.PepTalkError, "segment 1"):
            pt.parse_body(body)

    def test_segment_at_limit_is_fine(self):
        text = "x" * pt.MAX_SEGMENT_CHARS
        self.assertEqual(pt.parse_body(text), [pt.Speech(text)])

    def test_empty_speech_is_an_error(self):
        with self.assertRaisesRegex(pt.PepTalkError, "no text"):
            pt.parse_body("# only a heading\n[[PAUSE 3]]\n")

    def test_plain_text_strips_markup(self):
        _, body = pt.parse_front_matter(SPEECH_MD)
        self.assertEqual(pt.plain_text(body), "Alex, breathe in.\n\nYou are ready.")


# --------------------------------------------------------------------------
# cache key, dry run
# --------------------------------------------------------------------------


class CacheAndEstimateTests(Base):
    def test_cache_key_covers_text_voice_model_settings(self):
        base = pt.cache_key(CFG, "Hello.")
        self.assertEqual(pt.cache_key(CFG, "Hello."), base)
        self.assertNotEqual(pt.cache_key(CFG, "Hello!"), base)
        others = (
            pt.VoiceConfig("v2", CFG.model, CFG.stability, CFG.similarity, CFG.style),
            pt.VoiceConfig(CFG.voice_id, "eleven_v3", CFG.stability, CFG.similarity, CFG.style),
            pt.VoiceConfig(CFG.voice_id, CFG.model, CFG.stability, CFG.similarity, 0.9),
        )
        for cfg in others:
            self.assertNotEqual(pt.cache_key(cfg, "Hello."), base)

    def test_cache_key_ignores_neighbours(self):
        """Editing segment 1 must re-bill only segment 1, not segment 2 next to it."""
        calls: list[str] = []

        def fake_synth(req):
            calls.append(json.loads(req.data)["text"])
            return b"ID3fake"

        self.patch(pt, "synthesize", fake_synth)
        cache = self.tmp / "cache"

        def run(first: str) -> int:
            speech = pt.SpeechFile({}, pt.parse_body(f"{first}\n[[PAUSE 1]]\nSecond.\n"))
            with contextlib.redirect_stderr(io.StringIO()):
                _, billed = pt.fetch_segments(speech, CFG, cache, self.tmp, mock=False,
                                              stitch=True, api_key="sk")
            return billed

        self.assertEqual(run("First."), len("First.") + len("Second."))
        calls.clear()
        self.assertEqual(run("First, edited."), len("First, edited."))
        self.assertEqual(calls, ["First, edited."])

    def test_estimate_numbers(self):
        text = "[calm] " + "a" * 140  # 140 spoken chars -> 10 s
        speech = pt.SpeechFile({}, pt.parse_body(f"[[PAUSE 3]]\n{text}\n[[PAUSE 5]]\n{text}\n"))
        est = pt.estimate(speech, lead_in=2.0, tail=4.0)
        self.assertEqual(est.segments, 2)
        self.assertEqual(est.words, 2)
        self.assertEqual(est.chars, 2 * len(text))
        self.assertAlmostEqual(est.cost_usd, 2 * len(text) / 1000 * pt.COST_PER_1K_CHARS)
        self.assertAlmostEqual(est.spoken_s, 20.0)
        self.assertAlmostEqual(est.silence_s, 3 + 5 + 2 + 4)
        self.assertAlmostEqual(est.total_s, 34.0)

    def test_dry_run_cli_needs_no_ffmpeg_or_key(self):
        self.patch(pt.shutil, "which", lambda _name: None)
        self.set_environ({})
        p = self.write("s.md", "---\nmode: wake\n---\n" + "a" * 140 + "\n[[PAUSE 6]]\n")
        rc, out, _ = self.run_main("build", str(p), "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("segments:   1", out)
        self.assertIn("words:      1", out)
        self.assertIn("characters: 140  (budget 5,500)", out)
        self.assertIn("$0.01", out)
        self.assertIn("total:      ~0:22", out)  # 10 spoken + 6 pause + 2 lead-in + 4 tail
        self.assertIn("bed none", out)
        self.assertIn(f"voice:      {pt.DEFAULT_VOICE_ID}", out)

    def test_dry_run_flags_over_budget(self):
        self.set_environ({})
        words = " ".join(["word"] * 1200)  # 5,999 chars
        p = self.write("s.md", f"---\nmode: sleep\nvoice_id: front\n---\n{words}\n")
        rc, out, _ = self.run_main("build", str(p), "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("OVER the 5,500 budget", out)
        self.assertIn("voice:      front", out)

    def test_default_paths_are_repo_relative(self):
        self.assertEqual(pt.default_out(Path("speeches/20261018_x_wake.md")),
                         pt.REPO / "out" / "20261018_x_wake.mp3")
        self.assertEqual(pt.default_cache(), pt.REPO / ".cache" / "segments")

    def test_fmt_duration(self):
        self.assertEqual(pt.fmt_duration(0), "0:00")
        self.assertEqual(pt.fmt_duration(61.4), "1:01")
        self.assertEqual(pt.fmt_duration(600), "10:00")


# --------------------------------------------------------------------------
# ElevenLabs requests and errors
# --------------------------------------------------------------------------


class ElevenLabsTests(Base):
    def test_request_body_and_stitching(self):
        prev, nxt = "p" * 1500, "n" * 1500
        req = pt.build_request(CFG, "Hello.", prev, nxt, api_key="sk-test")
        body = json.loads(req.data)
        self.assertEqual(
            req.full_url,
            "https://api.elevenlabs.io/v1/text-to-speech/v1?output_format=mp3_44100_128")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(body["text"], "Hello.")
        self.assertEqual(body["model_id"], "eleven_v4")
        self.assertEqual(body["voice_settings"], {
            "stability": 0.5, "similarity_boost": 0.8, "style": 0.3, "use_speaker_boost": True,
        })
        self.assertEqual(body["previous_text"], prev[-1000:])
        self.assertEqual(body["next_text"], nxt[:1000])
        self.assertEqual(req.get_header("Accept"), "audio/mpeg")
        self.assertEqual(req.get_header("Xi-api-key"), "sk-test")

    def test_request_without_neighbours_omits_stitching(self):
        body = json.loads(pt.build_request(CFG, "Hello.", None, None, api_key="k").data)
        self.assertNotIn("previous_text", body)
        self.assertNotIn("next_text", body)

    def test_key_header_only_when_set(self):
        self.assertFalse(pt.build_request(CFG, "x", None, None, None).has_header("Xi-api-key"))
        self.assertTrue(pt.build_request(CFG, "x", None, None, "k").has_header("Xi-api-key"))

    def test_no_style_slider_unless_asked(self):
        cfg = pt.VoiceConfig("v1", "eleven_v4", 0.5, 0.8)
        self.assertNotIn("style", cfg.settings())

    def test_synthesize_retries_then_succeeds(self):
        outcomes = [_http_error(429), urllib.error.URLError("reset"), _Resp(b"ID3audio")]

        def fake_urlopen(req, timeout):
            o = outcomes.pop(0)
            if isinstance(o, Exception):
                raise o
            return o

        self.patch(pt.urllib.request, "urlopen", fake_urlopen)
        with contextlib.redirect_stderr(io.StringIO()):
            data = pt.synthesize(pt.build_request(CFG, "x", None, None, "k"))
        self.assertEqual(data, b"ID3audio")

    def test_synthesize_gives_up_after_three_tries(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(1)
            raise _http_error(503)

        self.patch(pt.urllib.request, "urlopen", fake_urlopen)
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaisesRegex(pt.PepTalkError, "after 3 tries"):
            pt.synthesize(pt.build_request(CFG, "x", None, None, "k"))
        self.assertEqual(len(calls), 3)

    def test_error_messages_no_retry(self):
        cases = [
            (_http_error(401), "Set ELEVENLABS_API_KEY in .env or the environment variables"),
            (_http_error(401), "network secret for api.elevenlabs.io with header xi-api-key"),
            (_http_error(401, b'{"detail":{"status":"quota_exceeded"}}'), "credits used up"),
            (_http_error(401, b'{"detail":{"status":"missing_permissions"}}'), "Text to Speech"),
            (_http_error(402, b'{"detail":"paid"}'), "paid plan"),
            (_http_error(422, b'{"detail":"model not found"}'), "model not found"),
            (_http_error(400, b"bad"), "eleven_multilingual_v2"),
            (_http_error(400, b"previous_text"), "--no-stitch"),
            (_http_error(403, b"blocked"), "network access"),
            (urllib.error.URLError("Tunnel connection failed: 403 Forbidden"), "network access"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                calls = []

                def fake_urlopen(req, timeout, error=error, calls=calls):
                    calls.append(1)
                    raise error

                with mock.patch.object(pt.urllib.request, "urlopen", fake_urlopen), \
                        self.assertRaises(pt.PepTalkError) as info:
                    pt.synthesize(pt.build_request(CFG, "x", None, None, "k"))
                self.assertIn(expected, str(info.exception))
                self.assertEqual(len(calls), 1)


# --------------------------------------------------------------------------
# end to end, mock audio
# --------------------------------------------------------------------------


def _probe(path: Path, entries: str) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entries,
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class MockBuildTests(Base):
    def test_mock_build_end_to_end(self):
        self.set_environ({"PATH": os.environ.get("PATH", "")})  # no API key anywhere
        text = "[calm] " + "a" * 70  # 5 s each
        speech = self.write("s.md", (
            "---\ntitle: Test talk\nmode: sleep\n---\n"
            f"[[PAUSE 1]]\n{text}\n[[PAUSE 3]]\n[[PAUSE 2]]\n{text}\n[[PAUSE 2]]\n"
        ))
        for bed in ("brown", "none"):
            with self.subTest(bed=bed):
                out = self.tmp / f"out_{bed}.mp3"
                rc, stdout, _ = self.run_main("build", str(speech), "--out", str(out), "--mock",
                                              "--bed", bed, "--cache-dir", str(self.tmp / "c"))
                self.assertEqual(rc, 0)
                expected = 2 + 1 + 5 + 5 + 5 + 2 + 4  # lead-in, pauses, two segments, tail
                self.assertAlmostEqual(float(_probe(out, "format=duration")), expected, delta=0.3)
                self.assertEqual(_probe(out, "format_tags=title"), "Test talk")
                self.assertEqual(_probe(out, "stream=sample_rate,channels").split(),
                                 ["44100", "1"])
                self.assertIn("chars billed: 0", stdout)
                self.assertIn("voice: mock", stdout)
        self.assertFalse((self.tmp / "c").exists())  # mock never touches the cache

    def test_real_build_without_key_sends_no_header(self):
        """No local key: warn once and send anyway, for a proxy that injects xi-api-key."""
        self.set_environ({"PATH": os.environ.get("PATH", "")})
        tone = self.tmp / "tone.mp3"
        pt.make_mock_mp3(tone, 1.0)
        seen = []

        def fake_urlopen(req, timeout):
            seen.append(req)
            return _Resp(tone.read_bytes())

        self.patch(pt.urllib.request, "urlopen", fake_urlopen)
        speech = self.write("s.md", "---\ntitle: T\nmode: wake\n---\nHello.\n")
        out = self.tmp / "out.mp3"
        rc, stdout, err = self.run_main("build", str(speech), "--out", str(out),
                                        "--cache-dir", str(self.tmp / "c"))
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].has_header("Xi-api-key"))
        self.assertIn("ELEVENLABS_API_KEY not set; sending without it", err)
        self.assertIn("chars billed: 6", stdout)
        self.assertTrue(out.is_file())


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------


def _parts(body: bytes, ctype: str) -> dict[str, tuple[str | None, str, bytes]]:
    """name -> (filename, content type, payload) of a multipart body."""
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        f"Content-Type: {ctype}\r\n\r\n".encode() + body
    )
    assert msg.is_multipart()
    return {
        p.get_param("name", header="content-disposition"): (
            p.get_filename(), p.get_content_type(), p.get_payload(decode=True)
        )
        for p in msg.iter_parts()
    }


def _form(req) -> dict[str, tuple[str | None, str, bytes]]:
    return _parts(req.data, req.get_header("Content-type"))


class CaptionTests(Base):
    def test_talk_meta_from_stem_and_front_matter(self):
        cases = [
            ("20261018_quarterly-review_wake", {}, "quarterly review", "wake", "2026-10-18"),
            ("20261019_20261018_test_sleep", {}, "test", "sleep", "2026-10-19"),
            ("20261018_quarterly-review_wake_v2", {}, "quarterly review", "wake", "2026-10-18"),
            ("offer_talk", {"mode": "sleep"}, "offer talk", "sleep", None),
            ("20261018_x_wake", {"topic": "The offer", "mode": "sleep"}, "The offer", "sleep",
             "2026-10-18"),
        ]
        for stem, meta, topic, mode, day in cases:
            with self.subTest(stem=stem):
                talk = pt.talk_meta(stem, meta)
                self.assertEqual(talk.topic, topic)
                self.assertEqual(talk.mode, mode)
                self.assertEqual(talk.day.isoformat() if talk.day else None, day)
                self.assertEqual(talk.title, topic)  # no title in the front matter

    def test_hashtag_keeps_letters_digits_underscores(self):
        cases = [("quarterly-review", "#quarterly_review"), ("future-self", "#future_self"),
                 ("pep talk", "#pep_talk"), ("Q4 / exec-update!", "#q4_exec_update"),
                 ("2026", None), ("  ", None)]
        for word, tag in cases:
            with self.subTest(word=word):
                self.assertEqual(pt.hashtag(word), tag)

    def test_caption_lines_and_hashtags(self):
        talk = pt.talk_meta("20261018_quarterly-review_wake",
                            {"title": "The Review", "theme": "future-self", "mode": "wake"})
        self.assertEqual(pt.build_caption(talk), (
            "The Review\n2026-10-18 · future-self · wake\nTopic: quarterly review\n\n"
            "#pep_talk #wake #future_self #quarterly_review"
        ))

    def test_caption_cut_to_limit_keeps_hashtags(self):
        caption = pt.build_caption(pt.talk_meta("20261018_x_sleep", {"title": "t" * 2000}))
        self.assertEqual(len(caption), pt.TELEGRAM_CAPTION_MAX)
        self.assertTrue(caption.endswith("\n\n#pep_talk #sleep #x"))
        self.assertIn("…", caption)

    def test_redact_exact_token_and_token_shapes(self):
        self.assertNotIn(TOKEN, pt.redact(f"https://api.telegram.org/bot{TOKEN}/sendAudio", TOKEN))
        self.assertEqual(pt.redact(f"url bot{TOKEN}/x"), "url bot<token>/x")
        self.assertEqual(pt.redact("no token here"), "no token here")

    def test_multipart_body_fields_and_files(self):
        body, ctype = pt.encode_multipart(
            {"chat_id": "42", "caption": "Ünïcode · #tag"},
            {"audio": ('a"b.mp3', "audio/mpeg", b"ID3\x00\xff")},
            boundary="BOUNDARY",
        )
        self.assertEqual(ctype, "multipart/form-data; boundary=BOUNDARY")
        self.assertTrue(body.endswith(b"--BOUNDARY--\r\n"))
        parts = _parts(body, ctype)
        self.assertEqual(parts["chat_id"][2], b"42")
        self.assertEqual(parts["caption"][2].decode("utf-8"), "Ünïcode · #tag")
        self.assertEqual(parts["audio"], ("a_b.mp3", "audio/mpeg", b"ID3\x00\xff"))


class TelegramTests(Base):
    STEM = "20261018_quarterly-review_wake"

    def setUp(self) -> None:
        super().setUp()
        self.mp3 = self.tmp / f"{self.STEM}.mp3"
        self.mp3.write_bytes(b"ID3audio")
        self.md = self.write("speech.md", SPEECH_MD)
        self.patch(pt, "_audio_seconds", lambda _p: 576)

    def server(self, outcomes: list) -> list:
        """Fake urlopen answering Bot API calls in turn; returns the requests it saw."""
        seen: list = []

        def fake_urlopen(req, timeout):
            seen.append(req)
            o = outcomes.pop(0)
            if isinstance(o, Exception):
                raise o
            return _Resp(json.dumps(o).encode())

        self.patch(pt.urllib.request, "urlopen", fake_urlopen)
        return seen

    def test_send_audio_then_speech_as_reply(self):
        seen = self.server([{"ok": True, "result": {"message_id": 7}},
                            {"ok": True, "result": {"message_id": 8}}])
        self.set_environ(TG_ENV)
        rc, out, err = self.run_main("telegram", str(self.mp3), str(self.md))
        self.assertEqual(rc, 0)
        audio, doc = seen
        self.assertEqual(audio.full_url, f"https://api.telegram.org/bot{TOKEN}/sendAudio")
        form = _form(audio)
        self.assertEqual(form["chat_id"][2], b"42")
        self.assertEqual(form["title"][2], b"The Review")
        self.assertEqual(form["performer"][2], b"Pep Talk")
        self.assertEqual(form["duration"][2], b"576")
        self.assertEqual(form["caption"][2].decode(), (
            "The Review\n2026-10-18 · future-self · wake\nTopic: the quarterly review\n\n"
            "#pep_talk #wake #future_self #the_quarterly_review"
        ))
        self.assertEqual(form["audio"], (self.mp3.name, "audio/mpeg", b"ID3audio"))
        self.assertTrue(doc.full_url.endswith("/sendDocument"))
        form = _form(doc)
        self.assertEqual(json.loads(form["reply_parameters"][2])["message_id"], 7)
        self.assertEqual(form["document"][0], f"{self.STEM}.md")
        self.assertEqual(form["document"][2], SPEECH_MD.encode())
        self.assertIn("sent to Telegram", out)
        self.assertIn("speech attached", out)
        self.assertNotIn(TOKEN, out + err)

    def test_config_from_dotenv(self):
        self.patch(pt, "ENV_FILE", self.write(".env", f"TELEGRAM_BOT_TOKEN={TOKEN}\n"
                                                      "TELEGRAM_CHAT_ID=42\n"))
        self.set_environ({})
        seen = self.server([{"ok": True, "result": {"message_id": 7}},
                            {"ok": True, "result": {"message_id": 8}}])
        self.assertEqual(self.run_main("telegram", str(self.mp3), str(self.md))[0], 0)
        self.assertEqual(len(seen), 2)

    def test_failed_speech_send_only_warns(self):
        self.server([{"ok": True, "result": {"message_id": 7}},
                     _http_error(400, b'{"ok":false,"description":"Bad Request: x"}')])
        self.set_environ(TG_ENV)
        rc, _, err = self.run_main("telegram", str(self.mp3), str(self.md))
        self.assertEqual(rc, 0)
        self.assertIn("speech not attached", err)

    def test_audio_send_errors_exit_1_redacted(self):
        cases = [
            (_http_error(401, b'{"ok":false,"error_code":401,"description":"Unauthorized"}'),
             "BotFather"),
            (_http_error(404, b'{"ok":false,"description":"Not Found"}'), "BotFather"),
            (_http_error(400, b'{"ok":false,"description":"Bad Request: chat not found"}'),
             "send it /start"),
            (_http_error(403, b'{"ok":false,"description":"Forbidden: bot was blocked"}'),
             "Unblock the bot"),
            (_http_error(403, b"blocked by proxy"), "network access"),
            (urllib.error.URLError("Tunnel connection failed: 403 Forbidden"), "api.telegram.org"),
            (urllib.error.URLError(f"Tunnel failed: 403 for /bot{TOKEN}/sendAudio"), "<token>"),
            ({"ok": False, "description": "Bad Request: odd"}, "Bad Request: odd"),
        ]
        self.set_environ(TG_ENV)
        for outcome, expected in cases:
            with self.subTest(expected=expected):
                seen = self.server([outcome])
                rc, _, err = self.run_main("telegram", str(self.mp3), str(self.md))
                self.assertEqual(rc, 1)
                self.assertIn(expected, err)
                self.assertNotIn(TOKEN, err)
                self.assertEqual(len(seen), 1)  # no retry, no speech send

    def test_missing_env_exits_3_without_network(self):
        seen = self.server([])
        self.set_environ({"TELEGRAM_CHAT_ID": "42"})
        for extra in ([], ["--dry-run"]):
            with self.subTest(extra=extra):
                rc, _, err = self.run_main("telegram", str(self.mp3), str(self.md), *extra)
                self.assertEqual(rc, pt.EXIT_NOT_CONFIGURED)
                self.assertIn("pep_talk: TELEGRAM_BOT_TOKEN not set, nothing sent", err)
                self.assertIn(".env.example", err)
        self.assertEqual(seen, [])

    def test_oversize_mp3_fails_before_sending(self):
        seen = self.server([])
        self.patch(pt, "TELEGRAM_MAX_BYTES", 4)
        self.set_environ(TG_ENV)
        rc, _, err = self.run_main("telegram", str(self.mp3), str(self.md))
        self.assertEqual(rc, 1)
        self.assertIn("at most 50 MB", err)
        self.assertEqual(seen, [])

    def test_dry_run_prints_fields_not_token(self):
        seen = self.server([])
        self.set_environ(TG_ENV)
        rc, out, _ = self.run_main("telegram", str(self.mp3), str(self.md), "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("bot<token>/sendAudio", out)
        self.assertIn("title:     The Review", out)
        self.assertIn("performer: Pep Talk", out)
        self.assertIn("#future_self", out)
        self.assertNotIn(TOKEN, out)
        self.assertEqual(seen, [])


# --------------------------------------------------------------------------
# GitHub pull request delivery
# --------------------------------------------------------------------------


class GitHubUnitTests(Base):
    def test_parse_github_remote(self):
        cases = {
            "https://github.com/acme/talks": ("acme", "talks"),
            "https://github.com/acme/talks.git": ("acme", "talks"),
            "https://github.com/acme/talks/": ("acme", "talks"),
            "https://user:secret@github.com/acme/my.talks.git": ("acme", "my.talks"),
            "git@github.com:acme/talks.git": ("acme", "talks"),
            "git@github.com:acme/talks": ("acme", "talks"),
            "ssh://git@github.com/acme/talks.git": ("acme", "talks"),
            "ssh://git@github.com:22/acme/talks.git": ("acme", "talks"),
        }
        for url, (owner, name) in cases.items():
            with self.subTest(url=url):
                self.assertEqual(pt.parse_github_remote(url), pt.GitHubRepo(owner, name))
        proxies = {
            "http://local_proxy@127.0.0.1:12345/git/acme/talks": ("acme", "talks"),
            "http://127.0.0.1:8080/git/acme/talks.git": ("acme", "talks"),
            "http://user:pw@localhost:9/git/acme/my-talks/": ("acme", "my-talks"),
            "https://localhost/git/acme/talks": ("acme", "talks"),
        }
        for url, (owner, name) in proxies.items():
            with self.subTest(url=url):
                self.assertEqual(pt.parse_github_remote(url),
                                 pt.GitHubRepo(owner, name, proxy=True))
        for url in ("https://gitlab.com/acme/talks.git", "git@bitbucket.org:acme/talks.git",
                    "/srv/git/talks.git", "https://github.com/acme", "https://notgithub.com/a/b",
                    "http://127.0.0.1:8080/acme/talks", "http://10.0.0.1:80/git/acme/talks",
                    "http://127.0.0.1:8080/git/acme"):
            with self.subTest(url=url):
                self.assertIsNone(pt.parse_github_remote(url))

    def test_safe_url_drops_credentials(self):
        self.assertEqual(pt._safe_url("https://u:tok@gitlab.com/a/b.git"),
                         "https://gitlab.com/a/b.git")

    def test_urls(self):
        repo = pt.GitHubRepo("acme", "talks")
        self.assertEqual(
            pt.blob_url(repo, "talk/20261018_x_wake", "talks/20261018_x_wake/20261018_x_wake.mp3"),
            "https://github.com/acme/talks/blob/talk/20261018_x_wake/"
            "talks/20261018_x_wake/20261018_x_wake.mp3?raw=true")
        self.assertEqual(pt.compare_url(repo, "main", "talk/20261018_x_wake"),
                         "https://github.com/acme/talks/compare/main...talk/20261018_x_wake"
                         "?expand=1")

    def test_pr_body(self):
        meta, body = pt.parse_front_matter(SPEECH_MD)
        talk = pt.talk_meta("20261018_quarterly-review_wake", meta)
        text = pt.build_pr_body(talk, length="7:42", mp3_url="https://x/y.mp3?raw=true",
                                mp3_name="y.mp3", speech_text=pt.plain_text(body))
        self.assertTrue(text.startswith("## The Review\n"))
        for line in ("- **Date:** 2026-10-18", "- **Theme:** future-self", "- **Mode:** wake",
                     "- **Topic:** the quarterly review", "- **Length:** 7:42",
                     "**Listen:** [y.mp3](https://x/y.mp3?raw=true)"):
            self.assertIn(line, text)
        details = text[text.index("<details>"):]
        self.assertIn("<summary>Speech</summary>\n\nAlex, breathe in.\n\nYou are ready.\n\n"
                      "</details>", details)
        self.assertNotIn("[calm]", text)
        self.assertNotIn("PAUSE", text)

    def test_pr_body_skips_unknown_facts(self):
        talk = pt.TalkMeta(title="T", day=None, theme=None, mode="sleep", topic="t")
        text = pt.build_pr_body(talk, length=None, mp3_url="u", mp3_name="n", speech_text="s")
        self.assertNotIn("Date", text)
        self.assertNotIn("Theme", text)
        self.assertNotIn("Length", text)


FAKE_GH = """#!/bin/sh
# Stand-in for the GitHub CLI: logs each call, answers from environment variables.
echo "$*" >> "$FAKE_GH_LOG"
case "$1 $2" in
    "auth status") exit 0 ;;
    "repo view") echo "$FAKE_GH_VISIBILITY" ;;
    "pr list") echo "$FAKE_GH_EXISTING" ;;
    "pr create") echo "https://github.com/acme/talks/pull/7" ;;
    *) exit 1 ;;
esac
"""


REJECT_TALK_BRANCHES = """#!/bin/sh
# Acts like a session git proxy: only the session's own branch may be pushed.
while read old new ref; do
    case "$ref" in
        refs/heads/talk/*) echo "proxy: push to $ref is not allowed" >&2; exit 1 ;;
    esac
done
"""


class GitRepoCase(Base):
    """Real git: a working clone whose remote URL is rewritten to a local bare repository.

    ``REMOTE_URL`` is what the clone's ``origin`` says; ``url.<bare>.insteadOf`` makes
    every fetch and push go to the bare repository instead.
    """

    STEM = "20261018_quarterly-review_wake"
    REMOTE_URL = "https://github.com/acme/talks.git"

    def setUp(self) -> None:
        super().setUp()
        # No user or system git config: no identity, no signing, no hooks from this machine.
        global_cfg = self.write("gitconfig", "")
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(global_cfg),
                                           "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.bare = self.tmp / "remote.git"
        self.work = self.tmp / "work"
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.bare))
        self.git(self.tmp, "init", "-q", "-b", "main", str(self.work))
        (self.work / ".gitignore").write_text(".cache/\n")
        (self.work / "notes.txt").write_text("v1\n")
        self.git(self.work, "add", ".")
        self.git(self.work, "-c", "user.name=t", "-c", "user.email=t@example.com",
                 "commit", "-q", "-m", "init")
        self.git(self.work, "remote", "add", "origin", self.REMOTE_URL)
        self.git(self.work, "config", f"url.{self.bare}.insteadOf", self.REMOTE_URL)
        self.git(self.work, "push", "-q", "origin", "main")
        # Uncommitted, staged work in progress that delivery must not disturb.
        (self.work / "notes.txt").write_text("v2\n")
        self.git(self.work, "add", "notes.txt")
        self.head = self.git(self.work, "rev-parse", "HEAD")

        self.mp3 = self.tmp / "out" / f"{self.STEM}.mp3"
        self.mp3.parent.mkdir()
        self.mp3.write_bytes(b"ID3audio-bytes")
        self.md = self.write(f"speeches/{self.STEM}.md", SPEECH_MD)
        self.patch(pt, "REPO", self.work)
        self.patch(pt, "_gh_path", lambda: None)

    def git(self, cwd: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              check=True).stdout.strip()

    def fake_gh(self, visibility: str, existing: str = "") -> Path:
        gh = self.write("bin/gh", FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        log = self.tmp / "gh.log"
        env = mock.patch.dict(os.environ, {"FAKE_GH_LOG": str(log),
                                           "FAKE_GH_VISIBILITY": visibility,
                                           "FAKE_GH_EXISTING": existing})
        env.start()
        self.addCleanup(env.stop)
        self.patch(pt, "_gh_path", lambda: str(gh))
        return log

    def reject_talk_branches(self) -> None:
        hook = self.bare / "hooks" / "pre-receive"
        hook.write_text(REJECT_TALK_BRANCHES)
        hook.chmod(0o755)

    def remote_branches(self) -> list[str]:
        out = self.git(self.bare, "for-each-ref", "--format=%(refname)", "refs/heads")
        return out.splitlines()

    def assert_worktree_untouched(self) -> None:
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), self.head)
        self.assertEqual(self.git(self.work, "branch", "--show-current"), "main")
        self.assertEqual(self.git(self.work, "status", "--porcelain"), "M  notes.txt")

    def pr(self, *extra: str) -> tuple[int, str, str]:
        return self.run_main("pr", str(self.mp3), str(self.md), *extra)


@unittest.skipUnless(HAS_GIT, "git not installed")
class PullRequestFlowTests(GitRepoCase):

    def test_without_gh_pushes_branch_and_exits_4(self):
        rc, out, err = self.pr()
        self.assertEqual(rc, pt.EXIT_NO_GH, err)
        branch = f"refs/heads/talk/{self.STEM}"
        self.assertIn(branch, self.remote_branches())
        folder = f"talks/{self.STEM}"
        tree = self.git(self.bare, "ls-tree", "-r", "--name-only", branch).splitlines()
        self.assertEqual(sorted(tree), [".gitignore", "notes.txt", f"{folder}/{self.STEM}.md",
                                        f"{folder}/{self.STEM}.mp3"])
        self.assertEqual(self.git(self.bare, "show", f"{branch}:{folder}/{self.STEM}.md"),
                         SPEECH_MD.strip())
        self.assertEqual(self.git(self.bare, "show", f"{branch}:notes.txt"), "v1")  # base, not WIP
        self.assertEqual(self.git(self.bare, "log", "-1", "--format=%s%n%an", branch),
                         "talk: The Review\npep-talk")
        self.assertEqual(self.git(self.bare, "rev-parse", f"{branch}^"),
                         self.git(self.bare, "rev-parse", "refs/heads/main"))
        body_file = self.work / ".cache" / "pr" / f"{self.STEM}.md"
        self.assertEqual(out.splitlines(), [
            "delivery: talk-branch",
            f"head: talk/{self.STEM}",
            "base: main",
            "title: The Review",
            f"body_file: {body_file}",
            f"compare_url: https://github.com/acme/talks/compare/main...talk/{self.STEM}"
            "?expand=1",
        ])
        self.assertIn(f"/blob/talk/{self.STEM}/talks/", body_file.read_text())
        self.assertIn("visibility was not checked", err)
        self.assert_worktree_untouched()

    def test_rerun_force_updates_the_branch(self):
        self.assertEqual(self.pr()[0], pt.EXIT_NO_GH)
        self.mp3.write_bytes(b"ID3audio-rebuilt")
        self.assertEqual(self.pr()[0], pt.EXIT_NO_GH)
        branch = f"refs/heads/talk/{self.STEM}"
        self.assertEqual(self.git(self.bare, "rev-list", "--count", f"main..{branch}"), "1")
        self.assertEqual(self.git(self.bare, "show",
                                  f"{branch}:talks/{self.STEM}/{self.STEM}.mp3"),
                         "ID3audio-rebuilt")

    def test_dry_run_pushes_nothing(self):
        rc, out, _ = self.pr("--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("repo:      acme/talks", out)
        self.assertIn("base:      main", out)
        self.assertIn(f"head:      talk/{self.STEM}  (force-pushed)\n", out)
        self.assertIn(f"talks/{self.STEM}/{self.STEM}.mp3", out)
        self.assertIn("nothing pushed", out)
        self.assertEqual(self.remote_branches(), ["refs/heads/main"])
        self.assertFalse((self.work / ".cache").exists())
        self.assert_worktree_untouched()

    def test_public_repo_refused_before_push(self):
        log = self.fake_gh("PUBLIC")
        rc, _, err = self.pr()
        self.assertEqual(rc, pt.EXIT_NOT_CONFIGURED)
        self.assertIn("PUBLIC", err)
        self.assertIn("personal notes", err)
        self.assertIn("--allow-public", err)
        self.assertEqual(self.remote_branches(), ["refs/heads/main"])
        self.assertNotIn("pr create", log.read_text())

    def test_allow_public_opens_the_pr(self):
        log = self.fake_gh("PUBLIC")
        rc, out, err = self.pr("--allow-public")
        self.assertEqual(rc, 0, err)
        self.assertIn("pull_request: https://github.com/acme/talks/pull/7", out)
        calls = log.read_text()
        self.assertIn(f"pr create --repo acme/talks --base main --head talk/{self.STEM} "
                      "--title The Review --body-file", calls)

    def test_private_repo_opens_the_pr(self):
        log = self.fake_gh("PRIVATE")
        rc, out, _ = self.pr("--base", "main")
        self.assertEqual(rc, 0)
        self.assertIn("pull_request:", out)
        self.assertIn("repo view acme/talks --json visibility", log.read_text())
        self.assertIn(f"refs/heads/talk/{self.STEM}", self.remote_branches())

    def test_existing_pr_is_reused(self):
        log = self.fake_gh("PRIVATE", existing="https://github.com/acme/talks/pull/3")
        rc, out, err = self.pr()
        self.assertEqual(rc, 0)
        self.assertIn("pull_request: https://github.com/acme/talks/pull/3", out)
        self.assertIn("already open", err)
        self.assertNotIn("pr create", log.read_text())

    def test_rejected_push_without_proxy_is_an_error(self):
        self.reject_talk_branches()
        rc, _, err = self.pr()
        self.assertEqual(rc, 1)
        self.assertIn("git push to origin failed", err)
        self.assertIn("is not allowed", err)
        self.assert_worktree_untouched()  # no fallback onto the current branch

    def test_head_equal_to_base_is_refused(self):
        rc, _, err = self.pr("--head", "main")
        self.assertEqual(rc, 1)
        self.assertIn("is the base branch", err)
        self.assert_worktree_untouched()

    def test_missing_base_branch_is_not_configured(self):
        rc, _, err = self.pr("--base", "trunk")
        self.assertEqual(rc, pt.EXIT_NOT_CONFIGURED)
        self.assertIn("'trunk' does not exist on origin", err)

    def test_no_remote_is_not_configured(self):
        self.git(self.work, "remote", "remove", "origin")
        rc, _, err = self.pr("--dry-run")
        self.assertEqual(rc, pt.EXIT_NOT_CONFIGURED)
        self.assertIn("no git remote 'origin'", err)
        self.assertIn("private GitHub repository", err)

    def test_non_github_remote_is_not_configured(self):
        self.git(self.work, "remote", "set-url", "origin", "https://u:pw@gitlab.com/acme/t.git")
        rc, _, err = self.pr()
        self.assertEqual(rc, pt.EXIT_NOT_CONFIGURED)
        self.assertIn("not on github.com (https://gitlab.com/acme/t.git)", err)
        self.assertNotIn("pw", err)

    def test_not_a_git_repo_is_not_configured(self):
        self.patch(pt, "REPO", self.tmp / "out")
        rc, _, err = self.pr()
        self.assertEqual(rc, pt.EXIT_NOT_CONFIGURED)
        self.assertIn("not a git repository", err)


@unittest.skipUnless(HAS_GIT, "git not installed")
class ProxyFallbackTests(GitRepoCase):
    """A Claude Code cloud git proxy remote that refuses every branch but the session's."""

    REMOTE_URL = "http://local_proxy@127.0.0.1:12345/git/acme/talks"
    SESSION = "claude/session-abc"

    def setUp(self) -> None:
        super().setUp()
        self.git(self.work, "checkout", "-q", "-b", self.SESSION)
        self.reject_talk_branches()
        self.folder = f"talks/{self.STEM}"

    def assert_landed_on_session_branch(self, out: str) -> None:
        ref = f"refs/heads/{self.SESSION}"
        self.assertIn(ref, self.remote_branches())
        self.assertNotIn(f"refs/heads/talk/{self.STEM}", self.remote_branches())
        changed = self.git(self.bare, "diff-tree", "--no-commit-id", "--name-only", "-r", ref)
        self.assertEqual(sorted(changed.splitlines()),
                         [f"{self.folder}/{self.STEM}.md", f"{self.folder}/{self.STEM}.mp3"])
        self.assertEqual(self.git(self.bare, "rev-parse", f"{ref}^"), self.head)
        self.assertEqual(self.git(self.bare, "log", "-1", "--format=%s", ref), "talk: The Review")
        self.assertEqual(self.git(self.bare, "show", f"{ref}:notes.txt"), "v1")  # WIP not in it
        # Locally: the commit is on the session branch, the staged WIP is still staged.
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"),
                         self.git(self.bare, "rev-parse", ref))
        self.assertEqual(self.git(self.work, "branch", "--show-current"), self.SESSION)
        self.assertEqual(self.git(self.work, "status", "--porcelain"), "M  notes.txt")
        self.assertIn("delivery: current-branch", out)
        self.assertIn(f"head: {self.SESSION}", out)
        self.assertIn("compare_url: https://github.com/acme/talks/compare/main..."
                      f"{self.SESSION}?expand=1", out)
        body = (self.work / ".cache" / "pr" / f"{self.STEM}.md").read_text()
        self.assertIn(f"/blob/{self.SESSION}/{self.folder}/{self.STEM}.mp3?raw=true", body)

    def test_refused_push_falls_back_to_current_branch(self):
        rc, out, err = self.pr()
        self.assertEqual(rc, pt.EXIT_NO_GH, err)
        self.assertIn(f"the git proxy refused talk/{self.STEM}", err)
        self.assert_landed_on_session_branch(out)

    def test_rerun_with_same_files_adds_no_commit(self):
        self.assertEqual(self.pr()[0], pt.EXIT_NO_GH)
        first = self.git(self.work, "rev-parse", "HEAD")
        rc, _, err = self.pr()
        self.assertEqual(rc, pt.EXIT_NO_GH, err)
        self.assertEqual(self.git(self.work, "rev-parse", "HEAD"), first)
        self.assertIn("already committed", err)

    def test_head_naming_current_branch_skips_the_talk_branch(self):
        rc, out, err = self.pr("--head", self.SESSION)
        self.assertEqual(rc, pt.EXIT_NO_GH, err)
        self.assertNotIn("refused", err)
        self.assert_landed_on_session_branch(out)

    def test_fallback_refused_on_the_base_branch(self):
        self.git(self.work, "checkout", "-q", "main")
        rc, _, err = self.pr()
        self.assertEqual(rc, 1)
        self.assertIn("the current branch is 'main', the pull request's base", err)
        self.assertEqual(self.remote_branches(), ["refs/heads/main"])
        self.assertFalse((self.work / "talks").exists())

    def test_fallback_refused_when_detached(self):
        self.git(self.work, "checkout", "-q", "--detach")
        rc, _, err = self.pr()
        self.assertEqual(rc, 1)
        self.assertIn("HEAD is detached", err)
        self.assertFalse((self.work / "talks").exists())

    def test_dry_run_names_the_fallback(self):
        rc, out, _ = self.pr("--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("repo:      acme/talks", out)
        self.assertIn(f"if the git proxy refuses, commit onto {self.SESSION}", out)
        self.assertEqual(self.remote_branches(), ["refs/heads/main"])


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


class DoctorTests(Base):
    def setUp(self) -> None:
        super().setUp()
        self.patch(pt, "REPO", self.tmp)  # not a git repo, no context files
        self.patch(pt.shutil, "which", lambda name: f"/usr/bin/{name}")
        self.patch(pt, "_mp3_encoder_ok", lambda: True)

        def no_network(*_a, **_k):
            raise AssertionError("network used")

        self.patch(pt.urllib.request, "urlopen", no_network)

    def test_ready_offline_never_prints_secrets(self):
        self.write("context/profile.md", "name: Alex\n")
        self.write("context/sources.md", "- ~/notes\n")
        self.set_environ({"ELEVENLABS_API_KEY": "sk_secret_value", **TG_ENV})
        rc, out, _ = self.run_main("doctor", "--offline")
        self.assertEqual(rc, 0)
        self.assertIn("✓ ffmpeg", out)
        self.assertIn("✓ ElevenLabs key  set (from environment), not checked (--offline)", out)
        self.assertIn(f"✓ voice           {pt.DEFAULT_VOICE_ID}", out)
        self.assertIn("✓ Telegram", out)
        self.assertIn("– git remote", out)
        self.assertIn("✓ profile", out)
        self.assertIn("✓ sources", out)
        self.assertIn("ready to render", out)
        self.assertNotIn("sk_secret_value", out)
        self.assertNotIn(TOKEN, out)

    def test_missing_key_is_a_warning(self):
        self.set_environ({})
        rc, out, _ = self.run_main("doctor", "--offline")
        self.assertEqual(rc, 0)  # a proxy may inject the key
        self.assertIn("– ElevenLabs key  ELEVENLABS_API_KEY not set", out)
        self.assertIn("proxy injects it", out)
        self.assertIn("– Telegram", out)
        self.assertIn("– profile", out)
        self.assertIn("cp context/profile.example.md", out)
        self.assertIn("ready to render", out)

    def test_missing_ffmpeg_is_not_ready(self):
        self.patch(pt.shutil, "which", lambda _name: None)
        self.set_environ({"ELEVENLABS_API_KEY": "k"})
        rc, out, _ = self.run_main("doctor", "--offline")
        self.assertEqual(rc, 1)
        self.assertIn("✗ ffmpeg", out)

    def test_half_telegram_config_is_flagged(self):
        self.set_environ({"ELEVENLABS_API_KEY": "k", "TELEGRAM_BOT_TOKEN": TOKEN})
        rc, out, _ = self.run_main("doctor", "--offline")
        self.assertEqual(rc, 0)  # Telegram does not block rendering
        self.assertIn("✗ Telegram        TELEGRAM_CHAT_ID missing", out)

    def test_key_from_dotenv_and_quota_online(self):
        self.patch(pt, "ENV_FILE", self.write(".env", "ELEVENLABS_API_KEY=sk_file\n"
                                                      "ELEVENLABS_VOICE_ID=myvoice\n"))
        self.set_environ({})
        seen = []

        def fake_urlopen(req, timeout):
            seen.append(req)
            return _Resp(json.dumps({"character_count": 1000, "character_limit": 30000,
                                     "tier": "starter"}).encode())

        self.patch(pt.urllib.request, "urlopen", fake_urlopen)
        rc, out, _ = self.run_main("doctor")
        self.assertEqual(rc, 0)
        self.assertIn("set (from .env); 29,000 of 30,000 characters left (tier starter)", out)
        self.assertIn("myvoice (ELEVENLABS_VOICE_ID)", out)
        self.assertEqual(seen[0].full_url, pt.SUBSCRIPTION_URL)
        self.assertEqual(seen[0].get_header("Xi-api-key"), "sk_file")
        self.assertNotIn("sk_file", out)

    def test_rejected_key_is_not_ready(self):
        self.set_environ({"ELEVENLABS_API_KEY": "bad"})

        def fake_urlopen(req, timeout):
            raise _http_error(401, b'{"detail":{"status":"invalid_api_key"}}')

        self.patch(pt.urllib.request, "urlopen", fake_urlopen)
        rc, out, _ = self.run_main("doctor")
        self.assertEqual(rc, 1)
        self.assertIn("rejected it (HTTP 401)", out)

    def test_unreachable_api_is_a_warning_not_a_failure(self):
        self.set_environ({"ELEVENLABS_API_KEY": "k"})

        def fake_urlopen(req, timeout):
            raise urllib.error.URLError("Tunnel connection failed: 403")

        self.patch(pt.urllib.request, "urlopen", fake_urlopen)
        rc, out, _ = self.run_main("doctor")
        self.assertEqual(rc, 0)
        self.assertIn("– ElevenLabs key", out)
        self.assertIn("allow api.elevenlabs.io", out)

    @unittest.skipUnless(HAS_GIT, "git not installed")
    def test_github_checks_with_fake_gh(self):
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "remote", "add", "origin",
                        "git@github.com:acme/talks.git"], check=True)
        gh = self.write("bin/gh", FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.patch(pt, "_gh_path", lambda: str(gh))
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "k",
                                          "FAKE_GH_LOG": str(self.tmp / "gh.log")}):
            rc, out, _ = self.run_main("doctor", "--offline")
        self.assertEqual(rc, 0)
        self.assertEqual((self.tmp / "gh.log").read_text(),
                         "auth status --hostname github.com\n")
        self.assertIn("✓ git remote      origin -> acme/talks", out)
        self.assertIn("✓ gh              logged in", out)
        self.assertIn("– repo visibility not checked (--offline)", out)


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------


class CliTests(Base):
    def test_subcommands(self):
        parser = pt.make_parser()
        self.assertEqual(parser.parse_args(["doctor"]).offline, False)
        args = parser.parse_args(["pr", "a.mp3", "b.md", "--base", "dev", "--allow-public"])
        self.assertEqual((args.base, args.remote, args.allow_public, args.dry_run),
                         ("dev", "origin", True, False))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["build", "x.md", "--mock", "--dry-run"])

    def test_talk_date_parsing_ignores_bad_dates(self):
        self.assertIsNone(pt.talk_meta("20261399_x_wake", {}).day)
        self.assertEqual(pt.talk_meta("20261018_x_wake", {}).day, date(2026, 10, 18))


if __name__ == "__main__":
    unittest.main()
