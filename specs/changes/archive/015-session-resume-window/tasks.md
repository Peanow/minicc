# 015-session-resume-window tasks

- [x] T1 [R1, AC1] Add safe, complete terminal rendering for persisted session messages and wire it into all interactive resume entry points.
- [x] T2 [R2, AC2] Add `/resume [ID]`, latest-session resolution, and session-ID completion while preserving `/session resume ID`.
- [x] T3 [R3, AC3] Emit metadata-only `session_resumed` Trace events after successful interactive resume.
- [x] T4 [R1, R2, R3, AC1, AC2, AC3] Add pytest coverage and update user/capability documentation.
