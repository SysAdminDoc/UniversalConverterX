# UniversalConverter X

The all-in-one media tool for Windows — convert, compress, edit, download, record, and 25+ AI-powered tools, all running locally.

A free, open-source alternative to Wondershare UniConverter and similar paid suites. No subscriptions, no cloud processing, no telemetry.

![Version](https://img.shields.io/badge/version-2.28.0-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

## Modules

- **Converter** — 1000+ formats via FFmpeg, ImageMagick, Pandoc, libvips, libjxl, libheif, Inkscape, Calibre, Assimp, Ghostscript, LibreOffice, resvg, Potrace.
- **Compressor** — web/archive profiles, cap-safe social size targets, custom maximum-size two-pass encoding, and VMAF-targeted smart compression with verified quality scores.
- **APV camera masters** — detect RFC 9924 raw APV and convert locally to H.265 10-bit, ProRes 422 HQ, or H.264 with the bundled FFmpeg build.
- **Preservation and production** — curated FFV1+FLAC archival, ProRes 422, and DNxHR HQ workflows with family filters in the preset browser.
- **Video Editor** — trim, crop, rotate, upscale, filter, audio adjust, batch.
- **Video Enhancer** — portable Real-ESRGAN export, optional Anime4K v4 GLSL chains through mpv, a local Windows App SDK 2.2 VideoScaler capability check, and optional SeedVR2 3B FP8 diffusion restoration for CUDA GPUs.
- **UltraHDR gain maps** — preserve ISO 21496-1 metadata during JPEG round-trips, convert UltraHDR JPEG to gain-map AVIF, or create AVIF gain maps from SDR/HDR image pairs through pinned libvips 8.18.2 and libavif 1.4.2 runtimes.
- **Lossless display metadata** — H.264/H.265 edge-crop metadata and packet-preserving aspect-ratio overrides in the Editor and ClipForge presets.
- **Downloader** — 1000+ sites: YouTube, Twitch, Kick, Rumble, Vimeo, X, Facebook, podcasts, direct URLs.
- **Recorder** — screen, webcam, system audio, microphone.
- **Toolbox** — 40+ specialized tools across Image, Video, AI, Audio, Documents, Disc, and Other categories.

## Toolbox highlights

| Category | Tools |
|---|---|
| **Image** | Image Converter · GIF Maker · Image Upscaler (AI) · AI Portrait · Slideshow Maker · Metadata Editor |
| **Video** | Auto Highlight · Auto Reframe (AI) · Auto Crop (AI) · Watermark Editor · Frame Snapshot · Scene Detection · Timeline Preview · Track Manager |
| **AI** | Background Remover · Subtitle Remover · Auto Subtitle · Vocal Remover · Voice Changer · Text-to-Speech · Speech-to-Text · Photo Restoration · Lip Reading |
| **Audio** | Audio Converter · Audio Compressor · Noise Remover (AI) |
| **Documents** | Document Converter (LibreOffice) · Archive Tool (7-Zip) · PDF Tools (pikepdf) · Subtitle Converter (pysubs2) · Font Converter (fonttools) · eBook Converter (Calibre) · OCR (Tesseract) |
| **Disc** | Data CD/DVD imaging and burn · DVD-Video authoring · DVD Rip · DVD Copy (planned) |
| **Other** | Format Inspector · Chapter Marks · Watch Folders · History · VMAF Quality |

## Architecture

UCX is a C# / .NET 10 / WinUI 3 shell that hosts the Converter natively and orchestrates specialized engines as sidecar processes. Each sidecar lives under `tools/<name>/` and follows the NDJSON CLI contract documented in [`tools/README.md`](tools/README.md).

Representative sidecar engines: VideoCrush, ClipForge, StreamKeep, AlphaCut, VideoSubtitleRemover, LipSight, Vertigo, FrameSnap, GifStudio, HEICShift, Audio Compressor, Voice Changer, Slideshow Maker, and Video Face Enhance.

## Features

- Right-Click Context Menu — convert files directly from Windows Explorer.
- Local Processing — all conversions happen on your machine. No telemetry.
- Progress Tracking — real-time progress with speed and ETA, NDJSON sidecar contract.
- Batch Conversion — convert and process multiple files at once.
- Image Quality Targeting — automatically find the best JPEG, WebP, AVIF, HEIC, or JXL quality for a size, PSNR, or local SSIMULACRA2 target.
- Batch Image Editing — apply named looks, colour/tone controls, blur, grain, vignette, tint, and borders while retaining compatible alpha and multi-frame output.
- Face Blur Privacy Filter — detect and irreversibly obscure frontal faces in every video frame with an offline, fail-closed OpenCV pipeline.
- Auto Highlight — rank scene-change and visible-motion peaks locally, review clip windows, and export an audio-preserving reel, CMX 3600 EDL, or OpenTimelineIO timeline.
- Exact Chapter Editor — import, edit, delete, and export MKV/MP4/MOV markers while retaining untouched PTS values; verified stream-copy muxing uses MKVToolNix 97+ for MKV and FFmpeg for MP4/MOV.
- Conversion History — search/export past jobs and restore exact Converter settings for a re-run.
- Queue Automation — notify, sleep, safely schedule shutdown, or run a hidden PowerShell hook with a JSON summary.
- Watch Folders — process stable new or renamed files automatically with duplicate and self-output loop protection.
- Modern UI — WinUI 3 with dark theme and Mica effects.
- CLI Support — full command-line interface for automation (`ucx`).

## Supported Converters

| Converter | Input Formats | Output Formats | Category | Priority |
|-----------|--------------|----------------|----------|----------|
| FFmpeg | 472+ | 199+ | Video, Audio | 100 |
| resvg | 1 (SVG) | 4+ | SVG Rendering | 97 |
| libheif | 4+ | 3+ | HEIC/HEIF | 96 |
| Inkscape | 10+ | 17+ | Vector Graphics | 95 |
| libjxl | 2+ | 3+ | JPEG XL | 94 |
| libvips | 40+ | 25+ | High-Perf Images | 92 |
| ImageMagick | 245+ | 183+ | General Images | 90 |
| Potrace | 5+ | 6+ | Raster to Vector | 88 |
| Calibre | 26+ | 19+ | E-books | 85 |
| Assimp | 40+ | 25+ | 3D Models | 85 |
| Pandoc | 43+ | 65+ | Documents | 80 |
| Ghostscript | 4+ | 8+ | PDF Processing | 75 |
| LibreOffice | 41+ | 22+ | Office Docs | 70 |

## Installation

### Requirements

- Windows 10 21H2+ or Windows 11
- .NET 10 Runtime
- Additional converter tools as needed (the Windows installer includes FFmpeg 8.1.2)
- DVD-Video authoring requires `dvdauthor` on `PATH` or configured through `UCX_DVDAUTHOR`; data CD/DVD imaging and burning use Windows IMAPI2 without it
- Gain-map presets require the opt-in pinned runtime (`gainmap download-runtime --accept-licenses`); the manifest records third-party licenses, immutable URLs, sizes, and SHA-256 hashes

### Quick Start

1. Install the portable release with `winget install SysAdminDoc.UniversalConverterX`, or download and extract the unsigned portable ZIP from the latest release.
2. Launch `UniversalConverterX.exe` for the desktop workspace or `ucx.exe` for automation.
3. Install any additional converter tools you need (or use `ucx tools download`).
4. Start converting!

The release also includes an intentionally unsigned MSIX for managed sideload environments that choose to apply their own disposable local sideload key. The portable ZIP needs no certificate and is the artifact used by WinGet.

## CLI Usage

```bash
# Convert a single file
ucx convert video.mp4 -o mp3

# Convert multiple files
ucx convert *.png -o webp -q high

# Export per-file status, sizes, timing, and warnings as JSON or CSV
ucx convert *.mov -o mp4 --report batch-report.json

# Move originals to an archive folder after verified output is created
ucx convert *.mov -o mp4 --source-action move --source-archive _converted-sources

# List supported formats
ucx list formats

# Check installed tools
ucx tools check

# Show file info
ucx info document.pdf
```

### Commands

| Command | Description |
|---------|-------------|
| `convert` | Convert one or more files |
| `list` | List formats, converters, or categories |
| `info` | Show information about a file |
| `config` | View or modify configuration |
| `tools` | Manage converter tools |

### Convert Options

```
-o, --output <FORMAT>     Output format (required)
-d, --directory <PATH>    Output directory
-q, --quality <LEVEL>     Quality: lowest, low, medium, high, highest, lossless
-f, --force               Overwrite existing files
-p, --parallel <COUNT>    Maximum parallel conversions
--converter <ID>          Force a specific converter
--hw-accel                Enable hardware acceleration
--source-action <ACTION>  After success: keep, move, or delete the source
--source-archive <PATH>   Archive folder for --source-action move
--report <PATH>           Write a per-file .json or .csv batch report
```

The History page can also export the current filtered history view as the same JSON or CSV report schema.

## Project planning

- [ROADMAP.md](ROADMAP.md) — active roadmap (actionable open work only).
- [CHANGELOG.md](CHANGELOG.md) — shipped work per release.
- [docs/research/](docs/research/) — audit and research evidence.

## Project Structure

```
UniversalConverterX/
├── src/
│   ├── UniversalConverterX.Core/          # Core conversion engine
│   │   ├── Interfaces/                    # Core interfaces
│   │   ├── Models/                        # Data models
│   │   ├── Converters/                    # 13 strategy implementations
│   │   ├── Services/                      # Orchestrator, ToolManager, ToolDownloader
│   │   ├── Configuration/                 # Options
│   │   └── Detection/                     # Magic bytes format detection
│   ├── UniversalConverterX.Console/       # CLI application
│   │   └── Commands/                      # CLI commands
│   ├── UniversalConverterX.UI/            # WinUI 3 application
│   │   ├── Views/                         # XAML views
│   │   ├── ViewModels/                    # MVVM ViewModels
│   │   └── Services/                      # UI services
│   └── UniversalConverterX.ShellExtension/ # Windows Explorer integration
├── tests/
│   └── UniversalConverterX.Core.Tests/    # Unit tests
├── installer/
│   ├── msix/                              # MSIX package manifest
│   └── wix/                               # WiX MSI installer
└── tools/
    └── bin/                               # CLI tool binaries
```

## Building from Source

### Prerequisites

- .NET 10 SDK
- Windows 10 version 1809 or newer for the WinUI project; Windows SDK and WinUI build tools restore from NuGet

### Build

```bash
# Build the full Windows solution
.\build.ps1 -Target Build -Configuration Release

# Run the focused core test suite
.\build.ps1 -Target Test -Configuration Release

# SDK-native builds can also use dotnet directly
dotnet build src/UniversalConverterX.sln -c Release -p:Platform=x64
dotnet build src/UniversalConverterX.Console/UniversalConverterX.Console.csproj -c Release
```

### Publish

```bash
# Publish CLI and WinUI output
.\build.ps1 -Target Publish -Configuration Release
```

## Architecture

### Strategy Pattern

Each converter tool implements `IConverterStrategy`:

```csharp
public interface IConverterStrategy
{
    string Id { get; }
    string Name { get; }
    int Priority { get; }
    bool CanConvert(FileFormat source, FileFormat target);
    Task<ConversionResult> ConvertAsync(ConversionJob job, ...);
}
```

### Orchestrator

The `ConversionOrchestrator` routes conversions to the best available strategy:

1. Detects input format (magic bytes + extension)
2. Finds converters supporting the conversion
3. Selects highest priority converter
4. Executes conversion with progress tracking

## Configuration

Configuration is stored in `%APPDATA%\UniversalConverterX\config.json`:

```json
{
  "ToolsBasePath": "C:\\Tools\\UniversalConverterX",
  "MaxConcurrentConversions": 4,
  "EnableHardwareAcceleration": true,
  "PreserveMetadata": true,
  "DefaultQuality": "High"
}
```

## Installing Converter Tools

The Windows installer carries a pinned FFmpeg 8.1.2 build. Use **Settings > Converter Tools** or `ucx tools download <tool>` for supported portable tools and updates. UCX installs only SHA-256 verified downloads and keeps replaced binaries under `tools/rollback/<tool>/`.

Converter exposes generated FFmpeg argument templates in its Advanced panel. Command editing is off by default; enable it under **Settings > Advanced** to edit a batch-safe `{input}`/`{output}` template or review exact commands generated inside sidecars before they run. UCX never sends edited text through a command shell and blocks shell metacharacters introduced by an edit.

### Third-party sidecar plugins

Drop each plugin into `%LOCALAPPDATA%\UniversalConverterX\plugins\<id>\`. A plugin remains quarantined until its complete directory hash is approved under **Settings > Trusted Plugins**; changed files are disabled automatically, and links/reparse points are rejected. Trusted presets appear in Presets and as one Toolbox tile per plugin.

Each directory needs a `manifest.json`, its declared executable, and at least one preset:

```json
{
  "schemaVersion": 1,
  "id": "example-plugin",
  "name": "Example Plugin",
  "version": "1.0.0",
  "description": "Local example conversion workflow",
  "engine": "example-plugin",
  "executable": "example-plugin.exe",
  "presets": ["presets/example.preset.xml"]
}
```

The directory name, `id`, and `engine` must match. Plugin preset files use the same validated `.preset.xml` schema as built-in workflows.

Subtitle Studio runs a local Whisper → optional Helsinki OPUS-MT ONNX pipeline, opens the timecoded cues for text/timing edits, and exports SRT, VTT, or ASS. Video sources can also receive a hard-coded caption copy after the edited subtitle file is saved.

Speech-to-Text also offers NVIDIA Parakeet TDT 0.6B v3 for CUDA systems and its 25 supported European languages. Its pinned CC-BY-4.0 model pack is never fetched implicitly: select Parakeet, review the license, and use the explicit model-download action before transcribing. CPU-only systems can continue using faster-whisper or whisper.cpp.

Video Enhancer keeps Real-ESRGAN as its portable default and adds Anime4K v4.0.1 as an optional 2× GLSL backend through mpv. Modes A, B, and C cover line restoration, soft restoration, and denoise; the pinned approximately 0.8 MB MIT shader pack requires explicit consent and SHA-256 verification, and all rendering remains local. SeedVR2 3B FP8 remains available as an optional diffusion-restoration engine on NVIDIA CUDA systems with at least 10 GB VRAM (12 GB or more recommended). Select SeedVR2, review the Apache-2.0 terms, and explicitly download the pinned approximately 3.9 GB runtime/model pack. UCX verifies immutable revisions and SHA-256 hashes, blocks cleanly when optional packs or runtimes are unavailable, and disables downloads during restoration.

### ONNX Runtime compatibility

ONNX Runtime 1.27 deprecates CUDA 12 and makes CUDA package selection explicit. UCX therefore advances its CPU-only RapidOCR path while holding CUDA-capable engines on the last validated pre-transition line:

| Sidecar | ORT requirement | Execution path | Migration state |
| --- | --- | --- | --- |
| `videosubtitleremover` | `>=1.27,<1.28` | RapidOCR CPU; CUDA work uses PyTorch/Paddle | 1.27 enabled |
| `alphacut` | `>=1.26,<1.27` | Optional ONNX CUDA 12 | Hold for CUDA 13 smoke |
| `stemkit` | `>=1.26,<1.27` | MDX-Net via optional ONNX CUDA 12 | Hold for CUDA 13 smoke |
| `translatekit` | `>=1.26,<1.27` | OPUS-MT via optional ONNX CUDA 12 | Hold for CUDA 13 smoke |

Preset health reports the held CUDA transition before launch. Do not override those upper bounds unless the matching CUDA 13 ONNX Runtime package and the complete sidecar stack have been validated together.

For full YouTube format extraction, install both the managed yt-dlp channel and Deno runtime. The Downloader health card reports their current status and can install or update both:

```powershell
ucx tools download yt-dlp
ucx tools download deno
```

### Windows (winget)

```powershell
winget install Gyan.FFmpeg
winget install ImageMagick.ImageMagick
winget install JohnMacFarlane.Pandoc
winget install calibre.calibre
winget install TheDocumentFoundation.LibreOffice
```

### Windows (Chocolatey)

```powershell
choco install ffmpeg imagemagick pandoc calibre libreoffice
```

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please read CONTRIBUTING.md for guidelines.

## Acknowledgments

- [FFmpeg](https://ffmpeg.org/) - Video/audio processing
- [ImageMagick](https://imagemagick.org/) - Image processing
- [Pandoc](https://pandoc.org/) - Document conversion
- [Calibre](https://calibre-ebook.com/) - E-book conversion
- [LibreOffice](https://www.libreoffice.org/) - Office documents
- [Inkscape](https://inkscape.org/) - Vector graphics
- [Ghostscript](https://www.ghostscript.com/) - PDF processing
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Media extraction and download support
- [Deno](https://deno.com/) - Sandboxed JavaScript runtime for YouTube extraction
- [libvips](https://www.libvips.org/) - High-performance image processing
- [libheif](https://github.com/strukturag/libheif) - HEIC/HEIF support
- [libjxl](https://github.com/libjxl/libjxl) - JPEG XL support
- [resvg](https://github.com/RazrFalcon/resvg) - SVG rendering
- [Potrace](http://potrace.sourceforge.net/) - Raster to vector tracing
- [Assimp](https://www.assimp.org/) - 3D model import
