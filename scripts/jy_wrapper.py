"""
JianYing Editor Skill - High Level Wrapper (Mixin Based)
旨在解决路径依赖、API 复杂度及严格校验问题。
"""

import os
import sys
import uuid
from typing import Union, Optional

# 环境初始化
from utils.env_setup import setup_env
setup_env()

# 导入工具函数
from utils.constants import SYNONYMS
from utils.formatters import (
    resolve_enum_with_synonyms, format_srt_time, safe_tim,
    get_duration_ffprobe_cached, get_default_drafts_root, get_all_drafts
)

# 导入基类与 Mixins
from core.project_base import JyProjectBase
from core.media_ops import MediaOpsMixin
from core.text_ops import TextOpsMixin
from core.vfx_ops import VfxOpsMixin
from core.mocking_ops import MockingOpsMixin

# macOS 支持模块
from core.macos_ops import (
    IS_MACOS, IS_WINDOWS,
    MacOSScreenRecorder, MacOSExportGuide,
    get_jianying_drafts_root_macos, get_platform_controller
)

try:
    import pyJianYingDraft as draft
    from pyJianYingDraft import VideoSceneEffectType, TransitionType
except ImportError:
    draft = None

# 平台特定的草稿根目录
def _get_drafts_root_with_macos_fallback():
    """获取草稿根目录，macOS 上自动使用正确的路径"""
    if IS_MACOS:
        macos_root = get_jianying_drafts_root_macos()
        if macos_root:
            return macos_root
        # 如果没找到，返回一个合理的默认值
        return os.path.expanduser("~/Library/Application Support/JianyingPro/User Data/Projects/com.lveditor.draft")
    return get_default_drafts_root()

class JyProject(JyProjectBase, MediaOpsMixin, TextOpsMixin, VfxOpsMixin, MockingOpsMixin):
    """
    高层封装工程类。通过多重继承 Mixins 实现功能解耦。
    """
    def __init__(self, *args, **kwargs):
        # macOS 上自动使用正确的草稿目录
        if IS_MACOS and 'drafts_root' not in kwargs:
            kwargs['drafts_root'] = _get_drafts_root_with_macos_fallback()
        super().__init__(*args, **kwargs)

    def _resolve_enum(self, enum_cls, name: str):
        return resolve_enum_with_synonyms(enum_cls, name, SYNONYMS)

    def add_clip(self, media_path: str, source_start: Union[str, int], duration: Union[str, int],
                 target_start: Union[str, int] = None, track_name: str = "VideoTrack", **kwargs):
        """高层剪辑接口：从媒体指定位置裁剪指定长度，并放入轨道。"""
        if target_start is None:
            target_start = self.get_track_duration(track_name)
        return self.add_media_safe(media_path, target_start, duration, track_name, source_start=source_start, **kwargs)

    def save(self):
        """保存并执行质检报告。"""
        self.script.save()
        self._patch_cloud_material_ids()
        self._force_activate_adjustments()

        draft_path = os.path.join(self.root, self.name)
        if os.path.exists(draft_path):
            os.utime(draft_path, None)

        # macOS 提示信息
        if IS_MACOS:
            print(f"✅ Project '{self.name}' saved (macOS mode).")
            print(f"📂 Draft location: {draft_path}")
            print("💡 Please open Jianying Pro to edit and export this draft.")
        else:
            print(f"✅ Project '{self.name}' saved and patched.")

        return {"status": "SUCCESS", "draft_path": draft_path, "platform": "macos" if IS_MACOS else "windows"}

    def export_video(self, output_path: str, resolution: str = "1080", fps: str = "30",
                   remote_host: str = None) -> dict:
        """
        导出视频。

        Args:
            output_path: 输出 MP4 路径
            resolution: 分辨率 (480/720/1080/2K/4K/8K)
            fps: 帧率 (24/25/30/50/60)
            remote_host: 远程 Windows Export Agent 地址 (如 "http://192.168.1.100:8765")
                       - 若设置，则使用远程 Agent 导出
                       - macOS 默认使用此方式（需配置 remote_host）
                       - 不设置则使用本地导出 (Windows)

        macOS 优先使用 remote_host 指定的 Windows Agent 进行导出。
        """
        if IS_MACOS or remote_host:
            # 使用远程 Windows Agent 导出
            guide = MacOSExportGuide()

            if remote_host:
                # 使用指定的远程 Agent
                try:
                    import requests
                    print(f"🔄 正在通过远程 Agent 导出: {remote_host}")

                    # 调用远程导出 API
                    response = requests.post(
                        f"{remote_host}/export",
                        json={
                            "draft_name": self.name,
                            "output_path": output_path,
                            "resolution": resolution,
                            "framerate": fps
                        },
                        timeout=30
                    )

                    if response.status_code == 200:
                        result = response.json()
                        task_id = result.get("task_id")
                        print(f"📋 任务已启动: {task_id}")
                        print(f"🔗 查询状态: {remote_host}/export/{task_id}/status")

                        # 轮询状态
                        import time
                        while True:
                            status_resp = requests.get(
                                f"{remote_host}/export/{task_id}/status",
                                timeout=10
                            )
                            status_data = status_resp.json()
                            status = status_data.get("status")

                            if status == "completed":
                                print(f"✅ 导出完成: {output_path}")
                                return {"status": "success", "output": output_path}
                            elif status == "failed":
                                print(f"❌ 导出失败: {status_data.get('error')}")
                                return {"status": "failed", "error": status_data.get("error")}
                            else:
                                progress = status_data.get("progress", 0)
                                print(f"⏳ 导出中... {progress}%")

                            time.sleep(5)

                    else:
                        raise Exception(f"API 返回错误: {response.status_code}")

                except ImportError:
                    return {"status": "error", "error": "requests 库未安装"}
                except Exception as e:
                    return {"status": "error", "error": str(e)}
            else:
                # 没有指定远程 Agent，显示手动引导
                instructions = guide.get_export_instructions(self.name)
                print("=" * 50)
                print("⚠️  macOS 无法直接自动导出")
                print("=" * 50)
                print(f"\n📂 草稿位置: {instructions['draft_path']}")
                print("\n📝 解决方案:")
                print("   1. 在 Windows 上运行 Export Agent 服务")
                print("   2. 设置 remote_host 参数:")
                print("      project.export_video('out.mp4', remote_host='http://Windows-IP:8765')")
                print()

                guide.open_in_finder(self.name)

                return {
                    "status": "remote_required",
                    "draft_path": instructions["draft_path"],
                    "hint": "需要配置 remote_host 指向 Windows Export Agent"
                }
        else:
            # Windows 本地导出

    @staticmethod
    def get_screen_recorder(output_dir: str = None):
        """获取适合当前平台的屏幕录制器"""
        if IS_MACOS:
            return MacOSScreenRecorder(output_dir=output_dir)
        elif IS_WINDOWS:
            from tools.recording.recorder import ProGuiRecorder
            return ProGuiRecorder(output_dir=output_dir)
        else:
            raise NotImplementedError(f"不支持的平台: {sys.platform}")

    @staticmethod
    def is_macos() -> bool:
        """检查是否运行在 macOS"""
        return IS_MACOS

    @staticmethod
    def is_windows() -> bool:
        """检查是否运行在 Windows"""
        return IS_WINDOWS

# 导出工具函数以便向下兼容
__all__ = ["JyProject", "get_default_drafts_root", "get_all_drafts", "safe_tim", "format_srt_time"]

if __name__ == "__main__":
    # 测试代码
    try:
        project = JyProject("Refactor_Test_Project", overwrite=True)
        print("🚀 Refactored JyProject initialized successfully.")
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
