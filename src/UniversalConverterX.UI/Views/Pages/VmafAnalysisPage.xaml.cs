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

        var reference = _reference;
        var distorted = _distorted;
        var proxied = false;

        using var cts = new CancellationTokenSource(TimeSpan.FromHours(1));

        // ROADMAP Item 74 — optional 480p proxy pass. Downscaling both inputs
        // to a fast proxy gives an approximate VMAF far quicker than a
        // full-resolution run; useful for iterating on encode settings before
        // confirming the final score at full resolution.
        if (ProxyToggle.IsOn)
        {
            StatusText.Text = AppLocalizer.Get("Generating 480p proxies...");
            var proxyReference = await GenerateProxyAsync(_reference, "reference", cts.Token);
            var proxyDistorted = proxyReference is null
                ? null
                : await GenerateProxyAsync(_distorted, "distorted", cts.Token);
            if (proxyReference is null || proxyDistorted is null)
            {
                StatusText.Text = AppLocalizer.Get("Could not generate proxies; run without the fast pass or check the clipforge engine.");
                RunButton.IsEnabled = true;
                return;
            }
            reference = proxyReference;
            distorted = proxyDistorted;
            proxied = true;
        }

        StatusText.Text = proxied
            ? AppLocalizer.Get("Running approximate VMAF on 480p proxies...")
            : AppLocalizer.Get("Running VMAF -- this may take a few minutes for long clips.");

        var args = new List<string>
        {
            "vmaf",
            "--reference", reference,
            "--distorted", distorted,
        };

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            VmafProgress.Value = p.Percent;
        }));
        var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
        {
            LogText.Text += $"[{l.Level}] {l.Message}\n";
        }));

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
                    StatBelow70.Text = AppLocalizer.Format($"{b70.GetDouble():F1}%");
            }));

        StatusText.Text = result.Success
            ? proxied
                ? AppLocalizer.Get("Approximate VMAF complete (480p proxies). Re-run without the fast pass to confirm the full-resolution score.")
                : AppLocalizer.Get("VMAF complete. Higher mean = closer to reference (90+ is excellent, 70- is visibly degraded).")
            : AppLocalizer.Format($"VMAF failed: {result.ErrorMessage ?? result.ErrorCode}");
        VmafProgress.Value = result.Success ? 100 : 0;
        RunButton.IsEnabled = true;
    }

    /// <summary>
    /// Generates a 480p preview proxy of <paramref name="source"/> via the
    /// clipforge proxy op, returning the proxy path or null on failure.
    /// </summary>
    private async Task<string?> GenerateProxyAsync(string source, string label, CancellationToken ct)
    {
        var cacheDir = System.IO.Path.Combine(
            System.IO.Path.GetTempPath(), "UniversalConverterX", "vmaf-proxies");
        try { System.IO.Directory.CreateDirectory(cacheDir); }
        catch { return null; }

        var proxyPath = System.IO.Path.Combine(
            cacheDir,
            $"{System.IO.Path.GetFileNameWithoutExtension(source)}-{label}-{Math.Abs(source.GetHashCode()):x8}-480p.mp4");

        var result = await _runner.RunAsync(
            "clipforge",
            ["proxy", "--input", source, "--output", proxyPath, "--height", "480"],
            ct: ct);

        return result.Success && System.IO.File.Exists(proxyPath) ? proxyPath : null;
    }

    private void ResetStats()
    {
        StatMean.Text = AppLocalizer.Get("--");
        StatHarmonic.Text = AppLocalizer.Get("--");
        StatMin.Text = AppLocalizer.Get("--");
        StatBelow70.Text = AppLocalizer.Get("--");
        LogText.Text = "";
        VmafProgress.Value = 0;
    }
}
