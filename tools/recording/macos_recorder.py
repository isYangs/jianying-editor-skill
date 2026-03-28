#!/usr/bin/env python3
"""
macOS 屏幕录制工具

使用 ffmpeg + avfoundation 实现屏幕录制，支持：
- 全屏录制
- 音频录制
- 事件追踪（鼠标点击、键盘按键）
- 自动导入剪映生成智能缩放草稿

依赖：
- ffmpeg (需安装: brew install ffmpeg)
- pynput (pip install pynput)
"""

import os
import sys
import json
import time
import subprocess
import threading
from typing import Optional, List, Dict, Any

# 路径设置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

try:
    from pynput import mouse, keyboard
except ImportError:
    print("⚠️ pynput 未安装，事件追踪将不可用")
    print("   安装命令: pip install pynput")
    mouse = None
    keyboard = None

# ============================================================================
# macOS 平台特定配置
# ============================================================================

# 检查 ffmpeg 是否可用
def check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False

FFMPEG_AVAILABLE = check_ffmpeg()

# macOS DPI 处理（Retina 支持）
try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog
except ImportError:
    print("⚠️ tkinter 不可用，GUI 将无法运行")
    tk = None


class MacOSScreenRecorderGUI:
    """
    macOS 屏幕录制器 GUI
    """

    def __init__(self, output_dir: Optional[str] = None):
        if tk is None:
            raise RuntimeError("tkinter 不可用，请安装 Python tkinter 包")

        self.output_dir = output_dir or os.getcwd()
        os.makedirs(self.output_dir, exist_ok=True)

        self.is_recording = False
        self.start_time = 0
        self.events: List[Dict[str, Any]] = []
        self.output_path: Optional[str] = None
        self.events_path: Optional[str] = None

        # ffmpeg 进程
        self.process: Optional[subprocess.Popen] = None

        # 事件监听器
        self._mouse_listener = None
        self._keyboard_listener = None

        # 屏幕尺寸
        self.screen_width = 1920
        self.screen_height = 1080

        # 音频启用
        self.audio_enabled = False

        # UI
        self.root: Optional[tk.Tk] = None
        self.status_label: Optional[tk.Label] = None
        self.start_btn: Optional[tk.Button] = None
        self.mini_frame: Optional[tk.Frame] = None

        self._setup_ui()

    def _setup_ui(self):
        """设置 UI"""
        self.root = tk.Tk()
        self.root.title("剪映录屏助手 (macOS)")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#2c3e50")

        # 主框架
        self.main_frame = tk.Frame(self.root, bg="#2c3e50")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题
        title_label = tk.Label(
            self.main_frame,
            text="🎬 macOS 屏幕录制",
            fg="#ecf0f1", bg="#2c3e50",
            font=("Arial", 14, "bold")
        )
        title_label.pack(pady=10)

        # ffmpeg 状态
        ffmpeg_status = "✅ ffmpeg 已安装" if FFMPEG_AVAILABLE else "⚠️ ffmpeg 未安装"
        ffmpeg_color = "#2ecc71" if FFMPEG_AVAILABLE else "#e74c3c"
        ffmpeg_label = tk.Label(
            self.main_frame,
            text=ffmpeg_status,
            fg=ffmpeg_color, bg="#2c3e50",
            font=("Arial", 10)
        )
        ffmpeg_label.pack(pady=5)

        # 状态标签
        self.status_label = tk.Label(
            self.main_frame,
            text="准备就绪",
            fg="#ecf0f1", bg="#2c3e50",
            font=("Arial", 12, "bold")
        )
        self.status_label.pack(pady=10)

        # 保存路径
        path_label = tk.Label(
            self.main_frame,
            text=f"保存至: {self.output_dir}",
            fg="#bdc3c7", bg="#2c3e50",
            font=("Arial", 8)
        )
        path_label.pack(pady=5)

        # 开始按钮
        self.start_btn = tk.Button(
            self.main_frame,
            text="🎬 开始录制",
            command=self.start_countdown,
            bg="#2ecc71", fg="white",
            font=("Arial", 12, "bold"),
            width=20, height=2,
            state="normal" if FFMPEG_AVAILABLE else "disabled"
        )
        self.start_btn.pack(pady=10)

        # 提示信息
        if not FFMPEG_AVAILABLE:
            hint_label = tk.Label(
                self.main_frame,
                text="请先安装 ffmpeg:\nbrew install ffmpeg",
                fg="#e74c3c", bg="#2c3e50",
                font=("Arial", 9)
            )
            hint_label.pack(pady=5)
        else:
            hint_label = tk.Label(
                self.main_frame,
                text="💡 点击录制按钮开始，\n点击红色圆点停止",
                fg="#bdc3c7", bg="#2c3e50",
                font=("Arial", 9)
            )
            hint_label.pack(pady=5)

        # 迷你录制框架 (红色圆点)
        self.mini_frame = tk.Frame(self.root, bg="#e74c3c", cursor="hand2")
        self.record_indicator = tk.Label(
            self.mini_frame,
            text="●",
            fg="white", bg="#e74c3c",
            font=("Arial", 20)
        )
        self.record_indicator.pack(expand=True)

        # 绑定停止事件
        self.mini_frame.bind("<Button-1>", lambda e: self.stop_recording())
        self.record_indicator.bind("<Button-1>", lambda e: self.stop_recording())

        # 允许拖拽
        self.mini_frame.bind("<B1-Motion>", self.drag_window)
        self.record_indicator.bind("<B1-Motion>", self.drag_window)

        # 初始隐藏迷你界面
        self.mini_frame.pack_forget()

        # 窗口关闭处理
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def drag_window(self, event):
        """拖拽窗口"""
        x = self.root.winfo_x() + event.x - 25
        y = self.root.winfo_y() + event.y - 25
        self.root.geometry(f"+{x}+{y}")

    def on_close(self):
        """窗口关闭处理"""
        if self.is_recording:
            self.stop_recording()
        self.root.destroy()

    def start_countdown(self):
        """开始倒计时"""
        if not FFMPEG_AVAILABLE:
            messagebox.showerror("错误", "ffmpeg 未安装，无法录制")
            return

        self.start_btn.config(state="disabled")

        for i in range(3, 0, -1):
            self.status_label.config(text=f"即将开始 ({i})...", fg="#f1c40f")
            self.root.update()
            time.sleep(1)

        self.start_actual_recording()

    def start_actual_recording(self):
        """实际开始录制"""
        # 生成文件名
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.output_path = os.path.join(self.output_dir, f"recording_{timestamp}.mp4")
        self.events_path = self.output_path.replace(".mp4", "_events.json")

        self.is_recording = True
        self.start_time = time.time()
        self.events = []

        # 切换到迷你界面
        self.main_frame.pack_forget()
        self.mini_frame.pack(fill=tk.BOTH, expand=True)
        self.root.overrideredirect(True)
        self.root.geometry("50x50")

        # 启动事件监听
        if mouse and keyboard:
            self._mouse_listener = mouse.Listener(on_click=self.on_click, on_move=self.on_move)
            self._keyboard_listener = keyboard.Listener(on_press=self.on_keypress)
            self._mouse_listener.start()
            self._keyboard_listener.start()

        # 启动 ffmpeg 录制
        threading.Thread(target=self.run_ffmpeg, daemon=True).start()

    def on_click(self, x: int, y: int, button, pressed: bool):
        """鼠标点击事件"""
        if self.is_recording and pressed:
            rel_time = time.time() - self.start_time
            self.events.append({
                "type": "click",
                "time": round(rel_time, 3),
                "x": round(x / self.screen_width, 3),
                "y": round(y / self.screen_height, 3)
            })

    def on_move(self, x: int, y: int):
        """鼠标移动事件（节流）"""
        if not self.is_recording:
            return

        now = time.time()
        if not hasattr(self, '_last_move_time'):
            self._last_move_time = 0
            self._last_move_pos = (x, y)

        if (now - self._last_move_time) > 0.1:
            last_x, last_y = self._last_move_pos
            if (x - last_x)**2 + (y - last_y)**2 > 25:
                rel_time = now - self.start_time
                self.events.append({
                    "type": "move",
                    "time": round(rel_time, 3),
                    "x": round(x / self.screen_width, 4),
                    "y": round(y / self.screen_height, 4)
                })
                self._last_move_time = now
                self._last_move_pos = (x, y)

    def on_keypress(self, key):
        """键盘事件"""
        if self.is_recording:
            rel_time = time.time() - self.start_time
            try:
                key_name = key.char if hasattr(key, 'char') else str(key)
            except Exception:
                key_name = str(key)
            self.events.append({
                "type": "keypress",
                "time": round(rel_time, 3),
                "key": key_name
            })

    def run_ffmpeg(self):
        """运行 ffmpeg 录制"""
        cmd = [
            "ffmpeg", "-y",
            "-f", "avfoundation",
            "-framerate", "30",
            "-i", "0",  # 第一个屏幕
        ]

        if self.audio_enabled:
            cmd.extend(["-f", "avfoundation", "-audio_device_index", "1"])

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
        ])

        if not self.audio_enabled:
            cmd.extend(["-an"])

        cmd.append(self.output_path)

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        log_file = os.path.join(self.output_dir, "ffmpeg_log.txt")

        try:
            with open(log_file, "w", encoding="utf-8") as f:
                self.process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    env=env
                )
                self.process.wait()
        except Exception as e:
            print(f"⚠️ ffmpeg 异常: {e}")

    def stop_recording(self):
        """停止录制"""
        if not self.is_recording:
            return

        self.is_recording = False

        # 停止事件监听
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()

        # 停止 ffmpeg
        if self.process:
            try:
                if self.process.poll() is None:
                    time.sleep(0.5)
                    self.process.stdin.write(b"q")
                    self.process.stdin.flush()
                    self.process.wait(timeout=5)
            except Exception as e:
                print(f"⚠️ 停止 ffmpeg 异常: {e}")
                try:
                    self.process.kill()
                except:
                    pass

        # 保存事件数据
        if self.events and self.events_path:
            try:
                with open(self.events_path, "w", encoding="utf-8") as f:
                    json.dump(self.events, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"⚠️ 事件保存失败: {e}")

        # 恢复 UI
        self.root.overrideredirect(False)
        self.mini_frame.pack_forget()
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        self.start_btn.config(state="normal")

        # 检查输出
        if self.output_path and os.path.exists(self.output_path):
            size = os.path.getsize(self.output_path)
            if size > 1000:
                self.status_label.config(text="录制成功！", fg="#2ecc71")
                print(f"✅ 录制成功: {self.output_path}")
                self.show_post_dialog()
            else:
                self.status_label.config(text="录制失败", fg="#e74c3c")
                messagebox.showerror("错误", "录制文件无效")
        else:
            self.status_label.config(text="录制失败", fg="#e74c3c")
            messagebox.showerror("错误", "未能生成视频文件")

    def show_post_dialog(self):
        """显示录制后操作对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("录制完成")
        dialog.geometry("400x250")
        dialog.configure(bg="#2c3e50")
        dialog.attributes("-topmost", True)

        # 居中
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        dialog.geometry(f"+{x}+{y}")

        lbl = tk.Label(
            dialog,
            text="✅ 视频已保存！\n下一步做什么？",
            fg="#ecf0f1", bg="#2c3e50",
            font=("Arial", 12, "bold")
        )
        lbl.pack(pady=20)

        btn_frame = tk.Frame(dialog, bg="#2c3e50")
        btn_frame.pack(fill=tk.BOTH, expand=True)

        def open_folder():
            subprocess.run(["open", "-R", self.output_path])
            dialog.destroy()

        def create_draft():
            name = simpledialog.askstring(
                "创建草稿",
                "请输入剪映项目名称:",
                initialvalue="录屏项目",
                parent=dialog
            )
            if not name:
                return
            dialog.destroy()
            self.create_smart_draft(name)

        tk.Button(
            btn_frame,
            text="✨ 自动生成智能草稿",
            command=create_draft,
            bg="#3498db", fg="white",
            font=("Arial", 10), width=20
        ).pack(pady=5)

        tk.Button(
            btn_frame,
            text="📂 打开文件位置",
            command=open_folder,
            bg="#95a5a6", fg="white",
            font=("Arial", 10), width=20
        ).pack(pady=5)

        tk.Button(
            btn_frame,
            text="❌ 关闭",
            command=dialog.destroy,
            bg="#e74c3c", fg="white",
            font=("Arial", 10), width=20
        ).pack(pady=5)

    def create_smart_draft(self, project_name: str):
        """创建智能草稿"""
        try:
            wrapper_path = os.path.join(SKILL_ROOT, "scripts", "jy_wrapper.py")

            if not os.path.exists(wrapper_path):
                messagebox.showerror("错误", f"找不到 jy_wrapper.py:\n{wrapper_path}")
                return

            cmd = [
                sys.executable, wrapper_path,
                "apply-zoom",
                "--name", project_name,
                "--video", self.output_path,
                "--json", self.events_path,
                "--scale", "150"
            ]

            self.status_label.config(text="正在生成草稿...", fg="#3498db")
            self.root.update()

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env
            )

            if result.returncode == 0:
                self.status_label.config(text="草稿创建成功！", fg="#2ecc71")
                messagebox.showinfo("成功", f"剪映草稿 '{project_name}' 已创建！\n\n请打开剪映查看。")
            else:
                self.status_label.config(text="创建失败", fg="#e74c3c")
                messagebox.showerror("失败", f"创建出错:\n{result.stderr}")

        except Exception as e:
            messagebox.showerror("异常", str(e))

    def run(self):
        """运行 GUI"""
        self.root.mainloop()


def main():
    """入口函数"""
    if not FFMPEG_AVAILABLE:
        print("⚠️ ffmpeg 未安装")
        print("请运行: brew install ffmpeg")
        print()

    if len(sys.argv) > 1:
        output_dir = sys.argv[1]
    else:
        output_dir = os.getcwd()

    if tk:
        try:
            recorder = MacOSScreenRecorderGUI(output_dir=output_dir)
            recorder.run()
        except RuntimeError as e:
            print(f"错误: {e}")
    else:
        # 无 GUI 模式
        print("无 GUI 模式可用，请设置 DISPLAY 环境变量或安装 tkinter")


if __name__ == "__main__":
    main()
