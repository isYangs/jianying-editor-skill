## Vendor Dependencies

This directory contains vendored runtime dependencies that are imported by skill code.

- `pyJianYingDraft/`: embedded library used by `jy_wrapper` and core mixins.

Guidelines:

- Keep upstream structure intact to simplify future sync.
- Prefer `git mv` for relocations to preserve history.
- Apply local patches only when required for this skill.
