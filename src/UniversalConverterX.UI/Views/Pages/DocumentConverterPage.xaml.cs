using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class DocumentFileItem : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;
    public string Path { get; init; } = "";
    public string FileName => System.IO.Path.GetFileName(Path);

    private string _statusText = "Pending";
    public string StatusText
    {
        get => _statusText;
        set
        {
            if (_statusText == value) return;
            _statusText = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(StatusText)));
        }
    }
}

public sealed partial class DocumentConverterPage : Page
{
    private static readonly string[] DocExts =
    [
        ".docx", ".doc", ".odt", ".rtf", ".txt", ".html", ".htm",
        ".xlsx", ".xls", ".ods", ".csv", ".tsv",
        ".pptx", ".ppt", ".odp",
        ".pdf", ".epub", ".fb2",
    ];

    private static readonly string[] TargetFormats =
    [
        "pdf", "docx", "odt", "rtf", "txt", "html", "epub",
        "xlsx", "ods", "csv",
        "pptx", "odp",
        "png", "svg",
    ];

    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly ObservableCollection<DocumentFileItem> _files = [];
    private string? _outputDir;

    public DocumentConverterPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        FilesList.ItemsSource = _files;
        foreach (var fmt in TargetFormats)
            FormatCombo.Items.Add(fmt);
        FormatCombo.SelectedIndex = 0;  // pdf
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop documents here";
        e.DragUIOverride.IsCaptionVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        var items = await e.DataView.GetStorageItemsAsync();
        foreach (var item in items)
        {
            if (item is StorageFile f) AddFile(f.Path);
            else if (item is StorageFolder folder) await AddFolderAsync(folder);
        }
        UpdateUi();
    }

    private async Task AddFolderAsync(StorageFolder folder)
    {
        try
        {
            foreach (var f in await folder.GetFilesAsync())
                if (DocExts.Contains(System.IO.Path.GetExtension(f.Path).ToLowerInvariant()))
                    AddFile(f.Path);
        }
        catch { /* permissions, ignore */ }
    }

    private async void AddFiles_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        foreach (var ext in DocExts) picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;
        foreach (var f in files) AddFile(f.Path);
        UpdateUi();
    }

    private async void BrowseOutputDir_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        picker.FileTypeFilter.Add("*");
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var folder = await picker.PickSingleFolderAsync();
        if (folder is null) return;
        _outputDir = folder.Path;
        OutputDirBox.Text = folder.Path;
    }

    private void AddFile(string path)
    {
        if (_files.Any(f => f.Path == path)) return;
        _files.Add(new DocumentFileItem { Path = path });
    }

    private void RemoveFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button b && b.Tag is DocumentFileItem item)
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
        foreach (var f in _files) f.StatusText = "Pending";

        var format = (FormatCombo.SelectedItem as string) ?? FormatCombo.Text?.Trim();
        if (string.IsNullOrEmpty(format))
        {
            StatusText.Text = "Pick a target format first.";
            ConvertButton.IsEnabled = true;
            return;
        }

        var outDir = string.IsNullOrEmpty(_outputDir)
            ? System.IO.Path.GetDirectoryName(_files[0].Path) ?? Environment.CurrentDirectory
            : _outputDir;
        Directory.CreateDirectory(outDir);

        var args = new List<string>
        {
            "convert",
            "--output-dir", outDir,
            "--format", format,
            "--input",
        };
        args.AddRange(_files.Select(f => f.Path));

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            WorkProgress.Value = p.Percent;
            StatusText.Text = $"{p.Stage} -- {p.Percent:F0}%";
        }));
        var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
        {
            LogText.Text += $"[{l.Level}] {l.Message}\n";
        }));

        StatusText.Text = "Converting...";
        var startedAt = DateTime.UtcNow;
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(30));
        var result = await _runner.RunAsync(
            "docconvert", args, progress, log, cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName != "doc") return;
                if (!root.TryGetProperty("input", out var ip)) return;
                var inPath = ip.GetString();
                var match = _files.FirstOrDefault(f => f.Path == inPath);
                if (match is not null) match.StatusText = "Done";
            }));

        if (result.ErrorCode == "sidecar_not_found")
        {
            StatusText.Text = "docconvert sidecar not built. Run pwsh tools/docconvert/build.ps1.";
        }
        else if (result.ErrorCode == "missing_libreoffice")
        {
            StatusText.Text = "LibreOffice not found. Install it from libreoffice.org and try again.";
        }
        else if (result.Success)
        {
            StatusText.Text = $"Done -- {_files.Count} document(s) converted to .{format}.";
            WorkProgress.Value = 100;
            foreach (var f in _files)
            {
                _ = _history.LogAsync(new HistoryRecord
                {
                    Timestamp = startedAt,
                    Engine = "docconvert",
                    Action = "convert",
                    SourcePath = f.Path,
                    OutputPath = System.IO.Path.Combine(outDir,
                        System.IO.Path.GetFileNameWithoutExtension(f.Path) + "." + format),
                    SourceBytes = TryFileSize(f.Path),
                    OutputBytes = TryFileSize(System.IO.Path.Combine(outDir,
                        System.IO.Path.GetFileNameWithoutExtension(f.Path) + "." + format)),
                    DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds / Math.Max(1, _files.Count),
                    Success = true,
                    Profile = format,
                });
            }
        }
        else
        {
            StatusText.Text = $"Conversion failed: {result.ErrorMessage ?? result.ErrorCode}";
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
