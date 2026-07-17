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
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class VideoEnhancerPage : Page
{
    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v"
    ];

    private readonly ISidecarRunner _runner;
    private readonly ISidecarHealthService _healthService;
    private readonly ObservableCollection<VeFileItem> _files = [];
    private readonly ObservableCollection<VeFinishedItem> _finished = [];
    private readonly List<VeModel> _models = [];
    private CancellationTokenSource? _cts;
    private bool _seedVr2ModelReady;
    private bool _seedVr2ActionRunning;
    private bool _anime4KReady;
    private bool _anime4KActionRunning;

    public VideoEnhancerPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _healthService = App.Services.GetRequiredService<ISidecarHealthService>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        ShowWindowsVideoScalerStatus();
        UpdateUi();
        _ = LoadModelsAsync();
        _ = RefreshSeedVr2ModelStatusAsync();
        _ = RefreshAnime4KStatusAsync();
    }

    private void ShowWindowsVideoScalerStatus()
    {
        var capability = _healthService.EvaluateWindowsVideoScaler();
        WindowsVsrStatusText.Text = capability.Status == "Ready"
            ? "Available for qualified frame pipelines"
            : "Unavailable on this system — choose Real-ESRGAN, Anime4K, or SeedVR2";
        WindowsVsrDetailText.Text = $"{capability.Detail} {capability.Remediation}".Trim();
    }

    private async Task LoadModelsAsync()
    {
        ModelCombo.PlaceholderText = "Discovering...";
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
            ModelHintText.Text = "Build the realesrgan sidecar first: pwsh tools/realesrgan/build.ps1";
            ModelCombo.PlaceholderText = "Sidecar not built";
            UpdateUi();
            return;
        }

        _models.AddRange(harvested);
        if (_models.Count == 0)
        {
            ModelCombo.PlaceholderText = "No models found";
            ModelHintText.Text = "Run pwsh tools/realesrgan/build.ps1 to fetch the upstream model set.";
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
            ModelCombo.IsEnabled = true;
            ModelHintText.Text = $"{_models.Count} model(s) discovered. realesr-animevideov3 is fastest for video.";
        }
        UpdateUi();
    }

    private async void RefreshModels_Click(object sender, RoutedEventArgs e) => await LoadModelsAsync();

    private void Engine_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (RealEsrganModelPanel is null || SeedVr2ModelPanel is null || Anime4KModelPanel is null ||
            RealEsrganQualityPanel is null || SeedVr2QualityPanel is null ||
            Anime4KQualityPanel is null || RunButton is null)
            return;
        var seedVr2 = IsSeedVr2Selected();
        var anime4K = IsAnime4KSelected();
        RealEsrganModelPanel.Visibility = seedVr2 || anime4K ? Visibility.Collapsed : Visibility.Visible;
        SeedVr2ModelPanel.Visibility = seedVr2 ? Visibility.Visible : Visibility.Collapsed;
        Anime4KModelPanel.Visibility = anime4K ? Visibility.Visible : Visibility.Collapsed;
        RealEsrganQualityPanel.Visibility = seedVr2 || anime4K ? Visibility.Collapsed : Visibility.Visible;
        SeedVr2QualityPanel.Visibility = seedVr2 ? Visibility.Visible : Visibility.Collapsed;
        Anime4KQualityPanel.Visibility = anime4K ? Visibility.Visible : Visibility.Collapsed;
        RunButton.Content = seedVr2 ? "Restore with SeedVR2" : anime4K ? "Upscale with Anime4K" : "Upscale Video";
        var summary = BuildPlanSummary();
        foreach (var file in _files) file.PlanSummary = summary;
        UpdateUi();
    }

    private async Task RefreshSeedVr2ModelStatusAsync()
    {
        if (_seedVr2ActionRunning) return;
        if (_runner.Locate("seedvr2") is null)
        {
            _seedVr2ModelReady = false;
            DownloadSeedVr2ModelButton.IsEnabled = false;
            SeedVr2ModelStatus.Text = "SeedVR2 sidecar is not installed in this build.";
            UpdateUi();
            return;
        }

        _seedVr2ActionRunning = true;
        _seedVr2ModelReady = false;
        DownloadSeedVr2ModelButton.IsEnabled = false;
        SeedVr2ModelStatus.Text = "Checking local model pack...";
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
                ? "Model ready — pinned local pack found."
                : result.ErrorCode == "sidecar_not_found"
                    ? "SeedVR2 sidecar is not installed in this build."
                    : "Model not installed. Review the license and download it when ready.";
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
            Title = "Download the SeedVR2 restoration pack?",
            Content = "This downloads pinned, SHA-256 verified Apache-2.0 runtime and model snapshots " +
                      "(approximately 3.9 GB). SeedVR2 requires an NVIDIA CUDA GPU with at least 10 GB VRAM; " +
                      "12 GB or more is recommended. UCX never downloads or updates this pack during restoration.",
            PrimaryButtonText = "Accept & download",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;

        _seedVr2ActionRunning = true;
        _seedVr2ModelReady = false;
        DownloadSeedVr2ModelButton.IsEnabled = false;
        SeedVr2ModelStatus.Text = "Downloading pinned SeedVR2 pack...";
        UpdateUi();
        try
        {
            var progress = new Progress<SidecarProgress>(value =>
                DispatcherQueue.TryEnqueue(() =>
                    SeedVr2ModelStatus.Text = string.IsNullOrWhiteSpace(value.Stage)
                        ? $"Downloading... {value.Percent:F0}%"
                        : $"{value.Stage} ({value.Percent:F0}%)"));
            var result = await _runner.RunAsync(
                "seedvr2",
                ["download-model", "--accept-license"],
                progress,
                ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromHours(4));
            _seedVr2ModelReady = result.Success;
            SeedVr2ModelStatus.Text = result.Success
                ? "Model ready — pinned local pack installed."
                : $"Download failed: {result.ErrorMessage ?? "Unknown error"}";
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
            Anime4KStatus.Text = "Anime4K sidecar is not installed in this build.";
            UpdateUi();
            return;
        }

        _anime4KActionRunning = true;
        _anime4KReady = false;
        DownloadAnime4KShadersButton.IsEnabled = false;
        Anime4KStatus.Text = "Checking mpv and local shader pack...";
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
                ? "Ready — mpv and the pinned Anime4K v4.0.1 shaders are available."
                : result.ErrorMessage ?? "Anime4K is not ready.";
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
            Title = "Download the Anime4K shader pack?",
            Content = "This downloads the pinned, SHA-256 verified Anime4K v4.0.1 GLSL shader pack " +
                      "(MIT license, approximately 0.8 MB). Export remains local and also requires mpv " +
                      "on PATH, beside the sidecar, or in tools/_bin.",
            PrimaryButtonText = "Accept & download",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;

        _anime4KActionRunning = true;
        _anime4KReady = false;
        DownloadAnime4KShadersButton.IsEnabled = false;
        Anime4KStatus.Text = "Downloading pinned Anime4K shaders...";
        UpdateUi();
        try
        {
            var progress = new Progress<SidecarProgress>(value =>
                DispatcherQueue.TryEnqueue(() =>
                    Anime4KStatus.Text = string.IsNullOrWhiteSpace(value.Stage)
                        ? $"Downloading... {value.Percent:F0}%"
                        : $"{value.Stage} ({value.Percent:F0}%)"));
            var result = await _runner.RunAsync(
                "anime-upscale",
                ["download-shaders", "--accept-license"],
                progress,
                ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromMinutes(5));
            Anime4KStatus.Text = result.Success
                ? "Shader pack installed; checking mpv..."
                : $"Download failed: {result.ErrorMessage ?? "Unknown error"}";
        }
        finally
        {
            _anime4KActionRunning = false;
            DownloadAnime4KShadersButton.IsEnabled = true;
        }
        await RefreshAnime4KStatusAsync();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop into upscale queue";
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
            ? "No supported videos found in that folder."
            : $"Added {added} files from {path}.";
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
            Path = path,
            FileName = info.Name,
            SourceSummary = $"{FormatSize(info.Length)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            PlanSummary = BuildPlanSummary(),
            Progress = 0,
            StatusText = "Queued",
        });
        if (updateUi) UpdateUi();
        return true;
    }

    private void RemoveQueued_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        if (sender is Button button && button.Tag is VeFileItem item)
        {
            _files.Remove(item);
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
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (EmptyState is null) return;
        UpdateUi();
    }

    private void Settings_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (RunButton is null) return;
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
        UpdateStatusText();
    }

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
        CrfLabel.Text = $"CRF {crf} ({hint})";
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
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
        Anime4KCrfLabel.Text = $"CRF {crf} ({hint})";
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null) return;
        var seedVr2 = IsSeedVr2Selected();
        var anime4K = IsAnime4KSelected();
        VeModel? model = (ModelCombo.SelectedItem as ComboBoxItem)?.Tag as VeModel;
        if (!seedVr2 && !anime4K && model is null)
        {
            StatusText.Text = "Pick a model first.";
            return;
        }
        if (seedVr2 && !_seedVr2ModelReady)
        {
            StatusText.Text = "Download the SeedVR2 model pack before restoration.";
            return;
        }
        if (anime4K && !_anime4KReady)
        {
            StatusText.Text = "Install mpv and download the Anime4K shader pack before upscaling.";
            return;
        }
        var scale = SelectedInt(ScaleCombo, 2);
        var resolution = SelectedInt(SeedVr2ResolutionCombo, 720);
        var crf = anime4K ? (int)Anime4KCrfSlider.Value : (int)CrfSlider.Value;
        var anime4KProfile = SelectedTag(Anime4KProfileCombo, "a");

        var jobs = _files.ToList();
        var completed = 0; var failed = 0;

        _cts = new CancellationTokenSource();
        RunButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        CancelButton.IsEnabled = true;

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested) break;
                var outputPath = BuildOutputPath(item.Path, seedVr2, anime4K, scale, resolution, anime4KProfile);
                var args = seedVr2
                    ? new List<string>
                    {
                        "restore",
                        "--input", item.Path,
                        "--output", outputPath,
                        "--resolution", resolution.ToString(CultureInfo.InvariantCulture),
                    }
                    : anime4K
                    ? new List<string>
                    {
                        "video",
                        "--backend", "anime4k",
                        "--profile", anime4KProfile,
                        "--input", item.Path,
                        "--output", outputPath,
                        "--scale", "2",
                        "--crf", crf.ToString(CultureInfo.InvariantCulture),
                    }
                    : new List<string>
                    {
                        "upscale-video",
                        "--input",  item.Path,
                        "--output", outputPath,
                        "--model",  model!.Name,
                        "--scale",  scale.ToString(CultureInfo.InvariantCulture),
                        "--crf",    crf.ToString(CultureInfo.InvariantCulture),
                    };

                item.Progress = 0;
                item.StatusText = seedVr2 ? "Restoring" : anime4K ? "Anime4K" : "Upscaling";
                StatusText.Text = seedVr2
                    ? $"Restoring {item.FileName} with SeedVR2 at {resolution}p... ({completed + failed + 1}/{jobs.Count})"
                    : anime4K
                    ? $"Upscaling {item.FileName} with Anime4K Mode {anime4KProfile.ToUpperInvariant()}... ({completed + failed + 1}/{jobs.Count})"
                    : $"Upscaling {item.FileName} \u00d7{scale}... ({completed + failed + 1}/{jobs.Count})";

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = string.IsNullOrEmpty(p.Stage)
                        ? $"{p.Percent:F0}%"
                        : $"{p.Percent:F0}% - {p.Stage}";
                }));
                var log = new Progress<SidecarLog>(_ => { });

                SidecarResult result;
                try
                {
                    // Video upscale is slow per minute — generous watchdog timeout.
                    var sidecar = seedVr2 ? "seedvr2" : anime4K ? "anime-upscale" : "realesrgan";
                    result = await _runner.RunAsync(sidecar, args, progress, log, _cts.Token,
                        silenceTimeout: seedVr2 ? TimeSpan.FromHours(2) : TimeSpan.FromMinutes(60));
                }
                catch (OperationCanceledException)
                {
                    result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user.", 130);
                }

                if (result.Success)
                {
                    completed++;
                    item.Progress = 100;
                    item.StatusText = "Done";
                }
                else
                {
                    failed++;
                    item.StatusText = result.ErrorCode == "cancelled" ? "Cancelled" : "Failed";
                }

                AddFinishedItem(item, result, outputPath);
                if (result.ErrorCode == "cancelled") break;
            }

            StatusText.Text = _cts.IsCancellationRequested
                ? $"Cancelled — {completed} upscaled, {failed} failed."
                : $"Done — {completed} upscaled, {failed} failed.";

            if (_finished.Count > 0)
                QueuePivot.SelectedIndex = 1;
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
            UpdateUi(updateStatus: false);
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
        {
            _cts.Cancel();
            CancelButton.IsEnabled = false;
            StatusText.Text = "Cancelling...";
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
            Success = result.Success,
            Glyph = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasFiles = _files.Count > 0;
        var hasFinished = _finished.Count > 0;
        var seedVr2 = IsSeedVr2Selected();
        var anime4K = IsAnime4KSelected();
        var hasModel = seedVr2
            ? _seedVr2ModelReady && _runner.Locate("seedvr2") is not null
            : anime4K
            ? _anime4KReady && _runner.Locate("anime-upscale") is not null
            : ModelCombo?.SelectedItem is not null;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;
        RunButton.IsEnabled = hasFiles && hasModel && _cts is null;
        ClearButton.IsEnabled = hasFiles && _cts is null;
        CancelButton.IsEnabled = _cts is not null;
        QueueSummaryText.Text = $"{_files.Count} queued / {_finished.Count} finished";
        CurrentSetupText.Text = BuildPlanSummary();
        if (updateStatus && _cts is null) UpdateStatusText();
    }

    private void UpdateStatusText()
    {
        StatusText.Text = _files.Count == 0
            ? "Drop video clips to start an enhancement queue."
            : $"Ready to enhance {_files.Count} clip(s). {BuildPlanSummary()}";
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
        var model = (ModelCombo?.SelectedItem as ComboBoxItem)?.Tag is VeModel m ? m.Name : "no model";
        var scale = SelectedInt(ScaleCombo, 2);
        var crf = CrfSlider is null ? 20 : (int)CrfSlider.Value;
        return $"\u00d7{scale} · {model} · CRF {crf}";
    }

    private static string BuildOutputPath(
        string inputPath, bool seedVr2, bool anime4K, int scale, int resolution, string anime4KProfile)
    {
        var dir = Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(inputPath);
        if (seedVr2)
            return EnsureUniquePath(Path.Combine(dir, $"{name}_seedvr2_{resolution}p.mp4"));
        if (anime4K)
            return EnsureUniquePath(Path.Combine(dir, $"{name}_anime4k_{anime4KProfile}_x2.mp4"));
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

    private static int SelectedInt(ComboBox combo, int fallback)
    {
        if (combo.SelectedItem is ComboBoxItem item &&
            int.TryParse(item.Tag?.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var v))
            return v;
        return fallback;
    }

    private static string SelectedTag(ComboBox combo, string fallback) =>
        combo.SelectedItem is ComboBoxItem item && item.Tag is string tag ? tag : fallback;

    private bool IsSeedVr2Selected() =>
        EngineCombo?.SelectedItem is ComboBoxItem { Tag: string tag } && tag == "seedvr2";

    private bool IsAnime4KSelected() =>
        EngineCombo?.SelectedItem is ComboBoxItem { Tag: string tag } && tag == "anime4k";

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
    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string SourceSummary { get; set; } = "";
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
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush? AccentBrush { get; set; }
    public bool CanOpenFolder => !string.IsNullOrWhiteSpace(OutputPath);
}
