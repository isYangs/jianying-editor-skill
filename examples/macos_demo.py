"""
macOS 演示示例 - 展示剪映 Skill 在 macOS 上的基础用法

此示例展示：
1. 自动探测 macOS 草稿目录
2. 创建和编辑项目
3. 导入素材
4. 添加字幕
5. 手动导出引导
"""

import os
import sys

# 设置 Skill 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
skill_root = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, os.path.join(skill_root, "scripts"))

from jy_wrapper import JyProject

# =============================================================================
# 示例 1: 基础视频剪辑
# =============================================================================

def basic剪辑示例():
    """macOS 上的基础视频剪辑"""
    
    # macOS 会自动使用正确的草稿目录
    project = JyProject("MacOS_Test_Project", overwrite=True)
    
    # 添加视频素材（使用绝对路径）
    video_path = "/Users/your_name/Videos/test.mp4"
    if os.path.exists(video_path):
        project.add_media_safe(video_path, start_time="0s", duration="10s")
    
    # 添加背景音乐
    project.add_cloud_music("阳光旅途", start_time="0s", duration="10s")
    
    # 添加标题
    project.add_text_simple(
        text="macOS 测试标题",
        start_time="1s",
        duration="3s",
        anim_in="打字机"
    )
    
    # 保存
    result = project.save()
    print(f"✅ 项目已保存: {result['draft_path']}")
    
    return result


# =============================================================================
# 示例 2: TTS 配音与字幕
# =============================================================================

def tts配音示例():
    """使用 TTS 生成配音和字幕"""
    
    project = JyProject("TTS_Demo_MacOS")
    
    # 添加视频
    project.add_media_safe("/Users/your_name/Videos/demo.mp4", "0s")
    
    # TTS 配音 + 自动字幕对齐
    project.add_narrated_subtitles(
        text="今天我们来讲解 Python 编程基础。Python 是一门简洁易学的语言。",
        speaker="zh_female_xiaopengyou",
        start_time="2s"
    )
    
    project.save()
    return project


# =============================================================================
# 示例 3: 屏幕录制 (macOS)
# =============================================================================

def 屏幕录制示例():
    """展示 macOS 屏幕录制功能"""
    
    # 获取屏幕录制器
    recorder = JyProject.get_screen_recorder(output_dir="/tmp")
    
    # 检查 ffmpeg 是否可用
    print("🍎 屏幕录制器已准备就绪")
    print("请运行以下命令启动 GUI 录制：")
    print(f"  python {skill_root}/tools/recording/macos_recorder.py")


# =============================================================================
# 示例 4: 导出引导 (macOS)
# =============================================================================

def 导出示例():
    """macOS 导出功能 - 提供手动导出引导"""
    
    project = JyProject("Export_Guide_Demo", overwrite=True)
    project.add_media_safe("/Users/your_name/Videos/test.mp4", "0s")
    project.save()
    
    # macOS 上会提示手动导出
    result = project.export_video(
        output_path="/Users/your_name/Movies/output.mp4",
        resolution="1080",
        fps="30"
    )
    
    print(f"导出状态: {result['status']}")
    if result['status'] == 'manual_required':
        print("请按照上面的步骤手动在剪映中导出")


# =============================================================================
# 主函数
# =============================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("JianYing Editor Skill - macOS 演示")
    print("=" * 50)
    
    # 检查平台
    print(f"\n当前平台: {'macOS' if JyProject.is_macos() else 'Windows'}")
    print(f"JyProject 草稿目录: {JyProject}")
    
    # 运行示例
    print("\n--- 示例 1: 基础剪辑 ---")
    # basic剪辑示例()  # 取消注释以运行
    
    print("\n--- 示例 2: TTS 配音 ---")
    # tts配音示例()  # 取消注释以运行
    
    print("\n--- 示例 3: 屏幕录制 ---")
    屏幕录制示例()
    
    print("\n--- 示例 4: 导出 ---")
    # 导出示例()  # 取消注释以运行
