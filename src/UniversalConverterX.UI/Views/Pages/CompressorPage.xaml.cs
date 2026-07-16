using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class CompressorPage : Page
{
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
    private const double TargetSizeHeadroom = 0.95;

    private static readonly IReadOnlyDictionary<string, double> TargetSizeLimitsMb =
        new Dictionary<string, double>(StringComparer.Ordinal)
        {
            ["discord-10mb"] = 10,
            ["discord-25mb"] = 25,
            ["discord-50mb"] = 50,
            ["email-25mb"] = 25,
        };

    private readonly ISidecarRunner _runner;
    private readonly ISidecarHealthService _health;
    private readonly IHistoryService _history;
    private readonly IPostQueueActionService _postQueueActions;
    private readonly ObservableCollection<CompressionFileItem> _files = [];
    private readonly ObservableCollection<CompressionFinishedItem> _finished = [];
    private CancellationTokenSource? _cts;
    private string? _outputDirectory;

    public CompressorPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _health = App.Services.GetRequiredService<ISidecarHealthService>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        _postQueueActions = App.Services.GetRequiredService<IPostQueueActionService>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        UpdatePresetSummaries();
        UpdateUi();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop into compression queue";
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
    }

    private void SameAsSource_Click(object sender, RoutedEventArgs e)
    {
        _outputDirectory = null;
        OutputDirectoryBox.Text = "";
        UpdateStatusText();
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
        {
            StatusText.Text = $"Folder not found: {path}";
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
            StatusText.Text = "Permission denied for that folder.";
            return;
        }
        catch (Exception ex)
        {
            StatusText.Text = $"Could not read folder: {ex.Message}";
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
            StatusText.Text = "No supported video files were added from that folder.";
        else if (truncated)
            StatusText.Text = $"Added {added} videos from {path} (capped at {FolderAddCap}).";
        else
            StatusText.Text = $"Added {added} videos from {path}.";
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
            UpdateUi();

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
        UpdatePresetSummaries();
        UpdateStatusText();
    }

    private void ProPreset_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (StatusText is null) return;
        UpdatePresetSummaries();
        UpdateStatusText();
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
    }

    private void TargetSize_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (StatusText is null || !IsTargetSizeMode) return;
        UpdatePresetSummaries();
        UpdateStatusText();
    }

    private void VmafTarget_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (StatusText is null || !IsVmafTargetMode) return;
        UpdatePresetSummaries();
        UpdateStatusText();
    }

    private void VmafEncoder_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (StatusText is null || !IsVmafTargetMode) return;
        UpdatePresetSummaries();
        UpdateStatusText();
    }

    private void HwAccel_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (StatusText is null) return;
        UpdateStatusText();
    }

    private string SelectedHwAccel()
    {
        if (HwAccelCombo?.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "none";
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
            StatusText.Text = "Checking ab-av1 smart-compression requirements...";
            SidecarHealthReport report;
            try
            {
                report = await _health.EvaluateEngineAsync("ab-av1");
            }
            catch (Exception ex)
            {
                UpdateUi();
                VmafHealthText.Text = $"Health check failed: {ex.Message}";
                StatusText.Text = "Smart compression is unavailable because its requirements could not be checked.";
                return;
            }

            VmafHealthText.Text = report.CanRun
                ? $"{report.Summary}. {report.Detail}"
                : report.Detail;
            if (!report.CanRun)
            {
                UpdateUi();
                StatusText.Text = $"Smart compression unavailable — {report.Summary}. {report.Detail}";
                return;
            }
        }

        if (_outputDirectory is not null)
        {
            try { Directory.CreateDirectory(_outputDirectory); }
            catch (Exception ex)
            {
                UpdateUi();
                StatusText.Text = $"Output folder unavailable: {ex.Message}";
                return;
            }
        }

        var preset = SelectedPresetTag();
        var engine = smartQualityMode ? "ab-av1" : "videocrush";
        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;
        long resultBytes = 0;
        var batchStartedAt = DateTime.UtcNow;
        var completionItems = new List<QueueCompletionItem>();

        _cts = new CancellationTokenSource();
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
                List<string> args;
                if (smartQualityMode)
                {
                    args =
                    [
                        "auto-encode",
                        "--input", item.Path,
                        "--output", outputPath,
                        "--encoder", SelectedVmafEncoder(),
                        "--target-vmaf", SelectedVmafTarget().ToString("0.##", CultureInfo.InvariantCulture),
                        "--preset", SelectedVmafEncoderPreset(),
                        "--verify-vmaf",
                    ];
                }
                else
                {
                    args = ["--input", item.Path, "--output", outputPath];
                    if (IsTargetSizeMode)
                    {
                        var targetPreset = SelectedTargetPresetTag();
                        if (targetPreset == "custom")
                        {
                            args.AddRange(
                            [
                                "--target-mb", (SelectedTargetLimitMb() * TargetSizeHeadroom).ToString("0.###", CultureInfo.InvariantCulture),
                                "--codec", "libx264",
                                "--ffmpeg-preset", "slow",
                                "--resolution", "720p",
                                "--audio-codec", "aac",
                                "--audio-bitrate", "96",
                            ]);
                        }
                        else
                        {
                            args.AddRange(["--preset", targetPreset]);
                        }
                        args.AddRange(["--hwaccel", "none"]);
                    }
                    else
                    {
                        args.AddRange(["--preset", preset, "--hwaccel", SelectedHwAccel()]);
                    }
                }

                item.StatusText = "Compressing";
                item.Progress = 0;
                ProgressTitle.Text = $"Compressing {item.FileName}";
                ProgressStage.Text = $"{completed + failed + 1} of {jobs.Count}";

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = $"{p.Percent:F0}%";
                    var overall = ((completed + failed) * 100.0 + p.Percent) / jobs.Count;
                    ProgressBar.Value = Math.Clamp(overall, 0, 100);
                    ProgressStage.Text = $"{p.Percent:F1}% - {p.Stage}";
                    ProgressEta.Text = p.EtaSeconds is int eta and >= 0
                        ? $"ETA {TimeSpan.FromSeconds(eta):mm\\:ss}"
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

                var result = await _runner.RunAsync(engine, args, progress, log, _cts.Token, rawEvent);
                if (result.Success)
                {
                    completed++;
                    item.Progress = 100;
                    item.StatusText = verifiedVmaf is double vmaf
                        ? $"Done · VMAF {vmaf:0.00}"
                        : "Done";
                    item.ResultSizeBytes = result.SizeBytes ?? 0;
                    resultBytes += item.ResultSizeBytes;
                }
                else
                {
                    failed++;
                    item.StatusText = result.ErrorCode == "cancelled" ? "Cancelled" : "Failed";
                }

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
                    });
                }

                if (result.ErrorCode == "cancelled")
                    break;
            }
        }
        finally
        {
            _cts.Dispose();
            _cts = null;
        }

        ProgressTitle.Text = failed == 0 ? "Done" : "Completed with errors";
        ProgressBar.Value = failed == 0 ? 100 : ProgressBar.Value;
        ProgressStage.Text = $"{completed} succeeded, {failed} failed";
        ProgressEta.Text = "";
        CancelButton.Content = "Close";
        QueuePivot.SelectedIndex = _finished.Count > 0 ? 1 : 0;
        UpdateTotals(resultBytes);
        UpdateUi();

        foreach (var pending in jobs.Skip(completionItems.Count))
        {
            completionItems.Add(new QueueCompletionItem
            {
                Source = pending.Path,
                Status = QueueCompletionItemStatus.Cancelled,
                Message = "Not started because the queue was cancelled.",
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

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
        {
            _cts.Cancel();
            return;
        }

        ProgressOverlay.Visibility = Visibility.Collapsed;
        CancelButton.Content = "Cancel";
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
        ProgressStage.Text = "Starting...";
        ProgressEta.Text = "";
        ProgressBar.Value = 0;
        CancelButton.Content = "Cancel";
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
        ClearButton.IsEnabled = hasFiles && _cts is null;
        UpdateTotals();
        UpdateStatusText();
    }

    private void UpdateTotals(long? explicitResultBytes = null)
    {
        var sourceBytes = _files.Sum(f => f.SourceSizeBytes);
        var resultBytes = explicitResultBytes ?? _files.Sum(f => f.ResultSizeBytes);

        SourceSizeText.Text = FormatSize(sourceBytes);
        ResultSizeText.Text = FormatSize(resultBytes);
        SavingsText.Text = sourceBytes > 0 && resultBytes > 0
            ? SavingsLabel(sourceBytes, resultBytes)
            : "Savings appear after compression.";
    }

    private void UpdateStatusText()
    {
        var output = _outputDirectory ?? "same folder as each source";
        StatusText.Text = _files.Count == 0
            ? "Add videos to start a compression queue."
            : $"Ready to compress {_files.Count} videos using {SelectedPresetLabel()}. Output: {output}.";
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

    private string SelectedVmafEncoderPreset() => SelectedVmafEncoder() switch
    {
        "libx265" => "medium",
        "libx264" => "slow",
        _ => "6",
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

    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string Extension { get; set; } = "";
    public string SourceSummary { get; set; } = "";
    public long SourceSizeBytes { get; set; }

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
