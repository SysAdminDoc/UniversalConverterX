# Vertigo sidecar

| | |
|---|---|
| **UCX module** | Toolbox > Auto Reframe |
| **Integration phase** | v2.3 |
| **Source ported** | YES — see this directory |
| **Entry point** | `vertigo.py` |
| **Runtime** | Python 3.10+ + PyQt6 + MediaPipe |
| **NDJSON CLI shim** | not yet — lands at integration phase |

## What this engine does

Vertical-video studio for short-form creators. Reframes any-aspect footage into 9:16 (Shorts/Reels/TikTok), 1:1, or 4:5 with four modes: Center Crop, Smart Track (MediaPipe face detection with scene-aware keyframes), Blur Letterbox, Manual. Batch queue with platform presets.

## How UCX will use it

The C# shell will launch a frozen build of this tool as a sidecar process via `ProcessStartInfo`, parsing NDJSON progress events on stdout. The contract lives in [`../README.md`](../README.md). The shim that adapts `vertigo.py` to the contract will be added when this module is wired up in v2.3.

## Original docs

- [`README-source.md`](README-source.md) — full project README from when this was a standalone repo
- [`LICENSE`](LICENSE) — source-tool license (preserved for attribution)
- [`CHANGELOG.md`](CHANGELOG.md) — pre-port changelog
- [`ROADMAP.md`](ROADMAP.md) — pre-port roadmap (now superseded by parent ROADMAP)
- `requirements.txt` (where present) — Python dependencies
