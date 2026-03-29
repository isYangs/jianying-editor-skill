import os
import uuid
import json
import subprocess
import pymediainfo

from typing import Optional, Literal
from typing import Dict, Any


def _get_video_info_ffprobe(path: str) -> Optional[Dict]:
    """使用 ffprobe 获取视频信息（pymediainfo 的 fallback）"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=width,height,duration",
        "-show_entries", "format=duration",
        "-of", "json",
        path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            duration = None
            
            # 优先取视频轨道的 duration
            for stream in streams:
                if stream.get("codec_type") == "video":
                    return {
                        "width": stream.get("width", 1920),
                        "height": stream.get("height", 1080),
                        "duration": stream.get("duration")
                    }
            
            # 否则取 format 的 duration
            fmt = data.get("format", {})
            if fmt.get("duration"):
                return {
                    "width": 1920,
                    "height": 1080,
                    "duration": float(fmt["duration"])
                }
    except Exception:
        pass
    return None


def _get_audio_info_ffprobe(path: str) -> Optional[float]:
    """使用 ffprobe 获取音频时长（pymediainfo 的 fallback）"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            fmt = data.get("format", {})
            if fmt.get("duration"):
                return float(fmt["duration"])
    except Exception:
        pass
    return None

class CropSettings:
    """素材的裁剪设置, 各属性均在0-1之间, 注意素材的坐标原点在左上角"""

    upper_left_x: float
    upper_left_y: float
    upper_right_x: float
    upper_right_y: float
    lower_left_x: float
    lower_left_y: float
    lower_right_x: float
    lower_right_y: float

    def __init__(self, *, upper_left_x: float = 0.0, upper_left_y: float = 0.0,
                 upper_right_x: float = 1.0, upper_right_y: float = 0.0,
                 lower_left_x: float = 0.0, lower_left_y: float = 1.0,
                 lower_right_x: float = 1.0, lower_right_y: float = 1.0):
        """初始化裁剪设置, 默认参数表示不裁剪"""
        self.upper_left_x = upper_left_x
        self.upper_left_y = upper_left_y
        self.upper_right_x = upper_right_x
        self.upper_right_y = upper_right_y
        self.lower_left_x = lower_left_x
        self.lower_left_y = lower_left_y
        self.lower_right_x = lower_right_x
        self.lower_right_y = lower_right_y

    def export_json(self) -> Dict[str, Any]:
        return {
            "upper_left_x": self.upper_left_x,
            "upper_left_y": self.upper_left_y,
            "upper_right_x": self.upper_right_x,
            "upper_right_y": self.upper_right_y,
            "lower_left_x": self.lower_left_x,
            "lower_left_y": self.lower_left_y,
            "lower_right_x": self.lower_right_x,
            "lower_right_y": self.lower_right_y
        }

class VideoMaterial:
    """本地视频素材（视频或图片）, 一份素材可以在多个片段中使用"""

    material_id: str
    """素材全局id, 自动生成"""
    local_material_id: str
    """素材本地id, 意义暂不明确"""
    material_name: str
    """素材名称"""
    path: str
    """素材文件路径"""
    duration: int
    """素材时长, 单位为微秒"""
    height: int
    """素材高度"""
    width: int
    """素材宽度"""
    crop_settings: CropSettings
    """素材裁剪设置"""
    material_type: Literal["video", "photo"]
    """素材类型: 视频或图片"""

    def __init__(self, path: str, material_name: Optional[str] = None, crop_settings: CropSettings = CropSettings(), duration: Optional[int] = None):
        """从指定位置加载视频（或图片）素材
        Args:
            duration (`int`, optional): 某些格式(如webm)解析可能会失败, 此时可手动传入时长(us)
        """
        path = os.path.abspath(path)
        postfix = os.path.splitext(path)[1]
        if not os.path.exists(path):
            raise FileNotFoundError(f"找不到 {path}")

        self.material_name = material_name if material_name else os.path.basename(path)
        self.material_id = uuid.uuid4().hex
        self.path = path
        self.crop_settings = crop_settings
        self.local_material_id = ""

        # 检查 pymediainfo 是否可用
        can_parse = False
        try:
            can_parse = pymediainfo.MediaInfo.can_parse()
        except Exception:
            pass

        if not can_parse:
            # pymediainfo 不可用，尝试用 ffprobe
            ffprobe_info = _get_video_info_ffprobe(path)
            if ffprobe_info:
                self.material_type = "video"
                self.width = ffprobe_info.get("width", 1920)
                self.height = ffprobe_info.get("height", 1080)
                dur = ffprobe_info.get("duration")
                if dur:
                    self.duration = int(dur * 1e6)
                elif duration is not None:
                    self.duration = duration
                else:
                    self.duration = 10 * 1000 * 1000  # 10s default
            elif duration is not None:
                # 最后 fallback：使用传入的 duration
                self.material_type = "video"
                self.duration = duration
                self.width, self.height = 1920, 1080
            else:
                raise ValueError(f"无法解析视频 '{path}'，pymediainfo 和 ffprobe 都不可用")
            return

        try:
            info: pymediainfo.MediaInfo = \
                pymediainfo.MediaInfo.parse(path, mediainfo_options={"File_TestContinuousFileNames": "0"})  # type: ignore
            
            # 有视频轨道的视为视频素材
            if len(info.video_tracks):
                self.material_type = "video"
                parsed_duration = info.video_tracks[0].duration
                
                if parsed_duration:
                    self.duration = int(parsed_duration * 1e3)
                else:
                    # 如果解析出来是 None (WebM 常见情况)
                    if duration is not None:
                        self.duration = duration
                    else:
                        # 既无法解析又没传参数，只能给个默认值防止崩
                        self.duration = 10 * 1000 * 1000 # 10s default
                        
                self.width, self.height = info.video_tracks[0].width, info.video_tracks[0].height 
            
            # gif文件使用 ffprobe 获取长度
            elif postfix.lower() == ".gif":
                ffprobe_info = _get_video_info_ffprobe(path)
                if ffprobe_info:
                    self.material_type = "video"
                    self.width = ffprobe_info.get("width", 1920)
                    self.height = ffprobe_info.get("height", 1080)
                    dur = ffprobe_info.get("duration")
                    self.duration = int(dur * 1e6) if dur else 10 * 1000 * 1000
                else:
                    self.material_type = "video"
                    self.duration = 10 * 1000 * 1000  # 10s default
                    self.width, self.height = 1920, 1080

            elif len(info.image_tracks):
                self.material_type = "photo"
                self.duration = 10800000000  # 相当于3h
                self.width, self.height = info.image_tracks[0].width, info.image_tracks[0].height 
            else:
                 # Fallback for WebM or other formats if pymediainfo detect no tracks but file exists
                if duration is not None:
                    self.material_type = "video"
                    self.duration = duration
                    self.width, self.height = 1920, 1080
                else:
                    raise ValueError(f"输入的素材文件 {path} 没有视频轨道或图片轨道")

        except Exception as e:
            # Global Fallback
            if duration is not None:
                 self.material_type = "video"
                 self.duration = duration
                 self.width, self.height = 1920, 1080
            else:
                raise e

    def export_json(self) -> Dict[str, Any]:
        video_material_json = {
            "audio_fade": None,
            "category_id": "",
            "category_name": "local",
            "check_flag": 63487,
            "crop": self.crop_settings.export_json(),
            "crop_ratio": "free",
            "crop_scale": 1.0,
            "duration": self.duration,
            "height": self.height,
            "id": self.material_id,
            "local_material_id": self.local_material_id,
            "material_id": self.material_id,
            "material_name": self.material_name,
            "media_path": "",
            "path": self.path,
            "type": self.material_type,
            "width": self.width
        }
        return video_material_json

class AudioMaterial:
    """本地音频素材"""

    material_id: str
    """素材全局id, 自动生成"""
    material_name: str
    """素材名称"""
    path: str
    """素材文件路径"""

    duration: int
    """素材时长, 单位为微秒"""

    def __init__(self, path: str, material_name: Optional[str] = None):
        """从指定位置加载音频素材, 注意视频文件不应该作为音频素材使用

        Args:
            path (`str`): 素材文件路径, 支持mp3, wav等常见音频文件.
            material_name (`str`, optional): 素材名称, 如果不指定, 默认使用文件名作为素材名称.

        Raises:
            `FileNotFoundError`: 素材文件不存在.
            `ValueError`: 不支持的素材文件类型.
        """
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"找不到 {path}")

        self.material_name = material_name if material_name else os.path.basename(path)
        self.material_id = uuid.uuid4().hex
        self.path = path

        # 检查 pymediainfo 是否可用
        can_parse = False
        try:
            can_parse = pymediainfo.MediaInfo.can_parse()
        except Exception:
            pass

        if not can_parse:
            # pymediainfo 不可用，尝试用 ffprobe
            ffprobe_dur = _get_audio_info_ffprobe(path)
            if ffprobe_dur:
                self.duration = int(ffprobe_dur * 1e6)
                return
            raise ValueError("不支持的音频素材类型 %s" % os.path.splitext(path)[1])

        info: pymediainfo.MediaInfo = pymediainfo.MediaInfo.parse(path)  # type: ignore
        if len(info.video_tracks):
            raise ValueError("音频素材不应包含视频轨道")
        if not len(info.audio_tracks):
            raise ValueError(f"给定的素材文件 {path} 没有音频轨道")
        self.duration = int(info.audio_tracks[0].duration * 1e3)  # type: ignore

    def export_json(self) -> Dict[str, Any]:
        return {
            "app_id": 0,
            "category_id": "",
            "category_name": "local",
            "check_flag": 3,
            "copyright_limit_type": "none",
            "duration": self.duration,
            "effect_id": "",
            "formula_id": "",
            "id": self.material_id,
            "local_material_id": self.material_id,
            "music_id": self.material_id,
            "name": self.material_name,
            "path": self.path,
            "source_platform": 0,
            "type": "extract_music",
            "wave_points": []
        }
