# tools/ — Sidecar Engines

Each subdirectory hosts a vendored copy of an external engine that UniversalConverterX hosts as a sidecar process. The C# shell launches each sidecar's frozen binary and parses NDJSON progress events on stdout.

## Audit (v2.0.0)

All 10 backing repos have been ported into this directory, plus a first-party `recordcast` recorder shim. Build artifacts (`build/`, `dist/`, frozen `.exe`s, `__pycache__`, `venv`, `.git`, AI working files) were stripped. Source code, `LICENSE`, `requirements.txt`, original `README` (renamed to `README-source.md`), and small assets were preserved.

| Directory | Source repo | Entry point | UCX module | Phase | Size |
|---|---|---|---|---|---|
| [`videocrush/`](videocrush/) | `~/repos/VideoCrush/` | `video_compressor.py` | Compressor | v2.1 | 1.4 MB |
| [`clipforge/`](clipforge/) | `~/repos/ClipForge/` | `clipforge.py` | Editor | v2.1 | 270 KB |
| [`streamkeep/`](streamkeep/) | `~/repos/StreamKeep/` | `StreamKeep.py` | Downloader | v2.1 | 3.2 MB |
| [`recordcast/`](recordcast/) | first-party UCX shim | `sidecar.py` | Recorder | v2.1 | under 100 KB |
| [`alphacut/`](alphacut/) | `~/repos/AlphaCut/` | `AlphaCut.py` | Toolbox > Background Remover | v2.2 | 206 KB |
| [`videosubtitleremover/`](videosubtitleremover/) | `~/repos/VideoSubtitleRemover/` | `VideoSubtitleRemover.py` | Toolbox > Subtitle Remover | v2.2 | 1.8 MB |
| [`lipsight/`](lipsight/) | `~/repos/LipSight/` | `LipSight.py` | Toolbox > Lip Reading | v2.2 | 1.3 MB |
| [`vertigo/`](vertigo/) | `~/repos/Vertigo/` | `vertigo.py` | Toolbox > Auto Reframe | v2.3 | 1.2 MB |
| [`framesnap/`](framesnap/) | `~/repos/FrameSnap/` | `framesnap.py` | Toolbox > Frame Snapshot | v2.3 | 642 KB |
| [`gifstudio/`](gifstudio/) | `~/repos/GifStudio/` | `index.html` (WebView2) | Toolbox > GIF Maker | v2.3 | 1.1 MB |
| [`heicshift/`](heicshift/) | `~/repos/HEICShift/` | `heicshift.py` | Toolbox > Image Converter | v2.3 | 1.3 MB |

**Total ported: ~12.4 MB of source.**

## Subprojects deliberately not ported

| Repo | Reason |
|---|---|
| `MediaForge` | Superseded — UCX's native FFmpeg strategy covers identical functionality |
| `MediaDL` | Userscript + PowerShell server; doesn't fit the sidecar pattern. StreamKeep is the canonical UCX downloader |
| `yt_livestream_downloader` | Subset of StreamKeep functionality |
| `Tunerize` | Audio chiptune synth — niche, not a Wondershare module |
| `Stock-Video-Collector` | Web-scraping niche tool, not a Wondershare module |
| `NovaCut` | Android video editor — separate platform target |
| `OpenCut` | Adobe Premiere Pro CEP plugin — separate target |

## Vendoring contract

Each sidecar tool will ship under `tools/<name>/` with:

```
tools/<name>/
  <entry>.py / index.html  # main entry point (now present)
  sidecar.py               # NDJSON CLI shim — added at the integration phase
  build.ps1                # PyInstaller freezer — added at the integration phase
  <name>.exe               # frozen binary — produced by build.ps1, gitignored
  README.md                # UCX-side sidecar contract (now present)
  README-source.md         # original project README (now present)
  LICENSE                  # source-tool license retained
  requirements.txt         # Python deps where applicable
  models/                  # any AI/ML weights (downloaded on first use, gitignored)
```

The C# orchestrator looks up the binary by walking up from `AppContext.BaseDirectory` and falling back to `%LocalAppData%\UniversalConverterX\tools`.

## NDJSON CLI contract

Each sidecar shim must emit one JSON object per line on stdout:

```json
{"event": "progress", "percent": 42.5, "stage": "encoding", "eta_seconds": 12}
{"event": "log", "level": "info", "message": "Started encoding"}
{"event": "complete", "output": "C:\\path\\to\\result.mp4", "size_bytes": 12345678}
{"event": "error", "code": "missing_dep", "message": "ffmpeg not found"}
```

This matches UCX's existing `IConversionOrchestrator` progress contract and minimizes glue code per tool.

## What lands per phase

- **v2.1** — `videocrush/sidecar.py` + `clipforge/sidecar.py` + `streamkeep/sidecar.py` + `recordcast/sidecar.py` + freeze scripts; UI tabs (Compressor / Editor / Downloader / Recorder) wired to invoke them.
- **v2.2** — `alphacut/sidecar.py` + `videosubtitleremover/sidecar.py` + `lipsight/sidecar.py`; shared ONNX model cache at `tools/_models/` (gitignored).
- **v2.3** — `vertigo/sidecar.py` + `framesnap/sidecar.py` + `heicshift/` defaults absorbed into UCX FFmpeg/libvips strategies; `gifstudio/index.html` hosted via WebView2 (no shim needed).
- **v2.21+** - first-party FFmpeg shims such as `audio-compressor/sidecar.py`, `voice-changer/sidecar.py`, `slideshow/sidecar.py`, and `video-face-enhance/sidecar.py` use the same NDJSON runner for local media processing workflows.
