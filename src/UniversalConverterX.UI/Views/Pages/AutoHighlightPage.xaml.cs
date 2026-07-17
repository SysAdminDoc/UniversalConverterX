using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.Core.ViewModels;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class AutoHighlightPage : Page
{
    private static readonly string[] VideoExtensions =
        [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts"];

    private readonly ISidecarRunner _runner;
    private readonly AutoHighlightWorkflowViewModel _viewModel = new();
    private CancellationTokenSource? _activeRun;

    public AutoHighlightPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        HighlightsList.ItemsSource = _viewModel.Highlights;
    }

    private async void OpenVideo_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            ViewMode = PickerViewMode.List,
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
        };
        foreach (var extension in VideoExtensions)
            picker.FileTypeFilter.Add(extension);

        InitializePicker(picker);
        var file = await picker.PickSingleFileAsync();
        if (file is null)
            return;

        _viewModel.LoadVideo(file.Path);
        AnalysisProgress.Value = 0;
        StatusText.Text = $"Loaded: {Path.GetFileName(_viewModel.SourcePath)}";
        UpdateUi();
    }

    private async void Analyze_Click(object sender, RoutedEventArgs e)
    {
        if (!_viewModel.CanAnalyze)
            return;

        _viewModel.Highlights.Clear();
        AnalysisProgress.Value = 0;
        StatusText.Text = "Analyzing scene changes and motion energy...";
        SetBusy(true);

        var args = _viewModel.BuildAnalyzeArguments(
            ThresholdBox.Value, ClipLengthBox.Value, (int)CandidateCountBox.Value, MinimumGapBox.Value);
        var progress = new Progress<SidecarProgress>(update =>
            DispatcherQueue.TryEnqueue(() =>
            {
                AnalysisProgress.Value = update.Percent;
                if (!string.IsNullOrWhiteSpace(update.Stage))
                    StatusText.Text = update.Stage;
            }));
        var log = new Progress<SidecarLog>(_ => { });
        _activeRun = new CancellationTokenSource(TimeSpan.FromHours(2));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync(
                "scenedetect", args, progress, log, _activeRun.Token,
                onRawEvent: (eventName, root) =>
                {
                    if (eventName != "highlight")
                        return;
                    var row = _viewModel.ParseHighlight(root);
                    DispatcherQueue.TryEnqueue(() =>
                    {
                        _viewModel.Highlights.Add(row);
                        UpdateUi();
                    });
                });
        }
        finally
        {
            _activeRun?.Dispose();
            _activeRun = null;
            SetBusy(false);
        }

        StatusText.Text = AutoHighlightWorkflowViewModel.MapAnalysisResult(
            result.Success, result.ErrorCode, result.ErrorMessage, _viewModel.Highlights.Count);
        UpdateUi();
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        StatusText.Text = "Cancelling...";
        _activeRun?.Cancel();
    }

    private void HighlightSelection_Click(object sender, RoutedEventArgs e)
    {
        _viewModel.NotifySelectionChanged();
        UpdateExportButtons();
    }

    private async void ExportReel_Click(object sender, RoutedEventArgs e) =>
        await ExportAsync(HighlightExportKind.Reel);

    private async void ExportEdl_Click(object sender, RoutedEventArgs e) =>
        await ExportAsync(HighlightExportKind.Edl);

    private async void ExportOtio_Click(object sender, RoutedEventArgs e) =>
        await ExportAsync(HighlightExportKind.Otio);

    private async Task ExportAsync(HighlightExportKind kind)
    {
        if (_viewModel.SourcePath is null || _viewModel.IsBusy)
            return;
        var selected = _viewModel.Highlights.Where(item => item.IsSelected).ToList();
        if (selected.Count == 0)
            return;

        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.VideosLibrary,
            SuggestedFileName = Path.GetFileNameWithoutExtension(_viewModel.SourcePath) + "_highlights",
        };
        switch (kind)
        {
            case HighlightExportKind.Reel:
                picker.FileTypeChoices.Add("MP4 video", [".mp4"]);
                break;
            case HighlightExportKind.Edl:
                picker.FileTypeChoices.Add("CMX 3600 EDL", [".edl"]);
                break;
            case HighlightExportKind.Otio:
                picker.FileTypeChoices.Add("OpenTimelineIO", [".otio"]);
                break;
        }

        InitializePicker(picker);
        var file = await picker.PickSaveFileAsync();
        if (file is null)
            return;

        var request = _viewModel.BuildRenderInvocation(kind, file.Path);

        SetBusy(true);
        AnalysisProgress.Value = 0;
        StatusText.Text = kind == HighlightExportKind.Reel ? "Rendering highlight reel..." : "Exporting timeline...";
        _activeRun = new CancellationTokenSource(TimeSpan.FromHours(2));
        var progress = new Progress<SidecarProgress>(update =>
            DispatcherQueue.TryEnqueue(() => AnalysisProgress.Value = update.Percent));
        SidecarResult result;
        try
        {
            result = await _runner.RunAsync(request.Engine, request.Arguments, progress, null, _activeRun.Token);
        }
        finally
        {
            _activeRun?.Dispose();
            _activeRun = null;
            SetBusy(false);
        }

        StatusText.Text = result.Success
            ? $"Exported {selected.Count} highlight(s) to {Path.GetFileName(file.Path)}."
            : $"Export failed: {result.ErrorMessage ?? result.ErrorCode}";
    }

    private void SetBusy(bool busy)
    {
        _viewModel.IsBusy = busy;
        OpenVideoButton.IsEnabled = !busy;
        AnalyzeButton.IsEnabled = _viewModel.CanAnalyze;
        CandidateCountBox.IsEnabled = !busy;
        ClipLengthBox.IsEnabled = !busy;
        ThresholdBox.IsEnabled = !busy;
        MinimumGapBox.IsEnabled = !busy;
        CancelButton.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
        UpdateExportButtons();
    }

    private void UpdateUi()
    {
        EmptyState.Visibility = _viewModel.Highlights.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        HighlightsScroll.Visibility = _viewModel.Highlights.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        AnalyzeButton.IsEnabled = _viewModel.CanAnalyze;
        UpdateExportButtons();
    }

    private void UpdateExportButtons()
    {
        var enabled = _viewModel.CanExport;
        ExportReelButton.IsEnabled = enabled;
        ExportEdlButton.IsEnabled = enabled;
        ExportOtioButton.IsEnabled = enabled;
    }

    private static void InitializePicker(object picker)
    {
        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
    }
}
