using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class FrameSnapshotPage : Page
{
    private static readonly HashSet<string> VideoExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg",
        ".3gp", ".3g2", ".mts", ".m2ts", ".ts", ".vob", ".ogv", ".mxf", ".asf", ".divx"
    };

    private readonly ObservableCollection<FrameSnapshotJobItem> _queue = [];
    private readonly ObservableCollection<FrameSnapshotFinishedItem> _finished = [];
    private readonly string _defaultOutputDirectory;
    private readonly string? _ffmpegPath;
    private string? _outputDirectory;
    private CancellationTokenSource? _cts;

    public FrameSnapshotPage()
    {
        InitializeComponent();

        _defaultOutputDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyPictures),
            "UniversalConverterX",
            "Snapshots");
        _outputDirectory = _defaultOutputDirectory;
        // Locked-down profiles can have MyPictures redirected to read-only
        // network shares; never crash the page just because we couldn't
        // pre-create the default folder.
        try { Directory.CreateDirectory(_defaultOutputDirectory); }
        catch
        {
            _defaultOutputDirectory = Path.Combine(Path.GetTempPath(), "UniversalConverterX-Snapshots");
            _outputDirectory = _defaultOutputDirectory;
            try { Directory.CreateDirectory(_defaultOutputDirectory); } catch { }
        }

        _ffmpegPath = FindExecutable("ffmpeg.exe");
        QueueList.ItemsSource = _queue;
        FinishedList.ItemsSource = _finished;
        OutputDirectoryBox.Text = _outputDirectory;
        FfmpegStatusText.Text = _ffmpegPath is null
            ? "FFmpeg was not found. Add ffmpeg.exe to PATH or UCX tools/bin to enable snapshot extraction."
            : $"Ready: {_ffmpegPath}";

        UpdatePlanSummary();
        UpdateUi();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop videos for frame snapshots";
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
        if (_queue.Count == 0 && QueuePivot.SelectedIndex == 0)
            BrowseFiles();
    }

    private void BrowseFiles_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        picker.FileTypeFilter.Add("*");

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
            SuggestedStartLocation = PickerLocationId.PicturesLibrary,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder is null)
            return;

        _outputDirectory = folder.Path;
        try { Directory.CreateDirectory(_outputDirectory); }
        catch (Exception ex)
        {
            OutputDirectoryBox.Text = $"(unavailable: {ex.Message})";
            return;
        }
        OutputDirectoryBox.Text = _outputDirectory;
        UpdateUi();
    }

    private void SameAsSource_Click(object sender, RoutedEventArgs e)
    {
        _outputDirectory = null;
        OutputDirectoryBox.Text = "Same folder as each source";
        UpdateUi();
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
            return;

        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path).Where(IsSupportedVideo).Take(500))
        {
            if (AddFile(file, updateUi: false))
                added++;
        }

        StatusText.Text = added == 0
            ? "No supported video files were added from that folder."
            : $"Added {added} videos from {path}.";
        UpdateUi(updateStatus: false);
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (!File.Exists(path) || _queue.Any(item => item.Path.Equals(path, StringComparison.OrdinalIgnoreCase)))
            return false;

        var info = new FileInfo(path);
        var isSupported = IsSupportedVideo(path);
        _queue.Add(new FrameSnapshotJobItem
        {
            Path = path,
            FileName = info.Name,
            Details = $"{FormatSize(info.Length)} - {Path.GetExtension(path).TrimStart('.').ToUpperInvariant()} video",
            PlanSummary = isSupported ? CurrentPlanLabel() : "May fail",
            StatusText = isSupported ? "Queued" : "Unknown video",
            Progress = 0,
        });

        if (updateUi)
            UpdateUi();

        return true;
    }

    private void RemoveQueued_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
            return;

        if (sender is Button button && button.Tag is FrameSnapshotJobItem item)
        {
            _queue.Remove(item);
            UpdateUi();
        }
    }

    private async void ClearQueue_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
            return;

        if (_queue.Count == 0)
            return;

        if (!await PageDialogService.ConfirmClearAsync(
                this,
                "Clear snapshot queue?",
                $"Remove {_queue.Count} queued video(s)? Finished snapshot exports stay available."))
        {
            return;
        }

        _queue.Clear();
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (PlanSummaryText is null) return;
        UpdateUi();
    }

    private void Option_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (PlanSummaryText is null) return;
        UpdatePlanSummary();
        foreach (var item in _queue.Where(item => !item.IsComplete))
            item.PlanSummary = CurrentPlanLabel();
        UpdateUi();
    }

    private void Option_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (PlanSummaryText is null) return;
        UpdatePlanSummary();
        foreach (var item in _queue.Where(item => !item.IsComplete))
            item.PlanSummary = CurrentPlanLabel();
        UpdateUi();
    }

    private async void Extract_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null || _queue.Count == 0 || _ffmpegPath is null)
            return;

        var plan = ReadPlan();
        if (plan is null)
        {
            StatusText.Text = "Use numeric start, interval, and frame count values before extracting.";
            return;
        }

        if (_outputDirectory is not null)
        {
            try { Directory.CreateDirectory(_outputDirectory); }
            catch (Exception ex)
            {
                StatusText.Text = $"Output folder unavailable: {ex.Message}";
                return;
            }
        }

        _cts = new CancellationTokenSource();
        ExtractButton.IsEnabled = false;
        ClearQueueButton.IsEnabled = false;
        CancelButton.IsEnabled = true;

        var pending = _queue.Where(item => !item.IsComplete).ToList();
        var completed = 0;
        var failed = 0;

        try
        {
            foreach (var job in pending)
            {
                if (_cts.IsCancellationRequested)
                    break;

                // ROADMAP Item 60 — keep the active job visible in long queues.
                try { QueueList.ScrollIntoView(job); } catch { /* virtualization race; ignore */ }

                StatusText.Text = $"Extracting snapshots from {job.FileName}...";
                var result = await ExtractJobAsync(job, plan.Value, _cts.Token);

                if (result.Success)
                {
                    completed++;
                    job.Progress = 100;
                    job.StatusText = "Done";
                }
                else
                {
                    failed++;
                    job.StatusText = result.Cancelled ? "Cancelled" : "Failed";
                }

                job.IsComplete = true;
                AddFinishedItem(job, result);

                if (result.Cancelled)
                    break;
            }
        }
        finally
        {
            _cts.Dispose();
            _cts = null;
        }

        QueuePivot.SelectedIndex = _finished.Count > 0 ? 1 : 0;
        StatusText.Text = $"{completed} videos completed, {failed} failed.";
        UpdateUi(updateStatus: false);
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
            _cts.Cancel();
    }

    private void OpenOutputFolder_Click(object sender, RoutedEventArgs e)
    {
        var folder = _outputDirectory
            ?? Path.GetDirectoryName(_queue.FirstOrDefault()?.Path ?? "")
            ?? _defaultOutputDirectory;
        OpenContainingFolder(folder);
    }

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string path)
            OpenContainingFolder(path);
    }

    private async Task<SnapshotJobResult> ExtractJobAsync(
        FrameSnapshotJobItem job,
        SnapshotPlan plan,
        CancellationToken cancellationToken)
    {
        var outputRoot = _outputDirectory ?? Path.GetDirectoryName(job.Path) ?? _defaultOutputDirectory;
        try { Directory.CreateDirectory(outputRoot); }
        catch (Exception ex)
        {
            return new SnapshotJobResult(
                Success: false,
                Cancelled: false,
                OutputPath: outputRoot,
                FirstFilePath: "",
                ExportedCount: 0,
                ErrorMessage: $"Output folder unavailable: {ex.Message}");
        }

        var exported = 0;
        var firstOutput = "";
        var error = "";

        for (var index = 0; index < plan.Count; index++)
        {
            if (cancellationToken.IsCancellationRequested)
            {
                return new SnapshotJobResult(
                    Success: false,
                    Cancelled: true,
                    OutputPath: outputRoot,
                    FirstFilePath: firstOutput,
                    ExportedCount: exported,
                    ErrorMessage: "Cancelled by user.");
            }

            var second = plan.StartSeconds + (index * plan.IntervalSeconds);
            var outputPath = BuildOutputPath(job.Path, outputRoot, second, index + 1, plan.Format);
            var (success, message) = await RunFfmpegSnapshotAsync(job.Path, outputPath, second, plan, cancellationToken);

            if (!success)
            {
                error = message;
                break;
            }

            exported++;
            firstOutput = string.IsNullOrWhiteSpace(firstOutput) ? outputPath : firstOutput;
            job.Progress = exported * 100.0 / plan.Count;
            job.StatusText = $"{exported}/{plan.Count} exported";
        }

        return new SnapshotJobResult(
            Success: exported == plan.Count,
            Cancelled: error.Equals("Cancelled by user.", StringComparison.OrdinalIgnoreCase),
            OutputPath: outputRoot,
            FirstFilePath: firstOutput,
            ExportedCount: exported,
            ErrorMessage: exported == plan.Count ? null : error);
    }

    private async Task<(bool Success, string Message)> RunFfmpegSnapshotAsync(
        string inputPath,
        string outputPath,
        double timestampSeconds,
        SnapshotPlan plan,
        CancellationToken cancellationToken)
    {
        var psi = new ProcessStartInfo
        {
            FileName = _ffmpegPath!,
            UseShellExecute = false,
            RedirectStandardError = true,
            RedirectStandardOutput = true,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };

        psi.ArgumentList.Add("-y");
        psi.ArgumentList.Add("-hide_banner");
        psi.ArgumentList.Add("-loglevel");
        psi.ArgumentList.Add("error");
        psi.ArgumentList.Add("-ss");
        psi.ArgumentList.Add(FormatTimestamp(timestampSeconds));
        psi.ArgumentList.Add("-i");
        psi.ArgumentList.Add(inputPath);
        psi.ArgumentList.Add("-frames:v");
        psi.ArgumentList.Add("1");

        if (plan.Format is "jpg" or "webp")
        {
            psi.ArgumentList.Add("-q:v");
            psi.ArgumentList.Add(plan.Quality.ToString());
        }

        psi.ArgumentList.Add(outputPath);

        using var process = new Process { StartInfo = psi };
        try
        {
            process.Start();
            var stderrTask = process.StandardError.ReadToEndAsync(cancellationToken);
            var stdoutTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
            await process.WaitForExitAsync(cancellationToken);
            var stderr = await stderrTask;
            _ = await stdoutTask;

            if (process.ExitCode == 0 && File.Exists(outputPath))
                return (true, "");

            return (false, string.IsNullOrWhiteSpace(stderr)
                ? $"FFmpeg exited with code {process.ExitCode}."
                : stderr.Trim());
        }
        catch (OperationCanceledException)
        {
            try
            {
                if (!process.HasExited)
                    process.Kill(entireProcessTree: true);
            }
            catch
            {
                // Keep cancellation best-effort.
            }

            return (false, "Cancelled by user.");
        }
    }

    private void AddFinishedItem(FrameSnapshotJobItem job, SnapshotJobResult result)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush = (Brush)Application.Current.Resources["AccentRedBrush"];
        var details = result.Success
            ? $"{result.ExportedCount} snapshots exported"
            : result.ErrorMessage ?? "Snapshot extraction failed";

        _finished.Insert(0, new FrameSnapshotFinishedItem
        {
            Title = result.Success ? job.FileName : $"{job.FileName} failed",
            Details = details,
            OutputPath = result.OutputPath,
            Success = result.Success,
            Glyph = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasQueued = _queue.Count > 0;
        var hasFinished = _finished.Count > 0;
        var hasFfmpeg = _ffmpegPath is not null;
        var isBusy = _cts is not null;
        var pending = _queue.Count(item => !item.IsComplete);

        QueueEmpty.Visibility = hasQueued ? Visibility.Collapsed : Visibility.Visible;
        QueueList.Visibility = hasQueued ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;

        QueueSummaryText.Text = $"{pending} queued / {_finished.Count} finished";
        ExtractButton.IsEnabled = hasQueued && hasFfmpeg && !isBusy;
        ClearQueueButton.IsEnabled = hasQueued && !isBusy;
        CancelButton.IsEnabled = isBusy;
        OpenOutputButton.IsEnabled = true;

        if (updateStatus && !isBusy)
        {
            StatusText.Text = !hasFfmpeg
                ? "Install FFmpeg or add ffmpeg.exe to PATH to enable extraction."
                : pending == 0
                    ? "Add videos to export frame snapshots."
                    : $"Ready to export {pending} videos with {CurrentPlanLabel()}.";
        }
    }

    private void UpdatePlanSummary()
    {
        var plan = ReadPlan();
        PlanSummaryText.Text = plan is null
            ? "Plan is incomplete. Use numeric start, interval, and frame count values."
            : $"{plan.Value.Count} frame(s) per video starting at {plan.Value.StartSeconds:0.###}s, every {plan.Value.IntervalSeconds:0.###}s, exported as {plan.Value.Format.ToUpperInvariant()}.";
    }

    private SnapshotPlan? ReadPlan()
    {
        if (!TryReadDouble(StartSecondBox.Text, 0, 86400, out var start) ||
            !TryReadDouble(IntervalSecondBox.Text, 0.1, 86400, out var interval) ||
            !TryReadInt(CountBox.Text, 1, 500, out var count))
        {
            return null;
        }

        return new SnapshotPlan(
            Format: SelectedTag(FormatCombo, "png"),
            StartSeconds: start,
            IntervalSeconds: interval,
            Count: count,
            Quality: SelectedIntTag(QualityCombo, 4));
    }

    private string CurrentPlanLabel()
    {
        var plan = ReadPlan();
        return plan is null
            ? "Needs setup"
            : $"{plan.Value.Count} x {plan.Value.Format.ToUpperInvariant()}";
    }

    private static bool TryReadDouble(string text, double min, double max, out double value)
    {
        if (double.TryParse(text.Trim(), out value))
        {
            value = Math.Clamp(value, min, max);
            return true;
        }

        value = 0;
        return false;
    }

    private static bool TryReadInt(string text, int min, int max, out int value)
    {
        if (int.TryParse(text.Trim(), out value))
        {
            value = Math.Clamp(value, min, max);
            return true;
        }

        value = 0;
        return false;
    }

    private static string BuildOutputPath(string inputPath, string outputRoot, double second, int index, string format)
    {
        var source = Path.GetFileNameWithoutExtension(inputPath);
        var safeTimestamp = FormatTimestamp(second).Replace(':', '-').Replace('.', '-');
        var fileName = $"{SanitizeFileName(source)}_frame-{index:000}_{safeTimestamp}.{format}";
        return EnsureUniquePath(Path.Combine(outputRoot, fileName));
    }

    private static string FormatTimestamp(double totalSeconds)
    {
        var span = TimeSpan.FromSeconds(Math.Max(0, totalSeconds));
        return $"{(int)span.TotalHours:00}:{span.Minutes:00}:{span.Seconds:00}.{span.Milliseconds:000}";
    }

    private static string SelectedTag(ComboBox combo, string fallback)
    {
        return combo.SelectedItem is ComboBoxItem item && item.Tag is not null
            ? item.Tag.ToString() ?? fallback
            : fallback;
    }

    private static int SelectedIntTag(ComboBox combo, int fallback)
    {
        return combo.SelectedItem is ComboBoxItem item &&
            int.TryParse(item.Tag?.ToString(), out var value)
            ? value
            : fallback;
    }

    private static bool IsSupportedVideo(string path) => VideoExtensions.Contains(Path.GetExtension(path));

    private static string SanitizeFileName(string fileName)
    {
        foreach (var c in Path.GetInvalidFileNameChars())
            fileName = fileName.Replace(c, '_');
        return string.IsNullOrWhiteSpace(fileName) ? "snapshot" : fileName;
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
            Process.Start(new ProcessStartInfo("explorer.exe", folder)
            {
                UseShellExecute = true,
            });
        }
        catch
        {
            // Explorer launch is best-effort only.
        }
    }

    private static string FormatSize(long bytes)
    {
        string[] suffixes = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        double size = bytes;

        while (size >= 1024 && i < suffixes.Length - 1)
        {
            size /= 1024;
            i++;
        }

        return $"{size:F1} {suffixes[i]}";
    }

    private static string? FindExecutable(string executableName)
    {
        var baseDirectory = AppContext.BaseDirectory;
        var candidates = new List<string>
        {
            Path.Combine(baseDirectory, "tools", "bin", executableName),
            Path.Combine(baseDirectory, "tools", "_bin", executableName),
        };

        var dir = new DirectoryInfo(baseDirectory);
        while (dir is not null)
        {
            candidates.Add(Path.Combine(dir.FullName, "tools", "bin", executableName));
            candidates.Add(Path.Combine(dir.FullName, "tools", "_bin", executableName));
            dir = dir.Parent;
        }

        var path = Environment.GetEnvironmentVariable("PATH");
        if (!string.IsNullOrWhiteSpace(path))
        {
            candidates.AddRange(path
                .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries)
                .Select(entry => Path.Combine(entry.Trim(), executableName)));
        }

        return candidates.FirstOrDefault(File.Exists);
    }

    private readonly record struct SnapshotPlan(
        string Format,
        double StartSeconds,
        double IntervalSeconds,
        int Count,
        int Quality);

    private sealed record SnapshotJobResult(
        bool Success,
        bool Cancelled,
        string OutputPath,
        string FirstFilePath,
        int ExportedCount,
        string? ErrorMessage);
}

public sealed class FrameSnapshotJobItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _planSummary = "";
    private bool _isComplete;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";

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

    public string PlanSummary
    {
        get => _planSummary;
        set => SetProperty(ref _planSummary, value);
    }

    public bool IsComplete
    {
        get => _isComplete;
        set => SetProperty(ref _isComplete, value);
    }

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value))
            return;

        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}

public sealed class FrameSnapshotFinishedItem
{
    public string Title { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush AccentBrush { get; set; } = null!;
    public bool CanOpenFolder => Success && !string.IsNullOrWhiteSpace(OutputPath);
}
