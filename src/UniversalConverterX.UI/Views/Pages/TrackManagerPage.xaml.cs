using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed class TrackRow : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;
    public int StreamIndex { get; init; }
    public string CodecType { get; init; } = "";
    public string CodecName { get; init; } = "";
    public string? Language { get; init; }
    public string? RawTitle { get; init; }
    public int? Channels { get; init; }
    public int? Width { get; init; }
    public int? Height { get; init; }
    public bool IsDefault { get; init; }

    public string IndexLabel => $"#{StreamIndex}";

    public string Title
    {
        get
        {
            if (!string.IsNullOrEmpty(RawTitle)) return RawTitle!;
            if (CodecType == "video"    && Width is int w && Height is int h)
                return $"{CodecName.ToUpperInvariant()} {w}x{h}";
            if (CodecType == "audio"    && Channels is int c)
                return $"{CodecName.ToUpperInvariant()} {c}ch";
            if (CodecType == "subtitle")
                return CodecName.ToUpperInvariant();
            return CodecName;
        }
    }

    public string Detail
    {
        get
        {
            var bits = new List<string>();
            if (!string.IsNullOrEmpty(Language)) bits.Add($"lang={Language}");
            if (IsDefault) bits.Add("default");
            if (CodecType == "video" && Width is int w && Height is int h)
                bits.Add($"{w}x{h}");
            if (CodecType == "audio" && Channels is int c) bits.Add($"{c}ch");
            return string.Join(" | ", bits);
        }
    }

    private bool _markedForRemoval;
    public bool MarkedForRemoval
    {
        get => _markedForRemoval;
        set
        {
            if (_markedForRemoval == value) return;
            _markedForRemoval = value;
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(MarkedForRemoval)));
        }
    }
}

public sealed partial class TrackManagerPage : Page
{
    private static readonly string[] VideoExts =
        [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<TrackRow> _tracks = [];
    private string? _currentPath;

    public TrackManagerPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        TracksList.ItemsSource = _tracks;
    }

    private async void OpenFile_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var ext in VideoExts) picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var f = await picker.PickSingleFileAsync();
        if (f is null) return;

        _currentPath = f.Path;
        SourceLabel.Text = Path.GetFileName(_currentPath);
        SourceMeta.Text = _currentPath;
        await LoadTracksAsync();
    }

    private async Task LoadTracksAsync()
    {
        if (_currentPath is null) return;
        _tracks.Clear();
        StatusText.Text = "Reading streams...";
        UpdateUi();

        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var result = await _runner.RunAsync(
            "clipforge",
            ["track-list", "--input", _currentPath],
            ct: cts.Token,
            onRawEvent: (evName, root) => DispatcherQueue.TryEnqueue(() =>
            {
                if (evName != "track") return;
                _tracks.Add(new TrackRow
                {
                    StreamIndex = root.TryGetProperty("stream_index", out var si) ? si.GetInt32() : -1,
                    CodecType   = root.TryGetProperty("codec_type", out var ct) ? ct.GetString() ?? "" : "",
                    CodecName   = root.TryGetProperty("codec_name", out var cn) ? cn.GetString() ?? "" : "",
                    Language    = root.TryGetProperty("language", out var lg) && lg.ValueKind == System.Text.Json.JsonValueKind.String ? lg.GetString() : null,
                    RawTitle    = root.TryGetProperty("title", out var t)   && t.ValueKind  == System.Text.Json.JsonValueKind.String ? t.GetString()  : null,
                    Channels    = TryInt(root, "channels"),
                    Width       = TryInt(root, "width"),
                    Height      = TryInt(root, "height"),
                    IsDefault   = root.TryGetProperty("default", out var d) && d.ValueKind == System.Text.Json.JsonValueKind.True,
                });
            }));

        if (result.ErrorCode == "sidecar_not_found")
        {
            StatusText.Text = "clipforge sidecar not built. Run pwsh tools/clipforge/build.ps1.";
        }
        else if (result.Success)
        {
            StatusText.Text = $"Loaded {_tracks.Count} stream(s). Tick to remove, then Apply.";
        }
        else
        {
            StatusText.Text = $"Failed to read tracks: {result.ErrorMessage ?? result.ErrorCode}";
        }
        UpdateUi();
    }

    private static int? TryInt(System.Text.Json.JsonElement root, string name) =>
        root.TryGetProperty(name, out var v) && v.ValueKind == System.Text.Json.JsonValueKind.Number
            ? v.GetInt32() : null;

    private void UpdateUi()
    {
        EmptyState.Visibility   = _tracks.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        TracksScroll.Visibility = _tracks.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        ApplyButton.IsEnabled   = _tracks.Count > 0;
        AddTrackButton.IsEnabled = _currentPath is not null;
    }

    private async void Apply_Click(object sender, RoutedEventArgs e)
    {
        if (_currentPath is null) return;
        var drop = _tracks.Where(t => t.MarkedForRemoval).Select(t => t.StreamIndex).ToList();
        if (drop.Count == 0)
        {
            StatusText.Text = "No streams marked for removal. Tick the rows to drop, then Apply.";
            return;
        }
        if (drop.Count >= _tracks.Count)
        {
            StatusText.Text = "Refusing to strip every stream -- leave at least one.";
            return;
        }

        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
            SuggestedFileName = Path.GetFileNameWithoutExtension(_currentPath) + "_tracks-edited",
        };
        var ext = Path.GetExtension(_currentPath);
        if (string.IsNullOrEmpty(ext)) ext = ".mkv";
        picker.FileTypeChoices.Add(ext.TrimStart('.').ToUpperInvariant(), [ext]);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var output = await picker.PickSaveFileAsync();
        if (output is null) return;

        StatusText.Text = $"Removing {drop.Count} stream(s) -- copy mux, no re-encode.";
        WorkProgress.Value = 0;
        ApplyButton.IsEnabled = false;

        var args = new List<string>
        {
            "track-remove",
            "--input",  _currentPath,
            "--output", output.Path,
            "--remove", string.Join(",", drop),
        };
        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            WorkProgress.Value = p.Percent;
        }));
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(20));
        var result = await _runner.RunAsync("clipforge", args, progress, null, cts.Token);
        StatusText.Text = result.Success
            ? $"Saved -> {Path.GetFileName(output.Path)}"
            : $"Failed: {result.ErrorMessage ?? result.ErrorCode}";
        ApplyButton.IsEnabled = true;
    }

    private async void AddTrack_Click(object sender, RoutedEventArgs e)
    {
        if (_currentPath is null) return;

        var pickAudio = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
        };
        foreach (var extraExt in new[] { ".mp3", ".aac", ".flac", ".ogg", ".opus", ".wav", ".m4a",
                                          ".srt", ".ass", ".vtt" })
            pickAudio.FileTypeFilter.Add(extraExt);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(pickAudio, hwnd);
        var extra = await pickAudio.PickSingleFileAsync();
        if (extra is null) return;

        // Quick metadata prompt: ask for ISO-639 lang (free-form; default empty).
        var langBox = new TextBox { Header = "Language code (ISO-639, optional)",
                                    PlaceholderText = "eng / jpn / fra / ..." };
        var titleBox = new TextBox { Header = "Track title (optional)" };
        var stack = new StackPanel { Spacing = 12, Width = 380 };
        stack.Children.Add(new TextBlock
        {
            Text = $"Attach: {extra.Name}",
            Style = (Style)Application.Current.Resources["LabelTextStyle"],
        });
        stack.Children.Add(langBox);
        stack.Children.Add(titleBox);
        var dlg = new ContentDialog
        {
            Title = "Add track",
            PrimaryButtonText = "Save as...",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
            Content = stack,
            XamlRoot = this.XamlRoot,
        };
        if (await dlg.ShowAsync() != ContentDialogResult.Primary) return;

        var savePicker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
            SuggestedFileName = Path.GetFileNameWithoutExtension(_currentPath) + "_with-track",
        };
        var ext = Path.GetExtension(_currentPath);
        if (string.IsNullOrEmpty(ext)) ext = ".mkv";
        savePicker.FileTypeChoices.Add(ext.TrimStart('.').ToUpperInvariant(), [ext]);
        WinRT.Interop.InitializeWithWindow.Initialize(savePicker, hwnd);
        var output = await savePicker.PickSaveFileAsync();
        if (output is null) return;

        var args = new List<string>
        {
            "track-add",
            "--input",  _currentPath,
            "--extra",  extra.Path,
            "--output", output.Path,
        };
        if (!string.IsNullOrWhiteSpace(langBox.Text))
            args.AddRange(["--language", langBox.Text.Trim()]);
        if (!string.IsNullOrWhiteSpace(titleBox.Text))
            args.AddRange(["--title", titleBox.Text.Trim()]);

        StatusText.Text = $"Attaching {Path.GetFileName(extra.Path)} -- copy mux, no re-encode.";
        WorkProgress.Value = 0;
        AddTrackButton.IsEnabled = false;

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            WorkProgress.Value = p.Percent;
        }));
        using var cts = new CancellationTokenSource(TimeSpan.FromMinutes(20));
        var result = await _runner.RunAsync("clipforge", args, progress, null, cts.Token);
        StatusText.Text = result.Success
            ? $"Saved -> {Path.GetFileName(output.Path)}. Open the new file to see the new track."
            : $"Failed: {result.ErrorMessage ?? result.ErrorCode}";
        AddTrackButton.IsEnabled = true;
    }
}
