# tools/ — Sidecar Engines

Each subdirectory will host a vendored copy of an external tool that UniversalConverterX hosts as a sidecar process. The C# shell launches the sidecar's CLI (`<tool>.exe`) and parses NDJSON progress events on stdout.

## Vendoring contract

Each sidecar tool ships under `tools/<name>/` with:

```
tools/<name>/
  <name>.exe          # frozen with PyInstaller (or native binary)
  README.md           # adapted from the source repo
  LICENSE             # source-tool license retained
  models/             # any AI/ML weights (downloaded on first use, gitignored)
```

The C# orchestrator looks up the binary by walking up from `AppContext.BaseDirectory` and falling back to `%LocalAppData%\UniversalConverterX\tools`.

## NDJSON CLI contract

Each sidecar must accept JSON arguments on stdin OR command-line flags, and emit progress as one JSON object per line on stdout:

```json
{"event": "progress", "percent": 42.5, "stage": "encoding", "eta_seconds": 12}
{"event": "log", "level": "info", "message": "Started encoding"}
{"event": "complete", "output": "C:\\path\\to\\result.mp4", "size_bytes": 12345678}
{"event": "error", "code": "missing_dep", "message": "ffmpeg not found"}
```

This matches the existing `IConversionOrchestrator` progress contract and minimizes glue code per tool.

## Planned sidecars

| Directory | Source repo | UCX module | Phase |
|---|---|---|---|
| `videocrush/` | `~/repos/VideoCrush/` | Compressor | v2.0 |
| `clipforge/` | `~/repos/ClipForge/` | Editor | v2.0 |
| `streamkeep/` | `~/repos/StreamKeep/` | Downloader | v2.0 |
| `alphacut/` | `~/repos/AlphaCut/` | Toolbox > Background Remover | v2.1 |
| `videosubtitleremover/` | `~/repos/VideoSubtitleRemover/` | Toolbox > Subtitle Remover | v2.1 |
| `lipsight/` | `~/repos/LipSight/` | Toolbox > Lip Reading | v2.1 |
| `vertigo/` | `~/repos/Vertigo/` | Toolbox > Auto Reframe | v2.2 |
| `framesnap/` | `~/repos/FrameSnap/` | Toolbox > Frame Snapshot | v2.2 |
| `gifstudio/` | `~/repos/GifStudio/` | Toolbox > GIF Maker | v2.2 |
| `heicshift/` | `~/repos/HEICShift/` | Toolbox > Image Converter (defaults absorbed into UCX FFmpeg/libvips strategies) | v2.2 |

Each subdirectory currently holds a stub README. Real binaries land in their target phase.
