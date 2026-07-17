using System.Collections.ObjectModel;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class AiLabPage : Page
{
    public ObservableCollection<AiLabToolTile> Tools { get; } = [];

    public AiLabPage()
    {
        InitializeComponent();
        SeedTools();
        AiToolsGrid.ItemsSource = Tools;
    }

    private void SeedTools()
    {
        var blue = (Brush)Application.Current.Resources["AccentBlueBrush"];
        var cyan = (Brush)Application.Current.Resources["AccentCyanBrush"];
        var green = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var orange = (Brush)Application.Current.Resources["AccentOrangeBrush"];
        var red = (Brush)Application.Current.Resources["AccentRedBrush"];

        Tools.Add(new AiLabToolTile("Video Enhancer", "Upscale, denoise, anime-sharpen, and face-enhance videos frame-by-frame.", "\uE7B3", blue, "Ready", "Workflow + presets available", "Real-ESRGAN / Anime4K / SeedVR2 / CodeFormer"));
        Tools.Add(new AiLabToolTile("Image Enhancer", "Sharpen, denoise, upscale, and restore photos without cloud processing.", "\uEB9F", cyan, "Ready", "Workflow available", "Real-ESRGAN"));
        Tools.Add(new AiLabToolTile("Background Remover", "Remove or replace video/image backgrounds and preserve alpha exports.", "\uE91B", green, "Ready", "Workflow available", "AlphaCut"));
        Tools.Add(new AiLabToolTile("Watermark Remover", "Inpaint selected logos, captions, objects, or people.", "\uE71B", orange, "Planned", "Needs region selection UI", "VideoSubtitleRemover"));
        Tools.Add(new AiLabToolTile("AI Subtitle & Translation", "Generate, edit, translate, burn, or export SRT/VTT/ASS captions.", "\uED1E", green, "Ready", "Full local studio available", "Whisper + OPUS-MT ONNX"));
        Tools.Add(new AiLabToolTile("Video Summarizer", "Extract chapters, highlights, and written summaries from long recordings.", "\uE8D2", blue, "Planned", "Needs transcript pipeline", "Whisper + local LLM"));
        Tools.Add(new AiLabToolTile("Noise Remover", "Reduce steady noise in speech and camera audio.", "\uE767", cyan, "Planned", "Needs audio model", "RNNoise / Demucs"));
        Tools.Add(new AiLabToolTile("Vocal Remover", "Split vocals and instrumentals for music and editing workflows.", "\uEC4F", red, "Planned", "Needs stem preview", "Demucs"));
        Tools.Add(new AiLabToolTile("Voice Changer", "Transform narration tone while preserving timing.", "\uED28", orange, "Ready", "Workflow available", "FFmpeg filters"));
        Tools.Add(new AiLabToolTile("Text-to-Speech", "Generate local narration, dialogue, or a consented voice clone from script text.", "\uEC4F", green, "Ready", "Offline workflows available", "Kokoro / Dia2 / Chatterbox"));
        Tools.Add(new AiLabToolTile("Speech-to-Text", "Transcribe audio/video into editable transcript files.", "\uE720", blue, "Ready", "Workflow available", "Whisper + Parakeet"));
        Tools.Add(new AiLabToolTile("Old Photo Restoration", "Repair scratches, fading, stains, and soft detail in legacy images.", "\uE91B", cyan, "Ready", "Workflow available", "Real-ESRGAN / GFPGAN"));
    }

    private static readonly Dictionary<string, string> _titleToRoute = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Video Enhancer"]          = "ai-video-enhancer",
        ["Image Enhancer"]          = "ai-image-enhancer",
        ["Background Remover"]      = "ai-bgremove",
        ["Watermark Remover"]       = "ai-watermark",
        ["AI Subtitle & Translation"] = "ai-subtitle",
        ["Video Summarizer"]        = "ai-summarizer",
        ["Noise Remover"]           = "ai-noise",
        ["Vocal Remover"]           = "ai-vocal",
        ["Voice Changer"]           = "ai-voice-changer",
        ["Text-to-Speech"]          = "ai-tts",
        ["Speech-to-Text"]          = "ai-stt",
        ["Old Photo Restoration"]   = "ai-photo-restore",
    };

    private void AiTool_Click(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is not AiLabToolTile tile)
            return;

        if (_titleToRoute.TryGetValue(tile.Title, out var route))
            App.RequestNavigation(route);
    }

    private void OpenToolbox_Click(object sender, RoutedEventArgs e) =>
        App.RequestNavigation("toolbox");

    private void OpenConverter_Click(object sender, RoutedEventArgs e) =>
        App.RequestNavigation("converter");
}

public sealed class AiLabToolTile
{
    public string Title { get; set; }
    public string Description { get; set; }
    public string Glyph { get; set; }
    public Brush AccentBrush { get; set; }
    public Brush PhaseBrush { get; set; }
    public string Phase { get; set; }
    public string WorkflowHint { get; set; }
    public string? PoweredBy { get; set; }

    public AiLabToolTile(string title, string description, string glyph, Brush accentBrush,
        string phase, string workflowHint, string? poweredBy)
    {
        Title = title;
        Description = description;
        Glyph = glyph;
        AccentBrush = accentBrush;
        Phase = phase;
        WorkflowHint = workflowHint;
        PoweredBy = poweredBy;
        PhaseBrush = phase switch
        {
            "Ready" => (Brush)Application.Current.Resources["AccentGreenBrush"],
            "Planned" => (Brush)Application.Current.Resources["AccentOrangeBrush"],
            _        => (Brush)Application.Current.Resources["TextMutedBrush"],
        };
    }
}
