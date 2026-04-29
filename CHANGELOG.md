# Changelog

All notable changes to UniversalConverterX will be documented in this file.

## [v2.0.0] - 2026-04-29

Major scope expansion: from a context-menu file converter into a full all-in-one media tool — a Wondershare UniConverter alternative.

### Added
- **NavigationView shell** — Wondershare-style left sidebar with Home / Converter / Compressor / Editor / Downloader / Recorder / Toolbox / Account.
- **Home page** — hero, search, quick-launch module tiles, recent files area.
- **Toolbox page** — categorized tile grid with 29 specialized tools across Image, Video, AI, Audio, Disc, and Other.
- **Module shells** — Compressor, Video Editor, Downloader, and Recorder pages with mocked-up final-state UI.
- **Placeholder page** — generic "Coming Soon" landing for tiles whose backing engines arrive in later phases.
- **`tools/` directory — all 10 sidecar engines ported in.** Source code (~12 MB total) for VideoCrush, ClipForge, StreamKeep, AlphaCut, VideoSubtitleRemover, LipSight, Vertigo, FrameSnap, GifStudio, HEICShift now lives under the UCX repo. Build artifacts (`build/`, `dist/`, `__pycache__`, frozen `.exe`s, `.git`, AI working files) were stripped during the port. Each tool retains its `LICENSE`, original README (renamed to `README-source.md`), `requirements.txt`, and small assets.
- Per-tool sidecar README documenting UCX module mapping, integration phase, entry point, and runtime.
- Top-level [`tools/README.md`](tools/README.md) audit table with deliberate skip list (MediaForge, MediaDL, yt_livestream_downloader, Tunerize, Stock-Video-Collector, NovaCut, OpenCut).
- NDJSON sidecar contract documented in `tools/README.md`.

### Changed
- `MainWindow` no longer hosts the Converter UI directly — moved to `Views/Pages/ConverterPage.xaml`.
- App startup window resized to 1280x820 to fit sidebar + content.
- Title bar extended into client area with tall preferred height.
- Version bumped to 2.0.0 across `Directory.Build.props`, all csproj files, app.manifest, WiX, MSIX, build scripts, and SettingsWindow.

## [v1.0.0] - 2026-04

- Added: CI/CD build workflow.
- Added: Initial release with 13 converter backends (FFmpeg, ImageMagick, Pandoc, libvips, libjxl, etc.) covering 1000+ formats.
- Added: Right-click context menu integration via SharpShell.
- Added: CLI (`ucx`) with convert / list / info / config / tools commands.
- Added: WinUI 3 desktop UI with drag-and-drop and batch progress.
