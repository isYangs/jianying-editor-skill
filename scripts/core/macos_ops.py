"""
macOS 平台特定操作模块

提供 macOS 下的剪映自动化替代方案：
- 草稿目录发现
- 手动导出引导
- 录屏功能（使用 avfoundation）
"""

import os
import sys
import json
import time
import subprocess
import re
from typing import Optional, List, Dict, Any
from pathlib import Path

# =============================================================================
# 剪映草稿目录发现
# =============================================================================

def get_jianying_drafts_root_macos() -> Optional[str]:
    """
    发现 macOS 上剪映的草稿目录。

    macOS 剪映草稿位置：
    /Movies/JianyingPro/User Data/Projects/com.lveditor.draft
    或
    ~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft
    """
    home = os.path.expanduser("~")

    # 可能的路径列表（按优先级排序）
    candidates = [
        # 标准安装位置 /Movies/
        os.path.join(home, "Movies", "JianyingPro", "User Data", "Projects", "com.lveditor.draft"),
        os.path.join("/Movies", "JianyingPro", "User Data", "Projects", "com.lveditor.draft"),
        # 旧版位置 ~/Library/Application Support/
        os.path.join(home, "Library", "Application Support", "JianyingPro", "User Data", "Projects", "com.lveditor.draft"),
        os.path.join(home, "Library", "Application Support", "Jianying", "User Data", "Projects", "com.lveditor.draft"),
        # 容器版
        os.path.join(home, "Library", "Containers", "com.lveditor.Jianying", "Data", "Library", "Application Support", "JianyingPro", "User Data", "Projects", "com.lveditor.draft"),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    # 返回标准位置（即使不存在）
    return os.path.join(home, "Movies", "JianyingPro", "User Data", "Projects", "com.lveditor.draft")


def get_jianying_app_path_macos() -> Optional[str]:
    """
    发现 macOS 上剪映应用的路径。
    """
    candidates = [
        "/Applications/JianyingPro.app",
        "/Applications/剪映专业版.app",
        os.path.expanduser("~/Applications/JianyingPro.app"),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path

    return None


# =============================================================================
# 平台检测
# =============================================================================

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"


# =============================================================================
# macOS 录屏功能
# =============================================================================

class MacOSScreenRecorder:
    """
    macOS 屏幕录制器，使用 ffmpeg + avfoundation。

    支持：
    - 全屏或区域录制
    - 系统音频录制（macOS 10.15+ 需要特殊权限）
    - 鼠标点击标注
    """

    def __init__(self, output_dir: Optional[str] = None, audio_enabled: bool = False):
        self.output_dir = output_dir or os.getcwd()
        os.makedirs(self.output_dir, exist_ok=True)

        self.audio_enabled = audio_enabled
        self.is_recording = False
        self.process: Optional[subprocess.Popen] = None
        self.output_path: Optional[str] = None
        self.events: List[Dict[str, Any]] = []
        self.start_time: float = 0

        # 录屏事件监听
        self._mouse_listener = None
        self._keyboard_listener = None

    def list_capture_devices(self) -> Dict[str, List[str]]:
        """
        列出可用的捕获设备。
        """
        devices = {"video": [], "audio": []}

        # 列出视频设备
        try:
            result = subprocess.run(
                ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
                capture_output=True, text=True, timeout=5
            )
            output = result.stderr

            in_video_section = False
            for line in output.split("\n"):
                if "Video devices" in line:
                    in_video_section = True
                    continue
                if "Audio devices" in line:
                    in_video_section = False
                    continue

                if in_video_section and "]" in line:
                    match = re.search(r'\[(\d+)\]\s*(.+)', line)
                    if match:
                        devices["video"].append(f"{match.group(1)}:{match.group(2).strip()}")

                if not in_video_section and "]" in line and "Audio" not in line:
                    match = re.search(r'\[(\d+)\]\s*(.+)', line)
                    if match:
                        devices["audio"].append(f"{match.group(1)}:{match.group(2).strip()}")
        except Exception as e:
            print(f"⚠️ 设备枚举失败: {e}")

        return devices

    def start_recording(self, video_device: str = "0", include_audio: bool = False,
                       video_filter: Optional[str] = None) -> bool:
        """
        开始屏幕录制。

        Args:
            video_device: 视频设备索引或名称（如 "0" 或 "CaptureScreen0"）
            include_audio: 是否包含音频
            video_filter: 额外的视频滤镜（如裁剪、缩放等）

        Returns:
            是否成功开始录制
        """
        if self.is_recording:
            print("⚠️ 已经在录制中")
            return False

        # 生成输出文件路径
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.output_path = os.path.join(self.output_dir, f"recording_{timestamp}.mp4")

        # 构建 ffmpeg 命令
        cmd = [
            "ffmpeg", "-y",
            "-f", "avfoundation",
            "-framerate", "30",
            "-video_size", "1920x1080",
        ]

        # 视频输入
        if video_device:
            cmd.extend(["-i", video_device])
        else:
            cmd.extend(["-i", "0"])  # 默认第一个屏幕

        # 音频输入
        if include_audio:
            # macOS 上音频设备通常在视频设备之后
            cmd.extend(["-f", "avfoundation", "-audio_device_index", "1"])

        # 视频滤镜
        filters = []
        if video_filter:
            filters.append(video_filter)

        if filters:
            cmd.extend(["-vf", ",".join(filters)])

        # 编码参数
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
        ])

        if include_audio:
            cmd.extend(["-c:a", "aac", "-ar", "44100"])
        else:
            cmd.extend(["-an"])

        cmd.append(self.output_path)

        try:
            # 设置环境
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env
            )

            self.is_recording = True
            self.start_time = time.time()
            self.events = []

            print(f"✅ 开始录制: {self.output_path}")
            return True

        except Exception as e:
            print(f"❌ 录制启动失败: {e}")
            return False

    def stop_recording(self) -> Optional[str]:
        """
        停止录制。

        Returns:
            录制文件的路径，失败返回 None
        """
        if not self.is_recording:
            return None

        self.is_recording = False

        if self.process:
            try:
                # 发送 q 信号停止 ffmpeg
                self.process.stdin.write(b"q")
                self.process.stdin.flush()
                self.process.wait(timeout=10)
            except Exception as e:
                print(f"⚠️ 停止录制时出错: {e}")
                try:
                    self.process.kill()
                except:
                    pass

        # 保存事件数据
        if self.events:
            events_path = self.output_path.replace(".mp4", "_events.json")
            try:
                with open(events_path, "w", encoding="utf-8") as f:
                    json.dump(self.events, f, indent=2, ensure_ascii=False)
                print(f"📋 事件数据已保存: {events_path}")
            except Exception as e:
                print(f"⚠️ 事件保存失败: {e}")

        # 验证输出文件
        if self.output_path and os.path.exists(self.output_path):
            size = os.path.getsize(self.output_path)
            if size > 1000:  # 至少 1KB
                print(f"✅ 录制完成: {self.output_path} ({size / 1024 / 1024:.2f} MB)")
                return self.output_path

        print("❌ 录制文件无效")
        return None

    def record_screen_simple(self, duration: int = 10, output_name: Optional[str] = None) -> Optional[str]:
        """
        简易屏幕录制（指定时长）。

        Args:
            duration: 录制时长（秒）
            output_name: 输出文件名（不含路径）

        Returns:
            录制文件路径
        """
        if output_name:
            self.output_path = os.path.join(self.output_dir, output_name)
        else:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            self.output_path = os.path.join(self.output_dir, f"recording_{timestamp}.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-f", "avfoundation",
            "-framerate", "30",
            "-i", "0",  # 第一个屏幕
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            self.output_path
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
            if result.returncode == 0 and os.path.exists(self.output_path):
                return self.output_path
            else:
                print(f"❌ ffmpeg 错误: {result.stderr[-500:]}")
                return None
        except subprocess.TimeoutExpired:
            print("❌ 录制超时")
            return None
        except Exception as e:
            print(f"❌ 录制失败: {e}")
            return None


# =============================================================================
# macOS 导出引导
# =============================================================================

class MacOSExportGuide:
    """
    macOS 下剪映导出引导。

    由于 macOS 剪映没有自动化 API，此模块提供：
    - 草稿位置信息
    - 导出步骤指引
    - 可能的 AppleScript 交互（如果支持）
    """

    def __init__(self):
        self.drafts_root = get_jianying_drafts_root_macos()
        self.app_path = get_jianying_app_path_macos()

    def get_export_instructions(self, draft_name: str) -> Dict[str, Any]:
        """
        获取导出指导信息。

        Returns:
            包含导出指导和草稿信息的字典
        """
        result = {
            "draft_name": draft_name,
            "draft_path": None,
            "app_path": self.app_path,
            "can_auto_export": False,
            "manual_steps": [
                "1. 打开剪映专业版",
                "2. 在草稿列表中找到并打开项目",
                "3. 点击右上角「导出」按钮",
                "4. 选择导出设置（分辨率、帧率等）",
                "5. 选择导出位置并点击「导出」"
            ]
        }

        if self.drafts_root:
            # 查找草稿路径
            draft_path = os.path.join(self.drafts_root, draft_name)
            if os.path.exists(draft_path):
                result["draft_path"] = draft_path
                result["draft_json_exists"] = os.path.exists(
                    os.path.join(draft_path, "draft_content.json")
                )

        return result

    def open_in_finder(self, draft_name: str) -> bool:
        """
        在 Finder 中显示草稿文件夹。
        """
        if not self.drafts_root:
            return False

        draft_path = os.path.join(self.drafts_root, draft_name)
        if os.path.exists(draft_path):
            subprocess.run(["open", "-R", draft_path])
            return True
        return False

    def open_jianying(self) -> bool:
        """
        尝试打开剪映应用。
        """
        if self.app_path and os.path.exists(self.app_path):
            subprocess.run(["open", "-a", self.app_path])
            return True
        return False


# =============================================================================
# macOS AppleScript 交互（实验性）
# =============================================================================

def try_applescript_control(command: str) -> Optional[str]:
    """
    尝试使用 AppleScript 控制剪映（如果支持）。

    注意：这是实验性功能，取决于剪映是否支持 AppleScript。
    """
    if not IS_MACOS:
        return None

    script = f'''
    tell application "JianyingPro"
        {command}
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception:
        return None


def jianying_supports_applescript() -> bool:
    """
    检测剪映是否支持 AppleScript 控制。
    """
    result = try_applescript_control("name")
    return result is not None


# =============================================================================
# 平台适配辅助函数
# =============================================================================

def get_platform_controller():
    """
    根据当前平台返回合适的控制器。

    Windows: 返回 JianyingController（使用 uiautomation）
    macOS: 返回 MacOSExportGuide（手动导出引导）
    """
    if IS_WINDOWS:
        from ..vendor.pyJianYingDraft.jianying_controller import JianyingController
        return JianyingController()
    elif IS_MACOS:
        return MacOSExportGuide()
    else:
        raise NotImplementedError(f"不支持的平台: {sys.platform}")


def get_screen_recorder():
    """
    根据当前平台返回屏幕录制器。

    Windows: 使用 ProGuiRecorder
    macOS: 使用 MacOSScreenRecorder
    """
    if IS_WINDOWS:
        # Windows 使用现有的 tkinter 录制器
        from tools.recording.recorder import ProGuiRecorder
        return ProGuiRecorder
    elif IS_MACOS:
        return MacOSScreenRecorder
    else:
        raise NotImplementedError(f"不支持的平台: {sys.platform}")


# =============================================================================
# 导出为空时的占位实现
# =============================================================================

class NoOpController:
    """
    空操作控制器，用于不支持的平台。
    当调用时会提示用户手动操作。
    """

    def __init__(self):
        self.is_macos = IS_MACOS
        self.is_windows = IS_WINDOWS

    def export_draft(self, draft_name: str, output_path: Optional[str] = None, **kwargs):
        """
        导出草稿（macOS 上提示手动导出）。
        """
        guide = MacOSExportGuide()
        instructions = guide.get_export_instructions(draft_name)

        print("=" * 50)
        print("⚠️  macOS 不支持自动导出")
        print("=" * 50)
        print(f"\n📂 草稿位置: {instructions['draft_path'] or '未知'}")
        print("\n📝 手动导出步骤:")
        for step in instructions["manual_steps"]:
            print(f"   {step}")
        print()

        if instructions["draft_path"]:
            print("💡 提示：可以在 Finder 中定位草稿文件夹")
            guide.open_in_finder(draft_name)

        raise NotImplementedError(
            "macOS 不支持自动导出功能。"
            "请手动在剪映中打开项目并导出。"
        )


# 兼容性别名
PlatformController = NoOpController if IS_MACOS else None
