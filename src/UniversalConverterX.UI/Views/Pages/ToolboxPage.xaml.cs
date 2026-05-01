using System.Collections.ObjectModel;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

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

    public ToolboxPage()
    {
        InitializeComponent();
        SeedTiles();
        ImageGrid.ItemsSource = ImageTools;
        VideoGrid.ItemsSource = VideoTools;
        AiGrid.ItemsSource = AiTools;
        AudioGrid.ItemsSource = AudioTools;
        DocumentGrid.ItemsSource = DocumentTools;
        DiscGrid.ItemsSource = DiscTools;
        OtherGrid.ItemsSource = OtherTools;
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
        ImageTools.Add(new ToolboxTile("ai-portrait", "AI Portrait", "Apply portrait stylization filters", "\uE77B", blue, "Future", yellow, true, null));
        ImageTools.Add(new ToolboxTile("slideshow-maker", "Slideshow Maker", "Stitch images into a video slideshow", "\uE786", blue, "Future", yellow, false, null));
        ImageTools.Add(new ToolboxTile("metadata-editor", "Metadata Editor", "View and edit EXIF / XMP / IPTC tags", "\uE8B7", blue, "Future", yellow, false, null));

        // Video
        VideoTools.Add(new ToolboxTile("smart-trimmer", "Smart Trimmer", "Detect highlight ranges and trim", "\uE71D", green, "Planned", orange, true, "ClipForge"));
        VideoTools.Add(new ToolboxTile("scene-detect", "Scene Detection", "Find cuts via PySceneDetect; export to CSV / EDL CMX 3600", "\uE71D", blue, "Ready", green, false, "PySceneDetect"));
        VideoTools.Add(new ToolboxTile("timeline-preview", "Timeline Preview", "Thumbnail strip + audio waveform image for any video", "\uE71D", blue, "Ready", green, false, "ClipForge"));
        VideoTools.Add(new ToolboxTile("track-manager", "Track Manager", "Add or remove audio / subtitle / data tracks (no re-encode)", "\uE93F", blue, "Ready", green, false, "ClipForge"));
        VideoTools.Add(new ToolboxTile("auto-reframe", "Auto Reframe", "Convert horizontal to 9:16 / 1:1 / 4:5 (static or smart face track)", "\uE740", blue, "Ready", green, true, "Vertigo"));
        VideoTools.Add(new ToolboxTile("auto-crop", "Auto Crop", "Detect subject and crop accordingly", "\uE7A8", blue, "Future", yellow, true, null));
        VideoTools.Add(new ToolboxTile("ai-watermark", "Watermark Editor", "Add or remove text and image watermarks", "\uE71B", yellow, "Ready", blue, false, "VideoSubtitleRemover"));
        VideoTools.Add(new ToolboxTile("auto-highlight", "Auto Highlight", "Detect strong clip candidates", "\uE7C9", blue, "Future", yellow, true, null));
        VideoTools.Add(new ToolboxTile("intro-outro", "Intro & Outro", "Apply branded intros and outros", "\uE7AD", green, "Future", yellow, false, null));
        VideoTools.Add(new ToolboxTile("lens-correction", "Lens Correction", "Fix distortion, rolling shutter, stabilize", "\uE71E", blue, "Future", yellow, false, null));
        VideoTools.Add(new ToolboxTile("vr-converter", "VR Converter", "Equirectangular, fisheye, 360° to 2D", "\uE787", blue, "Future", yellow, false, null));
        VideoTools.Add(new ToolboxTile("frame-snapshot", "Frame Snapshot", "Extract precise frames as images", "\uE722", blue, "Ready", green, false, "FFmpeg"));
        VideoTools.Add(new ToolboxTile("ai-video-enhancer", "Video Upscaler", "Real-ESRGAN frame-by-frame video super-resolution (slow)", "\uE799", blue, "Ready", green, true, "Real-ESRGAN"));

        // AI
        AiTools.Add(new ToolboxTile("ai-bgremove", "Background Remover", "Remove or replace video background", "\uE91B", green, "Ready", green, true, "AlphaCut"));
        AiTools.Add(new ToolboxTile("subtitle-remover", "Subtitle Remover", "Remove hard-coded subtitles from selected regions", "\uE93B", blue, "Planned", orange, true, "VideoSubtitleRemover"));
        AiTools.Add(new ToolboxTile("ai-subtitle", "Auto Subtitle", "Generate SRT/VTT subtitles + optional video burn-in", "\uED1E", blue, "Ready", green, true, "Whisper"));
        AiTools.Add(new ToolboxTile("ai-vocal", "Vocal Remover", "Isolate or remove vocals from audio", "\uE767", red, "Ready", blue, true, "Demucs"));
        AiTools.Add(new ToolboxTile("ai-voice-changer", "Voice Changer", "AI voice transformation", "\uE720", red, "Future", yellow, true, null));
        AiTools.Add(new ToolboxTile("ai-tts", "Text-to-Speech", "Generate voiceovers from text — 322 voices, 50+ languages", "\uEC4F", green, "Ready", green, true, "edge-tts"));
        AiTools.Add(new ToolboxTile("ai-photo-restore", "Photo Restoration", "GFPGAN blind face restoration for old / degraded portraits", "\uE77B", green, "Ready", green, true, "GFPGAN"));
        AiTools.Add(new ToolboxTile("ai-stt", "Speech-to-Text", "Transcribe audio to text", "\uE720", green, "Ready", blue, true, "Whisper"));
        AiTools.Add(new ToolboxTile("lip-reading", "Lip Reading", "Visual speech recognition", "\uE909", blue, "Ready", blue, true, "LipSight"));

        // Audio
        AudioTools.Add(new ToolboxTile("audio-converter", "Audio Converter", "MP3, WAV, FLAC, AAC, OGG, OPUS", "\uEC4F", green, "Planned", orange, false, "FFmpeg"));
        AudioTools.Add(new ToolboxTile("audio-compressor", "Audio Compressor", "Reduce audio file size", "\uE91F", blue, "Future", yellow, false, null));
        AudioTools.Add(new ToolboxTile("ai-noise", "Noise Remover", "RNNoise broadband speech denoise (FFmpeg arnndn)", "\uE767", blue, "Ready", green, true, "RNNoise"));

        // Documents
        DocumentTools.Add(new ToolboxTile("document-converter", "Document Converter", "DOCX, PDF, ODT, RTF, XLSX, ODS, CSV, PPTX, EPUB, HTML", "\uE8A5", blue, "Ready", green, false, "LibreOffice"));
        DocumentTools.Add(new ToolboxTile("archive", "Archive Tool", "Pack / unpack 7z, ZIP, TAR, RAR (read), ISO, CAB, MSI", "\uE7B8", orange, "Ready", green, false, "7-Zip"));
        DocumentTools.Add(new ToolboxTile("pdf-tools", "PDF Tools", "Merge / split / rotate / extract / encrypt / compress (pikepdf)", "\uEA90", red, "Ready", green, false, "pikepdf"));
        DocumentTools.Add(new ToolboxTile("subtitle-converter", "Subtitle Converter", "SRT / VTT / ASS / SSA / SUB conversion + retime", "\uE93B", blue, "Ready", green, false, "pysubs2"));

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
        OtherTools.Add(new ToolboxTile("batch-rename", "Batch Rename", "Rename files with patterns", "\uE8AC", blue, "Future", yellow, false, null));
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
