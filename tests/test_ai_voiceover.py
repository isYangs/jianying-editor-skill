# ruff: noqa: E402

import asyncio
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(CURRENT_DIR)
SCRIPTS_PATH = os.path.join(SKILL_ROOT, "scripts")
os.environ["JY_SKILL_ROOT"] = SKILL_ROOT
if SCRIPTS_PATH not in sys.path:
    sys.path.insert(0, SCRIPTS_PATH)

from utils.env_setup import setup_env

setup_env()

from core.text_ops import TextOpsMixin
from universal_tts import build_atempo_filter, split_voiceover_sentences


class TestVoiceoverAudioUtilities(unittest.TestCase):
    def test_split_voiceover_sentences_preserves_terminal_punctuation(self):
        self.assertEqual(
            split_voiceover_sentences("第一句。第二句！还有，半句"),
            ["第一句。", "第二句！", "还有，半句"],
        )

    def test_build_atempo_filter_supports_normal_and_chained_speed(self):
        self.assertEqual(build_atempo_filter(1.2), "atempo=1.2")
        self.assertEqual(build_atempo_filter(4.0), "atempo=2,atempo=2")


class TestAiVoiceoverTimeline(unittest.TestCase):
    def test_add_ai_voiceover_prepares_every_asset_before_editing_timeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = _FakeProject(temp_dir)
            generated = SimpleNamespace(
                text="第一句。第二句。",
                reasoning="reasoning",
                model="deepseek-r1",
                conversation_id="conversation-1",
                message_id="message-1",
            )
            tts = AsyncMock(side_effect=[("first.ogg", "sami"), (None, None)])

            with (
                patch("core.text_ops.generate_ai_script", new=AsyncMock(return_value=generated)),
                patch("core.text_ops.generate_voice_with_meta", new=tts),
                patch("core.text_ops.speed_up_audio") as speed_up,
            ):
                with self.assertRaisesRegex(RuntimeError, "第二句"):
                    asyncio.run(project.add_ai_voiceover_async("写稿"))

            speed_up.assert_not_called()
            self.assertEqual(project.media_calls, [])
            self.assertEqual(project.text_calls, [])

    def test_add_ai_voiceover_adds_speed_audio_and_matching_subtitles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = _FakeProject(temp_dir)
            generated = SimpleNamespace(
                text="第一句。第二句。",
                reasoning="reasoning",
                model="deepseek-r1",
                conversation_id="conversation-1",
                message_id="message-1",
            )

            async def fake_tts(text, output_path, speaker, **kwargs):
                with open(output_path, "wb") as file:
                    file.write(text.encode("utf-8"))
                return output_path, "sami"

            def fake_speed(source, output, speed):
                with open(output, "wb") as file:
                    file.write(b"speed")
                return output

            with (
                patch("core.text_ops.generate_ai_script", new=AsyncMock(return_value=generated)),
                patch("core.text_ops.generate_voice_with_meta", new=fake_tts),
                patch("core.text_ops.speed_up_audio", side_effect=fake_speed),
                patch("core.text_ops.get_duration_ffprobe_cached", return_value=2.0),
            ):
                result = asyncio.run(
                    project.add_ai_voiceover_async(
                        "写稿",
                        start_time="1s",
                        speed=1.2,
                        sentence_gap="100ms",
                    )
                )

            self.assertEqual(len(project.media_calls), 2)
            self.assertEqual(project.media_calls[0]["start_time"], 1_000_000)
            self.assertEqual(project.media_calls[1]["start_time"], 3_100_000)
            self.assertEqual(project.media_calls[0]["track_name"], "AI VoiceOver")
            self.assertEqual(project.text_calls[0]["text"], "第一句。")
            self.assertEqual(project.text_calls[0]["duration"], 2_000_000)
            self.assertEqual(project.text_calls[1]["start_time"], 3_100_000)
            self.assertEqual(result["text"], "第一句。第二句。")
            self.assertEqual(result["speaker"], "ICL_zh_female_manbo_jianying")
            self.assertEqual(result["speed"], 1.2)
            self.assertEqual(result["end_time"], 5_200_000)
            self.assertEqual(len(result["audio_segments"]), 2)
            self.assertEqual(len(result["subtitle_segments"]), 2)

    def test_sync_api_works_inside_an_active_event_loop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = _FakeProject(temp_dir)
            generated = SimpleNamespace(
                text="事件循环测试。",
                reasoning="reasoning",
                model="deepseek-r1",
                conversation_id="conversation-1",
                message_id="message-1",
            )

            async def fake_tts(text, output_path, speaker, **kwargs):
                with open(output_path, "wb") as file:
                    file.write(b"audio")
                return output_path, "sami"

            def fake_speed(source, output, speed):
                with open(output, "wb") as file:
                    file.write(b"speed")
                return output

            async def invoke_sync_api():
                return project.add_ai_voiceover("写稿")

            with (
                patch("core.text_ops.generate_ai_script", new=AsyncMock(return_value=generated)),
                patch("core.text_ops.generate_voice_with_meta", new=fake_tts),
                patch("core.text_ops.speed_up_audio", side_effect=fake_speed),
                patch("core.text_ops.get_duration_ffprobe_cached", return_value=1.0),
            ):
                result = asyncio.run(invoke_sync_api())

            self.assertEqual(result["text"], "事件循环测试。")
            self.assertEqual(len(project.media_calls), 1)
            self.assertEqual(len(project.text_calls), 1)


class _FakeProject(TextOpsMixin):
    def __init__(self, root):
        self.root = root
        self.name = "test-project"
        self.media_calls = []
        self.text_calls = []

    def get_track_duration(self, track_name):
        return 0

    def add_media_safe(self, media_path, start_time=None, duration=None, track_name=None, **kwargs):
        call = {
            "media_path": media_path,
            "start_time": start_time,
            "duration": duration,
            "track_name": track_name,
        }
        self.media_calls.append(call)
        return SimpleNamespace(
            target_timerange=SimpleNamespace(start=start_time, duration=duration or 2_000_000)
        )

    def add_text_simple(self, text, start_time=None, duration="3s", track_name="Subtitles", **kwargs):
        call = {
            "text": text,
            "start_time": start_time,
            "duration": duration,
            "track_name": track_name,
        }
        self.text_calls.append(call)
        return SimpleNamespace(
            text=text,
            target_timerange=SimpleNamespace(start=start_time, duration=duration),
        )


if __name__ == "__main__":
    unittest.main()
