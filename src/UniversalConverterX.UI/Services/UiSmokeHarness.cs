using System.Text;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media.Imaging;
using UniversalConverterX.UI.Views;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// Options parsed from the <c>--ui-smoke</c> command line switch.
/// </summary>
internal sealed record UiSmokeOptions(
    string ReportDirectory,
    bool CaptureEveryPage,
    TimeSpan PageTimeout);

/// <summary>
/// Result of navigating one route in one theme.
/// </summary>
internal sealed record UiSmokeResult(
    string RouteKey,
    string Theme,
    string ExpectedPage,
    string? ActualPage,
    bool Passed,
    string? Failure,
    string? ScreenshotPath,
    double ElapsedMilliseconds);

/// <summary>
/// Drives the real shell through every registered route in both themes and at
/// the reflow-critical window sizes, then writes a machine-readable report.
///
/// Static XAML inspection cannot prove that a page constructs, lays out, and
/// exposes a reachable focus target at runtime; every historical page-init NRE
/// and window <c>x:Uid</c> parse failure in this project was found by hand.
/// This harness is the automated replacement.
/// </summary>
internal static class UiSmokeHarness
{
    private const string SwitchName = "--ui-smoke";
    private const string ReportFileName = "ui-smoke.json";
    private const string LogFileName = "ui-smoke.ndjson";

    private static readonly (string Name, ElementTheme Theme)[] Themes =
    [
        ("light", ElementTheme.Light),
        ("dark", ElementTheme.Dark),
    ];

    private static readonly List<string> UnhandledExceptions = [];

    /// <summary>True once the harness has taken over this process.</summary>
    internal static bool IsActive { get; private set; }

    internal static UiSmokeOptions? TryParse(IReadOnlyList<string>? argv)
    {
        if (argv is null)
        {
            return null;
        }

        string? reportDirectory = null;
        var captureEveryPage = false;
        var timeout = TimeSpan.FromSeconds(20);
        var requested = false;

        for (var index = 0; index < argv.Count; index++)
        {
            var argument = argv[index];
            if (argument.Equals(SwitchName, StringComparison.OrdinalIgnoreCase))
            {
                requested = true;
                if (index + 1 < argv.Count && !argv[index + 1].StartsWith("--", StringComparison.Ordinal))
                {
                    reportDirectory = argv[++index];
                }
            }
            else if (argument.Equals("--ui-smoke-capture-all", StringComparison.OrdinalIgnoreCase))
            {
                captureEveryPage = true;
            }
            else if (argument.Equals("--ui-smoke-timeout", StringComparison.OrdinalIgnoreCase)
                && index + 1 < argv.Count
                && int.TryParse(argv[index + 1], out var seconds)
                && seconds is > 0 and <= 600)
            {
                timeout = TimeSpan.FromSeconds(seconds);
                index++;
            }
        }

        if (!requested)
        {
            return null;
        }

        reportDirectory ??= Path.Combine(
            Path.GetTempPath(),
            "ucx-ui-smoke-" + Guid.NewGuid().ToString("N"));
        return new UiSmokeOptions(
            Path.GetFullPath(reportDirectory),
            captureEveryPage,
            timeout);
    }

    /// <summary>
    /// Records an unhandled exception seen while the sweep is running. In smoke
    /// mode the exception is swallowed so the run reports every broken page
    /// instead of dying on the first one.
    /// </summary>
    internal static void RecordUnhandled(string source, Exception? exception)
    {
        lock (UnhandledExceptions)
        {
            UnhandledExceptions.Add(
                $"{source}: {exception?.GetType().FullName}: {exception?.Message}");
        }
    }

    internal static async Task RunAsync(MainWindow window, UiSmokeOptions options)
    {
        IsActive = true;
        Directory.CreateDirectory(options.ReportDirectory);

        var log = new StreamWriter(
            Path.Combine(options.ReportDirectory, LogFileName),
            append: false,
            Encoding.UTF8);
        await using var _ = log.ConfigureAwait(true);

        var results = new List<UiSmokeResult>();
        try
        {
            foreach (var (themeName, theme) in Themes)
            {
                UiTestHooks.ApplyTheme(window, theme);
                await SettleAsync().ConfigureAwait(true);

                foreach (var routeKey in NavigationRoutes.RouteKeys)
                {
                    var result = await NavigateAndInspectAsync(
                        window,
                        routeKey,
                        themeName,
                        options).ConfigureAwait(true);
                    results.Add(result);
                    await log.WriteLineAsync(
                        JsonSerializer.Serialize(result)).ConfigureAwait(true);
                    await log.FlushAsync().ConfigureAwait(true);
                }
            }

            // Narrow-window reflow: every page must survive the smallest
            // supported width without throwing during re-layout.
            UiTestHooks.ResizeWindow(window, 640, 720);
            await SettleAsync().ConfigureAwait(true);
            foreach (var routeKey in NavigationRoutes.RouteKeys)
            {
                var result = await NavigateAndInspectAsync(
                    window,
                    routeKey,
                    "dark-narrow",
                    options).ConfigureAwait(true);
                results.Add(result);
                await log.WriteLineAsync(
                    JsonSerializer.Serialize(result)).ConfigureAwait(true);
                await log.FlushAsync().ConfigureAwait(true);
            }
            UiTestHooks.ResizeWindow(window, 1280, 820);
        }
        catch (Exception exception)
        {
            RecordUnhandled("harness", exception);
        }

        string[] unhandled;
        lock (UnhandledExceptions)
        {
            unhandled = [.. UnhandledExceptions];
        }

        var failed = results.Count(result => !result.Passed);
        var report = new
        {
            schemaVersion = 1,
            generatedAtUtc = DateTime.UtcNow.ToString("O"),
            routeCount = NavigationRoutes.RouteKeys.Count,
            passes = results.Count - failed,
            failures = failed,
            unhandledExceptions = unhandled,
            results,
        };
        File.WriteAllText(
            Path.Combine(options.ReportDirectory, ReportFileName),
            JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }),
            Encoding.UTF8);

        Environment.Exit(failed == 0 && unhandled.Length == 0 ? 0 : 1);
    }

    private static async Task<UiSmokeResult> NavigateAndInspectAsync(
        MainWindow window,
        string routeKey,
        string themeName,
        UiSmokeOptions options)
    {
        var started = DateTime.UtcNow;
        var (expected, _) = NavigationRoutes.Resolve(routeKey);
        var frame = window.NavigationFrame;
        string? failure = null;
        Page? page = null;

        try
        {
            window.RequestNavigation(routeKey);
            page = await WaitForPageAsync(frame, expected, options.PageTimeout)
                .ConfigureAwait(true);
            if (page is null)
            {
                failure = frame.Content is Page actual
                    ? $"Navigated to {actual.GetType().Name} instead of {expected.Name}."
                    : $"{expected.Name} never became a laid-out page.";
            }
            else if (page.ActualWidth <= 0 || page.ActualHeight <= 0)
            {
                failure =
                    $"{expected.Name} laid out to an empty rect "
                    + $"({page.ActualWidth}x{page.ActualHeight}).";
            }
            else if (FocusManager.FindFirstFocusableElement(page) is null)
            {
                failure = $"{expected.Name} exposes no reachable focus target.";
            }
        }
        catch (Exception exception)
        {
            failure = $"{exception.GetType().FullName}: {exception.Message}";
        }

        string? screenshot = null;
        if (failure is not null || options.CaptureEveryPage)
        {
            if (options.CaptureEveryPage)
            {
                // NavigationThemeTransition can still be compositing the old
                // page after Frame.Content has switched. Marketing and visual
                // audit captures must name the page that is actually visible.
                await Task.Delay(450).ConfigureAwait(true);
            }
            screenshot = await TryCaptureAsync(
                window,
                Path.Combine(
                    options.ReportDirectory,
                    $"{themeName}--{routeKey.Replace(':', '_')}.png")).ConfigureAwait(true);
        }

        return new UiSmokeResult(
            routeKey,
            themeName,
            expected.Name,
            (frame.Content as Page)?.GetType().Name,
            failure is null,
            failure,
            screenshot,
            (DateTime.UtcNow - started).TotalMilliseconds);
    }

    private static async Task<Page?> WaitForPageAsync(
        Frame frame,
        Type expected,
        TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            if (frame.Content is Page page
                && page.GetType() == expected
                && page.IsLoaded
                && page.ActualWidth > 0
                && page.ActualHeight > 0)
            {
                // One more settle pass so deferred loading (x:Load, incremental
                // list realization) finishes before the focus assertion.
                await SettleAsync().ConfigureAwait(true);
                return frame.Content as Page;
            }

            await Task.Delay(25).ConfigureAwait(true);
        }

        return null;
    }

    private static async Task SettleAsync()
    {
        for (var pass = 0; pass < 3; pass++)
        {
            await Task.Delay(30).ConfigureAwait(true);
        }
    }

    private static async Task<string?> TryCaptureAsync(MainWindow window, string path)
    {
        try
        {
            if (window.Content is not UIElement root)
            {
                return null;
            }

            var bitmap = new RenderTargetBitmap();
            await bitmap.RenderAsync(root);
            var pixelBuffer = await bitmap.GetPixelsAsync();
            var pixels = new byte[pixelBuffer.Length];
            using (var pixelReader = Windows.Storage.Streams.DataReader.FromBuffer(pixelBuffer))
            {
                pixelReader.ReadBytes(pixels);
            }

            using var stream = new Windows.Storage.Streams.InMemoryRandomAccessStream();
            var encoder = await Windows.Graphics.Imaging.BitmapEncoder.CreateAsync(
                Windows.Graphics.Imaging.BitmapEncoder.PngEncoderId,
                stream);
            encoder.SetPixelData(
                Windows.Graphics.Imaging.BitmapPixelFormat.Bgra8,
                Windows.Graphics.Imaging.BitmapAlphaMode.Premultiplied,
                (uint)bitmap.PixelWidth,
                (uint)bitmap.PixelHeight,
                96,
                96,
                pixels);
            await encoder.FlushAsync();

            var buffer = new byte[stream.Size];
            using var reader = new Windows.Storage.Streams.DataReader(
                stream.GetInputStreamAt(0));
            await reader.LoadAsync((uint)stream.Size);
            reader.ReadBytes(buffer);
            await File.WriteAllBytesAsync(path, buffer).ConfigureAwait(true);
            return path;
        }
        catch (Exception exception)
        {
            RecordUnhandled("screenshot", exception);
            return null;
        }
    }
}
