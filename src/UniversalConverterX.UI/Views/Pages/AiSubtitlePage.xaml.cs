using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Text;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Models;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class AiSubtitlePage : Page
{
    private static readonly string[] AcceptedExtensions =
    [
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".ts", ".mts", ".m4v",
        ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ];

    private readonly ISidecarRunner _runner;
    private readonly ConverterXOptions _options;
    private readonly ObservableCollection<EditableSubtitleCue> _cues = [];
    private CancellationTokenSource? _cts;
    private string? _selectedPath;
    private string? _lastOutputPath;
    private string? _previewLanguageSuffix;

    public AiSubtitlePage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _options = App.Services.GetRequiredService<IOptions<ConverterXOptions>>().Value;
        CueList.ItemsSource = _cues;
        UpdateRunEnabled();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Drop a video or audio file";
        e.DragUIOverride.IsCaptionVisible = true;
        e.DragUIOverride.IsGlyphVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
            return;
        var items = await e.DataView.GetStorageItemsAsync();
        var first = items.OfType<StorageFile>().FirstOrDefault();
        if (first is not null)
            AcceptFile(first.Path);
    }

    private async void Browse_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var extension in AcceptedExtensions)
            picker.FileTypeFilter.Add(extension);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var file = await picker.PickSingleFileAsync();
        if (file is not null)
            AcceptFile(file.Path);
    }

    private void AcceptFile(string path)
    {
        if (!AcceptedExtensions.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase))
        {
            StatusText.Text = $"Unsupported extension {Path.GetExtension(path)}";
            return;
        }

        _selectedPath = path;
        _lastOutputPath = null;
        _previewLanguageSuffix = null;
        _cues.Clear();
        EditorPanel.Visibility = Visibility.Collapsed;
        DropZonePanel.Visibility = Visibility.Visible;
        DropZoneLabel.Text = Path.GetFileName(path);
        ProgressLabel.Text = "Choose transcription and translation settings, then generate a preview.";
        StatusText.Text = "Ready.";
        OpenOutputButton.IsEnabled = false;
        UpdateRunEnabled();
    }

    private void Settings_Changed(object sender, SelectionChangedEventArgs e) => UpdateRunEnabled();

    private void Settings_Bool_Changed(object sender, RoutedEventArgs e) => UpdateRunEnabled();

    private void Settings_Number_Changed(NumberBox sender, NumberBoxValueChangedEventArgs args) => UpdateRunEnabled();

    private void UpdateRunEnabled()
    {
        if (RunButton is null)
            return;

        var busy = _cts is not null;
        var translate = TranslateCheck?.IsChecked == true;
        RunButton.IsEnabled = _selectedPath is not null && !busy;
        if (ExportButton is not null)
            ExportButton.IsEnabled = _cues.Count > 0 && !busy;
        if (CancelButton is not null)
            CancelButton.IsEnabled = busy;
        if (TranslationModelCombo is not null)
            TranslationModelCombo.IsEnabled = translate && !busy;
        if (TargetLanguageCombo is not null)
            TargetLanguageCombo.IsEnabled = translate && !busy;
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedPath is null || _cts is not null)
            return;

        var backend = SelectedTag(BackendCombo) ?? "whisper-stt";
        var model = SelectedTag(ModelCombo) ?? "base";
        var language = SelectedTag(LanguageCombo) ?? "auto";
        var translate = TranslateCheck.IsChecked == true;
        var targetLanguage = SelectedTag(TargetLanguageCombo) ?? "es";
        var translationModel = SelectedTag(TranslationModelCombo) ?? "opus-mt";
        var useVad = VadCheck.IsChecked == true;
        var batchSize = SafeBatchSize(BatchSizeBox.Value);

        if (translate && language == "auto")
        {
            StatusText.Text = "Choose the source language before translation so the local model pair is deterministic.";
            return;
        }
        if (translate && language.Equals(targetLanguage, StringComparison.OrdinalIgnoreCase))
        {
            StatusText.Text = "Source and translation target languages must differ.";
            return;
        }

        var workDirectory = Path.Combine(
            Path.GetTempPath(),
            "UniversalConverterX",
            "subtitle-studio",
            Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(workDirectory);
        var transcriptPath = Path.Combine(workDirectory, "captions.srt");

        _cts = new CancellationTokenSource();
        UpdateRunEnabled();
        ProgressBar.Visibility = Visibility.Visible;
        ProgressBar.Value = 0;
        OpenOutputButton.IsEnabled = false;
        ProgressLabel.Text = $"Transcribing with {backend}, {model} model...";
        StatusText.Text = "Transcribing...";

        try
        {
            var sttArguments = BuildTranscriptionArguments(
                backend,
                _selectedPath,
                transcriptPath,
                model,
                language,
                useVad,
                batchSize);
            var transcriptionProgress = new Progress<SidecarProgress>(progress =>
                DispatcherQueue.TryEnqueue(() =>
                {
                    ProgressBar.Value = progress.Percent * (translate ? 0.7 : 1.0);
                    ProgressLabel.Text = string.IsNullOrEmpty(progress.Stage)
                        ? $"Transcribing - {progress.Percent:F0}%"
                        : $"{progress.Percent:F0}% - {progress.Stage}";
                }));

            var transcription = await _runner.RunAsync(
                backend,
                sttArguments,
                transcriptionProgress,
                null,
                _cts.Token);
            if (!transcription.Success)
            {
                StatusText.Text = transcription.ErrorMessage
                    ?? $"Transcription failed ({transcription.ErrorCode}).";
                return;
            }

            var previewPath = transcription.OutputPath ?? transcriptPath;
            _previewLanguageSuffix = null;
            if (translate)
            {
                StatusText.Text = "Translating captions locally...";
                ProgressLabel.Text = $"Translating {language} to {targetLanguage}...";
                var translationDirectory = Path.Combine(workDirectory, "translated");
                var translationProgress = new Progress<SidecarProgress>(progress =>
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        ProgressBar.Value = 70 + progress.Percent * 0.3;
                        ProgressLabel.Text = $"Translating - {progress.Percent:F0}% - {progress.Stage}";
                    }));
                var translation = await _runner.RunAsync(
                    "translatekit",
                    [
                        "srt",
                        "--input", previewPath,
                        "--output-dir", translationDirectory,
                        "--source", language,
                        "--target", targetLanguage,
                        "--model", translationModel,
                        "--device", "cpu",
                    ],
                    translationProgress,
                    null,
                    _cts.Token,
                    silenceTimeout: TimeSpan.FromMinutes(30));
                if (!translation.Success)
                {
                    StatusText.Text = translation.ErrorMessage
                        ?? $"Translation failed ({translation.ErrorCode}).";
                    return;
                }

                previewPath = Path.Combine(
                    translationDirectory,
                    $"{Path.GetFileNameWithoutExtension(previewPath)}.{targetLanguage}.srt");
                _previewLanguageSuffix = targetLanguage;
            }

            if (!File.Exists(previewPath))
            {
                StatusText.Text = "The pipeline completed without producing a subtitle preview.";
                return;
            }

            var content = await File.ReadAllTextAsync(previewPath, _cts.Token);
            var document = SubtitleDocument.ParseSrt(content);
            _cues.Clear();
            foreach (var cue in document.Cues)
            {
                _cues.Add(new EditableSubtitleCue
                {
                    Number = cue.Number,
                    StartSeconds = Math.Round(cue.Start.TotalSeconds, 3),
                    EndSeconds = Math.Round(cue.End.TotalSeconds, 3),
                    Text = cue.Text,
                });
            }

            CueSummaryText.Text = translate
                ? $"{_cues.Count} cues translated {language} -> {targetLanguage}. Edit text or timing before export."
                : $"{_cues.Count} cues. Edit text or timing before export.";
            DropZonePanel.Visibility = Visibility.Collapsed;
            EditorPanel.Visibility = Visibility.Visible;
            ProgressBar.Value = 100;
            StatusText.Text = "Preview ready. Review the cues, then export.";
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "Subtitle pipeline cancelled.";
        }
        catch (Exception exception)
        {
            StatusText.Text = $"Subtitle pipeline failed: {exception.Message}";
        }
        finally
        {
            try { Directory.Delete(workDirectory, recursive: true); } catch { }
            FinalCleanup();
        }
    }

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedPath is null || _cues.Count == 0 || _cts is not null)
            return;

        SubtitleDocument document;
        try
        {
            document = new SubtitleDocument(_cues.Select((cue, index) => new SubtitleCue(
                index + 1,
                TimeSpan.FromSeconds(cue.StartSeconds),
                TimeSpan.FromSeconds(cue.EndSeconds),
                cue.Text)));
        }
        catch (Exception exception)
        {
            StatusText.Text = $"Fix the preview before export: {exception.Message}";
            return;
        }

        var format = SelectedTag(FormatCombo) ?? "srt";
        var sourceDirectory = Path.GetDirectoryName(_selectedPath) ?? Environment.CurrentDirectory;
        var sourceStem = Path.GetFileNameWithoutExtension(_selectedPath);
        var languageSuffix = string.IsNullOrWhiteSpace(_previewLanguageSuffix)
            ? string.Empty
            : $".{_previewLanguageSuffix}";
        var subtitlePath = EnsureUniquePath(
            Path.Combine(sourceDirectory, $"{sourceStem}{languageSuffix}.{format}"));

        _cts = new CancellationTokenSource();
        UpdateRunEnabled();
        StatusText.Text = "Exporting edited preview...";
        try
        {
            await File.WriteAllTextAsync(
                subtitlePath,
                document.Serialize(format),
                new UTF8Encoding(encoderShouldEmitUTF8Identifier: false),
                _cts.Token);
            _lastOutputPath = subtitlePath;

            if (BurnInCheck.IsChecked == true && IsVideoFile(_selectedPath))
            {
                StatusText.Text = "Burning edited captions into video...";
                var burnedPath = EnsureUniquePath(Path.Combine(
                    sourceDirectory,
                    $"{sourceStem}{languageSuffix}_subtitled{Path.GetExtension(_selectedPath)}"));
                var burn = await BurnInAsync(
                    _selectedPath,
                    subtitlePath,
                    burnedPath,
                    _cts.Token);
                if (!burn.Success)
                {
                    StatusText.Text = $"Caption file exported, but burn-in failed: {burn.Error}";
                    OpenOutputButton.IsEnabled = true;
                    return;
                }

                _lastOutputPath = burnedPath;
                StatusText.Text = $"Done - {Path.GetFileName(burnedPath)}; {Path.GetFileName(subtitlePath)} kept alongside.";
            }
            else if (BurnInCheck.IsChecked == true)
            {
                StatusText.Text = $"Done - {Path.GetFileName(subtitlePath)}. Burn-in requires a video source.";
            }
            else
            {
                StatusText.Text = $"Done - {Path.GetFileName(subtitlePath)}";
            }

            OpenOutputButton.IsEnabled = true;
        }
        catch (OperationCanceledException)
        {
            StatusText.Text = "Export cancelled.";
        }
        catch (Exception exception)
        {
            StatusText.Text = $"Export failed: {exception.Message}";
        }
        finally
        {
            FinalCleanup();
        }
    }

    private static List<string> BuildTranscriptionArguments(
        string backend,
        string inputPath,
        string outputPath,
        string model,
        string language,
        bool useVad,
        int batchSize)
    {
        List<string> arguments;
        if (backend == "whisper-cpp")
        {
            arguments =
            [
                "transcribe",
                "--input", inputPath,
                "--output", outputPath,
                "--model", model,
                "--language", language,
            ];
        }
        else
        {
            arguments =
            [
                "--input", inputPath,
                "--output", outputPath,
                "--model", model,
                "--language", language,
                "--format", "srt",
                "--batch-size", batchSize.ToString(CultureInfo.InvariantCulture),
            ];
        }

        if (useVad)
            arguments.Add("--vad");
        return arguments;
    }

    private async Task<(bool Success, string? Error)> BurnInAsync(
        string videoPath,
        string subtitlePath,
        string outputPath,
        CancellationToken cancellationToken)
    {
        var ffmpeg = FindFfmpeg(_options.ToolsBasePath);
        if (ffmpeg is null)
            return (false, "FFmpeg was not found in the managed tools directory or PATH.");

        var workDirectory = Path.Combine(
            Path.GetTempPath(),
            "UniversalConverterX",
            "subtitle-burn",
            Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(workDirectory);
            // The subtitles filter has its own expression parser in addition
            // to normal argv parsing. Stage under a generated safe path so
            // user filenames containing quotes, brackets, commas, or
            // semicolons cannot be reinterpreted by that parser.
            var stagedSubtitle = Path.Combine(workDirectory, "captions" + Path.GetExtension(subtitlePath));
            File.Copy(subtitlePath, stagedSubtitle, overwrite: false);
            var escapedSubtitlePath = EscapeSubtitleFilterPath(stagedSubtitle);
            var startInfo = new ProcessStartInfo
            {
                FileName = ffmpeg,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                RedirectStandardError = true,
            };
            foreach (var argument in new[]
            {
                "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", videoPath,
                "-vf", $"subtitles='{escapedSubtitlePath}'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-c:a", "copy",
                outputPath,
            })
            {
                startInfo.ArgumentList.Add(argument);
            }

            using var process = Process.Start(startInfo);
            if (process is null)
                return (false, "FFmpeg could not be started.");
            var errorTask = process.StandardError.ReadToEndAsync(cancellationToken);
            try
            {
                await process.WaitForExitAsync(cancellationToken);
            }
            catch (OperationCanceledException)
            {
                try { if (!process.HasExited) process.Kill(entireProcessTree: true); } catch { }
                throw;
            }

            var error = await errorTask;
            var validOutput = process.ExitCode == 0
                && File.Exists(outputPath)
                && new FileInfo(outputPath).Length > 0;
            return validOutput
                ? (true, null)
                : (false, string.IsNullOrWhiteSpace(error)
                    ? $"FFmpeg exited with code {process.ExitCode}."
                    : error.Trim());
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception)
        {
            return (false, exception.Message);
        }
        finally
        {
            try { Directory.Delete(workDirectory, recursive: true); } catch { }
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

    private void OpenOutput_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(_lastOutputPath) || !File.Exists(_lastOutputPath))
            return;
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{_lastOutputPath}\"")
            {
                UseShellExecute = true,
            });
        }
        catch { }
    }

    private void FinalCleanup()
    {
        _cts?.Dispose();
        _cts = null;
        CancelButton.IsEnabled = false;
        ProgressBar.Visibility = Visibility.Collapsed;
        UpdateRunEnabled();
    }

    private static string? SelectedTag(ComboBox combo) =>
        combo.SelectedItem is ComboBoxItem { Tag: string tag } ? tag : null;

    private static int SafeBatchSize(double value) =>
        double.IsNaN(value) ? 8 : Math.Clamp((int)Math.Round(value), 1, 32);

    private static bool IsVideoFile(string path)
    {
        var extension = Path.GetExtension(path).ToLowerInvariant();
        return extension is ".mp4" or ".mkv" or ".mov" or ".avi" or ".webm" or ".flv"
            or ".wmv" or ".ts" or ".mts" or ".m4v";
    }

    private static string EscapeSubtitleFilterPath(string path) =>
        path.Replace("\\", "/", StringComparison.Ordinal)
            .Replace(":", "\\:", StringComparison.Ordinal)
            .Replace("'", "\\'", StringComparison.Ordinal)
            .Replace("[", "\\[", StringComparison.Ordinal)
            .Replace("]", "\\]", StringComparison.Ordinal)
            .Replace(",", "\\,", StringComparison.Ordinal)
            .Replace(";", "\\;", StringComparison.Ordinal);

    private static string? FindFfmpeg(string toolsBasePath)
    {
        var executable = OperatingSystem.IsWindows() ? "ffmpeg.exe" : "ffmpeg";
        var directCandidates = new[]
        {
            Path.Combine(toolsBasePath, "bin", executable),
            Path.Combine(toolsBasePath, executable),
            Path.Combine(AppContext.BaseDirectory, "tools", "bin", executable),
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "UniversalConverterX", "tools", "bin", executable),
        };
        foreach (var candidate in directCandidates)
        {
            if (File.Exists(candidate))
                return Path.GetFullPath(candidate);
        }

        foreach (var directory in (Environment.GetEnvironmentVariable("PATH") ?? "")
                     .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var candidate = Path.Combine(directory.Trim(), executable);
                if (File.Exists(candidate))
                    return Path.GetFullPath(candidate);
            }
            catch { }
        }

        return null;
    }

    private static string EnsureUniquePath(string path)
    {
        if (!File.Exists(path))
            return path;
        var directory = Path.GetDirectoryName(path) ?? ".";
        var name = Path.GetFileNameWithoutExtension(path);
        var extension = Path.GetExtension(path);
        for (var index = 1; index < 10_000; index++)
        {
            var candidate = Path.Combine(directory, $"{name} ({index}){extension}");
            if (!File.Exists(candidate))
                return candidate;
        }

        return Path.Combine(directory, $"{name}-{Guid.NewGuid():N}{extension}");
    }
}

public sealed class EditableSubtitleCue : INotifyPropertyChanged
{
    private double _startSeconds;
    private double _endSeconds;
    private string _text = string.Empty;

    public int Number { get; init; }

    public double StartSeconds
    {
        get => _startSeconds;
        set => SetField(ref _startSeconds, value);
    }

    public double EndSeconds
    {
        get => _endSeconds;
        set => SetField(ref _endSeconds, value);
    }

    public string Text
    {
        get => _text;
        set => SetField(ref _text, value);
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void SetField<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
            return;
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}
