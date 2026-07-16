using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using UniversalConverterX.Core.Interfaces;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class FormatInspectorPage : Page
{
    private readonly IConversionOrchestrator _orchestrator;
    private readonly ObservableCollection<InspectorFileItem> _files = [];
    private readonly string? _ffprobePath;
    private bool _isInspecting;

    public FormatInspectorPage()
    {
        InitializeComponent();
        _orchestrator = App.Services.GetRequiredService<IConversionOrchestrator>();
        _ffprobePath = FindFfprobe();
        FileList.ItemsSource = _files;
        ToolStatusText.Text = _ffprobePath is null
            ? "Native signature detection is available. Install FFprobe or set FFPROBE_PATH for video/audio streams and codec metadata."
            : $"Native signature detection and FFprobe stream analysis are available. FFprobe: {_ffprobePath}";
        UpdateUi();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop files to inspect";
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
            return;

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
        if (_files.Count == 0)
            BrowseFiles();
    }

    private void BrowseFiles_Click(object sender, RoutedEventArgs e) => BrowseFiles();

    private async void BrowseFiles()
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.ComputerFolder,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var files = await picker.PickMultipleFilesAsync();
        if (files is null)
            return;

        foreach (var file in files)
            AddFile(file.Path);
    }

    private async void BrowseFolder_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker
        {
            SuggestedStartLocation = PickerLocationId.ComputerFolder,
        };
        picker.FileTypeFilter.Add("*");

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder is not null)
            AddFolder(folder.Path);
    }

    private void AddFolder(string path)
    {
        if (!Directory.Exists(path))
            return;

        var added = 0;
        foreach (var file in Directory.EnumerateFiles(path).Take(500))
        {
            if (AddFile(file, updateUi: false))
                added++;
        }

        StatusText.Text = added == 0
            ? "No new files were added from that folder."
            : $"Added {added} files from {path}.";
        UpdateUi();
    }

    private bool AddFile(string path, bool updateUi = true)
    {
        if (_files.Any(f => f.Path == path))
            return false;

        var info = new FileInfo(path);
        if (!info.Exists)
            return false;

        _files.Add(new InspectorFileItem
        {
            Path = path,
            FileName = info.Name,
            SourceSummary = $"{FormatSize(info.Length)} - {info.Extension.TrimStart('.').ToUpperInvariant()}",
            DetailText = "Not inspected",
            StatusText = "Queued",
            Progress = 0,
        });

        if (FileList.SelectedItem is null)
            FileList.SelectedIndex = 0;

        if (updateUi)
            UpdateUi();

        return true;
    }

    private async void Inspect_Click(object sender, RoutedEventArgs e)
    {
        if (_files.Count == 0 || _isInspecting)
            return;

        _isInspecting = true;
        InspectButton.IsEnabled = false;
        ClearButton.IsEnabled = false;
        StatusText.Text = $"Inspecting {_files.Count} files...";

        var completed = 0;
        foreach (var item in _files)
        {
            item.StatusText = "Inspecting";
            item.Progress = 35;
            try
            {
                await InspectFileAsync(item);
                item.Progress = 100;
                item.StatusText = "Ready";
                completed++;
            }
            catch (Exception ex)
            {
                item.Progress = 100;
                item.StatusText = "Failed";
                item.DetailText = "Inspection failed";
                item.Report = $"Inspection failed: {ex.Message}";
            }

            if (ReferenceEquals(FileList.SelectedItem, item))
                ShowReport(item);
        }

        _isInspecting = false;
        StatusText.Text = $"Inspected {completed} of {_files.Count} files.";
        UpdateUi(updateStatus: false);
    }

    private async Task InspectFileAsync(InspectorFileItem item)
    {
        var info = new FileInfo(item.Path);
        var detected = await _orchestrator.DetectFormatAsync(item.Path);
        item.Progress = 65;

        var targets = _orchestrator.GetOutputFormatsFor(item.Path)
            .Take(12)
            .ToArray();
        var report = new StringBuilder();
        report.AppendLine("File");
        report.AppendLine($"  Path: {item.Path}");
        report.AppendLine($"  Size: {FormatSize(info.Length)} ({info.Length:N0} bytes)");
        report.AppendLine($"  Modified: {info.LastWriteTime}");
        report.AppendLine();
        report.AppendLine("Detected format");
        report.AppendLine($"  Extension: {detected.Extension}");
        report.AppendLine($"  Category: {detected.Category}");
        report.AppendLine($"  MIME: {detected.MimeType}");
        report.AppendLine($"  Signature: {detected.Description ?? "Extension fallback"}");
        report.AppendLine();
        report.AppendLine("Conversion readiness");
        report.AppendLine(targets.Length == 0
            ? "  No direct UCX output targets were found for this extension."
            : $"  Suggested targets: {string.Join(", ", targets)}");

        var ffprobe = await ProbeWithFfprobeAsync(item.Path);
        if (!string.IsNullOrWhiteSpace(ffprobe))
        {
            report.AppendLine();
            report.AppendLine("FFprobe streams");
            report.Append(ffprobe);
        }

        item.Extension = detected.Extension.ToUpperInvariant();
        item.Category = detected.Category.ToString();
        item.MimeType = detected.MimeType;
        item.Signature = detected.Description ?? "Extension fallback";
        item.DetailText = $"{item.Category} - {item.Extension}";
        item.Report = report.ToString();
        item.Summary = $"{detected.Description ?? detected.Extension.ToUpperInvariant()} - {detected.MimeType}";
    }

    private async Task<string?> ProbeWithFfprobeAsync(string path)
    {
        if (_ffprobePath is null)
            return null;

        using var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = _ffprobePath,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            },
        };
        foreach (var arg in new[]
        {
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            path,
        })
        {
            process.StartInfo.ArgumentList.Add(arg);
        }

        process.Start();
        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        var stdout = await stdoutTask;
        var stderr = await stderrTask;

        if (process.ExitCode != 0 || string.IsNullOrWhiteSpace(stdout))
            return string.IsNullOrWhiteSpace(stderr) ? null : $"  FFprobe error: {stderr.Trim()}";

        return FormatFfprobeJson(stdout);
    }

    private static string FormatFfprobeJson(string json)
    {
        using var doc = JsonDocument.Parse(json);
        var report = new StringBuilder();
        var root = doc.RootElement;

        if (root.TryGetProperty("format", out var format))
        {
            report.AppendLine("  Container");
            AppendJsonField(report, format, "format_long_name", "    Format");
            AppendDuration(report, format);
            AppendJsonField(report, format, "bit_rate", "    Bitrate");
            AppendTags(report, format, "    ");
        }

        if (root.TryGetProperty("streams", out var streams) && streams.ValueKind == JsonValueKind.Array)
        {
            var index = 0;
            foreach (var stream in streams.EnumerateArray())
            {
                var type = ReadString(stream, "codec_type", "stream");
                var codec = ReadString(stream, "codec_name", "unknown");
                report.AppendLine($"  Stream {index}: {type} / {codec}");

                if (type == "video")
                {
                    var width = ReadString(stream, "width", "?");
                    var height = ReadString(stream, "height", "?");
                    report.AppendLine($"    Resolution: {width}x{height}");
                    AppendJsonField(report, stream, "pix_fmt", "    Pixel format");
                    AppendJsonField(report, stream, "avg_frame_rate", "    Frame rate");
                }
                else if (type == "audio")
                {
                    AppendJsonField(report, stream, "sample_rate", "    Sample rate");
                    AppendJsonField(report, stream, "channels", "    Channels");
                    AppendJsonField(report, stream, "channel_layout", "    Layout");
                }
                else
                {
                    AppendJsonField(report, stream, "codec_long_name", "    Codec");
                }

                AppendJsonField(report, stream, "duration", "    Duration");
                index++;
            }
        }

        return report.ToString();
    }

    private void FileList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (FileList.SelectedItem is InspectorFileItem item)
            ShowReport(item);
        else
            ClearReport();
        UpdateUi(updateStatus: false);
    }

    private void OpenFolder_Click(object sender, RoutedEventArgs e)
    {
        if (FileList.SelectedItem is InspectorFileItem item)
            OpenContainingFolder(item.Path);
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (_isInspecting)
            return;

        if (_files.Count == 0)
            return;

        if (!await PageDialogService.ConfirmClearAsync(
                this,
                "Clear inspection list?",
                $"Remove {_files.Count} file(s) and clear the current report?"))
        {
            return;
        }

        _files.Clear();
        ClearReport();
        UpdateUi();
    }

    private void ShowReport(InspectorFileItem item)
    {
        ReportEmpty.Visibility = Visibility.Collapsed;
        ReportPanel.Visibility = Visibility.Visible;
        ReportTitle.Text = item.FileName;
        ReportSummary.Text = string.IsNullOrWhiteSpace(item.Summary)
            ? item.SourceSummary
            : item.Summary;
        ReportDetails.Text = string.IsNullOrWhiteSpace(item.Report)
            ? "Click Inspect All to generate a full report."
            : item.Report;
    }

    private void ClearReport()
    {
        ReportEmpty.Visibility = Visibility.Visible;
        ReportPanel.Visibility = Visibility.Collapsed;
        ReportTitle.Text = "";
        ReportSummary.Text = "";
        ReportDetails.Text = "";
    }

    private void UpdateUi(bool updateStatus = true)
    {
        var hasFiles = _files.Count > 0;
        EmptyState.Visibility = hasFiles ? Visibility.Collapsed : Visibility.Visible;
        FileList.Visibility = hasFiles ? Visibility.Visible : Visibility.Collapsed;
        InspectButton.IsEnabled = hasFiles && !_isInspecting;
        ClearButton.IsEnabled = hasFiles && !_isInspecting;
        OpenFolderButton.IsEnabled = FileList.SelectedItem is InspectorFileItem;

        if (updateStatus && !_isInspecting)
            StatusText.Text = hasFiles
                ? $"Ready to inspect {_files.Count} files."
                : "Add files to inspect format signatures, streams, and conversion targets.";
    }

    private static void AppendDuration(StringBuilder report, JsonElement element)
    {
        var duration = ReadString(element, "duration", "");
        if (double.TryParse(duration, System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture, out var seconds))
        {
            report.AppendLine($"    Duration: {TimeSpan.FromSeconds(seconds):hh\\:mm\\:ss\\.fff}");
        }
    }

    private static void AppendTags(StringBuilder report, JsonElement element, string indent)
    {
        if (!element.TryGetProperty("tags", out var tags) || tags.ValueKind != JsonValueKind.Object)
            return;

        report.AppendLine($"{indent}Tags");
        foreach (var tag in tags.EnumerateObject().Take(10))
            report.AppendLine($"{indent}  {tag.Name}: {tag.Value}");
    }

    private static void AppendJsonField(StringBuilder report, JsonElement element, string property, string label)
    {
        var value = ReadString(element, property, "");
        if (!string.IsNullOrWhiteSpace(value) && value != "N/A")
            report.AppendLine($"{label}: {value}");
    }

    private static string ReadString(JsonElement element, string property, string fallback)
    {
        if (!element.TryGetProperty(property, out var value))
            return fallback;

        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString() ?? fallback,
            JsonValueKind.Number => value.ToString(),
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            _ => fallback,
        };
    }

    private static string? FindFfprobe()
    {
        var candidates = new List<string?>();
        candidates.Add(Environment.GetEnvironmentVariable("FFPROBE_PATH"));
        candidates.Add(Path.Combine(AppContext.BaseDirectory, "tools", "bin", "ffprobe.exe"));
        candidates.Add(Path.Combine(AppContext.BaseDirectory, "tools", "_bin", "ffprobe.exe"));

        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            candidates.Add(Path.Combine(dir.FullName, "tools", "bin", "ffprobe.exe"));
            candidates.Add(Path.Combine(dir.FullName, "tools", "_bin", "ffprobe.exe"));
            dir = dir.Parent;
        }

        var pathDirs = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator) ?? [];
        candidates.AddRange(pathDirs.Select(pathDir => Path.Combine(pathDir, "ffprobe.exe")));

        return candidates.FirstOrDefault(path => !string.IsNullOrWhiteSpace(path) && File.Exists(path));
    }

    private static void OpenContainingFolder(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
            return;

        var folder = Directory.Exists(path)
            ? path
            : Path.GetDirectoryName(path);
        if (string.IsNullOrWhiteSpace(folder) || !Directory.Exists(folder))
            return;

        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{folder}\"")
            {
                UseShellExecute = true,
            });
        }
        catch
        {
            // Convenience action only; keep inspection state intact if Explorer fails.
        }
    }

    private static string FormatSize(long bytes)
    {
        string[] suffixes = ["B", "KB", "MB", "GB", "TB"];
        var index = 0;
        double value = bytes;
        while (value >= 1024 && index < suffixes.Length - 1)
        {
            value /= 1024;
            index++;
        }

        return $"{value:F1} {suffixes[index]}";
    }
}

public sealed class InspectorFileItem : INotifyPropertyChanged
{
    private double _progress;
    private string _statusText = "";
    private string _detailText = "";
    private string _summary = "";
    private string _report = "";

    public event PropertyChangedEventHandler? PropertyChanged;

    public string Path { get; set; } = "";
    public string FileName { get; set; } = "";
    public string SourceSummary { get; set; } = "";
    public string Extension { get; set; } = "";
    public string Category { get; set; } = "";
    public string MimeType { get; set; } = "";
    public string Signature { get; set; } = "";

    public double Progress
    {
        get => _progress;
        set => SetProperty(ref _progress, value);
    }

    public string StatusText
    {
        get => _statusText;
        set => SetProperty(ref _statusText, value);
    }

    public string DetailText
    {
        get => _detailText;
        set => SetProperty(ref _detailText, value);
    }

    public string Summary
    {
        get => _summary;
        set => SetProperty(ref _summary, value);
    }

    public string Report
    {
        get => _report;
        set => SetProperty(ref _report, value);
    }

    private void SetProperty<T>(ref T storage, T value, [CallerMemberName] string propertyName = "")
    {
        if (EqualityComparer<T>.Default.Equals(storage, value))
            return;

        storage = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
