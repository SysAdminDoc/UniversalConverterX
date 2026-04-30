using System.Collections.ObjectModel;
using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class SceneRow
{
    public int Index { get; init; }
    public string StartTc { get; init; } = "";
    public string EndTc { get; init; } = "";
    public double StartSeconds { get; init; }
    public double EndSeconds { get; init; }

    public string IndexLabel => $"#{Index + 1:D3}";
    public string DurationLabel => $"{(EndSeconds - StartSeconds):F2}s";
}

public sealed partial class SceneDetectPage : Page
{
    private static readonly string[] VideoExts =
        [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<SceneRow> _scenes = [];
    private string? _currentPath;

    public SceneDetectPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        ScenesList.ItemsSource = _scenes;
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
        DetectButton.IsEnabled = true;
        _scenes.Clear();
        ExportCsvButton.IsEnabled = false;
        ExportEdlButton.IsEnabled = false;
        UpdateUi();
    }

    private async void Detect_Click(object sender, RoutedEventArgs e)
    {
        if (_currentPath is null) return;

        DetectButton.IsEnabled = false;
        _scenes.Clear();
        ExportCsvButton.IsEnabled = false;
        ExportEdlButton.IsEnabled = false;
        DetectProgress.Value = 0;
        StatusText.Text = "Detecting scenes...";
        UpdateUi();

        var detector = (DetectorCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "content";
        var threshold = ThresholdBox.Value.ToString("0.##", CultureInfo.InvariantCulture);
        var minLen = ((int)MinLenBox.Value).ToString(CultureInfo.InvariantCulture);

        var args = new List<string>
        {
            "detect",
            "--input", _currentPath,
            "--detector", detector,
            "--threshold", threshold,
            "--min-scene-len", minLen,
        };

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            DetectProgress.Value = p.Percent;
        }));
        var log = new Progress<SidecarLog>(_ => { /* stay quiet -- detector is verbose */ });

        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(30));
        var result = await _runner.RunAsync(
            "scenedetect", args, progress, log, cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName != "scene") return;
                _scenes.Add(new SceneRow
                {
                    Index        = root.TryGetProperty("index", out var i) ? i.GetInt32() : _scenes.Count,
                    StartTc      = root.TryGetProperty("start_tc", out var s) ? s.GetString() ?? "" : "",
                    EndTc        = root.TryGetProperty("end_tc", out var en) ? en.GetString() ?? "" : "",
                    StartSeconds = root.TryGetProperty("start_seconds", out var ss) ? ss.GetDouble() : 0,
                    EndSeconds   = root.TryGetProperty("end_seconds", out var ee) ? ee.GetDouble() : 0,
                });
                UpdateUi();
            }));

        if (result.ErrorCode == "sidecar_not_found")
        {
            StatusText.Text = "scenedetect sidecar not built. Run pwsh tools/scenedetect/build.ps1.";
        }
        else
        {
            StatusText.Text = result.Success
                ? $"Done -- {_scenes.Count} scene(s) detected."
                : $"Detection failed: {result.ErrorMessage ?? result.ErrorCode}";
        }
        DetectButton.IsEnabled = true;
        ExportCsvButton.IsEnabled = _scenes.Count > 0;
        ExportEdlButton.IsEnabled = _scenes.Count > 0;
    }

    private void UpdateUi()
    {
        EmptyState.Visibility = _scenes.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        ScenesScroll.Visibility = _scenes.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
    }

    private async void ExportCsv_Click(object sender, RoutedEventArgs e) =>
        await ExportAsync(csv: true);

    private async void ExportEdl_Click(object sender, RoutedEventArgs e) =>
        await ExportAsync(csv: false);

    private async Task ExportAsync(bool csv)
    {
        if (_currentPath is null || _scenes.Count == 0) return;

        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
            SuggestedFileName = Path.GetFileNameWithoutExtension(_currentPath) +
                                (csv ? "_scenes" : "_scenes_edl"),
        };
        if (csv) picker.FileTypeChoices.Add("CSV", [".csv"]);
        else     picker.FileTypeChoices.Add("EDL", [".edl"]);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var f = await picker.PickSaveFileAsync();
        if (f is null) return;

        var args = new List<string>
        {
            "detect",
            "--input", _currentPath,
            "--detector", (DetectorCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "content",
            "--threshold", ThresholdBox.Value.ToString("0.##", CultureInfo.InvariantCulture),
            "--min-scene-len", ((int)MinLenBox.Value).ToString(CultureInfo.InvariantCulture),
            csv ? "--output-csv" : "--output-edl", f.Path,
        };
        StatusText.Text = $"Exporting {(csv ? "CSV" : "EDL")}...";
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(30));
        var result = await _runner.RunAsync("scenedetect", args, null, null, cts.Token);
        StatusText.Text = result.Success
            ? $"Exported -> {Path.GetFileName(f.Path)}"
            : $"Export failed: {result.ErrorMessage ?? result.ErrorCode}";
    }
}
