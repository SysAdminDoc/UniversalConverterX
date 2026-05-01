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
        foreach (var ext in SubExts) picker.FileTypeFilter.Add(ext);
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
            StatusText.Text = $"Output folder unavailable: {ex.Message}";
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
        args.AddRange(_files.Select(f => f.Path));

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            WorkProgress.Value = p.Percent;
            StatusText.Text = $"{p.Stage} -- {p.Percent:F0}%";
        }));

        var startedAt = DateTime.UtcNow;
        StatusText.Text = "Converting...";
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
            StatusText.Text = "subconvert sidecar not built. Run pwsh tools/subconvert/build.ps1.";
        else if (result.Success)
        {
            StatusText.Text = $"Done -- {_files.Count} subtitle(s) -> .{fmt}.";
            WorkProgress.Value = 100;
            foreach (var f in _files)
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
                    DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds / Math.Max(1, _files.Count),
                    Success = true,
                    Profile = fmt,
                });
            }
        }
        else
        {
            StatusText.Text = $"Failed: {result.ErrorMessage ?? result.ErrorCode}";
            foreach (var f in _files.Where(f => f.StatusText == "Pending"))
                f.StatusText = "Failed";
        }
        ConvertButton.IsEnabled = true;
    }

    private static long? TryFileSize(string path)
    {
        try { return new FileInfo(path).Length; } catch { return null; }
    }
}
