# LipSight sidecar

| | |
|---|---|
| **UCX module** | Toolbox > Lip Reading |
| **Integration phase** | v2.2 |
| **Source ported** | YES — see this directory |
| **Entry point** | `LipSight.py` |
| **Runtime** | Python 3.8+ + visual speech recognition models |
| **NDJSON CLI shim** | not yet — lands at integration phase |

## What this engine does

AI-powered lip reading: transcribe speech from silent video using state-of-the-art visual speech recognition models.

## How UCX will use it

The C# shell will launch a frozen build of this tool as a sidecar process via `ProcessStartInfo`, parsing NDJSON progress events on stdout. The contract lives in [`../README.md`](../README.md). The shim that adapts `LipSight.py` to the contract will be added when this module is wired up in v2.2.

## Original docs

- [`README-source.md`](README-source.md) — full project README from when this was a standalone repo
- [`LICENSE`](LICENSE) — source-tool license (preserved for attribution)
- [`CHANGELOG.md`](CHANGELOG.md) — pre-port changelog
- [`ROADMAP.md`](ROADMAP.md) — pre-port roadmap (now superseded by parent ROADMAP)
- `requirements.txt` (where present) — Python dependencies
