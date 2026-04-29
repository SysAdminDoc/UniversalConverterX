# ClipForge sidecar

| | |
|---|---|
| **UCX module** | Editor |
| **Integration phase** | v2.1 |
| **Source ported** | YES — see this directory |
| **Entry point** | `clipforge.py` |
| **Runtime** | Python 3.10+ + FFmpeg + Real-ESRGAN |
| **NDJSON CLI shim** | not yet — lands at integration phase |

## What this engine does

All-in-one editor: trim (lossless or re-encode), crop / rotate / flip with aspect presets, AI upscale via Real-ESRGAN, frame interpolation, format convert, filter, audio adjust, batch queue. Includes browser-based preview via index.html + editor.js.

## How UCX will use it

The C# shell will launch a frozen build of this tool as a sidecar process via `ProcessStartInfo`, parsing NDJSON progress events on stdout. The contract lives in [`../README.md`](../README.md). The shim that adapts `clipforge.py` to the contract will be added when this module is wired up in v2.1.

## Original docs

- [`README-source.md`](README-source.md) — full project README from when this was a standalone repo
- [`LICENSE`](LICENSE) — source-tool license (preserved for attribution)
- [`CHANGELOG.md`](CHANGELOG.md) — pre-port changelog
- [`ROADMAP.md`](ROADMAP.md) — pre-port roadmap (now superseded by parent ROADMAP)
- `requirements.txt` (where present) — Python dependencies
