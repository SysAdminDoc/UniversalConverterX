# HEICShift Roadmap

Universal image batch converter. 12+ input formats to JPEG/PNG/WebP/AVIF/TIFF/JXL with metadata and color-profile fidelity. Roadmap tracks format coverage, pipeline hardening, and pro-grade output controls.

## Planned Features

### Format & Pipeline
- **HEIC HDR gain-map round-trip** — preserve ISO 21496-1 gain maps when target is JXL; warn and strip when target is JPEG/PNG
- **Live Photo companion** — detect `.HEIC` + sibling `.MOV` pairs, optionally copy the motion file next to the converted still
- **Apple ProRAW (DNG) demosaic path** — dedicated Adobe DNG pipeline separate from rawpy, keeps embedded JPEG preview as fallback
- **Animated HEIC / motion-JPEG / APNG** — multi-frame decode, export as APNG/WebP/AVIF animation or per-frame PNG sequence
- **Output validator** — optional `ffprobe`/`dcraw`/Pillow cross-check pass before accepting output
- **Streaming TIFF/DNG read** — tile-wise read for >500MP scans, avoid full-buffer load
- **Smart chunking for huge batches** — break 10k+ file runs into persisted checkpoints, resume after crash/reboot

### Color & Metadata
- **BT.2020 / PQ HDR aware** — detect HDR color spaces, offer tone-map to sRGB with curve choice (BT.2390, Hable, Reinhard)
- **ExifTool side-car pass** — optional post-pass via bundled ExifTool to carry EXIF from RAW → JPEG without rewrite loss
- **XMP sidecar mode** — emit `.xmp` next to stripped output so metadata travels separately
- **ICC profile override** — embed a chosen profile (sRGB v4, Display P3, Rec.2020) instead of passthrough

### CLI & Automation
- **Watch mode** — `--watch <dir>` monitors source and converts new files on arrival (with debounce + lockfiles)
- **Presets as JSON** — dump GUI presets to `~/.heicshift/presets/*.json`, load via `--preset name` in CLI
- **Exit-code matrix** — structured exit codes for "partial format unavailable" vs "IO error" for scripting
- **JSON report mode** — `--report out.json` emits machine-readable per-file stats (current CSV is human-first)

### GUI / UX
- **Before/after preview pane** — thumbnail diff with SSIM score per file
- **Quality ladder view** — sample file encoded at 60/75/85/92/95 side-by-side with file-size readout
- **Per-file override** — right-click a row to change format/quality just for that entry
- **Drag output bar** — drag converted files out of the log to Explorer/Finder

## Competitive Research
- **ImageMagick / GraphicsMagick** — king of CLI breadth, but defaults strip ICC, lossy chroma, no GUI. Beat on defaults and workflow, not format count.
- **XnConvert** — strong cross-platform batch GUI with 500+ formats, but UI is dated and AVIF/JXL lag behind native codecs. HEICShift should out-perform on modern codecs + speed.
- **libvips / sharp** — fastest pipeline in the Node/C ecosystem; worth evaluating a `--backend vips` option for huge batches
- **Squoosh** (Google) — per-image tuning with live preview; steal the quality-ladder UX for batch comparison

## Nice-to-Haves
- Web-worker-style parallel decode via subprocess pool to sidestep Python GIL
- Face-aware quality: detect faces, hold higher quality in face regions (JPEG ROI, AVIF film-grain off)
- Perceptual quality target: `--target-ssim 0.98` binary-searches quality instead of a fixed KB goal
- Drag-to-dock mini-window mode for quick single-file conversions
- Plugin system: drop `.py` into `~/.heicshift/plugins/` to register a new decoder or post-processor
- Self-updater checking GitHub releases (opt-in)

## Open-Source Research (Round 2)

### Related OSS Projects
- **NeverMendel/heif-convert** — https://github.com/NeverMendel/heif-convert — Python multi-platform CLI (pip-installable) converting HEIF to jpg/png/webp/gif/tiff/bmp/ico
- **dragonGR/PyHEIC2JPG** — https://github.com/dragonGR/PyHEIC2JPG — parallel workers, recursive directory preservation, EXIF preservation, quality control, perf statistics
- **saschiwy/HeicConverter** — https://github.com/saschiwy/HeicConverter — minimal CLI, recursive folder walk
- **borelg/HEIC2jpg** — https://github.com/borelg/HEIC2jpg — GPL, batch, quality preservation
- **Jesikurr/Universal-Image-Converter** — https://github.com/Jesikurr/Universal-Image-Converter — Tkinter GUI, drag-and-drop, batch, dark/light mode, MIT
- **versoindustries/HEIC-Converter** — https://github.com/versoindustries/HEIC-Converter-Effortlessly-Convert-HEIC-to-JPG-PNG-or-WEBP — PyQt5, multi-processing, cross-platform installer
- **pillow-heif** — https://github.com/bigcat88/pillow_heif — the underlying pyheif/pillow decoder; track releases for libheif bumps
- **Openize.HEIC** — https://github.com/Openize/Openize.HEIC — ISO/IEC 23008-12 decoder in C#; reference for non-Python hosts
- **ImageMagick** — https://github.com/ImageMagick/ImageMagick — the industry fallback; useful for unusual formats HEICShift doesn't natively handle

### Features to Borrow
- Parallel workers with configurable count and per-core progress (PyHEIC2JPG)
- Recursive directory structure preservation in output tree (PyHEIC2JPG, saschiwy)
- EXIF + ICC profile + XMP metadata passthrough by default, with a "strip metadata" toggle (PyHEIC2JPG, pillow-heif)
- Drag-and-drop on the GUI plus "right-click > Convert with HEICShift" shell extension (Universal-Image-Converter and Windows common pattern)
- Per-target quality sliders (JPEG/WebP/AVIF) with "match-source" option that picks quality based on input bitrate (community pattern)
- Output naming template: `{stem}_{width}x{height}.{ext}` with tokens (ImageMagick -define filename:)
- Live format switch: HEIC, HEIF, AVIF, WebP-animation, JPEG-XL, JPEG 2000, TIFF pyramids (pillow-heif + OpenJPEG + libjxl)
- ImageMagick fallback for rare codec paths (MIFF, XCF, PSD) via a "use ImageMagick if available" flag
- CLI/GUI parity: every GUI action has a `--flag` equivalent; GUI actions log the equivalent CLI command at the bottom (UX that power users love)
- Batch "pre-check" mode: scan, report unsupported or too-large files, estimate output size before running (HEICShift UX pattern)
- Auto-detect Live Photo pairs (.heic + .mov) and keep them grouped in output (iPhone-specific, common user request)

### Patterns & Architectures Worth Studying
- pillow-heif as the decoder boundary, Pillow as the image abstraction — same pattern as PyHEIC2JPG; shields the app from libheif ABI changes (pillow-heif)
- Worker-pool via `concurrent.futures.ProcessPoolExecutor` with `multiprocessing.freeze_support()` as the first line in the entry script (project rule; PyInstaller fork-bomb rule)
- Plugin pattern: every output format is a `Converter` class that exposes `supports(input_mime)` and `convert(in_path, out_path, options)` — add formats without touching the core (Universal-Image-Converter's natural extension point)
- MIT + pyproject.toml + `pip install -e .` developer setup so contributors can hack on the CLI without touching the GUI (NeverMendel)
- Progress streaming via stdout JSONL for integration into other pipelines (GUI reads same stream) (modern CLI design)

## Implementation Deep Dive (Round 3)

### Reference Implementations to Study
- **bigcat88/pillow_heif `workaround-orientation.rst`** — https://github.com/bigcat88/pillow_heif/blob/master/docs/workaround-orientation.rst — canonical description of dual-orientation storage (irot property vs. EXIF tag) and why `set_orientation()` is mandatory.
- **bigcat88/pillow_heif `CHANGELOG.md`** — https://github.com/bigcat88/pillow_heif/blob/master/CHANGELOG.md — v1.14.0 changed encoding path (writes orientation to HEIF header instead of pre-rotating pixels); pin carefully.
- **bigcat88/pillow_heif `examples/`** — https://github.com/bigcat88/pillow_heif/tree/master/examples — `add_from_pillow()` and batch encode patterns.
- **python-pillow/Pillow Issue #4537** — https://github.com/python-pillow/Pillow/issues/4537 — EXIF orientation not rewritten on save for PNG; regression-test when HEIC→PNG pipeline is used.
- **python-pillow/Pillow `ImageOps.py` `exif_transpose`** — https://github.com/python-pillow/Pillow/blob/main/src/PIL/ImageOps.py — bake rotation into pixels and clear tag; the safe-default for any cross-format conversion.
- **strukturag/libheif `examples/heif-convert`** — https://github.com/strukturag/libheif/tree/master/examples — C-level reference for tile/derived-image handling; relevant for iPhone Live Photo dual-image HEIC.
- **bigcat88/pillow_heif `thumbnails` example** — https://pillow-heif.readthedocs.io/en/latest/pillow-plugin.html — shows iterating frames for multi-image HEIC (burst mode).

### Known Pitfalls from Similar Projects
- HEIC rotated twice on output — using `open_heif()` (low-level) skips automatic orientation reset. Always use `register_heif_opener()` + `Image.open()`, or call `pillow_heif.set_orientation()` manually (workaround-orientation.rst).
- macOS Preview < Sonoma rotates based on EXIF tag while libheif rotates via irot — strip EXIF `Orientation` (0x0112) to `1` after baking pixel rotation to avoid double-rotation on older macOS (workaround-orientation.rst).
- `ImageOps.exif_transpose()` returns a NEW Image — assigning result back is required or rotation is dropped (Pillow docs).
- PyInstaller misses the `pillow_heif._pillow_heif` C extension — add `--collect-all pillow_heif` or binary is missing at runtime.
- JPEG save with `exif=img.info['exif']` re-embeds the old orientation after you've baked pixels — strip the tag first via `exif.remove(0x0112)`.
- HEIF with more than one top-level image (Apple Live Photo) — `img.convert('RGB')` silently drops extras; iterate via `ImageSequence.Iterator(img)` to preserve.
- AVIF output requires `pillow-heif` built with libheif ≥ 1.17 AVIF support; Windows wheels from PyPI include it, but Linux musl wheels do not.

### Library Integration Checklist
- `pillow-heif==0.22.0` — https://pypi.org/project/pillow-heif/ — key API: `from pillow_heif import register_heif_opener; register_heif_opener()`. Gotcha: must be called before `Image.open()` on any thread that will read HEIC.
- `Pillow==11.1.0` — pin ≥10.4 for proper CMYK HEIC handling; ≤10.3 corrupts colorspace on save.
- `PyQt6==6.8.0` + `PyQt6-Qt6==6.8.1` — pin matching major/minor or `QStyleHints` import fails.
- `pyexiv2==2.15.3` — optional for metadata preservation (GPS, camera settings) that Pillow drops; gotcha: ships C++ runtime, PyInstaller needs `--collect-binaries pyexiv2`.
- `tqdm==4.67.1` — for CLI progress; wrap with `QThread.sleep(0)` equivalents in GUI to avoid double bars when Qt also shows progress.
- `piexif==1.1.3` — lighter alternative to pyexiv2 for JPEG/TIFF only; cannot write HEIC metadata.
