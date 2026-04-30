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

    public ChapterMarksPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        ChapterList.ItemsSource = _rows;
    }

    private async void OpenFile_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var ext in new[] { ".mp4", ".mkv", ".mov", ".m4v", ".webm", ".ts" })
            picker.FileTypeFilter.Add(ext);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var file = await picker.PickSingleFileAsync();
        if (file is null) return;

        _currentPath = file.Path;
        SourceLabel.Text = Path.GetFileName(_currentPath);
        SourceMeta.Text = _currentPath;
        StatusText.Text = "Reading chapters...";
        _rows.Clear();
        UpdateUi();

        var harvested = new List<ChapterRow>();
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var result = await _runner.RunAsync(
            "chaptermark",
            ["read", "--input", _currentPath],
            ct: cts.Token,
            onRawEvent: (evName, root) =>
            {
                if (evName != "chapter") return;
                harvested.Add(new ChapterRow
                {
                    StartText = root.TryGetProperty("start", out var s) ? s.GetDouble().ToString("F3", CultureInfo.InvariantCulture) : "0",
                    EndText = root.TryGetProperty("end", out var en) ? en.GetDouble().ToString("F3", CultureInfo.InvariantCulture) : "",
                    Title = root.TryGetProperty("title", out var t) ? (t.GetString() ?? "") : "",
                });
            });

        if (result.ErrorCode == "sidecar_not_found")
        {
            StatusText.Text = "chaptermark sidecar not built. Run pwsh tools/chaptermark/build.ps1.";
            return;
        }

        foreach (var c in harvested) _rows.Add(c);

        StatusText.Text = harvested.Count == 0
            ? "No chapters in this file. Click Add Chapter to create the first one."
            : $"Loaded {harvested.Count} chapter(s). Edit any cell, then Save As...";
        UpdateUi();
    }

    private void AddRow_Click(object sender, RoutedEventArgs e)
    {
        // Default new chapter to start right after the last one.
        var lastEnd = 0.0;
        if (_rows.Count > 0)
        {
            var last = _rows[^1];
            if (double.TryParse(last.EndText, NumberStyles.Float, CultureInfo.InvariantCulture, out var v))
                lastEnd = v;
            else if (double.TryParse(last.StartText, NumberStyles.Float, CultureInfo.InvariantCulture, out var vs))
                lastEnd = vs + 60;
        }
        _rows.Add(new ChapterRow
        {
            StartText = lastEnd.ToString("F3", CultureInfo.InvariantCulture),
            EndText = "",
            Title = $"Chapter {_rows.Count + 1}",
        });
        UpdateUi();
    }

    private void RemoveRow_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.Tag is ChapterRow row)
        {
            _rows.Remove(row);
            UpdateUi();
        }
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        if (_currentPath is null || _rows.Count == 0) return;

        // Validate + serialize the chapter list to a temp JSON file.
        var chapters = new List<object>();
        for (int i = 0; i < _rows.Count; i++)
        {
            var r = _rows[i];
            if (!double.TryParse(r.StartText, NumberStyles.Float, CultureInfo.InvariantCulture, out var start))
            {
                StatusText.Text = $"Chapter {i + 1}: invalid start time '{r.StartText}'.";
                return;
            }
            double? end = null;
            if (!string.IsNullOrWhiteSpace(r.EndText))
            {
                if (!double.TryParse(r.EndText, NumberStyles.Float, CultureInfo.InvariantCulture, out var e1))
                {
                    StatusText.Text = $"Chapter {i + 1}: invalid end time '{r.EndText}'.";
                    return;
                }
                end = e1;
            }
            chapters.Add(new Dictionary<string, object?>
            {
                ["start"] = start,
                ["end"] = end,
                ["title"] = r.Title,
            });
        }

        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
            SuggestedFileName = Path.GetFileNameWithoutExtension(_currentPath) + "_chapters",
        };
        var ext = Path.GetExtension(_currentPath);
        if (string.IsNullOrEmpty(ext)) ext = ".mp4";
        picker.FileTypeChoices.Add(ext.TrimStart('.').ToUpperInvariant(), [ext]);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var output = await picker.PickSaveFileAsync();
        if (output is null) return;

        var jsonPath = Path.Combine(Path.GetTempPath(), $"ucx_chapters_{Guid.NewGuid():N}.json");
        await File.WriteAllTextAsync(jsonPath, JsonSerializer.Serialize(chapters));

        try
        {
            StatusText.Text = "Muxing chapters into output (codec copy)...";
            using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(10));
            var result = await _runner.RunAsync(
                "chaptermark",
                ["write",
                 "--input", _currentPath,
                 "--output", output.Path,
                 "--chapters-json", jsonPath],
                ct: cts.Token);

            StatusText.Text = result.Success
                ? $"Saved {_rows.Count} chapter(s) → {Path.GetFileName(output.Path)}"
                : $"Save failed: {result.ErrorMessage ?? result.ErrorCode}";
        }
        finally
        {
            try { File.Delete(jsonPath); } catch { }
        }
    }

    private void UpdateUi()
    {
        var hasFile = _currentPath is not null;
        var hasRows = _rows.Count > 0;
        AddButton.IsEnabled = hasFile;
        SaveButton.IsEnabled = hasFile && hasRows;
        EmptyState.Visibility = hasRows ? Visibility.Collapsed : Visibility.Visible;
        ChapterScroll.Visibility = hasRows ? Visibility.Visible : Visibility.Collapsed;
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
    private void Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}
