using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using UniversalConverterX.Core.Services;
using UniversalConverterX.UI.Services;
using Windows.Media.Core;
using Windows.Media.Playback;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class VmafAnalysisPage : Page
{
    private static readonly string[] VideoExts =
        [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"];

    private readonly ISidecarRunner _runner;
    private readonly IRepresentativePreviewService _previewService;
    private string? _reference;
    private string? _distorted;
    private RepresentativePreviewRequest? _previewRequest;
    private bool _syncingPlayers;
    private bool _renderingSample;

    public VmafAnalysisPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _previewService = App.Services.GetRequiredService<IRepresentativePreviewService>();
        ReferencePlayer.MediaPlayer.PlaybackSession.PositionChanged += ReferencePlayer_PositionChanged;
        DistortedPlayer.MediaPlayer.PlaybackSession.PositionChanged += DistortedPlayer_PositionChanged;
    }

    protected override async void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (e.Parameter is not RepresentativePreviewRequest request)
            return;

        _previewRequest = request;
        SampleComparisonPanel.Visibility = Visibility.Visible;
        UseSettingsButton.Visibility = Visibility.Collapsed;
        SampleStartBox.Value = request.StartSeconds;
        SampleDurationBox.Value = Math.Clamp(request.DurationSeconds, 3, 15);
        await RenderRepresentativeSampleAsync();
    }

    private async void PickReference_Click(object sender, RoutedEventArgs e)
    {
        var picked = await PickAsync();
        if (picked is null) return;
        _reference = picked;
        ReferenceLabel.Text = picked;
        _ = SetPlayerSourceAsync(ReferencePlayer, picked);
        UpdateUi();
    }

    private async void PickDistorted_Click(object sender, RoutedEventArgs e)
    {
        var picked = await PickAsync();
        if (picked is null) return;
        _distorted = picked;
        DistortedLabel.Text = picked;
        _ = SetPlayerSourceAsync(DistortedPlayer, picked);
        UpdateUi();
    }

    private async Task<string?> PickAsync()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var ext in VideoExts) picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var f = await picker.PickSingleFileAsync();
        return f?.Path;
    }

    private void UpdateUi()
    {
        RunButton.IsEnabled = _reference is not null && _distorted is not null;
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_reference is null || _distorted is null) return;
        ResetStats();
        RunButton.IsEnabled = false;

        var reference = _reference;
        var distorted = _distorted;
        var proxied = false;

        using var cts = new CancellationTokenSource(TimeSpan.FromHours(1));
        try
        {
            // ROADMAP Item 74 — optional 480p proxy pass. Downscaling both
            // inputs to a fast proxy gives an approximate VMAF far quicker
            // than a full-resolution run.
            if (ProxyToggle.IsOn)
            {
                StatusText.Text = AppLocalizer.Get("Generating 480p proxies...");
                var proxyReference = await GenerateProxyAsync(_reference, "reference", cts.Token);
                var proxyDistorted = proxyReference is null
                    ? null
                    : await GenerateProxyAsync(_distorted, "distorted", cts.Token);
                if (proxyReference is null || proxyDistorted is null)
                {
                    StatusText.Text = AppLocalizer.Get("Could not generate proxies; run without the fast pass or check the clipforge engine.");
                    return;
                }
                reference = proxyReference;
                distorted = proxyDistorted;
                proxied = true;
            }

            await RunVmafAsync(reference, distorted, proxied, cts.Token);
        }
        finally
        {
            RunButton.IsEnabled = true;
        }
    }

    private async Task RunVmafAsync(
        string reference,
        string distorted,
        bool proxied,
        CancellationToken cancellationToken)
    {
        StatusText.Text = proxied
            ? AppLocalizer.Get("Running approximate VMAF on 480p proxies...")
            : AppLocalizer.Get("Running VMAF -- this may take a few minutes for long clips.");

        var args = new List<string>
        {
            "vmaf",
            "--reference", reference,
            "--distorted", distorted,
        };

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            VmafProgress.Value = p.Percent;
        }));
        var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
        {
            LogText.Text += $"[{l.Level}] {l.Message}\n";
        }));

        var result = await _runner.RunAsync(
            "clipforge", args, progress, log,
            ct: cancellationToken,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName != "vmaf_summary") return;
                if (root.TryGetProperty("mean", out var mean))
                    StatMean.Text = mean.GetDouble().ToString("F2", CultureInfo.InvariantCulture);
                if (root.TryGetProperty("harmonic_mean", out var hm))
                    StatHarmonic.Text = hm.GetDouble().ToString("F2", CultureInfo.InvariantCulture);
                if (root.TryGetProperty("min", out var mn))
                    StatMin.Text = mn.GetDouble().ToString("F2", CultureInfo.InvariantCulture);
                if (root.TryGetProperty("below_70_percent", out var b70))
                    StatBelow70.Text = AppLocalizer.Format($"{b70.GetDouble():F1}%");
            }));

        StatusText.Text = result.Success
            ? proxied
                ? AppLocalizer.Get("Approximate VMAF complete (480p proxies). Re-run without the fast pass to confirm the full-resolution score.")
                : AppLocalizer.Get("VMAF complete. Higher mean = closer to reference (90+ is excellent, 70- is visibly degraded).")
            : AppLocalizer.Format($"VMAF failed: {result.ErrorMessage ?? result.ErrorCode}");
        VmafProgress.Value = result.Success ? 100 : 0;
    }

    private async void RenderSample_Click(object sender, RoutedEventArgs e)
    {
        await RenderRepresentativeSampleAsync();
    }

    private async Task RenderRepresentativeSampleAsync()
    {
        if (_previewRequest is null || _renderingSample)
            return;

        _renderingSample = true;
        RenderSampleButton.IsEnabled = false;
        UseSettingsButton.Visibility = Visibility.Collapsed;
        ResetStats();
        SampleEstimateText.Text = AppLocalizer.Get("Preparing representative sample...");
        StatusText.Text = AppLocalizer.Get("Rendering a representative sample with the selected settings...");

        var start = double.IsFinite(SampleStartBox.Value) ? SampleStartBox.Value : 0;
        var duration = double.IsFinite(SampleDurationBox.Value) ? SampleDurationBox.Value : 10;
        _previewRequest = _previewRequest with
        {
            StartSeconds = Math.Max(0, start),
            DurationSeconds = Math.Clamp(duration, 3, 15),
        };

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            VmafProgress.Value = p.Percent;
        }));
        var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
        {
            LogText.Text += $"[{l.Level}] {l.Message}\n";
        }));

        try
        {
            var result = await _previewService.RenderAsync(_previewRequest, progress, log);
            if (!result.Success || string.IsNullOrWhiteSpace(result.SourceSamplePath)
                || string.IsNullOrWhiteSpace(result.OutputSamplePath))
            {
                StatusText.Text = AppLocalizer.Format(
                    $"Representative sample failed: {result.ErrorMessage ?? result.ErrorCode ?? "unknown error"}");
                SampleEstimateText.Text = AppLocalizer.Get("No estimate is available until a sample renders successfully.");
                return;
            }

            _reference = result.SourceSamplePath;
            _distorted = result.OutputSamplePath;
            ReferenceLabel.Text = result.SourceSamplePath;
            DistortedLabel.Text = result.OutputSamplePath;
            await SetPlayerSourceAsync(ReferencePlayer, result.SourceSamplePath);
            await SetPlayerSourceAsync(DistortedPlayer, result.OutputSamplePath);
            SampleEstimateText.Text = FormatEstimate(result);
            UseSettingsButton.Visibility = Visibility.Visible;
            UpdateUi();

            await RunVmafAsync(
                result.SourceSamplePath,
                result.OutputSamplePath,
                proxied: false,
                CancellationToken.None);
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = AppLocalizer.Get("Representative sample rendering was cancelled.");
        }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Format($"Representative sample failed: {ex.Message}");
            SampleEstimateText.Text = AppLocalizer.Get("No estimate is available until a sample renders successfully.");
        }
        finally
        {
            _renderingSample = false;
            RenderSampleButton.IsEnabled = true;
            UpdateUi();
        }
    }

    private void UseSettings_Click(object sender, RoutedEventArgs e)
    {
        var promotion = _previewRequest?.Promotion;
        if (promotion is null)
            return;

        if (string.Equals(promotion.Surface, "compressor", StringComparison.OrdinalIgnoreCase))
        {
            App.RequestNavigation("compressor", new ConversionRerunRequest
            {
                Surface = "compressor",
                SourcePaths = [promotion.SourcePath],
                OutputFormat = promotion.OutputFormat,
                OutputDirectory = promotion.OutputDirectory,
                PageSettings = new Dictionary<string, string?>(
                    promotion.PageSettings, StringComparer.OrdinalIgnoreCase),
            });
            return;
        }

        App.RequestNavigation("ai-video-enhancer", new VideoEnhancerRerunRequest(
            [promotion.SourcePath],
            new Dictionary<string, string?>(promotion.PageSettings, StringComparer.OrdinalIgnoreCase)));
    }

    private async Task SetPlayerSourceAsync(MediaPlayerElement player, string path)
    {
        try
        {
            var file = await StorageFile.GetFileFromPathAsync(path);
            player.Source = MediaSource.CreateFromStorageFile(file);
        }
        catch
        {
            player.Source = null;
        }
    }

    private void ReferencePlayer_PositionChanged(MediaPlaybackSession sender, object args) =>
        SyncPlayerPosition(sender, DistortedPlayer.MediaPlayer.PlaybackSession);

    private void DistortedPlayer_PositionChanged(MediaPlaybackSession sender, object args) =>
        SyncPlayerPosition(sender, ReferencePlayer.MediaPlayer.PlaybackSession);

    private void SyncPlayerPosition(MediaPlaybackSession source, MediaPlaybackSession target)
    {
        if (_syncingPlayers)
            return;

        try
        {
            if (Math.Abs((target.Position - source.Position).TotalMilliseconds) < 150)
                return;

            _syncingPlayers = true;
            target.Position = source.Position;
        }
        catch
        {
            // A player can briefly have no media source while a new sample is
            // loading; playback synchronization is best effort.
        }
        finally
        {
            _syncingPlayers = false;
        }
    }

    private static string FormatEstimate(RepresentativePreviewResult result)
    {
        var estimate = result.Estimate;
        if (estimate is null)
            return AppLocalizer.Get("Estimate unavailable for this sample.");

        var outputSize = estimate.EstimatedOutputBytes is long bytes
            ? FormatSize(bytes)
            : AppLocalizer.Get("unknown size");
        var renderTime = estimate.EstimatedRenderSeconds is double seconds
            ? FormatDuration(seconds)
            : AppLocalizer.Get("unknown time");
        var cacheNote = result.CacheHit ? AppLocalizer.Get(" Cached preview.") : "";
        return AppLocalizer.Format($"Sample {result.SampleDurationSeconds:F1}s / {FormatSize(result.OutputSampleBytes)}. Full source {FormatDuration(result.SourceDurationSeconds)}: estimated {outputSize}, about {renderTime} to render.{cacheNote}");
    }

    private static string FormatDuration(double seconds)
    {
        if (!double.IsFinite(seconds) || seconds < 0)
            return AppLocalizer.Get("unknown time");
        return TimeSpan.FromSeconds(seconds).TotalHours >= 1
            ? TimeSpan.FromSeconds(seconds).ToString(@"h\:mm\:ss")
            : TimeSpan.FromSeconds(seconds).ToString(@"m\:ss");
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1_073_741_824 => $"{bytes / 1_073_741_824.0:F1} GB",
        >= 1_048_576 => $"{bytes / 1_048_576.0:F1} MB",
        >= 1_024 => $"{bytes / 1_024.0:F1} KB",
        _ => $"{bytes} B",
    };

    /// <summary>
    /// Generates a 480p preview proxy of <paramref name="source"/> via the
    /// clipforge proxy op, returning the proxy path or null on failure.
    /// </summary>
    private async Task<string?> GenerateProxyAsync(string source, string label, CancellationToken ct)
    {
        var cacheDir = System.IO.Path.Combine(
            System.IO.Path.GetTempPath(), "UniversalConverterX", "vmaf-proxies");
        try { System.IO.Directory.CreateDirectory(cacheDir); }
        catch { return null; }

        var proxyPath = System.IO.Path.Combine(
            cacheDir,
            $"{System.IO.Path.GetFileNameWithoutExtension(source)}-{label}-{Math.Abs(source.GetHashCode()):x8}-480p.mp4");

        var result = await _runner.RunAsync(
            "clipforge",
            ["proxy", "--input", source, "--output", proxyPath, "--height", "480"],
            ct: ct);

        return result.Success && System.IO.File.Exists(proxyPath) ? proxyPath : null;
    }

    private void ResetStats()
    {
        StatMean.Text = AppLocalizer.Get("--");
        StatHarmonic.Text = AppLocalizer.Get("--");
        StatMin.Text = AppLocalizer.Get("--");
        StatBelow70.Text = AppLocalizer.Get("--");
        LogText.Text = "";
        VmafProgress.Value = 0;
    }
}
