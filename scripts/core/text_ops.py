import asyncio
import copy
import os
import re
import threading
import uuid
from typing import Union

import pyJianYingDraft as draft
from jianying_ai_writer import DEFAULT_MODEL, generate_ai_script
from universal_tts import (
    generate_voice_with_meta,
    speed_up_audio,
    split_voiceover_sentences,
)
from utils.formatters import get_duration_ffprobe_cached, safe_tim

MANBO_STORYTELLER_SPEAKER = "ICL_zh_female_manbo_jianying"


def _run_coroutine_sync(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    box = {"result": None, "error": None}

    def _worker():
        try:
            box["result"] = asyncio.run(coroutine)
        except Exception as exc:
            box["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    worker.join()
    if box["error"] is not None:
        raise box["error"]
    return box["result"]


class TextOpsMixin:
    """
    JyProject 的文本与字幕 Mixin。
    """

    def add_text_simple(
        self,
        text: str,
        start_time: Union[str, int] = None,
        duration: Union[str, int] = "3s",
        track_name: str = "Subtitles",
        **kwargs,
    ):
        if start_time is None:
            start_time = self.get_track_duration(track_name)
        self._ensure_track(draft.TrackType.text, track_name)

        start_us = safe_tim(start_time)
        dur_us = safe_tim(duration)

        # 兼容高层参数：动画参数不透传给 TextSegment，避免底层 __init__ 报 unexpected kw。
        anim_in = kwargs.pop("anim_in", None)
        anim_out = kwargs.pop("anim_out", None)
        anim_loop = kwargs.pop("anim_loop", None)
        anim_in_duration = kwargs.pop("anim_in_duration", None)
        anim_out_duration = kwargs.pop("anim_out_duration", None)
        anim_loop_duration = kwargs.pop("anim_loop_duration", None)

        # 仅透传 TextSegment 支持的字段
        allowed_keys = {"font", "style", "clip_settings", "border", "background", "shadow"}
        text_kwargs = {k: v for k, v in kwargs.items() if k in allowed_keys}
        # 统一默认字幕样式：字号 5 + 黑色描边
        if "style" not in text_kwargs:
            text_kwargs["style"] = draft.TextStyle(size=5.0)
        if "border" not in text_kwargs:
            text_kwargs["border"] = draft.TextBorder(color=(0.0, 0.0, 0.0), alpha=1.0, width=40.0)
        if "clip_settings" not in text_kwargs:
            text_kwargs["clip_settings"] = draft.ClipSettings(transform_y=-0.8)

        seg = draft.TextSegment(text, draft.Timerange(start_us, dur_us), **text_kwargs)

        # 为动画名称做同义词+模糊解析，支持如 "Typewriter" -> "复古打字机"
        if anim_in:
            intro_enum = self._resolve_enum(draft.TextIntro, str(anim_in))
            if intro_enum:
                seg.add_animation(intro_enum, duration=anim_in_duration)
        if anim_out:
            outro_enum = self._resolve_enum(draft.TextOutro, str(anim_out))
            if outro_enum:
                seg.add_animation(outro_enum, duration=anim_out_duration)
        if anim_loop:
            loop_enum = self._resolve_enum(draft.TextLoopAnim, str(anim_loop))
            if loop_enum:
                seg.add_animation(loop_enum, duration=anim_loop_duration)

        self.script.add_segment(seg, track_name)
        return seg

    def add_narrated_subtitles(
        self,
        text: str,
        speaker: str = "zh_female_xiaopengyou",
        start_time: Union[str, int] = None,
        track_name: str = "Subtitles",
    ):
        if start_time is None:
            start_time = self.get_track_duration(track_name)
        curr_us = safe_tim(start_time)
        chosen_backend = None

        parts = [p for p in re.split(r"([，。！？、\n\r]+)", text) if p.strip()]
        sentences = []
        for i in range(0, len(parts), 2):
            s = parts[i]
            if i + 1 < len(parts):
                s += parts[i + 1]
            sentences.append(s.strip())

        for s in sentences:
            clean_text = s.rstrip("，。！？、\n\r ")
            if not clean_text:
                continue

            audio_seg, backend_used = self.add_tts_intelligent(
                clean_text,
                speaker=speaker,
                start_time=curr_us,
                tts_backend=chosen_backend,
                allow_fallback=(chosen_backend is None),
                return_backend=True,
            )
            if audio_seg:
                if chosen_backend is None:
                    chosen_backend = backend_used
                actual_dur_us = audio_seg.target_timerange.duration
                # 默认设置为屏幕底部 (transform_y=-0.8)
                clip_settings = draft.ClipSettings(transform_y=-0.8)
                subtitle_style = draft.TextStyle(size=5.0)
                subtitle_border = draft.TextBorder(color=(0.0, 0.0, 0.0), alpha=1.0, width=40.0)
                self.add_text_simple(
                    clean_text,
                    start_time=curr_us,
                    duration=actual_dur_us,
                    track_name=track_name,
                    clip_settings=clip_settings,
                    style=subtitle_style,
                    border=subtitle_border,
                )
                curr_us += actual_dur_us + 100000
            else:
                if chosen_backend is not None:
                    raise RuntimeError(
                        f"TTS segment failed under locked backend '{chosen_backend}'. "
                        "Stopped to avoid mixed voice providers."
                    )
        return curr_us

    def add_ai_voiceover(
        self,
        prompt: str,
        *,
        start_time: Union[str, int] = None,
        speaker: str = MANBO_STORYTELLER_SPEAKER,
        speed: float = 1.2,
        sentence_gap: Union[str, int] = "100ms",
        voice_track: str = "AI VoiceOver",
        subtitle_track: str = "AI Subtitles",
        model: str = DEFAULT_MODEL,
        need_reasoning: bool = True,
        writer_credentials=None,
        writer_timeout: float = 120.0,
    ):
        """Generate a JianYing AI script, voice it, and add synchronized subtitles."""
        return _run_coroutine_sync(
            self.add_ai_voiceover_async(
                prompt,
                start_time=start_time,
                speaker=speaker,
                speed=speed,
                sentence_gap=sentence_gap,
                voice_track=voice_track,
                subtitle_track=subtitle_track,
                model=model,
                need_reasoning=need_reasoning,
                writer_credentials=writer_credentials,
                writer_timeout=writer_timeout,
            )
        )

    async def add_ai_voiceover_async(
        self,
        prompt: str,
        *,
        start_time: Union[str, int] = None,
        speaker: str = MANBO_STORYTELLER_SPEAKER,
        speed: float = 1.2,
        sentence_gap: Union[str, int] = "100ms",
        voice_track: str = "AI VoiceOver",
        subtitle_track: str = "AI Subtitles",
        model: str = DEFAULT_MODEL,
        need_reasoning: bool = True,
        writer_credentials=None,
        writer_timeout: float = 120.0,
    ):
        if float(speed) <= 0:
            raise ValueError("speed must be greater than zero")
        if start_time is None:
            start_time = max(
                self.get_track_duration(voice_track),
                self.get_track_duration(subtitle_track),
            )

        generated = await generate_ai_script(
            prompt,
            credentials=writer_credentials,
            model=model,
            need_reasoning=need_reasoning,
            timeout=writer_timeout,
        )
        sentences = split_voiceover_sentences(generated.text)
        if not sentences:
            raise RuntimeError("JianYing AI writer returned no usable voiceover sentences")

        temp_dir = os.path.join(self.root, self.name, "temp_assets", "ai_voiceover")
        os.makedirs(temp_dir, exist_ok=True)
        batch_id = uuid.uuid4().hex[:12]
        raw_assets = []

        # Generate every sentence before touching the timeline.
        for index, sentence in enumerate(sentences, 1):
            raw_path = os.path.join(temp_dir, f"{batch_id}_{index:03d}_raw.ogg")
            actual_path, backend = await generate_voice_with_meta(
                sentence,
                raw_path,
                speaker,
                backend="sami",
                allow_fallback=False,
                sami_retries=2,
            )
            if not actual_path or backend != "sami":
                raise RuntimeError(f"曼波讲故事配音失败：第 {index} 句“{sentence}”")
            raw_assets.append((sentence, actual_path))

        prepared_assets = []
        for index, (sentence, raw_path) in enumerate(raw_assets, 1):
            speed_path = os.path.join(temp_dir, f"{batch_id}_{index:03d}_{speed:g}x.ogg")
            actual_path = await asyncio.to_thread(
                speed_up_audio,
                raw_path,
                speed_path,
                speed,
            )
            duration_seconds = await asyncio.to_thread(
                get_duration_ffprobe_cached,
                actual_path,
            )
            if duration_seconds <= 0:
                raise RuntimeError(f"无法读取第 {index} 句变速音频时长：{actual_path}")
            prepared_assets.append(
                {
                    "text": sentence,
                    "path": actual_path,
                    "duration": int(round(duration_seconds * 1_000_000)),
                }
            )

        start_us = safe_tim(start_time)
        cursor = start_us
        gap_us = safe_tim(sentence_gap)
        audio_segments = []
        subtitle_segments = []
        script_snapshot = copy.deepcopy(self.script) if hasattr(self, "script") else None

        try:
            for asset in prepared_assets:
                audio_segment = self.add_media_safe(
                    asset["path"],
                    start_time=cursor,
                    duration=asset["duration"],
                    track_name=voice_track,
                )
                if audio_segment is None:
                    raise RuntimeError(f"无法将配音加入时间线：{asset['path']}")
                subtitle_segment = self.add_text_simple(
                    asset["text"],
                    start_time=cursor,
                    duration=asset["duration"],
                    track_name=subtitle_track,
                )
                audio_segments.append(audio_segment)
                subtitle_segments.append(subtitle_segment)
                cursor += asset["duration"] + gap_us
        except Exception:
            if script_snapshot is not None:
                self.script = script_snapshot
            raise

        return {
            "text": generated.text,
            "reasoning": generated.reasoning,
            "model": generated.model,
            "conversation_id": generated.conversation_id,
            "message_id": generated.message_id,
            "speaker": speaker,
            "speed": float(speed),
            "start_us": start_us,
            "end_us": cursor,
            "audio_segments": audio_segments,
            "subtitle_segments": subtitle_segments,
            "end_time": cursor,
        }

    def add_tts_intelligent(
        self,
        text: str,
        speaker: str = "zh_male_huoli",
        start_time: Union[str, int] = None,
        track_name: str = "VoiceOver",
        tts_backend: str = None,
        allow_fallback: bool = True,
        return_backend: bool = False,
    ):
        import uuid

        from universal_tts import generate_voice_with_meta

        if start_time is None:
            start_time = self.get_track_duration(track_name)

        temp_dir = os.path.join(self.root, self.name, "temp_assets")
        os.makedirs(temp_dir, exist_ok=True)
        output_file = os.path.join(temp_dir, f"tts_{uuid.uuid4().hex[:8]}.ogg")

        async def _generate():
            return await generate_voice_with_meta(
                text,
                output_file,
                speaker,
                backend=tts_backend,
                allow_fallback=allow_fallback,
                sami_retries=2,
            )

        try:
            asyncio.get_running_loop()
            loop_running = True
        except Exception:
            loop_running = False

        if loop_running:
            box = {"path": None, "err": None}

            def _worker():
                try:
                    box["path"] = asyncio.run(_generate())
                except Exception as e:
                    box["err"] = e

            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            t.join()
            if box["err"] is not None:
                raise box["err"]
            actual_path, backend_used = box["path"] if box["path"] else (None, None)
        else:
            actual_path, backend_used = asyncio.run(_generate())

        if not actual_path:
            return (None, None) if return_backend else None
        seg = self.add_media_safe(actual_path, start_time, track_name=track_name)
        return (seg, backend_used) if return_backend else seg

    async def add_tts_intelligent_async(
        self,
        text: str,
        speaker: str = "zh_male_huoli",
        start_time: Union[str, int] = None,
        track_name: str = "VoiceOver",
    ):
        import uuid

        from universal_tts import generate_voice

        if start_time is None:
            start_time = self.get_track_duration(track_name)

        temp_dir = os.path.join(self.root, self.name, "temp_assets")
        os.makedirs(temp_dir, exist_ok=True)
        output_file = os.path.join(temp_dir, f"tts_{uuid.uuid4().hex[:8]}.ogg")
        actual_path = await generate_voice(text, output_file, speaker)
        if not actual_path:
            return None
        return self.add_media_safe(actual_path, start_time, track_name=track_name)
