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

public sealed partial class ImageConverterPage : Page
{
    private static readonly string[] ImageExtensions =
    [
        ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp", ".gif",
        ".heic", ".heif", ".avif", ".jxl"
    ];

    private static readonly Dictionary<string, string> FormatExt = new(StringComparer.OrdinalIgnoreCase)
    {
        ["jpeg"] = ".jpg",
        ["png"]  = ".png",
        ["webp"] = ".webp",
        ["avif"] = ".avif",
        ["heic"] = ".heic",
        ["jxl"]  = ".jxl",
        ["tiff"] = ".tiff",
        ["bmp"]  = ".bmp",
    };

    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<ImgFileItem> _files = [];
    private readonly ObservableCollection<ImgFinishedItem> _finished = [];
    private CancellationTokenSource? _cts;

    private bool _isReady;

    public ImageConverterPage()
    {
        InitializeComponent();
        _isReady = true;
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        FileList.ItemsSource = _files;
        FinishedList.ItemsSource = _finished;
        UpdateQualityControls();
        UpdateUi();
    }

    // ── Drop zone ────────────────────────────────────────────────────────────

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = AppLocalizer.Get("Drop into convert queue");
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        var items = await DropSnapshotHelper.TrySnapshotDropAsync(e);
        if (items is null) return;
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
            SuggestedStartLocation = PickerLocationId.PicturesLibrary,
        };
        foreach (var ext in ImageExtensions)
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
        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path)
                     .Where(f => ImageExtensions.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase))
                     .Take(2000))
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

        _files.Add(new ImgFileItem
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
        if (sender is Button button && button.Tag is ImgFileItem item)
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
                $"Remove {_files.Count} queued image(s)? Finished conversions stay available."))
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
        UpdateQualityControls();
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

    private void Quality_Changed(object sender, RangeBaseValueChangedEventArgs e)
    {
        if (QualityValueText is null) return;
        QualityValueText.Text = ((int)e.NewValue).ToString(CultureInfo.InvariantCulture);
        var summary = BuildPlanSummary();
        foreach (var f in _files) f.PlanSummary = summary;
        UpdateStatusText();
    }

    private void TargetSize_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (!_isReady) return;
        UpdateQualityControls();
        RefreshPlanSummary();
    }

    private void EditNumber_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args)
    {
        if (!_isReady) return;
        RefreshPlanSummary();
    }

    private void EditText_Changed(object sender, TextChangedEventArgs e)
    {
        if (!_isReady) return;
        RefreshPlanSummary();
    }

    private void RefreshPlanSummary()
    {
        var summary = BuildPlanSummary();
        foreach (var file in _files) file.PlanSummary = summary;
        UpdateStatusText();
    }

    // ── Run ──────────────────────────────────────────────────────────────────

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _cts is not null) return;

        var format = SelectedFormat();
        var quality = (int)QualitySlider.Value;
        var stripExif = StripExifCheck.IsChecked == true;
        var stripIcc = StripIccCheck.IsChecked == true;
        var targetKb = TargetSizeBox.IsEnabled && !double.IsNaN(TargetSizeBox.Value)
            ? TargetSizeBox.Value
            : 0;
        var editArguments = BuildEditArguments();

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

                var outputPath = BuildOutputPath(item.Path, format);
                var args = new List<string>
                {
                    "convert",
                    "--input",   item.Path,
                    "--output",  outputPath,
                    "--format",  format,
                    "--quality", quality.ToString(CultureInfo.InvariantCulture),
                };
                if (targetKb > 0)
                {
                    args.Add("--target-kb");
                    args.Add(targetKb.ToString("0.###", CultureInfo.InvariantCulture));
                }
                args.AddRange(editArguments);
                if (stripExif) args.Add("--strip-exif");
                if (stripIcc)  args.Add("--strip-icc");

                item.Progress = 0;
                item.StatusText = "Converting";
                StatusText.Text = AppLocalizer.Format($"Converting {item.FileName}... ({completed + failed + 1}/{jobs.Count})");

                var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                {
                    item.Progress = p.Percent;
                    item.StatusText = string.IsNullOrEmpty(p.Stage) ? $"{p.Percent:F0}%" : p.Stage;
                }));
                var log = new Progress<SidecarLog>(_ => { });

                SidecarResult result;
                try
                {
                    result = await _runner.RunAsync("heicshift", args, progress, log, _cts.Token);
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
                ? AppLocalizer.Format($"Cancelled — {completed} converted, {failed} failed.")
                : AppLocalizer.Format($"Done — {completed} converted, {failed} failed.");

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

    // ── Helpers ──────────────────────────────────────────────────────────────

    private void AddFinishedItem(ImgFileItem item, SidecarResult result, string outputPath)
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
            details = result.ErrorMessage ?? "Conversion failed";
        }

        _finished.Insert(0, new ImgFinishedItem
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

        EmptyState.Visibility         = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility           = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        FinishedEmptyState.Visibility = hasFinished ? Visibility.Collapsed : Visibility.Visible;
        FinishedList.Visibility       = hasFinished ? Visibility.Visible : Visibility.Collapsed;

        RunButton.IsEnabled    = hasFiles && _cts is null;
        ClearButton.IsEnabled  = hasFiles && _cts is null;
        CancelButton.IsEnabled = _cts is not null;

        QueueSummaryText.Text = AppLocalizer.Format($"{_files.Count} queued / {_finished.Count} finished");
        CurrentSetupText.Text = BuildPlanSummary();

        if (updateStatus && _cts is null) UpdateStatusText();
    }

    private void UpdateStatusText()
    {
        StatusText.Text = _files.Count == 0
            ? AppLocalizer.Get("Drop images to start a conversion queue.")
            : AppLocalizer.Format($"Ready to convert {_files.Count} image(s). {BuildPlanSummary()}");
    }

    private string BuildPlanSummary()
    {
        if (FormatCombo is null) return "";
        var format = SelectedFormat();
        var lossy = IsQualityTargetFormat(format);
        var quality = QualitySlider is null ? 85 : (int)QualitySlider.Value;
        var targetKb = TargetSizeBox is not null && TargetSizeBox.IsEnabled &&
                       !double.IsNaN(TargetSizeBox.Value)
            ? TargetSizeBox.Value
            : 0;
        var meta = (StripExifCheck?.IsChecked == true ? "" : "EXIF ") +
                   (StripIccCheck?.IsChecked  == true ? "" : "ICC");
        if (string.IsNullOrWhiteSpace(meta)) meta = "no metadata";
        else                                 meta = "keep " + meta.Trim();
        var summary = targetKb > 0 ? $"{format.ToUpper()} ≤{targetKb:0.###} KB · {meta}"
                    : lossy ? $"{format.ToUpper()} q{quality} · {meta}"
                            : $"{format.ToUpper()} · {meta}";
        var preset = SelectedEditPreset();
        var custom = HasCustomEdits();
        if (!string.IsNullOrWhiteSpace(preset))
            summary += $" · {preset}";
        if (custom)
            summary += " · custom edits";
        return summary;
    }

    private List<string> BuildEditArguments()
    {
        var arguments = new List<string>();
        var preset = SelectedEditPreset();
        if (!string.IsNullOrWhiteSpace(preset))
        {
            arguments.Add("--adjust-preset");
            arguments.Add(preset);
        }

        AddNumberArgument(arguments, "--brightness", BrightnessBox);
        AddNumberArgument(arguments, "--contrast", ContrastBox);
        AddNumberArgument(arguments, "--saturation", SaturationBox);
        AddNumberArgument(arguments, "--sharpness", SharpnessBox);
        AddNumberArgument(arguments, "--blur", BlurBox);
        AddNumberArgument(arguments, "--hue", HueBox);
        AddNumberArgument(arguments, "--vignette", VignetteBox);
        AddNumberArgument(arguments, "--grain", GrainBox);
        if (GrayscaleCheck.IsChecked == true) arguments.Add("--grayscale");
        if (SepiaCheck.IsChecked == true) arguments.Add("--sepia");
        if (InvertCheck.IsChecked == true) arguments.Add("--invert");
        if (!string.IsNullOrWhiteSpace(TintBox.Text))
        {
            arguments.Add("--tint");
            arguments.Add(TintBox.Text.Trim());
        }
        if (NumberValue(BorderBox) > 0)
        {
            AddNumberArgument(arguments, "--border", BorderBox);
            arguments.Add("--border-color");
            arguments.Add(string.IsNullOrWhiteSpace(BorderColorBox.Text)
                ? "#ffffff"
                : BorderColorBox.Text.Trim());
        }
        return arguments;
    }

    private bool HasCustomEdits() =>
        NumberValue(BrightnessBox) != 0 || NumberValue(ContrastBox) != 0 ||
        NumberValue(SaturationBox) != 0 || NumberValue(SharpnessBox) != 0 ||
        NumberValue(BlurBox) != 0 || NumberValue(HueBox) != 0 ||
        NumberValue(VignetteBox) != 0 || NumberValue(GrainBox) != 0 ||
        NumberValue(BorderBox) != 0 || GrayscaleCheck.IsChecked == true ||
        SepiaCheck.IsChecked == true || InvertCheck.IsChecked == true ||
        !string.IsNullOrWhiteSpace(TintBox.Text);

    private string SelectedEditPreset() =>
        EditPresetCombo?.SelectedItem is ComboBoxItem { Tag: string tag } ? tag : "";

    private static void AddNumberArgument(List<string> arguments, string flag, NumberBox box)
    {
        var value = NumberValue(box);
        if (value == 0) return;
        arguments.Add(flag);
        arguments.Add(value.ToString("0.###", CultureInfo.InvariantCulture));
    }

    private static double NumberValue(NumberBox? box) =>
        box is null || double.IsNaN(box.Value) ? 0 : box.Value;

    private void UpdateQualityControls()
    {
        if (TargetSizeBox is null || QualitySlider is null) return;
        var supportsQuality = IsQualityTargetFormat(SelectedFormat());
        TargetSizeBox.IsEnabled = supportsQuality;
        var hasTarget = supportsQuality && !double.IsNaN(TargetSizeBox.Value) &&
                        TargetSizeBox.Value > 0;
        QualitySlider.IsEnabled = supportsQuality && !hasTarget;
    }

    private static bool IsQualityTargetFormat(string format) =>
        format is "jpeg" or "webp" or "avif" or "heic" or "jxl";

    private string SelectedFormat()
    {
        if (FormatCombo.SelectedItem is ComboBoxItem item && item.Tag is string tag)
            return tag;
        return "jpeg";
    }

    private static string BuildOutputPath(string inputPath, string format)
    {
        var ext = FormatExt.TryGetValue(format, out var e) ? e : ".out";
        var dir = Path.GetDirectoryName(inputPath) ?? Environment.CurrentDirectory;
        var name = Path.GetFileNameWithoutExtension(inputPath);
        return EnsureUniquePath(Path.Combine(dir, name + ext));
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
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{folder}\"") { UseShellExecute = true });
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
}

public sealed class ImgFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _planSummary = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string SourceSummary { get; set; } = "";

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

public sealed class ImgFinishedItem
{
    public string FileName { get; set; } = "";
    public string Details { get; set; } = "";
    public string OutputPath { get; set; } = "";
    public bool Success { get; set; }
    public string Glyph { get; set; } = "";
    public Brush? AccentBrush { get; set; }
    public bool CanOpenFolder => !string.IsNullOrWhiteSpace(OutputPath);
}
