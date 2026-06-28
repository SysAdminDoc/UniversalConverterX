using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.UI.Services;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class HomePage : Page
{
    private readonly List<HomeSearchSuggestion> _allSuggestions = [];
    private string? _primaryUpdateUrl;

    public ObservableCollection<HomeActionTile> Actions { get; } = [];
    public ObservableCollection<HomeAiFeatureTile> AiFeatures { get; } = [];
    public ObservableCollection<HomeClusterTile> Clusters { get; } = [];

    public HomePage()
    {
        InitializeComponent();
        SeedDashboard();
        SeedSearch();

        ActionsGrid.ItemsSource = Actions;
        AiGrid.ItemsSource = AiFeatures;
        ClustersGrid.ItemsSource = Clusters;
        TaskSearchBox.ItemsSource = _allSuggestions;

        Loaded += HomePage_Loaded;
    }

    private void HomePage_Loaded(object sender, RoutedEventArgs e)
    {
        // Item 7 Phase 2: read the cached update probe — never hits the network from here.
        // UpdateCheckService writes the cache opportunistically on app start when the
        // user's CheckForUpdates toggle is on; we just surface what's already there.
        try
        {
            var svc = App.Services?.GetService<IUpdateCheckService>();
            var cache = svc?.GetCachedResults();
            if (cache is null) return;

            var pending = cache.Tools.Where(t => t.UpdateAvailable).ToList();
            if (pending.Count == 0) return;

            var names = string.Join(", ",
                pending.Select(t => string.IsNullOrEmpty(t.LatestVersion)
                    ? t.DisplayName
                    : $"{t.DisplayName} {t.LatestVersion}"));
            UpdateBanner.Message = $"New release available for: {names}.";
            _primaryUpdateUrl = pending.FirstOrDefault(t => !string.IsNullOrWhiteSpace(t.ReleaseUrl))?.ReleaseUrl;
            UpdateBannerActionButton.IsEnabled = !string.IsNullOrWhiteSpace(_primaryUpdateUrl);
            UpdateBanner.IsOpen = true;
        }
        catch
        {
            // Banner is purely informational; never block the page on a service hiccup.
        }
    }

    private void UpdateBannerAction_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_primaryUpdateUrl)) return;
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = _primaryUpdateUrl,
                UseShellExecute = true,
            });
        }
        catch
        {
            // Shell-launch can fail in locked-down environments — silent is fine here.
        }
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

        Actions.Add(new HomeActionTile("Converter", "Batch convert media, documents, images, e-books, PDFs, and 3D files.", "\uE895", green, greenSurface, "Ready", "Convert files", "converter"));
        Actions.Add(new HomeActionTile("Video Enhancer", "Upscale, denoise, anime-sharpen, and face-enhance clips locally.", "\uE7B3", blue, blueSurface, "Ready", "Enhance video", "ai-video-enhancer"));
        Actions.Add(new HomeActionTile("Compressor", "Compress video for web, email, and archive targets.", "\uE91F", cyan, blueSurface, "Ready", "Compress video", "compressor"));
        Actions.Add(new HomeActionTile("Downloader", "Paste URLs, choose quality, and save to the local queue.", "\uE896", blue, blueSurface, "Ready", "Download media", "downloader"));
        Actions.Add(new HomeActionTile("Recorder", "Capture fixed-duration desktop recordings with local FFmpeg processing.", "\uE7C8", red, blueSurface, "Ready", "Record screen", "recorder"));
        Actions.Add(new HomeActionTile("Toolbox", "Open utilities for subtitles, watermarks, audio, discs, and metadata.", "\uE713", orange, greenSurface, "Mapped", "Browse tools", "toolbox"));

        AiFeatures.Add(new HomeAiFeatureTile("Video Summarizer", "Create transcript-backed summaries from long recordings.", "\uE8D2", blue, "Planned", "ai-lab"));
        AiFeatures.Add(new HomeAiFeatureTile("AI Subtitle & Translation", "Generate editable caption files and translations.", "\uED1E", green, "Planned", "ai-lab"));
        AiFeatures.Add(new HomeAiFeatureTile("Watermark Remover", "Inpaint selected logos, text, or objects.", "\uE71B", orange, "Planned", "ai-lab"));
        AiFeatures.Add(new HomeAiFeatureTile("Image Enhancer", "Sharpen, denoise, upscale, and restore photos locally.", "\uEB9F", cyan, "Ready", "ai-image-enhancer"));
        AiFeatures.Add(new HomeAiFeatureTile("Noise Remover", "Reduce background noise in speech and camera audio.", "\uE767", blue, "Planned", "ai-lab"));
        AiFeatures.Add(new HomeAiFeatureTile("Vocal Remover", "Split vocals and instrumentals for editing.", "\uEC4F", red, "Planned", "ai-lab"));

        Clusters.Add(new HomeClusterTile("Create", "Edit and generate", "Trim clips, create subtitles, repair metadata, generate speech, and prepare chapters.", "\uE70F", green, greenSurface, "toolbox"));
        Clusters.Add(new HomeClusterTile("Repair", "Clean up media", "Remove noise, isolate vocals, restore photos, and remove selected backgrounds or watermarks.", "\uE950", blue, blueSurface, "ai-lab"));
        Clusters.Add(new HomeClusterTile("Export", "Prepare output", "Convert formats, compress files, extract frames, build GIFs, and prepare delivery presets.", "\uE8AB", orange, greenSurface, "toolbox"));
    }

    private void SeedSearch()
    {
        _allSuggestions.AddRange([
            new("Convert files", "Open the batch converter", "converter"),
            new("Compress video", "Open preset video compression", "compressor"),
            new("Trim a clip", "Open video editor trim workflow", "editor"),
            new("Download from URL", "Open downloader", "downloader"),
            new("Record screen", "Open desktop screen recorder", "recorder"),
            new("Video enhancer", "Open Real-ESRGAN video enhancement", "ai-video-enhancer"),
            new("Video denoise", "Run Real-ESRGAN video cleanup presets", "presets:realesrgan"),
            new("Anime video sharpen", "Run anime-focused Real-ESRGAN presets", "presets:anime-upscale"),
            new("Video face enhance", "Run CodeFormer frame enhancement presets", "presets:video-face-enhance"),
            new("Subtitle generator", "View AI Lab status", "ai-lab"),
            new("Watermark remover", "View AI Lab status", "ai-lab"),
            new("Background remover", "Open background remover", "ai-bgremove"),
            new("Vocal remover", "View AI Lab status", "ai-lab"),
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

    private void OpenLogFolder_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var logger = App.Services?.GetService<IStructuredLogger>();
            var dir = logger?.LogDirectory;
            if (string.IsNullOrWhiteSpace(dir)) return;
            Directory.CreateDirectory(dir);
            Process.Start(new ProcessStartInfo { FileName = dir, UseShellExecute = true });
        }
        catch
        {
            DiagnosticsStatusText.Text = "Couldn't open the log folder. Check %LocalAppData%\\UniversalConverterX\\logs.";
        }
    }

    private void ExportCrashBundle_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var logger = App.Services?.GetService<IStructuredLogger>();
            if (logger is null)
            {
                DiagnosticsStatusText.Text = "Logger unavailable; bundle export skipped.";
                return;
            }
            logger.Info("diagnostics", "user-initiated crash bundle export");
            var path = CrashBundle.Capture(logger, exception: null,
                note: "User-initiated bundle export from Home dashboard.");
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            {
                DiagnosticsStatusText.Text = "Bundle export failed (disk full or permission denied).";
                return;
            }
            DiagnosticsStatusText.Text = $"Bundle saved: {path}";
            Process.Start(new ProcessStartInfo
            {
                FileName = "explorer.exe",
                Arguments = $"/select,\"{path}\"",
                UseShellExecute = true,
            });
        }
        catch (Exception ex)
        {
            DiagnosticsStatusText.Text = $"Bundle export error: {ex.GetType().Name}.";
        }
    }
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
