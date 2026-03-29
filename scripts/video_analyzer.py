"""
视频内容分析模块 (Video Content Analyzer)

功能:
    1. 抽帧提取关键帧
    2. 场景变更检测
    3. 根据字幕内容匹配最佳画面

依赖:
    - ffmpeg (系统命令)
    - numpy
"""

import os
import subprocess
import json
import hashlib
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class Frame:
    """单帧信息"""
    timestamp: float  # 秒
    frame_num: int
    path: str  # 缩略图路径
    scene_change: bool = False


@dataclass
class Scene:
    """场景片段"""
    start_time: float
    end_time: float
    duration: float
    keyframe: Optional[Frame] = None
    description: str = ""


def run_ffmpeg(cmd: List[str]) -> Tuple[bool, str]:
    """执行 ffmpeg 命令"""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
        return result.returncode == 0, result.stderr
    except subprocess.TimeoutExpired:
        return False, "Command timeout"
    except Exception as e:
        return False, str(e)


def extract_keyframes(video_path: str, output_dir: str, interval: float = 1.0) -> List[Frame]:
    """
    按时间间隔抽帧

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录
        interval: 抽帧间隔（秒）

    Returns:
        Frame 列表
    """
    os.makedirs(output_dir, exist_ok=True)

    # 使用 ffmpeg 抽帧
    output_pattern = os.path.join(output_dir, "frame_%06d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps=1/{interval}",
        "-q:v", "2",
        output_pattern
    ]

    success, msg = run_ffmpeg(cmd)
    if not success:
        print(f"⚠️ FFmpeg抽帧失败: {msg}")
        return []

    # 收集抽出的帧
    frames = []
    frame_files = sorted([f for f in os.listdir(output_dir) if f.startswith("frame_")])

    for i, fname in enumerate(frame_files):
        timestamp = (i + 1) * interval
        frames.append(Frame(
            timestamp=timestamp,
            frame_num=i + 1,
            path=os.path.join(output_dir, fname)
        ))

    return frames


def detect_scene_changes(video_path: str, output_dir: str, threshold: float = 0.3) -> List[Scene]:
    """
    场景变更检测

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录和缩略图目录
        threshold: 场景变更阈值 (0-1)

    Returns:
        Scene 列表
    """
    os.makedirs(output_dir, exist_ok=True)

    # 使用 ffmpeg scene detection
    scenes_file = os.path.join(output_dir, "scenes.txt")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null",
        "-"
    ]

    success, msg = run_ffmpeg(cmd)
    if not success:
        # 回退到间隔抽帧
        frames = extract_keyframes(video_path, output_dir, interval=2.0)
        return _frames_to_scenes(frames)

    # 解析场景变更点
    scenes = []
    timestamps = []

    for line in msg.split('\n'):
        if 'pts_time:' in line:
            try:
                ts = float(line.split('pts_time:')[1].split()[0])
                timestamps.append(ts)
            except:
                pass

    if not timestamps:
        # 回退
        frames = extract_keyframes(video_path, output_dir, interval=2.0)
        return _frames_to_scenes(frames)

    # 生成场景片段
    for i, ts in enumerate(timestamps):
        start = ts
        end = timestamps[i + 1] if i + 1 < len(timestamps) else None
        if end:
            scenes.append(Scene(
                start_time=start,
                end_time=end,
                duration=end - start,
                keyframe=Frame(timestamp=start, frame_num=i, path="")
            ))

    return scenes


def _frames_to_scenes(frames: List[Frame]) -> List[Scene]:
    """将帧列表转换为场景列表"""
    if not frames:
        return []

    scenes = []
    current_scene_start = frames[0].timestamp

    for i in range(1, len(frames)):
        # 简单逻辑：间隔超过3秒视为新场景
        if frames[i].timestamp - frames[i-1].timestamp > 3.0:
            scenes.append(Scene(
                start_time=current_scene_start,
                end_time=frames[i-1].timestamp,
                duration=frames[i-1].timestamp - current_scene_start,
                keyframe=frames[i-1]
            ))
            current_scene_start = frames[i].timestamp

    # 最后一个场景
    scenes.append(Scene(
        start_time=current_scene_start,
        end_time=frames[-1].timestamp,
        duration=frames[-1].timestamp - current_scene_start,
        keyframe=frames[-1]
    ))

    return scenes


def analyze_video(video_path: str, work_dir: Optional[str] = None) -> Dict:
    """
    完整分析视频内容

    Returns:
        {
            "duration": float,
            "scenes": List[Scene],
            "keyframes": List[Frame],
            "summary": str
        }
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    if work_dir is None:
        work_dir = os.path.join(os.path.dirname(video_path), "_analyze")
    os.makedirs(work_dir, exist_ok=True)

    # 获取视频时长
    duration = get_video_duration(video_path)

    # 抽帧
    frames = extract_keyframes(video_path, work_dir, interval=2.0)

    # 场景检测
    scenes = detect_scene_changes(video_path, work_dir)

    # 生成描述
    summary = f"视频时长 {duration:.1f}秒，共检测到 {len(scenes)} 个场景片段"

    return {
        "duration": duration,
        "scenes": scenes,
        "keyframes": frames,
        "summary": summary
    }


def get_video_duration(video_path: str) -> float:
    """获取视频时长（秒）"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data['format']['duration'])
    except:
        pass

    return 0.0


def match_subtitle_to_scene(subtitle_text: str, scenes: List[Scene],
                              frame_descriptions: Optional[Dict] = None) -> Optional[Scene]:
    """
    根据字幕内容匹配最佳场景

    Args:
        subtitle_text: 字幕文本
        scenes: 场景列表
        frame_descriptions: 帧描述（可选，用于更精确匹配）

    Returns:
        最佳匹配的 Scene 或 None
    """
    # 关键词匹配规则
    keywords_map = {
        "开箱": ["开箱", "包装", "拆箱"],
        "外观": ["外观", "设计", "颜值", "颜色"],
        "功能": ["功能", "特点", "配置"],
        "测试": ["测试", "实验", "效果"],
        "总结": ["总结", "最后", "总之"],
        "价格": ["价格", "多少钱", "性价比"],
        "对比": ["对比", "比较", "区别"],
    }

    matched_keywords = []
    for category, keywords in keywords_map.items():
        if any(kw in subtitle_text for kw in keywords):
            matched_keywords.append(category)

    if not matched_keywords:
        # 默认返回中间位置
        mid = len(scenes) // 2
        return scenes[mid] if scenes else None

    # 根据关键词选择场景位置
    if "开箱" in matched_keywords:
        return scenes[0] if scenes else None
    elif "总结" in matched_keywords or "价格" in matched_keywords:
        return scenes[-1] if scenes else None
    else:
        # 功能/测试类返回中间
        mid = len(scenes) // 2
        return scenes[mid] if scenes else None


def extract_frames_for_subtitles(video_path: str, subtitles: List[Dict],
                                  output_dir: str) -> List[Dict]:
    """
    为字幕提取最佳匹配帧

    Args:
        video_path: 视频路径
        subtitles: 字幕列表 [{start, end, text}, ...]
        output_dir: 输出目录

    Returns:
        [{subtitle: {}, frame: Frame, scene: Scene}, ...]
    """
    # 分析视频
    result = analyze_video(video_path, output_dir)
    scenes = result["scenes"]
    frames = result["keyframes"]

    matches = []

    for sub in subtitles:
        # 找到该字幕对应的时间点
        sub_start = sub.get("start", 0)

        # 找最近的关键帧
        best_frame = None
        min_diff = float('inf')
        for frame in frames:
            diff = abs(frame.timestamp - sub_start)
            if diff < min_diff:
                min_diff = diff
                best_frame = frame

        # 匹配场景
        matched_scene = match_subtitle_to_scene(sub.get("text", ""), scenes)

        matches.append({
            "subtitle": sub,
            "frame": best_frame,
            "scene": matched_scene,
            "timestamp": best_frame.timestamp if best_frame else sub_start
        })

    return matches


# 命令行接口
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python video_analyzer.py <视频路径> [输出目录]")
        sys.exit(1)

    video_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"🔍 分析视频: {video_path}")
    result = analyze_video(video_path, output_dir)
    print(f"\n📊 {result['summary']}")

    for i, scene in enumerate(result['scenes'][:10]):
        print(f"  场景{i+1}: {scene.start_time:.1f}s - {scene.end_time:.1f}s ({scene.duration:.1f}s)")
