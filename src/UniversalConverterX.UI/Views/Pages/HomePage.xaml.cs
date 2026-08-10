using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class HomePage : Page
{
    private readonly List<HomeSearchSuggestion> _allSuggestions = [];
    private readonly IHistoryService _history;
    private string? _primaryUpdateUrl;
    private bool _historyAttached;

    public ObservableCollection<HomeActionTile> Actions { get; } = [];
    public ObservableCollection<HomeRecentActivityItem> RecentActivity { get; } = [];

    public HomePage()
    {
        InitializeComponent();
        _history = App.Services.GetRequiredService<IHistoryService>();
        SeedDashboard();
        SeedSearch();

        ActionsRepeater.ItemsSource = Actions;
        RecentActivityList.ItemsSource = RecentActivity;
        TaskSearchBox.ItemsSource = _allSuggestions;

        Loaded += HomePage_Loaded;
        Unloaded += HomePage_Unloaded;
    }

    private void HomePage_Loaded(object sender, RoutedEventArgs e)
    {
        AttachHistory();
        RefreshRecentActivity();

        // Item 7 Phase 2: read the cached update probe — never hits the network from here.
        // UpdateCheckService writes the cache opportunistically on app start when the
        // user's CheckForUpdates toggle is on; we just surface what's already there.
        try
        {
            var svc = App.Services?.GetService<IUpdateCheckService>();
            var cache = svc?.GetCachedResults();
            if (cache is null) return;

            var pending = cache.Tools.Where(t => t.UpdateAvailable).ToList();
            var appUpdate = cache.Application;
            if (appUpdate?.UpdateAvailable == true)
            {
                UpdateBanner.Title = AppLocalizer.Format($"UniversalConverter X {appUpdate.LatestVersion ?? AppLocalizer.Get("update")} available");
                UpdateBanner.Severity = appUpdate.CompatibilityWarnings.Count > 0
                    ? InfoBarSeverity.Warning
                    : InfoBarSeverity.Informational;
                var compatibility = appUpdate.CompatibilityWarnings.Count > 0
                    ? " Before updating: " + string.Join(" ", appUpdate.CompatibilityWarnings)
                    : appUpdate.CompatibilityMetadataAvailable
                        ? " Custom preset and saved queue compatibility checks passed."
                        : "";
                var toolSuffix = pending.Count > 0
                    ? $" Tool updates are also available for {string.Join(", ", pending.Select(t => t.DisplayName))}."
                    : "";
                UpdateBanner.Message = compatibility.TrimStart() + toolSuffix;
                _primaryUpdateUrl = appUpdate.ReleaseUrl;
                UpdateBannerActionButton.IsEnabled = !string.IsNullOrWhiteSpace(_primaryUpdateUrl);
                UpdateBanner.IsOpen = true;
                return;
            }

            if (pending.Count == 0) return;

            var names = string.Join(", ",
                pending.Select(t => string.IsNullOrEmpty(t.LatestVersion)
                    ? t.DisplayName
                    : $"{t.DisplayName} {t.LatestVersion}"));
            UpdateBanner.Message = AppLocalizer.Format($"New release available for: {names}.");
            _primaryUpdateUrl = pending.FirstOrDefault(t => !string.IsNullOrWhiteSpace(t.ReleaseUrl))?.ReleaseUrl;
            UpdateBannerActionButton.IsEnabled = !string.IsNullOrWhiteSpace(_primaryUpdateUrl);
            UpdateBanner.IsOpen = true;
        }
        catch
        {
            // Banner is purely informational; never block the page on a service hiccup.
        }
    }

    private void HomePage_Unloaded(object sender, RoutedEventArgs e)
    {
        if (!_historyAttached)
            return;

        _history.Recent.CollectionChanged -= HistoryRecent_CollectionChanged;
        _historyAttached = false;
    }

    private void AttachHistory()
    {
        if (_historyAttached)
            return;

        _history.Recent.CollectionChanged += HistoryRecent_CollectionChanged;
        _historyAttached = true;
    }

    private void HistoryRecent_CollectionChanged(object? sender, NotifyCollectionChangedEventArgs e) =>
        RefreshRecentActivity();

    private void RefreshRecentActivity()
    {
        RecentActivity.Clear();
        foreach (var record in _history.Recent.Take(3))
            RecentActivity.Add(HomeRecentActivityItem.FromRecord(record));

        RecentEmptyState.Visibility = RecentActivity.Count == 0
            ? Visibility.Visible
            : Visibility.Collapsed;
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
        var red = (Brush)Application.Current.Resources["AccentRedBrush"];
        var blueSurface = (Brush)Application.Current.Resources["SurfaceLightBrush"];
        var greenSurface = (Brush)Application.Current.Resources["SurfaceSoftBrush"];
        var warmSurface = (Brush)Application.Current.Resources["SurfaceWarmBrush"];
        var dangerSurface = (Brush)Application.Current.Resources["SurfaceDangerBrush"];

        Actions.Add(new HomeActionTile("Converter", "Batch convert media, documents, images, e-books, and more.", "\uE895", green, greenSurface, "Convert files", "converter"));
        Actions.Add(new HomeActionTile("Video Enhancer", "Upscale, denoise, anime-sharpen, and restore clips locally.", "\uE7B3", blue, blueSurface, "Enhance video", "ai-video-enhancer"));
        Actions.Add(new HomeActionTile("Compressor", "Compress video for web, email, and archive targets.", "\uE91F", cyan, blueSurface, "Compress video", "compressor"));
        Actions.Add(new HomeActionTile("Downloader", "Paste URLs, choose quality, and save to the local queue.", "\uE896", blue, blueSurface, "Download media", "downloader"));
        Actions.Add(new HomeActionTile("Recorder", "Capture the desktop with local FFmpeg processing.", "\uE7C8", red, dangerSurface, "Record screen", "recorder"));
        Actions.Add(new HomeActionTile("Toolbox", "Open utilities for subtitles, metadata, audio, discs, and more.", "\uE713", orange, warmSurface, "Browse tools", "toolbox"));
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
            new("Auto crop", "Run ClipForge cropdetect presets", "presets:clipforge"),
            new("Intro outro", "Run ClipForge intro/outro presets", "presets:clipforge"),
            new("Lens correction", "Run ClipForge lens correction and stabilization presets", "presets:clipforge"),
            new("VR converter", "Run ClipForge 360 / VR projection presets", "presets:clipforge"),
            new("Metadata editor", "Run ExifTool metadata presets", "presets:exiftool-meta"),
            new("Subtitle remover", "Run VideoSubtitleRemover presets", "presets:videosubtitleremover"),
            new("Subtitle generator", "Open the local subtitle studio", "ai-subtitle"),
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

    private void WorkflowCard_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: string routeKey })
            App.RequestNavigation(routeKey);
    }

    private async void BrowseFiles_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var files = await picker.PickMultipleFilesAsync();
        if (files is null || files.Count == 0)
            return;

        NavigateToConverter(files.Select(file => file.Path));
    }

    private void FileIntake_DragOver(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
            return;

        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Add to the conversion queue");
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
        FileIntakeSurface.Background =
            (Brush)Application.Current.Resources["AccentPrimarySoftBrush"];
        FileIntakeSurface.BorderBrush =
            (Brush)Application.Current.Resources["AccentPrimaryHoverBrush"];
    }

    private void FileIntake_DragLeave(object sender, DragEventArgs e) =>
        ResetFileIntakeSurface();

    private async void FileIntake_Drop(object sender, DragEventArgs e)
    {
        ResetFileIntakeSurface();
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
            return;

        var items = await e.DataView.GetStorageItemsAsync();
        NavigateToConverter(items.Select(item => item switch
        {
            StorageFile file => file.Path,
            StorageFolder folder => folder.Path,
            _ => "",
        }));
    }

    private void ResetFileIntakeSurface()
    {
        FileIntakeSurface.Background =
            (Brush)Application.Current.Resources["HeroSurfaceBrush"];
        FileIntakeSurface.BorderBrush =
            (Brush)Application.Current.Resources["AccentPrimaryBrush"];
    }

    private static void NavigateToConverter(IEnumerable<string> paths)
    {
        var normalized = paths
            .Where(path => !string.IsNullOrWhiteSpace(path))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (normalized.Count == 0)
            return;

        App.RequestNavigation("converter", new FileIntakeRequest(normalized));
    }

    private void OpenHistory_Click(object sender, RoutedEventArgs e) =>
        App.RequestNavigation("history");

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
            DiagnosticsStatusText.Text = AppLocalizer.Get("Couldn't open the log folder. Check %LocalAppData%\\UniversalConverterX\\logs.");
        }
    }

    private async void ExportCrashBundle_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var logger = App.Services?.GetService<IStructuredLogger>();
            if (logger is null)
            {
                DiagnosticsStatusText.Text = AppLocalizer.Get("Logger unavailable; bundle export skipped.");
                return;
            }
            logger.Info("diagnostics", "user-initiated crash bundle export");
            var sidecarHealth = await BuildSidecarHealthSnapshotAsync();
            var path = CrashBundle.Capture(logger, exception: null,
                note: "User-initiated bundle export from Home dashboard.",
                sidecarHealth: sidecarHealth);
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            {
                DiagnosticsStatusText.Text = AppLocalizer.Get("Bundle export failed (disk full or permission denied).");
                return;
            }
            DiagnosticsStatusText.Text = AppLocalizer.Format($"Bundle saved: {path}");
            Process.Start(new ProcessStartInfo
            {
                FileName = "explorer.exe",
                Arguments = $"/select,\"{path}\"",
                UseShellExecute = true,
            });
        }
        catch (Exception ex)
        {
            DiagnosticsStatusText.Text = AppLocalizer.Format($"Bundle export error: {ex.GetType().Name}.");
        }
    }

    private static async Task<IReadOnlyList<SidecarHealthReport>> BuildSidecarHealthSnapshotAsync()
    {
        try
        {
            var cache = App.Services?.GetService<IUiPresetCache>();
            var health = App.Services?.GetService<ISidecarHealthService>();
            if (cache is null || health is null)
                return [];

            return await health.EvaluateAllAsync(cache.Get());
        }
        catch
        {
            return [];
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
    public string ActionText { get; }
    public string RouteKey { get; }

    public HomeActionTile(string title, string description, string glyph, Brush accentBrush,
        Brush accentSurfaceBrush, string actionText, string routeKey)
    {
        Title = title;
        Description = description;
        Glyph = glyph;
        AccentBrush = accentBrush;
        AccentSurfaceBrush = accentSurfaceBrush;
        ActionText = actionText;
        RouteKey = routeKey;
    }
}

public sealed class HomeRecentActivityItem
{
    public string Title { get; set; } = "";
    public string Subtitle { get; set; } = "";
    public string Timestamp { get; set; } = "";
    public string StatusText { get; set; } = "";
    public string Glyph { get; set; } = "";
    public Brush StatusBrush { get; set; } = null!;
    public Brush StatusSurfaceBrush { get; set; } = null!;

    public static HomeRecentActivityItem FromRecord(HistoryRecord record)
    {
        var success = record.Success;
        var displayPath = string.IsNullOrWhiteSpace(record.OutputPath)
            ? record.SourcePath
            : record.OutputPath;
        var title = Path.GetFileName(displayPath);
        if (string.IsNullOrWhiteSpace(title))
            title = string.IsNullOrWhiteSpace(record.Action) ? AppLocalizer.Get("Conversion job") : record.Action;

        return new HomeRecentActivityItem
        {
            Title = title,
            Subtitle = string.Join(" · ", new[] { record.Engine, record.Action }
                .Where(value => !string.IsNullOrWhiteSpace(value))),
            Timestamp = record.Timestamp.ToLocalTime().ToString("g", CultureInfo.CurrentCulture),
            StatusText = success ? AppLocalizer.Get("Completed") : AppLocalizer.Get("Needs attention"),
            Glyph = success ? "\uE73E" : "\uE783",
            StatusBrush = (Brush)Application.Current.Resources[
                success ? "AccentGreenBrush" : "AccentRedBrush"],
            StatusSurfaceBrush = (Brush)Application.Current.Resources[
                success ? "SurfaceSoftBrush" : "SurfaceDangerBrush"],
        };
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
