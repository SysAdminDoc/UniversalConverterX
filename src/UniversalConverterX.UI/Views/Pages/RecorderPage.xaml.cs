using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class RecorderPage : Page
{
    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<RecordingJobItem> _queue = [];
    private readonly ObservableCollection<RecordingFinishedItem> _finished = [];
    private readonly string _defaultOutputDirectory;
    private string _outputDirectory;
    private CancellationTokenSource? _cts;
    private bool _useWebcam;
    private string? _selectedWebcam;
    private string? _selectedAudio;
    private string? _selectedSystemAudio;
    private string? _selectedRegion;

    public RecorderPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _defaultOutputDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.MyVideos),
            "UniversalConverterX",
            "Recordings");
        _outputDirectory = _defaultOutputDirectory;
        try { Directory.CreateDirectory(_outputDirectory); }
        catch
        {
            _defaultOutputDirectory = Path.Combine(Path.GetTempPath(), "UniversalConverterX-Recordings");
            _outputDirectory = _defaultOutputDirectory;
            try { Directory.CreateDirectory(_outputDirectory); } catch { }
        }

        QueueList.ItemsSource = _queue;
        FinishedList.ItemsSource = _finished;
        OutputDirectoryBox.Text = _outputDirectory;
        UpdateUi();
        _ = LoadDevicesAsync();
    }

    private async void BrowseOutputFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
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
            // Folder picker can return a path the app no longer has rights to
            // (network share dropped, drive ejected). Surface the error and
            // fall back to the prior directory so the next Start succeeds.
            OutputDirectoryBox.Text = $"(unavailable: {ex.Message})";
            return;
        }
        OutputDirectoryBox.Text = _outputDirectory;
        UpdateUi();
    }

    private void SourceToggle_Click(object sender, RoutedEventArgs e)
    {
        if (sender is ToggleButton tb)
        {
            _useWebcam = tb == WebcamToggle;
            ScreenToggle.IsChecked = !_useWebcam;
            WebcamToggle.IsChecked = _useWebcam;
            WebcamDevicePanel.Visibility = _useWebcam ? Visibility.Visible : Visibility.Collapsed;
            UpdateUi();
        }
    }

    private async void RefreshDevices_Click(object sender, RoutedEventArgs e)
    {
        RefreshDevicesButton.IsEnabled = false;
        await LoadDevicesAsync();
        RefreshDevicesButton.IsEnabled = true;
    }

    private async Task LoadDevicesAsync()
    {
        var videoDevices = new List<string>();
        var audioDevices = new List<string>();

        var progress = new Progress<SidecarProgress>(_ => { });
        var logHandler = new Progress<SidecarLog>(_ => { });
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));

        try
        {
            await _runner.RunAsync(
                "recordcast",
                ["list-devices"],
                progress,
                logHandler,
                cts.Token,
                onRawEvent: (evName, data) =>
                {
                    if (evName != "device") return;
                    var type = data.TryGetProperty("type", out var t) ? t.GetString() ?? "" : "";
                    var name = data.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "";
                    if (type == "video" && name.Length > 0)
                        videoDevices.Add(name);
                    else if (type == "audio" && name.Length > 0)
                        audioDevices.Add(name);
                });
        }
        catch (OperationCanceledException)
        {
            // Timeout — proceed with empty lists
        }
        catch (Exception)
        {
            // Device enumeration is best-effort
        }

        DispatcherQueue.TryEnqueue(() => PopulateDeviceComboBoxes(videoDevices, audioDevices));
    }

    private void PopulateDeviceComboBoxes(List<string> videoDevices, List<string> audioDevices)
    {
        WebcamDeviceCombo.Items.Clear();
        foreach (var dev in videoDevices)
            WebcamDeviceCombo.Items.Add(new ComboBoxItem { Content = dev, Tag = dev });
        if (videoDevices.Count > 0)
            WebcamDeviceCombo.SelectedIndex = 0;

        AudioDeviceCombo.Items.Clear();
        AudioDeviceCombo.Items.Add(new ComboBoxItem { Content = "None (no microphone)", Tag = "" });
        foreach (var dev in audioDevices)
            AudioDeviceCombo.Items.Add(new ComboBoxItem { Content = dev, Tag = dev });
        AudioDeviceCombo.SelectedIndex = 0;

        // System-audio combo: pre-fill any audio devices that look like loopback
        // sources (Stereo Mix / What U Hear / virtual-audio-capturer / Wave Out).
        SystemAudioCombo.Items.Clear();
        SystemAudioCombo.Items.Add(new ComboBoxItem { Content = "Auto (Stereo Mix / virtual)", Tag = "" });
        foreach (var dev in audioDevices)
        {
            var lower = dev.ToLowerInvariant();
            if (lower.Contains("stereo mix") || lower.Contains("what u hear") ||
                lower.Contains("virtual-audio") || lower.Contains("wave out") ||
                lower.Contains("loopback"))
            {
                SystemAudioCombo.Items.Add(new ComboBoxItem { Content = dev, Tag = dev });
            }
        }
        SystemAudioCombo.SelectedIndex = 0;

        _selectedWebcam = videoDevices.Count > 0 ? videoDevices[0] : null;
        _selectedAudio = null;
    }

    private void AddSession_Click(object sender, RoutedEventArgs e)
    {
        _queue.Add(CreateJob());
        QueuePivot.SelectedIndex = 0;
        UpdateUi();
    }

    private void RemoveQueued_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
            return;

        if (sender is Button button && button.Tag is RecordingJobItem item)
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
                "Clear recording queue?",
                $"Remove {_queue.Count} queued recording session(s)? Finished recordings stay available."))
        {
            return;
        }

        _queue.Clear();
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (QueueSummaryText is null) return;
        UpdateUi();
    }

    private void Option_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (QueueSummaryText is null) return;

        // Track selected webcam/audio device names
        if (ReferenceEquals(sender, WebcamDeviceCombo) && WebcamDeviceCombo.SelectedItem is ComboBoxItem wci)
            _selectedWebcam = wci.Tag as string;
        if (ReferenceEquals(sender, AudioDeviceCombo) && AudioDeviceCombo.SelectedItem is ComboBoxItem aci)
            _selectedAudio = (aci.Tag as string)?.Length > 0 ? aci.Tag as string : null;
        if (ReferenceEquals(sender, SystemAudioCombo) && SystemAudioCombo.SelectedItem is ComboBoxItem sci)
            _selectedSystemAudio = sci.Tag as string ?? "";

        if (ReferenceEquals(sender, RegionCombo) && RegionCombo.SelectedItem is ComboBoxItem rci)
        {
            var tag = rci.Tag as string ?? "";
            if (CustomRegionGrid is not null)
                CustomRegionGrid.Visibility = tag == "custom" ? Visibility.Visible : Visibility.Collapsed;
            _selectedRegion = tag == "custom" ? BuildCustomRegion() : (string.IsNullOrEmpty(tag) ? null : tag);
        }

        UpdateUi();
    }

    private void Option_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (RegionCombo?.SelectedItem is ComboBoxItem rci && (rci.Tag as string) == "custom")
            _selectedRegion = BuildCustomRegion();
    }

    private void Option_BoolChanged(object sender, RoutedEventArgs e)
    {
        if (SystemAudioCombo is null) return;
        var enabled = SystemAudioCheck.IsChecked == true;
        SystemAudioCombo.Visibility = enabled ? Visibility.Visible : Visibility.Collapsed;
        if (!enabled) _selectedSystemAudio = null;
        else if (string.IsNullOrEmpty(_selectedSystemAudio))
            _selectedSystemAudio = "";  // sentinel for "use default loopback"
    }

    private string? BuildCustomRegion()
    {
        if (RegionXBox is null) return null;
        if (!int.TryParse(RegionXBox.Text, out var x)) x = 0;
        if (!int.TryParse(RegionYBox.Text, out var y)) y = 0;
        if (!int.TryParse(RegionWBox.Text, out var w) || w <= 0) return null;
        if (!int.TryParse(RegionHBox.Text, out var h) || h <= 0) return null;
        return $"{x},{y},{w},{h}";
    }

    private async void Record_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
            return;

        if (_queue.Count == 0)
            _queue.Add(CreateJob());

        var pending = _queue.Where(j => !j.IsComplete).ToList();
        if (pending.Count == 0)
            return;

        try { Directory.CreateDirectory(_outputDirectory); }
        catch (Exception ex)
        {
            StatusText.Text = $"Output folder unavailable: {ex.Message}";
            return;
        }
        _cts = new CancellationTokenSource();
        RecordButton.IsEnabled = false;
        ClearQueueButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        StatusText.Text = $"Recording {pending.Count} queued sessions...";

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

                var outputPath = BuildOutputPath(job);
                var args = BuildArgs(job, outputPath);

                job.Progress = 0;
                job.StatusText = "Starting";
                StatusText.Text = $"Recording {job.Title}";

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    job.Progress = p.Percent;
                    job.StatusText = $"{p.Percent:F1}% - {p.Stage}";
                }));
                var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
                {
                    job.StatusText = l.Level == "error" ? "Recorder error" : job.StatusText;
                }));

                SidecarResult result;
                try
                {
                    result = await _runner.RunAsync("recordcast", args, progress, log, _cts.Token);
                }
                catch (OperationCanceledException)
                {
                    result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user.", 130);
                }

                if (result.Success)
                {
                    completed++;
                    job.IsComplete = true;
                    job.Progress = 100;
                    job.StatusText = "Done";
                }
                else
                {
                    failed++;
                    job.IsComplete = true;
                    job.StatusText = result.ErrorCode == "cancelled" ? "Cancelled" : "Failed";
                }

                AddFinishedItem(job, result);

                if (result.ErrorCode == "cancelled")
                    break;
            }
        }
        finally
        {
            _cts.Dispose();
            _cts = null;
        }

        QueuePivot.SelectedIndex = _finished.Count > 0 ? 1 : 0;
        StatusText.Text = $"{completed} recordings completed, {failed} failed.";
        UpdateUi(updateStatus: false);
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
            _cts.Cancel();
    }

    private void OpenOutputFolder_Click(object sender, RoutedEventArgs e) => OpenContainingFolder(_outputDirectory);

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string path)
            OpenContainingFolder(path);
    }

    private RecordingJobItem CreateJob()
    {
        var duration = SelectedInt(DurationCombo, 30);
        var frameRate = SelectedInt(FrameRateCombo, 30);
        var crf = SelectedInt(QualityCombo, 20);
        var now = DateTime.Now;
        var source = _useWebcam ? "webcam" : "screen";
        var audioLabel = _selectedAudio is not null ? " + mic" : "";
        var title = $"{(char.ToUpperInvariant(source[0]) + source[1..])}{audioLabel} recording {now:HH-mm-ss}";

        return new RecordingJobItem
        {
            Title = title,
            StartedAt = now,
            DurationSeconds = duration,
            FrameRate = frameRate,
            Crf = crf,
            Source = source,
            WebcamDevice = _useWebcam ? _selectedWebcam : null,
            AudioDevice = _selectedAudio,
            EncoderPreset = "veryfast",
            PresetSummary = $"{FormatDuration(duration)} - {frameRate} fps",
            Details = $"{(char.ToUpperInvariant(source[0]) + source[1..])} capture, MP4 H.264, CRF {crf}{audioLabel}",
            StatusText = "Queued",
        };
    }

    private List<string> BuildArgs(RecordingJobItem job, string outputPath)
    {
        var args = new List<string>
        {
            "record",
            "--output", outputPath,
            "--duration", job.DurationSeconds.ToString(),
            "--framerate", job.FrameRate.ToString(),
            "--crf", job.Crf.ToString(),
            "--preset", job.EncoderPreset,
            "--source", job.Source,
        };

        if (job.Source == "webcam" && job.WebcamDevice is not null)
        {
            args.Add("--webcam");
            args.Add(job.WebcamDevice);
        }

        if (job.AudioDevice is not null)
        {
            args.Add("--audio");
            args.Add(job.AudioDevice);
        }

        if (SystemAudioCheck?.IsChecked == true)
        {
            // Empty string = sentinel for the sidecar's "auto-default loopback".
            args.Add("--system-audio");
            args.Add(_selectedSystemAudio ?? "");
        }

        if (!string.IsNullOrEmpty(_selectedRegion) && job.Source == "screen")
        {
            args.Add("--region");
            args.Add(_selectedRegion);
        }

        return args;
    }

    private string BuildOutputPath(RecordingJobItem job)
    {
        var safeTitle = string.Join("_", job.Title.Split(Path.GetInvalidFileNameChars()));
        var fileName = $"{safeTitle}_{job.DurationSeconds}s.mp4";
        return EnsureUniquePath(Path.Combine(_outputDirectory, fileName));
    }

    private void AddFinishedItem(RecordingJobItem job, SidecarResult result)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush = (Brush)Application.Current.Resources["AccentRedBrush"];
        var details = result.Success
            ? $"{job.PresetSummary} - {(result.SizeBytes is long size ? FormatSize(size) : "saved")}"
            : result.ErrorMessage ?? "Recording failed";

        _finished.Insert(0, new RecordingFinishedItem
        {
            Title = result.Success && !string.IsNullOrWhiteSpace(result.OutputPath)
                ? Path.GetFileName(result.OutputPath)
                : job.Title,
            Details = details,
            OutputPath = result.OutputPath ?? "",
            Success = result.Success,
            Glyph = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasQueued = _queue.Count > 0;
        var hasFinished = _finished.Count > 0;
        var pending = _queue.Count(j => !j.IsComplete);

        QueueEmpty.Visibility = hasQueued ? Visibility.Collapsed : Visibility.Visible;
        QueueList.Visibility = hasQueued ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;

        QueueSummaryText.Text = $"{pending} pending / {_finished.Count} finished";
        CurrentSetupText.Text = $"{FormatDuration(SelectedInt(DurationCombo, 30))}, {SelectedInt(FrameRateCombo, 30)} fps, CRF {SelectedInt(QualityCombo, 20)}. Output: {_outputDirectory}.";
        RecordButton.IsEnabled = _cts is null;
        ClearQueueButton.IsEnabled = hasQueued && _cts is null;
        CancelButton.IsEnabled = _cts is not null;

        if (updateStatus && _cts is null)
        {
            StatusText.Text = pending == 0
                ? "Add a recording session, or click Record All to capture the current setup."
                : $"Ready to record {pending} queued sessions.";
        }
    }

    private static int SelectedInt(ComboBox combo, int fallback)
    {
        if (combo.SelectedItem is ComboBoxItem item &&
            int.TryParse(item.Tag?.ToString(), out var value))
        {
            return value;
        }

        return fallback;
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
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\""{folder}\"""))
            {
                UseShellExecute = true,
            });
        }
        catch
        {
            // Convenience action only; keep recorder state intact if Explorer fails.
        }
    }

    private static string FormatDuration(int seconds)
    {
        if (seconds < 60)
            return $"{seconds}s";

        var span = TimeSpan.FromSeconds(seconds);
        return span.TotalHours >= 1
            ? $"{(int)span.TotalHours}h {span.Minutes}m"
            : $"{span.Minutes}m";
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

public sealed class RecordingJobItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private bool _isComplete;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Title { get; set; } = "";
    public DateTime StartedAt { get; set; }
    public int DurationSeconds { get; set; }
    public int FrameRate { get; set; }
    public int Crf { get; set; }
    public string EncoderPreset { get; set; } = "veryfast";
    public string PresetSummary { get; set; } = "";
    public string Details { get; set; } = "";
    public string Source { get; set; } = "screen";
    public string? WebcamDevice { get; set; }
    public string? AudioDevice { get; set; }

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

public sealed class RecordingFinishedItem
{
    public string Title { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush AccentBrush { get; set; } = null!;
    public bool CanOpenFolder => Success && !string.IsNullOrWhiteSpace(OutputPath);
}
