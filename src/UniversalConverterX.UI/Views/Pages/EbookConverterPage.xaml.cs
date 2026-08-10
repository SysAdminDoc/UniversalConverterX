using System.Collections.Concurrent;
using System.Collections.ObjectModel;
using System.ComponentModel;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class EbookFileItem : INotifyPropertyChanged
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

public sealed partial class EbookConverterPage : Page
{
    private static readonly string[] EbookExts =
    [
        ".epub", ".mobi", ".azw", ".azw3", ".azw4", ".pdf", ".fb2",
        ".lit", ".lrf", ".pdb", ".rtf", ".txt", ".html", ".htm", ".htmlz",
        ".docx", ".odt", ".cbz", ".cbr", ".kepub",
    ];

    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly ObservableCollection<EbookFileItem> _files = [];
    private readonly ConcurrentDictionary<string, string> _outputsByInput = new(StringComparer.OrdinalIgnoreCase);
    private string? _outputDir;

    public EbookConverterPage()
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
        foreach (var ext in EbookExts) picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;
        foreach (var f in files)
            if (!_files.Any(x => x.Path == f.Path))
                _files.Add(new EbookFileItem { Path = f.Path });
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
        if (sender is Button b && b.Tag is EbookFileItem item)
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
        LogText.Text = "";
        _outputsByInput.Clear();
        foreach (var f in _files) f.StatusText = "Pending";

        var fmt = (FormatCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "epub";
        var outDir = string.IsNullOrEmpty(_outputDir)
            ? System.IO.Path.GetDirectoryName(_files[0].Path) ?? Environment.CurrentDirectory
            : _outputDir;
        try { Directory.CreateDirectory(outDir); }
        catch (Exception ex)
        {
            LogText.Text = AppLocalizer.Format($"Output folder unavailable: {ex.Message}");
            ConvertButton.IsEnabled = true;
            return;
        }

        var args = new List<string>
        {
            "convert",
            "--output-dir", outDir,
            "--format", fmt,
        };
        if (!string.IsNullOrWhiteSpace(TitleBox.Text))    args.AddRange(["--title",    TitleBox.Text.Trim()]);
        if (!string.IsNullOrWhiteSpace(AuthorsBox.Text))  args.AddRange(["--authors",  AuthorsBox.Text.Trim()]);
        if (!string.IsNullOrWhiteSpace(LanguageBox.Text)) args.AddRange(["--language", LanguageBox.Text.Trim()]);
        args.Add("--input");
        args.AddRange(_files.Select(f => f.Path));

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            WorkProgress.Value = p.Percent;
            StatusText.Text = AppLocalizer.Format($"{p.Stage}");
        }));
        var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
        {
            LogText.Text += $"[{l.Level}] {l.Message}\n";
        }));

        var startedAt = DateTime.UtcNow;
        StatusText.Text = AppLocalizer.Get("Converting...");
        using var cts = new CancellationTokenSource(TimeSpan.FromHours(1));
        var result = await _runner.RunAsync(
            "ebookconvert", args, progress, log, cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName != "ebook") return;
                if (!root.TryGetProperty("input", out var ip)) return;
                var inputPath = ip.GetString();
                if (root.TryGetProperty("output", out var op)
                    && !string.IsNullOrWhiteSpace(inputPath)
                    && !string.IsNullOrWhiteSpace(op.GetString()))
                {
                    _outputsByInput[inputPath!] = op.GetString()!;
                }
                var match = _files.FirstOrDefault(f => f.Path == inputPath);
                if (match is not null) match.StatusText = "Done";
            }));

        if (result.ErrorCode == "sidecar_not_found")
            StatusText.Text = AppLocalizer.Get("ebookconvert sidecar not built. Run pwsh tools/ebookconvert/build.ps1.");
        else if (result.ErrorCode == "missing_calibre")
            StatusText.Text = AppLocalizer.Get("Calibre not found. Install from calibre-ebook.com and try again.");
        else if (result.ErrorCode == "protected_input")
            StatusText.Text = AppLocalizer.Get("Protected Kindle input rejected. UCX does not include DeDRM; provide a DRM-free export.");
        else if (result.Success)
        {
            StatusText.Text = AppLocalizer.Format($"Done -- {_files.Count} eBook(s) -> .{fmt}.");
            WorkProgress.Value = 100;
            foreach (var f in _files)
            {
                _ = _history.LogAsync(new HistoryRecord
                {
                    Timestamp = startedAt,
                    Engine = "ebookconvert",
                    Action = "convert",
                    SourcePath = f.Path,
                    OutputPath = _outputsByInput.TryGetValue(f.Path, out var actualOutput)
                        ? actualOutput
                        : System.IO.Path.Combine(outDir,
                            System.IO.Path.GetFileNameWithoutExtension(f.Path)
                            + (fmt.Equals("kepub", StringComparison.OrdinalIgnoreCase)
                                ? ".kepub.epub"
                                : "." + fmt)),
                    SourceBytes = TryFileSize(f.Path),
                    DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds / Math.Max(1, _files.Count),
                    Success = true,
                    Profile = fmt,
                });
            }
        }
        else
        {
            StatusText.Text = AppLocalizer.Format($"Failed: {result.ErrorMessage ?? result.ErrorCode}");
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
