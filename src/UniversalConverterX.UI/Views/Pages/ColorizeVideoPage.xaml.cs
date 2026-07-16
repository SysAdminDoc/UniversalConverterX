using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

/// <summary>
/// Offline black-and-white to colour for images and video via the colorize
/// sidecar (OpenCV DNN, CPU). The ~123 MB model is downloaded once behind an
/// explicit licence-consent dialog; colourisation never downloads.
/// </summary>
public sealed partial class ColorizeVideoPage : Page
{
    private static readonly string[] ImageExts = [".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"];
    private static readonly string[] VideoExts = [".mp4", ".mkv", ".mov", ".m4v", ".avi", ".webm", ".ts"];

    private readonly ISidecarRunner _runner;
    private string? _sourcePath;
    private string? _outputPath;
    private bool _isVideo;
    private bool _modelReady;
    private bool _busy;
    private CancellationTokenSource? _cts;

    public ColorizeVideoPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _ = RefreshModelStatusAsync();
    }

    // ── Model status / download ──────────────────────────────────────────────

    private async Task RefreshModelStatusAsync()
    {
        if (_runner.Locate("colorize") is null)
        {
            ModelStatus.Text = "colorize engine not built (tools/colorize/build.ps1).";
            DownloadModelButton.IsEnabled = false;
            _modelReady = false;
            UpdateColorizeEnabled();
            return;
        }

        var ready = false;
        await _runner.RunAsync(
            "colorize", ["check-model"],
            onRawEvent: (name, payload) =>
            {
                if (name == "model_status" && payload.TryGetProperty("ready", out var r))
                    ready = r.ValueKind == JsonValueKind.True;
            });
        _modelReady = ready;
        ModelStatus.Text = ready
            ? "Model ready — colourisation runs offline on the CPU."
            : "Model not downloaded. The colourisation weights (BSD-2-Clause) are ~123 MB.";
        DownloadModelButton.IsEnabled = !_busy;
        DownloadModelButton.Content = ready ? "Re-verify model" : "Download model (123 MB)";
        UpdateColorizeEnabled();
    }

    private async void DownloadModel_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || _runner.Locate("colorize") is null) return;

        if (!_modelReady)
        {
            var dialog = new ContentDialog
            {
                XamlRoot = XamlRoot,
                Title = "Download the colourisation model?",
                Content = "This downloads the SHA-256 verified Colorful Image Colorization model "
                          + "(BSD-2-Clause, ~123 MB) into the local model cache. It runs on the CPU — "
                          + "no GPU required — and is never downloaded again during colourisation.",
                PrimaryButtonText = "Accept & download",
                CloseButtonText = "Cancel",
                DefaultButton = ContentDialogButton.Close,
            };
            if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        }

        _busy = true;
        DownloadModelButton.IsEnabled = false;
        ColorizeButton.IsEnabled = false;
        ModelStatus.Text = "Downloading model…";
        try
        {
            var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                ModelStatus.Text = $"Downloading model… {p.Percent:F0}% ({p.Stage})"));
            var result = await _runner.RunAsync(
                "colorize", ["download-model", "--accept-license"],
                progress, ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromHours(1));
            if (!result.Success)
                ModelStatus.Text = $"Download failed: {result.ErrorMessage ?? result.ErrorCode}. "
                    + "Set UCX_COLORIZE_MODEL_URL to a mirror if the source is unavailable.";
        }
        finally
        {
            _busy = false;
            await RefreshModelStatusAsync();
        }
    }

    // ── Input ────────────────────────────────────────────────────────────────

    private async void Open_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker { ViewMode = PickerViewMode.Thumbnail };
        foreach (var ext in ImageExts.Concat(VideoExts)) picker.FileTypeFilter.Add(ext);
        var handle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, handle);
        var file = await picker.PickSingleFileAsync();
        if (file is not null) LoadSource(file.Path);
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = "Colorize";
        e.DragUIOverride.IsCaptionVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems)) return;
        var items = await e.DataView.GetStorageItemsAsync();
        var file = items.OfType<StorageFile>().FirstOrDefault(f =>
        {
            var ext = Path.GetExtension(f.Path).ToLowerInvariant();
            return ImageExts.Contains(ext) || VideoExts.Contains(ext);
        });
        if (file is not null) LoadSource(file.Path);
    }

    private void LoadSource(string path)
    {
        _sourcePath = path;
        _outputPath = null;
        OutputBox.Text = "";
        var ext = Path.GetExtension(path).ToLowerInvariant();
        _isVideo = VideoExts.Contains(ext);

        EmptyState.Visibility = Visibility.Collapsed;
        PreviewPanel.Visibility = Visibility.Visible;
        if (!_isVideo)
            PreviewImage.Source = new BitmapImage(new Uri(path));
        else
            PreviewImage.Source = null;

        StatusText.Text = _isVideo
            ? $"{Path.GetFileName(path)} · video — colourises frame-by-frame on the CPU (slow for long clips)."
            : $"{Path.GetFileName(path)} · image.";
        UpdateColorizeEnabled();
    }

    private async void ChooseOutput_Click(object sender, RoutedEventArgs e)
    {
        if (_sourcePath is null) return;
        var picker = new FileSavePicker { SuggestedStartLocation = PickerLocationId.PicturesLibrary };
        var ext = _isVideo ? ".mp4" : ".png";
        picker.FileTypeChoices.Add(_isVideo ? "Video" : "Image", [ext]);
        picker.SuggestedFileName = Path.GetFileNameWithoutExtension(_sourcePath) + "_color";
        var handle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, handle);
        var file = await picker.PickSaveFileAsync();
        if (file is not null)
        {
            _outputPath = file.Path;
            OutputBox.Text = file.Path;
        }
    }

    private void UpdateColorizeEnabled() =>
        ColorizeButton.IsEnabled = !_busy && _modelReady && _sourcePath is not null;

    private string DefaultOutputPath()
    {
        var dir = Path.GetDirectoryName(_sourcePath!) ?? Path.GetTempPath();
        var stem = Path.GetFileNameWithoutExtension(_sourcePath!);
        return Path.Combine(dir, $"{stem}_color{(_isVideo ? ".mp4" : ".png")}");
    }

    // ── Colorize ─────────────────────────────────────────────────────────────

    private async void Colorize_Click(object sender, RoutedEventArgs e)
    {
        if (_busy || _sourcePath is null || !_modelReady) return;

        var output = _outputPath ?? DefaultOutputPath();
        _busy = true;
        _cts = new CancellationTokenSource();
        ColorizeButton.IsEnabled = false;
        DownloadModelButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        ColorizeProgress.Visibility = Visibility.Visible;
        ColorizeProgress.Value = 0;
        StatusText.Text = _isVideo ? "Colourising video…" : "Colourising image…";

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            ColorizeProgress.Value = Math.Clamp(p.Percent, 0, 100);
            StatusText.Text = $"Colourising… {p.Percent:F0}% — {p.Stage}";
        }));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync(
                "colorize",
                [_isVideo ? "video" : "image", "--input", _sourcePath, "--output", output],
                progress, null, _cts.Token,
                silenceTimeout: TimeSpan.FromHours(6));
        }
        catch (OperationCanceledException)
        {
            result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user", 130);
        }
        finally
        {
            _busy = false;
            _cts = null;
            CancelButton.IsEnabled = false;
            DownloadModelButton.IsEnabled = true;
            ColorizeProgress.Visibility = Visibility.Collapsed;
            UpdateColorizeEnabled();
        }

        if (result.Success)
        {
            StatusText.Text = $"Saved colourised {(_isVideo ? "video" : "image")} to {output}.";
            if (!_isVideo && File.Exists(output))
                PreviewImage.Source = new BitmapImage(new Uri(output));
        }
        else
        {
            StatusText.Text = result.ErrorCode == "cancelled"
                ? "Colourisation cancelled."
                : $"Colourisation failed: {result.ErrorMessage ?? result.ErrorCode}";
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => _cts?.Cancel();
}
