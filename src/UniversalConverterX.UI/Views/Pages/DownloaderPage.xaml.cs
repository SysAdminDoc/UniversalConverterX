using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class DownloaderPage : Page
{
    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<DownloadJobItem> _queue = [];
    private readonly ObservableCollection<FinishedDownloadItem> _finished = [];
    private CancellationTokenSource? _cts;
    private readonly string _outputDir;

    public DownloaderPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _outputDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "Downloads", "UniversalConverterX");
        Directory.CreateDirectory(_outputDir);

        QueueList.ItemsSource = _queue;
        FinishedList.ItemsSource = _finished;
        UpdateUi();
    }

    private void UrlBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        AddUrlButton.IsEnabled = SplitUrls(UrlBox.Text).Any();
    }

    private void Paste_Click(object sender, RoutedEventArgs e)
    {
        var pkg = Clipboard.GetContent();
        if (!pkg.Contains(StandardDataFormats.Text))
            return;

        _ = pkg.GetTextAsync().AsTask().ContinueWith(t =>
        {
            DispatcherQueue.TryEnqueue(() =>
            {
                if (string.IsNullOrWhiteSpace(t.Result))
                    return;

                var text = t.Result.Trim();
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
            });
        });
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
            ? "No new URLs were added."
            : $"Added {added} download jobs.";
        UpdateUi();
    }

    private DownloadJobItem CreateJob(string url)
    {
        var quality = SelectedTag(QualityCombo, "best");
        var format = SelectedTag(OutputFormatCombo, "mp4");
        var audioOnly = AudioOnlyCheck.IsChecked == true;
        var subtitles = SubtitlesCheck.IsChecked == true;
        var title = TryBuildTitle(url);
        var mode = audioOnly ? "MP3 audio" : $"{format.ToUpperInvariant()} {QualityLabel(quality)}";
        if (subtitles)
            mode += " + subtitles";

        return new DownloadJobItem
        {
            Url = url,
            Title = title,
            Quality = quality,
            Format = format,
            AudioOnly = audioOnly,
            EmbedSubtitles = subtitles,
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

    private void ClearQueue_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null)
            return;

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

        _cts = new CancellationTokenSource();
        DownloadButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        ClearQueueButton.IsEnabled = false;
        StatusText.Text = $"Downloading {pending.Count} queued jobs...";

        var completed = 0;
        var failed = 0;
        try
        {
            foreach (var job in pending)
            {
                if (_cts.IsCancellationRequested)
                    break;

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

                if (result.ErrorCode == "cancelled")
                    break;
            }
        }
        finally
        {
            _cts.Dispose();
            _cts = null;
        }

        StatusText.Text = $"Downloads finished: {completed} succeeded, {failed} failed.";
        QueuePivot.SelectedIndex = _finished.Count > 0 ? 1 : 0;
        CancelButton.IsEnabled = false;
        UpdateUi();
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        CancelButton.IsEnabled = false;
        StatusText.Text = "Cancelling active download...";
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

        return args;
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
        QueueSummaryText.Text = $"{pending} pending / {_finished.Count} finished";
        DownloadButton.IsEnabled = pending > 0 && _cts is null;
        ClearQueueButton.IsEnabled = hasQueued && _cts is null;
        AddUrlButton.IsEnabled = SplitUrls(UrlBox.Text).Any();

        if (_cts is null && string.IsNullOrWhiteSpace(StatusText.Text))
            StatusText.Text = "Queue URLs to download video, audio, and subtitles locally.";
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
        => quality == "best" ? "Best" : $"{quality}p";

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
