using System.Diagnostics;
using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class AiSubtitlePage : Page
{
    private static readonly string[] AcceptedExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v",
        ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ];

    private readonly ISidecarRunner _runner;
    private CancellationTokenSource? _cts;
    private string? _selectedPath;
    private string? _lastSubtitlePath;

    public AiSubtitlePage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop a video or audio file";
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        var items = await e.DataView.GetStorageItemsAsync();
        var first = items.OfType<StorageFile>().FirstOrDefault();
        if (first is not null) AcceptFile(first.Path);
    }

    private async void Browse_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var ext in AcceptedExtensions) picker.FileTypeFilter.Add(ext);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var file = await picker.PickSingleFileAsync();
        if (file is not null) AcceptFile(file.Path);
    }

    private void AcceptFile(string path)
    {
        if (!AcceptedExtensions.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase))
        {
            StatusText.Text = $"Unsupported extension {Path.GetExtension(path)}";
            return;
        }
        _selectedPath = path;
        DropZoneLabel.Text = Path.GetFileName(path);
        StatusText.Text = "Ready.";
        UpdateRunEnabled();
    }

    private void Settings_Changed(object sender, SelectionChangedEventArgs e) => UpdateRunEnabled();

    private void Settings_Bool_Changed(object sender, RoutedEventArgs e) => UpdateRunEnabled();

    private void Settings_Number_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args) => UpdateRunEnabled();

    private void UpdateRunEnabled()
    {
        if (RunButton is null) return;
        RunButton.IsEnabled = _selectedPath is not null && _cts is null;
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedPath is null || _cts is not null) return;

        var backend = SelectedTag(BackendCombo) ?? "whisper-stt";
        var model = SelectedTag(ModelCombo) ?? "base";
        var language = SelectedTag(LanguageCombo) ?? "auto";
        var format = SelectedTag(FormatCombo) ?? "srt";
        var burnIn = BurnInCheck.IsChecked == true;
        var useVad = VadCheck.IsChecked == true;
        var batchSize = SafeBatchSize(BatchSizeBox.Value);

        // Subtitle output sits next to the source. Burn-in produces a second
        // file <name>_subtitled<ext>.
        var dir = Path.GetDirectoryName(_selectedPath) ?? Environment.CurrentDirectory;
        var stem = Path.GetFileNameWithoutExtension(_selectedPath);
        var subtitlePath = EnsureUniquePath(Path.Combine(dir, $"{stem}.{format}"));

        _cts = new CancellationTokenSource();
        UpdateRunEnabled();
        CancelButton.IsEnabled = true;
        ProgressBar.Visibility = Visibility.Visible;
        ProgressBar.Value = 0;
        OpenOutputButton.IsEnabled = false;
        ProgressLabel.Text = $"Transcribing with {backend}, {model} model...";
        StatusText.Text = "Transcribing...";

        // 1. Transcribe → subtitle file.
        List<string> sttArgs;
        if (backend == "whisper-cpp")
        {
            sttArgs =
            [
                "transcribe",
                "--input",  _selectedPath,
                "--output", subtitlePath,
                "--model",  model,
                "--language", language,
            ];
            if (useVad) sttArgs.Add("--vad");
        }
        else
        {
            sttArgs =
            [
                "--input",  _selectedPath,
                "--output", subtitlePath,
                "--model",  model,
                "--language", language,
                "--format", format,
            ];
            if (useVad) sttArgs.Add("--vad");
            sttArgs.Add("--batch-size");
            sttArgs.Add(batchSize.ToString(CultureInfo.InvariantCulture));
        }

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            // Reserve the last 15% for an optional burn-in pass.
            ProgressBar.Value = burnIn ? p.Percent * 0.85 : p.Percent;
            ProgressLabel.Text = string.IsNullOrEmpty(p.Stage)
                ? $"Transcribing — {p.Percent:F0}%"
                : $"{p.Percent:F0}% — {p.Stage}";
        }));
        var log = new Progress<SidecarLog>(_ => { });

        SidecarResult sttResult;
        try
        {
            sttResult = await _runner.RunAsync(backend, sttArgs, progress, log, _cts.Token);
        }
        catch (OperationCanceledException)
        {
            sttResult = new SidecarResult(false, null, null, "cancelled", "Cancelled.", 130);
        }

        if (!sttResult.Success)
        {
            StatusText.Text = sttResult.ErrorMessage ?? $"Transcription failed ({sttResult.ErrorCode}).";
            FinalCleanup();
            return;
        }

        _lastSubtitlePath = sttResult.OutputPath ?? subtitlePath;

        // 2. Optional burn-in via FFmpeg `subtitles` filter.
        if (burnIn && IsVideoFile(_selectedPath))
        {
            ProgressLabel.Text = "Burning subtitles into video...";
            var burnedPath = EnsureUniquePath(
                Path.Combine(dir, $"{stem}_subtitled{Path.GetExtension(_selectedPath)}"));
            var success = await BurnInAsync(_selectedPath, _lastSubtitlePath, burnedPath, _cts.Token);
            if (success)
            {
                _lastSubtitlePath = burnedPath;
                StatusText.Text = $"Done — {Path.GetFileName(burnedPath)} (subtitle file kept alongside).";
            }
            else
            {
                StatusText.Text = $"Subtitles generated but burn-in failed. SRT/VTT is at {Path.GetFileName(_lastSubtitlePath)}.";
            }
        }
        else
        {
            StatusText.Text = $"Done — {Path.GetFileName(_lastSubtitlePath)}";
        }

        ProgressBar.Value = 100;
        OpenOutputButton.IsEnabled = true;
        FinalCleanup();
    }

    private async Task<bool> BurnInAsync(string videoPath, string subtitlePath, string outputPath, CancellationToken ct)
    {
        // Locate ffmpeg the same way the sidecars do.
        var ffmpeg = FindFFmpeg();
        if (ffmpeg is null) return false;

        // FFmpeg subtitles filter needs forward slashes + colon escaping for Windows paths.
        var ffPath = subtitlePath.Replace("\\", "/").Replace(":", "\\:");
        var psi = new ProcessStartInfo
        {
            FileName = ffmpeg,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardError = true,
        };
        foreach (var arg in new[]
        {
            "-y", "-i", videoPath,
            "-vf", $"subtitles='{ffPath}'",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "copy",
            outputPath,
        }) psi.ArgumentList.Add(arg);

        try
        {
            using var proc = Process.Start(psi);
            if (proc is null) return false;
            await proc.WaitForExitAsync(ct);
            return proc.ExitCode == 0 && File.Exists(outputPath);
        }
        catch
        {
            return false;
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

    private void OpenOutput_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(_lastSubtitlePath) || !File.Exists(_lastSubtitlePath)) return;
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{_lastSubtitlePath}\"")
            {
                UseShellExecute = true,
            });
        }
        catch { }
    }

    private void FinalCleanup()
    {
        _cts?.Dispose();
        _cts = null;
        CancelButton.IsEnabled = false;
        ProgressBar.Visibility = Visibility.Collapsed;
        UpdateRunEnabled();
    }

    private static string? SelectedTag(ComboBox combo)
    {
        if (combo.SelectedItem is ComboBoxItem item && item.Tag is string tag) return tag;
        return null;
    }

    private static int SafeBatchSize(double value)
    {
        if (double.IsNaN(value)) return 8;
        return Math.Clamp((int)Math.Round(value), 1, 32);
    }

    private static bool IsVideoFile(string path)
    {
        var ext = Path.GetExtension(path).ToLowerInvariant();
        return ext is ".mp4" or ".mkv" or ".mov" or ".avi" or ".webm" or ".flv"
                  or ".wmv" or ".ts" or ".mts" or ".m4v";
    }

    private static string? FindFFmpeg()
    {
        var fromEnv = Environment.GetEnvironmentVariable("FFMPEG_PATH");
        if (!string.IsNullOrEmpty(fromEnv) && File.Exists(fromEnv)) return fromEnv;

        var pathDirs = (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator);
        foreach (var d in pathDirs)
        {
            var candidate = Path.Combine(d, "ffmpeg.exe");
            if (File.Exists(candidate)) return candidate;
        }

        // Common shared locations
        var localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        foreach (var c in new[]
        {
            Path.Combine(AppContext.BaseDirectory, "tools", "_bin", "ffmpeg.exe"),
            Path.Combine(localApp, "UniversalConverterX", "tools", "_bin", "ffmpeg.exe"),
        })
        {
            if (File.Exists(c)) return c;
        }
        return null;
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
}
