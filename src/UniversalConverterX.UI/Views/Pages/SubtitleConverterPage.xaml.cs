using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class SubFileItem : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;
    public string Path { get; init; } = "";
    public string FileName => System.IO.Path.GetFileName(Path);

    private string _statusText = "Pending";
    public string StatusText
    {
        get => _statusText;
        set { if (_statusText != value) { _statusText = value; PropertyChanged?.Invoke(this, new(nameof(StatusText))); } }
    }
}

public sealed partial class SubtitleConverterPage : Page
{
    private static readonly string[] SubExts =
        [".srt", ".vtt", ".ass", ".ssa", ".sub", ".tmp"];

    // Broadcast Scenarist captions and video containers are handled by the
    // ccextract sidecar (FFmpeg) instead of subconvert (pysubs2): SCC is read
    // and decoded to text, and video files have their embedded caption track
    // extracted. ccextract writes text formats only (srt/vtt/ass).
    private static readonly string[] CaptionExts = [".scc"];
    private static readonly string[] VideoExts =
        [".mp4", ".mkv", ".mov", ".m4v", ".ts", ".mts", ".m2ts", ".webm", ".avi"];
    private static readonly string[] CcExtractFormats = ["srt", "vtt", "ass"];

    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly ObservableCollection<SubFileItem> _files = [];
    private string? _outputDir;

    public SubtitleConverterPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        FilesList.ItemsSource = _files;
    }

    private async void AddFiles_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        foreach (var ext in SubExts.Concat(CaptionExts).Concat(VideoExts))
            picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;
        foreach (var f in files)
        {
            if (!_files.Any(x => x.Path == f.Path))
                _files.Add(new SubFileItem { Path = f.Path });
        }
        UpdateUi();
    }

    private async void BrowseOutputDir_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
        picker.FileTypeFilter.Add("*");
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var folder = await picker.PickSingleFolderAsync();
        if (folder is null) return;
        _outputDir = folder.Path;
        OutputDirBox.Text = folder.Path;
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button b && b.Tag is SubFileItem item)
        {
            _files.Remove(item);
            UpdateUi();
        }
    }

    private void UpdateUi()
    {
        var has = _files.Count > 0;
        EmptyState.Visibility = has ? Visibility.Collapsed : Visibility.Visible;
        FilesScroll.Visibility = has ? Visibility.Visible : Visibility.Collapsed;
        ConvertButton.IsEnabled = has;
    }

    private async void Convert_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0) return;
        ConvertButton.IsEnabled = false;
        WorkProgress.Value = 0;
        foreach (var f in _files) f.StatusText = "Pending";

        var fmt = (FormatCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "srt";
        var enc = (EncodingCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "utf-8";
        var outEnc = (OutEncodingCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "utf-8";
        var outDir = string.IsNullOrEmpty(_outputDir)
            ? System.IO.Path.GetDirectoryName(_files[0].Path) ?? Environment.CurrentDirectory
            : _outputDir;
        try { Directory.CreateDirectory(outDir); }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Format($"Output folder unavailable: {ex.Message}");
            ConvertButton.IsEnabled = true;
            return;
        }

        // SCC files and video containers go through ccextract (FFmpeg); plain
        // subtitle files stay on the subconvert (pysubs2) batch path.
        bool IsCaptionSource(SubFileItem f)
        {
            var ext = System.IO.Path.GetExtension(f.Path).ToLowerInvariant();
            return CaptionExts.Contains(ext) || VideoExts.Contains(ext);
        }
        var ccFiles = _files.Where(IsCaptionSource).ToList();
        var subFiles = _files.Where(f => !IsCaptionSource(f)).ToList();

        if (ccFiles.Count > 0)
            await ExtractCaptionsAsync(ccFiles, fmt, outDir);

        if (subFiles.Count == 0)
        {
            StatusText.Text = AppLocalizer.Format($"Done -- {ccFiles.Count} caption source(s) -> .{fmt}.");
            WorkProgress.Value = 100;
            ConvertButton.IsEnabled = true;
            return;
        }

        var args = new List<string>
        {
            "convert",
            "--output-dir", outDir,
            "--format", fmt,
            "--encoding", enc,
            "--output-encoding", outEnc,
        };
        if (Math.Abs(ShiftMsBox.Value) >= 1)
            args.AddRange(["--shift-ms", ((int)ShiftMsBox.Value).ToString(CultureInfo.InvariantCulture)]);
        if (!double.IsNaN(FpsInBox.Value) && !double.IsNaN(FpsOutBox.Value)
            && FpsInBox.Value > 0 && FpsOutBox.Value > 0)
        {
            args.AddRange(["--fps-in", FpsInBox.Value.ToString("0.###", CultureInfo.InvariantCulture)]);
            args.AddRange(["--fps-out", FpsOutBox.Value.ToString("0.###", CultureInfo.InvariantCulture)]);
        }
        args.Add("--input");
        args.AddRange(subFiles.Select(f => f.Path));

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            WorkProgress.Value = p.Percent;
            StatusText.Text = AppLocalizer.Format($"{p.Stage} -- {p.Percent:F0}%");
        }));

        var startedAt = DateTime.UtcNow;
        StatusText.Text = AppLocalizer.Get("Converting...");
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(15));
        var result = await _runner.RunAsync(
            "subconvert", args, progress, null, cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName != "subtitle") return;
                if (!root.TryGetProperty("input", out var ip)) return;
                var match = _files.FirstOrDefault(f => f.Path == ip.GetString());
                if (match is not null)
                {
                    var entries = root.TryGetProperty("entries", out var en) ? en.GetInt32() : 0;
                    match.StatusText = $"Done ({entries} cues)";
                }
            }));

        if (result.ErrorCode == "sidecar_not_found")
            StatusText.Text = AppLocalizer.Get("subconvert sidecar not built. Run pwsh tools/subconvert/build.ps1.");
        else if (result.Success)
        {
            StatusText.Text = AppLocalizer.Format($"Done -- {subFiles.Count} subtitle(s) -> .{fmt}.");
            WorkProgress.Value = 100;
            foreach (var f in subFiles)
            {
                _ = _history.LogAsync(new HistoryRecord
                {
                    Timestamp = startedAt,
                    Engine = "subconvert",
                    Action = "convert",
                    SourcePath = f.Path,
                    OutputPath = System.IO.Path.Combine(outDir,
                        System.IO.Path.GetFileNameWithoutExtension(f.Path) + ".") + fmt,
                    SourceBytes = TryFileSize(f.Path),
                    DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds / Math.Max(1, subFiles.Count),
                    Success = true,
                    Profile = fmt,
                });
            }
        }
        else
        {
            StatusText.Text = AppLocalizer.Format($"Failed: {result.ErrorMessage ?? result.ErrorCode}");
            foreach (var f in subFiles.Where(f => f.StatusText == "Pending"))
                f.StatusText = "Failed";
        }
        ConvertButton.IsEnabled = true;
    }

    /// <summary>
    /// Extracts captions from video containers (embedded track, with a CEA-608
    /// bitstream fallback) and decodes broadcast SCC files to the chosen text
    /// format via the ccextract sidecar. ccextract writes SRT/VTT/ASS only.
    /// </summary>
    private async Task ExtractCaptionsAsync(List<SubFileItem> ccFiles, string fmt, string outDir)
    {
        if (!CcExtractFormats.Contains(fmt))
        {
            foreach (var f in ccFiles)
                f.StatusText = "Skipped -- choose SRT/VTT/ASS for video/SCC";
            return;
        }

        foreach (var f in ccFiles)
        {
            var ext = System.IO.Path.GetExtension(f.Path).ToLowerInvariant();
            var isVideo = VideoExts.Contains(ext);
            var outPath = System.IO.Path.Combine(
                outDir, System.IO.Path.GetFileNameWithoutExtension(f.Path) + "." + fmt);
            var ccArgs = new List<string>
            {
                isVideo ? "extract" : "convert",
                "--input", f.Path,
                "--output", outPath,
                "--format", fmt,
            };
            f.StatusText = isVideo ? "Extracting..." : "Reading SCC...";

            using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(15));
            var result = await _runner.RunAsync("ccextract", ccArgs, null, null, cts.Token);

            if (result.ErrorCode == "sidecar_not_found")
            {
                f.StatusText = "ccextract not built (tools/ccextract/build.ps1)";
                continue;
            }
            if (!result.Success && isVideo && result.ErrorCode == "no_captions")
            {
                // Some broadcast sources carry CEA-608 only in the video
                // bitstream (SEI); retry through the subcc extraction path.
                ccArgs.Add("--embedded-608");
                result = await _runner.RunAsync("ccextract", ccArgs, null, null, cts.Token);
                f.StatusText = result.Success ? "Done (embedded 608)" : "No captions found";
                if (result.Success)
                    LogCaption(f, outPath, fmt);
                continue;
            }

            if (result.Success)
            {
                f.StatusText = "Done";
                LogCaption(f, outPath, fmt);
            }
            else
            {
                f.StatusText = $"Failed: {result.ErrorCode}";
            }
        }
    }

    private void LogCaption(SubFileItem f, string outPath, string fmt)
    {
        _ = _history.LogAsync(new HistoryRecord
        {
            Timestamp = DateTime.UtcNow,
            Engine = "ccextract",
            Action = "extract",
            SourcePath = f.Path,
            OutputPath = outPath,
            SourceBytes = TryFileSize(f.Path),
            Success = true,
            Profile = fmt,
        });
    }

    private static long? TryFileSize(string path)
    {
        try { return new FileInfo(path).Length; } catch { return null; }
    }
}
