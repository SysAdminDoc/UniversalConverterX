using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class PhotoRestorationPage : Page
{
    private static readonly string[] ImageExtensions =
    [
        ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"
    ];

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<PrFileItem> _files = [];
    private readonly ObservableCollection<PrFinishedItem> _finished = [];
    private readonly List<PrModel> _models = [];
    private CancellationTokenSource? _cts;

    private bool _isReady;

    public PhotoRestorationPage()
    {
        InitializeComponent();
        _isReady = true;
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        UpdateUi();
        _ = LoadModelsAsync();
    }

    private async Task LoadModelsAsync()
    {
        ModelCombo.PlaceholderText = AppLocalizer.Get("Discovering...");
        ModelCombo.IsEnabled = false;
        _models.Clear();
        ModelCombo.Items.Clear();

        var harvested = new List<PrModel>();
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        var result = await _runner.RunAsync(
            "gfpgan",
            ["list-models"],
            ct: cts.Token,
            onRawEvent: (evName, root) =>
            {
                if (evName != "model") return;
                harvested.Add(new PrModel
                {
                    Name = root.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "",
                    Path = root.TryGetProperty("path", out var p) ? p.GetString() ?? "" : "",
                });
            });

        if (result.ErrorCode == "sidecar_not_found")
        {
            ModelHintText.Text = AppLocalizer.Get("Build the gfpgan sidecar first: pwsh tools/gfpgan/build.ps1");
            ModelCombo.PlaceholderText = AppLocalizer.Get("Sidecar not built");
            return;
        }

        _models.AddRange(harvested);
        if (_models.Count == 0)
        {
            ModelCombo.PlaceholderText = AppLocalizer.Get("No models found");
            ModelHintText.Text = AppLocalizer.Get("Drop GFPGANv1.4.pth into tools/gfpgan/models/. Source: github.com/TencentARC/GFPGAN/releases (Apache 2.0).");
        }
        else
        {
            foreach (var m in _models)
                ModelCombo.Items.Add(new ComboBoxItem { Content = m.Name, Tag = m });
            ModelCombo.SelectedIndex = 0;
            ModelCombo.IsEnabled = true;
            ModelHintText.Text = AppLocalizer.Format($"{_models.Count} model(s) discovered.");
        }
        UpdateUi();
    }

    private async void RefreshModels_Click(object sender, RoutedEventArgs e) => await LoadModelsAsync();

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Drop into restoration queue");
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
                case StorageFile file: AddFile(file.Path); break;
                case StorageFolder folder: AddFolder(folder.Path); break;
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
            ViewMode = PickerViewMode.Thumbnail,
            SuggestedStartLocation = PickerLocationId.PicturesLibrary,
        };
        foreach (var ext in ImageExtensions) picker.FileTypeFilter.Add(ext);
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var files = await picker.PickMultipleFilesAsync();
        if (files is null) return;
        foreach (var file in files) AddFile(file.Path);
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path)) return;
        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path)
                     .Where(f => ImageExtensions.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase))
                     .Take(500))
        {
            if (AddFile(file, updateUi: false)) added++;
        }
        StatusText.Text = added == 0
            ? AppLocalizer.Get("No supported images found in that folder.")
            : AppLocalizer.Format($"Added {added} files from {path}.");
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => f.Path == path)) return false;
        var info = new FileInfo(path);
        if (!info.Exists) return false;
        if (!ImageExtensions.Contains(info.Extension, StringComparer.OrdinalIgnoreCase)) return false;
        _files.Add(new PrFileItem
        {
            Path = path,
            FileName = info.Name,
            SourceSummary = $"{FormatSize(info.Length)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
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
        if (sender is Button button && button.Tag is PrFileItem item)
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
                $"Remove {_files.Count} queued photo(s)? Finished restorations stay available."))
            return;
        _files.Clear();
        UpdateUi();
    }

    private void QueuePivot_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (EmptyState is null) return;
        UpdateUi();
    }

    private void Settings_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (!_isReady) return;
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
        UpdateStatusText();
    }

    private void Settings_Bool_Changed(object sender, RoutedEventArgs e)
    {
        if (!_isReady) return;
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
        UpdateStatusText();
    }

    private void Weight_Changed(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (WeightLabel is null) return;
        var v = e.NewValue / 100.0;
        var hint = v switch
        {
            <= 0.30 => "subtle",
            <= 0.55 => "balanced",
            <= 0.75 => "strong",
            _ => "aggressive",
        };
        WeightLabel.Text = AppLocalizer.Format($"{v:F2} ({hint})");
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null) return;
        if (ModelCombo.SelectedItem is not ComboBoxItem { Tag: PrModel model })
        {
            StatusText.Text = AppLocalizer.Get("Pick a GFPGAN model first.");
            return;
        }
        var upscale = SelectedInt(UpscaleCombo, 2);
        var weight = WeightSlider.Value / 100.0;
        var onlyCenter = OnlyCenterCheck.IsChecked == true;

        var jobs = _files.ToList();
        var completed = 0; var failed = 0;

        _cts = new CancellationTokenSource();
        RunButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        CancelButton.IsEnabled = true;

        try
        {
            foreach (var item in jobs)
            {
                if (_cts.IsCancellationRequested) break;
                var outputPath = BuildOutputPath(item.Path);
                var args = new List<string>
                {
                    "restore",
                    "--input",   item.Path,
                    "--output",  outputPath,
                    "--model",   model.Path,
                    "--upscale", upscale.ToString(CultureInfo.InvariantCulture),
                    "--weight",  weight.ToString("F2", CultureInfo.InvariantCulture),
                };
                if (onlyCenter) args.Add("--only-center-face");

                item.Progress = 0;
                item.StatusText = "Restoring";
                StatusText.Text = AppLocalizer.Format($"Restoring {item.FileName}... ({completed + failed + 1}/{jobs.Count})");

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = string.IsNullOrEmpty(p.Stage) ? $"{p.Percent:F0}%" : p.Stage;
                }));
                var log = new Progress<SidecarLog>(_ => { });

                SidecarResult result;
                try
                {
                    // GFPGAN can be slow on first-run model load + CPU mode.
                    result = await _runner.RunAsync("gfpgan", args, progress, log, _cts.Token,
                        silenceTimeout: TimeSpan.FromMinutes(15));
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
                ? AppLocalizer.Format($"Cancelled — {completed} restored, {failed} failed.")
                : AppLocalizer.Format($"Done — {completed} restored, {failed} failed.");

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
            StatusText.Text = AppLocalizer.Get("Cancelling...");
        }
    }

    private void OpenFinishedFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string path)
            OpenContainingFolder(path);
    }

    private void AddFinishedItem(PrFileItem item, SidecarResult result, string outputPath)
    {
        var successBrush = (Brush)Application.Current.Resources["AccentGreenBrush"];
        var errorBrush = (Brush)Application.Current.Resources["AccentRedBrush"];
        var size = result.SizeBytes ?? (File.Exists(outputPath) ? new FileInfo(outputPath).Length : 0);
        var details = result.Success
            ? $"{item.PlanSummary} — {(size > 0 ? FormatSize(size) : "saved")}"
            : (result.ErrorMessage ?? "Restoration failed");
        _finished.Insert(0, new PrFinishedItem
        {
            FileName = result.Success ? Path.GetFileName(outputPath) : item.FileName,
            Details = details,
            OutputPath = result.OutputPath ?? outputPath,
            Success = result.Success,
            Glyph = result.Success ? "\uE73E" : "\uE711",
            AccentBrush = result.Success ? successBrush : errorBrush,
        });
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasFiles = _files.Count > 0;
        var hasFinished = _finished.Count > 0;
        var hasModel = ModelCombo?.SelectedItem is not null;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility = hasFinished ? Visibility.Visible : Visibility.Collapsed;
        RunButton.IsEnabled = hasFiles && hasModel && _cts is null;
        ClearButton.IsEnabled = hasFiles && _cts is null;
        CancelButton.IsEnabled = _cts is not null;
        QueueSummaryText.Text = AppLocalizer.Format($"{_files.Count} queued / {_finished.Count} finished");
        CurrentSetupText.Text = BuildPlanSummary();
        if (updateStatus && _cts is null) UpdateStatusText();
    }

    private void UpdateStatusText()
    {
        StatusText.Text = _files.Count == 0
            ? AppLocalizer.Get("Drop portrait photos to start a restoration queue.")
            : AppLocalizer.Format($"Ready to restore {_files.Count} photo(s). {BuildPlanSummary()}");
    }

    private string BuildPlanSummary()
    {
        if (UpscaleCombo is null) return "";
        var model = (ModelCombo?.SelectedItem as ComboBoxItem)?.Tag is PrModel m ? m.Name : "no model";
        var upscale = SelectedInt(UpscaleCombo, 2);
        var weight = WeightSlider is null ? 0.5 : WeightSlider.Value / 100.0;
        var only = OnlyCenterCheck?.IsChecked == true ? " · centre face" : "";
        return $"\u00d7{upscale} · w={weight:F2} · {model}{only}";
    }

    private static string BuildOutputPath(string inputPath)
    {
        var dir = Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(inputPath);
        var ext = Path.GetExtension(inputPath);
        if (string.IsNullOrEmpty(ext)) ext = ".png";
        return EnsureUniquePath(Path.Combine(dir, $"{name}_restored{ext}"));
    }

    private static string EnsureUniquePath(string path)
    {
        if (!File.Exists(path)) return path;
        var dir = Path.GetDirectoryName(path) ?? ".";
        var name = Path.GetFileNameWithoutExtension(path);
        var ext = Path.GetExtension(path);
        for (var i = 1; i < 10_000; i++)
        {
            var candidate = Path.Combine(dir, $"{name} ({i}){ext}");
            if (!File.Exists(candidate)) return candidate;
        }
        return Path.Combine(dir, $"{name}-{Guid.NewGuid():N}{ext}");
    }

    private static int SelectedInt(ComboBox combo, int fallback)
    {
        if (combo.SelectedItem is ComboBoxItem item &&
            int.TryParse(item.Tag?.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var v))
            return v;
        return fallback;
    }

    private static void OpenContainingFolder(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return;
        var folder = Directory.Exists(path) ? path : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder)) return;
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{folder}\"") { UseShellExecute = true });
        }
        catch { }
    }

    private static string FormatSize(long bytes) => bytes switch
    {
        >= 1_073_741_824 => $"{bytes / 1_073_741_824.0:F1} GB",
        >= 1_048_576 => $"{bytes / 1_048_576.0:F1} MB",
        >= 1_024 => $"{bytes / 1_024.0:F1} KB",
        _ => $"{bytes} B",
    };

    internal sealed class PrModel
    {
        public string Name { get; init; } = "";
        public string Path { get; init; } = "";
    }
}

public sealed class PrFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _planSummary = "";
    public event PropertyChangedEventHandler? PropertyChanged;
    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string SourceSummary { get; set; } = "";
    public double Progress { get => _progress; set => Set(ref _progress, value); }
    public string StatusText { get => _statusText; set => Set(ref _statusText, value); }
    public string PlanSummary { get => _planSummary; set => Set(ref _planSummary, value); }
    private void Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}

public sealed class PrFinishedItem
{
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush? AccentBrush { get; set; }
    public bool CanOpenFolder => !string.IsNullOrWhiteSpace(OutputPath);
}
