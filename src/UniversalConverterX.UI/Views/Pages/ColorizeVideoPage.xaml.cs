using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using UniversalConverterX.Core.ViewModels;
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
    private readonly ColorizeWorkflowViewModel _viewModel = new();
    private CancellationTokenSource? _cts;
    private bool _initialized;

    public ColorizeVideoPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        _initialized = true;
        _ = RefreshModelStatusAsync();
    }

    // ── Model status / download ──────────────────────────────────────────────

    private async Task RefreshModelStatusAsync()
    {
        var tier = SelectedTier();
        if (_runner.Locate("colorize") is null)
        {
            ModelStatus.Text = AppLocalizer.Get("colorize engine not built (tools/colorize/build.ps1).");
            DownloadModelButton.IsEnabled = false;
            _viewModel.ModelReady = false;
            UpdateColorizeEnabled();
            return;
        }

        var ready = false;
        var disabled = false;
        await _runner.RunAsync(
            "colorize", ["check-model", "--tier", tier],
            onRawEvent: (name, payload) =>
            {
                if (name == "model_status" && payload.TryGetProperty("ready", out var r))
                    ready = r.ValueKind == JsonValueKind.True;
                if (name == "model_status" && payload.TryGetProperty("disabled", out var d))
                    disabled = d.ValueKind == JsonValueKind.True;
            });
        _viewModel.ModelReady = ready;
        ModelStatus.Text = ready
            ? tier == "ddcolor-temporal"
                ? AppLocalizer.Get("DDColor temporal model ready — optical-flow stabilisation runs offline.")
                : AppLocalizer.Get("Model ready — colourisation runs offline on the CPU.")
            : disabled
                ? AppLocalizer.Get("DDColor temporal tier is disabled by policy (UCX_DISABLE_DDCOLOR).")
                : tier == "ddcolor-temporal"
                ? AppLocalizer.Get("DDColor temporal model not downloaded. The Apache-2.0 ONNX pack is ~113 MB.")
                : AppLocalizer.Get("Model not downloaded. The colourisation weights (BSD-2-Clause) are ~123 MB.");
        DownloadModelButton.IsEnabled = !_viewModel.IsBusy && !disabled;
        DownloadModelButton.Content = ready
            ? AppLocalizer.Get("Re-verify model")
            : tier == "ddcolor-temporal"
                ? AppLocalizer.Get("Download DDColor model (113 MB)")
                : AppLocalizer.Get("Download model (123 MB)");
        UpdateColorizeEnabled();
    }

    private async void Tier_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (!_initialized || TierCombo is null || _viewModel.IsBusy) return;
        await RefreshModelStatusAsync();
    }

    private async void DownloadModel_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel.IsBusy || _runner.Locate("colorize") is null) return;

        var tier = SelectedTier();
        if (!_viewModel.ModelReady)
        {
            var dialog = new ContentDialog
            {
                XamlRoot = XamlRoot,
                Title = tier == "ddcolor-temporal"
                    ? AppLocalizer.Get("Download the DDColor temporal model?")
                    : AppLocalizer.Get("Download the colourisation model?"),
                Content = tier == "ddcolor-temporal"
                    ? AppLocalizer.Get("This downloads the revision- and SHA-256-pinned DDColor ONNX pack (Apache-2.0, ~113 MB) into the local model cache. Video mode propagates chroma through optical flow and resets on scene cuts to reduce flicker. The pack is never downloaded during colourisation.")
                    : AppLocalizer.Get("This downloads the SHA-256 verified Colorful Image Colorization model (BSD-2-Clause, ~123 MB) into the local model cache. It runs on the CPU — no GPU required — and is never downloaded again during colourisation."),
                PrimaryButtonText = AppLocalizer.Get("Accept & download"),
                CloseButtonText = AppLocalizer.Get("Cancel"),
                DefaultButton = ContentDialogButton.Close,
            };
            if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        }

        _viewModel.IsBusy = true;
        DownloadModelButton.IsEnabled = false;
        ColorizeButton.IsEnabled = false;
        ModelStatus.Text = AppLocalizer.Get("Downloading model…");
        try
        {
            var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
                ModelStatus.Text = AppLocalizer.Format($"Downloading model… {p.Percent:F0}% ({p.Stage})")));
            var result = await _runner.RunAsync(
                "colorize", ["download-model", "--tier", tier, "--accept-license"],
                progress, ct: CancellationToken.None,
                silenceTimeout: TimeSpan.FromHours(1));
            if (!result.Success)
                ModelStatus.Text = AppLocalizer.Format($"Download failed: {result.ErrorMessage ?? result.ErrorCode}. Set UCX_COLORIZE_MODEL_URL to a mirror if the source is unavailable.");
        }
        finally
        {
            _viewModel.IsBusy = false;
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
        e.DragUIOverride.Caption = AppLocalizer.Get("Colorize");
        e.DragUIOverride.IsCaptionVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        var items = await DropSnapshotHelper.TrySnapshotDropAsync(e);
        if (items is null) return;
        var file = items.OfType<StorageFile>().FirstOrDefault(f =>
        {
            var ext = Path.GetExtension(f.Path).ToLowerInvariant();
            return ImageExts.Contains(ext) || VideoExts.Contains(ext);
        });
        if (file is not null) LoadSource(file.Path);
    }

    private void LoadSource(string path)
    {
        if (!_viewModel.TryLoadSource(path))
            return;
        OutputBox.Text = "";

        EmptyState.Visibility = Visibility.Collapsed;
        PreviewPanel.Visibility = Visibility.Visible;
        if (!_viewModel.IsVideo)
            PreviewImage.Source = new BitmapImage(new Uri(path));
        else
            PreviewImage.Source = null;

        StatusText.Text = _viewModel.SourceStatus;
        UpdateColorizeEnabled();
    }

    private async void ChooseOutput_Click(object sender, RoutedEventArgs e)
    {
        if (_viewModel.SourcePath is null) return;
        var picker = new FileSavePicker { SuggestedStartLocation = PickerLocationId.PicturesLibrary };
        var ext = _viewModel.IsVideo ? ".mp4" : ".png";
        picker.FileTypeChoices.Add(_viewModel.IsVideo ? "Video" : "Image", [ext]);
        picker.SuggestedFileName = Path.GetFileNameWithoutExtension(_viewModel.SourcePath) + "_color";
        var handle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, handle);
        var file = await picker.PickSaveFileAsync();
        if (file is not null)
        {
            _viewModel.OutputPath = file.Path;
            OutputBox.Text = file.Path;
        }
    }

    private void UpdateColorizeEnabled() =>
        ColorizeButton.IsEnabled = _viewModel.CanColorize;

    // ── Colorize ─────────────────────────────────────────────────────────────

    private async void Colorize_Click(object sender, RoutedEventArgs e)
    {
        if (!_viewModel.CanColorize) return;

        var request = _viewModel.BuildInvocation(SelectedTier());
        var output = request.OutputPath;
        _viewModel.IsBusy = true;
        _cts = new CancellationTokenSource();
        ColorizeButton.IsEnabled = false;
        DownloadModelButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        ColorizeProgress.Visibility = Visibility.Visible;
        ColorizeProgress.Value = 0;
        StatusText.Text = _viewModel.IsVideo
            ? AppLocalizer.Get("Colourising video…")
            : AppLocalizer.Get("Colourising image…");

        var progress = new Progress<SidecarProgress>(p => DispatcherQueue.TryEnqueue(() =>
        {
            ColorizeProgress.Value = Math.Clamp(p.Percent, 0, 100);
            StatusText.Text = AppLocalizer.Format($"Colourising… {p.Percent:F0}% — {p.Stage}");
        }));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync(
                request.Engine, request.Arguments,
                progress, null, _cts.Token,
                silenceTimeout: TimeSpan.FromHours(6));
        }
        catch (OperationCanceledException)
        {
            result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user", 130);
        }
        finally
        {
            _viewModel.IsBusy = false;
            _cts = null;
            CancelButton.IsEnabled = false;
            DownloadModelButton.IsEnabled = true;
            ColorizeProgress.Visibility = Visibility.Collapsed;
            UpdateColorizeEnabled();
        }

        if (result.Success)
        {
            StatusText.Text = AppLocalizer.Format($"Saved colourised {(_viewModel.IsVideo ? "video" : "image")} to {output}.");
            if (!_viewModel.IsVideo && File.Exists(output))
                PreviewImage.Source = new BitmapImage(new Uri(output));
        }
        else
        {
            StatusText.Text = ColorizeWorkflowViewModel.MapError(result.ErrorCode, result.ErrorMessage);
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => _cts?.Cancel();

    private string SelectedTier() =>
        (TierCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "classic";
}
