using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.Core.Utilities;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class UniversalMatchItem : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;
    public required WorkflowCatalogItem CatalogItem { get; init; }
    public required UiPreset Preset { get; init; }
    public required IReadOnlyList<string> AcceptedInputs { get; init; }
    public required IReadOnlyList<string> AllInputs { get; init; }

    public string Name => CatalogItem.LocalizedTitle;
    public string Glyph { get; init; } = "\uE8B7";

    public string Subtitle
    {
        get
        {
            var parts = new List<string> { Preset.Engine };
            if (Preset.Folder is not null) parts.Add(Preset.Folder);
            parts.Add("-> ." + Preset.OutputExtension);
            return string.Join(" | ", parts);
        }
    }

    public string MatchSummary
    {
        get
        {
            if (AcceptedInputs.Count == AllInputs.Count)
                return $"Accepts all {AllInputs.Count} input(s)";
            return $"Accepts {AcceptedInputs.Count} of {AllInputs.Count} input(s)";
        }
    }

    private string _statusText = "";
    public string StatusText
    {
        get => _statusText;
        set { if (_statusText != value) { _statusText = value; PropertyChanged?.Invoke(this, new(nameof(StatusText))); } }
    }
}

public sealed partial class UniversalConvertPage : Page, INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    private readonly IPresetExecutor _executor;
    private readonly IHistoryService _history;
    private readonly IWorkflowCatalog _catalog;
    private readonly ObservableCollection<UniversalMatchItem> _displayed = [];
    private List<UniversalMatchItem> _all = [];
    private List<string> _selectedFiles = [];
    private string? _searchTerm;
    private CancellationTokenSource? _searchDebounce;
    private readonly HashSet<string> _running = new(StringComparer.Ordinal);

    private Visibility _filterVisibility = Visibility.Collapsed;
    public Visibility FilterVisibility
    {
        get => _filterVisibility;
        private set
        {
            if (_filterVisibility != value)
            {
                _filterVisibility = value;
                PropertyChanged?.Invoke(this, new(nameof(FilterVisibility)));
            }
        }
    }

    public UniversalConvertPage()
    {
        InitializeComponent();
        _executor    = App.Services.GetRequiredService<IPresetExecutor>();
        _history     = App.Services.GetRequiredService<IHistoryService>();
        _catalog    = App.Services.GetRequiredService<IWorkflowCatalog>();
        MatchList.ItemsSource = _displayed;
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        if (e.DataView.Contains(StandardDataFormats.StorageItems))
        {
            e.AcceptedOperation = DataPackageOperation.Copy;
            e.DragUIOverride.Caption = AppLocalizer.Get("Inspect for matching presets");
            e.DragUIOverride.IsCaptionVisible = true;
            e.DragUIOverride.IsContentVisible = true;
        }
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        var items = await DropSnapshotHelper.TrySnapshotDropAsync(e);
        if (items is null) return;
        var paths = items.OfType<StorageFile>().Select(f => f.Path).ToList();
        if (paths.Count == 0) return;
        SetFiles(paths);
    }

    private async void Pick_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
        picker.FileTypeFilter.Add("*");
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null || files.Count == 0) return;
        SetFiles(files.Select(f => f.Path).ToList());
    }

    private void Clear_Click(object sender, RoutedEventArgs e)
    {
        _selectedFiles.Clear();
        SelectedFilesText.Text = "";
        DropHint.Text = AppLocalizer.Get("Drop files here, or pick them");
        StatusText.Text = AppLocalizer.Get("Drop files above to see matching presets.");
        FilterVisibility = Visibility.Collapsed;
        NoMatchesState.Visibility = Visibility.Collapsed;
        MatchScroll.Visibility = Visibility.Visible;
        _all.Clear();
        _displayed.Clear();
    }

    private void SetFiles(List<string> paths)
    {
        _selectedFiles = paths
            .Where(File.Exists)
            .Distinct(OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal)
            .ToList();
        if (_selectedFiles.Count == 0)
        {
            Clear_Click(this, new RoutedEventArgs());
            StatusText.Text = AppLocalizer.Get("No readable files were selected.");
            return;
        }
        var first = Path.GetFileName(_selectedFiles[0]);
        SelectedFilesText.Text = _selectedFiles.Count == 1
            ? first
            : AppLocalizer.Format($"{first} +{_selectedFiles.Count - 1} more");
        DropHint.Text = AppLocalizer.Format($"{_selectedFiles.Count} file(s) selected");

        // Compute extension list (lowercase, no dot).
        var exts = _selectedFiles.Select(p => Path.GetExtension(p).TrimStart('.').ToLowerInvariant())
                        .Where(e => !string.IsNullOrEmpty(e))
                        .ToList();

        var presets = _catalog.GetPresets();
        var matches = new List<UniversalMatchItem>();
        foreach (var catalogItem in presets)
        {
            if (catalogItem.Preset is not UiPreset p)
                continue;
            var allowed = p.InputTypes.Select(s => s.TrimStart('.').ToLowerInvariant()).ToHashSet();
            var accepted = _selectedFiles.Where(path =>
            {
                if (allowed.Count == 0) return true;
                var ext = Path.GetExtension(path).TrimStart('.').ToLowerInvariant();
                return !string.IsNullOrEmpty(ext) && allowed.Contains(ext);
            }).ToList();
            if (accepted.Count == 0 && allowed.Count > 0) continue;
            matches.Add(new UniversalMatchItem
            {
                CatalogItem = catalogItem,
                Preset = p,
                AcceptedInputs = accepted,
                AllInputs = _selectedFiles,
                Glyph = catalogItem.Glyph,
            });
        }
        // Sort: full-coverage matches first, then by engine, then by name.
        matches.Sort((a, b) =>
        {
            var ca = a.AcceptedInputs.Count == a.AllInputs.Count;
            var cb = b.AcceptedInputs.Count == b.AllInputs.Count;
            if (ca != cb) return cb.CompareTo(ca);
            var eng = string.Compare(a.Preset.Engine, b.Preset.Engine, StringComparison.OrdinalIgnoreCase);
            return eng != 0 ? eng : string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase);
        });

        _all = matches;
        ApplyFilter();
        FilterVisibility = matches.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
        NoMatchesState.Visibility = matches.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        MatchScroll.Visibility = matches.Count == 0 ? Visibility.Collapsed : Visibility.Visible;

        var distinctExts = exts.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        var extSummary = string.Join(", ", distinctExts.Take(6).Select(e => "." + e));
        if (distinctExts.Count > 6) extSummary += "...";
        if (string.IsNullOrWhiteSpace(extSummary)) extSummary = "extensionless files";
        StatusText.Text = matches.Count == 0
            ? AppLocalizer.Format($"No presets accept {extSummary}. Try installing/wiring a sidecar for this format.")
            : AppLocalizer.Format($"Found {matches.Count} preset(s) that accept {extSummary}.");
    }

    private async void Search_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput) return;
        _searchTerm = sender.Text;
        _searchDebounce?.Cancel();
        _searchDebounce?.Dispose();
        var cts = new CancellationTokenSource();
        _searchDebounce = cts;
        try { await Task.Delay(TimeSpan.FromMilliseconds(120), cts.Token); }
        catch (OperationCanceledException) { return; }
        if (cts.IsCancellationRequested) return;
        ApplyFilter();
    }

    private void ApplyFilter()
    {
        IEnumerable<UniversalMatchItem> q = _all;
        if (!string.IsNullOrWhiteSpace(_searchTerm))
        {
            var s = _searchTerm.Trim();
            q = q.Where(c =>
                c.Name.Contains(s, StringComparison.OrdinalIgnoreCase)
                || (c.Preset.Folder?.Contains(s, StringComparison.OrdinalIgnoreCase) ?? false)
                || c.Preset.Engine.Contains(s, StringComparison.OrdinalIgnoreCase)
                || c.Preset.OutputExtension.Contains(s, StringComparison.OrdinalIgnoreCase));
        }
        _displayed.Clear();
        foreach (var c in q) _displayed.Add(c);
    }

    private async void RunPreset_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button b || b.Tag is not string workflowId) return;
        var card = _all.FirstOrDefault(c =>
            string.Equals(c.CatalogItem.Id, workflowId, StringComparison.OrdinalIgnoreCase));
        if (card is null) return;
        var preset = card.Preset;
        if (card.AcceptedInputs.Count == 0)
        {
            card.StatusText = AppLocalizer.Get("No accepted inputs.");
            return;
        }

        if (!_running.Add(preset.Name))
        {
            card.StatusText = AppLocalizer.Get("Already running...");
            return;
        }

        try
        {
            // Reuse the exact file paths matched in SetFiles; wildcard presets
            // intentionally accept extensionless files.
            var inputs = card.AcceptedInputs.ToList();

            // Output dir prompt for batch modes; per-file infers from template.
            string? outDir = null;
            if (PresetInvocationModes.RequiresOutputDirectory(preset.Mode))
            {
                var folderPicker = new FolderPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
                folderPicker.FileTypeFilter.Add("*");
                var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
                WinRT.Interop.InitializeWithWindow.Initialize(folderPicker, hwnd);
                var folder = await folderPicker.PickSingleFolderAsync();
                if (folder is null) return;
                outDir = folder.Path;
            }

            card.StatusText = AppLocalizer.Get("Running...");
            var startedAt = DateTime.UtcNow;
            using var cts = new CancellationTokenSource(TimeSpan.FromHours(1));
            var result = await _executor.RunAsync(preset, inputs, outDir, cancellationToken: cts.Token);
            card.StatusText = result.Success ? AppLocalizer.Get("Done") : AppLocalizer.Format($"Failed ({result.ErrorCode})");

            StatusText.Text = result.Success
                ? AppLocalizer.Format($"{preset.Name} -- {inputs.Count} input(s), exit {result.ExitCode}.")
                : AppLocalizer.Format($"{preset.Name} -- {result.ErrorCode}: {result.ErrorMessage ?? "Unknown error"}");

            if (inputs.Count > 0)
            {
                var firstInput = inputs[0];
                string? firstOut = !result.Success || !PresetInvocationModes.ProducesOutputPath(preset.Mode)
                    ? null
                    : preset.Mode == PresetInvocationMode.PerFile
                        ? UiPresetLoader.ResolveOutputPath(preset, firstInput)
                        : outDir is null ? null : Path.Combine(outDir,
                            Path.GetFileNameWithoutExtension(firstInput) + "." + preset.OutputExtension);
                _ = _history.LogAsync(new HistoryRecord
                {
                    Timestamp = startedAt,
                    Engine = preset.Engine,
                    Action = "universal-convert",
                    SourcePath = inputs.Count == 1 ? firstInput : $"({inputs.Count} files)",
                    OutputPath = firstOut,
                    SourceBytes = TryFileSize(firstInput),
                    OutputBytes = firstOut is null ? null : TryFileSize(firstOut),
                    DurationSeconds = (DateTime.UtcNow - startedAt).TotalSeconds,
                    Success = result.Success,
                    ErrorCode = result.ErrorCode,
                    ErrorMessage = result.ErrorMessage,
                    Profile = preset.Name,
                });
            }
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"UniversalConvert: {ex}");
            card.StatusText = AppLocalizer.Format($"Failed ({ex.GetType().Name})");
        }
        finally
        {
            _running.Remove(preset.Name);
        }
    }

    private static string GlyphFor(string engine) => engine switch
    {
        "videocrush" or "clipforge" or "recordcast" => "\uE714",
        "gifstudio" or "lottiekit" => "\uE909",
        "heicshift" or "rawphoto" or "iccprofile" or "texturekit" or "vectorkit" => "\uEB9F",
        "framesnap" => "\uE722",
        "rnnoise" or "demucs" or "stemkit" or "speechenhance" => "\uE767",
        "edge-tts" or "midisynth" or "trackermod" or "audiotag" => "\uEC4F",
        "whisper-cpp" or "whisper-stt" or "parakeet-stt" or "ai-subtitle" => "\uED1E",
        "vertigo" => "\uE740",
        "realesrgan" or "sdkit" => "\uE799",
        "videosubtitleremover" or "subconvert" => "\uE93B",
        "streamkeep" => "\uE896",
        "scenedetect" => "\uE71D",
        "chaptermark" => "\uE8B7",
        "docconvert" or "pandoc-cli" or "ebookconvert" or "datakit" or "pdfmarkdown" or "datasci" or "i18nkit" => "\uE8A5",
        "archive" => "\uE7B8",
        "pdftools" or "pdfocr" => "\uEA90",
        "fontconvert" or "fontsubset" => "\uE8D2",
        "ocr" => "\uE8A1",
        "meshconvert" or "pointcloud" => "\uF158",
        "gisconvert" => "\uE707",
        "cadkit" => "\uE8B7",
        "dicomkit" => "\uE8A1",
        "calconvert" or "mailbox" or "mailimport" or "webarchive" => "\uE715",
        "codeformat" => "\uE943",
        "lutgen" => "\uE790",
        "gametools" => "\uE7FC",
        "diskimage" => "\uE7C4",
        _ => "\uE8B7",
    };

    private static long? TryFileSize(string path)
    {
        try { return new FileInfo(path).Length; } catch { return null; }
    }
}
