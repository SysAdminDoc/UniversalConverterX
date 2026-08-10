using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

/// <summary>
/// Rips titles from an unprotected DVD VIDEO_TS structure to MP4/MKV via the
/// dvdrip sidecar. Commercial CSS-encrypted discs are never decrypted; the
/// sidecar reports them as unreadable and the page surfaces that.
/// </summary>
public sealed partial class DvdRipPage : Page
{
    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<DvdTitle> _titles = [];
    private string? _videoTsPath;
    private string? _outputPath;
    private CancellationTokenSource? _cts;

    public DvdRipPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        TitleList.ItemsSource = _titles;
    }

    // ── Input ────────────────────────────────────────────────────────────────

    private async void Open_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.ComputerFolder };
        picker.FileTypeFilter.Add("*");
        var handle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, handle);
        var folder = await picker.PickSingleFolderAsync();
        if (folder is not null)
            await ScanAsync(folder.Path);
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Scan VIDEO_TS");
        e.DragUIOverride.IsCaptionVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        var items = await DropSnapshotHelper.TrySnapshotDropAsync(e);
        if (items is null)
            return;
        var folder = items.OfType<StorageFolder>().FirstOrDefault();
        if (folder is not null)
            await ScanAsync(folder.Path);
    }

    private async Task ScanAsync(string path)
    {
        if (_cts is not null)
            return;
        if (_runner.Locate("dvdrip") is null)
        {
            StatusText.Text = AppLocalizer.Get("The dvdrip engine was not found. Build it with tools/dvdrip/build.ps1.");
            return;
        }

        _titles.Clear();
        _videoTsPath = path;
        StatusText.Text = AppLocalizer.Format($"Scanning {path}…");

        var found = new List<DvdTitle>();
        string? errorMessage = null;
        var result = await _runner.RunAsync(
            "dvdrip",
            ["probe", "--input", path],
            onRawEvent: (name, payload) =>
            {
                if (name == "title")
                {
                    var index = payload.TryGetProperty("index", out var i) && i.ValueKind == JsonValueKind.Number ? i.GetInt32() : 0;
                    var readable = payload.TryGetProperty("readable", out var r) && r.ValueKind == JsonValueKind.True;
                    var parts = payload.TryGetProperty("parts", out var p) && p.ValueKind == JsonValueKind.Number ? p.GetInt32() : 0;
                    double? duration = payload.TryGetProperty("duration_seconds", out var d) && d.ValueKind == JsonValueKind.Number ? d.GetDouble() : null;
                    long size = payload.TryGetProperty("size_bytes", out var s) && s.ValueKind == JsonValueKind.Number && s.TryGetInt64(out var sv) ? sv : 0;
                    found.Add(new DvdTitle
                    {
                        Index = index,
                        Readable = readable,
                        TitleLabel = $"Title {index}",
                        Summary = readable
                            ? $"{parts} part(s) · {FormatSize(size)}"
                            : "Unreadable — likely CSS-protected or damaged",
                        Duration = duration is double sec ? FormatTime(sec) : "—",
                    });
                }
                else if (name == "error" && payload.TryGetProperty("message", out var m) && m.ValueKind == JsonValueKind.String)
                {
                    errorMessage = m.GetString();
                }
            });

        foreach (var title in found)
            _titles.Add(title);

        var hasTitles = _titles.Any(t => t.Readable);
        EmptyState.Visibility = _titles.Count > 0 ? Visibility.Collapsed : Visibility.Visible;
        TitleList.Visibility = _titles.Count > 0 ? Visibility.Visible : Visibility.Collapsed;

        if (!result.Success && _titles.Count == 0)
        {
            StatusText.Text = errorMessage
                ?? AppLocalizer.Get("No ripable titles were found. Point at a VIDEO_TS folder.");
            return;
        }

        StatusText.Text = hasTitles
            ? AppLocalizer.Format($"Found {_titles.Count(t => t.Readable)} ripable title(s). Select one, choose an output, then rip.")
            : AppLocalizer.Get("No readable titles — this disc may be CSS-protected, which is not supported.");
    }

    // ── Selection + output ───────────────────────────────────────────────────

    private void Title_SelectionChanged(object sender, SelectionChangedEventArgs e) => UpdateRipEnabled();

    private void Mode_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (CrfBox is not null)
            CrfBox.IsEnabled = SelectedMode() != "copy";
    }

    private string SelectedMode() =>
        (ModeCombo?.SelectedItem as ComboBoxItem)?.Tag as string ?? "h264";

    private async void ChooseOutput_Click(object sender, RoutedEventArgs e)
    {
        if (TitleList.SelectedItem is not DvdTitle title)
            return;
        var mode = SelectedMode();
        var extension = mode == "copy" ? ".mkv" : ".mp4";
        var picker = new FileSavePicker { SuggestedStartLocation = PickerLocationId.VideosLibrary };
        picker.FileTypeChoices.Add(mode == "copy" ? "Matroska" : "MP4 video", [extension]);
        picker.SuggestedFileName = $"DVD_Title_{title.Index:00}";
        var handle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, handle);
        var file = await picker.PickSaveFileAsync();
        if (file is not null)
        {
            _outputPath = file.Path;
            OutputBox.Text = file.Path;
            UpdateRipEnabled();
        }
    }

    private void UpdateRipEnabled()
    {
        RipButton.IsEnabled = _cts is null
            && _videoTsPath is not null
            && TitleList.SelectedItem is DvdTitle { Readable: true };
    }

    private string DefaultOutputPath(DvdTitle title, string mode)
    {
        var extension = mode == "copy" ? ".mkv" : ".mp4";
        var directory = Path.GetDirectoryName(_videoTsPath!.TrimEnd('\\', '/')) ?? Path.GetTempPath();
        return Path.Combine(directory, $"DVD_Title_{title.Index:00}{extension}");
    }

    // ── Rip ──────────────────────────────────────────────────────────────────

    private async void Rip_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null || _videoTsPath is null || TitleList.SelectedItem is not DvdTitle title)
            return;

        var mode = SelectedMode();
        var output = _outputPath ?? DefaultOutputPath(title, mode);
        var crf = (int)Math.Clamp(CrfBox.Value is double.NaN ? 20 : CrfBox.Value, 0, 51);

        var args = new List<string>
        {
            "rip",
            "--input", _videoTsPath,
            "--output", output,
            "--title", title.Index.ToString(CultureInfo.InvariantCulture),
            "--mode", mode,
        };
        if (mode != "copy")
            args.AddRange(["--crf", crf.ToString(CultureInfo.InvariantCulture)]);

        _cts = new CancellationTokenSource();
        RipButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        RipProgress.Visibility = Visibility.Visible;
        RipProgress.Value = 0;
        StatusText.Text = AppLocalizer.Format($"Ripping Title {title.Index}…");

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            RipProgress.Value = Math.Clamp(p.Percent, 0, 100);
            StatusText.Text = AppLocalizer.Format($"Ripping Title {title.Index}… {p.Percent:F0}% — {p.Stage}");
        }));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync("dvdrip", args, progress, null, _cts.Token);
        }
        catch (OperationCanceledException)
        {
            result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user", 130);
        }
        finally
        {
            _cts = null;
            CancelButton.IsEnabled = false;
            RipProgress.Visibility = Visibility.Collapsed;
            UpdateRipEnabled();
        }

        StatusText.Text = result.Success
            ? AppLocalizer.Format($"Saved Title {title.Index} to {output}.")
            : result.ErrorCode == "cancelled"
                ? AppLocalizer.Get("Rip cancelled.")
                : AppLocalizer.Format($"Rip failed: {result.ErrorMessage}");
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => _cts?.Cancel();

    private static string FormatTime(double seconds)
    {
        if (seconds < 0) seconds = 0;
        var span = TimeSpan.FromSeconds(seconds);
        return span.Hours > 0
            ? $"{(int)span.TotalHours}:{span.Minutes:00}:{span.Seconds:00}"
            : $"{span.Minutes:00}:{span.Seconds:00}";
    }

    private static string FormatSize(long bytes)
    {
        string[] units = ["B", "KB", "MB", "GB", "TB"];
        double size = bytes;
        var unit = 0;
        while (size >= 1024 && unit < units.Length - 1)
        {
            size /= 1024;
            unit++;
        }
        return $"{size:0.#} {units[unit]}";
    }

    private sealed class DvdTitle
    {
        public int Index { get; init; }
        public bool Readable { get; init; }
        public string TitleLabel { get; init; } = "";
        public string Summary { get; init; } = "";
        public string Duration { get; init; } = "";
    }
}
