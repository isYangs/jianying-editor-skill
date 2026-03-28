# Agent Playbook

Task routing matrix for reliable execution.

## 0) Quick Edit Runtime Template (Default for "来个剪辑")

Use this fixed sequence:

1. Environment check (minimal):
   - verify Python works
   - verify draft root exists
2. Asset resolution:
   - use explicit local/cloud assets
   - only call `asset_search.py` when user asks for style/effect lookup
3. Script assembly:
   - generate one runnable script with deterministic APIs
4. Execute once:
   - run script and capture success/failure output
5. Acceptance check:
   - validate draft and track structure (see checklist below)

### Acceptance Checklist (Mandatory)

- Draft folder exists under JianYing drafts root
- `project.save()` completed successfully
- At least one `video` track segment exists
- If BGM exists, it must be on `audio` track (not `video`)
- If narration exists, subtitle segments should exist and be time-aligned

## 1) Cloud Video + BGM Draft

- Read: `rules/setup.md`, `rules/media.md`, `rules/audio-voice.md`
- Reference: `examples/cloud_video_music_tts_demo.py`
- Required checks:
  - BGM goes to audio track.
  - project saved successfully.

## 2) Narration + Subtitle Alignment

- Read: `rules/text.md`, `rules/audio-voice.md`
- APIs: `add_tts_intelligent`, `add_narrated_subtitles`
- Required checks:
  - subtitle timing aligns with narration.
  - subtitle track exists.

## 3) Recording + Smart Zoom

- Read: `rules/recording.md`
- Execute: `tools/recording/recorder.py`
- Required checks:
  - recording output exists.
  - generated draft can be opened.

## 4) Effects / Transitions

- Read: `rules/effects.md`, `rules/keyframes.md`
- Tools: `scripts/asset_search.py`
- Required checks:
  - selected IDs resolved.
  - no None returns from effect/transition methods.

## 5) Commentary from Long Video

- Read: `rules/generative.md`
- Prompt: `prompts/movie_commentary.md`
- Execute: `scripts/movie_commentary_builder.py`
- Required checks:
  - input media pre-optimized (<=30 min, 360p preferred).
  - storyboard JSON parsed and applied.

## 6) Export and CI-facing Validation

- Read: `rules/core.md`, `rules/cli.md`
- Execute:
  - `scripts/auto_exporter.py`
  - `scripts/api_validator.py --json`
- Required checks:
  - output file exists.
  - CLI return code and JSON contract are valid.
