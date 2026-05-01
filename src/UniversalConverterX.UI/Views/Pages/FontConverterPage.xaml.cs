using System.Collections.ObjectModel;
using System.ComponentModel;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class FontFileItem : INotifyPropertyChanged
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

public sealed partial class FontConverterPage : Page
{
    private static readonly string[] FontExts = [".ttf", ".otf", ".woff", ".woff2"];

    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly ObservableCollection<FontFileItem> _files = [];
    private string? _outputDir;

    public FontConverterPage()
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
        foreach (var ext in FontExts) picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;
        foreach (var f in files)
            if (!_files.Any(x => x.Path == f.Path))
                _files.Add(new FontFileItem { Path = f.Path });
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
        if (sender is Button b && b.Tag is FontFileItem item)
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

        var fmt = (FormatCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "woff2";
        var outDir = string.IsNullOrEmpty(_outputDir)
            ? System.IO.Path.GetDirectoryName(_files[0].Path) ?? Environment.CurrentDirectory
            : _outputDir;
        Directory.CreateDirectory(outDir);

        var args = new List<string>
        {
            "convert",
            "--output-dir", outDir,
            "--format", fmt,
            "--input",
        };
        args.AddRange(_files.Select(f => f.Path));

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            WorkProgress.Value = p.Percent;
            StatusText.Text = $"{p.Stage} -- {p.Percent:F0}%";
        }));

        var startedAt = DateTime.UtcNow;
        StatusText.Text = "Converting...";
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(10));
        var result = await _runner.RunAsync(
            "fontconvert", args, progress, null, cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName != "font") return;
                if (!root.TryGetProperty("input", out var ip)) return;
                var match = _files.FirstOrDefault(f => f.Path == ip.GetString());
                if (match is not null)
                {
                    var sz = root.TryGetProperty("size_bytes", out var s) ? s.GetInt64() : 0;
                    match.StatusText = sz > 0 ? FormatBytes(sz) : "Done";
                }
            }));

        if (result.ErrorCode == "sidecar_not_found")
            StatusText.Text = "fontconvert sidecar not built. Run pwsh tools/fontconvert/build.ps1.";
        else if (result.Success)
        {
            StatusText.Text = $"Done -- {_files.Count} font(s) -> .{fmt}.";
            WorkProgress.Value = 100;
            foreach (var f in _files)
            {
                _ = _history.LogAsync(new HistoryRecord
                {
                    Timestamp = startedAt,
                    Engine = "fontconvert",
                    Action = "convert",
                    SourcePath = f.Path,
                    OutputPath = System.IO.Path.Combine(outDir,
                        System.IO.Path.GetFileNameWithoutExtension(f.Path) + "." + fmt),
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

    private static string FormatBytes(long b)
    {
        double v = b;
        string[] u = ["B", "KB", "MB", "GB"];
        var i = 0;
        while (v >= 1024 && i < u.Length - 1) { v /= 1024; i++; }
        return $"{v:0.##} {u[i]}";
    }

    private static long? TryFileSize(string path)
    {
        try { return new FileInfo(path).Length; } catch { return null; }
    }
}
