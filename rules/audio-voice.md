---
name: audio-voice-generative
description: Rules for generating TTS voiceover and sourcing/downloading background music.
metadata:
  tags: tts, voiceover, bgm, audio
---

# Audio & Voice Rules

## 1) TTS (Preferred)

Use `project.add_tts_intelligent(...)` for narration.

```python
seg = project.add_tts_intelligent(
    "你好，我是全自动剪辑助手。",
    speaker="zh_male_huoli",
    start_time="0s",
    track_name="AudioTrack",
)
```

Recommended speakers:

- `zh_male_huoli`
- `zh_female_xiaopengyou`
- `zh_male_xionger_stream_gpu`
- `zh_female_inspirational`

## 2) TTS + Subtitles Sync

Use `project.add_narrated_subtitles(...)` when you need aligned narration and subtitles in one call.

```python
project.add_narrated_subtitles(
    "欢迎来到 AI 剪辑教程。今天我们演示自动旁白与字幕对齐。",
    speaker="zh_female_xiaopengyou",
    start_time="1s",
    track_name="Subtitles",
)
```

## 3) JianYing AI Writer + Manbo Voiceover

Use `project.add_ai_voiceover(...)` when the user wants JianYing to generate the copy and
place synchronized narration and subtitles on the timeline in one operation.

```python
result = project.add_ai_voiceover(
    "写一段关于年轻人存钱困难的30秒口播稿。",
    start_time="0s",
)
```

Defaults:

- JianYing `smart_text_v2` with `deepseek-r1` reasoning
- `ICL_zh_female_manbo_jianying` (`曼波讲故事`)
- real FFmpeg `1.2x` speed conversion
- `100ms` sentence gap
- tracks `AI VoiceOver` and `AI Subtitles`
- no UI fallback

All audio files are generated and validated before the timeline is changed. Compatibility is
verified against JianYing Pro `10.7.0.14095`.

## 4) BGM / SFX Sourcing

Data files:

- `data/jy_cached_audio.csv`: local synced music paths
- `data/cloud_music_library.csv`: cloud music index
- `data/cloud_sound_effects.csv`: cloud sound effects index

Valid APIs in this repo:

- Cloud assets (music/video/sfx): `project.add_cloud_media(query, ...)`
- Explicit cloud music helper: `project.add_cloud_music(query, ...)`
- Local audio file: `project.add_audio_safe(path, ...)`

Examples:

```python
# cloud bgm by id
bgm = project.add_cloud_media("7546546694282676275", start_time="0s", duration="12s", track_name="BGM_Track")
if bgm:
    bgm.volume = 0.6

# cloud sfx by id (also through add_cloud_media)
project.add_cloud_media("7135753343380606242", start_time="5s", duration="2s", track_name="SFX_Track")
```

## 5) Mandatory Mixing Rule

When narration and background music coexist, set BGM volume to `0.6` by default.

## 6) Fallback

If cloud/local assets are unavailable, use royalty-free web audio, download to local file, then call `add_audio_safe(...)`.
