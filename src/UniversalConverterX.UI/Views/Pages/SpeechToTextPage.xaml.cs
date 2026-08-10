using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class SpeechToTextPage : Page
{
    private static readonly string[] AudioExtensions =
    [
        ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"
    ];

    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v"
    ];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<SttFileItem> _files = [];
    private readonly ObservableCollection<SttFinishedItem> _finished = [];
    private CancellationTokenSource? _cts;
    private CancellationTokenSource? _waveformCts;
    private string? _previewedWaveformPath;
    private string? _outputFolder;
    private bool _parakeetModelReady;
    private bool _diarizationModelReady;
    private bool _modelActionRunning;

    public SpeechToTextPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        ApplyBackendCapabilities();
        _ = RefreshDiarizationModelStatusAsync();
        UpdateUi();
    }

    // -------------------------------------------------------------------------
    // Drop zone
    // -------------------------------------------------------------------------

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Drop audio or video into queue");
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

    // -------------------------------------------------------------------------
    // Browse
    // -------------------------------------------------------------------------

    private void Browse_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
        };
        foreach (var ext in AudioExtensions.Concat(VideoExtensions))
            picker.FileTypeFilter.Add(ext);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;

        foreach (var file in files)
            AddFile(file.Path);
    }

    private async void BrowseFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
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
        if (folder is null) return;

        _outputFolder = folder.Path;
        OutputFolderBox.Text = _outputFolder;
    }

    // -------------------------------------------------------------------------
    // File management
    // -------------------------------------------------------------------------

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path)) return;

        var supported = AudioExtensions.Concat(VideoExtensions)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path)
                     .Where(f => supported.Contains(Path.GetExtension(f)))
                     .Take(200))
        {
            if (AddFile(file, updateUi: false))
                added++;
        }

        StatusLabel.Text = added == 0
            ? AppLocalizer.Get("No supported files found in that folder.")
            : AppLocalizer.Format($"Added {added} files from {path}.");
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => f.Path == path)) return false;

        var info = new FileInfo(path);
        if (!info.Exists) return false;

        var ext = info.Extension;
        var supported = AudioExtensions.Concat(VideoExtensions)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!supported.Contains(ext)) return false;

        _files.Add(new SttFileItem
        {
            Path = path,
            FileName = info.Name,
            SourceSummary = $"{FormatSize(info.Length)} - {ext.TrimStart('.').ToUpperInvariant()}",
            SettingsSummary = BuildSettingsSummary(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi) UpdateUi();
        return true;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is SttFileItem file)
        {
            _files.Remove(file);
            UpdateUi();
        }
    }

    private void ClearAll_Click(object sender, RoutedEventArgs e)
    {
        _files.Clear();
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (EmptyState is null) return;
        UpdateUi();
    }

    // -------------------------------------------------------------------------
    // Settings change
    // -------------------------------------------------------------------------

    private async void Backend_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (TranscribeButton is null) return;
        ApplyBackendCapabilities();
        Settings_Changed(sender, e);
        if (SelectedComboTag(BackendCombo) == "parakeet-stt")
            await RefreshParakeetModelStatusAsync();
        else if (SelectedComboTag(BackendCombo) == "whisper-stt")
            await RefreshDiarizationModelStatusAsync();
    }

    private void Settings_Changed(object sender, object e)
    {
        if (TranscribeButton is null) return;
        var summary = BuildSettingsSummary();
        foreach (var f in _files)
            f.SettingsSummary = summary;
    }

    private void Settings_Number_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (TranscribeButton is null) return;
        var summary = BuildSettingsSummary();
        foreach (var f in _files)
            f.SettingsSummary = summary;
    }

    private void ApplyBackendCapabilities()
    {
        if (BackendCombo is null || WhisperModelPanel is null) return;
        var backend = SelectedComboTag(BackendCombo) ?? "whisper-stt";
        var parakeet = backend == "parakeet-stt";

        WhisperModelPanel.Visibility = parakeet ? Visibility.Collapsed : Visibility.Visible;
        ParakeetModelPanel.Visibility = parakeet ? Visibility.Visible : Visibility.Collapsed;
        DiarizationModelPanel.Visibility = backend == "whisper-stt"
            ? Visibility.Visible
            : Visibility.Collapsed;
        LanguageCombo.Visibility = parakeet ? Visibility.Collapsed : Visibility.Visible;
        ParakeetLanguageNote.Visibility = parakeet ? Visibility.Visible : Visibility.Collapsed;
        BatchSizeBox.IsEnabled = backend == "whisper-stt";
        VadCheck.IsEnabled = backend != "parakeet-stt";
        DiarizationCheck.IsEnabled = backend == "whisper-stt";
        if (parakeet)
            VadCheck.IsChecked = false;
        if (backend != "whisper-stt")
            DiarizationCheck.IsChecked = false;
        UpdateUi();
    }

    private async void Diarization_Changed(object sender, RoutedEventArgs e)
    {
        if (TranscribeButton is null) return;
        Settings_Changed(sender, e);
        if (DiarizationCheck.IsChecked == true &&
            SelectedComboTag(BackendCombo) == "whisper-stt" &&
            !_diarizationModelReady)
        {
            await RefreshDiarizationModelStatusAsync();
        }
        UpdateUi();
    }

    private async Task RefreshParakeetModelStatusAsync()
    {
        if (_modelActionRunning) return;
        if (_runner.Locate("parakeet-stt") is null)
        {
            _parakeetModelReady = false;
            DownloadParakeetModelButton.IsEnabled = false;
            ParakeetModelStatus.Text = AppLocalizer.Get("Parakeet sidecar is not installed in this build.");
            UpdateUi();
            return;
        }
        _modelActionRunning = true;
        _parakeetModelReady = false;
        DownloadParakeetModelButton.IsEnabled = false;
        ParakeetModelStatus.Text = AppLocalizer.Get("Checking local model pack...");
        UpdateUi();
        try
        {
            var result = await _runner.RunAsync(
                "parakeet-stt",
                ["model-status"],
                ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromSeconds(30));
            _parakeetModelReady = result.Success;
            ParakeetModelStatus.Text = result.Success
                ? AppLocalizer.Get("Model ready — pinned local snapshot found.")
                : result.ErrorCode == "sidecar_not_found"
                    ? AppLocalizer.Get("Parakeet sidecar is not installed in this build.")
                    : AppLocalizer.Get("Model not installed. Review the license and download it when ready.");
        }
        finally
        {
            _modelActionRunning = false;
            DownloadParakeetModelButton.IsEnabled = true;
            UpdateUi();
        }
    }

    private async void DownloadParakeetModel_Click(object sender, RoutedEventArgs e)
    {
        if (_modelActionRunning || _runner.Locate("parakeet-stt") is null) return;

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = AppLocalizer.Get("Download NVIDIA Parakeet TDT v3?"),
            Content = AppLocalizer.Get("This downloads the pinned approximately 2.5 GB model pack from Hugging Face. The model is governed by CC-BY-4.0. Downloading confirms that you accept that license. UCX will not download or update this model during transcription."),
            PrimaryButtonText = AppLocalizer.Get("Accept & download"),
            CloseButtonText = AppLocalizer.Get("Cancel"),
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
            return;

        _modelActionRunning = true;
        _parakeetModelReady = false;
        DownloadParakeetModelButton.IsEnabled = false;
        ParakeetModelStatus.Text = AppLocalizer.Get("Downloading pinned model pack...");
        UpdateUi();
        try
        {
            var progress = new Progress<SidecarProgress>(value =>
                DispatcherQueue.TryEnqueue(() =>
                    ParakeetModelStatus.Text = string.IsNullOrWhiteSpace(value.Stage)
                        ? AppLocalizer.Format($"Downloading... {value.Percent:F0}%")
                        : AppLocalizer.Format($"{value.Stage} ({value.Percent:F0}%)")));
            var result = await _runner.RunAsync(
                "parakeet-stt",
                ["download-model", "--accept-license"],
                progress,
                ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromHours(2));
            _parakeetModelReady = result.Success;
            ParakeetModelStatus.Text = result.Success
                ? AppLocalizer.Get("Model ready — pinned local snapshot installed.")
                : AppLocalizer.Format($"Download failed: {result.ErrorMessage ?? "Unknown error"}");
        }
        finally
        {
            _modelActionRunning = false;
            DownloadParakeetModelButton.IsEnabled = true;
            UpdateUi();
        }
    }

    private async Task RefreshDiarizationModelStatusAsync()
    {
        if (_modelActionRunning || SelectedComboTag(BackendCombo) != "whisper-stt") return;
        if (_runner.Locate("whisper-stt") is null)
        {
            _diarizationModelReady = false;
            DownloadDiarizationModelButton.IsEnabled = false;
            DiarizationModelStatus.Text = AppLocalizer.Get("Whisper sidecar is not installed in this build.");
            UpdateUi();
            return;
        }

        _modelActionRunning = true;
        _diarizationModelReady = false;
        DownloadDiarizationModelButton.IsEnabled = false;
        DiarizationModelStatus.Text = AppLocalizer.Get("Checking local speaker model pack...");
        UpdateUi();
        try
        {
            var result = await _runner.RunAsync(
                "whisper-stt",
                ["model-status"],
                ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromSeconds(30));
            _diarizationModelReady = result.Success;
            DiarizationModelStatus.Text = result.Success
                ? AppLocalizer.Get("Speaker model ready — pinned local pack found.")
                : result.ErrorCode == "sidecar_not_found"
                    ? AppLocalizer.Get("Whisper sidecar is not installed in this build.")
                    : AppLocalizer.Get("Speaker model not installed. Review the terms and download it when ready.");
        }
        finally
        {
            _modelActionRunning = false;
            DownloadDiarizationModelButton.IsEnabled = true;
            UpdateUi();
        }
    }

    private async void DownloadDiarizationModel_Click(object sender, RoutedEventArgs e)
    {
        if (_modelActionRunning || _runner.Locate("whisper-stt") is null) return;

        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = AppLocalizer.Get("Download the offline speaker model?"),
            Content = AppLocalizer.Get("This downloads the revision-pinned pyannote 3.1 speaker model pack (approximately 32 MB) from Hugging Face. The model is MIT-licensed but access is gated by the upstream model terms, which may request contact information. Downloading confirms that you accept those terms. UCX stores and verifies the local files, then performs diarization without network access or telemetry."),
            PrimaryButtonText = AppLocalizer.Get("Accept terms & download"),
            CloseButtonText = AppLocalizer.Get("Cancel"),
            DefaultButton = ContentDialogButton.Close,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
            return;

        _modelActionRunning = true;
        _diarizationModelReady = false;
        DownloadDiarizationModelButton.IsEnabled = false;
        DiarizationModelStatus.Text = AppLocalizer.Get("Downloading pinned speaker model pack...");
        UpdateUi();
        try
        {
            var progress = new Progress<SidecarProgress>(value =>
                DispatcherQueue.TryEnqueue(() =>
                    DiarizationModelStatus.Text = string.IsNullOrWhiteSpace(value.Stage)
                        ? AppLocalizer.Format($"Downloading... {value.Percent:F0}%")
                        : AppLocalizer.Format($"{value.Stage} ({value.Percent:F0}%)")));
            var result = await _runner.RunAsync(
                "whisper-stt",
                ["download-model", "--accept-license"],
                progress,
                ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromHours(2));
            _diarizationModelReady = result.Success;
            DiarizationModelStatus.Text = result.Success
                ? AppLocalizer.Get("Speaker model ready — pinned local pack installed.")
                : AppLocalizer.Format($"Download failed: {result.ErrorMessage ?? "Unknown error"}");
        }
        finally
        {
            _modelActionRunning = false;
            DownloadDiarizationModelButton.IsEnabled = true;
            UpdateUi();
        }
    }

    // -------------------------------------------------------------------------
    // Transcribe
    // -------------------------------------------------------------------------

    private async void Transcribe_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null) return;

        var backend = SelectedComboTag(BackendCombo) ?? "whisper-stt";
        var model = SelectedComboTag(ModelCombo) ?? "base";
        var language = SelectedComboTag(LanguageCombo) ?? "auto";
        var format = SelectedComboTag(FormatCombo) ?? "srt";
        var wordTs = WordTimestampsToggle.IsOn;
        var useVad = VadCheck?.IsChecked == true;
        var useDiarization = backend == "whisper-stt" && DiarizationCheck?.IsChecked == true;
        var batchSize = SafeBatchSize(BatchSizeBox?.Value);
        if (backend == "parakeet-stt" && !_parakeetModelReady)
        {
            StatusLabel.Text = AppLocalizer.Get("Download the Parakeet model pack before transcription.");
            return;
        }
        if (useDiarization && !_diarizationModelReady)
        {
            StatusLabel.Text = AppLocalizer.Get("Download the offline speaker model pack before transcription.");
            return;
        }

        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;

        _cts = new CancellationTokenSource();
        TranscribeButton.IsEnabled = false;
        CancelButton.IsEnabled = true;

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested) break;

                var outputPath = BuildOutputPath(item.Path, format);

                // Per-backend arg shape:
                //   whisper-stt (faster-whisper):  no subcommand, flat flags.
                //   whisper-cpp:                   `transcribe` subcommand,
                //                                  output extension drives format.
                List<string> args;
                if (backend == "parakeet-stt")
                {
                    args =
                    [
                        "transcribe",
                        "--input", item.Path,
                        "--output", outputPath,
                        "--format", format,
                        "--language", "auto",
                    ];
                    if (wordTs) args.Add("--word-timestamps");
                }
                else if (backend is "whisper-cpp" or "ffmpeg-whisper")
                {
                    // Native whisper backends use the output extension as their format contract.
                    // Replace whatever we built with the format-driven extension.
                    var ext = format switch
                    {
                        "vtt" => ".vtt",
                        "txt" => ".txt",
                        "json" => ".json",
                        _ => ".srt",
                    };
                    var dir = Path.GetDirectoryName(outputPath);
                    var stem = Path.GetFileNameWithoutExtension(outputPath);
                    outputPath = Path.Combine(dir ?? "", stem + ext);

                    args =
                    [
                        "transcribe",
                        "--input",    item.Path,
                        "--output",   outputPath,
                        "--model",    model,           // sidecar accepts bare 'base' / 'large-v3' / etc.
                        "--language", language,
                    ];
                    if (wordTs) args.Add("--word-timestamps");
                    if (useVad) args.Add("--vad");
                }
                else
                {
                    args =
                    [
                        "--input",    item.Path,
                        "--output",   outputPath,
                        "--model",    model,
                        "--language", language,
                        "--format",   format,
                    ];
                    if (wordTs) args.Add("--word-timestamps");
                    if (useVad) args.Add("--vad");
                    if (useDiarization) args.Add("--diarize");
                    args.Add("--batch-size");
                    args.Add(batchSize.ToString(CultureInfo.InvariantCulture));
                }

                item.Progress = 0;
                item.StatusText = "Transcribing";
                StatusLabel.Text = AppLocalizer.Format($"Transcribing {item.FileName}... ({completed + failed + 1}/{jobs.Count})");

                var progressHandler = new Progress<SidecarProgress>(p =>
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        item.Progress = p.Percent;
                        item.StatusText = $"{p.Percent:F0}%";
                        if (!string.IsNullOrEmpty(p.Stage))
                            item.StatusText = p.Stage;
                    }));

                var logHandler = new Progress<SidecarLog>(_ => { });

                var result = await _runner.RunAsync(
                    backend, args, progressHandler, logHandler, _cts.Token);

                if (result.Success)
                {
                    completed++;
                    item.Progress = 100;
                    item.StatusText = "Done";
                    var fi = new FileInfo(outputPath);
                    _finished.Add(new SttFinishedItem
                    {
                        FileName = item.FileName,
                        Details = $"Transcribed using {(backend == "parakeet-stt" ? "Parakeet TDT v3" : model)} — {(fi.Exists ? FormatSize(fi.Length) : "?")}",
                        OutputPath = outputPath,
                        Glyph = "\uE73E",
                        AccentBrush = (SolidColorBrush)Application.Current.Resources["AccentGreenBrush"],
                        CanOpenFile = fi.Exists,
                    });
                }
                else
                {
                    failed++;
                    item.Progress = 0;
                    item.StatusText = result.ErrorMessage?.Length > 40
                        ? result.ErrorMessage[..40] + "..."
                        : result.ErrorMessage ?? "Error";
                    _finished.Add(new SttFinishedItem
                    {
                        FileName = item.FileName,
                        Details = $"Failed: {result.ErrorMessage ?? "Unknown error"}",
                        OutputPath = string.Empty,
                        Glyph = "\uE783",
                        AccentBrush = (SolidColorBrush)Application.Current.Resources["AccentRedBrush"],
                        CanOpenFile = false,
                    });
                }
            }

            var msg = _cts.IsCancellationRequested
                ? $"Cancelled — {completed} completed, {failed} failed."
                : $"Done — {completed} transcribed, {failed} failed.";
            StatusLabel.Text = msg;

            if (_finished.Count > 0)
            {
                FinishedList.Visibility = Visibility.Visible;
                FinishedEmptyState.Visibility = Visibility.Collapsed;
                QueuePivot.SelectedIndex = 1;
            }

            // Remove successful files from queue
            foreach (var item in jobs.Where(j => j.Progress >= 100).ToList())
                _files.Remove(item);
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
            UpdateUi();
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        StatusLabel.Text = AppLocalizer.Get("Cancelling...");
        CancelButton.IsEnabled = false;
    }

    // -------------------------------------------------------------------------
    // Output finished items
    // -------------------------------------------------------------------------

    private void OpenFinishedFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is string path && File.Exists(path))
            Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
    }

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is string path)
        {
            var dir = File.Exists(path) ? Path.GetDirectoryName(path) : path;
            if (!string.IsNullOrEmpty(dir) && Directory.Exists(dir))
                Process.Start(new ProcessStartInfo("explorer.exe", $"\"{dir}\"") { UseShellExecute = true });
        }
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private string BuildOutputPath(string inputPath, string format)
    {
        var stem = Path.GetFileNameWithoutExtension(inputPath);
        var ext = $".{format}";
        var dir = string.IsNullOrEmpty(_outputFolder)
            ? Path.GetDirectoryName(inputPath) ?? Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments)
            : _outputFolder;
        return Path.Combine(dir, stem + "_transcript" + ext);
    }

    private string BuildSettingsSummary()
    {
        var model = SelectedComboTag(ModelCombo) ?? "base";
        var format = SelectedComboTag(FormatCombo) ?? "srt";
        var backend = SelectedComboTag(BackendCombo) ?? "whisper-stt";
        if (backend == "parakeet-stt")
            return $"Parakeet TDT v3 / .{format} / auto";
        var batch = backend == "whisper-stt" ? $" / b{SafeBatchSize(BatchSizeBox?.Value)}" : "";
        var vad = VadCheck?.IsChecked == true ? " / VAD" : "";
        var speakers = backend == "whisper-stt" && DiarizationCheck?.IsChecked == true
            ? " / speakers"
            : "";
        return $"{model} / .{format}{batch}{vad}{speakers}";
    }

    private static string? SelectedComboTag(ComboBox combo)
    {
        return (combo.SelectedItem as ComboBoxItem)?.Tag as string;
    }

    private static int SafeBatchSize(double? value)
    {
        if (value is null || double.IsNaN(value.Value)) return 8;
        return Math.Clamp((int)Math.Round(value.Value), 1, 32);
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1_073_741_824 => $"{bytes / 1_073_741_824.0:F1} GB",
        >= 1_048_576 => $"{bytes / 1_048_576.0:F1} MB",
        >= 1_024 => $"{bytes / 1_024.0:F1} KB",
        _ => $"{bytes} B",
    };

    private void UpdateUi()
    {
        if (EmptyState is null) return;

        var hasFiles = _files.Count > 0;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;

        var hasFinished = _finished.Count > 0;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;

        var selectedBackend = SelectedComboTag(BackendCombo) ?? "whisper-stt";
        var diarizationReady = selectedBackend != "whisper-stt"
            || DiarizationCheck?.IsChecked != true
            || _diarizationModelReady;
        var modelReady = (selectedBackend != "parakeet-stt" || _parakeetModelReady)
            && diarizationReady;
        TranscribeButton.IsEnabled = hasFiles && _cts is null && modelReady && !_modelActionRunning;
        CancelButton.IsEnabled = _cts is not null;

        if (!hasFiles)
            StatusLabel.Text = AppLocalizer.Get("Add audio or video files to transcribe.");

        UpdateWaveformPreview();
    }

    /// <summary>
    /// Renders a waveform PNG for the most-recently-added file into the preview
    /// card. Skips unchanged targets and degrades silently to a hidden card when
    /// FFmpeg/the mediathumb sidecar is unavailable — transcription never depends
    /// on the preview.
    /// </summary>
    private void UpdateWaveformPreview()
    {
        if (WaveformCard is null)
            return;

        var target = _files.Count > 0 ? _files[^1] : null;
        if (target is null)
        {
            _waveformCts?.Cancel();
            _previewedWaveformPath = null;
            WaveformCard.Visibility = Visibility.Collapsed;
            WaveformImage.Source = null;
            return;
        }

        if (string.Equals(target.Path, _previewedWaveformPath, StringComparison.OrdinalIgnoreCase))
            return;

        _previewedWaveformPath = target.Path;
        _waveformCts?.Cancel();
        _waveformCts = new CancellationTokenSource();
        _ = RenderWaveformAsync(target.Path, target.FileName, _waveformCts.Token);
    }

    private async Task RenderWaveformAsync(string sourcePath, string fileName, CancellationToken ct)
    {
        if (_runner.Locate("mediathumb") is null)
        {
            WaveformCard.Visibility = Visibility.Collapsed;
            return;
        }

        try
        {
            var outputDirectory = Path.Combine(
                Path.GetTempPath(), "UniversalConverterX", "waveforms");
            Directory.CreateDirectory(outputDirectory);
            var outputPath = Path.Combine(
                outputDirectory,
                $"{Path.GetFileNameWithoutExtension(sourcePath)}-{Math.Abs(sourcePath.GetHashCode()):x8}.png");

            string? emittedPath = null;
            var result = await _runner.RunAsync(
                "mediathumb",
                [
                    "waveform",
                    "--input", sourcePath,
                    "--output", outputPath,
                    "--width", "900",
                    "--height", "160",
                ],
                ct: ct,
                onRawEvent: (eventName, payload) =>
                {
                    if (eventName == "waveform_doc"
                        && payload.TryGetProperty("output", out var output)
                        && output.ValueKind == System.Text.Json.JsonValueKind.String)
                    {
                        emittedPath = output.GetString();
                    }
                });

            if (ct.IsCancellationRequested)
                return;

            var image = emittedPath ?? outputPath;
            if (!result.Success || string.IsNullOrWhiteSpace(image) || !File.Exists(image))
            {
                WaveformCard.Visibility = Visibility.Collapsed;
                return;
            }

            DispatcherQueue.TryEnqueue(() =>
            {
                if (ct.IsCancellationRequested || !File.Exists(image))
                    return;
                WaveformImage.Source = new BitmapImage(new Uri(image)) { DecodePixelWidth = 900 };
                WaveformCaption.Text = fileName;
                WaveformCard.Visibility = Visibility.Visible;
            });
        }
        catch (OperationCanceledException)
        {
            // Superseded by a newer selection — nothing to clean up.
        }
        catch (Exception)
        {
            DispatcherQueue.TryEnqueue(() => WaveformCard.Visibility = Visibility.Collapsed);
        }
    }
}

// -------------------------------------------------------------------------
// Data models
// -------------------------------------------------------------------------

internal sealed class SttFileItem : INotifyPropertyChanged
{
    public string Path { get; init; } = string.Empty;
    public string FileName { get; init; } = string.Empty;
    public string SourceSummary { get; init; } = string.Empty;

    private string _settingsSummary = string.Empty;
    public string SettingsSummary
    {
        get => _settingsSummary;
        set { _settingsSummary = value; OnPropertyChanged(); }
    }

    private double _progress;
    public double Progress
    {
        get => _progress;
        set { _progress = value; OnPropertyChanged(); }
    }

    private string _statusText = string.Empty;
    public string StatusText
    {
        get => _statusText;
        set { _statusText = value; OnPropertyChanged(); }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    private void OnPropertyChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

internal sealed class SttFinishedItem
{
    public string FileName { get; init; } = string.Empty;
    public string Details { get; init; } = string.Empty;
    public string OutputPath { get; init; } = string.Empty;
    public string Glyph { get; init; } = "\uE73E";
    public SolidColorBrush? AccentBrush { get; init; }
    public bool CanOpenFile { get; init; }
}
