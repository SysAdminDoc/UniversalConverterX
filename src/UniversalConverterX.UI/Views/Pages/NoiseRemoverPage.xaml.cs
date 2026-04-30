using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class NoiseRemoverPage : Page
{
    private static readonly string[] AudioExtensions =
    [
        ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"
    ];

    private static readonly string[] VideoExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v"
    ];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<NrFileItem> _files = [];
    private readonly ObservableCollection<NrFinishedItem> _finished = [];
    private readonly List<ModelEntry> _models = [];
    private CancellationTokenSource? _cts;

    public NoiseRemoverPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        UpdateUi();
        _ = LoadModelsAsync();
    }

    // ── Model discovery ──────────────────────────────────────────────────────

    private async Task LoadModelsAsync()
    {
        ModelCombo.PlaceholderText = "Discovering...";
        ModelCombo.IsEnabled = false;
        _models.Clear();
        ModelCombo.Items.Clear();

        var harvested = new List<ModelEntry>();
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(10));

        try
        {
            var result = await _runner.RunAsync(
                "rnnoise",
                ["list-models"],
                ct: cts.Token,
                onRawEvent: (evName, root) =>
                {
                    if (evName != "model") return;
                    harvested.Add(new ModelEntry
                    {
                        Name = root.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "",
                        Path = root.TryGetProperty("path", out var p) ? p.GetString() ?? "" : "",
                        Location = root.TryGetProperty("location", out var l) ? l.GetString() ?? "" : "",
                    });
                });

            if (result.ErrorCode == "sidecar_not_found")
            {
                ModelHintText.Text = "Build the rnnoise sidecar first: pwsh tools/rnnoise/build.ps1";
                ModelCombo.PlaceholderText = "Sidecar not built";
                StatusText.Text = ModelHintText.Text;
                return;
            }
        }
        catch (OperationCanceledException)
        {
            ModelHintText.Text = "Model discovery timed out.";
            return;
        }

        _models.AddRange(harvested);
        if (_models.Count == 0)
        {
            ModelCombo.PlaceholderText = "No .rnnn models found";
            ModelHintText.Text = "Drop a .rnnn model under tools/rnnoise/models/ — cb.rnnn from github.com/GregorR/rnnoise-models is a solid default.";
        }
        else
        {
            foreach (var m in _models)
                ModelCombo.Items.Add(new ComboBoxItem
                {
                    Content = $"{m.Name} ({m.Location})",
                    Tag = m,
                });
            ModelCombo.SelectedIndex = 0;
            ModelCombo.IsEnabled = true;
            ModelHintText.Text = $"{_models.Count} model(s) discovered. Drop additional .rnnn files into tools/rnnoise/models/ to add more.";
        }
        UpdateUi();
    }

    private async void RefreshModels_Click(object sender, RoutedEventArgs e)
    {
        await LoadModelsAsync();
    }

    // ── Drop zone ────────────────────────────────────────────────────────────

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop into denoise queue";
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        var items = await e.DataView.GetStorageItemsAsync();
        foreach (var item in items)
        {
            switch (item)
            {
                case StorageFile file:
                    AddFile(file.Path);
                    break;
                case StorageFolder folder:
                    AddFolder(folder.Path);
                    break;
            }
        }
    }

    private void DropZone_PointerPressed(object sender, PointerRoutedEventArgs e)
    {
        if (e.Pointer.PointerDeviceType == Microsoft.UI.Input.PointerDeviceType.Mouse &&
            !e.GetCurrentPoint(null).Properties.IsLeftButtonPressed)
            return;
        if (_files.Count == 0 && QueuePivot.SelectedIndex == 0)
            BrowseFiles();
    }

    private void Browse_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.MusicLibrary,
        };
        foreach (var ext in AudioExtensions.Concat(VideoExtensions))
            picker.FileTypeFilter.Add(ext);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;
        foreach (var file in files) AddFile(file.Path);
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path)) return;
        var supported = AudioExtensions.Concat(VideoExtensions)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path)
                     .Where(f => supported.Contains(Path.GetExtension(f)))
                     .Take(500))
        {
            if (AddFile(file, updateUi: false)) added++;
        }
        StatusText.Text = added == 0
            ? "No supported audio/video files found in that folder."
            : $"Added {added} files from {path}.";
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => f.Path == path)) return false;
        var info = new FileInfo(path);
        if (!info.Exists) return false;

        var supported = AudioExtensions.Concat(VideoExtensions)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!supported.Contains(info.Extension)) return false;

        _files.Add(new NrFileItem
        {
            Path = path,
            FileName = info.Name,
            SourceSummary = $"{FormatSize(info.Length)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            IsVideo = VideoExtensions.Contains(info.Extension, StringComparer.OrdinalIgnoreCase),
            PlanSummary = BuildPlanSummary(),
            Progress = 0,
            StatusText = "Queued",
        });

        if (updateUi) UpdateUi();
        return true;
    }

    private void RemoveQueued_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null) return;
        if (sender is Button button && button.Tag is NrFileItem item)
        {
            _files.Remove(item);
            UpdateUi();
        }
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null || _files.Count == 0) return;
        if (!await PageDialogService.ConfirmClearAsync(
                this, "Clear queue?",
                $"Remove {_files.Count} queued file(s)? Finished tracks stay available."))
            return;
        _files.Clear();
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (EmptyState is null) return;
        UpdateUi();
    }

    private void Settings_Combo_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (RunButton is null) return;
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
        UpdateStatusText();
    }

    // ── Run ──────────────────────────────────────────────────────────────────

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null) return;
        if (ModelCombo.SelectedItem is not ComboBoxItem { Tag: ModelEntry model })
        {
            StatusText.Text = "No RNNoise model selected.";
            return;
        }

        var mode = SelectedMode();
        var audioExt = SelectedAudioExt();

        var jobs = _files.ToList();
        var completed = 0;
        var failed = 0;

        _cts = new CancellationTokenSource();
        RunButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        CancelButton.IsEnabled = true;

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested) break;

                var outputPath = BuildOutputPath(item, mode, audioExt);
                var args = new List<string>
                {
                    "denoise",
                    "--input",  item.Path,
                    "--output", outputPath,
                    "--model",  model.Path,
                };
                if (mode == "audio") args.Add("--audio-only");

                item.Progress = 0;
                item.StatusText = "Denoising";
                StatusText.Text = $"Denoising {item.FileName}... ({completed + failed + 1}/{jobs.Count})";

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = string.IsNullOrEmpty(p.Stage)
                        ? $"{p.Percent:F0}%"
                        : $"{p.Percent:F0}% - {p.Stage}";
                }));
                var log = new Progress<SidecarLog>(_ => { });

                SidecarResult result;
                try
                {
                    result = await _runner.RunAsync("rnnoise", args, progress, log, _cts.Token);
                }
                catch (OperationCanceledException)
                {
                    result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user.", 130);
                }

                if (result.Success)
                {
                    completed++;
                    item.Progress = 100;
                    item.StatusText = "Done";
                }
                else
                {
                    failed++;
                    item.StatusText = result.ErrorCode == "cancelled" ? "Cancelled" : "Failed";
                }

                AddFinishedItem(item, result, outputPath);

                if (result.ErrorCode == "cancelled") break;
            }

            StatusText.Text = _cts.IsCancellationRequested
                ? $"Cancelled — {completed} denoised, {failed} failed."
                : $"Done — {completed} denoised, {failed} failed.";

            if (_finished.Count > 0)
                QueuePivot.SelectedIndex = 1;
        }
        finally
        {
            _cts?.Dispose();
            _cts = null;
            UpdateUi(updateStatus: false);
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is { IsCancellationRequested: false })
        {
            _cts.Cancel();
            CancelButton.IsEnabled = false;
            StatusText.Text = "Cancelling...";
        }
    }

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string path)
            OpenContainingFolder(path);
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    private void AddFinishedItem(NrFileItem item, SidecarResult result, string outputPath)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush   = (Brush)Application.Current.Resources["AccentRedBrush"];

        string details;
        if (result.Success)
        {
            var size = result.SizeBytes ?? (File.Exists(outputPath) ? new FileInfo(outputPath).Length : 0);
            details = $"{item.PlanSummary} — {(size > 0 ? FormatSize(size) : "saved")}";
        }
        else
        {
            details = result.ErrorMessage ?? "Denoise failed";
        }

        _finished.Insert(0, new NrFinishedItem
        {
            FileName    = result.Success ? Path.GetFileName(outputPath) : item.FileName,
            Details     = details,
            OutputPath  = result.OutputPath ?? outputPath,
            Success     = result.Success,
            Glyph       = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasFiles    = _files.Count > 0;
        var hasFinished = _finished.Count > 0;
        var hasModel    = ModelCombo?.SelectedItem is not null;

        EmptyState.Visibility         = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility           = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility       = hasFinished ? Visibility.Visible : Visibility.Collapsed;

        RunButton.IsEnabled    = hasFiles && hasModel && _cts is null;
        ClearButton.IsEnabled  = hasFiles && _cts is null;
        CancelButton.IsEnabled = _cts is not null;

        QueueSummaryText.Text = $"{_files.Count} queued / {_finished.Count} finished";
        CurrentSetupText.Text = BuildPlanSummary();

        if (updateStatus && _cts is null)
            UpdateStatusText();
    }

    private void UpdateStatusText()
    {
        if (_files.Count == 0)
        {
            StatusText.Text = ModelCombo?.SelectedItem is null
                ? "Drop an .rnnn model into tools/rnnoise/models/, then add files."
                : "Drop audio or video files to start a denoise queue.";
            return;
        }
        StatusText.Text = $"Ready to denoise {_files.Count} file(s). {BuildPlanSummary()}";
    }

    private string BuildPlanSummary()
    {
        if (ModeCombo is null) return "";
        var mode = SelectedMode() == "audio" ? "audio-only" : "video + denoised audio";
        var ext = SelectedAudioExt().TrimStart('.').ToUpperInvariant();
        var modelName = (ModelCombo?.SelectedItem as ComboBoxItem)?.Tag is ModelEntry m
            ? m.Name : "no model";
        return $"{mode} · {ext} · {modelName}";
    }

    private string SelectedMode()
    {
        if (ModeCombo.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "muxed";
    }

    private string SelectedAudioExt()
    {
        if (AudioFormatCombo.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return ".wav";
    }

    private static string BuildOutputPath(NrFileItem item, string mode, string audioExt)
    {
        var dir = Path.GetDirectoryName(item.Path) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(item.Path);
        if (mode == "audio")
            return EnsureUniquePath(Path.Combine(dir, $"{name}_denoised{audioExt}"));
        // muxed: keep video container, just rename
        var ext = Path.GetExtension(item.Path);
        return EnsureUniquePath(Path.Combine(dir, $"{name}_denoised{ext}"));
    }

    private static string EnsureUniquePath(string path)
    {
        if (!File.Exists(path)) return path;
        var directory = Path.GetDirectoryName(path) ?? ".";
        var name = Path.GetFileNameWithoutExtension(path);
        var ext = Path.GetExtension(path);
        for (var i = 1; i < 10_000; i++)
        {
            var candidate = Path.Combine(directory, $"{name} ({i}){ext}");
            if (!File.Exists(candidate)) return candidate;
        }
        return Path.Combine(directory, $"{name}-{Guid.NewGuid():N}{ext}");
    }

    private static void OpenContainingFolder(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        var folder = Directory.Exists(path) ? path : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder)) return;
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", folder) { UseShellExecute = true });
        }
        catch { /* convenience only */ }
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1_073_741_824 => $"{bytes / 1_073_741_824.0:F1} GB",
        >= 1_048_576     => $"{bytes / 1_048_576.0:F1} MB",
        >= 1_024         => $"{bytes / 1_024.0:F1} KB",
        _                => $"{bytes} B",
    };

    private sealed class ModelEntry
    {
        public string Name { get; init; } = "";
        public string Path { get; init; } = "";
        public string Location { get; init; } = "";
    }
}

public sealed class NrFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _planSummary = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string SourceSummary { get; set; } = "";
    public bool IsVideo { get; set; }

    public double Progress
    {
        get => _progress;
        set => Set(ref _progress, value);
    }

    public string StatusText
    {
        get => _statusText;
        set => Set(ref _statusText, value);
    }

    public string PlanSummary
    {
        get => _planSummary;
        set => Set(ref _planSummary, value);
    }

    private void Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}

public sealed class NrFinishedItem
{
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush? AccentBrush { get; set; }
    public bool CanOpenFolder => !string.IsNullOrWhiteSpace(OutputPath);
}
