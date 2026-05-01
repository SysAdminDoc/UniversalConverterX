using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Media.Imaging;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class TimelineThumb
{
    public int Index { get; init; }
    public double TimestampSeconds { get; init; }
    public string ImagePath { get; init; } = "";

    public string TimecodeLabel
    {
        get
        {
            var ts = TimeSpan.FromSeconds(TimestampSeconds);
            return ts.TotalHours >= 1
                ? $"{(int)ts.TotalHours:D2}:{ts.Minutes:D2}:{ts.Seconds:D2}"
                : $"{ts.Minutes:D2}:{ts.Seconds:D2}";
        }
    }
}

public sealed partial class TimelinePreviewPage : Page
{
    private static readonly string[] VideoExts =
        [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<TimelineThumb> _thumbs = [];
    private string? _currentPath;
    private string? _outputDir;
    private double _durationSeconds;

    public TimelinePreviewPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        ThumbStrip.ItemsSource = _thumbs;
    }

    private async void OpenFile_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var ext in VideoExts) picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var f = await picker.PickSingleFileAsync();
        if (f is null) return;

        _currentPath = f.Path;
        StatusText.Text = $"Loaded: {Path.GetFileName(_currentPath)}";
        GenerateButton.IsEnabled = true;
    }

    private async void Generate_Click(object sender, RoutedEventArgs e)
    {
        if (_currentPath is null) return;

        _thumbs.Clear();
        WaveformImage.Source = null;
        SeekSlider.IsEnabled = false;
        SeekSlider.Value = 0;
        ExportButton.IsEnabled = false;
        GenerateButton.IsEnabled = false;
        GenProgress.Value = 0;
        EmptyState.Visibility = Visibility.Collapsed;
        TimelineRoot.Visibility = Visibility.Visible;

        _outputDir = Path.Combine(Path.GetTempPath(),
                                  $"ucx_timeline_{Guid.NewGuid():N}");
        try { Directory.CreateDirectory(_outputDir); }
        catch (Exception ex)
        {
            EmptyState.Visibility = Visibility.Visible;
            TimelineRoot.Visibility = Visibility.Collapsed;
            GenerateButton.IsEnabled = true;
            // Disk full / locked TEMP — keep the page recoverable. Surface
            // the failure in the debug log; the empty-state panel stays
            // generic since it's a designer-set composition.
            System.Diagnostics.Debug.WriteLine($"TimelinePreview: scratch dir failed: {ex.Message}");
            return;
        }

        var fps = ThumbFpsBox.Value.ToString("0.##", CultureInfo.InvariantCulture);
        var height = ((int)ThumbHeightBox.Value).ToString(CultureInfo.InvariantCulture);

        var args = new List<string>
        {
            "timeline",
            "--input",       _currentPath,
            "--output-dir",  _outputDir,
            "--thumb-fps",   fps,
            "--thumb-height", height,
        };

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            GenProgress.Value = p.Percent;
            StatusText.Text = $"{p.Stage} -- {p.Percent:F0}%";
        }));
        var log = new Progress<SidecarLog>(_ => { });

        StatusText.Text = "Generating timeline...";
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(15));
        var result = await _runner.RunAsync(
            "clipforge", args, progress, log, cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName == "thumb")
                {
                    _thumbs.Add(new TimelineThumb
                    {
                        Index            = root.TryGetProperty("index", out var i) ? i.GetInt32() : _thumbs.Count,
                        TimestampSeconds = root.TryGetProperty("timestamp_seconds", out var ts) ? ts.GetDouble() : 0,
                        ImagePath        = root.TryGetProperty("path", out var p) ? p.GetString() ?? "" : "",
                    });
                }
                else if (evName == "complete")
                {
                    if (root.TryGetProperty("duration_seconds", out var d))
                        _durationSeconds = d.GetDouble();
                    if (root.TryGetProperty("waveform_path", out var wp) &&
                        wp.ValueKind == System.Text.Json.JsonValueKind.String &&
                        wp.GetString() is string wfPath && File.Exists(wfPath))
                    {
                        try { WaveformImage.Source = new BitmapImage(new Uri(wfPath)); }
                        catch { /* corrupt PNG, ignore */ }
                    }
                }
            }));

        if (result.ErrorCode == "sidecar_not_found")
        {
            StatusText.Text = "clipforge sidecar not built. Run pwsh tools/clipforge/build.ps1.";
        }
        else if (result.Success)
        {
            StatusText.Text = $"Done -- {_thumbs.Count} thumbnail(s).";
            GenProgress.Value = 100;
            if (_durationSeconds > 0)
            {
                SeekSlider.Maximum = _durationSeconds;
                SeekSlider.Value = 0;
                SeekSlider.IsEnabled = true;
                UpdateSeekLabel(0);
            }
            ExportButton.IsEnabled = true;
        }
        else
        {
            StatusText.Text = $"Generation failed: {result.ErrorMessage ?? result.ErrorCode}";
        }
        GenerateButton.IsEnabled = true;
    }

    private void SeekSlider_ValueChanged(object sender, RangeBaseValueChangedEventArgs e)
    {
        UpdateSeekLabel(e.NewValue);
        // Scroll the strip so the thumb closest to the cursor sits roughly centered.
        if (_thumbs.Count == 0 || _durationSeconds <= 0) return;
        var ratio = e.NewValue / _durationSeconds;
        var stripWidth = ThumbStrip.ActualWidth;
        var target = Math.Max(0, ratio * stripWidth - ThumbStripScroll.ViewportWidth / 2);
        ThumbStripScroll.ChangeView(target, null, null, disableAnimation: true);
    }

    private void UpdateSeekLabel(double seconds)
    {
        SeekLabel.Text = $"{Format(seconds)} / {Format(_durationSeconds)}";
    }

    private static string Format(double seconds)
    {
        if (seconds < 0 || double.IsNaN(seconds)) return "00:00.000";
        var ts = TimeSpan.FromSeconds(seconds);
        return ts.TotalHours >= 1
            ? $"{(int)ts.TotalHours:D2}:{ts.Minutes:D2}:{ts.Seconds:D2}.{ts.Milliseconds:D3}"
            : $"{ts.Minutes:D2}:{ts.Seconds:D2}.{ts.Milliseconds:D3}";
    }

    private void Export_Click(object sender, RoutedEventArgs e)
    {
        if (_outputDir is null || !Directory.Exists(_outputDir)) return;
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "explorer.exe",
                Arguments = $"\"{_outputDir}\"",
                UseShellExecute = true,
            });
        }
        catch { /* best-effort */ }
    }
}
