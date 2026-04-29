using System.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class DownloaderPage : Page
{
    private readonly ISidecarRunner _runner;
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
    }

    private void UrlBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        DownloadButton.IsEnabled = LooksLikeUrl(UrlBox.Text);
    }

    private void Paste_Click(object sender, RoutedEventArgs e)
    {
        var pkg = Clipboard.GetContent();
        if (pkg.Contains(StandardDataFormats.Text))
        {
            _ = pkg.GetTextAsync().AsTask().ContinueWith(t =>
            {
                DispatcherQueue.TryEnqueue(() =>
                {
                    if (!string.IsNullOrWhiteSpace(t.Result))
                        UrlBox.Text = t.Result.Trim();
                });
            });
        }
    }

    private void OpenOutput_Click(object sender, RoutedEventArgs e)
    {
        try { Process.Start("explorer.exe", _outputDir); } catch { /* swallow */ }
    }

    private async void Download_Click(object sender, RoutedEventArgs e)
    {
        var url = UrlBox.Text.Trim();
        if (!LooksLikeUrl(url)) return;

        QueueEmpty.Visibility = Visibility.Collapsed;
        ActiveJob.Visibility = Visibility.Visible;
        JobUrl.Text = url;
        JobStatus.Text = "Resolving…";
        JobProgress.Value = 0;
        JobDetail.Text = "";
        JobLog.Text = "";
        StatusText.Text = "";
        DownloadButton.IsEnabled = false;
        CancelButton.IsEnabled = true;

        var args = new List<string>
        {
            "download",
            "--url", url,
            "--output-dir", _outputDir,
            "--merge-format", SelectedTag(OutputFormatCombo, "mp4"),
            "--merge",
        };

        var quality = SelectedTag(QualityCombo, "best");
        if (quality == "best")
            args.AddRange(new[] { "--format", "bv*+ba/b" });
        else
            args.AddRange(new[] { "--format", $"bv*[height<={quality}]+ba/b[height<={quality}]" });

        if (AudioOnlyCheck.IsChecked == true)
            args.Add("--audio-only");

        if (SubtitlesCheck.IsChecked == true)
            args.AddRange(new[] { "--subtitles", "en", "--embed-subtitles" });

        _cts = new CancellationTokenSource();
        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            JobProgress.Value = p.Percent;
            JobStatus.Text = $"{p.Percent:F1}% — {p.Stage}";
            JobDetail.Text = p.EtaSeconds is int eta and >= 0
                ? $"ETA {TimeSpan.FromSeconds(eta):mm\\:ss}"
                : "";
        }));
        var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
        {
            JobLog.Text += $"[{l.Level}] {l.Message}\n";
        }));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync("streamkeep", args, progress, log, _cts.Token);
        }
        finally
        {
            _cts.Dispose();
            _cts = null;
        }

        CancelButton.IsEnabled = false;
        DownloadButton.IsEnabled = LooksLikeUrl(UrlBox.Text);

        if (result.Success)
        {
            JobProgress.Value = 100;
            JobStatus.Text = "Done";
            JobDetail.Text = result.SizeBytes is long sz ? FormatSize(sz) : "";
            StatusText.Text = $"Saved to {result.OutputPath}";
        }
        else
        {
            JobStatus.Text = "Failed";
            JobDetail.Text = result.ErrorCode is null ? "" : $"({result.ErrorCode})";
            StatusText.Text = result.ErrorMessage ?? "Download failed.";
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        CancelButton.IsEnabled = false;
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

    private static string FormatSize(long bytes)
    {
        string[] s = ["B", "KB", "MB", "GB", "TB"];
        int i = 0;
        double v = bytes;
        while (v >= 1024 && i < s.Length - 1) { v /= 1024; i++; }
        return $"{v:F1} {s[i]}";
    }
}
