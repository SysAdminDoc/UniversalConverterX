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

        Tools.Add(new AiLabToolTile("Video Enhancer", "Upscale footage to 4K/8K, denoise, sharpen faces/anime, and smooth frame rate.", "\uE7B3", blue, "Wave 2", "Model cache + preview needed", "Real-ESRGAN / RIFE"));
        Tools.Add(new AiLabToolTile("Image Enhancer", "Sharpen, denoise, upscale, and restore photos without cloud processing.", "\uEB9F", cyan, "Wave 2", "Standalone workflow needed", "Real-ESRGAN"));
        Tools.Add(new AiLabToolTile("Background Remover", "Remove or replace video/image backgrounds and preserve alpha exports.", "\uE91B", green, "Wave 1", "Sidecar staged", "AlphaCut"));
        Tools.Add(new AiLabToolTile("Watermark Remover", "Detect selected logos, captions, objects, or people and inpaint the region.", "\uE71B", orange, "Wave 2", "Region UI needed", "VideoSubtitleRemover"));
        Tools.Add(new AiLabToolTile("AI Subtitle & Translation", "Generate, edit, translate, burn, or export SRT/VTT/ASS captions.", "\uED1E", green, "Wave 2", "Whisper pipeline needed", "Whisper"));
        Tools.Add(new AiLabToolTile("Video Summarizer", "Extract chapters, highlights, and written summaries from long recordings.", "\uE8D2", blue, "Wave 2", "Transcript pipeline needed", "Whisper + local LLM"));
        Tools.Add(new AiLabToolTile("Noise Remover", "Clean voice and camera audio with configurable denoise strength.", "\uE767", cyan, "Wave 2", "Audio model needed", "RNNoise / Demucs"));
        Tools.Add(new AiLabToolTile("Vocal Remover", "Split vocals and instrumentals for music and editing workflows.", "\uEC4F", red, "Wave 2", "Stem preview needed", "Demucs"));
        Tools.Add(new AiLabToolTile("Voice Changer", "Transform narration tone while preserving timing.", "\uE720", orange, "Future", "Model choice open", null));
        Tools.Add(new AiLabToolTile("Text-to-Speech", "Generate voiceover audio from script text.", "\uEC4F", green, "Future", "Voice catalog needed", null));
        Tools.Add(new AiLabToolTile("Speech-to-Text", "Transcribe audio/video into editable transcript files.", "\uE720", blue, "Future", "Can share subtitle pipeline", "Whisper"));
        Tools.Add(new AiLabToolTile("Old Photo Restoration", "Repair scratches, fading, stains, and soft detail in legacy images.", "\uE91B", cyan, "Future", "Photo-specific presets needed", null));
    }

    private void AiTool_Click(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is not AiLabToolTile tile)
            return;

        App.RequestPlaceholderNavigation(new PlaceholderInfo(
            Title: tile.Title,
            Subtitle: tile.Description,
            IconGlyph: tile.Glyph,
            Headline: $"{tile.Title} implementation scope",
            Description: tile.PoweredBy is null
                ? $"{tile.WorkflowHint}. This feature needs a model/runtime selection, preview contract, and batch export UI before it can ship."
                : $"{tile.WorkflowHint}. Planned engine: {tile.PoweredBy}. Next step is wiring import, preview, progress, and export through the shared sidecar contract.",
            StatusBadge: tile.Phase,
            PoweredBy: tile.PoweredBy));
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
    }
}
