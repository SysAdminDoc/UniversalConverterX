using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class OcrFileItem : INotifyPropertyChanged
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

public sealed partial class OcrPage : Page
{
    private static readonly string[] ImgExts =
        [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"];

    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly ObservableCollection<OcrFileItem> _files = [];
    private string? _outputDir;

    public OcrPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        FilesList.ItemsSource = _files;
        // Populate eng as the default; user can hit Reload to discover the rest.
        LangCombo.Items.Add("eng");
        LangCombo.SelectedIndex = 0;
    }

    private async void ReloadLangs_Click(object sender, RoutedEventArgs e)
    {
        StatusText.Text = AppLocalizer.Get("Querying installed languages...");
        var langs = new List<string>();
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));
        var result = await _runner.RunAsync(
            "ocr", ["languages"],
            ct: cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName == "ocr_language" && root.TryGetProperty("code", out var c))
                    langs.Add(c.GetString() ?? "");
            }));

        if (result.ErrorCode == "sidecar_not_found")
            StatusText.Text = AppLocalizer.Get("ocr sidecar not built. Run pwsh tools/ocr/build.ps1.");
        else if (result.ErrorCode == "missing_tesseract")
            StatusText.Text = AppLocalizer.Get("Tesseract not found. Install from UB-Mannheim's release page.");
        else if (result.Success)
        {
            var current = (LangCombo.SelectedItem as string) ?? LangCombo.Text;
            LangCombo.Items.Clear();
            foreach (var l in langs.Where(s => !string.IsNullOrWhiteSpace(s)).OrderBy(s => s))
                LangCombo.Items.Add(l);
            if (LangCombo.Items.Count > 0)
            {
                LangCombo.SelectedItem = LangCombo.Items.Contains(current ?? "") ? current : "eng";
                if (LangCombo.SelectedIndex < 0) LangCombo.SelectedIndex = 0;
            }
            StatusText.Text = AppLocalizer.Format($"Discovered {langs.Count} language pack(s).");
        }
        else
        {
            StatusText.Text = AppLocalizer.Format($"Failed: {result.ErrorMessage ?? result.ErrorCode}");
        }
    }

    private async void AddFiles_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            SuggestedStartLocation = PickerLocationId.PicturesLibrary,
        };
        foreach (var ext in ImgExts) picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;
        foreach (var f in files)
            if (!_files.Any(x => x.Path == f.Path))
                _files.Add(new OcrFileItem { Path = f.Path });
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
        if (sender is Button b && b.Tag is OcrFileItem item)
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
        RecognizeButton.IsEnabled = has;
    }

    private async void Recognize_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0) return;
        RecognizeButton.IsEnabled = false;
        WorkProgress.Value = 0;
        foreach (var f in _files) f.StatusText = "Pending";

        var lang = (LangCombo.SelectedItem as string) ?? LangCombo.Text?.Trim();
        if (string.IsNullOrWhiteSpace(lang)) lang = "eng";
        var fmt = (FormatCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "txt";
        var psm = ((int)PsmBox.Value).ToString(CultureInfo.InvariantCulture);
        var outDir = string.IsNullOrEmpty(_outputDir)
            ? System.IO.Path.GetDirectoryName(_files[0].Path) ?? Environment.CurrentDirectory
            : _outputDir;
        try { Directory.CreateDirectory(outDir); }
        catch (Exception ex)
        {
            StatusText.Text = AppLocalizer.Format($"Output folder unavailable: {ex.Message}");
            RecognizeButton.IsEnabled = true;
            return;
        }

        var args = new List<string>
        {
            "recognize",
            "--output-dir", outDir,
            "--format", fmt,
            "--lang", lang,
            "--psm", psm,
            "--input",
        };
        args.AddRange(_files.Select(f => f.Path));

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            WorkProgress.Value = p.Percent;
            StatusText.Text = AppLocalizer.Format($"{p.Stage}");
        }));

        var startedAt = DateTime.UtcNow;
        StatusText.Text = AppLocalizer.Get("Running OCR...");
        using var cts = new CancellationTokenSource(TimeSpan.FromHours(1));
        var result = await _runner.RunAsync(
            "ocr", args, progress, null, cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName != "ocr_result") return;
                if (!root.TryGetProperty("input", out var ip)) return;
                var match = _files.FirstOrDefault(f => f.Path == ip.GetString());
                if (match is not null) match.StatusText = "Done";
            }));

        if (result.ErrorCode == "sidecar_not_found")
            StatusText.Text = AppLocalizer.Get("ocr sidecar not built. Run pwsh tools/ocr/build.ps1.");
        else if (result.ErrorCode == "missing_tesseract")
            StatusText.Text = AppLocalizer.Get("Tesseract not found. Install from UB-Mannheim's release page.");
        else if (result.Success)
        {
            StatusText.Text = AppLocalizer.Format($"Done -- OCR'd {_files.Count} image(s) -> .{fmt}.");
            WorkProgress.Value = 100;
            foreach (var f in _files)
            {
                _ = _history.LogAsync(new HistoryRecord
                {
                    Timestamp = startedAt,
                    Engine = "ocr",
                    Action = "recognize",
                    SourcePath = f.Path,
                    OutputPath = System.IO.Path.Combine(outDir,
                        System.IO.Path.GetFileNameWithoutExtension(f.Path) + ExtFor(fmt)),
                    SourceBytes = TryFileSize(f.Path),
                    DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds / Math.Max(1, _files.Count),
                    Success = true,
                    Profile = $"{lang}/{fmt}",
                });
            }
        }
        else
        {
            StatusText.Text = AppLocalizer.Format($"Failed: {result.ErrorMessage ?? result.ErrorCode}");
            foreach (var f in _files.Where(f => f.StatusText == "Pending"))
                f.StatusText = "Failed";
        }
        RecognizeButton.IsEnabled = true;
    }

    private static string ExtFor(string fmt) => fmt switch
    {
        "txt"  => ".txt",
        "hocr" => ".hocr",
        "pdf"  => ".pdf",
        "tsv"  => ".tsv",
        "alto" => ".xml",
        _      => "." + fmt,
    };

    private static long? TryFileSize(string path)
    {
        try { return new FileInfo(path).Length; } catch { return null; }
    }
}
