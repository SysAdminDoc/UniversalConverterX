using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class UniversalMatchItem : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;
    public required UiPreset Preset { get; init; }
    public required IReadOnlyList<string> AcceptedInputs { get; init; }
    public required IReadOnlyList<string> AllInputs { get; init; }

    public string Name => Preset.Name;
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

    private readonly ISidecarRunner _runner;
    private readonly IHistoryService _history;
    private readonly ObservableCollection<UniversalMatchItem> _displayed = [];
    private List<UniversalMatchItem> _all = [];
    private List<string> _selectedFiles = [];
    private string? _searchTerm;

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
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _history = App.Services.GetRequiredService<IHistoryService>();
        MatchList.ItemsSource = _displayed;
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        if (e.DataView.Contains(StandardDataFormats.StorageItems))
        {
            e.AcceptedOperation = DataPackageOperation.Copy;
            e.DragUIOverride.Caption = "Inspect for matching presets";
            e.DragUIOverride.IsCaptionVisible = true;
            e.DragUIOverride.IsContentVisible = true;
        }
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        var items = await e.DataView.GetStorageItemsAsync();
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
        DropHint.Text = "Drop files here, or pick them";
        StatusText.Text = "Drop files above to see matching presets.";
        FilterVisibility = Visibility.Collapsed;
        _all.Clear();
        _displayed.Clear();
    }

    private void SetFiles(List<string> paths)
    {
        _selectedFiles = paths;
        var first = Path.GetFileName(paths[0]);
        SelectedFilesText.Text = paths.Count == 1
            ? first
            : $"{first} +{paths.Count - 1} more";
        DropHint.Text = $"{paths.Count} file(s) selected";

        // Compute extension list (lowercase, no dot).
        var exts = paths.Select(p => Path.GetExtension(p).TrimStart('.').ToLowerInvariant())
                        .Where(e => !string.IsNullOrEmpty(e))
                        .ToList();

        var presets = UiPresetLoader.LoadAll();
        var matches = new List<UniversalMatchItem>();
        foreach (var p in presets)
        {
            var allowed = p.InputTypes.Select(s => s.TrimStart('.').ToLowerInvariant()).ToHashSet();
            var accepted = exts.Where(e => allowed.Count == 0 || allowed.Contains(e)).ToList();
            if (accepted.Count == 0 && allowed.Count > 0) continue;
            matches.Add(new UniversalMatchItem
            {
                Preset = p,
                AcceptedInputs = accepted,
                AllInputs = exts,
                Glyph = GlyphFor(p.Engine),
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

        var extSummary = string.Join(", ", exts.Distinct().Take(6));
        if (exts.Distinct().Count() > 6) extSummary += "...";
        StatusText.Text = matches.Count == 0
            ? $"No presets accept .{extSummary}. Try installing/wiring a sidecar for this format."
            : $"Found {matches.Count} preset(s) that accept .{extSummary}.";
    }

    private void Search_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput) return;
        _searchTerm = sender.Text;
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
        if (sender is not Button b || b.Tag is not string presetName) return;
        var card = _all.FirstOrDefault(c => c.Name == presetName);
        if (card is null) return;
        var preset = card.Preset;
        if (card.AcceptedInputs.Count == 0)
        {
            card.StatusText = "No accepted inputs.";
            return;
        }

        // Reuse the inputs we already collected; only the accepted-by-extension ones.
        var allowed = preset.InputTypes.Select(s => s.TrimStart('.').ToLowerInvariant()).ToHashSet();
        var inputs = _selectedFiles.Where(p =>
            allowed.Count == 0 ||
            allowed.Contains(Path.GetExtension(p).TrimStart('.').ToLowerInvariant())).ToList();

        // Output dir prompt for batch modes; per-file infers from template.
        string? outDir = null;
        if (preset.Mode != PresetInvocationMode.PerFile)
        {
            var folderPicker = new FolderPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
            folderPicker.FileTypeFilter.Add("*");
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
            WinRT.Interop.InitializeWithWindow.Initialize(folderPicker, hwnd);
            var folder = await folderPicker.PickSingleFolderAsync();
            if (folder is null) return;
            outDir = folder.Path;
        }

        card.StatusText = "Running...";
        var startedAt = DateTime.UtcNow;
        var result = await RunSidecarAsync(preset, inputs, outDir);
        card.StatusText = result.success ? "Done" : $"Failed ({result.code})";

        StatusText.Text = result.success
            ? $"{preset.Name} -- {inputs.Count} input(s), exit {result.exit}."
            : $"{preset.Name} -- {result.code}: {result.message ?? ""}";

        if (result.success && inputs.Count > 0)
        {
            var firstInput = inputs[0];
            string? firstOut = preset.Mode == PresetInvocationMode.PerFile
                ? UiPresetLoader.ResolveOutputPath(preset, firstInput)
                : (outDir is null ? null : Path.Combine(outDir,
                       Path.GetFileNameWithoutExtension(firstInput) + "." + preset.OutputExtension));
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
                Success = true,
                Profile = preset.Name,
            });
        }
    }

    private async Task<(bool success, string? code, string? message, int exit)> RunSidecarAsync(
        UiPreset preset, IReadOnlyList<string> inputs, string? outDir)
    {
        try
        {
            var args = new List<string>(preset.Args);
            using var cts = new CancellationTokenSource(TimeSpan.FromHours(1));

            switch (preset.Mode)
            {
                case PresetInvocationMode.PerFile:
                    {
                        int exit = 0;
                        foreach (var input in inputs)
                        {
                            var output = UiPresetLoader.ResolveOutputPath(preset, input);
                            var dir = Path.GetDirectoryName(output);
                            if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                            var perArgs = new List<string>(preset.Args)
                            { "--input", input, "--output", output };
                            var r = await _runner.RunAsync(preset.Engine, perArgs, null, null, cts.Token);
                            if (!r.Success) return (false, r.ErrorCode, r.ErrorMessage, r.ExitCode);
                            exit = r.ExitCode;
                        }
                        return (true, null, null, exit);
                    }
                case PresetInvocationMode.BatchOutputDir:
                    {
                        Directory.CreateDirectory(outDir!);
                        args.AddRange(["--output-dir", outDir!, "--input"]);
                        args.AddRange(inputs);
                        var r = await _runner.RunAsync(preset.Engine, args, null, null, cts.Token);
                        return (r.Success, r.ErrorCode, r.ErrorMessage, r.ExitCode);
                    }
                case PresetInvocationMode.BatchSingleOutput:
                    {
                        var first = inputs[0];
                        var output = outDir is null
                            ? UiPresetLoader.ResolveOutputPath(preset, first)
                            : Path.Combine(outDir, Path.GetFileNameWithoutExtension(first) + "." + preset.OutputExtension);
                        var dir = Path.GetDirectoryName(output);
                        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                        args.AddRange(["--output", output, "--input"]);
                        args.AddRange(inputs);
                        var r = await _runner.RunAsync(preset.Engine, args, null, null, cts.Token);
                        return (r.Success, r.ErrorCode, r.ErrorMessage, r.ExitCode);
                    }
                case PresetInvocationMode.ExtractEach:
                    {
                        int exit = 0;
                        foreach (var input in inputs)
                        {
                            var perOut = outDir is null
                                ? UiPresetLoader.ResolveOutputPath(preset, input)
                                : Path.Combine(outDir, Path.GetFileNameWithoutExtension(input));
                            Directory.CreateDirectory(perOut);
                            var perArgs = new List<string>(preset.Args)
                            { "--input", input, "--output-dir", perOut };
                            var r = await _runner.RunAsync(preset.Engine, perArgs, null, null, cts.Token);
                            if (!r.Success) return (false, r.ErrorCode, r.ErrorMessage, r.ExitCode);
                            exit = r.ExitCode;
                        }
                        return (true, null, null, exit);
                    }
            }
            return (false, "unknown_mode", null, -1);
        }
        catch (Exception ex)
        {
            Debug.WriteLine($"UniversalConvert: {ex}");
            return (false, "internal", ex.Message, -1);
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
        "whisper-cpp" or "whisper-stt" or "ai-subtitle" => "\uED1E",
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
