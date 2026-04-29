# StreamKeep sidecar

| | |
|---|---|
| **UCX module** | Downloader |
| **Integration phase** | v2.1 |
| **Source ported** | YES — see this directory |
| **Entry point** | `StreamKeep.py` |
| **Runtime** | Python 3.10+ + yt-dlp + ffmpeg |
| **NDJSON CLI shim** | not yet — lands at integration phase |

## What this engine does

Multi-platform VOD and live-stream downloader. Native extractors for Kick, Twitch, Rumble, SoundCloud, Reddit, Audius; podcast RSS; direct URL sniffing; yt-dlp fallback for 1000+ sites. Channel monitoring, segmented downloads, GPU-accelerated post-processing.

## How UCX will use it

The C# shell will launch a frozen build of this tool as a sidecar process via `ProcessStartInfo`, parsing NDJSON progress events on stdout. The contract lives in [`../README.md`](../README.md). The shim that adapts `StreamKeep.py` to the contract will be added when this module is wired up in v2.1.

## Original docs

- [`README-source.md`](README-source.md) — full project README from when this was a standalone repo
- [`LICENSE`](LICENSE) — source-tool license (preserved for attribution)
- [`CHANGELOG.md`](CHANGELOG.md) — pre-port changelog
- [`ROADMAP.md`](ROADMAP.md) — pre-port roadmap (now superseded by parent ROADMAP)
- `requirements.txt` (where present) — Python dependencies
