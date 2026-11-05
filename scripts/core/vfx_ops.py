import os
import time
from typing import Union, Optional
import pyJianYingDraft as draft
from utils.formatters import safe_tim, tim

# 兼容补丁：Transition 类未从包顶层导出 (video_segment.Transition)
try:
    draft.Transition
except AttributeError:
    from pyJianYingDraft.video_segment import Transition as _Transition
    draft.Transition = _Transition

class VfxOpsMixin:
    """
    JyProject 的特效与转场 Mixin。
    """
    def add_effect_simple(self, effect_name: str, start_time: Union[str, int] = None, duration: Union[str, int] = "3s", track_name: str = "EffectTrack"):
        if start_time is None:
            start_time = self.get_track_duration(track_name)
        self._ensure_track(draft.TrackType.effect, track_name)
        
        eff_type = self._resolve_enum(draft.VideoSceneEffectType, effect_name)
        if not eff_type: return None
        
        # 上游 bug 修复：必须用 ScriptFile.add_effect 注册 effect 素材
        # （旧代码手工建 EffectSegment + add_segment，素材不会进 materials，草稿里特效丢失）
        self.script.add_effect(eff_type, draft.Timerange(safe_tim(start_time), safe_tim(duration)), track_name)
        return None

    def add_transition_simple(
        self,
        transition_name: str,
        video_segment: Optional[draft.VideoSegment] = None,
        duration: Union[str, int] = "1s",
        track_name: Optional[str] = None,
    ):
        # 兼容调用：如果未直接给 segment，则尝试从指定轨道获取最后一个视频片段
        if video_segment is None and track_name:
            track = self.script.tracks.get(track_name)
            if not track or not getattr(track, "segments", None):
                return None
            video_segment = track.segments[-1]

        if video_segment is None:
            return None

        trans_type = self._resolve_enum(draft.TransitionType, transition_name)
        if not trans_type: return None
        
        # 上游 bug 修复：VideoSegment.add_transition 期望 (transition_type, duration)，
        # 会自行构造 Transition；且片段已有转场时会抛 ValueError
        if video_segment.transition is not None:
            raise ValueError(f'片段 {video_segment} 已有转场，不能再添加')
        video_segment.add_transition(trans_type, duration=safe_tim(duration))
        # 兼容注册：若转场在片段入轨后才添加，需补登记素材，否则草稿里转场丢失
        if video_segment.transition not in self.script.materials:
            self.script.materials.transitions.append(video_segment.transition)
        return video_segment.transition

    def add_web_asset_safe(self, html_path: str, start_time: Union[str, int] = None, duration: Union[str, int] = "5s", 
                           track_name: str = "WebVfxTrack", output_dir: Optional[str] = None):
        from web_recorder import record_web_animation
        
        if start_time is None:
            start_time = self.get_track_duration(track_name)
        if output_dir is None:
            output_dir = os.path.join(self.root, self.name, "temp_assets")
        os.makedirs(output_dir, exist_ok=True)
        
        video_output = os.path.join(output_dir, f"web_vfx_{int(time.time())}.webm")
        if record_web_animation(html_path, video_output, max_duration=safe_tim(duration)/1e6 + 5):
            return self.add_media_safe(video_output, start_time, duration, track_name=track_name)
        return None
