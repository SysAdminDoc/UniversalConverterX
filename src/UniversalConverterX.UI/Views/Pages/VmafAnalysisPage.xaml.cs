using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class VmafAnalysisPage : Page
{
    private static readonly string[] VideoExts =
        [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"];

    private readonly ISidecarRunner _runner;
    private string? _reference;
    private string? _distorted;

    public VmafAnalysisPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
    }

    private async void PickReference_Click(object sender, RoutedEventArgs e)
    {
        var picked = await PickAsync();
        if (picked is null) return;
        _reference = picked;
        ReferenceLabel.Text = picked;
        UpdateUi();
    }

    private async void PickDistorted_Click(object sender, RoutedEventArgs e)
    {
        var picked = await PickAsync();
        if (picked is null) return;
        _distorted = picked;
        DistortedLabel.Text = picked;
        UpdateUi();
    }

    private async Task<string?> PickAsync()
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
        return f?.Path;
    }

    private void UpdateUi()
    {
        RunButton.IsEnabled = _reference is not null && _distorted is not null;
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_reference is null || _distorted is null) return;
        ResetStats();
        RunButton.IsEnabled = false;
        StatusText.Text = "Running VMAF -- this may take a few minutes for long clips.";

        var args = new List<string>
        {
            "vmaf",
            "--reference", _reference,
            "--distorted", _distorted,
        };

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            VmafProgress.Value = p.Percent;
        }));
        var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
        {
            LogText.Text += $"[{l.Level}] {l.Message}\n";
        }));

        using var cts = new CancellationTokenSource(TimeSpan.FromHours(1));
        var result = await _runner.RunAsync(
            "clipforge", args, progress, log, cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName != "vmaf_summary") return;
                if (root.TryGetProperty("mean", out var mean))
                    StatMean.Text = mean.GetDouble().ToString("F2", CultureInfo.InvariantCulture);
                if (root.TryGetProperty("harmonic_mean", out var hm))
                    StatHarmonic.Text = hm.GetDouble().ToString("F2", CultureInfo.InvariantCulture);
                if (root.TryGetProperty("min", out var mn))
                    StatMin.Text = mn.GetDouble().ToString("F2", CultureInfo.InvariantCulture);
                if (root.TryGetProperty("below_70_percent", out var b70))
                    StatBelow70.Text = $"{b70.GetDouble():F1}%";
            }));

        StatusText.Text = result.Success
            ? "VMAF complete. Higher mean = closer to reference (90+ is excellent, 70- is visibly degraded)."
            : $"VMAF failed: {result.ErrorMessage ?? result.ErrorCode}";
        VmafProgress.Value = result.Success ? 100 : 0;
        RunButton.IsEnabled = true;
    }

    private void ResetStats()
    {
        StatMean.Text = "--";
        StatHarmonic.Text = "--";
        StatMin.Text = "--";
        StatBelow70.Text = "--";
        LogText.Text = "";
        VmafProgress.Value = 0;
    }
}
