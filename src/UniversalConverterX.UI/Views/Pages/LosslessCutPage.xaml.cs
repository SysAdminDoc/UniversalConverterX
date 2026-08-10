using System.Collections.ObjectModel;
using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media.Imaging;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

/// <summary>
/// Keyframe-aware lossless cutting page. Loads a visual thumbnail strip and
/// waveform (clipforge <c>timeline</c>) plus the video keyframe list
/// (clipforge <c>keyframes</c>), lets the user set in/out points that snap to
/// keyframes in lossless mode, and exports a stream-copy cut with no re-encode.
/// </summary>
public sealed partial class LosslessCutPage : Page
{
    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv",
        ".ts", ".mts", ".m2ts", ".m4v", ".mpg", ".mpeg",
    ];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<TimelineThumb> _thumbs = [];

    private string? _sourcePath;
    private string? _outputPath;
    private double _duration;
    private double _inPoint;
    private double _outPoint;
    private double _playhead;
    private IReadOnlyList<double> _keyframes = [];
    private CancellationTokenSource? _cts;
    private CancellationTokenSource? _loadCts;
    private bool _draggingOverlay;

    public LosslessCutPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        ThumbStrip.ItemsSource = _thumbs;
    }

    // ── File input ────────────────────────────────────────────────────────────

    private async void Open_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker { ViewMode = PickerViewMode.List };
        foreach (var extension in VideoExtensions)
            picker.FileTypeFilter.Add(extension);
        var handle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, handle);
        var file = await picker.PickSingleFileAsync();
        if (file is not null)
            await LoadVideoAsync(file.Path);
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Open for lossless cutting");
        e.DragUIOverride.IsCaptionVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        var items = await DropSnapshotHelper.TrySnapshotDropAsync(e);
        if (items is null)
            return;
        var file = items.OfType<StorageFile>()
            .FirstOrDefault(f => VideoExtensions.Contains(Path.GetExtension(f.Path).ToLowerInvariant()));
        if (file is not null)
            await LoadVideoAsync(file.Path);
    }

    private async Task LoadVideoAsync(string path)
    {
        if (_cts is not null)
            return;

        _loadCts?.Cancel();
        _loadCts = new CancellationTokenSource();
        var ct = _loadCts.Token;

        _sourcePath = path;
        _thumbs.Clear();
        _keyframes = [];
        PreviewImage.Source = null;
        StatusText.Text = AppLocalizer.Format($"Analysing {Path.GetFileName(path)}…");

        if (_runner.Locate("clipforge") is null)
        {
            StatusText.Text = AppLocalizer.Get("The clipforge engine was not found. Build it with tools/clipforge/build.ps1.");
            return;
        }

        var outputDirectory = Path.Combine(
            Path.GetTempPath(), "UniversalConverterX", "lossless-cut",
            Math.Abs(path.GetHashCode()).ToString("x8", CultureInfo.InvariantCulture));
        try { Directory.CreateDirectory(outputDirectory); }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Format($"Could not create the analysis cache: {ex.Message}");
            return;
        }

        // Timeline: thumbnail strip + duration.
        var thumbEntries = new List<(double Timestamp, string Path)>();
        double duration = 0;
        var timeline = await _runner.RunAsync(
            "clipforge",
            [
                "timeline",
                "--input", path,
                "--output-dir", outputDirectory,
                "--thumb-fps", "1",
                "--thumb-height", "72",
            ],
            ct: ct,
            onRawEvent: (name, payload) =>
            {
                if (name == "thumb"
                    && payload.TryGetProperty("path", out var tp) && tp.ValueKind == System.Text.Json.JsonValueKind.String
                    && payload.TryGetProperty("timestamp_seconds", out var ts) && ts.ValueKind == System.Text.Json.JsonValueKind.Number)
                {
                    thumbEntries.Add((ts.GetDouble(), tp.GetString()!));
                }
                else if (name == "complete"
                    && payload.TryGetProperty("duration_seconds", out var d) && d.ValueKind == System.Text.Json.JsonValueKind.Number)
                {
                    duration = d.GetDouble();
                }
            });

        if (ct.IsCancellationRequested)
            return;

        if (!timeline.Success || duration <= 0)
        {
            StatusText.Text = AppLocalizer.Get("Could not read the video timeline. Is it a valid media file?");
            return;
        }

        // Keyframes for snapping.
        var keyframes = new List<double>();
        await _runner.RunAsync(
            "clipforge",
            ["keyframes", "--input", path],
            ct: ct,
            onRawEvent: (name, payload) =>
            {
                if (name == "keyframes"
                    && payload.TryGetProperty("timestamps", out var arr)
                    && arr.ValueKind == System.Text.Json.JsonValueKind.Array)
                {
                    foreach (var element in arr.EnumerateArray())
                        if (element.ValueKind == System.Text.Json.JsonValueKind.Number)
                            keyframes.Add(element.GetDouble());
                }
            });

        if (ct.IsCancellationRequested)
            return;

        _duration = duration;
        _keyframes = keyframes.Count > 0 ? keyframes : [0.0];
        _inPoint = 0;
        _outPoint = duration;
        _playhead = 0;

        thumbEntries.Sort((a, b) => a.Timestamp.CompareTo(b.Timestamp));
        foreach (var (timestamp, thumbPath) in thumbEntries)
        {
            if (!File.Exists(thumbPath))
                continue;
            _thumbs.Add(new TimelineThumb
            {
                Timestamp = timestamp,
                Image = new BitmapImage(new Uri(thumbPath)) { DecodePixelHeight = 72 },
            });
        }

        EmptyState.Visibility = Visibility.Collapsed;
        EditorPanel.Visibility = Visibility.Visible;
        LayoutThumbs();
        UpdateKeyframeHint();
        SeekTo(0);
        UpdateInOutLabels();
        UpdateSelectionSummary();
        UpdateExportEnabled();
        StatusText.Text =
            AppLocalizer.Format($"{Path.GetFileName(path)} · {FormatTime(duration)} · {_keyframes.Count} keyframes. ") +
            AppLocalizer.Get("Scrub, set In/Out, then export.");
    }

    // ── Scrubbing ───────────────────────────────────────────────────────────────

    private void Scrub_ValueChanged(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (_duration <= 0)
            return;
        SeekTo(e.NewValue / 1000.0 * _duration, fromSlider: true);
    }

    private void SeekTo(double seconds, bool fromSlider = false)
    {
        _playhead = Math.Clamp(seconds, 0, _duration);
        if (!fromSlider && _duration > 0)
            ScrubSlider.Value = _playhead / _duration * 1000.0;

        PlayheadLabel.Text = FormatTime(_playhead);

        var nearest = NearestThumb(_playhead);
        if (nearest is not null)
            PreviewImage.Source = nearest.Image;

        UpdatePlayheadVisual();
    }

    private TimelineThumb? NearestThumb(double seconds)
    {
        TimelineThumb? best = null;
        var bestDelta = double.MaxValue;
        foreach (var thumb in _thumbs)
        {
            var delta = Math.Abs(thumb.Timestamp - seconds);
            if (delta < bestDelta)
            {
                bestDelta = delta;
                best = thumb;
            }
        }
        return best;
    }

    // ── In / Out ─────────────────────────────────────────────────────────────────

    private void SetIn_Click(object sender, RoutedEventArgs e)
    {
        var value = _playhead;
        if (LosslessToggle.IsOn)
            value = SnapDownToKeyframe(value);
        _inPoint = Math.Min(value, _outPoint - 0.001);
        _inPoint = Math.Max(0, _inPoint);
        UpdateInOutLabels();
        UpdateSelectionVisual();
        UpdateSelectionSummary();
    }

    private void SetOut_Click(object sender, RoutedEventArgs e)
    {
        var value = _playhead;
        if (LosslessToggle.IsOn)
            value = SnapUpToKeyframe(value);
        _outPoint = Math.Max(value, _inPoint + 0.001);
        _outPoint = Math.Min(_duration, _outPoint);
        UpdateInOutLabels();
        UpdateSelectionVisual();
        UpdateSelectionSummary();
    }

    private void Lossless_Toggled(object sender, RoutedEventArgs e)
    {
        if (_duration <= 0)
            return;
        if (LosslessToggle.IsOn)
        {
            _inPoint = SnapDownToKeyframe(_inPoint);
            _outPoint = SnapUpToKeyframe(_outPoint);
            UpdateInOutLabels();
            UpdateSelectionVisual();
        }
        UpdateSelectionSummary();
        UpdateKeyframeHint();
    }

    private double SnapDownToKeyframe(double seconds)
    {
        double best = 0;
        foreach (var kf in _keyframes)
            if (kf <= seconds + 0.0005 && kf >= best)
                best = kf;
        return best;
    }

    private double SnapUpToKeyframe(double seconds)
    {
        foreach (var kf in _keyframes)
            if (kf >= seconds - 0.0005)
                return Math.Min(kf, _duration);
        return _duration;
    }

    private void UpdateInOutLabels()
    {
        InLabel.Text = FormatTime(_inPoint);
        OutLabel.Text = FormatTime(_outPoint);
    }

    private void UpdateSelectionSummary()
    {
        if (_duration <= 0)
        {
            SelectionSummary.Text = AppLocalizer.Get("Whole clip");
            return;
        }
        var span = Math.Max(0, _outPoint - _inPoint);
        var mode = LosslessToggle.IsOn ? "keyframe-snapped, stream copy" : "frame-exact, re-encode";
        SelectionSummary.Text = AppLocalizer.Format($"Cut {FormatTime(_inPoint)} → {FormatTime(_outPoint)} ({FormatTime(span)}, {mode}).");
    }

    private void UpdateKeyframeHint()
    {
        if (_keyframes.Count == 0)
        {
            KeyframeHint.Text = AppLocalizer.Get("Keyframes: —");
            return;
        }
        KeyframeHint.Text = LosslessToggle.IsOn
            ? AppLocalizer.Format($"Keyframes: {_keyframes.Count}. In/Out snap to the nearest keyframe so the copy is exact.")
            : AppLocalizer.Format($"Keyframes: {_keyframes.Count}. Re-encode mode cuts on any frame.");
    }

    // ── Timeline overlay geometry ────────────────────────────────────────────────

    private void Timeline_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        LayoutThumbs();
        UpdateSelectionVisual();
        UpdatePlayheadVisual();
    }

    private void LayoutThumbs()
    {
        if (_thumbs.Count == 0)
            return;
        var available = OverlayCanvas.ActualWidth;
        if (available <= 0)
            available = 600;
        var width = Math.Max(6, available / _thumbs.Count);
        foreach (var thumb in _thumbs)
            thumb.Width = width;
    }

    private void UpdateSelectionVisual()
    {
        if (_duration <= 0)
            return;
        var width = OverlayCanvas.ActualWidth;
        if (width <= 0)
            return;
        var left = _inPoint / _duration * width;
        var right = _outPoint / _duration * width;
        Canvas.SetLeft(SelectionBand, left);
        SelectionBand.Width = Math.Max(0, right - left);
    }

    private void UpdatePlayheadVisual()
    {
        if (_duration <= 0)
            return;
        var width = OverlayCanvas.ActualWidth;
        if (width <= 0)
            return;
        Canvas.SetLeft(Playhead, Math.Clamp(_playhead / _duration * width, 0, width - 2));
    }

    private void Overlay_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        _draggingOverlay = true;
        OverlayCanvas.CapturePointer(e.Pointer);
        SeekFromPointer(e);
    }

    private void Overlay_PointerMoved(object sender, PointerRoutedEventArgs e)
    {
        if (_draggingOverlay)
            SeekFromPointer(e);
    }

    private void Overlay_PointerReleased(object sender, PointerRoutedEventArgs e)
    {
        _draggingOverlay = false;
        OverlayCanvas.ReleasePointerCapture(e.Pointer);
    }

    private void SeekFromPointer(PointerRoutedEventArgs e)
    {
        var width = OverlayCanvas.ActualWidth;
        if (width <= 0 || _duration <= 0)
            return;
        var x = e.GetCurrentPoint(OverlayCanvas).Position.X;
        SeekTo(Math.Clamp(x / width, 0, 1) * _duration);
    }

    // ── Output + export ──────────────────────────────────────────────────────────

    private async void ChooseOutput_Click(object sender, RoutedEventArgs e)
    {
        if (_sourcePath is null)
            return;
        var picker = new FileSavePicker { SuggestedStartLocation = PickerLocationId.VideosLibrary };
        var extension = Path.GetExtension(_sourcePath);
        if (string.IsNullOrWhiteSpace(extension))
            extension = ".mp4";
        picker.FileTypeChoices.Add("Video", [extension]);
        picker.SuggestedFileName = Path.GetFileNameWithoutExtension(_sourcePath) + "_cut";
        var handle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, handle);
        var file = await picker.PickSaveFileAsync();
        if (file is not null)
        {
            _outputPath = file.Path;
            OutputBox.Text = file.Path;
            UpdateExportEnabled();
        }
    }

    private void UpdateExportEnabled()
    {
        ExportButton.IsEnabled = _cts is null && _sourcePath is not null && _duration > 0;
    }

    private string DefaultOutputPath()
    {
        var directory = Path.GetDirectoryName(_sourcePath!) ?? Path.GetTempPath();
        var stem = Path.GetFileNameWithoutExtension(_sourcePath!);
        var extension = Path.GetExtension(_sourcePath!);
        if (string.IsNullOrWhiteSpace(extension))
            extension = ".mp4";
        return Path.Combine(directory, $"{stem}_cut{extension}");
    }

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null || _sourcePath is null || _duration <= 0)
            return;

        var output = _outputPath ?? DefaultOutputPath();
        if (string.Equals(Path.GetFullPath(output), Path.GetFullPath(_sourcePath), StringComparison.OrdinalIgnoreCase))
        {
            StatusText.Text = AppLocalizer.Get("Choose an output file that is different from the source.");
            return;
        }

        var args = new List<string>
        {
            "trim",
            "--input", _sourcePath,
            "--output", output,
            "--start", _inPoint.ToString("0.###", CultureInfo.InvariantCulture),
            "--end", _outPoint.ToString("0.###", CultureInfo.InvariantCulture),
        };
        if (LosslessToggle.IsOn)
            args.Add("--lossless");

        _cts = new CancellationTokenSource();
        ExportButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        ExportProgress.Visibility = Visibility.Visible;
        ExportProgress.Value = 0;
        StatusText.Text = AppLocalizer.Get("Exporting cut…");

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            ExportProgress.Value = Math.Clamp(p.Percent, 0, 100);
            StatusText.Text = AppLocalizer.Format($"Exporting cut… {p.Percent:F0}% — {p.Stage}");
        }));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync("clipforge", args, progress, null, _cts.Token);
        }
        catch (OperationCanceledException)
        {
            result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user", 130);
        }
        finally
        {
            _cts = null;
            CancelButton.IsEnabled = false;
            ExportProgress.Visibility = Visibility.Collapsed;
            UpdateExportEnabled();
        }

        StatusText.Text = result.Success
            ? AppLocalizer.Format($"Saved cut to {output}.")
            : result.ErrorCode == "cancelled"
                ? AppLocalizer.Get("Export cancelled.")
                : AppLocalizer.Format($"Export failed: {result.ErrorMessage}");
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => _cts?.Cancel();

    private static string FormatTime(double seconds)
    {
        if (seconds < 0)
            seconds = 0;
        var span = TimeSpan.FromSeconds(seconds);
        return span.Hours > 0
            ? $"{(int)span.TotalHours:00}:{span.Minutes:00}:{span.Seconds:00}.{span.Milliseconds:000}"
            : $"{span.Minutes:00}:{span.Seconds:00}.{span.Milliseconds:000}";
    }

    private sealed class TimelineThumb : System.ComponentModel.INotifyPropertyChanged
    {
        public double Timestamp { get; init; }
        public BitmapImage? Image { get; init; }

        private double _width = 12;
        public double Width
        {
            get => _width;
            set
            {
                if (Math.Abs(_width - value) < 0.01)
                    return;
                _width = value;
                PropertyChanged?.Invoke(this, new System.ComponentModel.PropertyChangedEventArgs(nameof(Width)));
            }
        }

        public event System.ComponentModel.PropertyChangedEventHandler? PropertyChanged;
    }
}
