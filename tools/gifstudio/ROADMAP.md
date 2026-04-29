# ROADMAP

Backlog for GifStudio — single-file browser GIF editor. Stays 100% client-side, no backend.

## Planned Features

### Capture / import
- **Screen / tab / window recording** via `getDisplayMedia()` with frame-rate and region
  controls, then convert to GIF in the same session.
- **Webcam source** with MediaRecorder then frame extraction.
- **Video-URL import** for same-origin videos or uploaded local files; seek and grab frame range
  directly.
- **Drag-drop multiple images** to build a GIF from an image sequence (already implied; surface
  as a first-class source).
- **Paste-from-clipboard** image / video blob support (`navigator.clipboard.read()`).

### Editor
- **Text layer with animation** — per-layer keyframes (position, scale, opacity, rotation,
  color). Cross-reference the GifText desktop app's model; port the keyframe UI to web.
- **Sticker/emoji overlay** with Twemoji.
- **Shape primitives** — rectangle, circle, arrow, speech bubble; resizable and keyframable.
- **Onion-skinning** in the editor preview to track moving subjects.
- **Per-frame delay editor** with drag handle on the timeline, not just global playback speed.
- **Reverse / Ping-pong / Boomerang** toggles.
- **Ease-in / ease-out interpolation options** between keyframes.

### Quality / encoding
- **gif.js worker-based encoding** with quality + dither options (Floyd-Steinberg, Bayer, none).
- **Animated WebP / APNG export** alongside GIF (smaller + alpha support).
- **MP4 / WebM export** via MediaRecorder as a lossy alternative for social posting.
- **Palette control** — global vs per-frame palette, custom palette import, 16/64/256-color
  modes.
- **Transparency support** — mask a color as transparent during encode.
- **Max-size target** — iteratively re-encode until output fits under N MB.

### Filters / effects
- **CSS-filter layer** — brightness, contrast, saturation, hue-rotate with live preview.
- **LUT application** via WebGL shader.
- **Motion blur** between frames.
- **Background removal** via `@huggingface/transformers.js` with a MODNet port — runs in-browser.

### UX
- **Session autosave** to IndexedDB; recover on reload.
- **Project file** download (JSON + base64 frames) for resume-later without re-uploading source.
- **Keyboard-free but shortcut-aware** — palette + menu covers everything; optional shortcuts
  (per project rule of no shortcuts in production builds, this is opt-in).
- **Undo / redo stack** with keyboard + toolbar buttons, 50 levels.
- **Dense / comfortable layout toggle**.
- **Additional themes** — Catppuccin Mocha default, GitHub Dark, AMOLED Black, Nord.

### Distribution
- **PWA manifest + service worker** — installable, offline-capable.
- **Share-link generation** — upload optional (user-configured S3 bucket / imgur token), default
  local-only.

## Competitive Research

- **Ezgif** — the dominant browser-based GIF editor. Wider toolset (crop, rotate, optimize,
  split, reverse). GifStudio should match the core editor set and beat ezgif on UX cleanliness
  and local-only processing.
- **Kapwing** — polished web video + GIF editor with AI captions. Differentiator to avoid:
  server-side processing / upload requirement.
- **ScreenToGif (desktop)** — the gold standard for screen→GIF workflows. GifStudio should
  cover the "web equivalent" with tab-capture.
- **Giphy Create** — social-focused. Don't replicate; focus on power-user editing features
  Giphy lacks.
- **VideoToJPG.com / Teamz Converter** — privacy-first WASM tools; same local-only ethos.

## Nice-to-Haves

- **Motion-tracked sticker** — OpenCV.js-based point tracking so a sticker follows a subject
  across frames.
- **AI caption suggestion** using an in-browser speech-to-text on source audio.
- **Automatic thumbnail choice** — detect best frame (least blur / best composition) to use as
  preview thumbnail.
- **Batch mode** — apply the same edits to multiple source videos.
- **Embeddable share page** — after export, generate a standalone HTML page with the GIF + loop
  control the user can host themselves.
- **Plugin hooks** — JS plugin API for community filters/effects.

## Open-Source Research (Round 2)

### Related OSS Projects
- **Gifcurry** — https://github.com/lettier/gifcurry — Haskell GUI+CLI; trim/crop/seek/text overlay with font/rotation/timing + video→GIF pipeline.
- **gif.js** — https://github.com/jnordberg/gif.js — Canonical in-browser GIF encoder; Web Worker pipeline; foundation many browser GIF tools still build on.
- **gifski** — https://github.com/ImageOptim/gifski — Highest-quality GIF encoder (Rust) via pngquant; use via WASM for "export high-quality" button.
- **Kap** — https://github.com/wulkano/Kap — Screen→GIF capture; plugin API; good model for "record-then-edit" flow.
- **Shubhankardubey/Gif-Maker** — https://github.com/Shubhankardubey/Gif-Maker — JS lib using gifshot + getUserMedia; pattern for webcam→GIF.
- **ScreenToGif** — https://github.com/NickeManarin/ScreenToGif — C#/WPF editor; best-of-class per-frame editor (delete / reorder / annotate) worth mirroring.
- **Giffusion** — https://github.com/DN6/giffusion — Stable Diffusion → GIF; AI frame generation for completeness of feature set.
- **awesome-gif** — https://github.com/davisonio/awesome-gif — Curated index.

### Features to Borrow
- Gifski WASM export path for "high quality" mode — dithering + perceptual color reduction beats stock palette quantize.
- Web Worker parallel encoding (`gif.js`) — split frame ranges across workers, merge. Avoids UI jank on 200+ frame GIFs.
- Screen-capture input (`Kap`, `ScreenToGif`) — `getDisplayMedia()` → MediaRecorder → frames → GIF without leaving the app.
- Webcam input (`Shubhankardubey/Gif-Maker`) — `getUserMedia()` direct to frame buffer; 1-click selfie GIF.
- Per-frame editor panel (`ScreenToGif`) — thumbnail strip with drag-reorder, duplicate, delete, set-delay-per-frame.
- Text overlay with keyframe timing (`Gifcurry`) — start-frame + end-frame per text element (see GifText project for algorithm).
- Subtitle import `.srt`/`.vtt` (`Gifcurry`) — auto-place captions at exact frames.

### Patterns & Architectures Worth Studying
- **NEUQUANT palette quantization in a Worker** (`gif.js`): runs entirely off-main-thread; frame data sent as Transferable ArrayBuffer to avoid copy cost.
- **OffscreenCanvas frame pipeline**: decode video frames into `OffscreenCanvas` inside a Worker; chrome/firefox support is solid now. Reference: `gif.js` modernized forks.
- **File System Access API for streaming export**: write directly to disk as frames are encoded via `showSaveFilePicker` + `createWritable`. No more giant Blobs in RAM for long GIFs. Used by newer Kap plugins.
- **Plugin architecture** (`Kap` plugins dir): each encoder / filter / input source is a dynamically loaded module with a small contract — lets contributors add e.g. APNG or WebP export without patching core.
