# GifStudio sidecar

| | |
|---|---|
| **UCX module** | Toolbox > GIF Maker |
| **Integration phase** | v2.3 |
| **Source ported** | YES — see this directory |
| **Entry point** | `index.html` |
| **Runtime** | HTML / JS (single file) |
| **NDJSON CLI shim** | not yet — lands at integration phase |

## What this engine does

Browser-based GIF creation and editing studio. Build GIFs from images or video frames with frame manipulation, effects, and timing controls. 100% client-side — UCX hosts it via WebView2.

## How UCX will use it

The C# shell will launch a frozen build of this tool as a sidecar process via `ProcessStartInfo`, parsing NDJSON progress events on stdout. The contract lives in [`../README.md`](../README.md). The shim that adapts `index.html` to the contract will be added when this module is wired up in v2.3.

## Original docs

- [`README-source.md`](README-source.md) — full project README from when this was a standalone repo
- [`LICENSE`](LICENSE) — source-tool license (preserved for attribution)
- [`CHANGELOG.md`](CHANGELOG.md) — pre-port changelog
- [`ROADMAP.md`](ROADMAP.md) — pre-port roadmap (now superseded by parent ROADMAP)
- `requirements.txt` (where present) — Python dependencies
