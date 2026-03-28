# -*- coding: utf-8 -*-
import os
import sys
import time
import shutil
import argparse
import traceback
import ctypes
import psutil
import subprocess
import winreg

# ========== 1. 环境与依赖修复 (打包关键) ==========
def _init_frozen_env():
    """修复 PyInstaller 打包后的环境问题"""
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
        try:
            import comtypes.client
            _ = comtypes.client.CreateObject
        except ImportError: pass
        if hasattr(sys, '_MEIPASS'):
            os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')

_init_frozen_env()

import uiautomation as uia

# ========== 2. 核心辅助类 ==========

def dprint(msg):
    print(f"[*] {msg}")

class ControlFinder:
    """控件查找逻辑 (移植自 pyJianYingDraft)"""
    
    @staticmethod
    def desc_matcher(target_desc: str, exact: bool = False):
        """根据 LegacyIAccessible.Description (ID:30159) 查找"""
        target_desc = target_desc.lower()
        def matcher(control: uia.Control, depth: int) -> bool:
            try:
                # 30159 = UIA_FullDescriptionPropertyId
                full_desc = control.GetPropertyValue(30159)
                if not full_desc: return False
                full_desc = full_desc.lower()
                return (target_desc == full_desc) if exact else (target_desc in full_desc)
            except:
                return False
        return matcher

    @staticmethod
    def class_matcher(class_name: str, exact: bool = False):
        """根据 ClassName 查找"""
        class_name = class_name.lower()
        def matcher(control: uia.Control, depth: int) -> bool:
            try:
                curr = control.ClassName.lower()
                return (class_name == curr) if exact else (class_name in curr)
            except:
                return False
        return matcher

# ========== 3. 导出控制器 ==========

class Exporter:
    def __init__(self):
        self.window = None
        self._setup_dpi()
        self.connect()

    def _setup_dpi(self):
        """强制开启高 DPI 感知"""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            dprint("DPI: 系统级感知已开启")
        except:
            ctypes.windll.user32.SetProcessDPIAware()
            dprint("DPI: 基础感知已开启")

    def _find_jianying_path(self):
        """通过注册表或常用路径查找剪映执行文件"""
        # 1. 尝试从注册表查找卸载项
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    subkey_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        try:
                            name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                            if "剪映专业版" in name:
                                ico = winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                                apps_dir = os.path.dirname(ico)
                                # 优先尝试根目录的入口程序
                                main_exe = os.path.join(apps_dir, "JianyingPro.exe")
                                if os.path.exists(main_exe):
                                    return main_exe
                        except: continue
        except: pass

        # 2. 常用路径兜底
        user_profile = os.environ.get('USERPROFILE')
        paths = [
            os.path.join(user_profile, r"AppData\Local\JianyingPro\Apps\JianyingPro.exe"),
            r"C:\Users\Administrator\AppData\Local\JianyingPro\Apps\JianyingPro.exe"
        ]
        for p in paths:
            if os.path.exists(p): return p
            
        return None

    def connect(self, retry=True):
        """连接或唤醒剪映窗口"""
        # 1. 查找窗口
        self.window = uia.WindowControl(searchDepth=1, Name='剪映专业版')
        if not self.window.Exists(0):
            # 尝试通过导出窗口定位
            export_win = uia.WindowControl(searchDepth=1, Name='导出')
            if export_win.Exists(0):
                self.window = export_win
            else:
                if retry:
                    dprint("未找到【剪映专业版】，尝试启动程序...")
                    exe_path = self._find_jianying_path()
                    if exe_path:
                        dprint(f"启动: {exe_path}")
                        subprocess.Popen(exe_path)
                        # 等待程序启动完成
                        for _ in range(30):
                            time.sleep(2)
                            if uia.WindowControl(searchDepth=1, Name='剪映专业版').Exists(0):
                                dprint("程序已启动。")
                                return self.connect(retry=False)
                    raise Exception("无法自动启动【剪映专业版】，请手动启动后重试。")
                else:
                    raise Exception("未找到【剪映专业版】窗口，请确保它已启动。")
        
        # 2. 激活窗口
        try:
            if self.window.Exists(0):
                self.window.SetActive()
                self.window.SetTopmost(True) # 临时置顶确保不被遮挡
                time.sleep(0.2)
                self.window.SetTopmost(False)
        except Exception as e:
            dprint(f"窗口激活警告: {e}")

    def dismiss_blocking_dialogs(self):
        """尝试关闭可能阻挡界面的弹窗 (如环境检测、媒体丢失、版本更新等)"""
        dialogs = [
            {"Name": "环境检测", "CloseBtn": "确定"},
            {"Name": "链接媒体", "CloseBtn": "取消"},
            {"Name": "提示", "CloseBtn": "确定"},
            {"Name": "更新", "CloseBtn": "以后再说"}
        ]
        for dlg in dialogs:
            try:
                # 检查是否存在名为该名称的窗口
                win = uia.WindowControl(searchDepth=1, Name=dlg["Name"])
                if win.Exists(0):
                    dprint(f"检测到干扰弹窗【{dlg['Name']}】，正在尝试关闭...")
                    # 尝试定位按钮 (可能是 Button 或 Text 类型)
                    close_btn = win.ButtonControl(Name=dlg["CloseBtn"])
                    if not close_btn.Exists(0):
                        close_btn = win.TextControl(Name=dlg["CloseBtn"])
                    
                    if close_btn.Exists(0):
                        close_btn.Click(simulateMove=False)
                    else:
                        win.SendKeys('{Esc}')
                    time.sleep(1)
            except: pass

    def is_home_page(self):
        return "HomePage" in self.window.ClassName

    def is_edit_page(self):
        return "MainWindow" in self.window.ClassName

    def switch_to_home(self):
        """从编辑页返回首页"""
        dprint("正在切换回首页...")
        if self.is_home_page():
            dprint("已在首页.")
            return

        # 查找左上角关闭/返回按钮
        # 策略：找 TitleBarButton 组中的第4个 (Index 3)，或者是特定的 Description
        # 在 pyJianYingDraft 中是 ClassName="TitleBarButton", foundIndex=3
        close_btn = self.window.GroupControl(searchDepth=1, ClassName="TitleBarButton", foundIndex=3)
        if close_btn.Exists(1):
            close_btn.Click(simulateMove=False)
        else:
            # 备选：按 ESC 尝试，或找 Name="关闭"
            self.window.SendKeys('{Esc}')
        
        time.sleep(2)
        self.connect() # 重新绑定
        if not self.is_home_page():
            raise Exception("无法返回首页，请手动检查界面状态。")

    def open_draft(self, draft_name):
        """在首页查找并打开草稿"""
        # 1. 自动处理首页干扰弹窗
        self.dismiss_blocking_dialogs()
        
        dprint(f"正在查找草稿: {draft_name}...")
        if not self.is_home_page():
            self.switch_to_home()

        # 使用 Description 查找草稿标题
        target_desc = f"HomePageDraftTitle:{draft_name}"
        
        # 2. 增强查找循环
        draft_card = None
        dprint("开始进入草稿查找轮询...")
        for attempt in range(12): # 延长到 24 秒等待首页渲染
            # 策略 A: 精确 Description 匹配
            draft_text = self.window.TextControl(searchDepth=6, Compare=ControlFinder.desc_matcher(target_desc, exact=True))
            if draft_text.Exists(0):
                draft_card = draft_text.GetParentControl()
                dprint(f"✅ 匹配成功 (Desc): {draft_name}")
                break
            
            # 策略 B: Name 模糊匹配
            draft_text = self.window.TextControl(searchDepth=6, Name=draft_name)
            if draft_text.Exists(0):
                draft_card = draft_text.GetParentControl()
                dprint(f"✅ 匹配成功 (Name): {draft_name}")
                break
                
            # 策略 C: 部分匹配 (包含)
            def partial_matcher(control, depth):
                try: return draft_name in control.Name
                except: return False
            
            draft_text = self.window.TextControl(searchDepth=6, Compare=partial_matcher)
            if draft_text.Exists(0):
                draft_card = draft_text.GetParentControl()
                dprint(f"✅ 匹配成功 (模糊): {draft_text.Name}")
                break
            
            time.sleep(2)
            if attempt == 5:
                # 尝试点击一下首页空白处，激活列表滚动
                dprint("尝试刷新首页状态...")
                self.window.Click(ratioX=0.5, ratioY=0.5, simulateMove=False)

        if not draft_card:
             # 打印首页前 10 个文本块帮助调试
             try:
                 dprint("未找到草稿，首页可见文本如下:")
                 all_texts = [child.Name for child in self.window.GetChildren() if child.ControlType == uia.ControlType.TextControl][:10]
                 dprint(f"DEBUG: {all_texts}")
             except: pass
             raise Exception(f"未找到名为【{draft_name}】的草稿。")

        # 点击草稿卡片
        dprint(f"正在打开草稿...")
        # 剪映首页草稿通常在点击后会有短暂的“正在打开”状态
        draft_card.Click(simulateMove=False)
        
        # 等待加载编辑页 (延长到 60s，并增加异常容错)
        dprint("正在加载编辑器 (可能需要较长时间)...")
        for i in range(60):
            time.sleep(1)
            try:
                # 在窗口切换过程中，可能会有短暂的窗口丢失，忽略连接错误
                self.connect(retry=False) 
                if self.is_edit_page():
                    dprint(f"成功进入编辑页 (耗时 {i+1}s)。")
                    # 额外等待渲染完成
                    time.sleep(3)
                    return
            except:
                # 忽略加载过程中的连接失败，继续轮询
                continue
        raise Exception("打开草稿超时，未能进入编辑界面。请确认是否手动干预或程序卡死。")

    def export(self, output_path, draft_name, resolution="1080P", framerate="30fps"):
        """执行导出流程"""
        dprint("=== 开始导出流程 ===")
        
        if not self.is_edit_page():
            raise Exception("当前不在编辑页，无法导出。")

        # 2. 点击顶部【导出】按钮
        export_btn = self.window.TextControl(searchDepth=5, Compare=ControlFinder.desc_matcher("MainWindowTitleBarExportBtn"))
        if not export_btn.Exists(1):
            export_btn = self.window.TextControl(searchDepth=5, Name="导出")
        
        if not export_btn.Exists(0):
            raise Exception("找不到【导出】按钮。")
            
        export_btn.Click(simulateMove=False)
        time.sleep(2) 

        # 3. 定位导出弹窗并抓取导出路径
        self.connect(retry=False)
        real_export_file = None
        
        try:
            # 参考源代码逻辑：通过 ExportPath 抓取真实导出位置
            export_path_sib = self.window.TextControl(searchDepth=8, Compare=ControlFinder.desc_matcher("ExportPath"))
            if export_path_sib.Exists(2):
                # 兄弟节点往往包含真实的绝对路径文本
                path_ctrl = export_path_sib.GetSiblingControl(lambda ctrl: True)
                if path_ctrl:
                    real_export_file = path_ctrl.GetPropertyValue(30159) # 抓取 FullDescription
                    dprint(f"检测到剪映真实导出位置: {real_export_file}")
        except Exception as e:
            dprint(f"路径抓取失败 (尝试保底): {e}")

        # 4. 设置分辨率 (参考源代码逻辑)
        if resolution:
            try:
                res_map = {"480P": "480", "720P": "720", "1080P": "1080", "2K": "2K", "4K": "4K"}
                target_val = res_map.get(resolution, resolution)
                
                # 点击分辨率下拉框
                res_btn = self.window.TextControl(searchDepth=10, Compare=ControlFinder.desc_matcher("ExportSharpnessInput"))
                if res_btn.Exists(1):
                    res_btn.Click(simulateMove=False)
                    time.sleep(0.5)
                    # 在弹出的列表中查找目标分辨率
                    res_item = self.window.TextControl(searchDepth=5, Name=target_val)
                    if not res_item.Exists(0.5):
                        # 尝试通过 FullDescription 查找
                        res_item = self.window.TextControl(searchDepth=5, Compare=ControlFinder.desc_matcher(target_val))
                    
                    if res_item.Exists(0.5):
                        res_item.Click(simulateMove=False)
                        dprint(f"已设置分辨率为: {resolution}")
                        time.sleep(0.5)
            except Exception as e:
                dprint(f"分辨率设置失败: {e}")

        # 5. 点击【导出】确认按钮
        confirm_btn = self.window.TextControl(searchDepth=8, Compare=ControlFinder.desc_matcher("ExportOkBtn"))
        if not confirm_btn.Exists(0):
            confirm_btn = self.window.ButtonControl(Name="导出")
        
        if not confirm_btn.Exists(1):
             raise Exception("无法在导出弹窗中找到确认按钮。")

        dprint("确认导出...")
        confirm_btn.Click(simulateMove=False)

        # 6. 等待导出完成
        dprint("正在导出中，请勿操作剪映...")
        start_time = time.time()
        completed = False
        
        while time.time() - start_time < 900: # 最长 15 分钟
            close_btn = self.window.TextControl(searchDepth=8, Compare=ControlFinder.desc_matcher("ExportSucceedCloseBtn"))
            if close_btn.Exists(0):
                dprint("✅ 导出完成检测成功！")
                close_btn.Click(simulateMove=False)
                completed = True
                break
            time.sleep(2)

        if not completed:
            raise Exception("导出超时或未检测到完成状态。")

        # 7. 文件处理 (剪映默认导出路径 -> 目标路径)
        try:
            dprint("尝试自动搬运视频文件...")
            # 剪映导出的文件名默认就是草稿名
            # 如果导出的名字太长会被截断，我们取前几个字
            safe_name = "".join([c for c in draft_name if c not in r'\/:*?"<>|']).strip()
            
            # 查找可能输出的目录
            # 策略：从导出窗口抓取的路径，或者常见的视频/桌面路径
            possible_dirs = []
            
            # A. 尝试从 UI 抓取保存路径
            try:
                # 在确认按钮点击前，我们应该已经保存了路径。
                # 如果没保存，现在窗口可能已经关了。我们尝试从刚才 Log 记录中恢复，
                # 或者遍历几个默认位置。
                user_video_dir = os.path.join(os.environ['USERPROFILE'], 'Videos')
                user_desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
                possible_dirs.extend([user_video_dir, user_desktop, os.path.join(user_video_dir, 'Jianying')])
            except: pass
            
            # B. 寻找最近生成的符合名字的文件
            found_file = None
            
            # 如果刚才抓到了真实路径且文件存在，优先用它
            if real_export_file and os.path.exists(real_export_file):
                found_file = real_export_file
            else:
                dprint("尝试扫描保底目录...")
                newest_time = 0
                for d in set(possible_dirs):
                    if not os.path.exists(d): continue
                    for f in os.listdir(d):
                        if f.lower().endswith(('.mp4', '.mov')) and (safe_name in f or f in safe_name):
                            f_path = os.path.join(d, f)
                            mtime = os.path.getmtime(f_path)
                            if mtime > newest_time and (time.time() - mtime < 300):
                                newest_time = mtime
                                found_file = f_path
            
            if found_file:
                dprint(f"找到导出的原始文件: {found_file}")
                # 确保目标文件夹存在
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                # 执行移动 (如果目标已存在则覆盖)
                if os.path.exists(output_path): os.remove(output_path)
                shutil.move(found_file, output_path)
                dprint(f"🎉 成功搬运至目标位置: {output_path}")
                return True
            else:
                dprint("⚠️ 未能在默认目录找到匹配的视频文件，可能路径不匹配。")
        except Exception as e:
            dprint(f"文件搬运逻辑出错: {e}")

def run(draft_name, output_path):
    dprint(f"任务: 导出【{draft_name}】 -> {output_path}")
    exporter = Exporter()
    
    # 1. 确保在首页
    if exporter.is_edit_page():
        dprint("检测到在编辑页，将尝试先导出当前草稿（如果名字匹配）或切回首页")
        # 这里简单处理：切回首页重来，确保状态一致
        exporter.switch_to_home()
    
    # 2. 打开草稿
    exporter.open_draft(draft_name)
    
    # 3. 导出
    # 注意：此脚本目前仅触发导出点击和等待，没有修改导出路径。
    # 剪映会导出到它上次记住的路径。
    # 为了完整性，我们需要在弹窗里读取路径，或者用户接受它导出到默认位置，然后我们去搜刚生成的文件。
    exporter.export(output_path, draft_name)
    
    # 由于我们没改路径，这里简单提示
    dprint(f"⚠️ 注意: 视频已导出到剪映默认目录，请在剪映提示的文件夹中查找。")
    # 如果通过 Exporter 能读到路径最好，这留给下一阶段优化。

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="剪映自动化导出工具")
    parser.add_argument("draft_name", help="草稿名称")
    parser.add_argument("output_path", help="目标文件路径")
    
    args = parser.parse_args()
    
    try:
        run(args.draft_name, args.output_path)
    except Exception as e:
        dprint(f"❌ 错误: {str(e)}")
        dprint("-" * 40)
        dprint("💡 建议：如果脚本无法定位窗口或草稿，请尝试【手动重启剪映程序】后再运行。")
        dprint("-" * 40)
        dprint(traceback.format_exc())
        input("按回车键退出...")
        sys.exit(1)
