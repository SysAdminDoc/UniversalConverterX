# StreamKeep Development Roadmap

# StreamKeep Development Roadmap

# StreamKeep Development Roadmap
> **Version at time of writing:** v4.17.0
# StreamKeep Development Roadmap
> **Date:** 2026-04-13
# StreamKeep Development Roadmap
> **Full feature specs:** See `features.md` for detailed What/Why/Touches/Risks per feature.
# StreamKeep Development Roadmap
>
# StreamKeep Development Roadmap
> This roadmap is designed to be followed across multiple implementation sessions.
# StreamKeep Development Roadmap
> Each phase groups features by dependency, scope, and theme. Within a phase,
# StreamKeep Development Roadmap
> features are ordered by recommended implementation sequence. Complete each
# StreamKeep Development Roadmap
> feature fully (implement, test via `py_compile` + `pyflakes` + headless smoke,
# StreamKeep Development Roadmap
> version bump, commit) before moving to the next.
# StreamKeep Development Roadmap

# StreamKeep Development Roadmap
---
# StreamKeep Development Roadmap

# StreamKeep Development Roadmap
## How to use this roadmap

# StreamKeep Development Roadmap
## How to use this roadmap
1. **Start a session** by reading this file and `CLAUDE.md`.
# StreamKeep Development Roadmap
## How to use this roadmap
2. **Pick the next unchecked feature** in the current phase.
# StreamKeep Development Roadmap
## How to use this roadmap
3. **Read `features.md`** for the full spec (What/Why/Touches/Risks).
# StreamKeep Development Roadmap
## How to use this roadmap
4. **Plan 3-8 implementation steps**, check in if scope grows.
# StreamKeep Development Roadmap
## How to use this roadmap
5. **Implement, test, version bump, commit.**
# StreamKeep Development Roadmap
## How to use this roadmap
6. **Check the box** below and update the version number.
# StreamKeep Development Roadmap
## How to use this roadmap
7. Move to the next feature or end the session.
# StreamKeep Development Roadmap
## How to use this roadmap

# StreamKeep Development Roadmap
## How to use this roadmap
### Versioning convention

# StreamKeep Development Roadmap
## How to use this roadmap
### Versioning convention
- Each **phase** bumps the minor version (v4.18.0, v4.19.0, ...).
# StreamKeep Development Roadmap
## How to use this roadmap
### Versioning convention
- Multiple features in one phase share the same minor version.
# StreamKeep Development Roadmap
## How to use this roadmap
### Versioning convention
- Hotfixes within a phase bump patch (v4.18.1).
# StreamKeep Development Roadmap
## How to use this roadmap
### Versioning convention
- The commit message should list all features shipped in that version.
# StreamKeep Development Roadmap
## How to use this roadmap
### Versioning convention

# StreamKeep Development Roadmap
## How to use this roadmap
### Quality bar per feature

# StreamKeep Development Roadmap
## How to use this roadmap
### Quality bar per feature
- `py_compile` clean on all touched files
# StreamKeep Development Roadmap
## How to use this roadmap
### Quality bar per feature
- `pyflakes` clean (no unused imports, no undefined names)
# StreamKeep Development Roadmap
## How to use this roadmap
### Quality bar per feature
- Headless smoke test covering the new code path where practical
# StreamKeep Development Roadmap
## How to use this roadmap
### Quality bar per feature
- No regressions in existing features (verify tabs still load, config round-trips)
# StreamKeep Development Roadmap
## How to use this roadmap
### Quality bar per feature
- Match existing code style, architecture, and Catppuccin Mocha theme
# StreamKeep Development Roadmap
## How to use this roadmap
### Quality bar per feature

# StreamKeep Development Roadmap
## How to use this roadmap
### Quality bar per feature
---
# StreamKeep Development Roadmap
## How to use this roadmap
### Quality bar per feature

# StreamKeep Development Roadmap
## Phase 1 — Quick Wins
> Small-scope, high-value features with no cross-feature dependencies.
# StreamKeep Development Roadmap
## Phase 1 — Quick Wins
> Goal: ship 6-8 improvements fast, build momentum.
# StreamKeep Development Roadmap
## Phase 1 — Quick Wins

# StreamKeep Development Roadmap
## Phase 1 — Quick Wins

# StreamKeep Development Roadmap
## Phase 1 — Quick Wins

# StreamKeep Development Roadmap
## Phase 1 — Quick Wins

# StreamKeep Development Roadmap
## Phase 1 — Quick Wins

# StreamKeep Development Roadmap
## Phase 1 — Quick Wins

# StreamKeep Development Roadmap
## Phase 1 — Quick Wins

# StreamKeep Development Roadmap
## Phase 1 — Quick Wins

# StreamKeep Development Roadmap
## Phase 1 — Quick Wins

# StreamKeep Development Roadmap
## Phase 1 — Quick Wins
---
# StreamKeep Development Roadmap
## Phase 1 — Quick Wins

# StreamKeep Development Roadmap
## Phase 2 — Download Core
> Strengthen the core download workflow. F1 (queue) is the centerpiece.
# StreamKeep Development Roadmap
## Phase 2 — Download Core
> Build supporting features first, then tackle the queue.
# StreamKeep Development Roadmap
## Phase 2 — Download Core

# StreamKeep Development Roadmap
## Phase 2 — Download Core

# StreamKeep Development Roadmap
## Phase 2 — Download Core

# StreamKeep Development Roadmap
## Phase 2 — Download Core

# StreamKeep Development Roadmap
## Phase 2 — Download Core

# StreamKeep Development Roadmap
## Phase 2 — Download Core

# StreamKeep Development Roadmap
## Phase 2 — Download Core

# StreamKeep Development Roadmap
## Phase 2 — Download Core
---
# StreamKeep Development Roadmap
## Phase 2 — Download Core

# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing
> Make the editing pipeline powerful. Build low-level features first,
# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing
> then composite features that combine them.
# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing

# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing

# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing

# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing

# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing

# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing

# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing

# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing

# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing
---
# StreamKeep Development Roadmap
## Phase 3 — Trim, Clip & Post-Processing

# StreamKeep Development Roadmap
## Phase 4 — Notifications, Hooks & Integration
> External connections — make StreamKeep play well with other tools.
# StreamKeep Development Roadmap
## Phase 4 — Notifications, Hooks & Integration

# StreamKeep Development Roadmap
## Phase 4 — Notifications, Hooks & Integration

# StreamKeep Development Roadmap
## Phase 4 — Notifications, Hooks & Integration

# StreamKeep Development Roadmap
## Phase 4 — Notifications, Hooks & Integration

# StreamKeep Development Roadmap
## Phase 4 — Notifications, Hooks & Integration

# StreamKeep Development Roadmap
## Phase 4 — Notifications, Hooks & Integration

# StreamKeep Development Roadmap
## Phase 4 — Notifications, Hooks & Integration
---
# StreamKeep Development Roadmap
## Phase 4 — Notifications, Hooks & Integration

# StreamKeep Development Roadmap
## Phase 5 — Monitor Intelligence
> Make auto-record smarter. These features build on the existing
# StreamKeep Development Roadmap
## Phase 5 — Monitor Intelligence
> ChannelMonitor and MonitorEntry infrastructure.
# StreamKeep Development Roadmap
## Phase 5 — Monitor Intelligence

# StreamKeep Development Roadmap
## Phase 5 — Monitor Intelligence

# StreamKeep Development Roadmap
## Phase 5 — Monitor Intelligence

# StreamKeep Development Roadmap
## Phase 5 — Monitor Intelligence

# StreamKeep Development Roadmap
## Phase 5 — Monitor Intelligence

# StreamKeep Development Roadmap
## Phase 5 — Monitor Intelligence
---
# StreamKeep Development Roadmap
## Phase 5 — Monitor Intelligence

# StreamKeep Development Roadmap
## Phase 6 — Library & Organization
> Transform History from a download log into a browsable media library.
# StreamKeep Development Roadmap
## Phase 6 — Library & Organization
> F38 (watch status) enables F32 (lifecycle cleanup) from Phase 5.
# StreamKeep Development Roadmap
## Phase 6 — Library & Organization

# StreamKeep Development Roadmap
## Phase 6 — Library & Organization

# StreamKeep Development Roadmap
## Phase 6 — Library & Organization

# StreamKeep Development Roadmap
## Phase 6 — Library & Organization

# StreamKeep Development Roadmap
## Phase 6 — Library & Organization

# StreamKeep Development Roadmap
## Phase 6 — Library & Organization

# StreamKeep Development Roadmap
## Phase 6 — Library & Organization
---
# StreamKeep Development Roadmap
## Phase 6 — Library & Organization

# StreamKeep Development Roadmap
## Phase 7 — Advanced & Ambitious
> Larger features that add differentiated capabilities.
# StreamKeep Development Roadmap
## Phase 7 — Advanced & Ambitious
> Each is independent and can be tackled in any order.
# StreamKeep Development Roadmap
## Phase 7 — Advanced & Ambitious

# StreamKeep Development Roadmap
## Phase 7 — Advanced & Ambitious

# StreamKeep Development Roadmap
## Phase 7 — Advanced & Ambitious

# StreamKeep Development Roadmap
## Phase 7 — Advanced & Ambitious

# StreamKeep Development Roadmap
## Phase 7 — Advanced & Ambitious

# StreamKeep Development Roadmap
## Phase 7 — Advanced & Ambitious

# StreamKeep Development Roadmap
## Phase 7 — Advanced & Ambitious
---
# StreamKeep Development Roadmap
## Phase 7 — Advanced & Ambitious

# Wave 2 — Features F41-F80

# Wave 2 — Features F41-F80
> Wave 1 (F1-F40) shipped in v4.18.0-v4.24.5. Wave 2 expands StreamKeep
# Wave 2 — Features F41-F80
> into a full media management platform: headless/CLI operation, authenticated
# Wave 2 — Features F41-F80
> downloads, built-in playback, AI-assisted editing, analytics, distribution
# Wave 2 — Features F41-F80
> pipelines, and deep UX polish.
# Wave 2 — Features F41-F80

# Wave 2 — Features F41-F80
---
# Wave 2 — Features F41-F80

# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale
> Infrastructure that future Wave 2 features depend on.
# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale
> SQLite migration (F41) unblocks analytics, plugin data, and scale.
# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale
> CLI mode (F42) unlocks headless deployment.
# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale

# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale

# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale

# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale

# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale

# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale

# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale

# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale
---
# Wave 2 — Features F41-F80
## Phase 8 — Foundation & Scale

# Wave 2 — Features F41-F80
## Phase 9 — Authentication & Network
> Unlock paywalled and geo-blocked content. Cookie import (F47) is
# Wave 2 — Features F41-F80
## Phase 9 — Authentication & Network
> the highest-impact feature in this phase.
# Wave 2 — Features F41-F80
## Phase 9 — Authentication & Network

# Wave 2 — Features F41-F80
## Phase 9 — Authentication & Network

# Wave 2 — Features F41-F80
## Phase 9 — Authentication & Network

# Wave 2 — Features F41-F80
## Phase 9 — Authentication & Network

# Wave 2 — Features F41-F80
## Phase 9 — Authentication & Network

# Wave 2 — Features F41-F80
## Phase 9 — Authentication & Network

# Wave 2 — Features F41-F80
## Phase 9 — Authentication & Network
---
# Wave 2 — Features F41-F80
## Phase 9 — Authentication & Network

# Wave 2 — Features F41-F80
## Phase 10 — Built-in Player
> Watch content without leaving the app. F52 is the centerpiece;
# Wave 2 — Features F41-F80
## Phase 10 — Built-in Player
> F53-F56 extend it. All depend on mpv/libmpv.
# Wave 2 — Features F41-F80
## Phase 10 — Built-in Player

# Wave 2 — Features F41-F80
## Phase 10 — Built-in Player

# Wave 2 — Features F41-F80
## Phase 10 — Built-in Player

# Wave 2 — Features F41-F80
## Phase 10 — Built-in Player

# Wave 2 — Features F41-F80
## Phase 10 — Built-in Player

# Wave 2 — Features F41-F80
## Phase 10 — Built-in Player

# Wave 2 — Features F41-F80
## Phase 10 — Built-in Player
---
# Wave 2 — Features F41-F80
## Phase 10 — Built-in Player

# Wave 2 — Features F41-F80
## Phase 11 — Intelligence
> Let the app make smart decisions about content. F57 combines
# Wave 2 — Features F41-F80
## Phase 11 — Intelligence
> existing chat/audio/scene signals. F58-F62 are independent.
# Wave 2 — Features F41-F80
## Phase 11 — Intelligence

# Wave 2 — Features F41-F80
## Phase 11 — Intelligence

# Wave 2 — Features F41-F80
## Phase 11 — Intelligence

# Wave 2 — Features F41-F80
## Phase 11 — Intelligence

# Wave 2 — Features F41-F80
## Phase 11 — Intelligence

# Wave 2 — Features F41-F80
## Phase 11 — Intelligence

# Wave 2 — Features F41-F80
## Phase 11 — Intelligence

# Wave 2 — Features F41-F80
## Phase 11 — Intelligence
---
# Wave 2 — Features F41-F80
## Phase 11 — Intelligence

# Wave 2 — Features F41-F80
## Phase 12 — Analytics & Health
> Visibility into your archive. Data sourced from History + DB.
# Wave 2 — Features F41-F80
## Phase 12 — Analytics & Health
> All features in this phase are independent.
# Wave 2 — Features F41-F80
## Phase 12 — Analytics & Health

# Wave 2 — Features F41-F80
## Phase 12 — Analytics & Health

# Wave 2 — Features F41-F80
## Phase 12 — Analytics & Health

# Wave 2 — Features F41-F80
## Phase 12 — Analytics & Health

# Wave 2 — Features F41-F80
## Phase 12 — Analytics & Health

# Wave 2 — Features F41-F80
## Phase 12 — Analytics & Health

# Wave 2 — Features F41-F80
## Phase 12 — Analytics & Health
---
# Wave 2 — Features F41-F80
## Phase 12 — Analytics & Health

# Wave 2 — Features F41-F80
## Phase 13 — Distribution & Sharing
> Get content out of StreamKeep. Upload destinations (F68) is the
# Wave 2 — Features F41-F80
## Phase 13 — Distribution & Sharing
> big one; others are lighter integration features.
# Wave 2 — Features F41-F80
## Phase 13 — Distribution & Sharing

# Wave 2 — Features F41-F80
## Phase 13 — Distribution & Sharing

# Wave 2 — Features F41-F80
## Phase 13 — Distribution & Sharing

# Wave 2 — Features F41-F80
## Phase 13 — Distribution & Sharing

# Wave 2 — Features F41-F80
## Phase 13 — Distribution & Sharing

# Wave 2 — Features F41-F80
## Phase 13 — Distribution & Sharing

# Wave 2 — Features F41-F80
## Phase 13 — Distribution & Sharing
---
# Wave 2 — Features F41-F80
## Phase 13 — Distribution & Sharing

# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility
> Polish and open up. Plugin SDK (F77) is the strategic feature;
# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility
> i18n (F74) has the widest user impact.
# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility

# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility

# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility

# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility

# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility

# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility

# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility

# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility

# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility

# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility
---
# Wave 2 — Features F41-F80
## Phase 14 — UX & Extensibility

# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)

# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
```
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
F17 (Pagination) ──> F2 (Batch VOD) ──> F1 (Queue) enables full batch flow
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
F8 (Chat markers) ──> F9 (Multi-range highlight reel)
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
F9 (Multi-range) ──> F31 (Social clip export) extends the dialog
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
F7 (Presets) ──> F18 (Per-download override) uses preset picker
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
F38 (Watch status) ──> F32 (Lifecycle cleanup) uses "delete after watched"
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
F29 (WhisperX) ──> F27 (Transcript search) benefits from word-level timestamps
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
F34 (Waveform) ──> improves F9 (Multi-range) and F31 (Social export) editing UX
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
F30 (Scene detect) ──> F8 (Chat markers) can combine signals for better clip detection
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
F4 (Notification log) ──> F15 (Webhook expansion) more targets for same events
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
F24 (Event hooks) ──> F33 (Media server) can be wired via hooks as alternative
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)
```
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 1 (completed)

# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
```
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
F41 (SQLite) ──> F63 (Analytics) + F64 (Bandwidth) + F66 (Channel stats)
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
                  require indexed queries on large datasets
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
F41 (SQLite) ──> F72 (Backup/Restore) includes DB export
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
F42 (CLI) ──> decouples engine from Qt for headless deployment
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
F47 (Cookies) ──> F48 (Accounts) builds on cookie-based auth
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
F52 (Player) ──> F53 (PiP) + F54 (Sync) + F55 (Chapters) + F56 (EQ)
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
                  all depend on embedded mpv
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
F8+F34+F30 (Wave 1 signals) ──> F57 (AI highlights) combines all three
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
F37 (REST API, Wave 1) ──> F69 (Gallery) + F70 (RSS) extend the web server
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
F45 (Global search) ──> F71 (Notes) adds notes to search corpus
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
F41 (SQLite) ──> F77 (Plugins) need DB for plugin state/settings
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
F79 (Encrypted config) ──> F48 (Accounts) stores credentials securely
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
```
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2

# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2
---
# Wave 2 — Features F41-F80
## Dependency Graph (cross-feature)
### Wave 2

# Wave 2 — Features F41-F80
## Version Plan

# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)

# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)
| Phase | Target Version | Features | Theme |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)
|-------|---------------|----------|-------|
# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)
| 1 | v4.18.0 | F6, F11, F12, F14, F5, F28, F40, F10 | Quick wins |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)
| 2 | v4.19.0 | F16, F21, F3, F1, F17, F2 | Download core |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)
| 3 | v4.20.0 | F34, F26, F7, F8, F9, F30, F31 | Editing pipeline |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)
| 4 | v4.21.0 | F4, F15, F24, F19, F33 | Integration |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)
| 5 | v4.22.0 | F18, F25, F32, F39 | Monitor intelligence |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)
| 6 | v4.23.0 | F38, F13, F35, F36, F27 | Library |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)
| 7 | v4.24.0 | F29, F22, F23, F37, F20 | Advanced |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 1 (completed)

# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)

# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)
| Phase | Target Version | Features | Theme |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)
|-------|---------------|----------|-------|
# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)
| 8  | v4.25.0 | F41, F42, F43, F44, F45, F46 | Foundation & scale |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)
| 9  | v4.26.0 | F47, F48, F49, F50, F51 | Auth & network |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)
| 10 | v4.27.0 | F52, F53, F54, F55, F56 | Built-in player |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)
| 11 | v4.28.0 | F57, F58, F59, F60, F61, F62 | Intelligence |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)
| 12 | v4.29.0 | F63, F64, F65, F66, F67 | Analytics & health |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)
| 13 | v4.30.0 | F68, F69, F70, F71, F72 | Distribution |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)
| 14 | v4.31.0 | F73, F74, F75, F76, F77, F78, F79, F80 | UX & extensibility |
# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)

# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)
---
# Wave 2 — Features F41-F80
## Version Plan
### Wave 2 (planned)

# Wave 2 — Features F41-F80
## Session Resumption Notes

# Wave 2 — Features F41-F80
## Session Resumption Notes
When resuming in a new conversation:
# Wave 2 — Features F41-F80
## Session Resumption Notes

# Wave 2 — Features F41-F80
## Session Resumption Notes
1. Read `ROADMAP.md` (this file) to see what's done and what's next.
# Wave 2 — Features F41-F80
## Session Resumption Notes
2. Read `CLAUDE.md` for project conventions and architecture.
# Wave 2 — Features F41-F80
## Session Resumption Notes
3. Read `features.md` for the full spec of the feature you're implementing.
# Wave 2 — Features F41-F80
## Session Resumption Notes
4. Check `git log --oneline -5` to see what was last shipped.
# Wave 2 — Features F41-F80
## Session Resumption Notes
5. The user prefers autonomous implementation — don't ask for confirmation,
# Wave 2 — Features F41-F80
## Session Resumption Notes
   just implement, test, version bump, and commit.
# Wave 2 — Features F41-F80
## Session Resumption Notes
6. Each feature should be a single commit with message format:
# Wave 2 — Features F41-F80
## Session Resumption Notes
   `v{X.Y.Z} - {Feature title} (F{N})`
# Wave 2 — Features F41-F80
## Session Resumption Notes
7. Always sign release APKs — wait, this is a Python desktop app.
# Wave 2 — Features F41-F80
## Session Resumption Notes
   For this project: always run `py_compile` + `pyflakes` clean before committing.

## Open-Source Research (Round 2)

### Related OSS Projects
- **yt-dlp** — https://github.com/yt-dlp/yt-dlp — the downloader engine everyone wraps; 1000+ site extractors, SponsorBlock integration, postprocessor hooks, --cookies-from-browser, format selection DSL
- **dsymbol/yt-dlp-gui** — https://github.com/dsymbol/yt-dlp-gui — PySide6 wrapper, purpose-built for yt-dlp; concurrent queue, format presets, config-file driven
- **Tartube (axcore)** — https://github.com/axcore/tartube — Python3/Gtk3 mature library-oriented GUI (Windows/Linux/BSD/macOS); channel subscriptions, archive tracking
- **yt-dlg (oleksis/youtube-dl-gui)** — https://github.com/oleksis/youtube-dl-gui — wxPython cross-platform, distributed via PyPI/MS Store/Winget/Snap — shipping-polish reference
- **Open Video Downloader (jely2002)** — https://github.com/jely2002/youtube-dl-gui — Tauri + Vue; modern lightweight alternative with auto-update
- **ytdl-sub** — https://github.com/jmbannon/ytdl-sub — declarative YAML subscriptions that produce a Plex/Jellyfin-compatible library; audit trail + dry-run
- **MeTube** — https://github.com/alexta69/metube — web-hosted yt-dlp with queue, SSO, Docker-ready; self-hosted family option
- **streamlink** — https://github.com/streamlink/streamlink — focused on live streams (Twitch/Kick); DASH/HLS fronting; StreamKeep should integrate as a fallback extractor
- **gallery-dl** — https://github.com/mikf/gallery-dl — image/gallery extractor with similar architecture; useful for platform breadth

### Features to Borrow
- Declarative YAML subscription format that outputs into a Plex/Jellyfin folder tree (ytdl-sub)
- Archive.txt plus SQLite dual-tracking: quick seen check plus rich metadata (ytdl-sub pattern)
- Format-selector DSL exposure as a visual builder ("bestvideo+bestaudio/best" → menu) with raw fallback (yt-dlp-gui)
- Streamlink integration for Twitch/Kick/YouTube-Live that yt-dlp can't follow (Streamlink)
- Built-in SponsorBlock chapter-add + skip-add postprocessor options (yt-dlp native)
- --cookies-from-browser selector with Firefox/Chrome/Edge/Brave profile picker (yt-dlp)
- Queue persistence with resumable downloads across app restarts (MeTube, yt-dlg)
- Concurrent-download limiter per host to avoid bans (--sleep-requests, --max-downloads) (yt-dlp)
- Automatic proxy rotation from a user-provided list on 429/403 (power-user feature in yt-dlp config)
- Postprocessor chain: auto-chapters from SponsorBlock + metadata embed + thumbnail embed + subtitles burn/embed (yt-dlp)
- Web UI mode mirroring desktop via Tauri/Flask so users can queue from their phone on the LAN (MeTube)
- Per-extractor plugin API so community extractors can be dropped in without patching the core (yt-dlp plugins)

### Patterns & Architectures Worth Studying
- Extractor plugin architecture: each site = one class inheriting InfoExtractor, auto-discovered from a folder (yt-dlp)
- Postprocessor chain pattern: each stage implements .run(info_dict, files) and returns a new info_dict (yt-dlp)
- Archive file pattern as the dedupe source-of-truth, simpler than a DB for casual users (yt-dlp --download-archive)
- Declarative-vs-imperative subscription modes: ytdl-sub proves a YAML-first model is more auditable than GUI clicks (ytdl-sub)
- Headless daemon + web UI split that MeTube uses — lets StreamKeep run on a NAS and be driven from anywhere (MeTube)

## Implementation Deep Dive (Round 3)

### Reference Implementations to Study
- **yt-dlp/yt-dlp `yt_dlp/YoutubeDL.py`** — https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/YoutubeDL.py — authoritative `YoutubeDL(params)` options surface; use `devscripts/cli_to_api.py` to translate CLI flags to kwargs.
- **yt-dlp Plugin Development wiki** — https://github.com/yt-dlp/yt-dlp/wiki/Plugin-Development — canonical namespace-package pattern `yt_dlp_plugins.extractor.<name>` for third-party extractors.
- **yt-dlp/yt-dlp-sample-plugins** — https://github.com/yt-dlp/yt-dlp-sample-plugins — template repo; fork this for StreamKeep's plugin SDK.
- **mpv-player/python-mpv** — https://github.com/jaseg/python-mpv — embedded mpv via libmpv; `MPV(wid=winid)` binds to a Qt widget `winId()` for in-app playback.
- **yt-dlp/yt-dlp `yt_dlp/postprocessor/ffmpeg.py`** — https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/postprocessor/ffmpeg.py — reference for ffmpeg argument construction (remux, embed subs, embed thumbnail).
- **streamlink/streamlink `src/streamlink/plugin/plugin.py`** — https://github.com/streamlink/streamlink/blob/master/src/streamlink/plugin/plugin.py — alternate extractor architecture; matcher-based URL dispatch cleaner than yt-dlp's regex inheritance.
- **yt-dlp progress hook example** — https://github.com/yt-dlp/yt-dlp?tab=readme-ov-file#embedding-yt-dlp — `progress_hooks=[lambda d: ...]` — wire to PyQt signal via `QObject.invoke_method` to cross threads safely.

### Known Pitfalls from Similar Projects
- `yt_dlp.YoutubeDL(params).download(urls)` blocks the calling thread — wrap in `QThread` or use `params['progress_hooks']` + `concurrent.futures.ThreadPoolExecutor`.
- Plugin namespace packages require an empty `__init__.py` in `yt_dlp_plugins/extractor/` — missing causes silent non-registration; verify with `-v` flag.
- `ytdlp-plugins` third-party manager is inactive (no release >12 months) — do NOT depend on it; use official plugin spec instead.
- PyInstaller one-file + yt-dlp lazy extractor loader: `--collect-submodules yt_dlp.extractor` is mandatory or dynamic plugin discovery breaks.
- mpv `libmpv-2.dll` on Windows must be in the same dir as the exe or next to the script; PyInstaller bundles require `--add-binary "libmpv-2.dll;."`.
- Progress hooks fire on yt-dlp's worker thread — direct Qt widget access raises `QObject::setParent: Cannot set parent, new parent is in a different thread`. Use `QMetaObject.invokeMethod(widget, "update", Qt.QueuedConnection, ...)`.
- Twitch HLS segments encrypted after 2024 policy change — yt-dlp >=2024.08 handles it; older pins silently produce broken files.
- FFmpeg `-c copy` remux fails on fragmented MP4 with timestamp discontinuities — fall back to `-c:v copy -c:a aac -async 1`.

### Library Integration Checklist
- `yt-dlp==2025.01.15` — https://pypi.org/project/yt-dlp — key API `from yt_dlp import YoutubeDL; YoutubeDL(params).download([url])`. Gotcha: pin with calver; breaking changes land monthly.
- `python-mpv==1.0.7` — https://github.com/jaseg/python-mpv — embedded player. Gotcha: requires `libmpv-2.dll` on PATH; bundle alongside exe.
- `PyQt6==6.8.0` — `QThread` + `pyqtSignal` for progress updates. Gotcha: connect signals with `Qt.QueuedConnection` when crossing thread boundaries.
- `ffmpeg-python==0.2.0` — fluent wrapper over ffmpeg CLI; gotcha: requires `ffmpeg.exe` on PATH (not bundled). Ship via `imageio-ffmpeg` if self-contained.
- `imageio-ffmpeg==0.5.1` — bundles ffmpeg binary per-platform; `import imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe()` returns absolute path.
- `fastapi==0.115.6` + `uvicorn==0.34.0` — REST API. Gotcha: under PyInstaller, use `--collect-all fastapi --collect-all pydantic` or `anyio` imports fail at runtime.
- `mutagen==1.47.0` — metadata embedding for MP3/M4A; cleaner than yt-dlp's `--embed-metadata` if you need custom tags.
- `PyInstaller==6.11.1` — spec flags: `--collect-submodules yt_dlp.extractor` + `--add-binary libmpv-2.dll;.` + runtime hook for `multiprocessing.freeze_support()`.
