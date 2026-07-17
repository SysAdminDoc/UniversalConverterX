using System.Collections.ObjectModel;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class DiscBurnPage : Page
{
    private readonly ISidecarRunner _runner;
    private readonly ObservableCollection<DiscSource> _sources = [];
    private readonly ObservableCollection<DiscRecorder> _recorders = [];
    private string? _outputPath;
    private CancellationTokenSource? _cts;

    public DiscBurnPage()
    {
        InitializeComponent();
        _runner = App.Services.GetRequiredService<ISidecarRunner>();
        SourceList.ItemsSource = _sources;
        DriveCombo.ItemsSource = _recorders;
        _ = RefreshDrivesAsync();
    }

    private string SelectedTag(ComboBox combo, string fallback) =>
        (combo.SelectedItem as ComboBoxItem)?.Tag as string ?? fallback;

    private bool IsDvdVideo => SelectedTag(ModeCombo, "data") == "dvd";
    private bool IsBurn => SelectedTag(ActionCombo, "image") == "burn";

    private async void ChooseSource_Click(object sender, RoutedEventArgs e)
    {
        if (IsDvdVideo)
        {
            var picker = new FileOpenPicker { SuggestedStartLocation = PickerLocationId.VideosLibrary };
            picker.FileTypeFilter.Add("*");
            InitializePicker(picker);
            var files = await picker.PickMultipleFilesAsync();
            SetSources(files.Select(file => new DiscSource(file.Name, file.Path)));
            return;
        }

        var folderPicker = new FolderPicker { SuggestedStartLocation = PickerLocationId.ComputerFolder };
        folderPicker.FileTypeFilter.Add("*");
        InitializePicker(folderPicker);
        var folder = await folderPicker.PickSingleFolderAsync();
        if (folder is not null)
            SetSources([new DiscSource(folder.Name, folder.Path)]);
    }

    private static void InitializePicker(object picker)
    {
        var handle = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, handle);
    }

    private void SetSources(IEnumerable<DiscSource> sources)
    {
        _sources.Clear();
        foreach (var source in sources)
            _sources.Add(source);
        EmptyState.Visibility = _sources.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        SourceList.Visibility = _sources.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        StatusText.Text = _sources.Count == 0
            ? "No source selected."
            : IsDvdVideo
                ? $"Ready to author {_sources.Count} DVD-Video title(s)."
                : $"Ready to image {_sources[0].Path}.";
        UpdateEnabled();
    }

    private void DropZone_DragOver(object sender, DragEventArgs e)
    {
        e.AcceptedOperation = DataPackageOperation.Copy;
        e.DragUIOverride.Caption = IsDvdVideo ? "Add DVD-Video titles" : "Use as data-disc source";
        e.DragUIOverride.IsCaptionVisible = true;
    }

    private async void DropZone_Drop(object sender, DragEventArgs e)
    {
        if (!e.DataView.Contains(StandardDataFormats.StorageItems))
            return;
        var items = await e.DataView.GetStorageItemsAsync();
        if (IsDvdVideo)
        {
            SetSources(items.OfType<StorageFile>().Select(file => new DiscSource(file.Name, file.Path)));
            return;
        }
        var folder = items.OfType<StorageFolder>().FirstOrDefault();
        if (folder is not null)
            SetSources([new DiscSource(folder.Name, folder.Path)]);
    }

    private void Mode_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (MediaCombo is null)
            return;
        MediaCombo.Visibility = IsDvdVideo ? Visibility.Collapsed : Visibility.Visible;
        StandardCombo.Visibility = IsDvdVideo ? Visibility.Visible : Visibility.Collapsed;
        EmptyTitle.Text = IsDvdVideo ? "Choose one or more video titles" : "Choose a folder for the disc";
        EmptyHint.Text = IsDvdVideo
            ? "Videos are transcoded to DVD MPEG-2 and authored into a VIDEO_TS structure."
            : "Its files and subfolders will become the data-disc contents.";
        SetSources([]);
        UpdateEnabled();
    }

    private void Action_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (OutputBox is null)
            return;
        OutputBox.Visibility = IsBurn ? Visibility.Collapsed : Visibility.Visible;
        ChooseOutputButton.Visibility = IsBurn ? Visibility.Collapsed : Visibility.Visible;
        DriveCombo.Visibility = IsBurn ? Visibility.Visible : Visibility.Collapsed;
        StartButton.Content = IsBurn ? "Burn disc" : "Create ISO";
        UpdateEnabled();
    }

    private async void ChooseOutput_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileSavePicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
        picker.FileTypeChoices.Add("ISO disc image", [".iso"]);
        picker.SuggestedFileName = IsDvdVideo ? "UniversalX_DVD-Video" : "UniversalX_DataDisc";
        InitializePicker(picker);
        var file = await picker.PickSaveFileAsync();
        if (file is null)
            return;
        _outputPath = file.Path;
        OutputBox.Text = file.Path;
        UpdateEnabled();
    }

    private async void RefreshDrives_Click(object sender, RoutedEventArgs e) => await RefreshDrivesAsync();

    private async Task RefreshDrivesAsync()
    {
        _recorders.Clear();
        if (_runner.Locate("discburn") is null)
        {
            StatusText.Text = "The discburn sidecar was not found.";
            return;
        }
        var found = new List<DiscRecorder>();
        var result = await _runner.RunAsync("discburn", ["drives"], onRawEvent: (name, payload) =>
        {
            if (name != "drive")
                return;
            var id = payload.TryGetProperty("id", out var idNode) ? idNode.GetString() : null;
            if (string.IsNullOrWhiteSpace(id))
                return;
            var vendor = payload.TryGetProperty("vendor", out var vendorNode) ? vendorNode.GetString() : null;
            var product = payload.TryGetProperty("product", out var productNode) ? productNode.GetString() : null;
            found.Add(new DiscRecorder(id, $"{vendor} {product}".Trim()));
        });
        foreach (var recorder in found)
            _recorders.Add(recorder);
        if (_recorders.Count > 0)
            DriveCombo.SelectedIndex = 0;
        else if (!result.Success)
            StatusText.Text = $"Optical recorder discovery failed: {result.ErrorMessage}";
        else
            StatusText.Text = "No physical recorder found. ISO image creation remains available.";
        UpdateEnabled();
    }

    private void UpdateEnabled()
    {
        if (StartButton is null)
            return;
        StartButton.IsEnabled = _cts is null
            && _sources.Count > 0
            && (IsBurn ? DriveCombo.SelectedItem is DiscRecorder : !string.IsNullOrWhiteSpace(_outputPath));
    }

    private async void Start_Click(object sender, RoutedEventArgs e)
    {
        if (_cts is not null || _sources.Count == 0)
            return;
        var operation = IsDvdVideo
            ? (IsBurn ? "burn-dvd" : "image-dvd")
            : (IsBurn ? "burn-data" : "image-data");
        var args = new List<string> { operation };
        if (IsDvdVideo)
        {
            foreach (var source in _sources)
                args.AddRange(["--input", source.Path]);
            args.AddRange(["--standard", SelectedTag(StandardCombo, "ntsc")]);
        }
        else
        {
            args.AddRange(["--input", _sources[0].Path, "--media", SelectedTag(MediaCombo, "dvd")]);
        }
        args.AddRange(["--label", LabelBox.Text]);
        if (IsBurn && DriveCombo.SelectedItem is DiscRecorder recorder)
            args.AddRange(["--recorder", recorder.Id]);
        else if (_outputPath is not null)
            args.AddRange(["--output", _outputPath]);

        _cts = new CancellationTokenSource();
        StartButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        OperationProgress.Visibility = Visibility.Visible;
        OperationProgress.Value = 0;
        var progress = new Progress<SidecarProgress>(value => DispatcherQueue.TryEnqueue(() =>
        {
            OperationProgress.Value = Math.Clamp(value.Percent, 0, 100);
            StatusText.Text = $"{value.Stage} — {value.Percent:F0}%";
        }));

        SidecarResult result;
        try
        {
            result = await _runner.RunAsync("discburn", args, progress, null, _cts.Token);
        }
        catch (OperationCanceledException)
        {
            result = new SidecarResult(false, null, null, "cancelled", "Cancelled by user", 130);
        }
        finally
        {
            _cts = null;
            CancelButton.IsEnabled = false;
            OperationProgress.Visibility = Visibility.Collapsed;
            UpdateEnabled();
        }
        StatusText.Text = result.Success
            ? IsBurn ? "Disc burn completed." : $"ISO image saved to {_outputPath}."
            : result.ErrorCode == "cancelled" ? "Disc operation cancelled." : $"Disc operation failed: {result.ErrorMessage}";
    }

    private void Cancel_Click(object sender, RoutedEventArgs e) => _cts?.Cancel();

    private sealed record DiscSource(string Name, string Path);
    private sealed record DiscRecorder(string Id, string Name)
    {
        public override string ToString() => string.IsNullOrWhiteSpace(Name) ? Id : Name;
    }
}
