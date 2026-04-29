using System.Collections.ObjectModel;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class HomePage : Page
{
    private readonly List<HomeSearchSuggestion> _allSuggestions = [];

    public ObservableCollection<HomeActionTile> Actions { get; } = [];
    public ObservableCollection<HomeAiFeatureTile> AiFeatures { get; } = [];
    public ObservableCollection<HomeClusterTile> Clusters { get; } = [];
    public ObservableCollection<HomePersonaTile> Personas { get; } = [];

    public HomePage()
    {
        InitializeComponent();
        SeedDashboard();
        SeedSearch();

        ActionsGrid.ItemsSource = Actions;
        AiGrid.ItemsSource = AiFeatures;
        ClustersGrid.ItemsSource = Clusters;
        PersonasGrid.ItemsSource = Personas;
        TaskSearchBox.ItemsSource = _allSuggestions;
    }

    private void SeedDashboard()
    {
        var blue = (Brush)Application.Current.Resources["AccentBlueBrush"];
        var cyan = (Brush)Application.Current.Resources["AccentCyanBrush"];
        var green = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var orange = (Brush)Application.Current.Resources["AccentOrangeBrush"];
        var yellow = (Brush)Application.Current.Resources["AccentYellowBrush"];
        var red = (Brush)Application.Current.Resources["AccentRedBrush"];
        var blueSurface = (Brush)Application.Current.Resources["SurfaceLightBrush"];
        var greenSurface = (Brush)Application.Current.Resources["SurfaceSoftBrush"];

        Actions.Add(new HomeActionTile("Converter", "Batch convert media, documents, images, e-books, PDFs, and 3D files.", "\uE895", green, greenSurface, "Ready", "Open converter", "converter"));
        Actions.Add(new HomeActionTile("Video Enhancer", "AI upscaling, denoise, face/anime detail, and frame interpolation workflow.", "\uE7B3", blue, blueSurface, "AI Lab", "Plan enhancement", "ai-lab"));
        Actions.Add(new HomeActionTile("Compressor", "Preserve quality while targeting web, email, and archive size budgets.", "\uE91F", cyan, blueSurface, "Ready", "Compress video", "compressor"));
        Actions.Add(new HomeActionTile("Downloader", "Paste a URL, choose quality, merge audio, and save to the local queue.", "\uE896", blue, blueSurface, "Ready", "Download media", "downloader"));
        Actions.Add(new HomeActionTile("Recorder", "Capture fixed-duration desktop recordings with local FFmpeg processing.", "\uE7C8", red, blueSurface, "Ready", "Record screen", "recorder"));
        Actions.Add(new HomeActionTile("Toolbox", "Open specialized tools for subtitles, watermark, audio, discs, metadata, and more.", "\uE713", orange, greenSurface, "29 tools", "Browse tools", "toolbox"));

        AiFeatures.Add(new HomeAiFeatureTile("Video Summarizer", "Condense long videos into searchable recaps.", "\uE8D2", blue, "Roadmap", "ai-lab"));
        AiFeatures.Add(new HomeAiFeatureTile("AI Subtitle & Translation", "Generate editable captions and bilingual subtitles.", "\uED1E", green, "Roadmap", "ai-lab"));
        AiFeatures.Add(new HomeAiFeatureTile("Watermark Remover", "Remove logos, text, or objects from selected regions.", "\uE71B", orange, "Roadmap", "ai-lab"));
        AiFeatures.Add(new HomeAiFeatureTile("Image Enhancer", "Sharpen, denoise, upscale, and restore photos locally.", "\uEB9F", cyan, "Roadmap", "ai-lab"));
        AiFeatures.Add(new HomeAiFeatureTile("Noise Remover", "Clean voice, music, and camera audio with AI models.", "\uE767", blue, "Roadmap", "ai-lab"));
        AiFeatures.Add(new HomeAiFeatureTile("Vocal Remover", "Split vocals and instrumentals for reuse.", "\uEC4F", red, "Roadmap", "ai-lab"));

        Clusters.Add(new HomeClusterTile("Creation Tools", "Edit and generate", "Video editor, text-to-speech, subtitles, metadata repair, chapters, intros, and highlight reels.", "\uE70F", green, greenSurface, "toolbox"));
        Clusters.Add(new HomeClusterTile("Enhancement Tools", "Fix and improve", "Noise removal, background removal, image/video enhancement, vocal isolation, and restoration workflows.", "\uE950", blue, blueSurface, "ai-lab"));
        Clusters.Add(new HomeClusterTile("Export & Conversion", "Deliver anywhere", "Format conversion, compression, merger, DVD/CD, snapshots, GIF, social aspect ratios, and web presets.", "\uE8AB", orange, greenSurface, "toolbox"));

        Personas.Add(new HomePersonaTile("Content Creator", "Batch convert camera files, download references, compress for upload, and generate captions."));
        Personas.Add(new HomePersonaTile("Video Lover", "Convert 4K/8K libraries to player-ready formats while preserving quality."));
        Personas.Add(new HomePersonaTile("Social Publisher", "Compress clips for platform limits and reframe to 9:16, 1:1, or 4:5."));
        Personas.Add(new HomePersonaTile("Educator", "Record lessons, clean audio, create subtitles, and export LMS-friendly files."));
        Personas.Add(new HomePersonaTile("Business Team", "Reuse saved presets for recurring conversion, compression, and delivery workflows."));
    }

    private void SeedSearch()
    {
        _allSuggestions.AddRange([
            new("Convert files", "Open the batch converter", "converter"),
            new("Compress video", "Open preset video compression", "compressor"),
            new("Trim a clip", "Open video editor trim workflow", "editor"),
            new("Download from URL", "Open downloader", "downloader"),
            new("Record screen", "Open desktop screen recorder", "recorder"),
            new("Video enhancer", "Open AI Lab", "ai-lab"),
            new("Subtitle generator", "Open AI Lab", "ai-lab"),
            new("Watermark remover", "Open AI Lab", "ai-lab"),
            new("Background remover", "Open AI Lab", "ai-lab"),
            new("Vocal remover", "Open AI Lab", "ai-lab"),
            new("Inspect file format", "Probe codecs, streams, and conversion targets", "format-inspector"),
            new("Extract video frames", "Open Frame Snapshot", "frame-snapshot"),
            new("Toolbox", "Browse all specialized tools", "toolbox"),
        ]);
    }

    private void TaskSearchBox_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput)
            return;

        var query = sender.Text.Trim();
        sender.ItemsSource = string.IsNullOrWhiteSpace(query)
            ? _allSuggestions
            : _allSuggestions
                .Where(s => s.Title.Contains(query, StringComparison.OrdinalIgnoreCase)
                    || s.Subtitle.Contains(query, StringComparison.OrdinalIgnoreCase))
                .ToList();
    }

    private void TaskSearchBox_SuggestionChosen(AutoSuggestBox sender, AutoSuggestBoxSuggestionChosenEventArgs args)
    {
        if (args.SelectedItem is HomeSearchSuggestion suggestion)
            sender.Text = suggestion.Title;
    }

    private void TaskSearchBox_QuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
    {
        var suggestion = args.ChosenSuggestion as HomeSearchSuggestion
            ?? _allSuggestions.FirstOrDefault(s =>
                s.Title.Equals(args.QueryText, StringComparison.OrdinalIgnoreCase))
            ?? _allSuggestions.FirstOrDefault(s =>
                s.Title.Contains(args.QueryText, StringComparison.OrdinalIgnoreCase)
                || s.Subtitle.Contains(args.QueryText, StringComparison.OrdinalIgnoreCase));

        if (suggestion is not null)
            App.RequestNavigation(suggestion.RouteKey);
    }

    private void ActionTile_Click(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is HomeActionTile tile)
            App.RequestNavigation(tile.RouteKey);
    }

    private void AiTile_Click(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is HomeAiFeatureTile tile)
            App.RequestNavigation(tile.RouteKey);
    }

    private void ClusterTile_Click(object sender, ItemClickEventArgs e)
    {
        if (e.ClickedItem is HomeClusterTile tile)
            App.RequestNavigation(tile.RouteKey);
    }

    private void OpenConverter_Click(object sender, RoutedEventArgs e) =>
        App.RequestNavigation("converter");

    private void OpenAiLab_Click(object sender, RoutedEventArgs e) =>
        App.RequestNavigation("ai-lab");

    private void OpenToolbox_Click(object sender, RoutedEventArgs e) =>
        App.RequestNavigation("toolbox");
}

public sealed class HomeActionTile
{
    public string Title { get; }
    public string Description { get; }
    public string Glyph { get; }
    public Brush AccentBrush { get; }
    public Brush AccentSurfaceBrush { get; }
    public string Badge { get; }
    public string ActionText { get; }
    public string RouteKey { get; }
    public Visibility BadgeVisibility => string.IsNullOrWhiteSpace(Badge) ? Visibility.Collapsed : Visibility.Visible;

    public HomeActionTile(string title, string description, string glyph, Brush accentBrush,
        Brush accentSurfaceBrush, string badge, string actionText, string routeKey)
    {
        Title = title;
        Description = description;
        Glyph = glyph;
        AccentBrush = accentBrush;
        AccentSurfaceBrush = accentSurfaceBrush;
        Badge = badge;
        ActionText = actionText;
        RouteKey = routeKey;
    }
}

public sealed class HomeAiFeatureTile
{
    public string Title { get; set; }
    public string Description { get; set; }
    public string Glyph { get; set; }
    public Brush AccentBrush { get; set; }
    public string StatusText { get; set; }
    public string RouteKey { get; set; }

    public HomeAiFeatureTile(string title, string description, string glyph, Brush accentBrush,
        string statusText, string routeKey)
    {
        Title = title;
        Description = description;
        Glyph = glyph;
        AccentBrush = accentBrush;
        StatusText = statusText;
        RouteKey = routeKey;
    }
}

public sealed class HomeClusterTile
{
    public string Title { get; set; }
    public string Subtitle { get; set; }
    public string Description { get; set; }
    public string Glyph { get; set; }
    public Brush AccentBrush { get; set; }
    public Brush AccentSurfaceBrush { get; set; }
    public string RouteKey { get; set; }

    public HomeClusterTile(string title, string subtitle, string description, string glyph,
        Brush accentBrush, Brush accentSurfaceBrush, string routeKey)
    {
        Title = title;
        Subtitle = subtitle;
        Description = description;
        Glyph = glyph;
        AccentBrush = accentBrush;
        AccentSurfaceBrush = accentSurfaceBrush;
        RouteKey = routeKey;
    }
}

public sealed class HomePersonaTile
{
    public string Title { get; set; }
    public string Description { get; set; }

    public HomePersonaTile(string title, string description)
    {
        Title = title;
        Description = description;
    }
}

public sealed class HomeSearchSuggestion
{
    public string Title { get; set; }
    public string Subtitle { get; set; }
    public string RouteKey { get; set; }

    public HomeSearchSuggestion(string title, string subtitle, string routeKey)
    {
        Title = title;
        Subtitle = subtitle;
        RouteKey = routeKey;
    }
}
