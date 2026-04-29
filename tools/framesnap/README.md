# FrameSnap sidecar

| | |
|---|---|
| **UCX module** | Toolbox > Frame Snapshot |
| **Integration phase** | v2.3 |
| **Source ported** | YES — see this directory |
| **Entry point** | `framesnap.py` |
| **Runtime** | Python 3.10+ + FFmpeg |
| **NDJSON CLI shim** | not yet — lands at integration phase |

## What this engine does

Browse any video, mark frames visually, and export precise screenshots. Supports 30+ video formats via FFmpeg with OS fallback.

## How UCX will use it

The C# shell will launch a frozen build of this tool as a sidecar process via `ProcessStartInfo`, parsing NDJSON progress events on stdout. The contract lives in [`../README.md`](../README.md). The shim that adapts `framesnap.py` to the contract will be added when this module is wired up in v2.3.

## Original docs

- [`README-source.md`](README-source.md) — full project README from when this was a standalone repo
- [`LICENSE`](LICENSE) — source-tool license (preserved for attribution)
- [`CHANGELOG.md`](CHANGELOG.md) — pre-port changelog
- [`ROADMAP.md`](ROADMAP.md) — pre-port roadmap (now superseded by parent ROADMAP)
- `requirements.txt` (where present) — Python dependencies
