using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class ChapterMarksPage : Page
{
    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<ChapterRow> _rows = [];
    private string? _currentPath;
    private bool _isBusy;

    public ChapterMarksPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        ChapterList.ItemsSource = _rows;
        UpdateUi();
    }

    private async void OpenFile_Click(object sender, RoutedEventArgs e)
    {
        if (_isBusy)
            return;
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var extension in new[] { ".mp4", ".mkv", ".mov", ".m4v", ".m4a", ".m4b" })
            picker.FileTypeFilter.Add(extension);
        InitializePicker(picker);
        var file = await picker.PickSingleFileAsync();
        if (file is null)
            return;

        _currentPath = file.Path;
        SourceLabel.Text = Path.GetFileName(_currentPath);
        SourceMeta.Text = _currentPath;
        await LoadRowsAsync("read", _currentPath, replaceMediaStatus: true);
    }

    private async void Import_Click(object sender, RoutedEventArgs e)
    {
        if (_isBusy)
            return;
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
        };
        foreach (var extension in new[] { ".json", ".xml", ".txt", ".ogm" })
            picker.FileTypeFilter.Add(extension);
        InitializePicker(picker);
        var file = await picker.PickSingleFileAsync();
        if (file is null)
            return;

        await LoadRowsAsync("import", file.Path, replaceMediaStatus: false);
    }

    private async Task LoadRowsAsync(string operation, string input, bool replaceMediaStatus)
    {
        SetBusy(true);
        StatusText.Text = operation == "read" ? "Reading exact chapter timestamps..." : "Importing chapter list...";
        var harvested = new List<ChapterRow>();
        SidecarResult result;
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            result = await _runner.RunAsync(
                "chaptermark",
                [operation, "--input", input],
                ct: cts.Token,
                onRawEvent: (eventName, root) =>
                {
                    if (eventName == "chapter")
                        harvested.Add(ChapterRow.FromEvent(root));
                });
        }
        finally
        {
            SetBusy(false);
        }

        if (!result.Success)
        {
            StatusText.Text = result.ErrorCode == "sidecar_not_found"
                ? "Chapter Editor is not installed. Build it with tools/chaptermark/build.ps1."
                : $"Chapter {operation} failed: {result.ErrorMessage ?? result.ErrorCode}";
            return;
        }

        _rows.Clear();
        foreach (var row in harvested)
            _rows.Add(row);

        if (replaceMediaStatus)
        {
            StatusText.Text = harvested.Count == 0
                ? "No chapters in this media. Add or import markers, then save a new copy."
                : $"Loaded {harvested.Count} chapter(s) with exact PTS. Edit any field, then save a new copy.";
        }
        else
        {
            StatusText.Text = _currentPath is null
                ? $"Imported {harvested.Count} chapter(s). Open media before saving the chapter table."
                : $"Imported {harvested.Count} chapter(s). Save media to apply them without re-encoding.";
        }
        UpdateUi();
    }

    private void AddRow_Click(object sender, RoutedEventArgs e)
    {
        var lastEnd = 0m;
        if (_rows.Count > 0)
        {
            var last = _rows[^1];
            if (!decimal.TryParse(last.EndText, NumberStyles.Float, CultureInfo.InvariantCulture, out lastEnd)
                && decimal.TryParse(last.StartText, NumberStyles.Float, CultureInfo.InvariantCulture, out var start))
            {
                lastEnd = start + 60m;
            }
        }
        _rows.Add(new ChapterRow
        {
            StartText = lastEnd.ToString("0.#########", CultureInfo.InvariantCulture),
            EndText = "",
            Title = $"Chapter {_rows.Count + 1}",
        });
        StatusText.Text = _currentPath is null
            ? "Chapter added. Open media before saving."
            : "Chapter added.";
        UpdateUi();
    }

    private void RemoveRow_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button { Tag: ChapterRow row })
        {
            _rows.Remove(row);
            StatusText.Text = _rows.Count == 0
                ? "All chapters removed. Saving now will clear the media's chapter table."
                : "Chapter removed.";
            UpdateUi();
        }
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        if (_currentPath is null || _isBusy)
            return;
        if (!TryBuildChapterPayload(out var chapters, out var diagnostic))
        {
            StatusText.Text = diagnostic;
            return;
        }

        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
            SuggestedFileName = Path.GetFileNameWithoutExtension(_currentPath) + "_chapters",
        };
        var extension = Path.GetExtension(_currentPath);
        if (string.IsNullOrEmpty(extension))
            extension = ".mp4";
        picker.FileTypeChoices.Add(extension.TrimStart('.').ToUpperInvariant(), [extension]);
        InitializePicker(picker);
        var output = await picker.PickSaveFileAsync();
        if (output is null)
            return;

        var jsonPath = await WriteTemporaryPayloadAsync(chapters);
        SetBusy(true);
        try
        {
            StatusText.Text = extension.Equals(".mkv", StringComparison.OrdinalIgnoreCase)
                ? "Muxing exact chapters with MKVToolNix (stream copy)..."
                : "Muxing exact chapters with FFmpeg (stream copy)...";
            using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(30));
            var result = await _runner.RunAsync(
                "chaptermark",
                ["write", "--input", _currentPath, "--output", output.Path, "--chapters-json", jsonPath],
                ct: cts.Token);
            StatusText.Text = result.Success
                ? $"Saved {_rows.Count} chapter(s) to {Path.GetFileName(output.Path)}; exact PTS verification passed."
                : $"Save failed: {result.ErrorMessage ?? result.ErrorCode}";
        }
        finally
        {
            TryDelete(jsonPath);
            SetBusy(false);
        }
    }

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        if (_isBusy || _rows.Count == 0)
            return;
        if (!TryBuildChapterPayload(out var chapters, out var diagnostic))
        {
            StatusText.Text = diagnostic;
            return;
        }

        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
            SuggestedFileName = _currentPath is null
                ? "chapters"
                : Path.GetFileNameWithoutExtension(_currentPath) + "_chapters",
        };
        picker.FileTypeChoices.Add("Exact chapter JSON", [".json"]);
        picker.FileTypeChoices.Add("Matroska chapter XML", [".xml"]);
        picker.FileTypeChoices.Add("Simple chapter text", [".txt"]);
        InitializePicker(picker);
        var output = await picker.PickSaveFileAsync();
        if (output is null)
            return;

        var jsonPath = await WriteTemporaryPayloadAsync(chapters);
        SetBusy(true);
        try
        {
            StatusText.Text = "Exporting chapter list...";
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            var result = await _runner.RunAsync(
                "chaptermark",
                ["export", "--chapters-json", jsonPath, "--output", output.Path],
                ct: cts.Token);
            StatusText.Text = result.Success
                ? $"Exported {_rows.Count} chapter(s) to {Path.GetFileName(output.Path)}."
                : $"Export failed: {result.ErrorMessage ?? result.ErrorCode}";
        }
        finally
        {
            TryDelete(jsonPath);
            SetBusy(false);
        }
    }

    private bool TryBuildChapterPayload(
        out List<Dictionary<string, object?>> chapters,
        out string diagnostic)
    {
        chapters = [];
        diagnostic = "";
        decimal? previousStart = null;
        for (var index = 0; index < _rows.Count; index++)
        {
            var row = _rows[index];
            if (!decimal.TryParse(row.StartText, NumberStyles.Float, CultureInfo.InvariantCulture, out var start)
                || start < 0)
            {
                diagnostic = $"Chapter {index + 1}: start time must be a non-negative number.";
                return false;
            }
            if (previousStart is not null && start <= previousStart)
            {
                diagnostic = $"Chapter {index + 1}: start times must be strictly increasing.";
                return false;
            }
            previousStart = start;

            decimal? end = null;
            if (!string.IsNullOrWhiteSpace(row.EndText))
            {
                if (!decimal.TryParse(row.EndText, NumberStyles.Float, CultureInfo.InvariantCulture, out var parsedEnd)
                    || parsedEnd <= start)
                {
                    diagnostic = $"Chapter {index + 1}: end time must be after its start.";
                    return false;
                }
                end = parsedEnd;
            }

            var payload = new Dictionary<string, object?> { ["title"] = row.Title };
            if (row.CanReuseExactTimes)
            {
                payload["start_pts"] = row.StartPts;
                payload["end_pts"] = row.EndPts;
                payload["time_base"] = row.TimeBase;
            }
            else
            {
                payload["start"] = start.ToString(CultureInfo.InvariantCulture);
                payload["end"] = end?.ToString(CultureInfo.InvariantCulture);
            }
            chapters.Add(payload);
        }
        return true;
    }

    private static async Task<string> WriteTemporaryPayloadAsync(
        List<Dictionary<string, object?>> chapters)
    {
        var path = Path.Combine(Path.GetTempPath(), $"ucx_chapters_{Guid.NewGuid():N}.json");
        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(chapters));
        return path;
    }

    private void SetBusy(bool busy)
    {
        _isBusy = busy;
        UpdateUi();
    }

    private void UpdateUi()
    {
        var hasFile = _currentPath is not null;
        var hasRows = _rows.Count > 0;
        OpenFileButton.IsEnabled = !_isBusy;
        ImportButton.IsEnabled = !_isBusy;
        AddButton.IsEnabled = !_isBusy;
        SaveButton.IsEnabled = !_isBusy && hasFile;
        ExportButton.IsEnabled = !_isBusy && hasRows;
        EmptyState.Visibility = hasRows ? Visibility.Collapsed : Visibility.Visible;
        ChapterScroll.Visibility = hasRows ? Visibility.Visible : Visibility.Collapsed;
    }

    private static void InitializePicker(object picker)
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
    }

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch
        {
            // Best-effort cleanup of a private temporary JSON file.
        }
    }
}

public sealed class ChapterRow : INotifyPropertyChanged
{
    private string _startText = "0";
    private string _endText = "";
    private string _title = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    public string StartText { get => _startText; set => Set(ref _startText, value); }
    public string EndText { get => _endText; set => Set(ref _endText, value); }
    public string Title { get => _title; set => Set(ref _title, value); }
    public long? StartPts { get; init; }
    public long? EndPts { get; init; }
    public string? TimeBase { get; init; }
    public string? LoadedStartText { get; init; }
    public string? LoadedEndText { get; init; }

    public bool CanReuseExactTimes =>
        StartPts is not null
        && EndPts is not null
        && !string.IsNullOrWhiteSpace(TimeBase)
        && StartText == LoadedStartText
        && EndText == LoadedEndText;

    public static ChapterRow FromEvent(JsonElement root)
    {
        var startText = root.TryGetProperty("start_text", out var startLabel)
            ? startLabel.GetString() ?? "0"
            : root.TryGetProperty("start", out var start)
                ? start.GetDouble().ToString("0.#########", CultureInfo.InvariantCulture)
                : "0";
        var endText = root.TryGetProperty("end_text", out var endLabel)
            ? endLabel.GetString() ?? ""
            : root.TryGetProperty("end", out var end)
                ? end.GetDouble().ToString("0.#########", CultureInfo.InvariantCulture)
                : "";
        return new ChapterRow
        {
            StartText = startText,
            EndText = endText,
            Title = root.TryGetProperty("title", out var title) ? title.GetString() ?? "" : "",
            StartPts = root.TryGetProperty("start_pts", out var startPts) ? startPts.GetInt64() : null,
            EndPts = root.TryGetProperty("end_pts", out var endPts) ? endPts.GetInt64() : null,
            TimeBase = root.TryGetProperty("time_base", out var timeBase) ? timeBase.GetString() : null,
            LoadedStartText = startText,
            LoadedEndText = endText,
        };
    }

    private void Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
            return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}
