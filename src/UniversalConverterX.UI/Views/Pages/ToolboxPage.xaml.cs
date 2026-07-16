using System.Collections.ObjectModel;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.Core.Security;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class ToolboxPage : Page
{
    public ObservableCollection<ToolboxTile> ImageTools { get; } = new();
    public ObservableCollection<ToolboxTile> VideoTools { get; } = new();
    public ObservableCollection<ToolboxTile> AiTools { get; } = new();
    public ObservableCollection<ToolboxTile> AudioTools { get; } = new();
    public ObservableCollection<ToolboxTile> DocumentTools { get; } = new();
    public ObservableCollection<ToolboxTile> DiscTools { get; } = new();
    public ObservableCollection<ToolboxTile> OtherTools { get; } = new();
    public ObservableCollection<ToolboxTile> PluginTools { get; } = new();

    public ToolboxPage()
    {
        InitializeComponent();
        SeedTiles();
        SeedPluginTiles();
        // The wave-by-wave SeedTiles() body has accreted over 20+ releases and
        // a few tiles end up with the same RouteKey across waves (e.g.
        // presets:codeformat, presets:audiotag, presets:gisconvert). Dedupe
        // before binding so the user doesn't see two identical cards.
        DedupeTiles(ImageTools);
        DedupeTiles(VideoTools);
        DedupeTiles(AiTools);
        DedupeTiles(AudioTools);
        DedupeTiles(DocumentTools);
        DedupeTiles(DiscTools);
        DedupeTiles(OtherTools);
        DedupeTiles(PluginTools);

        ImageGrid.ItemsSource = ImageTools;
        VideoGrid.ItemsSource = VideoTools;
        AiGrid.ItemsSource = AiTools;
        AudioGrid.ItemsSource = AudioTools;
        DocumentGrid.ItemsSource = DocumentTools;
        DiscGrid.ItemsSource = DiscTools;
        OtherGrid.ItemsSource = OtherTools;
        PluginGrid.ItemsSource = PluginTools;
        PluginSection.Visibility = PluginTools.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private void SeedPluginTiles()
    {
        var trustService = App.Services.GetRequiredService<IPluginTrustService>();
        var blue = (Brush)Application.Current.Resources["AccentBlueBrush"];
        var green = (Brush)Application.Current.Resources["AccentGreenBrush"];
        foreach (var plugin in trustService.Discover()
                     .Where(plugin => plugin.IsTrusted && plugin.PresetPaths.Count > 0))
        {
            PluginTools.Add(new ToolboxTile(
                $"presets:{plugin.Engine}",
                plugin.Name,
                plugin.Description,
                "\uE74C",
                blue,
                "Ready",
                green,
                plugin.IsAi,
                $"{plugin.Name} {plugin.Version}"));
        }
    }

    private static void DedupeTiles(ObservableCollection<ToolboxTile> tiles)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < tiles.Count; i++)
        {
            if (!seen.Add(tiles[i].RouteKey))
            {
                tiles.RemoveAt(i);
                i--;
            }
        }
    }

    private void SeedTiles()
    {
        var blue = (Brush)Application.Current.Resources["AccentBlueBrush"];
        var green = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var orange = (Brush)Application.Current.Resources["AccentOrangeBrush"];
        var yellow = (Brush)Application.Current.Resources["AccentYellowBrush"];
        var red = (Brush)Application.Current.Resources["AccentRedBrush"];

        // Image
        ImageTools.Add(new ToolboxTile("image-converter", "Image Converter", "JPEG, PNG, HEIC, AVIF, WebP, TIFF, BMP", "\uEB9F", blue, "Ready", green, false, "HEICShift"));
        ImageTools.Add(new ToolboxTile("gif-maker", "GIF Maker", "Create GIFs from videos or image sequences", "\uE909", green, "Ready", green, false, "GifStudio"));
        ImageTools.Add(new ToolboxTile("ai-image-enhancer", "Image Upscaler", "Real-ESRGAN super-resolution up to 4× (ncnn-vulkan)", "\uE799", blue, "Ready", green, true, "Real-ESRGAN"));
        ImageTools.Add(new ToolboxTile("ai-portrait", "AI Portrait", "CodeFormer + GFPGAN portrait upscale & restoration with fidelity slider", "\uE77B", blue, "Ready", green, true, "CodeFormer / GFPGAN"));
        ImageTools.Add(new ToolboxTile("slideshow-maker", "Slideshow Maker", "Image folders to MP4/MOV/WebM with Ken Burns motion, transitions, captions, and music", "\uE786", blue, "Ready", green, false, "FFmpeg slideshow"));
        ImageTools.Add(new ToolboxTile("presets:exiftool-meta", "Metadata Editor", "View, edit, and clear EXIF / XMP / IPTC metadata", "\uE8B7", blue, "Ready", green, false, "ExifTool"));

        // Video
        VideoTools.Add(new ToolboxTile("smart-trimmer", "Smart Trimmer", "Detect highlight ranges and trim", "\uE71D", green, "Planned", orange, true, "ClipForge"));
        VideoTools.Add(new ToolboxTile("scene-detect", "Scene Detection", "Find cuts via PySceneDetect; export to CSV / EDL CMX 3600", "\uE71D", blue, "Ready", green, false, "PySceneDetect"));
        VideoTools.Add(new ToolboxTile("timeline-preview", "Timeline Preview", "Thumbnail strip + audio waveform image for any video", "\uE71D", blue, "Ready", green, false, "ClipForge"));
        VideoTools.Add(new ToolboxTile("track-manager", "Track Manager", "Add or remove audio / subtitle / data tracks (no re-encode)", "\uE93F", blue, "Ready", green, false, "ClipForge"));
        VideoTools.Add(new ToolboxTile("auto-reframe", "Auto Reframe", "Convert horizontal to 9:16 / 1:1 / 4:5 (static or smart face track)", "\uE740", blue, "Ready", green, true, "Vertigo"));
        VideoTools.Add(new ToolboxTile("presets:clipforge", "Auto Crop", "Detect crop bounds and apply FFmpeg crop filters", "\uE7A8", blue, "Ready", green, true, "ClipForge"));
        VideoTools.Add(new ToolboxTile("presets:clipforge", "Face Blur", "Detect and irreversibly obscure frontal faces in local video", "\uE8C8", red, "Ready", green, true, "OpenCV + ClipForge"));
        VideoTools.Add(new ToolboxTile("ai-watermark", "Watermark Editor", "Add or remove text and image watermarks", "\uE71B", yellow, "Ready", blue, false, "VideoSubtitleRemover"));
        VideoTools.Add(new ToolboxTile("auto-highlight", "Auto Highlight", "Rank scene-change + motion peaks; export reel / EDL / OTIO", "\uE7C9", blue, "Ready", green, false, "PySceneDetect + FFmpeg"));
        VideoTools.Add(new ToolboxTile("presets:clipforge", "Intro & Outro", "Apply branded intros and outros", "\uE7AD", green, "Ready", green, false, "ClipForge"));
        VideoTools.Add(new ToolboxTile("presets:clipforge", "Lens Correction", "Fix distortion, rolling shutter, and stabilize clips", "\uE71E", blue, "Ready", green, false, "ClipForge"));
        VideoTools.Add(new ToolboxTile("presets:clipforge", "VR Converter", "Equirectangular, fisheye, and 360° projection conversion", "\uE787", blue, "Ready", green, false, "ClipForge"));
        VideoTools.Add(new ToolboxTile("frame-snapshot", "Frame Snapshot", "Extract precise frames as images", "\uE722", blue, "Ready", green, false, "FFmpeg"));
        VideoTools.Add(new ToolboxTile("ai-video-enhancer", "Video Upscaler", "Real-ESRGAN frame-by-frame video super-resolution and cleanup", "\uE799", blue, "Ready", green, true, "Real-ESRGAN"));
        VideoTools.Add(new ToolboxTile("presets:video-face-enhance", "Video Face Enhance", "CodeFormer/GFPGAN frame restoration with source audio passthrough", "\uE77B", blue, "Ready", green, true, "CodeFormer / GFPGAN"));

        // AI
        AiTools.Add(new ToolboxTile("ai-bgremove", "Background Remover", "Remove or replace video background", "\uE91B", green, "Ready", green, true, "AlphaCut"));
        AiTools.Add(new ToolboxTile("presets:videosubtitleremover", "Subtitle Remover", "Remove hard-coded subtitles from selected regions", "\uE93B", blue, "Ready", green, true, "VideoSubtitleRemover"));
        AiTools.Add(new ToolboxTile("ai-subtitle", "Subtitle Studio", "Transcribe, translate, edit, export SRT/VTT/ASS, or burn captions", "\uED1E", blue, "Ready", green, true, "Whisper + OPUS-MT ONNX"));
        AiTools.Add(new ToolboxTile("ai-vocal", "Vocal Remover", "Isolate or remove vocals from audio", "\uE767", red, "Ready", blue, true, "Demucs"));
        AiTools.Add(new ToolboxTile("ai-voice-changer", "Voice Changer", "Local voice style transformation with pitch, timbre, and video remux options", "\uE720", red, "Ready", green, true, "FFmpeg filters"));
        AiTools.Add(new ToolboxTile("ai-tts", "Text-to-Speech", "Generate voiceovers from text — 322 voices, 50+ languages", "\uEC4F", green, "Ready", green, true, "edge-tts"));
        AiTools.Add(new ToolboxTile("ai-photo-restore", "Photo Restoration", "GFPGAN blind face restoration for old / degraded portraits", "\uE77B", green, "Ready", green, true, "GFPGAN"));
        AiTools.Add(new ToolboxTile("ai-stt", "Speech-to-Text", "Transcribe audio to text", "\uE720", green, "Ready", blue, true, "Whisper + Parakeet"));
        AiTools.Add(new ToolboxTile("lip-reading", "Lip Reading", "Visual speech recognition", "\uE909", blue, "Ready", blue, true, "LipSight"));

        // Audio
        AudioTools.Add(new ToolboxTile("audio-converter", "Audio Converter", "MP3, WAV, FLAC, AAC, OGG, Opus · VBR + advanced encoder controls", "\uEC4F", green, "Ready", green, false, "FFmpeg / AudioPro"));
        AudioTools.Add(new ToolboxTile("audio-compressor", "Audio Compressor", "Dynamic-range compression (FFmpeg acompressor) — light/medium/heavy/podcast/broadcast presets", "\uE91F", blue, "Ready", green, false, "FFmpeg acompressor"));
        AudioTools.Add(new ToolboxTile("ai-noise", "Noise Remover", "RNNoise broadband speech denoise (FFmpeg arnndn)", "\uE767", blue, "Ready", green, true, "RNNoise"));

        // Documents
        DocumentTools.Add(new ToolboxTile("document-converter", "Document Converter", "DOCX, PDF, ODT, RTF, XLSX, ODS, CSV, PPTX, EPUB, HTML", "\uE8A5", blue, "Ready", green, false, "LibreOffice"));
        DocumentTools.Add(new ToolboxTile("archive", "Archive Tool", "Pack / unpack 7z, ZIP, TAR, RAR (read), ISO, CAB, MSI", "\uE7B8", orange, "Ready", green, false, "7-Zip"));
        DocumentTools.Add(new ToolboxTile("pdf-tools", "PDF Tools", "Merge / split / rotate / extract / encrypt / compress (pikepdf)", "\uEA90", red, "Ready", green, false, "pikepdf"));
        DocumentTools.Add(new ToolboxTile("subtitle-converter", "Subtitle Converter", "SRT / VTT / ASS / SSA / SUB conversion + retime", "\uE93B", blue, "Ready", green, false, "pysubs2"));
        DocumentTools.Add(new ToolboxTile("font-converter", "Font Converter", "TTF / OTF / WOFF / WOFF2 (fonttools + Brotli)", "\uE8D2", green, "Ready", green, false, "fontTools"));
        DocumentTools.Add(new ToolboxTile("ebook-converter", "eBook Converter", "EPUB / MOBI / AZW3 / PDF / FB2 / DOCX via Calibre", "\uE82D", red, "Ready", green, false, "Calibre"));
        DocumentTools.Add(new ToolboxTile("ocr", "OCR (Text Recognition)", "Tesseract: extract text -> TXT / hOCR / searchable PDF", "\uE8A1", blue, "Ready", green, true, "Tesseract"));
        DocumentTools.Add(new ToolboxTile("presets:pandoc-cli", "Pandoc Documents", "Markdown / RST / DOCX / EPUB / HTML / LaTeX / PDF (60+ formats)", "\uE8A5", green, "Ready", green, false, "Pandoc"));
        DocumentTools.Add(new ToolboxTile("presets:pdfocr", "Scanned PDF OCR", "Add a searchable text layer to scanned PDFs (ocrmypdf)", "\uEA90", blue, "Ready", green, true, "ocrmypdf"));

        // Image RAW
        ImageTools.Add(new ToolboxTile("presets:rawphoto", "RAW Photo Developer", "CR2 / CR3 / NEF / ARW / DNG / RAF -> JPEG / TIFF / PNG (LibRaw)", "\uEB9F", orange, "Ready", green, false, "rawpy + LibRaw"));

        // 3D models -- new section feels overkill for one tile; group under Other.
        OtherTools.Add(new ToolboxTile("presets:meshconvert", "3D Model Converter", "STL / OBJ / PLY / GLB / GLTF / FBX / DAE / 3DS (trimesh)", "\uF158", blue, "Ready", green, false, "trimesh + assimp"));
        OtherTools.Add(new ToolboxTile("presets:gisconvert", "GIS Data Converter", "KML / GPX / GeoJSON / Shapefile / GeoPackage (GDAL ogr2ogr)", "\uE707", green, "Ready", green, false, "GDAL"));
        OtherTools.Add(new ToolboxTile("presets", "Presets Browser", "Browse + run all shipped presets and any custom *.preset.xml", "\uE71D", blue, "Ready", green, false, "UCX"));

        // Disc
        DiscTools.Add(new ToolboxTile("dvd-burn", "DVD Burn", "Burn videos to DVD", "\uE958", red, "Future", yellow, false, null));
        DiscTools.Add(new ToolboxTile("dvd-copy", "DVD Copy", "Copy or backup DVDs", "\uE958", red, "Future", yellow, false, null));
        DiscTools.Add(new ToolboxTile("cd-burner", "CD Burner", "Burn audio CDs", "\uE958", red, "Future", yellow, false, null));

        // Other
        OtherTools.Add(new ToolboxTile("format-inspector", "Format Inspector", "Probe codecs, streams, and metadata", "\uE946", blue, "Ready", green, false, "UCX + FFprobe"));
        OtherTools.Add(new ToolboxTile("chapter-marks", "Chapter Marks", "Edit embedded MKV / MP4 chapter markers (no re-encode)", "\uE8B7", blue, "Ready", green, false, "FFmpeg"));
        OtherTools.Add(new ToolboxTile("watch-folders", "Watch Folders", "Auto-process files dropped into a watched folder", "\uED25", green, "Ready", green, false, "UCX"));
        OtherTools.Add(new ToolboxTile("history", "History", "Search the persistent log of every job + re-run", "\uE81C", blue, "Ready", green, false, "UCX + SQLite"));
        OtherTools.Add(new ToolboxTile("vmaf", "VMAF Quality", "Score a compressed clip against its reference (mean / harmonic / min)", "\uE9D9", blue, "Ready", green, false, "FFmpeg + libvmaf"));
        OtherTools.Add(new ToolboxTile("batch-rename", "Batch Rename", "Pattern + regex rename with live preview", "\uE8AC", blue, "Ready", green, false, "UCX"));

        // v2.7 OSS engines
        DocumentTools.Add(new ToolboxTile("presets:datakit", "Data Converter", "JSON / YAML / TOML / XML / CSV / TSV / NDJSON", "\uE8A5", blue, "Ready", green, false, "PyYAML + tomli + xmltodict"));
        DocumentTools.Add(new ToolboxTile("presets:mailbox", "Email Converter", "MBOX / EML / Maildir mutual conversion", "\uE715", blue, "Ready", green, false, "stdlib mailbox"));
        DocumentTools.Add(new ToolboxTile("presets:calconvert", "Calendar / vCard", "ICS / VCF -> JSON / CSV (and back)", "\uE787", blue, "Ready", green, false, "icalendar + vobject"));
        DocumentTools.Add(new ToolboxTile("presets:webarchive", "Web Archive", "HAR <-> WARC + extraction", "\uE774", blue, "Ready", green, false, "warcio"));
        DocumentTools.Add(new ToolboxTile("presets:codeformat", "Code Formatter", "prettier / black / gofmt / rustfmt / clang-format", "\uE943", blue, "Ready", green, false, "OSS formatters"));

        AudioTools.Add(new ToolboxTile("presets:audiotag", "Audio Metadata", "Read / write / strip ID3 / FLAC / Ogg / M4A tags", "\uE189", blue, "Ready", green, false, "mutagen"));
        AudioTools.Add(new ToolboxTile("presets:trackermod", "Tracker Modules", "MOD / IT / XM / S3M -> WAV / FLAC / MP3", "\uE767", green, "Ready", green, false, "libopenmpt"));
        AudioTools.Add(new ToolboxTile("presets:midisynth", "MIDI Renderer", "MIDI + SoundFont -> WAV / FLAC / MP3 (FluidSynth)", "\uEC4F", red, "Ready", green, false, "FluidSynth"));

        ImageTools.Add(new ToolboxTile("presets:iccprofile", "ICC Color Profile", "Apply / embed / strip color profiles (sRGB / AdobeRGB / Lab)", "\uE790", blue, "Ready", green, false, "Pillow ImageCms"));
        ImageTools.Add(new ToolboxTile("presets:lottiekit", "Lottie Animation", ".json / .tgs / .lottie -> GIF / MP4 / WebP / APNG / SVG", "\uE909", blue, "Ready", green, false, "python-lottie"));
        ImageTools.Add(new ToolboxTile("presets:texturekit", "GPU Textures", "DDS / KTX / KTX2 / ASTC / EXR / TGA mutual conversion", "\uEB9F", orange, "Ready", green, false, "Pillow + imageio + astcenc"));
        ImageTools.Add(new ToolboxTile("presets:dicomkit", "DICOM Imaging", "Medical DCM -> PNG / JPEG / TIFF + anonymization", "\uE8A1", red, "Ready", green, false, "pydicom"));

        OtherTools.Add(new ToolboxTile("presets:cadkit", "CAD (DXF/DWG)", "DXF -> SVG / PDF / version-up; DWG -> DXF (ODA)", "\uE8B7", green, "Ready", green, false, "ezdxf + ODA"));
        VideoTools.Add(new ToolboxTile("presets:clipforge", "Video Extras", "Concat / slow-mo / reverse / LUT-3D / HDR -> SDR", "\uE714", blue, "Ready", green, false, "ClipForge + FFmpeg"));

        // v2.20.1 cleanup — surface previously-orphaned sidecars
        VideoTools.Add(new ToolboxTile("presets:alphacut", "Video Background Removal", "AI matting on video tracks (U2Net / SAM 2 segmentation)", "\uE91F", red, "Ready", green, false, "U2Net + SAM 2"));
        OtherTools.Add(new ToolboxTile("presets:archive", "Archive Tool", "Pack / unpack / list 7z / zip / tar / rar / iso / cab archives", "\uE7B8", blue, "Ready", green, false, "7-Zip"));
        AudioTools.Add(new ToolboxTile("presets:audiotag", "Audio Metadata Tags", "Read / write / strip ID3 / FLAC / Vorbis / M4A tags", "\uE189", blue, "Ready", green, false, "mutagen"));
        VideoTools.Add(new ToolboxTile("presets:chaptermark", "Chapter Markers", "Read / write MP4 / MKV / M4B chapter markers", "\uE7C3", blue, "Ready", green, false, "mutagen + mkvmerge"));
        DocumentTools.Add(new ToolboxTile("presets:codeformat", "Source Code Formatter", "prettier / black / gofmt / rustfmt / clang-format auto-format", "\uE943", blue, "Ready", green, false, "OSS formatters"));
        OtherTools.Add(new ToolboxTile("presets:coordfmt", "Coordinate Format", "GPS DD / DMS / UTM / MGRS / Geohash / Plus Codes batch convert", "\uE707", blue, "Ready", green, false, "pyproj + mgrs"));
        AudioTools.Add(new ToolboxTile("presets:demucs", "Audio Stem Separation", "Demucs htdemucs_ft 4-stem (vocals / drums / bass / other)", "\uE767", red, "Ready", green, false, "Demucs"));
        DocumentTools.Add(new ToolboxTile("presets:docconvert", "Document Convert", "DOCX / ODT / RTF / HTML / TXT / PDF via LibreOffice headless", "\uE8A5", blue, "Ready", green, false, "LibreOffice"));
        DocumentTools.Add(new ToolboxTile("presets:ebookconvert", "eBook Convert", "EPUB / MOBI / AZW3 / PDF / FB2 / LRF mutual conversion", "\uE82D", blue, "Ready", green, false, "Calibre"));
        AudioTools.Add(new ToolboxTile("presets:edge-tts", "Microsoft Edge TTS", "Text -> speech via Microsoft Edge TTS voices (free)", "\uE767", blue, "Ready", green, false, "edge-tts"));
        DocumentTools.Add(new ToolboxTile("presets:fontconvert", "Font Format Convert", "TTF / OTF / WOFF / WOFF2 / EOT / TTC mutual conversion", "\uE8D2", blue, "Ready", green, false, "fontTools"));
        VideoTools.Add(new ToolboxTile("presets:framesnap", "Video Frame Extract", "Frames every N seconds / N frames / scene cuts -> JPG / PNG / WebP", "\uE91B", blue, "Ready", green, false, "FFmpeg"));
        ImageTools.Add(new ToolboxTile("presets:gfpgan", "Face Restoration GFPGAN", "Restore old / blurry / damaged faces in photos via GFPGAN v1.4", "\uE91F", red, "Ready", green, false, "GFPGAN"));
        ImageTools.Add(new ToolboxTile("presets:gifstudio", "GIF Studio", "MP4 / MOV / WebM -> GIF with palette + dithering presets", "\uE909", orange, "Ready", green, false, "FFmpeg"));
        OtherTools.Add(new ToolboxTile("presets:gisconvert", "GIS Vector + Raster", "Shapefile / KML / GPX / GeoJSON / GeoTIFF / DEM via GDAL", "\uE707", blue, "Ready", green, false, "GDAL"));
        ImageTools.Add(new ToolboxTile("presets:heicshift", "HEIC Image Converter", "iPhone HEIC -> JPG / PNG / WebP / TIFF batch convert", "\uEB9F", blue, "Ready", green, false, "Pillow + libheif"));
        VideoTools.Add(new ToolboxTile("presets:lipsight", "Lip-Reading Transcribe", "Transcribe video audio via lip-reading model (HF Space)", "\uE767", red, "Ready", green, false, "HuggingFace"));
        AudioTools.Add(new ToolboxTile("presets:mailbox", "Email Mailbox Convert", "mbox / EML / Maildir / RFC822 mutual conversion", "\uE715", blue, "Ready", green, false, "stdlib mailbox"));
        DocumentTools.Add(new ToolboxTile("presets:ocr", "Image OCR (Tesseract)", "Image / multi-page TIFF -> TXT / hOCR / PDF / TSV / ALTO", "\uE8E6", blue, "Ready", green, false, "Tesseract"));
        DocumentTools.Add(new ToolboxTile("presets:pdfocr", "Scanned PDF -> Searchable PDF", "OCRmyPDF + Poppler scanned-PDF OCR pass", "\uE8E6", blue, "Ready", green, false, "OCRmyPDF"));
        DocumentTools.Add(new ToolboxTile("presets:pdftools", "PDF Tools", "Merge / split / compress / encrypt / extract / rotate via pikepdf", "\uEA90", orange, "Ready", green, false, "pikepdf"));
        ImageTools.Add(new ToolboxTile("presets:realesrgan", "Image / Video Upscale", "Real-ESRGAN x4 super-resolution for image + video", "\uE714", red, "Ready", green, false, "Real-ESRGAN"));
        AudioTools.Add(new ToolboxTile("recorder", "Screen / Audio Recorder", "Live screen + system-audio + mic capture (DirectShow / FFmpeg)", "\uE714", blue, "Ready", green, false, "FFmpeg + DirectShow"));
        AudioTools.Add(new ToolboxTile("presets:rnnoise", "Audio Denoise (RNNoise)", "Real-time RNNoise voice denoising for any audio", "\uE767", blue, "Ready", green, false, "RNNoise"));
        VideoTools.Add(new ToolboxTile("presets:scenedetect", "Scene Detection", "PySceneDetect adaptive + content scene-change detection -> CSV / EDL", "\uE714", blue, "Ready", green, false, "PySceneDetect"));
        AudioTools.Add(new ToolboxTile("downloader", "Stream / VOD Downloader", "yt-dlp wrapper for YouTube / Twitch / TikTok / Vimeo / 1500+ sites", "\uE896", blue, "Ready", green, false, "yt-dlp + FFmpeg"));
        VideoTools.Add(new ToolboxTile("presets:subconvert", "Subtitle Format Convert", "SRT / VTT / ASS / SSA / SUB / SAMI mutual conversion + retime", "\uED1E", blue, "Ready", green, false, "pysubs2"));
        OtherTools.Add(new ToolboxTile("presets:timefmt", "Timestamp Format", "ISO 8601 / Epoch / Excel / FILETIME / Cocoa / Mainframe Julian", "\uE787", blue, "Ready", green, false, "stdlib + dateutil"));
        VideoTools.Add(new ToolboxTile("presets:vertigo", "Auto-Reframe 9:16 Vertical", "Smart 16:9 -> 9:16 vertical reframing for TikTok / Reels / Shorts", "\uE714", red, "Ready", green, false, "Vertigo + OpenCV"));
        VideoTools.Add(new ToolboxTile("presets:videocrush", "Video Compressor", "SVT-AV1 v2 fast / quality / streaming + size targeting", "\uE714", green, "Ready", green, false, "FFmpeg + SVT-AV1"));
        VideoTools.Add(new ToolboxTile("presets:videosubtitleremover", "Burned-In Subtitle Remove", "STTN inpainting to erase burned-in subtitles from video", "\uED1E", red, "Ready", green, false, "STTN"));
        AudioTools.Add(new ToolboxTile("presets:whisper-cpp", "Speech -> Text (whisper.cpp)", "Local CPU Whisper transcription via whisper.cpp (no GPU needed)", "\uE767", blue, "Ready", green, false, "whisper.cpp"));
        AudioTools.Add(new ToolboxTile("presets:whisper-stt", "Speech -> Text (Whisper Large v3 Turbo)", "GPU-accelerated Whisper Large v3 Turbo + Silero VAD + diarization", "\uE767", red, "Ready", green, false, "Whisper + pyannote"));

        // v2.20 wave (AI/ML + Forensics + Notes + DAW + Video post + PCB + BI + Reg + LMS + Med + IoT + Social + Dev)
        OtherTools.Add(new ToolboxTile("presets:mlmodel", "AI/ML Model Interchange", "ONNX + safetensors + GGUF + TFLite + CoreML + .pt header probes", "\uE99A", red, "Ready", green, false, "stdlib + onnx"));
        OtherTools.Add(new ToolboxTile("presets:forensics", "Digital Forensics", "NTFS $MFT + .reg + prefetch + browser history + EWF E01 probe", "\uE72E", orange, "Ready", green, false, "stdlib + sqlite + ewfinfo"));
        DocumentTools.Add(new ToolboxTile("presets:notetaking", "Note-Taking Apps", "Notion + Evernote .enex + Obsidian + Joplin + Day One + Roam -> Markdown", "\uE70F", blue, "Ready", green, false, "stdlib"));
        AudioTools.Add(new ToolboxTile("presets:dawproject", "DAW Project Probes", "Ableton .als + FL .flp + REAPER .rpp + Audacity .aup3 + LMMS + DAWproject", "\uE767", blue, "Ready", green, false, "stdlib + sqlite"));
        VideoTools.Add(new ToolboxTile("presets:vidpost", "Video Timelines", "FCPXML + OTIO + Premiere .prproj + EDL CMX 3600 -> JSON / CSV", "\uE714", blue, "Ready", green, false, "stdlib + otioconvert"));
        OtherTools.Add(new ToolboxTile("presets:pcbcad", "Electronics CAD", "Gerber RS-274X + Excellon drill + KiCad + Eagle + IPC-D-356", "\uEC7A", green, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:bireport", "BI / Reporting", "Tableau .twb/.twbx + Power BI .pbix + SSRS .rdl + Looker LookML + dbt", "\uE9D9", blue, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:sdmx", "Regulatory Data", "XBRL + iXBRL + SDMX-ML + DDI codebooks -> CSV / JSON", "\uE9D5", orange, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:lmskit", "Learning Management", "SCORM + Common Cartridge + QTI + xAPI + LTI 1.3 JWT + Moodle .mbz", "\uE73E", blue, "Ready", green, false, "stdlib"));
        ImageTools.Add(new ToolboxTile("presets:medkitex", "Healthcare Extras", "DICOM SR + DICOM Waveform + HL7 CCD/CCDA + IHE XDS + NCPDP", "\uE8A1", red, "Ready", green, false, "pydicom + numpy"));
        OtherTools.Add(new ToolboxTile("presets:iotbus", "Industrial IoT", "OPC UA NodeSet + Modbus map + KNX ETS .knxproj + EDS DeviceNet", "\uEC7A", blue, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:socialarchives", "Social Media Archives", "Twitter / X + Mastodon + Reddit + Discord exports -> CSV", "\uE8BD", blue, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:devbuild", "Build Manifests", "npm + Cargo + Composer + Maven + Go + .csproj package manifests -> CSV", "\uE943", blue, "Ready", green, false, "stdlib"));

        // v2.19 wave (Lab + Scope + Retro + Test reports + DB exports + Splat + ArcGIS + Thumbs)
        OtherTools.Add(new ToolboxTile("presets:labkit", "Lab + Windows Trace", "LabVIEW LVM/TDMS + Sysinternals Procmon + ETW .etl + perfmon .blg -> CSV", "\uE9F1", blue, "Ready", green, false, "stdlib + npTDMS + Win tools"));
        OtherTools.Add(new ToolboxTile("presets:scope", "Oscilloscope Waveforms", "Tektronix .wfm/.isf + LeCroy .trc + Keysight .bin -> CSV", "\uEC03", green, "Ready", green, false, "stdlib"));
        ImageTools.Add(new ToolboxTile("presets:retroimg", "Retro Computer Images", "Atari ST DEGAS + ZX Spectrum SCR + Apple II HGR + WBMP -> PNG", "\uEB9F", orange, "Ready", green, false, "stdlib + Pillow"));
        OtherTools.Add(new ToolboxTile("presets:retrodisks", "Retro Disk Images", "Apple II .dsk + C64 D64 + Atari ATR + ZX TAP catalog reader", "\uE7B5", green, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:legacydocs", "DOS Legacy Word Processors", "WordStar + MS Write + Lotus Word Pro -> plain text (string scrape)", "\uE8A5", orange, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:testreports", "Test Result Reports", "JUnit / TAP / Allure / Cucumber / TestNG -> CSV / HTML report", "\uE73E", blue, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:dbexport", "DB Vendor Exports", "DB2 IXF + SQL Server BCP + MySQL dump + SQL*Loader -> CSV", "\uE9D5", blue, "Ready", green, false, "stdlib"));
        AudioTools.Add(new ToolboxTile("presets:demosound", "Demoscene Chiptune", "Atari ST .YM + ZX AY + Atari 8-bit SAP -> WAV via emulator backends", "\uE767", red, "Ready", green, false, "sc68 / zxtune123 / asap"));
        VideoTools.Add(new ToolboxTile("presets:vidlegacy", "Legacy Video", "RealVideo .rm/.rmvb + Bink + Smacker + OGM + DivX + Cinepak -> MP4 H.264", "\uE714", orange, "Ready", green, false, "FFmpeg"));
        OtherTools.Add(new ToolboxTile("presets:gsplat", "Gaussian Splatting", "Antimatter15 .splat <-> 3DGS .ply round-trip + header probe", "\uF158", green, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:arcgis", "ArcGIS File Geodatabase", ".gdb / .gpkg layer list + extract -> GeoJSON / SHP / GPKG / FGB via GDAL", "\uE707", blue, "Ready", green, false, "GDAL ogr2ogr"));
        ImageTools.Add(new ToolboxTile("presets:mediathumb", "Universal Thumbnails", "Video / PDF / audio cover / EPUB / DOCX / image -> JPG thumbnail", "\uE91B", blue, "Ready", green, false, "FFmpeg + Poppler + mutagen + Pillow"));

        // v2.18 wave (Source Xform + DICOM-RT + niche eBooks + Auto + Airline + Tax)
        DocumentTools.Add(new ToolboxTile("presets:srctranspile", "Code Transpiler", "Python 2 -> 3 + CoffeeScript -> JS + Vue 2 -> 3 + JS -> TS bootstrap + Flow -> TS", "\uE943", blue, "Ready", green, false, "lib2to3 + tsc + npm CLIs"));
        ImageTools.Add(new ToolboxTile("presets:dicomrt", "DICOM-RT (Radiation Therapy)", "RTSTRUCT contours + RTPLAN beams + RTDOSE 3D grid -> NIfTI / JSON / CSV", "\uE8A1", red, "Ready", green, false, "pydicom + SimpleITK"));
        DocumentTools.Add(new ToolboxTile("presets:ebookmore", "eBooks Long-Tail", "FictionBook 2 + PalmDoc + iSilo + LRF / TPZ via Calibre fallback", "\uE82D", blue, "Ready", green, false, "stdlib + calibre"));
        OtherTools.Add(new ToolboxTile("presets:bus", "Automotive Bus", "DBC CAN database + ARXML AUTOSAR + candump + OBD-II PID reference", "\uEC7A", green, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:iata", "Airline Messaging", "IATA NDC airline booking XML + PNR + airport / airline code reference", "\uE709", blue, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:mobilephotos", "Mobile Photo Libraries", "Google Takeout Photos + Apple .photoslibrary + Android MediaStore + iOS .ips", "\uE8B9", blue, "Ready", green, false, "stdlib + sqlite"));
        DocumentTools.Add(new ToolboxTile("presets:taxkit", "Tax / Accounting", "Swedish SIE 4 + DATEV German + IFX + ELSTER tax filing XML", "\uE9D9", blue, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:datakitmore", "Niche Data Formats", "EDN / KDL / JSON5 / HJSON / RON / NestedText round-trip with JSON", "\uE943", orange, "Ready", green, false, "stdlib + optional libs"));
        DocumentTools.Add(new ToolboxTile("presets:diagrammore", "Diagrams Long-Tail", "GraphML / yEd -> SVG via Graphviz + Freemind .mm -> Markdown / OPML + Lucidchart .lcc", "\uE9B6", blue, "Ready", green, false, "stdlib + graphviz"));
        OtherTools.Add(new ToolboxTile("presets:bgpkit", "BGP / Routing Telemetry", "MRT TABLE_DUMP_V2 RIB + BIRD show route + RPKI ROA dump normalization", "\uEC05", blue, "Ready", green, false, "mrtparse"));
        AudioTools.Add(new ToolboxTile("presets:sdrkit", "SDR IQ Files", "RTL-SDR cu8 / HackRF cs16 / GNU Radio cf32 IQ + SigMF probe", "\uE767", green, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:comicmeta", "Comic Metadata", "ComicInfo.xml read / inject / CSV bulk-edit / scrub for CBZ libraries", "\uE82D", orange, "Ready", green, false, "stdlib"));

        // v2.17 wave (Specialty Engineering + Wire / Network / Music / Sci)
        OtherTools.Add(new ToolboxTile("presets:wells", "Oil-Well Logs (LAS / DLIS)", "LAS 2.0/3.0 + DLIS binary log files -> CSV / JSON for petroleum analysis", "\uE9F1", green, "Ready", green, false, "stdlib + dlisio"));
        DocumentTools.Add(new ToolboxTile("presets:datawire", "Protobuf / Avro / Thrift", "Schema-driven binary wire formats -> JSON via protoc + fastavro + IDL parser", "\uE943", blue, "Ready", green, false, "fastavro + protoc"));
        OtherTools.Add(new ToolboxTile("presets:wirelesskit", "GPS NMEA / AIS Marine", "NMEA 0183 sentences -> JSON / CSV / KML / GPX track + AIS marine tracking", "\uE707", blue, "Ready", green, false, "stdlib + pyais"));
        OtherTools.Add(new ToolboxTile("presets:iac", "Infrastructure as Code", "Docker Compose v1->v3 + CFN YAML<->JSON + Terraform plan summary + Helm/Kustomize render", "\uEC1F", blue, "Ready", green, false, "PyYAML + helm + kustomize"));
        OtherTools.Add(new ToolboxTile("presets:bed", "Genome Intervals (BED)", "BED / bigBed / GFF3 / GTF / narrowPeak / broadPeak interval conversion", "\uE7C2", green, "Ready", green, false, "stdlib + UCSC bigBedToBed"));
        DocumentTools.Add(new ToolboxTile("presets:swiftmx", "SWIFT MX (ISO 20022)", "Modern XML banking: pacs.* / pain.* / camt.* / setr.* / remt.* -> JSON / CSV", "\uE9D9", blue, "Ready", green, false, "stdlib"));
        AudioTools.Add(new ToolboxTile("presets:musicmore", "LilyPond + MuseScore", "LilyPond .ly -> PDF / SVG / MIDI + MusicXML <-> .ly + .mscz -> MIDI / PDF", "\uE767", red, "Ready", green, false, "lilypond + musescore"));
        AudioTools.Add(new ToolboxTile("presets:playlistmore", "iTunes + Spotify Playlists", "iTunes Library.xml -> M3U / JSON + Spotify export -> M3U / normalized CSV", "\uE93C", blue, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:netflowkit", "NetFlow / IPFIX Flows", "NetFlow v5/v9 + IPFIX v10 router/switch flow records -> JSON", "\uEC05", blue, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:proteomics", "Mass Spec / Proteomics", "mzML / mzXML / MGF mass spectrometry data -> JSON / CSV peak lists", "\uE7C2", green, "Ready", green, false, "stdlib"));

        // v2.16 wave (Email + Messaging + Calendar + Subtitles + Specialty Enterprise)
        DocumentTools.Add(new ToolboxTile("presets:emailpro", "Email Plus", "Outlook .msg + Apple .emlx + thread mbox bundling", "\uE715", blue, "Ready", green, false, "extract-msg + stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:messaging", "Messaging Exports", "Telegram / Discord / Slack / iMessage / WhatsApp -> CSV / JSON / HTML", "\uE8BD", blue, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:calmore", "Calendar + Address Book", ".icbu unpack + Google Takeout calendar JSON -> ICS + LDIF / Outlook CSV -> vCard", "\uE787", blue, "Ready", green, false, "icalendar + vobject"));
        VideoTools.Add(new ToolboxTile("presets:subextra", "Subtitles Plus", "CEA-608/708 caps via ccextractor + iTunes Timed Text + ASS karaoke -> LRC", "\uED1E", green, "Ready", green, false, "ccextractor + stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:edi", "EDI X12 / EDIFACT", "Healthcare / supply-chain / banking EDI -> hierarchical JSON / per-segment CSV", "\uE943", blue, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:swift", "SWIFT MT (Banking)", "MT103 / MT202 / etc. message families -> structured JSON / CSV", "\uE9D9", blue, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:asn1", "ASN.1 / X.509", "BER / DER / PEM <-> JSON tree (X.509 / PKCS#7 / CMS / SNMP / Kerberos)", "\uE72E", orange, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:mobile", "Mobile Backups", "iTunes iOS backup inventory + extract + Android adb .ab -> tar", "\uE8EA", blue, "Ready", green, false, "stdlib + sqlite"));
        OtherTools.Add(new ToolboxTile("presets:dbsql", "SQL Dialect Translator", "MySQL / Postgres / SQL Server / Oracle / SQLite / BigQuery / Snowflake / DuckDB", "\uE9D5", blue, "Ready", green, false, "sqlglot"));
        DocumentTools.Add(new ToolboxTile("presets:spreadsheet", "Legacy Spreadsheets", "Lotus 1-2-3 / Quattro Pro / Gnumeric / StarOffice / AppleWorks -> XLSX / ODS / CSV", "\uE9F9", blue, "Ready", green, false, "LibreOffice"));
        OtherTools.Add(new ToolboxTile("presets:colorfmt", "Color Formats", "Hex / RGB / HSL / HSV / CMYK / Lab / CSS named -> CSV / JSON / CSS variables", "\uE790", orange, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:gameasset", "Game Asset Containers", "Quake .pak / Doom .wad / Source .vpk / Godot .pck / .pk3 / .bsa", "\uE7FC", green, "Ready", green, false, "stdlib"));

        // v2.15 wave (Healthcare + Finance + Engineering + Wire formats)
        DocumentTools.Add(new ToolboxTile("presets:hl7", "HL7 Healthcare", "HL7 v2 messages <-> JSON + FHIR R4/R5 JSON <-> XML", "\uE8A1", red, "Ready", green, false, "stdlib"));
        DocumentTools.Add(new ToolboxTile("presets:finance", "Finance / Accounting", "OFX / QFX / QIF / IIF / MT940 -> CSV / JSON / QIF (transaction-aware)", "\uE9D9", blue, "Ready", green, false, "ofxparse + mt-940"));
        OtherTools.Add(new ToolboxTile("presets:cadmore", "3D Printing CAD", "STL / OBJ / PLY / GLB / 3MF / AMF mutual conversion + G-code probe", "\uF158", green, "Ready", green, false, "trimesh + custom 3MF/AMF"));
        OtherTools.Add(new ToolboxTile("presets:genome", "Genomics Binary", "VCF <-> BCF + bgzip / tabix index + ENCODE peak -> BED", "\uE7C2", green, "Ready", green, false, "pysam"));
        OtherTools.Add(new ToolboxTile("presets:gistiles", "GIS Tiles + COG", "MBTiles / PMTiles probe + KMZ / KML round-trip + GeoTIFF -> COG", "\uE707", blue, "Ready", green, false, "GDAL + sqlite"));
        ImageTools.Add(new ToolboxTile("presets:imgmore", "Niche Images Plus", "JBIG2 / FAX TIFF / Mac PICT / Amiga IFF / Atari Degas / layered TIFF", "\uEB9F", orange, "Ready", green, false, "ImageMagick + jbig2dec + tifffile"));
        DocumentTools.Add(new ToolboxTile("presets:wirefmt", "Binary Wire Formats", "CBOR / MessagePack / BSON / Ion <-> JSON (the formats every modern API uses)", "\uE943", blue, "Ready", green, false, "cbor2 + msgpack + bson + amazon.ion"));

        // v2.14 wave (Streaming + Crypto + Niche A/V)
        VideoTools.Add(new ToolboxTile("presets:videopro", "Specialty Video", "VOB / MTS / DV / 3GP / F4V / SWF / H.264-H.265-AV1 elementary streams", "\uE714", green, "Ready", green, false, "FFmpeg"));
        VideoTools.Add(new ToolboxTile("presets:streaming", "Streaming Manifests", "MP4 -> HLS / DASH / CMAF + manifest -> MP4 round-trip", "\uE968", blue, "Ready", green, false, "shaka-packager + FFmpeg"));
        VideoTools.Add(new ToolboxTile("presets:imageseq", "Image Sequence", "DPX / EXR / PNG / TIFF sequence <-> ProRes / DNxHR / H.264 / H.265 / AV1", "\uE7C3", blue, "Ready", green, false, "FFmpeg"));
        AudioTools.Add(new ToolboxTile("presets:chiptune", "Chiptune Audio", "NSF / SPC / VGM / GBS / HES / KSS / SID / AY -> WAV / FLAC / MP3", "\uEC4F", green, "Ready", green, false, "game-music-emu + sidplayfp"));
        AudioTools.Add(new ToolboxTile("presets:audiomore", "Niche Audio", "AIFF / CAF / DTS-HD MA / TrueHD / HE-AAC v2 / ulaw / alaw / xHE-AAC", "\uEC4F", red, "Ready", green, false, "FFmpeg"));
        OtherTools.Add(new ToolboxTile("presets:gpgkit", "OpenPGP / GnuPG", "Binary <-> ASCII armor + key metadata probe", "\uE72E", blue, "Ready", green, false, "stdlib + GnuPG CLI"));
        OtherTools.Add(new ToolboxTile("presets:wallet", "Crypto Wallet (read)", "BIP39 mnemonic check + Ethereum keystore + Bitcoin descriptor + PSBT decode", "\uE7B5", orange, "Ready", green, false, "mnemonic + stdlib"));

        // v2.13 wave (Office + Diagrams + Sysadmin)
        DocumentTools.Add(new ToolboxTile("presets:legacyoffice", "Legacy Office Documents", "WordPerfect / AmiPro / Works / Publisher / StarOffice / KOffice / AbiWord", "\uE8A5", blue, "Ready", green, false, "LibreOffice"));
        DocumentTools.Add(new ToolboxTile("presets:applepro", "Apple iWork", "Pages / Numbers / Keynote -> DOCX / XLSX / PPTX / PDF", "\uE8A5", blue, "Ready", green, false, "LibreOffice + iWork XML"));
        DocumentTools.Add(new ToolboxTile("presets:hwpkit", "Korean Hangul HWP", "HWP / HWPX -> PDF / DOCX / ODT / HTML / TXT", "\uE8A5", blue, "Ready", green, false, "pyhwp + LibreOffice"));
        DocumentTools.Add(new ToolboxTile("presets:diagram", "Diagrams", "Mermaid / PlantUML / Graphviz / Visio / draw.io / Excalidraw -> SVG / PNG / PDF", "\uE9B6", blue, "Ready", green, false, "mermaid-cli + plantuml + dot"));
        DocumentTools.Add(new ToolboxTile("presets:notebooks", "Jupyter Notebooks", "ipynb <-> py / md / Rmd / qmd / html / pdf / slides", "\uE7C3", green, "Ready", green, false, "nbconvert + jupytext"));
        DocumentTools.Add(new ToolboxTile("presets:helpkit", "Compiled Help (CHM)", "CHM extraction + CHM -> single PDF", "\uE897", blue, "Ready", green, false, "7z + weasyprint"));
        DocumentTools.Add(new ToolboxTile("presets:comic", "Comic Books", "CBZ / CBR / CBT / CB7 mutual conversion + CBZ -> PDF / EPUB", "\uE82D", orange, "Ready", green, false, "rarfile + img2pdf + EbookLib"));
        AudioTools.Add(new ToolboxTile("presets:playlist", "Playlists", "M3U / M3U8 / PLS / XSPF / WPL / ASX / B4S / iTunes XML mutual conversion", "\uEC4F", blue, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:tlskit", "TLS Certificates", "X.509 PEM / DER / PKCS#7 / PKCS#12 conversion + cert metadata probe", "\uE72E", blue, "Ready", green, false, "cryptography"));
        OtherTools.Add(new ToolboxTile("presets:sshkit", "SSH Keys", "OpenSSH / PEM PKCS#8 / PuTTY .ppk / RFC 4716 conversion", "\uE72E", blue, "Ready", green, false, "cryptography + puttygen"));
        OtherTools.Add(new ToolboxTile("presets:timefmt", "Timestamps", "ISO 8601 / Unix epoch / Excel / FILETIME / cocoa / RFC 822 / cron explain", "\uE823", blue, "Ready", green, false, "stdlib + croniter"));
        OtherTools.Add(new ToolboxTile("presets:coordfmt", "Coordinates", "DD / DMS / DDM / UTM / MGRS / Geohash / Plus Codes batch conversion", "\uE707", blue, "Ready", green, false, "utm + mgrs + olc"));
        OtherTools.Add(new ToolboxTile("presets:config", "DevOps Config", "HCL / HOCON / properties / INI / systemd / JSON / YAML / TOML", "\uE943", blue, "Ready", green, false, "python-hcl2 + pyhocon"));
        OtherTools.Add(new ToolboxTile("presets:dnskit", "DNS Zone Files", "BIND zone <-> JSON / YAML / CSV + zone validation", "\uE968", blue, "Ready", green, false, "dnspython"));

        // v2.12 wave (Domain-specific & exotic)
        OtherTools.Add(new ToolboxTile("presets:chemkit", "Chemistry", "SMILES / MOL / SDF / MOL2 / PDB / XYZ / CIF / InChI", "\uE7C2", green, "Ready", green, false, "RDKit + Open Babel"));
        OtherTools.Add(new ToolboxTile("presets:biokit", "Bioinformatics", "FASTA / FASTQ / GenBank / EMBL / VCF / BAM / SAM / Newick", "\uE7C2", green, "Ready", green, false, "Biopython + pysam"));
        OtherTools.Add(new ToolboxTile("presets:medkit", "Medical Imaging 3D", "NIfTI / Analyze / MetaImage / NRRD / MINC / GIPL volumes", "\uE8A1", red, "Ready", green, false, "SimpleITK + nibabel"));
        OtherTools.Add(new ToolboxTile("presets:netcap", "Network Capture", "PCAP <-> PCAPNG + CSV packet summaries", "\uE968", blue, "Ready", green, false, "scapy"));
        DocumentTools.Add(new ToolboxTile("presets:logkit", "Log Files", "Apache / Nginx / syslog / Windows .evtx -> structured JSONL", "\uE9D9", blue, "Ready", green, false, "stdlib + python-evtx"));
        ImageTools.Add(new ToolboxTile("presets:rasterimg", "Niche Raster", "PCX / TGA / DPX / SGI / Sun / PCD / Netpbm / APNG / XPM / Palm", "\uEB9F", orange, "Ready", green, false, "Pillow"));
        DocumentTools.Add(new ToolboxTile("presets:morearchive", "More Archives", "SIT / LHA / ARJ / DEB / RPM / DMG / IPA / APK / MSIX / NUPKG", "\uE7B8", orange, "Ready", green, false, "7z + unar"));
        OtherTools.Add(new ToolboxTile("presets:bookmark", "Browser Bookmarks", "Chrome / Firefox / Safari / Opera / Netscape / CSV mutual conversion", "\uE74C", blue, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:engcad", "Engineering CAD", "STEP / IGES / BREP / STL / OBJ -- BREP solids via Open CASCADE", "\uE8B7", green, "Ready", green, false, "pythonocc"));
        OtherTools.Add(new ToolboxTile("presets:animkit", "3D Animation", "BVH motion-capture / Alembic / USD / USDZ / FBX / glTF / VRM / Collada", "\uF158", blue, "Ready", green, false, "usd-core + assimp"));

        // v2.11 wave (Raw Coverage)
        ImageTools.Add(new ToolboxTile("presets:psdkit", "Photoshop / GIMP", "PSD / PSB / XCF -> PNG/JPG/TIFF + per-layer extraction", "\uEB9F", blue, "Ready", green, false, "psd-tools + gimpformats"));
        ImageTools.Add(new ToolboxTile("presets:hdrkit", "HDR Image", "Radiance HDR / OpenEXR / PFM + tone-mapping (Reinhard/Drago/Mantiuk)", "\uEB9F", orange, "Ready", green, false, "imageio + OpenCV"));
        ImageTools.Add(new ToolboxTile("presets:iconkit", "Icon Generator", "PNG -> Windows .ico (multi-res) + Apple .icns / .iconset", "\uEB9F", blue, "Ready", green, false, "Pillow"));
        AudioTools.Add(new ToolboxTile("presets:audiopro", "Niche Audio Codec", "DSD / APE / WV / TAK / AC3 / DTS / WMA / AMR / SPEEX / GSM / RA / AU", "\uEC4F", red, "Ready", green, false, "FFmpeg"));
        DocumentTools.Add(new ToolboxTile("presets:subocr", "Bitmap Subtitle OCR", "Blu-ray PGS / DVD VobSub -> SRT (FFmpeg + Tesseract)", "\uE93B", blue, "Ready", green, false, "Tesseract"));
        DocumentTools.Add(new ToolboxTile("presets:subkit", "Subtitle Interchange", "SAMI / TTML / DFXP / SCC / EBU STL / MicroDVD / LRC / SBV", "\uE93B", blue, "Ready", green, false, "pycaption + pysubs2"));
        DocumentTools.Add(new ToolboxTile("presets:dbtools", "Database / Stats", "Access / DBF / SAS / SPSS / Stata / R -> CSV / Parquet / SQLite", "\uE9D9", blue, "Ready", green, false, "pandas + dbfread + pyreadstat + pyreadr"));
        OtherTools.Add(new ToolboxTile("presets:textencode", "Text Recoder", "Charset (UTF-8 / Shift-JIS / cp1252 / GB18030) + line endings + BOM", "\uE8A5", blue, "Ready", green, false, "stdlib + chardet"));
        OtherTools.Add(new ToolboxTile("presets:hashkit", "Hash / Checksum", "MD5 / SHA-1/2/3 / BLAKE2 / BLAKE3 / xxHash / CRC32 -- generate + verify", "\uE72E", blue, "Ready", green, false, "hashlib + blake3"));
        OtherTools.Add(new ToolboxTile("presets:encodekit", "Base64 / Hex Encoder", "Base64 / Base32 / Base85 / Hex / data: URL", "\uE943", blue, "Ready", green, false, "stdlib"));
        OtherTools.Add(new ToolboxTile("presets:plistkit", "Apple plist", "Binary / XML / JSON plist mutual conversion", "\uE7B5", blue, "Ready", green, false, "stdlib plistlib"));
        DocumentTools.Add(new ToolboxTile("presets:music", "Music Notation", "MusicXML / MIDI / ABC / MuseScore / GuitarPro mutual conversion", "\uEC4F", green, "Ready", green, false, "music21 + GuitarPro"));
        OtherTools.Add(new ToolboxTile("presets:hexkit", "Embedded Flash Image", "Intel HEX / Motorola SREC / TI-TXT / raw binary", "\uE950", blue, "Ready", green, false, "bincopy"));

        // v2.10 wave (Latest & Greatest)
        AiTools.Add(new ToolboxTile("presets:bgremove", "BG Remove (BiRefNet)", "SOTA cutouts via BiRefNet / RMBG-2.0 / IS-Net / U2Net / SAM 2", "\uE91B", green, "Ready", green, true, "BiRefNet + RMBG-2.0"));
        AiTools.Add(new ToolboxTile("presets:superres", "Image Upscaler Pro", "Modern transformer SR: HAT / DAT / SwinIR / APISR / DRCT (spandrel)", "\uE799", blue, "Ready", green, true, "spandrel"));
        AiTools.Add(new ToolboxTile("presets:facerestore", "Face Restoration Pro", "CodeFormer + GFPGAN with fidelity / quality slider", "\uE77B", green, "Ready", green, true, "CodeFormer"));
        AiTools.Add(new ToolboxTile("presets:premiumtts", "Premium TTS", "Kokoro / F5-TTS zero-shot cloning / XTTS v2 multilingual", "\uEC4F", green, "Ready", green, true, "Kokoro + F5-TTS"));
        AiTools.Add(new ToolboxTile("presets:translatekit", "Translator (200 lang)", "Local NLLB-200 / MADLAD-400 -- text, files, SRT subtitles", "\uE774", blue, "Ready", green, true, "NLLB-200"));
        AiTools.Add(new ToolboxTile("presets:inpaint", "Object Removal (LaMa)", "LaMa + YOLO auto-detect: 'remove every car / person / bird'", "\uE91B", orange, "Ready", green, true, "LaMa + YOLOv11"));
        AudioTools.Add(new ToolboxTile("presets:audiomastering", "Audio Mastering", "Matchering reference-based mastering + EBU R128 loudnorm", "\uEC4F", red, "Ready", green, true, "Matchering"));
        DocumentTools.Add(new ToolboxTile("presets:ocrpro", "OCR Pro (Surya)", "Layout + text + tables + math, 90+ languages", "\uE8A1", blue, "Ready", green, true, "Surya"));

        // v2.9 wave (Coverage)
        OtherTools.Add(new ToolboxTile("presets:gametools", "Game ROM Tools", "IPS/BPS/UPS patches + N64 byteswap + CHD <-> CUE/BIN", "\uE7FC", green, "Ready", green, false, "UCX + chdman"));
        DocumentTools.Add(new ToolboxTile("presets:datasci", "Scientific Data", "CSV / Parquet / Feather / Avro / ORC / HDF5 / NetCDF / FITS / NPY / MAT", "\uE9D9", blue, "Ready", green, false, "pandas + pyarrow + astropy"));
        DocumentTools.Add(new ToolboxTile("presets:i18nkit", "Localization", "PO / MO / XLIFF / TMX / RESX / .strings / JSON / YAML / CSV", "\uE774", blue, "Ready", green, false, "Babel"));
        OtherTools.Add(new ToolboxTile("presets:pointcloud", "Point Clouds", "PLY / PCD / XYZ / PTS / OBJ / LAS / LAZ / E57 (LiDAR / 3D scans)", "\uF158", orange, "Ready", green, false, "Open3D + laspy + pye57"));
        OtherTools.Add(new ToolboxTile("presets:diskimage", "VM Disk Images", "RAW / QCOW2 / VMDK / VHD / VHDX / VDI / QED conversion", "\uE7C4", blue, "Ready", green, false, "qemu-img"));
        DocumentTools.Add(new ToolboxTile("presets:mailimport", "Outlook PST/OST", "Convert PST / OST -> MBOX / EML (libpff)", "\uE715", blue, "Ready", green, false, "libpff"));
        OtherTools.Add(new ToolboxTile("universal-convert", "Universal Convert", "Drop any file -> instantly see every preset that accepts it", "\uED0C", blue, "Ready", green, true, "UCX"));

        // v2.8 OSS engines
        AiTools.Add(new ToolboxTile("presets:sdkit", "Stable Diffusion", "txt2img / img2img / inpaint / x4 upscale (diffusers)", "\uE790", blue, "Ready", green, true, "diffusers + SD 1.5/2/XL"));
        AiTools.Add(new ToolboxTile("presets:speechenhance", "Speech Enhancer", "DeepFilterNet 3 SOTA denoise + dereverb for voice", "\uE767", green, "Ready", green, true, "DeepFilterNet"));
        AudioTools.Add(new ToolboxTile("presets:stemkit", "Stem Separator", "Vocals / drums / bass / other (Roformer / Demucs / MDX)", "\uEC4F", red, "Ready", green, true, "audio-separator"));
        DocumentTools.Add(new ToolboxTile("presets:pdfmarkdown", "PDF -> Markdown", "Layout-aware Markdown extraction (pymupdf4llm / marker)", "\uE8A5", green, "Ready", green, false, "pymupdf4llm"));
        ImageTools.Add(new ToolboxTile("presets:vectorkit", "Vector Converter", "AI / EPS / PS / EMF / WMF / SVG / CDR / VSD via Inkscape", "\uE8B7", green, "Ready", green, false, "Inkscape headless"));
        OtherTools.Add(new ToolboxTile("presets:lutgen", "3D LUT Generator", "Build .cube / .3dl from before/after grading reference frames", "\uE790", orange, "Ready", green, false, "UCX (numpy)"));
        DocumentTools.Add(new ToolboxTile("presets:fontsubset", "Webfont Subsetter", "Shrink TTF/OTF/WOFF -> WOFF2 to only used glyphs", "\uE8D2", blue, "Ready", green, false, "fontTools.subset"));
    }

    private void Tile_Click(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is ToolboxTile tile)
        {
            if (tile.StatusBadge == "Ready")
            {
                App.RequestNavigation(tile.RouteKey);
                return;
            }

            var info = new PlaceholderInfo(
                Title: tile.Title,
                Subtitle: tile.Description,
                IconGlyph: tile.Glyph,
                Headline: $"{tile.Title} is not available yet.",
                Description: tile.PoweredBy is not null
                    ? $"Planned engine: {tile.PoweredBy}. Import, preview, export, and recovery are not wired yet."
                    : "This tool is tracked, but the runnable workflow is not wired into this build.",
                StatusBadge: tile.StatusBadge,
                PoweredBy: tile.PoweredBy);

            App.RequestPlaceholderNavigation(info);
        }
    }
}

public sealed class ToolboxTile
{
    public string RouteKey { get; }
    public string Title { get; }
    public string Description { get; }
    public string Glyph { get; }
    public Brush AccentBrush { get; }
    public string StatusBadge { get; }
    public Brush StatusBrush { get; }
    public Visibility ShowAi { get; }
    public string? PoweredBy { get; }

    public ToolboxTile(string routeKey, string title, string description, string glyph,
        Brush accentBrush, string statusBadge, Brush statusBrush, bool isAi, string? poweredBy)
    {
        RouteKey = routeKey;
        Title = title;
        Description = description;
        Glyph = glyph;
        AccentBrush = accentBrush;
        StatusBadge = statusBadge;
        StatusBrush = statusBrush;
        ShowAi = isAi ? Visibility.Visible : Visibility.Collapsed;
        PoweredBy = poweredBy;
    }
}
