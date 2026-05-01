using System.Collections.ObjectModel;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class ArchiveItem
{
    public string Path { get; init; } = "";
    public bool IsFolder { get; init; }
    public long? Size { get; init; }

    public string DisplayName => System.IO.Path.GetFileName(Path) is var n && !string.IsNullOrEmpty(n) ? n : Path;
    public string Glyph => IsFolder ? "\uE8B7" : "\uE8A5";
    public string SizeLabel => Size is long s ? FormatBytes(s) : (IsFolder ? "(folder)" : "");

    public static string FormatBytes(long b)
    {
        double v = b;
        string[] u = ["B", "KB", "MB", "GB", "TB"];
        var i = 0;
        while (v >= 1024 && i < u.Length - 1) { v /= 1024; i++; }
        return $"{v:0.##} {u[i]}";
    }
}

public sealed partial class ArchivePage : Page
{
    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly ObservableCollection<ArchiveItem> _items = [];
    private string? _packOutput;
    private string? _unpackInput;
    private string? _unpackOutputDir;
    private bool _packMode = true;

    public ArchivePage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        ItemsList.ItemsSource = _items;
    }

    private void ModePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        _packMode = ModePivot.SelectedIndex == 0;
        _items.Clear();
        EmptyHint.Text = _packMode
            ? "Pack mode: drop the items you want to archive."
            : "Unpack mode: drop or pick an archive to extract.";
        GoButton.Content = _packMode ? "Pack" : "Unpack";
        ListButton.IsEnabled = !_packMode && _unpackInput is not null;
        UpdateUi();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.Caption = _packMode ? "Add to pack queue" : "Use as archive source";
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        var items = await e.DataView.GetStorageItemsAsync();
        if (_packMode)
        {
            foreach (var it in items)
            {
                long? size = null;
                bool isFolder = it is StorageFolder;
                if (it is StorageFile f)
                {
                    try { size = (long)(await f.GetBasicPropertiesAsync()).Size; } catch { }
                }
                if (!_items.Any(x => x.Path == it.Path))
                    _items.Add(new ArchiveItem { Path = it.Path, IsFolder = isFolder, Size = size });
            }
            UpdateUi();
        }
        else if (items.FirstOrDefault() is StorageFile sf)
        {
            _unpackInput = sf.Path;
            UnpackArchiveBox.Text = sf.Path;
            ListButton.IsEnabled = true;
            UpdateUi();
        }
    }

    private async void PickPackOutput_Click(object sender, RoutedEventArgs e)
    {
        var fmt = (PackFormatCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "7z";
        var ext = fmt switch { "gz" => ".tar.gz", "xz" => ".tar.xz", "bz2" => ".tar.bz2", _ => "." + fmt };
        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.Downloads,
            SuggestedFileName = "archive",
        };
        picker.FileTypeChoices.Add(fmt.ToUpperInvariant(), [ext]);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var f = await picker.PickSaveFileAsync();
        if (f is null) return;
        _packOutput = f.Path;
        PackOutputBox.Text = f.Path;
        UpdateUi();
    }

    private async void PickUnpackInput_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            SuggestedStartLocation = PickerLocationId.Downloads,
        };
        foreach (var ext in new[] { ".7z", ".zip", ".rar", ".tar", ".gz", ".bz2", ".xz",
                                    ".lzma", ".iso", ".cab", ".msi", ".lzh", ".wim", ".tgz" })
            picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var f = await picker.PickSingleFileAsync();
        if (f is null) return;
        _unpackInput = f.Path;
        UnpackArchiveBox.Text = f.Path;
        ListButton.IsEnabled = true;
        UpdateUi();
    }

    private async void PickUnpackOutput_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.Downloads };
        picker.FileTypeFilter.Add("*");
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var folder = await picker.PickSingleFolderAsync();
        if (folder is null) return;
        _unpackOutputDir = folder.Path;
        UnpackOutputDirBox.Text = folder.Path;
        UpdateUi();
    }

    private void RemoveItem_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button b && b.Tag is ArchiveItem item)
        {
            _items.Remove(item);
            UpdateUi();
        }
    }

    private void UpdateUi()
    {
        if (_packMode)
        {
            var has = _items.Count > 0;
            EmptyState.Visibility = has ? Visibility.Collapsed : Visibility.Visible;
            ItemsScroll.Visibility = has ? Visibility.Visible : Visibility.Collapsed;
            GoButton.IsEnabled = has && _packOutput is not null;
        }
        else
        {
            // In unpack mode the list shows archive contents (only after List).
            var has = _items.Count > 0;
            EmptyState.Visibility = has ? Visibility.Collapsed : Visibility.Visible;
            ItemsScroll.Visibility = has ? Visibility.Visible : Visibility.Collapsed;
            GoButton.IsEnabled = _unpackInput is not null && _unpackOutputDir is not null;
        }
    }

    private async void Go_Click(object sender, RoutedEventArgs e)
    {
        if (_packMode) await DoPackAsync();
        else           await DoUnpackAsync();
    }

    private async Task DoPackAsync()
    {
        if (_items.Count == 0 || _packOutput is null) return;
        GoButton.IsEnabled = false;
        WorkProgress.Value = 0;
        LogText.Text = "";

        var fmt = (PackFormatCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "7z";
        var pwd = PackPasswordBox.Password;
        var args = new List<string>
        {
            "pack",
            "--output", _packOutput,
            "--format", fmt,
            "--level", ((int)LevelSlider.Value).ToString(System.Globalization.CultureInfo.InvariantCulture),
        };
        if (!string.IsNullOrEmpty(pwd)) args.AddRange(["--password", pwd]);
        args.Add("--input");
        args.AddRange(_items.Select(i => i.Path));

        var startedAt = DateTime.UtcNow;
        var totalSrc = _items.Sum(i => i.Size ?? 0);

        StatusText.Text = $"Packing {_items.Count} item(s) -> {System.IO.Path.GetFileName(_packOutput)}...";
        var result = await RunSidecarAsync(args);
        if (result.Success)
        {
            StatusText.Text = $"Packed -> {System.IO.Path.GetFileName(_packOutput)} ({ArchiveItem.FormatBytes(result.SizeBytes ?? 0)})";
            _ = _history.LogAsync(new HistoryRecord
            {
                Timestamp = startedAt,
                Engine = "archive",
                Action = "pack",
                SourcePath = _items.Count == 1 ? _items[0].Path : $"({_items.Count} items)",
                OutputPath = _packOutput,
                SourceBytes = totalSrc > 0 ? totalSrc : null,
                OutputBytes = result.SizeBytes,
                DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds,
                Success = true,
                Profile = fmt,
            });
        }
        else
        {
            StatusText.Text = $"Pack failed: {result.ErrorMessage ?? result.ErrorCode}";
        }
        GoButton.IsEnabled = true;
    }

    private async Task DoUnpackAsync()
    {
        if (_unpackInput is null || _unpackOutputDir is null) return;
        GoButton.IsEnabled = false;
        WorkProgress.Value = 0;
        LogText.Text = "";

        var args = new List<string>
        {
            "unpack",
            "--input", _unpackInput,
            "--output-dir", _unpackOutputDir,
        };

        var startedAt = DateTime.UtcNow;
        StatusText.Text = $"Unpacking {System.IO.Path.GetFileName(_unpackInput)}...";
        var result = await RunSidecarAsync(args);
        if (result.Success)
        {
            StatusText.Text = $"Unpacked to {_unpackOutputDir}";
            _ = _history.LogAsync(new HistoryRecord
            {
                Timestamp = startedAt,
                Engine = "archive",
                Action = "unpack",
                SourcePath = _unpackInput,
                OutputPath = _unpackOutputDir,
                SourceBytes = TryFileSize(_unpackInput),
                OutputBytes = result.SizeBytes,
                DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds,
                Success = true,
                Profile = System.IO.Path.GetExtension(_unpackInput).TrimStart('.'),
            });
        }
        else
        {
            StatusText.Text = $"Unpack failed: {result.ErrorMessage ?? result.ErrorCode}";
        }
        GoButton.IsEnabled = true;
    }

    private async void ListContents_Click(object sender, RoutedEventArgs e)
    {
        if (_unpackInput is null) return;
        ListButton.IsEnabled = false;
        _items.Clear();
        UpdateUi();
        StatusText.Text = $"Listing contents of {System.IO.Path.GetFileName(_unpackInput)}...";

        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(2));
        var result = await _runner.RunAsync(
            "archive",
            ["list", "--input", _unpackInput],
            ct: cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName != "archive_entry") return;
                _items.Add(new ArchiveItem
                {
                    Path = root.TryGetProperty("path", out var p) ? p.GetString() ?? "" : "",
                    Size = root.TryGetProperty("size", out var s) && s.ValueKind == System.Text.Json.JsonValueKind.Number
                        ? s.GetInt64() : null,
                    IsFolder = false,
                });
            }));

        if (result.ErrorCode == "sidecar_not_found")
            StatusText.Text = "archive sidecar not built. Run pwsh tools/archive/build.ps1.";
        else if (result.ErrorCode == "missing_7zip")
            StatusText.Text = "7-Zip not found. Install from 7-zip.org and try again.";
        else if (result.Success)
            StatusText.Text = $"Listed {_items.Count} entries.";
        else
            StatusText.Text = $"List failed: {result.ErrorMessage ?? result.ErrorCode}";
        ListButton.IsEnabled = true;
        UpdateUi();
    }

    private async Task<SidecarResult> RunSidecarAsync(List<string> args)
    {
        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            WorkProgress.Value = p.Percent;
        }));
        var log = new Progress<SidecarLog>(l => DispatcherQueue.TryEnqueue(() =>
        {
            LogText.Text += $"[{l.Level}] {l.Message}\n";
        }));
        using var cts = new CancellationTokenSource(TimeSpan.FromHours(1));
        return await _runner.RunAsync("archive", args, progress, log, cts.Token);
    }

    private static long? TryFileSize(string path)
    {
        try { return new FileInfo(path).Length; } catch { return null; }
    }
}
