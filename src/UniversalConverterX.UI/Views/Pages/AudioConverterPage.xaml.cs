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
using Microsoft.UI.Xaml.Media.Imaging;
using UniversalConverterX.Core.Utilities;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class AudioConverterPage : Page
{
    private static readonly string[] AudioExtensions =
    [
        ".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".aac",
        ".ape", ".wv", ".tak", ".tta", ".alac", ".dsf", ".dff",
        ".ac3", ".eac3", ".dts", ".thd", ".mlp", ".amr", ".awb",
        ".spx", ".gsm", ".wma", ".mpc", ".au", ".snd", ".voc",
        ".ra", ".rm", ".sbc",
    ];

    private static readonly IReadOnlyDictionary<string, string> OutputExtensions =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["mp3"] = ".mp3",
            ["aac"] = ".m4a",
            ["fdk-aac"] = ".m4a",
            ["opus"] = ".opus",
            ["vorbis"] = ".ogg",
            ["flac"] = ".flac",
            ["wav"] = ".wav",
            ["alac"] = ".m4a",
            ["wavpack"] = ".wv",
            ["ac3"] = ".ac3",
            ["eac3"] = ".eac3",
            ["wma"] = ".wma",
        };

    private static readonly IReadOnlySet<string> LossyFormats = new HashSet<string>(
        ["mp3", "aac", "fdk-aac", "opus", "vorbis", "ac3", "eac3", "wma"],
        StringComparer.Ordinal);

    private static readonly IReadOnlySet<string> VariableBitrateFormats = new HashSet<string>(
        ["mp3", "aac", "fdk-aac", "opus", "vorbis"],
        StringComparer.Ordinal);

    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly ObservableCollection<AudioConversionFileItem> _files = [];
    private CancellationTokenSource? _cts;
    private CancellationTokenSource? _waveformCts;
    private string? _previewedWaveformPath;
    private string? _outputDirectory;
    private bool _viewReady;

    public AudioConverterPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        FileList.ItemsSource = _files;
        _viewReady = true;
        UpdateEncodingControls();
        UpdateUi();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Add to audio conversion queue");
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
            if (item is StorageFile file)
                AddFile(file.Path, updateUi: false);
            else if (item is StorageFolder folder)
                AddFolder(folder.Path, updateUi: false);
        }
        UpdateUi();
    }

    private void DropZone_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        if (_files.Count != 0)
            return;
        if (e.Pointer.PointerDeviceType == Microsoft.UI.Input.PointerDeviceType.Mouse &&
            !e.GetCurrentPoint(null).Properties.IsLeftButtonPressed)
        {
            return;
        }
        BrowseFiles();
    }

    private void Browse_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
        };
        foreach (var extension in AudioExtensions)
            picker.FileTypeFilter.Add(extension);

        var windowHandle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, windowHandle);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null)
            return;
        foreach (var file in files)
            AddFile(file.Path, updateUi: false);
        UpdateUi();
    }

    private async void BrowseFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.MusicLibrary };
        picker.FileTypeFilter.Add("*");
        var windowHandle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, windowHandle);
        var folder = await picker.PickSingleFolderAsync();
        if (folder is null)
            return;
        AddFolder(folder.Path);
    }

    private void AddFolder(string path, bool updateUi = true)
    {
        if (!Directory.Exists(path))
            return;

        try
        {
            foreach (var file in Directory.EnumerateFiles(path)
                         .Where(IsSupportedAudio)
                         .Take(2_000))
            {
                AddFile(file, updateUi: false);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            StatusText.Text = AppLocalizer.Format($"Could not read folder: {ex.Message}");
        }

        if (updateUi)
            UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(item => string.Equals(item.Path, path, StringComparison.OrdinalIgnoreCase)))
            return false;

        var info = new FileInfo(path);
        if (!info.Exists || !IsSupportedAudio(info.FullName))
            return false;

        _files.Add(new AudioConversionFileItem
        {
            Path = info.FullName,
            FileName = info.Name,
            SourceBytes = info.Length,
            SourceSummary = $"{FormatSize(info.Length)} · {info.Extension.TrimStart('.').ToUpperInvariant()}",
            StatusText = "Queued",
        });

        if (_outputDirectory is null)
        {
            var sourceDirectory = info.DirectoryName ?? Environment.CurrentDirectory;
            _outputDirectory = Path.Combine(sourceDirectory, "Converted Audio");
            OutputDirectoryBox.Text = _outputDirectory;
        }

        if (updateUi)
            UpdateUi();
        return true;
    }

    private void Remove_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
            return;
        if (sender is Button { Tag: AudioConversionFileItem item })
        {
            _files.Remove(item);
            UpdateUi();
        }
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null || _files.Count == 0)
            return;
        if (!await PageDialogService.ConfirmClearAsync(
                this,
                "Clear audio queue?",
                $"Remove {_files.Count} queued file(s)?"))
        {
            return;
        }

        _files.Clear();
        UpdateUi();
    }

    private async void BrowseOutput_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.MusicLibrary };
        picker.FileTypeFilter.Add("*");
        var windowHandle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, windowHandle);
        var folder = await picker.PickSingleFolderAsync();
        if (folder is null)
            return;

        _outputDirectory = folder.Path;
        OutputDirectoryBox.Text = folder.Path;
        UpdateStatusText();
    }

    private void Format_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (!_viewReady)
            return;
        UpdateEncodingControls();
        UpdateStatusText();
    }

    private void Vbr_Toggled(object sender, RoutedEventArgs e)
    {
        if (!_viewReady)
            return;
        UpdateEncodingControls();
        UpdateStatusText();
    }

    private void VorbisManaged_Toggled(object sender, RoutedEventArgs e)
    {
        if (!_viewReady)
            return;
        if (VorbisManagedToggle.IsOn)
            VbrToggle.IsOn = false;
        UpdateEncodingControls();
        UpdateStatusText();
    }

    private void Setting_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (_viewReady)
            UpdateStatusText();
    }

    private void NumberSetting_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (_viewReady)
            UpdateStatusText();
    }

    private void VbrQuality_ValueChanged(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (!_viewReady)
            return;

        var quality = (int)e.NewValue;
        var description = quality switch
        {
            <= 1 => "maximum quality",
            <= 3 => "high quality",
            <= 6 => "balanced",
            _ => "smallest files",
        };
        VbrQualityValue.Text = AppLocalizer.Format($"{quality} — {description}");
        UpdateStatusText();
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null || string.IsNullOrWhiteSpace(_outputDirectory))
            return;

        AudioConversionOptions options;
        try
        {
            options = BuildOptions();
            Directory.CreateDirectory(options.OutputDirectory);
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or UnauthorizedAccessException)
        {
            StatusText.Text = AppLocalizer.Format($"Invalid conversion setup: {ex.Message}");
            return;
        }

        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;
        _cts = new CancellationTokenSource();
        UpdateUi(updateStatus: false);

        try
        {
            for (var index = 0; index < jobs.Count; index++)
            {
                if (_cts.IsCancellationRequested)
                    break;

                var item = jobs[index];
                var startedAt = DateTime.UtcNow;
                item.Progress = 0;
                item.StatusText = "Converting";
                StatusText.Text = AppLocalizer.Format($"Converting {item.FileName} ({index + 1}/{jobs.Count})...");

                var progress = new Progress<SidecarProgress>(value => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = value.Percent;
                    item.StatusText = string.IsNullOrWhiteSpace(value.Stage)
                        ? $"{value.Percent:F0}%"
                        : value.Stage;
                }));
                var log = new Progress<SidecarLog>(_ => { });

                SidecarResult result;
                try
                {
                    var arguments = AudioConversionCommandBuilder.Build([item.Path], options);
                    result = await _runner.RunAsync(
                        "audiopro",
                        arguments,
                        progress,
                        log,
                        _cts.Token);
                }
                catch (OperationCanceledException)
                {
                    result = new SidecarResult(
                        false,
                        null,
                        null,
                        "cancelled",
                        "Cancelled by user.",
                        130);
                }
                catch (ArgumentException ex)
                {
                    result = new SidecarResult(false, null, null, "bad_options", ex.Message, -1);
                }

                var outputPath = result.Success
                    ? FindNewestOutput(item.Path, options.OutputDirectory, options.Format, startedAt)
                    : null;
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

                try
                {
                    await _history.LogAsync(new HistoryRecord
                    {
                        Timestamp = startedAt,
                        Engine = "audiopro",
                        Action = "convert",
                        SourcePath = item.Path,
                        OutputPath = outputPath,
                        SourceBytes = item.SourceBytes,
                        OutputBytes = TryFileSize(outputPath),
                        DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds,
                        Success = result.Success,
                        ErrorCode = result.ErrorCode,
                        ErrorMessage = result.ErrorMessage,
                        Profile = BuildPlanSummary(),
                    });
                }
                catch
                {
                    // History is non-critical; conversion status remains authoritative.
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

        StatusText.Text = _files.Any(item => item.StatusText == "Cancelled")
            ? AppLocalizer.Format($"Cancelled — {completed} converted, {failed} failed or cancelled.")
            : AppLocalizer.Format($"Done — {completed} converted, {failed} failed.");
        UpdateUi(updateStatus: false);
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not { IsCancellationRequested: false })
            return;
        _cts.Cancel();
        CancelButton.IsEnabled = false;
        StatusText.Text = AppLocalizer.Get("Cancelling...");
    }

    private void OpenOutput_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_outputDirectory) || !Directory.Exists(_outputDirectory))
            return;
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{_outputDirectory}\"")
            {
                UseShellExecute = true,
            });
        }
        catch
        {
            // User-invoked convenience action only.
        }
    }

    private AudioConversionOptions BuildOptions()
    {
        var format = SelectedTag(FormatCombo, "mp3");
        var managedVorbis = format == "vorbis" && VorbisManagedToggle.IsOn;
        return new AudioConversionOptions
        {
            Format = format,
            OutputDirectory = _outputDirectory ?? throw new InvalidOperationException("Choose an output folder."),
            UseVariableBitrate = VbrToggle.IsOn && !managedVorbis,
            VariableBitrateQuality = (int)VbrQualitySlider.Value,
            Bitrate = LossyFormats.Contains(format) && (!VbrToggle.IsOn || managedVorbis)
                ? SelectedTag(BitrateCombo, "192k")
                : null,
            SampleRate = ParseNullableInt(SelectedTag(SampleRateCombo, "")),
            Channels = ParseNullableInt(SelectedTag(ChannelsCombo, "")),
            OpusApplication = format == "opus" ? SelectedTag(OpusApplicationCombo, "audio") : null,
            OpusFrameDuration = format == "opus"
                ? ParseNullableDouble(SelectedTag(OpusFrameCombo, "20"))
                : null,
            OpusAmbisonics = format == "opus" ? SelectedTag(OpusAmbisonicsCombo, "off") : null,
            FdkCutoff = format == "fdk-aac" && !double.IsNaN(FdkCutoffBox.Value)
                ? (int)FdkCutoffBox.Value
                : null,
            FdkAfterburner = format == "fdk-aac" ? FdkAfterburnerToggle.IsOn : null,
            FdkProfile = format == "fdk-aac" ? SelectedTag(FdkProfileCombo, "aac_low") : null,
            VorbisManaged = managedVorbis,
        };
    }

    private void UpdateEncodingControls()
    {
        var format = SelectedTag(FormatCombo, "mp3");
        var lossy = LossyFormats.Contains(format);
        var supportsVariableBitrate = VariableBitrateFormats.Contains(format);
        var managedVorbis = format == "vorbis" && VorbisManagedToggle?.IsOn == true;

        QualityCard.Visibility = lossy ? Visibility.Visible : Visibility.Collapsed;
        VbrToggle.IsEnabled = supportsVariableBitrate && !managedVorbis;
        if (!supportsVariableBitrate)
            VbrToggle.IsOn = false;
        VbrPanel.Visibility = supportsVariableBitrate && VbrToggle.IsOn && !managedVorbis
            ? Visibility.Visible
            : Visibility.Collapsed;
        BitratePanel.Visibility = lossy && (!VbrToggle.IsOn || managedVorbis)
            ? Visibility.Visible
            : Visibility.Collapsed;

        OpusPanel.Visibility = format == "opus" ? Visibility.Visible : Visibility.Collapsed;
        FdkPanel.Visibility = format == "fdk-aac" ? Visibility.Visible : Visibility.Collapsed;
        VorbisPanel.Visibility = format == "vorbis" ? Visibility.Visible : Visibility.Collapsed;
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasFiles = _files.Count > 0;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        RunButton.IsEnabled = hasFiles && _cts is null && !string.IsNullOrWhiteSpace(_outputDirectory);
        ClearButton.IsEnabled = hasFiles && _cts is null;
        CancelButton.IsEnabled = _cts is not null;
        if (updateStatus && _cts is null)
            UpdateStatusText();
        UpdateWaveformPreview();
    }

    /// <summary>
    /// Renders a waveform PNG for the most-recently-added file into the preview
    /// card. Skips work when the target is unchanged, and degrades silently to a
    /// hidden card when FFmpeg/the mediathumb sidecar is unavailable — the queue
    /// never depends on the preview.
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
            // A preview is optional; hide the card rather than disturb the queue.
            DispatcherQueue.TryEnqueue(() => WaveformCard.Visibility = Visibility.Collapsed);
        }
    }

    private void UpdateStatusText()
    {
        if (StatusText is null)
            return;
        StatusText.Text = _files.Count == 0
            ? AppLocalizer.Get("Add audio files to start a conversion queue.")
            : AppLocalizer.Format($"Ready to convert {_files.Count} file(s) · {BuildPlanSummary()} · {_outputDirectory}");
    }

    private string BuildPlanSummary()
    {
        var format = SelectedTag(FormatCombo, "mp3");
        if (!LossyFormats.Contains(format))
            return $"{format.ToUpperInvariant()} lossless";
        if (format == "vorbis" && VorbisManagedToggle?.IsOn == true)
            return $"Ogg Vorbis managed {SelectedTag(BitrateCombo, "192k")}";
        return VbrToggle?.IsOn == true && VariableBitrateFormats.Contains(format)
            ? $"{format.ToUpperInvariant()} VBR Q{(int)(VbrQualitySlider?.Value ?? 2)}"
            : $"{format.ToUpperInvariant()} {SelectedTag(BitrateCombo, "192k")}";
    }

    private static string? FindNewestOutput(
        string sourcePath,
        string outputDirectory,
        string format,
        DateTime startedAt)
    {
        if (!Directory.Exists(outputDirectory) || !OutputExtensions.TryGetValue(format, out var extension))
            return null;
        var stem = Path.GetFileNameWithoutExtension(sourcePath);
        try
        {
            return Directory.EnumerateFiles(outputDirectory)
                .Where(path => string.Equals(Path.GetExtension(path), extension, StringComparison.OrdinalIgnoreCase))
                .Where(path => Path.GetFileNameWithoutExtension(path).StartsWith(stem, StringComparison.OrdinalIgnoreCase))
                .Select(path => new FileInfo(path))
                .Where(info => info.LastWriteTimeUtc >= startedAt.AddSeconds(-2))
                .OrderByDescending(info => info.LastWriteTimeUtc)
                .Select(info => info.FullName)
                .FirstOrDefault();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static long? TryFileSize(string? path)
    {
        try
        {
            return path is not null && File.Exists(path) ? new FileInfo(path).Length : null;
        }
        catch
        {
            return null;
        }
    }

    private static bool IsSupportedAudio(string path) =>
        AudioExtensions.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase);

    private static string SelectedTag(ComboBox comboBox, string fallback) =>
        comboBox.SelectedItem is ComboBoxItem { Tag: string tag } ? tag : fallback;

    private static int? ParseNullableInt(string value) =>
        int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed)
            ? parsed
            : null;

    private static double? ParseNullableDouble(string value) =>
        double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var parsed)
            ? parsed
            : null;

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1_073_741_824 => $"{bytes / 1_073_741_824.0:F1} GB",
        >= 1_048_576 => $"{bytes / 1_048_576.0:F1} MB",
        >= 1_024 => $"{bytes / 1_024.0:F1} KB",
        _ => $"{bytes} B",
    };
}

public sealed class AudioConversionFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Path { get; init; } = "";
    public string FileName { get; init; } = "";
    public string SourceSummary { get; init; } = "";
    public long SourceBytes { get; init; }

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

    private void SetProperty<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
            return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
