using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;
using UniversalConverterX.Core.Utilities;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class VideoEnhancerPage : Page
{
    private const string QueueKey = "video-enhancer";
    private const string QueuePageName = "Video Enhancer";
    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v"
    ];

    private readonly ISidecarRunner _runner;
    private readonly ISidecarHealthService _healthService;
    private readonly IBatchQueueStore _queueStore;
    private readonly IAppJobCoordinator _jobCoordinator;
    private readonly IHistoryService _history;
    private readonly ObservableCollection<VeFileItem> _files = [];
    private readonly ObservableCollection<VeFinishedItem> _finished = [];
    private readonly List<VeModel> _models = [];
    private CancellationTokenSource? _cts;
    private bool _seedVr2ModelReady;
    private bool _seedVr2ActionRunning;
    private bool _anime4KReady;
    private bool _anime4KActionRunning;
    private bool _rifeReady;
    private bool _restoringQueue;
    private string? _pendingModelName;

    private bool _isReady;

    public VideoEnhancerPage()
    {
        InitializeComponent();
        _isReady = true;
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _healthService = App.Services.GetRequiredService<ISidecarHealthService>();
        _queueStore = App.Services.GetRequiredService<IBatchQueueStore>();
        _jobCoordinator = App.Services.GetRequiredService<IAppJobCoordinator>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        ShowWindowsVideoScalerStatus();
        RestorePersistedQueue();
        UpdateUi();
        _ = LoadModelsAsync();
        _ = RefreshSeedVr2ModelStatusAsync();
        _ = RefreshAnime4KStatusAsync();
        _ = RefreshRifeStatusAsync();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (e.Parameter is VideoEnhancerRerunRequest request)
            ApplyRerunRequest(request);
    }

    private void ApplyRerunRequest(VideoEnhancerRerunRequest request)
    {
        var settings = request.PageSettings ?? new Dictionary<string, string?>();
        _pendingModelName = settings.GetValueOrDefault("model");
        SelectTaggedItem(EngineCombo, settings.GetValueOrDefault("engine"));
        SelectTaggedItem(ScaleCombo, settings.GetValueOrDefault("scale"));
        SelectTaggedItem(Anime4KProfileCombo, settings.GetValueOrDefault("anime4kProfile"));
        SelectTaggedItem(SeedVr2ResolutionCombo, settings.GetValueOrDefault("resolution"));
        SelectTaggedItem(TargetFpsCombo, settings.GetValueOrDefault("targetFps"));
        if (double.TryParse(settings.GetValueOrDefault("crf"), NumberStyles.Float, CultureInfo.InvariantCulture, out var crf))
            CrfSlider.Value = crf;
        if (double.TryParse(settings.GetValueOrDefault("anime4kCrf"), NumberStyles.Float, CultureInfo.InvariantCulture, out var animeCrf))
            Anime4KCrfSlider.Value = animeCrf;
        foreach (var sourcePath in request.SourcePaths.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (File.Exists(sourcePath) && !_files.Any(file => file.Path.Equals(sourcePath, StringComparison.OrdinalIgnoreCase)))
                AddFile(sourcePath, updateUi: false);
        }
        UpdateUi();
    }

    private void ShowWindowsVideoScalerStatus()
    {
        var capability = _healthService.EvaluateWindowsVideoScaler();
        WindowsVsrStatusText.Text = capability.Status == "Ready"
            ? AppLocalizer.Get("Available for qualified frame pipelines")
            : AppLocalizer.Get("Unavailable on this system — choose Real-ESRGAN, Anime4K, or SeedVR2");
        WindowsVsrDetailText.Text = AppLocalizer.Format($"{capability.Detail} {capability.Remediation}").Trim();
    }

    private async Task LoadModelsAsync()
    {
        ModelCombo.PlaceholderText = AppLocalizer.Get("Discovering...");
        ModelCombo.IsEnabled = false;
        _models.Clear();
        ModelCombo.Items.Clear();

        var harvested = new List<VeModel>();
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        var result = await _runner.RunAsync(
            "realesrgan",
            ["list-models"],
            ct: cts.Token,
            onRawEvent: (evName, root) =>
            {
                if (evName != "model") return;
                harvested.Add(new VeModel
                {
                    Name = root.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "",
                    Location = root.TryGetProperty("location", out var l) ? l.GetString() ?? "" : "",
                });
            });

        if (result.ErrorCode == "sidecar_not_found")
        {
            ModelHintText.Text = AppLocalizer.Get("Build the realesrgan sidecar first: pwsh tools/realesrgan/build.ps1");
            ModelCombo.PlaceholderText = AppLocalizer.Get("Sidecar not built");
            UpdateUi();
            return;
        }

        _models.AddRange(harvested);
        if (_models.Count == 0)
        {
            ModelCombo.PlaceholderText = AppLocalizer.Get("No models found");
            ModelHintText.Text = AppLocalizer.Get("Run pwsh tools/realesrgan/build.ps1 to fetch the upstream model set.");
        }
        else
        {
            // Prefer realesr-animevideov3 as the default for video — much faster.
            int defaultIdx = -1;
            for (int i = 0; i < _models.Count; i++)
            {
                ModelCombo.Items.Add(new ComboBoxItem { Content = _models[i].Name, Tag = _models[i] });
                if (_models[i].Name.Contains("animevideov3", StringComparison.OrdinalIgnoreCase))
                    defaultIdx = i;
            }
            ModelCombo.SelectedIndex = defaultIdx >= 0 ? defaultIdx : 0;
            if (!string.IsNullOrWhiteSpace(_pendingModelName))
            {
                var pending = ModelCombo.Items
                    .OfType<ComboBoxItem>()
                    .FirstOrDefault(item => item.Tag is VeModel model
                        && string.Equals(model.Name, _pendingModelName, StringComparison.OrdinalIgnoreCase));
                if (pending is not null)
                    ModelCombo.SelectedItem = pending;
                _pendingModelName = null;
            }
            ModelCombo.IsEnabled = true;
            ModelHintText.Text = AppLocalizer.Format($"{_models.Count} model(s) discovered. realesr-animevideov3 is fastest for video.");
        }
        UpdateUi();
    }

    private async void RefreshModels_Click(object sender, RoutedEventArgs e) => await LoadModelsAsync();

    private void Engine_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (RealEsrganModelPanel is null || SeedVr2ModelPanel is null || Anime4KModelPanel is null ||
            RifeModelPanel is null ||
            RealEsrganQualityPanel is null || SeedVr2QualityPanel is null ||
            Anime4KQualityPanel is null || RifeQualityPanel is null || RunButton is null)
            return;
        var seedVr2 = IsSeedVr2Selected();
        var anime4K = IsAnime4KSelected();
        var rife = IsRifeSelected();
        RealEsrganModelPanel.Visibility = seedVr2 || anime4K || rife ? Visibility.Collapsed : Visibility.Visible;
        SeedVr2ModelPanel.Visibility = seedVr2 ? Visibility.Visible : Visibility.Collapsed;
        Anime4KModelPanel.Visibility = anime4K ? Visibility.Visible : Visibility.Collapsed;
        RifeModelPanel.Visibility = rife ? Visibility.Visible : Visibility.Collapsed;
        RealEsrganQualityPanel.Visibility = seedVr2 || anime4K || rife ? Visibility.Collapsed : Visibility.Visible;
        SeedVr2QualityPanel.Visibility = seedVr2 ? Visibility.Visible : Visibility.Collapsed;
        Anime4KQualityPanel.Visibility = anime4K ? Visibility.Visible : Visibility.Collapsed;
        RifeQualityPanel.Visibility = rife ? Visibility.Visible : Visibility.Collapsed;
        RunButton.Content = seedVr2
            ? AppLocalizer.Get("Restore with SeedVR2")
            : anime4K
                ? AppLocalizer.Get("Upscale with Anime4K")
                : rife
                    ? AppLocalizer.Get("Interpolate Video")
                    : AppLocalizer.Get("Upscale Video");
        var summary = BuildPlanSummary();
        foreach (var file in _files) file.PlanSummary = summary;
        PersistQueue();
        UpdateUi();
    }

    private async Task RefreshSeedVr2ModelStatusAsync()
    {
        if (_seedVr2ActionRunning) return;
        if (_runner.Locate("seedvr2") is null)
        {
            _seedVr2ModelReady = false;
            DownloadSeedVr2ModelButton.IsEnabled = false;
            SeedVr2ModelStatus.Text = AppLocalizer.Get("SeedVR2 sidecar is not installed in this build.");
            UpdateUi();
            return;
        }

        _seedVr2ActionRunning = true;
        _seedVr2ModelReady = false;
        DownloadSeedVr2ModelButton.IsEnabled = false;
        SeedVr2ModelStatus.Text = AppLocalizer.Get("Checking local model pack...");
        UpdateUi();
        try
        {
            var result = await _runner.RunAsync(
                "seedvr2",
                ["model-status"],
                ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromMinutes(2));
            _seedVr2ModelReady = result.Success;
            SeedVr2ModelStatus.Text = result.Success
                ? AppLocalizer.Get("Model ready — pinned local pack found.")
                : result.ErrorCode == "sidecar_not_found"
                    ? AppLocalizer.Get("SeedVR2 sidecar is not installed in this build.")
                    : AppLocalizer.Get("Model not installed. Review the license and download it when ready.");
        }
        finally
        {
            _seedVr2ActionRunning = false;
            DownloadSeedVr2ModelButton.IsEnabled = _runner.Locate("seedvr2") is not null;
            UpdateUi();
        }
    }

    private async void DownloadSeedVr2Model_Click(object sender, RoutedEventArgs e)
    {
        if (_seedVr2ActionRunning || _runner.Locate("seedvr2") is null) return;

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = AppLocalizer.Get("Download the SeedVR2 restoration pack?"),
            Content = AppLocalizer.Get("This downloads pinned, SHA-256 verified Apache-2.0 runtime and model snapshots (approximately 3.9 GB). SeedVR2 requires an NVIDIA CUDA GPU with at least 10 GB VRAM; 12 GB or more is recommended. UCX never downloads or updates this pack during restoration."),
            PrimaryButtonText = AppLocalizer.Get("Accept & download"),
            CloseButtonText = AppLocalizer.Get("Cancel"),
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;

        _seedVr2ActionRunning = true;
        _seedVr2ModelReady = false;
        DownloadSeedVr2ModelButton.IsEnabled = false;
        SeedVr2ModelStatus.Text = AppLocalizer.Get("Downloading pinned SeedVR2 pack...");
        UpdateUi();
        try
        {
            var progress = new Progress<SidecarProgress>(value =>
                DispatcherQueue.TryEnqueue(() =>
                    SeedVr2ModelStatus.Text = string.IsNullOrWhiteSpace(value.Stage)
                        ? AppLocalizer.Format($"Downloading... {value.Percent:F0}%")
                        : AppLocalizer.Format($"{value.Stage} ({value.Percent:F0}%)")));
            var result = await _runner.RunAsync(
                "seedvr2",
                ["download-model", "--accept-license"],
                progress,
                ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromHours(4));
            _seedVr2ModelReady = result.Success;
            SeedVr2ModelStatus.Text = result.Success
                ? AppLocalizer.Get("Model ready — pinned local pack installed.")
                : AppLocalizer.Format($"Download failed: {result.ErrorMessage ?? AppLocalizer.Get("Unknown error")}");
        }
        finally
        {
            _seedVr2ActionRunning = false;
            DownloadSeedVr2ModelButton.IsEnabled = true;
            UpdateUi();
        }
    }

    private async Task RefreshAnime4KStatusAsync()
    {
        if (_anime4KActionRunning) return;
        if (_runner.Locate("anime-upscale") is null)
        {
            _anime4KReady = false;
            DownloadAnime4KShadersButton.IsEnabled = false;
            Anime4KStatus.Text = AppLocalizer.Get("Anime4K sidecar is not installed in this build.");
            UpdateUi();
            return;
        }

        _anime4KActionRunning = true;
        _anime4KReady = false;
        DownloadAnime4KShadersButton.IsEnabled = false;
        Anime4KStatus.Text = AppLocalizer.Get("Checking mpv and local shader pack...");
        UpdateUi();
        try
        {
            var result = await _runner.RunAsync(
                "anime-upscale",
                ["shader-status"],
                ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromMinutes(2));
            _anime4KReady = result.Success;
            Anime4KStatus.Text = result.Success
                ? AppLocalizer.Get("Ready — mpv and the pinned Anime4K v4.0.1 shaders are available.")
                : result.ErrorMessage ?? AppLocalizer.Get("Anime4K is not ready.");
        }
        finally
        {
            _anime4KActionRunning = false;
            DownloadAnime4KShadersButton.IsEnabled = _runner.Locate("anime-upscale") is not null;
            UpdateUi();
        }
    }

    private async void DownloadAnime4KShaders_Click(object sender, RoutedEventArgs e)
    {
        if (_anime4KActionRunning || _runner.Locate("anime-upscale") is null) return;

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = AppLocalizer.Get("Download the Anime4K shader pack?"),
            Content = AppLocalizer.Get("This downloads the pinned, SHA-256 verified Anime4K v4.0.1 GLSL shader pack (MIT license, approximately 0.8 MB). Export remains local and also requires mpv on PATH, beside the sidecar, or in tools/_bin."),
            PrimaryButtonText = AppLocalizer.Get("Accept & download"),
            CloseButtonText = AppLocalizer.Get("Cancel"),
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;

        _anime4KActionRunning = true;
        _anime4KReady = false;
        DownloadAnime4KShadersButton.IsEnabled = false;
        Anime4KStatus.Text = AppLocalizer.Get("Downloading pinned Anime4K shaders...");
        UpdateUi();
        try
        {
            var progress = new Progress<SidecarProgress>(value =>
                DispatcherQueue.TryEnqueue(() =>
                    Anime4KStatus.Text = string.IsNullOrWhiteSpace(value.Stage)
                        ? AppLocalizer.Format($"Downloading... {value.Percent:F0}%")
                        : AppLocalizer.Format($"{value.Stage} ({value.Percent:F0}%)")));
            var result = await _runner.RunAsync(
                "anime-upscale",
                ["download-shaders", "--accept-license"],
                progress,
                ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromMinutes(5));
            Anime4KStatus.Text = result.Success
                ? AppLocalizer.Get("Shader pack installed; checking mpv...")
                : AppLocalizer.Format($"Download failed: {result.ErrorMessage ?? "Unknown error"}");
        }
        finally
        {
            _anime4KActionRunning = false;
            DownloadAnime4KShadersButton.IsEnabled = true;
        }
        await RefreshAnime4KStatusAsync();
    }

    private async Task RefreshRifeStatusAsync()
    {
        _rifeReady = false;
        if (_runner.Locate("clipforge") is null)
        {
            RifeStatusText.Text = AppLocalizer.Get("ClipForge sidecar is not installed in this build.");
            UpdateUi();
            return;
        }

        RifeStatusText.Text = AppLocalizer.Get("Checking pinned RIFE runtime and Vulkan readiness...");
        UpdateUi();
        try
        {
            var statusPreset = new UiPreset(
                "RIFE runtime status",
                "AI/Video",
                VideoExtensions,
                "{dir}/{stem}",
                "mp4",
                "clipforge",
                PresetInvocationMode.PerFile,
                ["rife-status"],
                "built-in:rife-status");
            var report = await _healthService.EvaluateAsync(statusPreset);
            _rifeReady = report.CanRun
                && report.Requirements.Any(requirement =>
                    requirement.Name.Contains("RIFE", StringComparison.OrdinalIgnoreCase)
                    && requirement.Status == "Ready");
            RifeStatusText.Text = AppLocalizer.Format($"{report.Summary}. {report.Detail}");
        }
        catch (Exception exception)
        {
            RifeStatusText.Text = AppLocalizer.Format($"RIFE readiness check failed: {exception.Message}");
        }
        UpdateUi();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Drop into upscale queue");
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        var items = await e.DataView.GetStorageItemsAsync();
        foreach (var item in items)
        {
            switch (item)
            {
                case StorageFile file: AddFile(file.Path); break;
                case StorageFolder folder: AddFolder(folder.Path); break;
            }
        }
    }

    private void DropZone_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        if (e.Pointer.PointerDeviceType == Microsoft.UI.Input.PointerDeviceType.Mouse &&
            !e.GetCurrentPoint(null).Properties.IsLeftButtonPressed)
            return;
        if (_files.Count == 0 && QueuePivot.SelectedIndex == 0)
            BrowseFiles();
    }

    private void Browse_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var ext in VideoExtensions) picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;
        foreach (var file in files) AddFile(file.Path);
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path)) return;
        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path)
                     .Where(f => VideoExtensions.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase))
                     .Take(50))
        {
            if (AddFile(file, updateUi: false)) added++;
        }
        StatusText.Text = added == 0
            ? AppLocalizer.Get("No supported videos found in that folder.")
            : AppLocalizer.Format($"Added {added} files from {path}.");
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => f.Path == path)) return false;
        var info = new FileInfo(path);
        if (!info.Exists) return false;
        if (!VideoExtensions.Contains(info.Extension, StringComparer.OrdinalIgnoreCase)) return false;
        _files.Add(new VeFileItem
        {
            Id = Guid.NewGuid().ToString("N"),
            Path = path,
            FileName = info.Name,
            SourceSummary = $"{FormatSize(info.Length)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            PlanSummary = BuildPlanSummary(),
            Progress = 0,
            StatusText = "Queued",
        });
        PersistQueue();
        if (updateUi) UpdateUi();
        return true;
    }

    private void RestorePersistedQueue()
    {
        var queue = _queueStore.Load(QueueKey);
        if (queue is null || queue.Jobs.Count == 0)
            return;

        _restoringQueue = true;
        try
        {
            if (queue.Settings.TryGetValue("engine", out var engine)
                && !string.IsNullOrWhiteSpace(engine))
            {
                for (var i = 0; i < EngineCombo.Items.Count; i++)
                {
                    if (EngineCombo.Items[i] is ComboBoxItem { Tag: string tag }
                        && tag.Equals(engine, StringComparison.OrdinalIgnoreCase))
                    {
                        EngineCombo.SelectedIndex = i;
                        break;
                    }
                }
            }
            if (queue.Settings.TryGetValue("targetFps", out var targetFps)
                && int.TryParse(targetFps, NumberStyles.Integer, CultureInfo.InvariantCulture, out var fps))
            {
                for (var i = 0; i < TargetFpsCombo.Items.Count; i++)
                {
                    if (TargetFpsCombo.Items[i] is ComboBoxItem { Tag: string tag }
                        && tag.Equals(fps.ToString(CultureInfo.InvariantCulture), StringComparison.Ordinal))
                    {
                        TargetFpsCombo.SelectedIndex = i;
                        break;
                    }
                }
            }

            foreach (var job in queue.Jobs)
            {
                if (string.IsNullOrWhiteSpace(job.SourcePath)
                    || _files.Any(file => file.Path.Equals(job.SourcePath, StringComparison.OrdinalIgnoreCase)))
                    continue;

                FileInfo? sourceInfo = null;
                try
                {
                    if (File.Exists(job.SourcePath))
                        sourceInfo = new FileInfo(job.SourcePath);
                }
                catch (IOException) { }
                var extension = Path.GetExtension(job.SourcePath);
                _files.Add(new VeFileItem
                {
                    Id = string.IsNullOrWhiteSpace(job.Id) ? Guid.NewGuid().ToString("N") : job.Id,
                    Path = job.SourcePath,
                    FileName = Path.GetFileName(job.SourcePath),
                    SourceSummary = sourceInfo is null
                        ? "Source file is missing"
                        : $"{FormatSize(sourceInfo.Length)} - {extension.TrimStart('.').ToUpperInvariant()}",
                    PlanSummary = BuildPlanSummary(),
                    OutputPath = job.OutputPath,
                    Engine = job.Engine,
                    ErrorMessage = job.ErrorMessage,
                    Provenance = job.Provenance,
                    PersistedArgs = [.. job.Args],
                    StatusText = RestoreStatus(job.Status),
                });
            }
        }
        finally
        {
            _restoringQueue = false;
        }

        if (_files.Count > 0)
            StatusText.Text = AppLocalizer.Format($"Restored {_files.Count} video enhancement job(s) from the previous session.");
    }

    private void PersistQueue()
    {
        if (_restoringQueue)
            return;

        var activeJobs = _files
            .Where(file => !file.StatusText.Equals("Done", StringComparison.OrdinalIgnoreCase))
            .Select(file => new PersistedBatchJob
            {
                Id = string.IsNullOrWhiteSpace(file.Id) ? Guid.NewGuid().ToString("N") : file.Id,
                SourcePath = file.Path,
                OutputPath = file.OutputPath,
                Engine = string.IsNullOrWhiteSpace(file.Engine) ? SelectedEngine() : file.Engine,
                Action = IsRifeSelected() ? "interpolate" : "enhance",
                Preset = BuildPlanSummary(),
                Args = file.PersistedArgs,
                Status = NormalizePersistedStatus(file.StatusText),
                ErrorMessage = file.ErrorMessage,
                Provenance = file.Provenance,
            })
            .ToList();

        if (activeJobs.Count == 0)
        {
            _queueStore.Clear(QueueKey);
            _jobCoordinator.NotifyJobsChanged();
            return;
        }

        _queueStore.Save(new PersistedBatchQueue
        {
            QueueKey = QueueKey,
            PageName = QueuePageName,
            Settings = new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
            {
                ["engine"] = SelectedEngine(),
                ["targetFps"] = SelectedInt(TargetFpsCombo, 60).ToString(CultureInfo.InvariantCulture),
            },
            Jobs = activeJobs,
        });
        _jobCoordinator.NotifyJobsChanged();
    }

    private static string RestoreStatus(string? status) => status?.ToLowerInvariant() switch
    {
        "interrupted" or "running" or "converting" or "cancelling" => "Interrupted - ready to retry",
        "failed" => "Failed - ready to retry",
        "cancelled" => "Cancelled - ready to retry",
        "skipped" => "Skipped",
        _ => "Queued",
    };

    private static string NormalizePersistedStatus(string? status)
    {
        if (status?.StartsWith("Interrupted", StringComparison.OrdinalIgnoreCase) == true)
            return "Interrupted";
        if (status?.StartsWith("Failed", StringComparison.OrdinalIgnoreCase) == true)
            return "Failed";
        if (status?.StartsWith("Cancelled", StringComparison.OrdinalIgnoreCase) == true)
            return "Cancelled";
        if (status?.StartsWith("Skipped", StringComparison.OrdinalIgnoreCase) == true)
            return "Skipped";
        if (status?.Equals("Enhancing", StringComparison.OrdinalIgnoreCase) == true
            || status?.Equals("Interpolating", StringComparison.OrdinalIgnoreCase) == true
            || status?.EndsWith("%", StringComparison.Ordinal) == true)
            return "Running";
        return "Queued";
    }

    private void RemoveQueued_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        if (sender is Button button && button.Tag is VeFileItem item)
        {
            _files.Remove(item);
            PersistQueue();
            UpdateUi();
        }
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null || _files.Count == 0) return;
        if (!await PageDialogService.ConfirmClearAsync(
                this, "Clear queue?",
                $"Remove {_files.Count} queued clip(s)? Finished upscales stay available."))
            return;
        _files.Clear();
        PersistQueue();
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (EmptyState is null) return;
        UpdateUi();
    }

    private void Settings_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (!_isReady) return;
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
        PersistQueue();
        UpdateStatusText();
    }

    private void PreviewSample_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0)
        {
            StatusText.Text = AppLocalizer.Get("Add a video before rendering a representative sample.");
            return;
        }

        var seedVr2 = IsSeedVr2Selected();
        var anime4K = IsAnime4KSelected();
        var rife = IsRifeSelected();
        var model = (ModelCombo.SelectedItem as ComboBoxItem)?.Tag as VeModel;
        if (!seedVr2 && !anime4K && !rife && model is null)
        {
            StatusText.Text = AppLocalizer.Get("Pick a model first.");
            return;
        }

        var item = _files[0];
        var scale = SelectedInt(ScaleCombo, 2);
        var resolution = SelectedInt(SeedVr2ResolutionCombo, 720);
        var targetFps = SelectedInt(TargetFpsCombo, 60);
        var animeProfile = SelectedTag(Anime4KProfileCombo, "a");
        var outputPath = BuildOutputPath(
            item.Path, seedVr2, anime4K, rife, scale, resolution, animeProfile, targetFps);
        var arguments = BuildInvocationArguments(item.Path, outputPath, model);
        App.RequestNavigation("vmaf", new RepresentativePreviewRequest(
            Surface: "video-enhancer",
            SourcePath: item.Path,
            Engine: rife ? "clipforge" : seedVr2 ? "seedvr2" : anime4K ? "anime-upscale" : "realesrgan",
            Arguments: arguments,
            Promotion: new RepresentativePreviewPromotion(
                Surface: "video-enhancer",
                SourcePath: item.Path,
                OutputDirectory: Path.GetDirectoryName(outputPath),
                OutputFormat: Path.GetExtension(outputPath).TrimStart('.'),
                PageSettings: BuildEnhancerSettings(model))));
    }

    private Dictionary<string, string?> BuildEnhancerSettings(VeModel? model) =>
        new(StringComparer.OrdinalIgnoreCase)
        {
            ["engine"] = SelectedEngine(),
            ["model"] = model?.Name,
            ["scale"] = SelectedInt(ScaleCombo, 2).ToString(CultureInfo.InvariantCulture),
            ["crf"] = ((int)CrfSlider.Value).ToString(CultureInfo.InvariantCulture),
            ["anime4kProfile"] = SelectedTag(Anime4KProfileCombo, "a"),
            ["anime4kCrf"] = ((int)Anime4KCrfSlider.Value).ToString(CultureInfo.InvariantCulture),
            ["resolution"] = SelectedInt(SeedVr2ResolutionCombo, 720).ToString(CultureInfo.InvariantCulture),
            ["targetFps"] = SelectedInt(TargetFpsCombo, 60).ToString(CultureInfo.InvariantCulture),
        };

    private void Crf_Changed(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (CrfLabel is null) return;
        var crf = (int)e.NewValue;
        var hint = crf switch
        {
            <= 17 => "visually lossless",
            <= 22 => "high quality",
            <= 26 => "balanced",
            <= 30 => "compressed",
            _ => "very compressed",
        };
        CrfLabel.Text = AppLocalizer.Format($"CRF {crf} ({hint})");
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
        PersistQueue();
    }

    private void Anime4KCrf_Changed(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (Anime4KCrfLabel is null) return;
        var crf = (int)e.NewValue;
        var hint = crf switch
        {
            <= 17 => "visually lossless",
            <= 22 => "high quality",
            <= 26 => "balanced",
            <= 30 => "compressed",
            _ => "very compressed",
        };
        Anime4KCrfLabel.Text = AppLocalizer.Format($"CRF {crf} ({hint})");
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
        PersistQueue();
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null) return;
        var seedVr2 = IsSeedVr2Selected();
        var anime4K = IsAnime4KSelected();
        var rife = IsRifeSelected();
        VeModel? model = (ModelCombo.SelectedItem as ComboBoxItem)?.Tag as VeModel;
        if (!seedVr2 && !anime4K && !rife && model is null)
        {
            StatusText.Text = AppLocalizer.Get("Pick a model first.");
            return;
        }
        if (seedVr2 && !_seedVr2ModelReady)
        {
            StatusText.Text = AppLocalizer.Get("Download the SeedVR2 model pack before restoration.");
            return;
        }
        if (anime4K && !_anime4KReady)
        {
            StatusText.Text = AppLocalizer.Get("Install mpv and download the Anime4K shader pack before upscaling.");
            return;
        }
        if (rife && !_rifeReady)
        {
            StatusText.Text = AppLocalizer.Get("Install the pinned RIFE runtime and a Vulkan-capable driver before interpolation.");
            return;
        }
        var scale = SelectedInt(ScaleCombo, 2);
        var resolution = SelectedInt(SeedVr2ResolutionCombo, 720);
        var targetFps = SelectedInt(TargetFpsCombo, 60);
        var crf = anime4K ? (int)Anime4KCrfSlider.Value : (int)CrfSlider.Value;
        var anime4KProfile = SelectedTag(Anime4KProfileCombo, "a");

        var jobs = _files.ToList();
        var completed = 0; var failed = 0;

        _cts = new CancellationTokenSource();
        RunButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        var handles = jobs
            .Select(item => new AppJobHandle(QueueKey, item.Id))
            .ToList();
        foreach (var handle in handles)
            _jobCoordinator.RegisterCancellation(handle, _cts.Cancel);

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested) break;
                var outputPath = BuildOutputPath(item.Path, seedVr2, anime4K, rife, scale, resolution, anime4KProfile, targetFps);
                var args = BuildInvocationArguments(item.Path, outputPath, model);

                var itemHandle = new AppJobHandle(QueueKey, item.Id);
                item.Engine = seedVr2 ? "seedvr2" : anime4K ? "anime-upscale" : rife ? "clipforge" : "realesrgan";
                item.OutputPath = outputPath;
                item.PersistedArgs = [.. args];
                item.ErrorMessage = null;
                item.Progress = 0;
                item.StatusText = seedVr2 ? "Restoring" : anime4K ? "Anime4K" : rife ? "Interpolating" : "Upscaling";
                _jobCoordinator.UpdateStatus(itemHandle, "Running");
                PersistQueue();
                StatusText.Text = seedVr2
                    ? AppLocalizer.Format($"Restoring {item.FileName} with SeedVR2 at {resolution}p... ({completed + failed + 1}/{jobs.Count})")
                    : anime4K
                    ? AppLocalizer.Format($"Upscaling {item.FileName} with Anime4K Mode {anime4KProfile.ToUpperInvariant()}... ({completed + failed + 1}/{jobs.Count})")
                    : rife
                    ? AppLocalizer.Format($"Interpolating {item.FileName} to {targetFps} FPS with RIFE... ({completed + failed + 1}/{jobs.Count})")
                    : AppLocalizer.Format($"Upscaling {item.FileName} \u00d7{scale}... ({completed + failed + 1}/{jobs.Count})");

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = string.IsNullOrEmpty(p.Stage)
                        ? $"{p.Percent:F0}%"
                        : $"{p.Percent:F0}% - {p.Stage}";
                }));
                var log = new Progress<SidecarLog>(_ => { });

                var jobStartedAt = DateTime.UtcNow;
                SidecarResult result;
                try
                {
                    // Video upscale is slow per minute — generous watchdog timeout.
                    var sidecar = seedVr2 ? "seedvr2" : anime4K ? "anime-upscale" : rife ? "clipforge" : "realesrgan";
                    result = await _runner.RunAsync(sidecar, args, progress, log, _cts.Token,
                        silenceTimeout: seedVr2 || rife ? TimeSpan.FromHours(2) : TimeSpan.FromMinutes(60));
                }
                catch (OperationCanceledException)
                {
                    result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user.", 130);
                }

                if (result.Success && !IsValidSourcePreservingOutput(item.Path, result.OutputPath ?? outputPath))
                {
                    result = new SidecarResult(
                        false,
                        result.OutputPath,
                        result.SizeBytes,
                        "output_validation_failed",
                        "The output was not a non-empty file distinct from the source.",
                        result.ExitCode)
                    {
                        Provenance = result.Provenance,
                        Capability = result.Capability,
                    };
                }

                if (result.Success)
                {
                    completed++;
                    item.Progress = 100;
                    item.StatusText = "Done";
                    item.OutputPath = result.OutputPath ?? outputPath;
                    item.ErrorMessage = null;
                    _jobCoordinator.UpdateStatus(itemHandle, "Completed");
                }
                else
                {
                    failed++;
                    item.StatusText = result.ErrorCode == "cancelled" ? "Cancelled" : "Failed";
                    item.ErrorMessage = result.ErrorMessage;
                    _jobCoordinator.UpdateStatus(
                        itemHandle,
                        result.ErrorCode == "cancelled" ? "Cancelled" : "Failed",
                        result.ErrorMessage);
                }
                item.Provenance = result.Provenance is null
                    ? null
                    : JobProvenanceCodec.Serialize(result.Provenance);

                AddFinishedItem(item, result, outputPath);
                PersistQueue();
                if (result.ErrorCode != "cancelled")
                {
                    long? sourceBytes = null;
                    try { sourceBytes = new FileInfo(item.Path).Length; } catch { }
                    _ = _history.LogAsync(new HistoryRecord
                    {
                        Timestamp = jobStartedAt,
                        Engine = item.Engine,
                        Action = rife ? "interpolate" : "enhance",
                        SourcePath = item.Path,
                        OutputPath = result.Success ? result.OutputPath ?? outputPath : null,
                        SourceBytes = sourceBytes,
                        OutputBytes = result.Success ? result.SizeBytes : null,
                        DurationSeconds = Math.Max(0, (DateTime.UtcNow - jobStartedAt).TotalSeconds),
                        Success = result.Success,
                        ErrorCode = result.ErrorCode,
                        ErrorMessage = result.ErrorMessage,
                        Profile = BuildPlanSummary(),
                        Provenance = result.Provenance is null
                            ? null
                            : JobProvenanceCodec.Serialize(result.Provenance),
                    });
                }
                if (result.ErrorCode == "cancelled") break;
            }

            StatusText.Text = _cts.IsCancellationRequested
                ? AppLocalizer.Format($"Cancelled — {completed} completed, {failed} failed.")
                : AppLocalizer.Format($"Done — {completed} completed, {failed} failed.");

            if (_finished.Count > 0)
                QueuePivot.SelectedIndex = 1;
        }
        finally
        {
            foreach (var handle in handles)
                _jobCoordinator.UnregisterCancellation(handle);
            _cts?.Dispose();
            _cts = null;
            PersistQueue();
            UpdateUi(updateStatus: false);
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
        {
            _cts.Cancel();
            CancelButton.IsEnabled = false;
            StatusText.Text = AppLocalizer.Get("Cancelling...");
        }
    }

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string path)
            OpenContainingFolder(path);
    }

    private void AddFinishedItem(VeFileItem item, SidecarResult result, string outputPath)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush = (Brush)Application.Current.Resources["AccentRedBrush"];
        var size = result.SizeBytes ?? (File.Exists(outputPath) ? new FileInfo(outputPath).Length : 0);
        var details = result.Success
            ? $"{item.PlanSummary} — {(size > 0 ? FormatSize(size) : "saved")}"
            : (result.ErrorMessage ?? "Upscale failed");
        _finished.Insert(0, new VeFinishedItem
        {
            FileName = result.Success ? Path.GetFileName(outputPath) : item.FileName,
            Details = details,
            OutputPath = result.OutputPath ?? outputPath,
            SourcePath = item.Path,
            Success = result.Success,
            Glyph = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });
    }

    private void RetryFinished_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null || sender is not Button { Tag: VeFinishedItem finished } || finished.Success)
            return;

        var queued = _files.FirstOrDefault(file =>
            file.Path.Equals(finished.SourcePath, StringComparison.OrdinalIgnoreCase));
        if (queued is null)
        {
            AddFile(finished.SourcePath);
            queued = _files.FirstOrDefault(file =>
                file.Path.Equals(finished.SourcePath, StringComparison.OrdinalIgnoreCase));
        }
        if (queued is null)
        {
            StatusText.Text = AppLocalizer.Get("The source file is no longer available for retry.");
            return;
        }

        queued.StatusText = "Queued";
        queued.ErrorMessage = null;
        queued.Progress = 0;
        _finished.Remove(finished);
        PersistQueue();
        QueuePivot.SelectedIndex = 0;
        UpdateUi();
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasFiles = _files.Count > 0;
        var hasFinished = _finished.Count > 0;
        var seedVr2 = IsSeedVr2Selected();
        var anime4K = IsAnime4KSelected();
        var rife = IsRifeSelected();
        var hasModel = seedVr2
            ? _seedVr2ModelReady && _runner.Locate("seedvr2") is not null
            : anime4K
            ? _anime4KReady && _runner.Locate("anime-upscale") is not null
            : rife
            ? _rifeReady && _runner.Locate("clipforge") is not null
            : ModelCombo?.SelectedItem is not null;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;
        RunButton.IsEnabled = hasFiles && hasModel && _cts is null;
        PreviewSampleButton.IsEnabled = hasFiles && hasModel && _cts is null;
        ClearButton.IsEnabled = hasFiles && _cts is null;
        CancelButton.IsEnabled = _cts is not null;
        QueueSummaryText.Text = AppLocalizer.Format($"{_files.Count} queued / {_finished.Count} finished");
        CurrentSetupText.Text = BuildPlanSummary();
        if (updateStatus && _cts is null) UpdateStatusText();
    }

    private void UpdateStatusText()
    {
        StatusText.Text = _files.Count == 0
            ? AppLocalizer.Get("Drop video clips to start an enhancement queue.")
            : IsRifeSelected()
                ? AppLocalizer.Format($"Ready to interpolate {_files.Count} clip(s). {BuildPlanSummary()}")
                : AppLocalizer.Format($"Ready to enhance {_files.Count} clip(s). {BuildPlanSummary()}");
    }

    private string BuildPlanSummary()
    {
        if (ScaleCombo is null || EngineCombo is null) return "";
        if (IsSeedVr2Selected())
        {
            var resolution = SelectedInt(SeedVr2ResolutionCombo, 720);
            return $"SeedVR2 3B FP8 · {resolution}p · CUDA offline";
        }
        if (IsAnime4KSelected())
        {
            var profile = SelectedTag(Anime4KProfileCombo, "a").ToUpperInvariant();
            var animeCrf = Anime4KCrfSlider is null ? 18 : (int)Anime4KCrfSlider.Value;
            return $"Anime4K Mode {profile} · 2× · mpv GLSL · CRF {animeCrf}";
        }
        if (IsRifeSelected())
        {
            var targetFps = SelectedInt(TargetFpsCombo, 60);
            return $"RIFE {RifeModelLabel()} · {targetFps} FPS · Vulkan";
        }
        var model = (ModelCombo?.SelectedItem as ComboBoxItem)?.Tag is VeModel m ? m.Name : "no model";
        var scale = SelectedInt(ScaleCombo, 2);
        var crf = CrfSlider is null ? 20 : (int)CrfSlider.Value;
        return $"\u00d7{scale} · {model} · CRF {crf}";
    }

    private static string BuildOutputPath(
        string inputPath, bool seedVr2, bool anime4K, bool rife, int scale, int resolution,
        string anime4KProfile, int targetFps)
    {
        var dir = Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(inputPath);
        if (seedVr2)
            return EnsureUniquePath(Path.Combine(dir, $"{name}_seedvr2_{resolution}p.mp4"));
        if (anime4K)
            return EnsureUniquePath(Path.Combine(dir, $"{name}_anime4k_{anime4KProfile}_x2.mp4"));
        if (rife)
            return EnsureUniquePath(Path.Combine(dir, $"{name}_rife_{targetFps}fps.mp4"));
        var ext = Path.GetExtension(inputPath);
        if (string.IsNullOrEmpty(ext)) ext = ".mp4";
        return EnsureUniquePath(Path.Combine(dir, $"{name}_x{scale}{ext}"));
    }

    private static string EnsureUniquePath(string path)
    {
        if (!File.Exists(path)) return path;
        var dir = Path.GetDirectoryName(path) ?? ".";
        var name = Path.GetFileNameWithoutExtension(path);
        var ext = Path.GetExtension(path);
        for (var i = 1; i < 10_000; i++)
        {
            var candidate = Path.Combine(dir, $"{name} ({i}){ext}");
            if (!File.Exists(candidate)) return candidate;
        }
        return Path.Combine(dir, $"{name}-{Guid.NewGuid():N}{ext}");
    }

    private static bool IsValidSourcePreservingOutput(string sourcePath, string outputPath)
    {
        try
        {
            var source = Path.GetFullPath(sourcePath);
            var output = Path.GetFullPath(outputPath);
            return !string.Equals(source, output, StringComparison.OrdinalIgnoreCase)
                && File.Exists(output)
                && new FileInfo(output).Length > 0;
        }
        catch
        {
            return false;
        }
    }

    private static int SelectedInt(ComboBox combo, int fallback)
    {
        if (combo.SelectedItem is ComboBoxItem item &&
            int.TryParse(item.Tag?.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var v))
            return v;
        return fallback;
    }

    private static void SelectTaggedItem(ComboBox combo, string? tag)
    {
        if (string.IsNullOrWhiteSpace(tag)) return;
        var match = combo.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(item => string.Equals(
                item.Tag?.ToString(), tag, StringComparison.OrdinalIgnoreCase));
        if (match is not null)
            combo.SelectedItem = match;
    }

    private List<string> BuildInvocationArguments(string inputPath, string outputPath, VeModel? model)
    {
        if (IsSeedVr2Selected())
        {
            return
            [
                "restore",
                "--input", inputPath,
                "--output", outputPath,
                "--resolution", SelectedInt(SeedVr2ResolutionCombo, 720).ToString(CultureInfo.InvariantCulture),
            ];
        }

        if (IsAnime4KSelected())
        {
            return
            [
                "video",
                "--backend", "anime4k",
                "--profile", SelectedTag(Anime4KProfileCombo, "a"),
                "--input", inputPath,
                "--output", outputPath,
                "--scale", "2",
                "--crf", ((int)Anime4KCrfSlider.Value).ToString(CultureInfo.InvariantCulture),
            ];
        }

        if (IsRifeSelected())
        {
            return
            [
                "rife",
                "--input", inputPath,
                "--output", outputPath,
                "--target-fps", SelectedInt(TargetFpsCombo, 60).ToString(CultureInfo.InvariantCulture),
            ];
        }

        if (model is null)
            throw new InvalidOperationException("A Real-ESRGAN model is required.");
        return
        [
            "upscale-video",
            "--input", inputPath,
            "--output", outputPath,
            "--model", model.Name,
            "--scale", SelectedInt(ScaleCombo, 2).ToString(CultureInfo.InvariantCulture),
            "--crf", ((int)CrfSlider.Value).ToString(CultureInfo.InvariantCulture),
        ];
    }

    private static string SelectedTag(ComboBox combo, string fallback) =>
        combo.SelectedItem is ComboBoxItem item && item.Tag is string tag ? tag : fallback;

    private bool IsSeedVr2Selected() =>
        EngineCombo?.SelectedItem is ComboBoxItem { Tag: string tag } && tag == "seedvr2";

    private bool IsAnime4KSelected() =>
        EngineCombo?.SelectedItem is ComboBoxItem { Tag: string tag } && tag == "anime4k";

    private bool IsRifeSelected() =>
        EngineCombo?.SelectedItem is ComboBoxItem { Tag: string tag } && tag == "rife";

    private string SelectedEngine() =>
        EngineCombo?.SelectedItem is ComboBoxItem { Tag: string tag } ? tag : "realesrgan";

    private static string RifeModelLabel() => "rife-v4.6";

    private static void OpenContainingFolder(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        var folder = Directory.Exists(path) ? path : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder)) return;
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{folder}\"") { UseShellExecute = true });
        }
        catch { }
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1_073_741_824 => $"{bytes / 1_073_741_824.0:F1} GB",
        >= 1_048_576 => $"{bytes / 1_048_576.0:F1} MB",
        >= 1_024 => $"{bytes / 1_024.0:F1} KB",
        _ => $"{bytes} B",
    };

    internal sealed class VeModel
    {
        public string Name { get; init; } = "";
        public string Location { get; init; } = "";
    }
}

public sealed class VeFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _planSummary = "";
    public event PropertyChangedEventHandler? PropertyChanged;
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string SourceSummary { get; set; } = "";
    public string? OutputPath { get; set; }
    public string Engine { get; set; } = "";
    public string? ErrorMessage { get; set; }
    public string? Provenance { get; set; }
    public List<string> PersistedArgs { get; set; } = [];
    public double Progress { get => _progress; set => Set(ref _progress, value); }
    public string StatusText { get => _statusText; set => Set(ref _statusText, value); }
    public string PlanSummary { get => _planSummary; set => Set(ref _planSummary, value); }
    private void Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}

public sealed class VeFinishedItem
{
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public string SourcePath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush? AccentBrush { get; set; }
    public bool CanOpenFolder => !string.IsNullOrWhiteSpace(OutputPath);
    public bool CanRetry => !Success && !string.IsNullOrWhiteSpace(SourcePath);
}
