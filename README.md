# jianying-editor v1.0.0

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

## 安装

复制以下命令发给 AI Agent：

```
帮我安装 jianying-editor skill：
cd <workspace>/skills && git clone https://github.com/isYangs/jianying-editor-skill.git jianying-editor && cd jianying-editor && pip install -r requirements.txt
```

## 依赖要求

- Python 3.8+
- ffmpeg (录屏功能必需)
- 剪映专业版 (自动导出需要 5.9 或更低版本)

## 相关链接

- [GitHub](https://github.com/isYangs/jianying-editor-skill)
- [SKILL.md](SKILL.md) - AI 说明书


