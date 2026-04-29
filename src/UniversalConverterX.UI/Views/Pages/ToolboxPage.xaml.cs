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
        DiscGrid.ItemsSource = DiscTools;
        OtherGrid.ItemsSource = OtherTools;
    }

    private void SeedTiles()
    {
        var blue = (Brush)Application.Current.Resources["AccentBlueBrush"];
        var green = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var yellow = (Brush)Application.Current.Resources["AccentYellowBrush"];
        var red = (Brush)Application.Current.Resources["AccentRedBrush"];

        // Image
        ImageTools.Add(new ToolboxTile("image-converter", "Image Converter", "JPEG, PNG, HEIC, AVIF, JPEG XL, WebP, RAW, TIFF", "\uEB9F", blue, "Planned", green, false, "HEICShift"));
        ImageTools.Add(new ToolboxTile("gif-maker", "GIF Maker", "Create GIFs from videos or image sequences", "\uE909", green, "Planned", green, false, "GifStudio"));
        ImageTools.Add(new ToolboxTile("image-upscaler", "Image Upscaler", "AI super-resolution up to 4x", "\uE799", blue, "Planned", green, true, "Real-ESRGAN"));
        ImageTools.Add(new ToolboxTile("ai-portrait", "AI Portrait", "Apply portrait stylization filters", "\uE77B", blue, "Future", yellow, true, null));
        ImageTools.Add(new ToolboxTile("slideshow-maker", "Slideshow Maker", "Stitch images into a video slideshow", "\uE786", blue, "Future", yellow, false, null));
        ImageTools.Add(new ToolboxTile("metadata-editor", "Metadata Editor", "View and edit EXIF / XMP / IPTC tags", "\uE8B7", blue, "Future", yellow, false, null));

        // Video
        VideoTools.Add(new ToolboxTile("smart-trimmer", "Smart Trimmer", "Auto-detect highlights and trim", "\uE71D", green, "Planned", green, true, "ClipForge"));
        VideoTools.Add(new ToolboxTile("auto-reframe", "Auto Reframe", "Convert horizontal to 9:16 / 1:1 / 4:5", "\uE740", blue, "Planned", green, true, "Vertigo"));
        VideoTools.Add(new ToolboxTile("auto-crop", "Auto Crop", "Detect subject and crop accordingly", "\uE7A8", blue, "Future", yellow, true, null));
        VideoTools.Add(new ToolboxTile("watermark-editor", "Watermark Editor", "Add or remove text and image watermarks", "\uE71B", yellow, "Future", yellow, false, null));
        VideoTools.Add(new ToolboxTile("auto-highlight", "Auto Highlight", "Detect best clips automatically", "\uE7C9", blue, "Future", yellow, true, null));
        VideoTools.Add(new ToolboxTile("intro-outro", "Intro & Outro", "Apply branded intros and outros", "\uE7AD", green, "Future", yellow, false, null));
        VideoTools.Add(new ToolboxTile("lens-correction", "Lens Correction", "Fix distortion, rolling shutter, stabilize", "\uE71E", blue, "Future", yellow, false, null));
        VideoTools.Add(new ToolboxTile("vr-converter", "VR Converter", "Equirectangular, fisheye, 360° to 2D", "\uE787", blue, "Future", yellow, false, null));
        VideoTools.Add(new ToolboxTile("frame-snapshot", "Frame Snapshot", "Extract precise frames as images", "\uE722", blue, "Planned", green, false, "FrameSnap"));

        // AI
        AiTools.Add(new ToolboxTile("background-remover", "Background Remover", "Remove or replace video background", "\uE91B", green, "Planned", green, true, "AlphaCut"));
        AiTools.Add(new ToolboxTile("subtitle-remover", "Subtitle Remover", "AI-powered hard-coded subtitle removal", "\uE93B", blue, "Planned", green, true, "VideoSubtitleRemover"));
        AiTools.Add(new ToolboxTile("subtitle-editor", "Subtitle Editor", "Create and edit SRT/VTT/ASS subtitles", "\uED1E", blue, "Future", yellow, false, null));
        AiTools.Add(new ToolboxTile("caption-generator", "Caption Generator", "Auto-generate captions with Whisper", "\uE8D2", blue, "Future", yellow, true, null));
        AiTools.Add(new ToolboxTile("vocal-remover", "Vocal Remover", "Isolate or remove vocals from audio", "\uE767", red, "Future", yellow, true, null));
        AiTools.Add(new ToolboxTile("voice-changer", "Voice Changer", "AI voice transformation", "\uE720", red, "Future", yellow, true, null));
        AiTools.Add(new ToolboxTile("text-to-speech", "Text-to-Speech", "Generate voiceovers from text", "\uEC4F", green, "Future", yellow, true, null));
        AiTools.Add(new ToolboxTile("speech-to-text", "Speech-to-Text", "Transcribe audio to text", "\uE720", green, "Future", yellow, true, null));
        AiTools.Add(new ToolboxTile("lip-reading", "Lip Reading", "Visual speech recognition", "\uE909", blue, "Planned", green, true, "LipSight"));

        // Audio
        AudioTools.Add(new ToolboxTile("audio-converter", "Audio Converter", "MP3, WAV, FLAC, AAC, OGG, OPUS", "\uEC4F", green, "Planned", green, false, "FFmpeg"));
        AudioTools.Add(new ToolboxTile("audio-compressor", "Audio Compressor", "Reduce audio file size", "\uE91F", blue, "Future", yellow, false, null));
        AudioTools.Add(new ToolboxTile("noise-remover", "Noise Remover", "AI-powered noise reduction", "\uE767", blue, "Future", yellow, true, null));

        // Disc
        DiscTools.Add(new ToolboxTile("dvd-burn", "DVD Burn", "Burn videos to DVD", "\uE958", red, "Future", yellow, false, null));
        DiscTools.Add(new ToolboxTile("dvd-copy", "DVD Copy", "Copy or backup DVDs", "\uE958", red, "Future", yellow, false, null));
        DiscTools.Add(new ToolboxTile("cd-burner", "CD Burner", "Burn audio CDs", "\uE958", red, "Future", yellow, false, null));

        // Other (already covered above; placeholder for parity expansions)
        OtherTools.Add(new ToolboxTile("format-inspector", "Format Inspector", "Probe codecs, streams, and metadata", "\uE946", blue, "Future", yellow, false, null));
        OtherTools.Add(new ToolboxTile("batch-rename", "Batch Rename", "Rename files with patterns", "\uE8AC", blue, "Future", yellow, false, null));
    }

    private void Tile_Click(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is ToolboxTile tile)
        {
            var statusText = tile.StatusBadge switch
            {
                "Planned" => "Coming Soon",
                "Future" => "Coming Soon",
                _ => tile.StatusBadge
            };

            var info = new PlaceholderInfo(
                Title: tile.Title,
                Subtitle: tile.Description,
                IconGlyph: tile.Glyph,
                Headline: $"{tile.Title} arrives in a future release.",
                Description: tile.PoweredBy is not null
                    ? $"This tool will be powered by the {tile.PoweredBy} engine, integrated as a UCX sidecar."
                    : "This tool is on the roadmap. Functionality lands in a future v2.x release.",
                StatusBadge: statusText,
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
