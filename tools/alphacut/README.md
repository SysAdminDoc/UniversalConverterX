# AlphaCut sidecar

| | |
|---|---|
| **UCX module** | Toolbox > Background Remover |
| **Integration phase** | v2.2 |
| **Source ported** | YES — see this directory |
| **Entry point** | `AlphaCut.py` |
| **Runtime** | Python 3.9+ + ONNX Runtime + FFmpeg |
| **NDJSON CLI shim** | not yet — lands at integration phase |

## What this engine does

AI video background removal and compositing. 8 ONNX segmentation models (U2Net / ISNet / BiRefNet) with chroma-key fallback. Output to ProRes 4444 + alpha, WebM VP9 + alpha, animated WebP, animated GIF, PNG sequences, green screen, or grayscale matte. Pipelined I/O with parallel decode/infer/save.

## How UCX will use it

The C# shell will launch a frozen build of this tool as a sidecar process via `ProcessStartInfo`, parsing NDJSON progress events on stdout. The contract lives in [`../README.md`](../README.md). The shim that adapts `AlphaCut.py` to the contract will be added when this module is wired up in v2.2.

## Original docs

- [`README-source.md`](README-source.md) — full project README from when this was a standalone repo
- [`LICENSE`](LICENSE) — source-tool license (preserved for attribution)
- [`CHANGELOG.md`](CHANGELOG.md) — pre-port changelog
- [`ROADMAP.md`](ROADMAP.md) — pre-port roadmap (now superseded by parent ROADMAP)
- `requirements.txt` (where present) — Python dependencies
