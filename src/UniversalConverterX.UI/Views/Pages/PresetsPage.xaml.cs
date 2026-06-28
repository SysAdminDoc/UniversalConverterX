using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

#nullable enable

public sealed class PresetCardItem : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;
    public required UiPreset Preset { get; init; }
    public string Name => Preset.Name;
    public string Glyph { get; init; } = "\uE8B7";

    public string Subtitle
    {
        get
        {
            var parts = new List<string> { Preset.Engine };
            if (Preset.Folder is not null) parts.Add(Preset.Folder);
            parts.Add(Preset.InputTypes.Count == 0
                ? "any input"
                : string.Join(",", Preset.InputTypes.Take(8))
                  + (Preset.InputTypes.Count > 8 ? "..." : ""));
            parts.Add("-> ." + Preset.OutputExtension);
            return string.Join(" | ", parts);
        }
    }

    private string _statusText = "";
    public string StatusText
    {
        get => _statusText;
        set { if (_statusText != value) { _statusText = value; PropertyChanged?.Invoke(this, new(nameof(StatusText))); } }
    }

    private bool _canRun = true;
    public bool CanRun
    {
        get => _canRun;
        set { if (_canRun != value) { _canRun = value; PropertyChanged?.Invoke(this, new(nameof(CanRun))); } }
    }

    private string _healthDetail = "";
    public string HealthDetail
    {
        get => _healthDetail;
        set { if (_healthDetail != value) { _healthDetail = value; PropertyChanged?.Invoke(this, new(nameof(HealthDetail))); } }
    }
}

public sealed partial class PresetsPage : Page
{
    private readonly IPresetExecutor _executor;
    private readonly IHistoryService _history;
    private readonly IUiPresetCache _presetCache;
    private readonly ISidecarHealthService _health;
    private readonly ObservableCollection<PresetCardItem> _displayed = [];
    private List<PresetCardItem> _all = [];
    private readonly Dictionary<string, SidecarHealthReport> _healthByEngine = new(StringComparer.OrdinalIgnoreCase);
    private string? _engineFilter;
    private string? _searchTerm;

    /// <summary>Per-card lock so the same Run button can't double-fire if the user double-clicks.</summary>
    private readonly HashSet<string> _running = new(StringComparer.Ordinal);
    /// <summary>Cancels the in-flight search debounce when the user keeps typing.</summary>
    private CancellationTokenSource? _searchDebounce;

    /// <summary>Optional nav parameter: filter to a specific engine on first load.</summary>
    public string? InitialEngineFilter { get; set; }

    public PresetsPage()
    {
        InitializeComponent();
        _executor    = App.Services.GetRequiredService<IPresetExecutor>();
        _history     = App.Services.GetRequiredService<IHistoryService>();
        _presetCache = App.Services.GetRequiredService<IUiPresetCache>();
        _health      = App.Services.GetRequiredService<ISidecarHealthService>();
        PresetList.ItemsSource = _displayed;
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (e.Parameter is string filter && !string.IsNullOrWhiteSpace(filter))
            InitialEngineFilter = filter;
        Reload();
    }

    private void Reload()
    {
        // Force-refresh from disk on explicit reload — the user clicking the
        // refresh button is a clear signal they expect a fresh scan even if
        // the TTL hasn't expired.
        _presetCache.Invalidate();
        var presets = _presetCache.Get();
        _all = presets.Select(p => new PresetCardItem
        {
            Preset = p,
            Glyph = GlyphFor(p.Engine),
        }).ToList();
        RefreshHealth();

        // Populate engine filter combo (first item "(all engines)" stays).
        var engines = presets.Select(p => p.Engine).Distinct()
                             .OrderBy(s => s, StringComparer.OrdinalIgnoreCase).ToList();
        // Wipe everything except the first sentinel item.
        while (EngineFilter.Items.Count > 1) EngineFilter.Items.RemoveAt(1);
        foreach (var eng in engines)
            EngineFilter.Items.Add(new ComboBoxItem { Content = eng, Tag = eng });

        if (!string.IsNullOrEmpty(InitialEngineFilter))
        {
            for (int i = 0; i < EngineFilter.Items.Count; i++)
            {
                if (EngineFilter.Items[i] is ComboBoxItem ci
                    && string.Equals((ci.Tag as string) ?? "", InitialEngineFilter, StringComparison.OrdinalIgnoreCase))
                {
                    EngineFilter.SelectedIndex = i;
                    _engineFilter = InitialEngineFilter;
                    break;
                }
            }
            InitialEngineFilter = null;
        }
        else if (EngineFilter.SelectedIndex < 0)
        {
            EngineFilter.SelectedIndex = 0;
        }

        ApplyFilter();
        var dirs = UiPresetLoader.ResolvePresetDirs();
        // GetFileName returns empty for trailing-slash paths — fall back to the
        // last directory segment so the status line never shows ", , ,".
        StatusText.Text = $"Loaded {_all.Count} preset(s) from "
                        + string.Join(", ", dirs.Select(d =>
                              Path.GetFileName(d.TrimEnd(Path.DirectorySeparatorChar,
                                                        Path.AltDirectorySeparatorChar))));
    }

    private void RefreshHealth()
    {
        _healthByEngine.Clear();
        foreach (var report in _health.EvaluateAll(_all.Select(c => c.Preset)))
            _healthByEngine[report.Engine] = report;

        foreach (var card in _all)
        {
            if (!_healthByEngine.TryGetValue(card.Preset.Engine, out var report))
            {
                card.CanRun = false;
                card.StatusText = "Health unavailable";
                card.HealthDetail = "Dependency health could not be evaluated.";
                continue;
            }

            card.CanRun = report.CanRun;
            card.StatusText = report.Summary;
            card.HealthDetail = report.Detail;
        }
    }

    private void ApplyFilter()
    {
        IEnumerable<PresetCardItem> q = _all;
        if (!string.IsNullOrEmpty(_engineFilter))
            q = q.Where(c => string.Equals(c.Preset.Engine, _engineFilter, StringComparison.OrdinalIgnoreCase));
        if (!string.IsNullOrWhiteSpace(_searchTerm))
        {
            var s = _searchTerm.Trim();
            q = q.Where(c =>
                c.Name.Contains(s, StringComparison.OrdinalIgnoreCase)
                || (c.Preset.Folder?.Contains(s, StringComparison.OrdinalIgnoreCase) ?? false)
                || c.Preset.Engine.Contains(s, StringComparison.OrdinalIgnoreCase)
                || c.Preset.InputTypes.Any(e => e.Contains(s, StringComparison.OrdinalIgnoreCase)));
        }
        _displayed.Clear();
        foreach (var c in q) _displayed.Add(c);
        EmptyState.Visibility = _displayed.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        PresetScroll.Visibility = _displayed.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        UpdateHealthPanel();
    }

    private void UpdateHealthPanel()
    {
        var visibleReports = _displayed
            .Select(c => _healthByEngine.TryGetValue(c.Preset.Engine, out var report) ? report : null)
            .Where(r => r is not null)
            .DistinctBy(r => r!.Engine, StringComparer.OrdinalIgnoreCase)
            .Select(r => r!)
            .ToList();

        if (visibleReports.Count == 0)
        {
            HealthPanelTitle.Text = "Preset health";
            HealthPanelSummary.Text = "No visible preset engines to check.";
            HealthPanelDetails.Text = "";
            return;
        }

        var blocked = visibleReports.Where(r => !r.CanRun).ToList();
        var warnings = visibleReports
            .Where(r => r.CanRun && r.Requirements.Any(req => req.Status == "Warning"))
            .ToList();
        HealthPanelTitle.Text = blocked.Count == 0
            ? "Preset health: ready"
            : $"Preset health: {blocked.Count} blocked engine(s)";
        HealthPanelSummary.Text = $"{visibleReports.Count} engine(s) visible - {blocked.Count} blocked - {warnings.Count} warning(s)";
        HealthPanelDetails.Text = blocked.Count > 0
            ? string.Join("  |  ", blocked.Take(4).Select(r => $"{r.Engine}: {r.Detail}"))
            : warnings.Count > 0
                ? string.Join("  |  ", warnings.Take(4).Select(r => $"{r.Engine}: {r.Detail}"))
                : "All visible preset engines have their sidecar binary and required external tools available.";
    }

    private void Reload_Click(object sender, RoutedEventArgs e) => Reload();

    private async void Search_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput) return;
        _searchTerm = sender.Text;

        // Debounce so a fast typist doesn't trigger 200 ItemsSource resets in a
        // row — the filter itself is in-memory but each rebuild thrashes the
        // UI virtualization.
        _searchDebounce?.Cancel();
        _searchDebounce?.Dispose();
        var cts = new CancellationTokenSource();
        _searchDebounce = cts;
        try { await Task.Delay(TimeSpan.FromMilliseconds(120), cts.Token); }
        catch (OperationCanceledException) { return; }
        if (cts.IsCancellationRequested) return;
        ApplyFilter();
    }

    private void EngineFilter_Changed(object sender, SelectionChangedEventArgs e)
    {
        _engineFilter = (EngineFilter.SelectedItem as ComboBoxItem)?.Tag as string;
        if (string.IsNullOrEmpty(_engineFilter)) _engineFilter = null;
        ApplyFilter();
    }

    private async void RunPreset_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button b || b.Tag is not string presetName) return;
        var card = _all.FirstOrDefault(c => c.Name == presetName);
        if (card is null) return;
        var preset = card.Preset;
        var health = _health.Evaluate(preset);
        _healthByEngine[preset.Engine] = health;
        card.CanRun = health.CanRun;
        card.StatusText = health.Summary;
        card.HealthDetail = health.Detail;
        UpdateHealthPanel();
        if (!health.CanRun)
        {
            StatusText.Text = $"{preset.Name} blocked: {health.Detail}";
            return;
        }

        // Per-card guard — multiple clicks on the same Run button while the
        // first invocation is still in flight used to spawn parallel sidecars.
        if (!_running.Add(preset.Name))
        {
            card.StatusText = "Already running...";
            return;
        }

        try
        {
            // 1) File picker (filtered by preset's input extensions, or wildcard).
            var picker = new FileOpenPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
            if (preset.InputTypes.Count == 0)
                picker.FileTypeFilter.Add("*");
            else
                foreach (var ext in preset.InputTypes) picker.FileTypeFilter.Add("." + ext);

            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
            WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
            var files = await picker.PickMultipleFilesAsync();
            if (files is null || files.Count == 0) return;

            var inputs = files.Select(f => f.Path).ToList();

            // 2) Output dir for batch / extract-each modes; per-file mode resolves
            // each output via the preset's template, so we just need the parent dir.
            string? outDir = null;
            if (preset.Mode != PresetInvocationMode.PerFile)
            {
                var folderPicker = new FolderPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
                folderPicker.FileTypeFilter.Add("*");
                WinRT.Interop.InitializeWithWindow.Initialize(folderPicker, hwnd);
                var folder = await folderPicker.PickSingleFolderAsync();
                if (folder is null) return;
                outDir = folder.Path;
            }

            card.StatusText = "Running...";
            var startedAt = DateTime.UtcNow;
            using var cts = new CancellationTokenSource(TimeSpan.FromHours(1));
            var result = await _executor.RunAsync(preset, inputs, outDir, cancellationToken: cts.Token);
            card.StatusText = result.Success ? "Done" : $"Failed ({result.ErrorCode})";

            StatusText.Text = result.Success
                ? $"{preset.Name} -- {inputs.Count} input(s), exit {result.ExitCode}."
                : $"{preset.Name} -- {result.ErrorCode}: {result.ErrorMessage ?? ""}";

            // Always log the attempt — distinguishing success from failure in
            // the History dashboard is exactly what the user needs to debug a
            // recurring sidecar problem.
            var firstInput = inputs[0];
            string? firstOut = !result.Success ? null : (preset.Mode == PresetInvocationMode.PerFile
                ? UiPresetLoader.ResolveOutputPath(preset, firstInput)
                : (outDir is null ? null : Path.Combine(outDir,
                    Path.GetFileNameWithoutExtension(firstInput) + "." + preset.OutputExtension)));
            _ = _history.LogAsync(new HistoryRecord
            {
                Timestamp = startedAt,
                Engine = preset.Engine,
                Action = "preset",
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
        catch (Exception ex)
        {
            Debug.WriteLine($"PresetRun: {ex}");
            card.StatusText = $"Failed ({ex.GetType().Name})";
        }
        finally
        {
            _running.Remove(preset.Name);
        }
    }

    private static string GlyphFor(string engine) => engine switch
    {
        "videocrush"   => "\uE714",   // play
        "clipforge"    => "\uE71D",   // film
        "gifstudio"    => "\uE909",   // gif
        "heicshift"    => "\uEB9F",   // image
        "framesnap"    => "\uE722",   // camera
        "rnnoise"      => "\uE767",   // microphone
        "edge-tts"     => "\uEC4F",   // speech
        "whisper-cpp"  => "\uED1E",
        "whisper-stt"  => "\uED1E",
        "demucs"       => "\uE767",
        "gfpgan"       => "\uE77B",
        "alphacut"     => "\uE91B",
        "anime-upscale" => "\uE799",
        "video-face-enhance" => "\uE77B",
        "lipsight"     => "\uE909",
        "recordcast"   => "\uE714",
        "vertigo"      => "\uE740",
        "realesrgan"   => "\uE799",
        "videosubtitleremover" => "\uE93B",
        "streamkeep"   => "\uE896",
        "scenedetect"  => "\uE71D",
        "chaptermark"  => "\uE8B7",
        "exiftool-meta" => "\uE8B7",
        "docconvert"   => "\uE8A5",
        "archive"      => "\uE7B8",
        "pdftools"     => "\uEA90",
        "subconvert"   => "\uE93B",
        "fontconvert"  => "\uE8D2",
        "ebookconvert" => "\uE82D",
        "ocr"          => "\uE8A1",
        "meshconvert"  => "\uF158",   // 3D
        "pandoc-cli"   => "\uE8A5",
        "rawphoto"     => "\uEB9F",
        "pdfocr"       => "\uEA90",
        "gisconvert"   => "\uE707",   // globe
        _              => "\uE8B7",
    };

    private static long? TryFileSize(string path)
    {
        try { return new FileInfo(path).Length; } catch { return null; }
    }
}
