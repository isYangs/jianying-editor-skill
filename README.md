# jianying-editor v1.0.0

[![ClawHub](https://img.shields.io/badge/ClawHub-jianying--editor-blue)](https://clawhub.ai/skills/jianying-editor)

```bash
clawhub install jianying-editor
```

**剪映 (JianYing) AI 自动化剪辑 Skill。** 通过自然语言告诉 AI 你想做什么视频，它帮你完成从写文案、配音、加字幕、选音乐、上特效到最终导出的整套流程。

## 功能特性

- **素材导入** - 视频、音频、图片一句话丢进时间轴
- **AI 配音** - 输入文案自动生成语音
- **字幕生成** - 根据配音自动拆句、逐句对齐字幕
- **自动配乐** - 本地音乐或剪映云端曲库
- **特效/转场/滤镜** - 按名字搜索剪映自带特效库
- **录屏 + 智能变焦** - 录制屏幕并自动添加缩放和红圈标记
- **网页动效转视频** - HTML/JS/Canvas 动画录屏变视频素材
- **自动导出** - 一键导出 MP4 (1080P~4K)

## 支持环境

| 平台 | 状态 | 说明 |
|:----:|:----:|------|
| Windows | ✅ | 完全支持，包括自动导出 |
| macOS | ✅ | 支持 (导出需通过 Windows Agent) |
| 剪映 5.9 及以下 | ✅ | 自动导出依赖此版本 |

## 安装

### Claude Code (推荐)
```
/plugin marketplace add isYangs/jianying-editor-skill
/plugin install jianying-editor@jianying-editor-skill
```

### 手动安装
```bash
# Clone 到 skills 目录
git clone https://github.com/isYangs/jianying-editor-skill.git ~/.claude/skills/jianying-editor

# 安装 Python 依赖
pip install -r requirements.txt
```

## 快速开始

```python
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
skill_root = next((p for p in [
    os.getenv("JY_SKILL_ROOT"),
    os.path.join(current_dir, ".claude", "skills", "jianying-editor"),
    os.path.join(current_dir, "skills", "jianying-editor"),
] if p and os.path.exists(os.path.join(p, "scripts", "jy_wrapper.py"))), None)

if not skill_root:
    raise ImportError("Could not find jianying-editor skill")

sys.path.insert(0, os.path.join(skill_root, "scripts"))
from jy_wrapper import JyProject

project = JyProject("我的视频")
project.add_text_simple("剪映自动化开启", start_time="1s", duration="3s")
project.save()
```

## macOS 远程导出方案

macOS 可通过远程调用 Windows 上的 Export Agent 实现自动导出：

```
macOS (OpenClaw) ──HTTP──> Windows Export Agent ──> 剪映客户端
```

**Windows 部署 Agent：**
```bash
pip install fastapi uvicorn pyJianYingDraft
python scripts/core/windows_export_agent.py --port 8765
```

## 依赖要求

- Python 3.8+
- ffmpeg (录屏功能必需)
- 剪映专业版 (自动导出需要 5.9 或更低版本)

## 相关链接

- [GitHub](https://github.com/isYangs/jianying-editor-skill)
- [SKILL.md](SKILL.md) - AI 说明书
- [CHANGELOG.md](CHANGELOG.md) - 更新日志


