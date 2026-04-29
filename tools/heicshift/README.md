# HEICShift sidecar

| | |
|---|---|
| **UCX module** | Toolbox > Image Converter (defaults absorbed) |
| **Integration phase** | v2.3 |
| **Source ported** | YES — see this directory |
| **Entry point** | `heicshift.py` |
| **Runtime** | Python 3.10+ + Pillow + libheif + libjxl + dcraw |
| **NDJSON CLI shim** | not yet — lands at integration phase |

## What this engine does

Universal image batch converter. Scans directories recursively and converts JPEG, PNG, HEIC, AVIF, WebP, JPEG XL, Camera RAW, TIFF, BMP, JPEG 2000, QOI, ICO with full metadata preservation (no chroma subsampling, ICC profiles preserved). HEICShift's metadata/ICC defaults will be absorbed into UCX's existing libvips/libjxl strategies in v2.3.

## How UCX will use it

The C# shell will launch a frozen build of this tool as a sidecar process via `ProcessStartInfo`, parsing NDJSON progress events on stdout. The contract lives in [`../README.md`](../README.md). The shim that adapts `heicshift.py` to the contract will be added when this module is wired up in v2.3.

## Original docs

- [`README-source.md`](README-source.md) — full project README from when this was a standalone repo
- [`LICENSE`](LICENSE) — source-tool license (preserved for attribution)
- [`CHANGELOG.md`](CHANGELOG.md) — pre-port changelog
- [`ROADMAP.md`](ROADMAP.md) — pre-port roadmap (now superseded by parent ROADMAP)
- `requirements.txt` (where present) — Python dependencies
