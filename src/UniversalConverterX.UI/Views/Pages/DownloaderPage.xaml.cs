using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class DownloaderPage : Page
{
    private const int FinishedCap = 200;

    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly ISidecarHealthService _health;
    private readonly IToolManager _toolManager;
    private readonly IPostQueueActionService _postQueueActions;
    private readonly ObservableCollection<DownloadJobItem> _queue = [];
    private readonly ObservableCollection<FinishedDownloadItem> _finished = [];
    private CancellationTokenSource? _cts;
    private bool _runtimeOpInFlight;
    private readonly string _outputDir;
    private readonly string? _outputDirectoryWarning;
    private readonly bool _outputDirectoryAvailable;

    public DownloaderPage()
    {
        InitializeComponent();
        _runner  = App.Services.GetRequiredService<ISidecarRunner>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        _health = App.Services.GetRequiredService<ISidecarHealthService>();
        _toolManager = App.Services.GetRequiredService<IToolManager>();
        _postQueueActions = App.Services.GetRequiredService<IPostQueueActionService>();
        var options = App.Services.GetRequiredService<IOptions<ConverterXOptions>>().Value;
        var output = ResolveOutputDirectory(options.DefaultOutputDirectory);
        _outputDir = output.Path;
        _outputDirectoryWarning = output.Warning;
        _outputDirectoryAvailable = output.Available;

        QueueList.ItemsSource = _queue;
        FinishedList.ItemsSource = _finished;
        OutputDirectoryText.Text = BuildOutputDirectoryStatus();
        if (_outputDirectoryWarning is not null)
            StatusText.Text = _outputDirectoryWarning;
        UpdateUi();
        // Probe the cookie store on first paint so the user sees real status
        // instead of the placeholder "Checking..." string. Background-fired so
        // page activation isn't gated on the sidecar starting up.
        _ = RefreshCookieStatusAsync();
        _ = RefreshRuntimeHealthAsync();
    }

    private async Task RefreshRuntimeHealthAsync()
    {
        try
        {
            var report = await _health.EvaluateEngineAsync("streamkeep");
            var downloader = report.Requirements.FirstOrDefault(r => r.Name == "yt-dlp");
            var deno = report.Requirements.FirstOrDefault(r => r.Name.StartsWith("Deno", StringComparison.Ordinal));
            RuntimeHealthTitleText.Text = report.Summary;
            RuntimeHealthDetailText.Text = string.Join("  ", new[]
            {
                downloader is null ? null : AppLocalizer.Format($"yt-dlp: {downloader.Status}."),
                deno is null ? null : AppLocalizer.Format($"Deno: {deno.Status}. {(deno.Status == "Ready" ? deno.Detail : deno.Remediation)}"),
                report.Requirements.Any(r => r.Kind == "sidecar" && r.Status == "Missing")
                    ? report.Detail
                    : null,
            }.Where(text => !string.IsNullOrWhiteSpace(text)));
        }
        catch (Exception ex)
        {
            RuntimeHealthTitleText.Text = AppLocalizer.Get("Downloader health unavailable");
            RuntimeHealthDetailText.Text = ex.Message;
        }
        finally
        {
            RuntimeToolsButton.IsEnabled = !_runtimeOpInFlight;
        }
    }

    private async void RuntimeTools_Click(object sender, RoutedEventArgs e)
    {
        if (_runtimeOpInFlight)
            return;

        _runtimeOpInFlight = true;
        RuntimeToolsButton.IsEnabled = false;
        RuntimeToolsButton.Content = AppLocalizer.Get("Installing...");
        try
        {
            var results = new List<ToolDownloadResult>();
            string[] tools = ["yt-dlp", "deno"];
            for (var index = 0; index < tools.Length; index++)
            {
                var tool = tools[index];
                var ordinal = index + 1;
                var progress = new Progress<DownloadProgress>(update =>
                {
                    var percent = update.TotalBytes > 0
                        ? update.BytesDownloaded * 100.0 / update.TotalBytes
                        : 0;
                    RuntimeHealthTitleText.Text = AppLocalizer.Format($"Installing {tool}");
                    RuntimeHealthDetailText.Text = AppLocalizer.Format($"{ordinal}/{tools.Length} · {percent:F0}%");
                });
                results.Add(await _toolManager.DownloadToolAsync(tool, progress));
            }
            var failed = results.Where(result => !result.Success).ToList();
            if (failed.Count > 0)
            {
                RuntimeHealthTitleText.Text = AppLocalizer.Get("Runtime update incomplete");
                RuntimeHealthDetailText.Text = string.Join("  ", failed.Select(result =>
                    AppLocalizer.Format($"{result.ToolName}: {result.ErrorMessage}")));
            }
        }
        finally
        {
            _runtimeOpInFlight = false;
            RuntimeToolsButton.Content = AppLocalizer.Get("Install / update runtimes");
            await RefreshRuntimeHealthAsync();
        }
    }

    // ─── Cookie Auth (ROADMAP Item 9 UI completion) ─────────────────────────
    //
    // The DPAPI at-rest encryption layer shipped in iter-3 (commit b8058de).
    // These handlers expose the cookies-status / cookies-import / cookies-clear
    // ops on the streamkeep sidecar so the user can manage cookie auth
    // without touching %APPDATA%/StreamKeep manually.

    private bool _cookieOpInFlight;

    private async Task RefreshCookieStatusAsync()
    {
        if (_cookieOpInFlight) return;
        await RunCookieOpAsync(["cookies-status"], silentMessage: true);
    }

    private async void ImportCookiesFromBrowser_Click(object sender, RoutedEventArgs e)
    {
        var browser = SelectedTag(BrowserCombo, "chrome");
        await RunCookieOpAsync(["cookies-import", "--browser", browser]);
    }

    private async void ImportCookiesFromFile_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.Downloads,
        };
        picker.FileTypeFilter.Add(".txt");
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var file = await picker.PickSingleFileAsync();
        if (file is null) return;

        await RunCookieOpAsync(["cookies-import", "--file", file.Path]);
    }

    private async void ClearCookies_Click(object sender, RoutedEventArgs e)
    {
        if (!await PageDialogService.ConfirmClearAsync(
                this,
                "Clear cookie store?",
                "Delete the on-disk cookies and any process-cached plaintext temp file? You'll need to re-import to authenticate again."))
        {
            return;
        }
        await RunCookieOpAsync(["cookies-clear"]);
    }

    private async Task RunCookieOpAsync(IEnumerable<string> args, bool silentMessage = false)
    {
        if (_cookieOpInFlight) return;
        _cookieOpInFlight = true;
        SetCookieControlsEnabled(false);

        // Capture the most-recent cookie_status payload across all NDJSON events
        // so we can update the UI once after the sidecar exits.
        bool? present = null;
        bool? encrypted = null;
        long ageSeconds = -1;
        string? lastAction = null;
        string? lastMessage = null;

        try
        {
            await _runner.RunAsync(
                "streamkeep",
                args,
                progress: null,
                log: null,
                ct: default,
                onRawEvent: (evName, root) =>
                {
                    if (evName != "cookie_status") return;
                    if (root.TryGetProperty("present", out var pEl) && pEl.ValueKind is JsonValueKind.True or JsonValueKind.False)
                        present = pEl.GetBoolean();
                    if (root.TryGetProperty("encrypted", out var eEl) && eEl.ValueKind is JsonValueKind.True or JsonValueKind.False)
                        encrypted = eEl.GetBoolean();
                    if (root.TryGetProperty("age_seconds", out var aEl) && aEl.ValueKind == JsonValueKind.Number)
                        ageSeconds = aEl.GetInt64();
                    if (root.TryGetProperty("action", out var actEl) && actEl.ValueKind == JsonValueKind.String)
                        lastAction = actEl.GetString();
                    if (root.TryGetProperty("message", out var msgEl) && msgEl.ValueKind == JsonValueKind.String)
                        lastMessage = msgEl.GetString();
                });
        }
        finally
        {
            DispatcherQueue.TryEnqueue(() =>
            {
                ApplyCookieStatusToUi(present, encrypted, ageSeconds, lastAction,
                    silentMessage ? null : lastMessage);
                _cookieOpInFlight = false;
                SetCookieControlsEnabled(true);
            });
        }
    }

    private void SetCookieControlsEnabled(bool enabled)
    {
        BrowserCombo.IsEnabled = enabled;
        CookieImportBrowserButton.IsEnabled = enabled;
        CookieImportFileButton.IsEnabled = enabled;
        // Clear is gated on actual cookie presence — don't re-enable here; the
        // status apply step decides.
    }

    private void ApplyCookieStatusToUi(bool? present, bool? encrypted, long ageSeconds,
        string? action, string? message)
    {
        if (present is null)
        {
            // Sidecar didn't emit a cookie_status — likely missing streamkeep
            // package or build. Show the action message if we have one.
            CookieStatusText.Text = AppLocalizer.Get(
                "Cookie store unavailable. Build the streamkeep sidecar (`pwsh tools/streamkeep/build.ps1`).");
            CookieClearButton.IsEnabled = false;
        }
        else if (present == true)
        {
            var enc = encrypted == true ? "encrypted at rest (DPAPI)" : "plaintext (legacy)";
            var age = FormatCookieAge(ageSeconds);
            CookieStatusText.Text = AppLocalizer.Format($"Cookies imported · {enc} · {age}");
            CookieClearButton.IsEnabled = true;
        }
        else
        {
            CookieStatusText.Text = AppLocalizer.Get(
                "No cookies imported. Sites that need login (premium, age-gated, region-locked) won't work.");
            CookieClearButton.IsEnabled = false;
        }

        if (string.IsNullOrWhiteSpace(message))
        {
            CookieMessageText.Visibility = Visibility.Collapsed;
            CookieMessageText.Text = "";
        }
        else
        {
            // Distinguish failure vs success in the inline message.
            var prefix = action switch
            {
                "imported"      => "✓ ",
                "cleared"       => "✓ ",
                "import_failed" => "✗ ",
                "clear_failed"  => "✗ ",
                _ => "",
            };
            CookieMessageText.Text = prefix + message;
            CookieMessageText.Visibility = Visibility.Visible;
        }
    }

    private static string FormatCookieAge(long ageSeconds)
    {
        if (ageSeconds < 0) return "no timestamp";
        if (ageSeconds < 60) return $"{ageSeconds}s ago";
        if (ageSeconds < 3600) return $"{ageSeconds / 60}m ago";
        if (ageSeconds < 86400) return $"{ageSeconds / 3600}h ago";
        return $"{ageSeconds / 86400}d ago";
    }

    private void UrlBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        AddUrlButton.IsEnabled = SplitUrls(UrlBox.Text).Any();
    }

    private async void Paste_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var pkg = Clipboard.GetContent();
            if (!pkg.Contains(StandardDataFormats.Text))
            {
                StatusText.Text = AppLocalizer.Get("Clipboard does not contain text.");
                return;
            }

            var text = await pkg.GetTextAsync();
            if (string.IsNullOrWhiteSpace(text))
            {
                StatusText.Text = AppLocalizer.Get("Clipboard text is empty.");
                return;
            }

            text = text.Trim();
            var urls = SplitUrls(text).ToList();
            if (urls.Count > 1)
            {
                AddUrls(urls);
                UrlBox.Text = "";
            }
            else
            {
                UrlBox.Text = text;
            }
        }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Get("Clipboard could not be read. Try again.");
            Debug.WriteLine($"Downloader clipboard read failed: {ex.GetType().Name}: {ex.Message}");
        }
    }

    private void AddUrl_Click(object sender, RoutedEventArgs e)
    {
        var urls = SplitUrls(UrlBox.Text).ToList();
        AddUrls(urls);
        if (urls.Count > 0)
            UrlBox.Text = "";
    }

    private void AddUrls(IEnumerable<string> urls)
    {
        var added = 0;
        foreach (var url in urls)
        {
            if (_queue.Any(j => j.Url.Equals(url, StringComparison.OrdinalIgnoreCase)))
                continue;

            var item = CreateJob(url);
            _queue.Add(item);
            added++;
        }

        StatusText.Text = added == 0
            ? AppLocalizer.Get("No new URLs were added.")
            : AppLocalizer.Format($"Added {added} download jobs.");
        UpdateUi();
    }

    private DownloadJobItem CreateJob(string url)
    {
        var quality = SelectedTag(QualityCombo, "best");
        var format = SelectedTag(OutputFormatCombo, "mp4");
        var audioOnly = AudioOnlyCheck.IsChecked == true;
        var subtitles = SubtitlesCheck.IsChecked == true;
        var sponsorBlock = SponsorBlockCheck.IsChecked == true;
        var title = TryBuildTitle(url);
        var mode = audioOnly ? "MP3 audio" : $"{format.ToUpperInvariant()} {QualityLabel(quality)}";
        if (subtitles)
            mode += " + subtitles";
        if (sponsorBlock)
            mode += " + sponsor-skip";

        return new DownloadJobItem
        {
            Url = url,
            Title = title,
            Quality = quality,
            Format = format,
            AudioOnly = audioOnly,
            EmbedSubtitles = subtitles,
            SponsorBlock = sponsorBlock,
            OptionSummary = mode,
            StatusText = "Queued",
            Progress = 0,
        };
    }

    private void RemoveQueued_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
            return;

        if (sender is Button button && button.Tag is DownloadJobItem item)
        {
            _queue.Remove(item);
            UpdateUi();
        }
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        UpdateUi();
    }

    private async void ClearQueue_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
            return;

        if (_queue.Count == 0)
            return;

        if (!await PageDialogService.ConfirmClearAsync(
                this,
                "Clear download queue?",
                $"Remove {_queue.Count} queued URL(s)? Finished downloads stay available."))
        {
            return;
        }

        _queue.Clear();
        UpdateUi();
    }

    private void OpenOutput_Click(object sender, RoutedEventArgs e) => OpenContainingFolder(_outputDir);

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string path)
            OpenContainingFolder(path);
    }

    private async void Download_Click(object sender, RoutedEventArgs e)
    {
        var pending = _queue.Where(j => !j.IsComplete).ToList();
        if (pending.Count == 0)
            return;

        if (!_outputDirectoryAvailable)
        {
            StatusText.Text = _outputDirectoryWarning ??
                AppLocalizer.Get("Download output directory is unavailable. Choose a writable location in Settings.");
            return;
        }

        try
        {
            Directory.CreateDirectory(_outputDir);
        }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Format($"Download output directory is unavailable: {ex.Message}");
            return;
        }

        _cts = new CancellationTokenSource();
        DownloadButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        ClearQueueButton.IsEnabled = false;
        StatusText.Text = AppLocalizer.Format($"Downloading {pending.Count} queued jobs...");

        var completed = 0;
        var failed = 0;
        var batchStartedAt = DateTime.UtcNow;
        var completionItems = new List<QueueCompletionItem>();
        try
        {
            foreach (var job in pending)
            {
                if (_cts.IsCancellationRequested)
                    break;

                // ROADMAP Item 60 — keep the active job visible in long queues.
                try { QueueList.ScrollIntoView(job); } catch { /* virtualization race; ignore */ }

                job.StatusText = "Resolving";
                job.Progress = 0;
                job.LogPreview = "";

                var args = BuildArgs(job);
                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    job.Progress = p.Percent;
                    job.StatusText = $"{p.Percent:F1}% - {p.Stage}";
                }));
                var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
                {
                    job.LogPreview = $"[{l.Level}] {l.Message}";
                }));

                SidecarResult result;
                var startedAt = DateTime.UtcNow;
                try
                {
                    result = await _runner.RunAsync("streamkeep", args, progress, log, _cts.Token);
                }
                catch (OperationCanceledException)
                {
                    result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user.", -1);
                }

                job.IsComplete = true;
                if (result.Success)
                {
                    completed++;
                    job.Progress = 100;
                    job.StatusText = "Done";
                }
                else
                {
                    failed++;
                    job.StatusText = result.ErrorCode == "cancelled" ? "Cancelled" : "Failed";
                }

                AddFinishedItem(job, result);
                completionItems.Add(new QueueCompletionItem
                {
                    Source = job.Url,
                    Output = result.OutputPath,
                    Status = result.ErrorCode == "cancelled"
                        ? QueueCompletionItemStatus.Cancelled
                        : result.Success
                            ? QueueCompletionItemStatus.Succeeded
                            : QueueCompletionItemStatus.Failed,
                    Message = result.ErrorMessage,
                });

                // Persist to History so the dashboard tracks downloads, just
                // like Compressor and the preset pages do. Skip user-cancelled
                // jobs to keep the failed count meaningful.
                if (result.ErrorCode != "cancelled")
                {
                    _ = _history.LogAsync(new HistoryRecord
                    {
                        Timestamp       = startedAt,
                        Engine          = "streamkeep",
                        Action          = "download",
                        SourcePath      = job.Url,
                        OutputPath      = result.Success ? result.OutputPath : null,
                        SourceBytes     = null,
                        OutputBytes     = result.Success ? result.SizeBytes : null,
                        DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds,
                        Success         = result.Success,
                        ErrorCode       = result.ErrorCode,
                        ErrorMessage    = result.ErrorMessage,
                        Profile         = job.OptionSummary,
                    });
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

        StatusText.Text = AppLocalizer.Format($"Downloads finished: {completed} succeeded, {failed} failed.");
        QueuePivot.SelectedIndex = _finished.Count > 0 ? 1 : 0;
        CancelButton.IsEnabled = false;
        UpdateUi();

        foreach (var unstarted in pending.Skip(completionItems.Count))
        {
            completionItems.Add(new QueueCompletionItem
            {
                Source = unstarted.Url,
                Status = QueueCompletionItemStatus.Cancelled,
                Message = AppLocalizer.Get("Not started because the queue was cancelled."),
            });
        }
        if (completionItems.Count > 0)
        {
            var actionResult = await _postQueueActions.ExecuteAsync(new QueueCompletionSummary
            {
                Workflow = "Downloader",
                StartedUtc = batchStartedAt,
                CompletedUtc = DateTime.UtcNow,
                Items = completionItems,
            });
            if (actionResult.Action != QueueCompletionAction.None && !actionResult.Executed)
                StatusText.Text = actionResult.Message;
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        CancelButton.IsEnabled = false;
        StatusText.Text = AppLocalizer.Get("Cancelling active download...");
    }

    private List<string> BuildArgs(DownloadJobItem job)
    {
        var args = new List<string>
        {
            "download",
            "--url", job.Url,
            "--output-dir", _outputDir,
            "--merge-format", job.Format,
            "--merge",
        };

        if (job.Quality == "best")
            args.AddRange(["--format", "bv*+ba/b"]);
        else
            args.AddRange(["--format", $"bv*[height<={job.Quality}]+ba/b[height<={job.Quality}]"]);

        if (job.AudioOnly)
            args.Add("--audio-only");

        if (job.EmbedSubtitles)
            args.AddRange(["--subtitles", "en", "--embed-subtitles"]);

        if (job.SponsorBlock)
            args.AddRange(["--sponsorblock", "remove"]);

        return args;
    }

    private string BuildOutputDirectoryStatus()
    {
        var location = AppLocalizer.Format($"Downloads will be saved to: {_outputDir}");
        return _outputDirectoryWarning is null
            ? location
            : AppLocalizer.Format($"{_outputDirectoryWarning} {location}");
    }

    private static (string Path, string? Warning, bool Available) ResolveOutputDirectory(
        string? configuredDirectory)
    {
        var candidates = new List<(string Path, string Label)>();
        if (!string.IsNullOrWhiteSpace(configuredDirectory))
            candidates.Add((configuredDirectory.Trim(), "the configured default output directory"));

        var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (!string.IsNullOrWhiteSpace(userProfile))
        {
            candidates.Add((
                Path.Combine(userProfile, "Downloads", "UniversalConverterX"),
                "the Downloads output directory"));
        }

        var tempDirectory = Path.Combine(Path.GetTempPath(), "UniversalConverterX-Downloads");
        candidates.Add((tempDirectory, "the temporary output directory"));

        var failures = new List<string>();
        for (var index = 0; index < candidates.Count; index++)
        {
            var candidate = candidates[index];
            try
            {
                var fullPath = Path.GetFullPath(Environment.ExpandEnvironmentVariables(candidate.Path));
                Directory.CreateDirectory(fullPath);
                if (!Directory.Exists(fullPath))
                {
                    failures.Add($"Could not create {candidate.Label}.");
                    continue;
                }

                var failureSummary = string.Join(" ", failures);
                string? warning = failures.Count == 0 && index == 0
                    ? null
                    : AppLocalizer.Format($"{failureSummary} Using {candidate.Label}: {fullPath}.");
                return (fullPath, warning, true);
            }
            catch (Exception ex)
            {
                failures.Add(AppLocalizer.Format($"{candidate.Label} unavailable: {ex.Message}."));
            }
        }

        var fallback = candidates.LastOrDefault().Path;
        var unavailable = string.IsNullOrWhiteSpace(fallback)
            ? AppLocalizer.Get("No writable download output directory is available.")
            : AppLocalizer.Format($"No writable download output directory is available. Last tried: {fallback}.");
        return (fallback ?? tempDirectory, unavailable, false);
    }

    private void AddFinishedItem(DownloadJobItem job, SidecarResult result)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush = (Brush)Application.Current.Resources["AccentRedBrush"];
        var details = result.Success
            ? $"{job.OptionSummary} - {(result.SizeBytes is long sz ? FormatSize(sz) : "saved")}"
            : result.ErrorMessage ?? "Download failed";

        _finished.Insert(0, new FinishedDownloadItem
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

        while (_finished.Count > FinishedCap)
            _finished.RemoveAt(_finished.Count - 1);
    }

    private void UpdateUi()
    {
        var hasQueued = _queue.Count > 0;
        var hasFinished = _finished.Count > 0;
        QueueEmpty.Visibility = hasQueued ? Visibility.Collapsed : Visibility.Visible;
        QueueList.Visibility = hasQueued ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;

        var pending = _queue.Count(j => !j.IsComplete);
        QueueSummaryText.Text = AppLocalizer.Format($"{pending} pending / {_finished.Count} finished");
        DownloadButton.IsEnabled = pending > 0 && _cts is null;
        ClearQueueButton.IsEnabled = hasQueued && _cts is null;
        AddUrlButton.IsEnabled = SplitUrls(UrlBox.Text).Any();

        if (_cts is null && string.IsNullOrWhiteSpace(StatusText.Text))
            StatusText.Text = AppLocalizer.Get("Queue URLs to download video, audio, and subtitles locally.");
    }

    private static IEnumerable<string> SplitUrls(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
            yield break;

        var parts = text
            .Split(['\r', '\n', '\t', ' '], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(LooksLikeUrl)
            .Distinct(StringComparer.OrdinalIgnoreCase);

        foreach (var part in parts)
            yield return part;
    }

    private static string SelectedTag(ComboBox cb, string fallback)
        => (cb.SelectedItem as ComboBoxItem)?.Tag as string ?? fallback;

    private static bool LooksLikeUrl(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return false;
        var t = text.Trim();
        return t.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
            || t.StartsWith("https://", StringComparison.OrdinalIgnoreCase);
    }

    private static string TryBuildTitle(string url)
    {
        if (Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            var host = uri.Host.Replace("www.", "", StringComparison.OrdinalIgnoreCase);
            var path = uri.AbsolutePath.Trim('/').Split('/').LastOrDefault();
            return string.IsNullOrWhiteSpace(path) ? host : $"{host} / {Uri.UnescapeDataString(path)}";
        }

        return url;
    }

    private static string QualityLabel(string quality)
        => quality == "best" ? "Highest available" : $"{quality}p";

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
            var startInfo = Directory.Exists(path)
                ? new ProcessStartInfo
                {
                    FileName = folder,
                    UseShellExecute = true,
                }
                : new ProcessStartInfo("explorer.exe", $"/select,\"{path}\"")
                {
                    UseShellExecute = true,
                };
            Process.Start(startInfo);
        }
        catch
        {
            // Convenience action only; preserve downloader state if Explorer fails.
        }
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

public sealed class DownloadJobItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _logPreview = "";
    private bool _isComplete;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Url { get; set; } = "";
    public string Title { get; set; } = "";
    public string Quality { get; set; } = "best";
    public string Format { get; set; } = "mp4";
    public bool AudioOnly { get; set; }
    public bool EmbedSubtitles { get; set; }
    public bool SponsorBlock { get; set; }
    public string OptionSummary { get; set; } = "";

    public bool IsComplete
    {
        get => _isComplete;
        set => SetProperty(ref _isComplete, value);
    }

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

    public string LogPreview
    {
        get => _logPreview;
        set => SetProperty(ref _logPreview, value);
    }

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value))
            return;

        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}

public sealed class FinishedDownloadItem
{
    public string Title { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush AccentBrush { get; set; } = null!;
    public bool CanOpenFolder => Success && !string.IsNullOrWhiteSpace(OutputPath);
}
