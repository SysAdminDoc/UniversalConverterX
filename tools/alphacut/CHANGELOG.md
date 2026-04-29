# Changelog

All notable changes to AlphaCut will be documented in this file.

## [v1.2.0] - 2025-07-27

### Added
- **Animated GIF export** — new `gif_anim` output format; 256-colour palette with binary transparency mask, `disposal=2` for proper background restoration. Optimal for web compatibility and emoji-like short loops.
- **Chroma-key auto-detection** — `detect_chroma_background()` samples 3 video frames, checks corner patches for green/blue dominance, returns detection result with similarity/blend parameters.
- **ChromaDetectWorker** — background thread that runs detection without blocking the GUI; emits result signal on completion.
- **ChromaKeyWorker** — FFmpeg-based chroma-key implementation with real-time progress parsing; supports mp4, webm, prores, matte, png_seq; 10× faster than AI for solid-colour backgrounds.
- **Chroma-key UI** — hidden checkbox `Use chroma-key (faster, better edges)` shown only after detection confirms green/blue screen. Hint label displays detected color.
- **Batch thumbnail previews** — `ThumbnailLoader` extracts 80px thumbnails from batch videos in background; integrated into JobTable as column 0.
- **JobTable redesign** — 5-column table: thumbnail, file, status, progress, output. Thumbnail column displays frame at 0.5s with 48px height.
- **CLI chroma-key support** — `--chroma-key` flag; auto-detection runs in CLI mode; if detected, uses `ChromaKeyWorker` instead of AI.

### Fixed
- Fixed docstring version (was v1.0.1, now v1.2.0).
- Fixed audio exclusion logic to include `gif_anim`.
- Updated all 4 `ext_map` dicts to include `'gif_anim': '.gif'`.
- Updated `estimate_output_size` bpf to include GIF estimate (0.06× px).

### Changed
- Version bumped to `1.2.0` across all files.
- Output formats list: 6 → 7 formats (added GIF).
- Batch job table: 4 → 5 columns (thumbnail column added).
- README updated to document chroma-key fallback feature.

---

## [v1.1.0] - 2025-07-19

### Added
- **Animated WebP export** — new `webp_anim` output format; pure-Python PIL encode, no FFmpeg dependency, RGBA transparency preserved, quality slider maps directly to WebP quality. Best for short loops and web product overlays.
- **SHA-256 model integrity verification** — `_compute_sha256` computes a hash after download and stores a `.sha256` sidecar. On subsequent loads the hash is re-verified; tampered or corrupted models are automatically re-downloaded.
- **requirements.txt** — pinned dependency list for `pip install -r requirements.txt` installs.
- **PyInstaller CI/CD** (`.github/workflows/build.yml`) — `workflow_dispatch`-triggered matrix build for Windows (`.exe`), Linux, and macOS; GitHub Release created automatically with all three artifacts.

### Fixed
- CLI `--format` default corrected from `prores` to `mp4` (matches argparser default).
- CLI `--format` help text now lists all formats including `mp4` and `webp_anim`.
- `_delete_model` now removes the corresponding `.sha256` sidecar alongside the model file.
- Audio track inclusion logic now correctly excludes `webp_anim` (PIL encode has no audio mux).

### Changed
- Version bumped to `1.1.0` across all files.

---

## [v1.0.0] - 2025-07-01

### Added
- Initial release.
- 8 ONNX segmentation models: U2Net variants, ISNet, BiRefNet.
- Output formats: MP4 H.264, WebM VP9+Alpha, ProRes 4444+Alpha, grayscale matte, PNG sequence, green screen composite.
- Pipelined reader/infer/saver threads for higher throughput.
- Frame skip with mask reuse (up to 10× speedup).
- Benchmark mode (10-frame speed estimation).
- Resume interrupted jobs (SHA-256 WIP dirs, progress JSON every 50 frames).
- Background replacement: solid color or image file.
- Color spill suppression, shadow preservation, mask inversion.
- Batch queue with per-file status table.
- CLI (`argparse`) for headless operation.
- Auto-named output patterns (`{name}`, `{model}`, `{format}`, `{date}`).
- Export presets (JSON), recent files, settings persistence.
- Before/after split-view with draggable divider.
- System tray integration, toast notifications.
- Update checker (GitHub releases API).
- Model Manager dialog (view/delete cached ONNX files).
- PyQt6 dark theme, auto-installs all Python dependencies at startup.

