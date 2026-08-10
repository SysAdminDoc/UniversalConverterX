using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Navigation;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;
using UniversalConverterX.Core.ViewModels;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class CompressorPage : Page
{
    private const string QueueKey = "compressor";
    private const string QueuePageName = "Compressor";
    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v"
    ];

    /// <summary>Hard cap on chars retained in the inline log panel — without
    /// this a 4-hour two-pass encode emits enough lines to make the TextBlock
    /// unresponsive.</summary>
    private const int ProgressLogMaxChars = 64_000;
    private const int FinishedCap = 200;
    private const int FolderAddCap = 500;

    private static readonly IReadOnlyDictionary<string, double> TargetSizeLimitsMb =
        new Dictionary<string, double>(StringComparer.Ordinal)
        {
            ["discord-10mb"] = 10,
            ["discord-25mb"] = 25,
            ["discord-50mb"] = 50,
            ["email-25mb"] = 25,
        };

    private readonly ISidecarRunner _runner;
    private readonly ConverterXOptions _appOptions;
    private readonly ISidecarHealthService _health;
    private readonly IBatchQueueStore _queueStore;
    private readonly IAppJobCoordinator _jobCoordinator;
    private readonly IHistoryService _history;
    private readonly IPostQueueActionService _postQueueActions;
    private readonly ObservableCollection<CompressionFileItem> _files = [];
    private readonly ObservableCollection<CompressionFinishedItem> _finished = [];
    private CancellationTokenSource? _cts;
    private string? _outputDirectory;
    private bool _restoringQueue;

    public CompressorPage()
    {
        InitializeComponent();
        _appOptions = App.Services
            .GetRequiredService<Microsoft.Extensions.Options.IOptions<ConverterXOptions>>()
            .Value;
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _health = App.Services.GetRequiredService<ISidecarHealthService>();
        _queueStore = App.Services.GetRequiredService<IBatchQueueStore>();
        _jobCoordinator = App.Services.GetRequiredService<IAppJobCoordinator>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        _postQueueActions = App.Services.GetRequiredService<IPostQueueActionService>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        ApplyConfiguredHardwareAcceleration();
        _ = RefreshHardwareCapabilitiesAsync();
        UpdatePresetSummaries();
        RestorePersistedQueue();
        UpdateUi();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (e.Parameter is ConversionRerunRequest request
            && string.Equals(request.Surface, "compressor", StringComparison.OrdinalIgnoreCase))
        {
            ApplyRerunRequest(request);
        }
    }

    private async void ApplyLastUsed_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var request = await _history.GetLastUsedRerunAsync(surface: "compressor");
            if (request is null)
            {
                StatusText.Text = AppLocalizer.Get("No saved Compressor settings are available yet.");
                return;
            }

            ApplyRerunRequest(request);
        }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Format($"Could not restore the last Compressor settings: {ex.Message}");
        }
    }

    private void ApplyRerunRequest(ConversionRerunRequest request)
    {
        var settings = request.PageSettings ?? [];
        _restoringQueue = true;
        try
        {
            if (settings.TryGetValue("preset", out var preset))
            {
                switch (preset)
                {
                    case "email-10mb": PresetEmail.IsChecked = true; break;
                    case "__target__": PresetTarget.IsChecked = true; break;
                    case "__vmaf__": PresetVmaf.IsChecked = true; break;
                    case "archive-av1": PresetArchive.IsChecked = true; break;
                    case "__pro__": PresetPro.IsChecked = true; break;
                    default: PresetWeb.IsChecked = true; break;
                }
            }

            if (settings.TryGetValue("targetPreset", out var targetPreset))
                SelectTaggedItem(SocialTargetCombo, targetPreset);
            if (settings.TryGetValue("proPreset", out var proPreset))
                SelectTaggedItem(ProPresetCombo, proPreset);
            if (settings.TryGetValue("targetMegabytes", out var targetMegabytes)
                && double.TryParse(targetMegabytes, NumberStyles.Float, CultureInfo.InvariantCulture, out var megabytes))
                TargetSizeBox.Value = megabytes;
            if (settings.TryGetValue("vmafEncoder", out var vmafEncoder))
                SelectTaggedItem(VmafEncoderCombo, vmafEncoder);
            if (settings.TryGetValue("vmafTarget", out var vmafTarget)
                && double.TryParse(vmafTarget, NumberStyles.Float, CultureInfo.InvariantCulture, out var vmaf))
                VmafTargetBox.Value = vmaf;
            if (settings.TryGetValue("hardwareAcceleration", out var hardwareAcceleration))
                SelectTaggedItem(HwAccelCombo, hardwareAcceleration);
            if (settings.TryGetValue("d3d12Deinterlace", out var deinterlace))
                D3D12DeinterlaceToggle.IsChecked = bool.TryParse(deinterlace, out var enabled) && enabled;

            _outputDirectory = string.IsNullOrWhiteSpace(request.OutputDirectory)
                ? null
                : request.OutputDirectory;
            OutputDirectoryBox.Text = _outputDirectory ?? "";

            foreach (var sourcePath in request.SourcePaths.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                if (File.Exists(sourcePath)
                    && !_files.Any(file => file.Path.Equals(sourcePath, StringComparison.OrdinalIgnoreCase)))
                    AddFile(sourcePath, updateUi: false);
            }

            if (request.SourcePaths.Count == 1)
            {
                var restoredFile = _files.FirstOrDefault(file =>
                    file.Path.Equals(request.SourcePaths[0], StringComparison.OrdinalIgnoreCase));
                if (restoredFile is not null && !string.IsNullOrWhiteSpace(request.OutputPath))
                    restoredFile.OutputPath = request.OutputPath;
            }
        }
        finally
        {
            _restoringQueue = false;
        }

        UpdatePresetSummaries();
        PersistQueue();
        UpdateUi();
        StatusText.Text = _files.Count > 0
            ? AppLocalizer.Format($"Restored {_files.Count} file(s) with the saved Compressor settings.")
            : AppLocalizer.Get("The saved Compressor source file is no longer available.");
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Drop into compression queue");
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
            return;

        var items = await e.DataView.GetStorageItemsAsync();
        foreach (var item in items)
        {
            switch (item)
            {
                case StorageFile file:
                    AddFile(file.Path);
                    break;
                case StorageFolder folder:
                    AddFolder(folder.Path);
                    break;
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
        foreach (var ext in VideoExtensions)
            picker.FileTypeFilter.Add(ext);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var files = await picker.PickMultipleFilesAsync();
        if (files is null)
            return;

        foreach (var file in files)
            AddFile(file.Path);
    }

    private async void BrowseFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder is not null)
            AddFolder(folder.Path);
    }

    private async void BrowseOutputFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder is null)
            return;

        _outputDirectory = folder.Path;
        OutputDirectoryBox.Text = _outputDirectory;
        UpdateStatusText();
        PersistQueue();
    }

    private void SameAsSource_Click(object sender, RoutedEventArgs e)
    {
        _outputDirectory = null;
        OutputDirectoryBox.Text = "";
        UpdateStatusText();
        PersistQueue();
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
        {
            StatusText.Text = AppLocalizer.Format($"Folder not found: {path}");
            return;
        }

        IEnumerable<string> entries;
        try
        {
            entries = Directory.EnumerateFiles(path)
                .Where(f => VideoExtensions.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase));
        }
        catch (UnauthorizedAccessException)
        {
            StatusText.Text = AppLocalizer.Get("Permission denied for that folder.");
            return;
        }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Format($"Could not read folder: {ex.Message}");
            return;
        }

        var added = 0;
        var truncated = false;
        foreach (var file in entries)
        {
            if (added >= FolderAddCap) { truncated = true; break; }
            if (AddFile(file, updateUi: false))
                added++;
        }

        if (added == 0)
            StatusText.Text = AppLocalizer.Get("No supported video files were added from that folder.");
        else if (truncated)
            StatusText.Text = AppLocalizer.Format($"Added {added} videos from {path} (capped at {FolderAddCap}).");
        else
            StatusText.Text = AppLocalizer.Format($"Added {added} videos from {path}.");
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => string.Equals(f.Path, path, StringComparison.OrdinalIgnoreCase)))
            return false;

        FileInfo info;
        long size;
        try
        {
            info = new FileInfo(path);
            if (!info.Exists) return false;
            size = info.Length;
        }
        catch
        {
            return false;
        }

        if (!VideoExtensions.Contains(info.Extension, StringComparer.OrdinalIgnoreCase))
            return false;

        _files.Add(new CompressionFileItem
        {
            Path = path,
            FileName = info.Name,
            Extension = info.Extension.TrimStart('.').ToUpperInvariant(),
            SourceSizeBytes = size,
            SourceSummary = $"{FormatSize(size)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            PresetSummary = SelectedPresetLabel(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi)
        {
            UpdateUi();
            PersistQueue();
        }

        return true;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is CompressionFileItem file)
        {
            _files.Remove(file);
            UpdateUi();
        }
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0)
            return;

        if (!await PageDialogService.ConfirmClearAsync(
                this,
                "Clear compression queue?",
                $"Remove {_files.Count} queued video file(s)? Finished results stay available."))
        {
            return;
        }

        _files.Clear();
        UpdateUi();
        PersistQueue();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (EmptyState is null) return;
        UpdateUi();
    }

    private void Preset_Checked(object sender, RoutedEventArgs e)
    {
        // IsChecked="True" on PresetWeb fires this during InitializeComponent() before
        // all Connect() cases have run — bail out until the visual tree is complete.
        if (PresetEmail is null) return;
        if (ProPresetCombo is not null)
            ProPresetCombo.Visibility = PresetPro?.IsChecked == true
                ? Visibility.Visible
                : Visibility.Collapsed;
        if (TargetSizePanel is not null)
            TargetSizePanel.Visibility = IsTargetSizeMode
                ? Visibility.Visible
                : Visibility.Collapsed;
        if (VmafTargetPanel is not null)
            VmafTargetPanel.Visibility = IsVmafTargetMode
                ? Visibility.Visible
                : Visibility.Collapsed;
        if (HwAccelCombo is not null)
            HwAccelCombo.IsEnabled = !IsTargetSizeMode && !IsVmafTargetMode;
        UpdateD3D12Options();
        UpdatePresetSummaries();
        UpdateStatusText();
        PersistQueue();
    }

    private void ProPreset_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (StatusText is null) return;
        UpdatePresetSummaries();
        UpdateStatusText();
        PersistQueue();
    }

    private void SocialTarget_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (TargetSizeBox is null) return;

        var tag = SelectedTargetPresetTag();
        var isCustom = tag == "custom";
        TargetSizeBox.IsEnabled = isCustom;
        if (!isCustom && TargetSizeLimitsMb.TryGetValue(tag, out var limitMb))
            TargetSizeBox.Value = limitMb;

        if (StatusText is null) return;
        UpdatePresetSummaries();
        UpdateStatusText();
        PersistQueue();
    }

    private void TargetSize_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (StatusText is null || !IsTargetSizeMode) return;
        UpdatePresetSummaries();
        UpdateStatusText();
        PersistQueue();
    }

    private void VmafTarget_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (StatusText is null || !IsVmafTargetMode) return;
        UpdatePresetSummaries();
        UpdateStatusText();
        PersistQueue();
    }

    private void VmafEncoder_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (StatusText is null || !IsVmafTargetMode) return;
        UpdatePresetSummaries();
        UpdateStatusText();
        PersistQueue();
    }

    private void HwAccel_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (StatusText is null) return;
        UpdateD3D12Options();
        UpdateStatusText();
        PersistQueue();
    }

    private void UpdateD3D12Options()
    {
        if (D3D12DeinterlaceToggle is null) return;
        D3D12DeinterlaceToggle.Visibility =
            !IsTargetSizeMode && !IsVmafTargetMode && SelectedHwAccel() == "d3d12"
                ? Visibility.Visible
                : Visibility.Collapsed;
    }

    private string SelectedHwAccel()
    {
        if (HwAccelCombo?.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "none";
    }

    private static void SelectTaggedItem(ComboBox selector, string? tag)
    {
        if (string.IsNullOrWhiteSpace(tag))
            return;

        var match = selector.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(item => string.Equals(
                item.Tag?.ToString(), tag, StringComparison.OrdinalIgnoreCase));
        if (match is not null)
            selector.SelectedItem = match;
    }

    private void ApplyConfiguredHardwareAcceleration()
    {
        var tag = !_appOptions.EnableHardwareAcceleration
            || _appOptions.DefaultHardwareAcceleration == HardwareAcceleration.None
                ? "none"
                : _appOptions.DefaultHardwareAcceleration switch
                {
                    HardwareAcceleration.Nvenc or HardwareAcceleration.Cuda => "nvenc",
                    HardwareAcceleration.Qsv => "qsv",
                    HardwareAcceleration.Amf => "amf",
                    _ => "none",
                };

        var match = HwAccelCombo.Items
            .OfType<ComboBoxItem>()
            .FirstOrDefault(item => string.Equals(
                item.Tag?.ToString(), tag, StringComparison.OrdinalIgnoreCase));
        if (match is not null)
            HwAccelCombo.SelectedItem = match;
    }

    private async Task RefreshHardwareCapabilitiesAsync()
    {
        var ffmpeg = new FFmpegConverter(_appOptions.ToolsBasePath);
        var executablePath = ffmpeg.ResolveExecutablePath();
        IReadOnlySet<string> encoderNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (executablePath is not null)
        {
            try
            {
                encoderNames = await Task.Run(
                    () => FfmpegEncoderProbe.ProbeEncoderNames(executablePath));
            }
            catch
            {
                // The controls stay disabled when the local probe cannot run.
            }
        }

        DispatcherQueue.TryEnqueue(() => ApplyHardwareCapabilities(executablePath, encoderNames));
    }

    private void ApplyHardwareCapabilities(
        string? executablePath,
        IReadOnlySet<string> encoderNames)
    {
        if (HwAccelCombo is null)
            return;

        foreach (var item in HwAccelCombo.Items.OfType<ComboBoxItem>())
        {
            var tag = item.Tag?.ToString() ?? "none";
            var enabled = tag.Equals("none", StringComparison.OrdinalIgnoreCase)
                || executablePath is not null
                    && FfmpegEncoderProbe.SupportsAcceleration(tag, encoderNames);
            item.IsEnabled = enabled;

            var explanation = tag.Equals("none", StringComparison.OrdinalIgnoreCase)
                ? "Always available: encodes on the CPU and preserves the requested output settings."
                : enabled
                    ? $"Detected encoder(s): {string.Join(", ", MatchingEncoderNames(tag, encoderNames).Take(4))}. "
                        + "A driver or VRAM failure still falls back to software and is recorded in history."
                    : FfmpegEncoderProbe.DescribeUnavailable(tag, executablePath is not null, encoderNames);
            ToolTipService.SetToolTip(item, explanation);
            AutomationProperties.SetHelpText(item, explanation);
        }

        var selected = HwAccelCombo.SelectedItem as ComboBoxItem;
        if (selected is not null && !selected.IsEnabled)
            SelectTaggedItem(HwAccelCombo, "none");

        HwAccelStatusText.Text = executablePath is null
            ? "Software only: the configured FFmpeg executable was not found."
            : encoderNames.Count == 0
                ? "Software only: this FFmpeg build exposes no supported hardware encoders."
                : $"Detected {encoderNames.Count} FFmpeg encoder(s). Hardware choices are enabled only when probed; runtime driver/VRAM failures fall back to CPU and are saved in history.";
        UpdateD3D12Options();
        UpdateStatusText();
        if (!_restoringQueue)
            PersistQueue();
    }

    private static IEnumerable<string> MatchingEncoderNames(
        string acceleration,
        IEnumerable<string> encoderNames)
    {
        string[] suffixes = acceleration.ToLowerInvariant() switch
        {
            "nvenc" => new[] { "_nvenc" },
            "amf" => new[] { "_amf" },
            "qsv" => new[] { "_qsv" },
            "d3d12" => new[] { "_d3d12va" },
            "vaapi" => new[] { "_vaapi" },
            "videotoolbox" => new[] { "_videotoolbox" },
            "vulkan" => new[] { "_vulkan" },
            _ => Array.Empty<string>(),
        };
        return encoderNames
            .Where(name => suffixes.Any(suffix =>
                name.EndsWith(suffix, StringComparison.OrdinalIgnoreCase)))
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase);
    }

    private void RestorePersistedQueue()
    {
        _restoringQueue = true;
        try
        {
            var queue = _queueStore.Load(QueueKey);
            if (queue is null || queue.Jobs.Count == 0)
                return;

            if (queue.Settings.TryGetValue("outputDirectory", out var outputDirectory)
                && !string.IsNullOrWhiteSpace(outputDirectory))
            {
                _outputDirectory = outputDirectory;
                OutputDirectoryBox.Text = outputDirectory;
            }

            foreach (var job in queue.Jobs)
            {
                if (string.IsNullOrWhiteSpace(job.SourcePath)
                    || _files.Any(file => file.Path.Equals(job.SourcePath, StringComparison.OrdinalIgnoreCase)))
                    continue;

                var sourceInfo = new FileInfo(job.SourcePath);
                var sourceExists = sourceInfo.Exists;
                var sourceSize = sourceExists ? sourceInfo.Length : 0;
                _files.Add(new CompressionFileItem
                {
                    Id = string.IsNullOrWhiteSpace(job.Id) ? Guid.NewGuid().ToString("N") : job.Id,
                    Path = job.SourcePath,
                    FileName = sourceInfo.Name,
                    Extension = sourceInfo.Extension.TrimStart('.').ToUpperInvariant(),
                    SourceSizeBytes = sourceSize,
                    SourceSummary = sourceExists
                        ? $"{FormatSize(sourceSize)} - {sourceInfo.Extension.TrimStart('.').ToUpperInvariant()}"
                        : "Source file is missing",
                    PresetSummary = SelectedPresetLabel(),
                    OutputPath = job.OutputPath,
                    ErrorMessage = job.ErrorMessage,
                    Engine = job.Engine,
                    StatusText = RestoreStatus(job.Status),
                });
            }

            if (_files.Count > 0)
                StatusText.Text = AppLocalizer.Format($"Restored {_files.Count} compression job(s) from the previous session.");
        }
        finally
        {
            _restoringQueue = false;
        }

        PersistQueue();
    }

    private void PersistQueue()
    {
        if (_restoringQueue || _queueStore is null || _jobCoordinator is null)
            return;

        var activeJobs = _files
            .Where(file => !file.StatusText.Equals("Done", StringComparison.OrdinalIgnoreCase))
            .Select(file => new PersistedBatchJob
            {
                Id = string.IsNullOrWhiteSpace(file.Id) ? Guid.NewGuid().ToString("N") : file.Id,
                SourcePath = file.Path,
                OutputPath = file.OutputPath,
                Engine = string.IsNullOrWhiteSpace(file.Engine) ? "videocrush" : file.Engine,
                Action = "compress",
                Preset = SelectedPresetTag(),
                Status = NormalizePersistedStatus(file.StatusText),
                ErrorMessage = file.ErrorMessage,
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
                ["outputDirectory"] = _outputDirectory,
                ["preset"] = SelectedPresetTag(),
                ["hardwareAcceleration"] = SelectedHwAccel(),
                ["targetPreset"] = SelectedTargetPresetTag(),
                ["targetMegabytes"] = SelectedTargetLimitMb().ToString(CultureInfo.InvariantCulture),
                ["proPreset"] = ProPresetCombo?.SelectedItem is ComboBoxItem proItem
                    ? proItem.Tag?.ToString()
                    : "prores-422-hq",
                ["vmafEncoder"] = SelectedVmafEncoder(),
                ["vmafTarget"] = SelectedVmafTarget().ToString(CultureInfo.InvariantCulture),
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
        if (status?.Equals("Compressing", StringComparison.OrdinalIgnoreCase) == true
            || status?.EndsWith("%", StringComparison.Ordinal) == true)
            return "Running";
        return "Queued";
    }

    private async void Compress_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null)
            return;

        var smartQualityMode = IsVmafTargetMode;
        if (smartQualityMode)
        {
            CompressButton.IsEnabled = false;
            ClearButton.IsEnabled = false;
            StatusText.Text = AppLocalizer.Get("Checking ab-av1 smart-compression requirements...");
            SidecarHealthReport report;
            try
            {
                report = await _health.EvaluateEngineAsync("ab-av1");
            }
            catch (Exception ex)
            {
                UpdateUi();
                VmafHealthText.Text = AppLocalizer.Format($"Health check failed: {ex.Message}");
                StatusText.Text = AppLocalizer.Get("Smart compression is unavailable because its requirements could not be checked.");
                return;
            }

            VmafHealthText.Text = report.CanRun
                ? AppLocalizer.Format($"{report.Summary}. {report.Detail}")
                : report.Detail;
            if (!report.CanRun)
            {
                UpdateUi();
                StatusText.Text = AppLocalizer.Format($"Smart compression unavailable — {report.Summary}. {report.Detail}");
                return;
            }
        }

        if (_outputDirectory is not null)
        {
            try { Directory.CreateDirectory(_outputDirectory); }
            catch (Exception ex)
            {
                UpdateUi();
                StatusText.Text = AppLocalizer.Format($"Output folder unavailable: {ex.Message}");
                return;
            }
        }

        var preset = SelectedPresetTag();
        var workflow = BuildWorkflow();
        var engine = workflow.Engine;
        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;
        long resultBytes = 0;
        var batchStartedAt = DateTime.UtcNow;
        var completionItems = new List<QueueCompletionItem>();

        var cancellation = new CancellationTokenSource();
        _cts = cancellation;
        var registeredHandles = jobs
            .Select(item => new AppJobHandle(QueueKey, item.Id))
            .ToList();
        foreach (var handle in registeredHandles)
            _jobCoordinator.RegisterCancellation(handle, cancellation.Cancel);
        CompressButton.IsEnabled = false;
        ProgressLog.Text = "";
        ShowOverlay($"Compressing {jobs.Count} files ({preset})");

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested)
                    break;

                var outputPath = BuildOutputPath(item.Path, smartQualityMode);
                var request = workflow.BuildInvocation(item.Path, outputPath);

                item.Engine = engine;
                item.OutputPath = outputPath;
                item.StatusText = "Compressing";
                item.ErrorMessage = null;
                item.Progress = 0;
                ProgressTitle.Text = AppLocalizer.Format($"Compressing {item.FileName}");
                ProgressStage.Text = AppLocalizer.Format($"{completed + failed + 1} of {jobs.Count}");
                PersistQueue();

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = $"{p.Percent:F0}%";
                    var overall = ((completed + failed) * 100.0 + p.Percent) / jobs.Count;
                    ProgressBar.Value = Math.Clamp(overall, 0, 100);
                    ProgressStage.Text = AppLocalizer.Format($"{p.Percent:F1}% - {p.Stage}");
                    ProgressEta.Text = p.EtaSeconds is int eta and >= 0
                        ? AppLocalizer.Format($"ETA {TimeSpan.FromSeconds(eta):mm\\:ss}")
                        : "";
                }));
                var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
                {
                    var line = $"[{l.Level}] {l.Message}\n";
                    var combined = ProgressLog.Text + line;
                    // Keep the tail when we exceed the cap; the most recent
                    // lines are what the user is watching anyway.
                    if (combined.Length > ProgressLogMaxChars)
                    {
                        var trimmed = combined.Length - ProgressLogMaxChars;
                        // Snap to the next newline so we never start mid-line.
                        var nl = combined.IndexOf('\n', trimmed);
                        combined = nl >= 0 ? combined[(nl + 1)..] : combined[trimmed..];
                    }
                    ProgressLog.Text = combined;
                }));

                var jobStartedAt = DateTime.UtcNow;
                double? verifiedVmaf = null;
                double? finalCrf = null;
                Action<string, JsonElement>? rawEvent = null;
                if (smartQualityMode)
                {
                    rawEvent = (eventName, root) =>
                    {
                        if (eventName != "complete") return;
                        var verified = root.TryGetProperty("vmaf_verified", out var verifiedElement)
                            && verifiedElement.ValueKind == JsonValueKind.True;
                        if (verified
                            && root.TryGetProperty("final_vmaf", out var vmafElement)
                            && vmafElement.ValueKind == JsonValueKind.Number)
                        {
                            verifiedVmaf = vmafElement.GetDouble();
                        }
                        if (root.TryGetProperty("final_crf", out var crfElement)
                            && crfElement.ValueKind == JsonValueKind.Number)
                        {
                            finalCrf = crfElement.GetDouble();
                        }
                    };
                }

                var result = await _runner.RunAsync(
                    request.Engine, request.Arguments, progress, log, cancellation.Token, rawEvent);
                if (result.Success)
                {
                    completed++;
                    item.Progress = 100;
                    item.StatusText = verifiedVmaf is double vmaf
                        ? $"Done · VMAF {vmaf:0.00}"
                        : "Done";
                    item.OutputPath = result.OutputPath ?? outputPath;
                    item.ErrorMessage = null;
                    item.ResultSizeBytes = result.SizeBytes ?? 0;
                    resultBytes += item.ResultSizeBytes;
                }
                else
                {
                    failed++;
                    item.StatusText = result.ErrorCode == "cancelled" ? "Cancelled" : "Failed";
                    item.OutputPath = result.OutputPath ?? outputPath;
                    item.ErrorMessage = result.ErrorMessage;
                }
                PersistQueue();

                AddFinishedItem(item, result, verifiedVmaf, finalCrf);
                completionItems.Add(new QueueCompletionItem
                {
                    Source = item.Path,
                    Output = result.OutputPath,
                    Status = result.ErrorCode == "cancelled"
                        ? QueueCompletionItemStatus.Cancelled
                        : result.Success
                            ? QueueCompletionItemStatus.Succeeded
                            : QueueCompletionItemStatus.Failed,
                    Message = result.ErrorMessage,
                });

                // Persist every job to the history dashboard. We skip pure cancellations
                // (user-driven) so the failed-count stat stays meaningful.
                if (result.ErrorCode != "cancelled")
                {
                    long? srcBytes = null;
                    try { srcBytes = new FileInfo(item.Path).Length; } catch { /* deleted mid-job */ }
                    _ = _history.LogAsync(new HistoryRecord
                    {
                        Timestamp = jobStartedAt,
                        Engine = engine,
                        Action = "compress",
                        SourcePath = item.Path,
                        OutputPath = result.Success ? outputPath : null,
                        SourceBytes = srcBytes,
                        OutputBytes = result.Success ? result.SizeBytes : null,
                        DurationSeconds = (DateTime.UtcNow - jobStartedAt).TotalSeconds,
                        Success = result.Success,
                        ErrorCode = result.ErrorCode,
                        ErrorMessage = result.ErrorMessage,
                        Profile = preset,
                        RerunParameters = ConversionRerunRequestCodec.Serialize(
                            BuildRerunRequest(item.Path, outputPath)),
                        Provenance = result.Provenance is null
                            ? null
                            : JobProvenanceCodec.Serialize(result.Provenance),
                    });
                }

                if (result.ErrorCode == "cancelled")
                    break;
            }
        }
        finally
        {
            foreach (var handle in registeredHandles)
                _jobCoordinator.UnregisterCancellation(handle);
            cancellation.Dispose();
            _cts = null;
        }

        ProgressTitle.Text = failed == 0
            ? AppLocalizer.Get("Done")
            : AppLocalizer.Get("Completed with errors");
        ProgressBar.Value = failed == 0 ? 100 : ProgressBar.Value;
        ProgressStage.Text = AppLocalizer.Format($"{completed} succeeded, {failed} failed");
        ProgressEta.Text = "";
        CancelButton.Content = AppLocalizer.Get("Close");
        QueuePivot.SelectedIndex = _finished.Count > 0 ? 1 : 0;
        UpdateTotals(resultBytes);
        UpdateUi();

        foreach (var pending in jobs.Skip(completionItems.Count))
        {
            completionItems.Add(new QueueCompletionItem
            {
                Source = pending.Path,
                Status = QueueCompletionItemStatus.Cancelled,
                Message = AppLocalizer.Get("Not started because the queue was cancelled."),
            });
        }
        if (completionItems.Count > 0)
        {
            var actionResult = await _postQueueActions.ExecuteAsync(new QueueCompletionSummary
            {
                Workflow = "Compressor",
                StartedUtc = batchStartedAt,
                CompletedUtc = DateTime.UtcNow,
                Items = completionItems,
            });
            if (actionResult.Action != QueueCompletionAction.None && !actionResult.Executed)
                StatusText.Text = actionResult.Message;
        }
    }

    private void PreviewSample_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0)
        {
            StatusText.Text = AppLocalizer.Get("Add a video before rendering a representative sample.");
            return;
        }

        var item = _files[0];
        var workflow = BuildWorkflow();
        var outputPath = BuildOutputPath(item.Path, workflow.Mode == CompressionWorkflowMode.Vmaf);
        var invocation = workflow.BuildInvocation(item.Path, outputPath);
        var rerun = BuildRerunRequest(item.Path, outputPath);
        App.RequestNavigation("vmaf", new RepresentativePreviewRequest(
            Surface: "compressor",
            SourcePath: item.Path,
            Engine: invocation.Engine,
            Arguments: invocation.Arguments,
            Promotion: new RepresentativePreviewPromotion(
                Surface: "compressor",
                SourcePath: item.Path,
                OutputDirectory: rerun.OutputDirectory,
                OutputFormat: rerun.OutputFormat,
                PageSettings: new Dictionary<string, string?>(rerun.PageSettings,
                    StringComparer.OrdinalIgnoreCase))));
    }

    private CompressorWorkflowViewModel BuildWorkflow() => new()
    {
        Mode = IsVmafTargetMode
            ? CompressionWorkflowMode.Vmaf
            : IsTargetSizeMode
                ? CompressionWorkflowMode.TargetSize
                : CompressionWorkflowMode.Standard,
        Preset = SelectedPresetTag(),
        HardwareAcceleration = SelectedHwAccel(),
        D3D12Deinterlace = D3D12DeinterlaceToggle?.IsChecked == true,
        TargetPreset = SelectedTargetPresetTag(),
        TargetMegabytes = SelectedTargetLimitMb(),
        VmafEncoder = SelectedVmafEncoder(),
        VmafTarget = SelectedVmafTarget(),
    };

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
        {
            _cts.Cancel();
            return;
        }

        ProgressOverlay.Visibility = Visibility.Collapsed;
        CancelButton.Content = AppLocalizer.Get("Cancel");
    }

    private void OpenOutputFolder_Click(object sender, RoutedEventArgs e)
    {
        var path = _outputDirectory
            ?? _finished.LastOrDefault(f => f.Success && !string.IsNullOrWhiteSpace(f.OutputPath))?.OutputPath
            ?? _files.FirstOrDefault()?.Path;
        OpenContainingFolder(path);
    }

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string path)
            OpenContainingFolder(path);
    }

    private void ShowOverlay(string title)
    {
        ProgressTitle.Text = title;
        ProgressStage.Text = AppLocalizer.Get("Starting...");
        ProgressEta.Text = "";
        ProgressBar.Value = 0;
        CancelButton.Content = AppLocalizer.Get("Cancel");
        ProgressOverlay.Visibility = Visibility.Visible;
    }

    private void AddFinishedItem(
        CompressionFileItem item,
        SidecarResult result,
        double? verifiedVmaf = null,
        double? finalCrf = null)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush = (Brush)Application.Current.Resources["AccentRedBrush"];
        var qualityResult = verifiedVmaf is double vmaf
            ? $" - Verified VMAF {vmaf:0.00}" + (finalCrf is double crf ? $" at CRF {crf:0.##}" : "")
            : "";
        var details = result.Success
            ? $"{item.SourceSummary} -> {FormatSize(result.SizeBytes ?? 0)} - {SavingsLabel(item.SourceSizeBytes, result.SizeBytes ?? 0)}{qualityResult}"
            : result.ErrorMessage ?? "Compression failed";

        _finished.Insert(0, new CompressionFinishedItem
        {
            FileName = result.Success && !string.IsNullOrWhiteSpace(result.OutputPath)
                ? Path.GetFileName(result.OutputPath)
                : item.FileName,
            Details = details,
            OutputPath = result.OutputPath ?? "",
            Success = result.Success,
            Glyph = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });

        while (_finished.Count > FinishedCap)
            _finished.RemoveAt(_finished.Count - 1);
    }

    private void UpdateUi()
    {
        var hasFiles = _files.Count > 0;
        var hasFinished = _finished.Count > 0;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;
        CompressButton.IsEnabled = hasFiles && _cts is null;
        PreviewSampleButton.IsEnabled = hasFiles && _cts is null;
        ClearButton.IsEnabled = hasFiles && _cts is null;
        UpdateTotals();
        UpdateStatusText();
        PersistQueue();
    }

    private void UpdateTotals(long? explicitResultBytes = null)
    {
        var sourceBytes = _files.Sum(f => f.SourceSizeBytes);
        var resultBytes = explicitResultBytes ?? _files.Sum(f => f.ResultSizeBytes);

        SourceSizeText.Text = FormatSize(sourceBytes);
        ResultSizeText.Text = FormatSize(resultBytes);
        SavingsText.Text = sourceBytes > 0 && resultBytes > 0
            ? SavingsLabel(sourceBytes, resultBytes)
            : AppLocalizer.Get("Savings appear after compression.");
    }

    private void UpdateStatusText()
    {
        var output = _outputDirectory ?? "same folder as each source";
        StatusText.Text = _files.Count == 0
            ? AppLocalizer.Get("Add videos to start a compression queue.")
            : AppLocalizer.Format($"Ready to compress {_files.Count} videos using {SelectedPresetLabel()}. Output: {output}.");
    }

    private void UpdatePresetSummaries()
    {
        var label = SelectedPresetLabel();
        foreach (var file in _files)
            file.PresetSummary = label;
    }

    private string SelectedPresetTag()
    {
        if (IsVmafTargetMode)
        {
            var target = SelectedVmafTarget().ToString("0.##", CultureInfo.InvariantCulture);
            return $"vmaf-{target}-{SelectedVmafEncoder()}";
        }
        if (IsTargetSizeMode)
        {
            var targetPreset = SelectedTargetPresetTag();
            return targetPreset == "custom"
                ? $"custom-{SelectedTargetLimitMb().ToString("0.##", CultureInfo.InvariantCulture)}mb"
                : targetPreset;
        }
        if (PresetEmail.IsChecked == true) return "email-10mb";
        if (PresetArchive.IsChecked == true) return "archive-av1";
        if (PresetPro?.IsChecked == true)
        {
            // Professional radio: pick from the sub-combo.
            if (ProPresetCombo?.SelectedItem is ComboBoxItem item && item.Tag is string tag)
                return tag;
            return "prores-422-hq";
        }
        return "web-1080p";
    }

    private string SelectedPresetLabel()
    {
        if (IsVmafTargetMode)
            return $"Smart VMAF {SelectedVmafTarget():0.##} ({SelectedVmafEncoderLabel()})";
        if (IsTargetSizeMode)
        {
            if (SelectedTargetPresetTag() == "custom")
                return $"Custom {SelectedTargetLimitMb():0.##} MB limit";
            if (SocialTargetCombo?.SelectedItem is ComboBoxItem targetItem)
                return targetItem.Content?.ToString() ?? "Target size";
            return "Target size";
        }
        if (PresetEmail.IsChecked == true) return "Email";
        if (PresetArchive.IsChecked == true) return "Archive AV1";
        if (PresetPro?.IsChecked == true && ProPresetCombo?.SelectedItem is ComboBoxItem proItem)
            return proItem.Content?.ToString() ?? "Professional";
        return "Web 1080p";
    }

    private bool IsTargetSizeMode => PresetTarget?.IsChecked == true;

    private bool IsVmafTargetMode => PresetVmaf?.IsChecked == true;

    private string SelectedTargetPresetTag()
    {
        if (SocialTargetCombo?.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "discord-10mb";
    }

    private double SelectedTargetLimitMb()
    {
        var presetTag = SelectedTargetPresetTag();
        if (TargetSizeLimitsMb.TryGetValue(presetTag, out var presetLimit))
            return presetLimit;

        var value = TargetSizeBox?.Value ?? 10;
        return double.IsFinite(value) && value >= 1 ? value : 10;
    }

    private double SelectedVmafTarget()
    {
        var value = VmafTargetBox?.Value ?? 93;
        return double.IsFinite(value) ? Math.Clamp(value, 50, 100) : 93;
    }

    private string SelectedVmafEncoder()
    {
        if (VmafEncoderCombo?.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "libsvtav1";
    }

    private string SelectedVmafEncoderLabel()
    {
        if (VmafEncoderCombo?.SelectedItem is ComboBoxItem item)
            return item.Content?.ToString() ?? "SVT-AV1";
        return "SVT-AV1";
    }

    private ConversionRerunRequest BuildRerunRequest(string sourcePath, string outputPath) =>
        new()
        {
            Surface = "compressor",
            SourcePaths = [sourcePath],
            OutputFormat = Path.GetExtension(outputPath).TrimStart('.'),
            OutputDirectory = _outputDirectory,
            OutputPath = outputPath,
            PageSettings = new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
            {
                ["preset"] = PresetTarget.IsChecked == true
                    ? "__target__"
                    : PresetVmaf.IsChecked == true
                        ? "__vmaf__"
                        : PresetPro.IsChecked == true
                            ? "__pro__"
                            : SelectedPresetTag(),
                ["targetPreset"] = SelectedTargetPresetTag(),
                ["targetMegabytes"] = SelectedTargetLimitMb().ToString(CultureInfo.InvariantCulture),
                ["vmafEncoder"] = SelectedVmafEncoder(),
                ["vmafTarget"] = SelectedVmafTarget().ToString(CultureInfo.InvariantCulture),
                ["hardwareAcceleration"] = SelectedHwAccel(),
                ["d3d12Deinterlace"] = (D3D12DeinterlaceToggle.IsChecked == true).ToString(),
            },
        };

    private string BuildOutputPath(string inputPath, bool smartQualityMode = false)
    {
        var dir = _outputDirectory ?? Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(inputPath);
        var suffix = smartQualityMode
            ? $"_smart_vmaf{SelectedVmafTarget().ToString("0.##", CultureInfo.InvariantCulture)}"
            : "_compressed";
        var extension = smartQualityMode ? ".mkv" : ".mp4";
        return EnsureUniquePath(Path.Combine(dir, name + suffix + extension));
    }

    private static string EnsureUniquePath(string path)
    {
        if (!File.Exists(path))
            return path;

        var directory = Path.GetDirectoryName(path) ?? ".";
        var name = Path.GetFileNameWithoutExtension(path);
        var extension = Path.GetExtension(path);
        for (var i = 1; i < 10_000; i++)
        {
            var candidate = Path.Combine(directory, $"{name} ({i}){extension}");
            if (!File.Exists(candidate))
                return candidate;
        }

        return Path.Combine(directory, $"{name}-{Guid.NewGuid():N}{extension}");
    }

    private static void OpenContainingFolder(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
            return;

        var folder = Directory.Exists(path)
            ? path
            : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder))
            return;

        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{folder}\"")
            {
                UseShellExecute = true,
            });
        }
        catch
        {
            // Convenience action only; keep compression state intact if Explorer fails.
        }
    }

    private static string SavingsLabel(long inputBytes, long outputBytes)
    {
        if (inputBytes <= 0 || outputBytes <= 0)
            return "No savings data";

        var ratio = (1.0 - (double)outputBytes / inputBytes) * 100.0;
        return ratio >= 0
            ? $"Saved {ratio:F1}% ({FormatSize(inputBytes - outputBytes)})"
            : $"Output is larger by {-ratio:F1}%";
    }

    private static string FormatSize(long bytes)
    {
        string[] s = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        double v = bytes;
        while (v >= 1024 && i < s.Length - 1)
        {
            v /= 1024;
            i++;
        }

        return $"{v:F1} {s[i]}";
    }
}

public sealed class CompressionFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _presetSummary = "";
    private long _resultSizeBytes;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string Extension { get; set; } = "";
    public string SourceSummary { get; set; } = "";
    public long SourceSizeBytes { get; set; }
    public string? OutputPath { get; set; }
    public string? ErrorMessage { get; set; }
    public string Engine { get; set; } = "videocrush";

    public long ResultSizeBytes
    {
        get => _resultSizeBytes;
        set => SetProperty(ref _resultSizeBytes, value);
    }

    public double Progress
    {
        get => _progress;
        set => SetProperty(ref _progress, value);
    }

    public string StatusText
    {
        get => _statusText;
        set => SetProperty(ref _statusText, value);
    }

    public string PresetSummary
    {
        get => _presetSummary;
        set => SetProperty(ref _presetSummary, value);
    }

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value))
            return;

        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}

public sealed class CompressionFinishedItem
{
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush AccentBrush { get; set; } = null!;
    public bool CanOpenFolder => Success && !string.IsNullOrWhiteSpace(OutputPath);
}
