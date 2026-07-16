using System.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class HistoryPage : Page
{
    private readonly IHistoryService _history;
    private string? _searchTerm;

    /// <summary>
    /// Bumped on every load request so a slow earlier query (e.g. "a") can't
    /// overwrite a faster later query ("audio") if both complete out of order.
    /// </summary>
    private int _loadEpoch;

    /// <summary>
    /// Cancels the pending search so we don't re-hit SQLite on every keystroke.
    /// 200 ms feels instant but absorbs typical typing bursts.
    /// </summary>
    private CancellationTokenSource? _searchDebounce;
    private static readonly TimeSpan SearchDebounce = TimeSpan.FromMilliseconds(200);

    public HistoryPage()
    {
        InitializeComponent();
        _history = App.Services.GetRequiredService<IHistoryService>();
        _ = LoadAsync();
    }

    private async Task LoadAsync()
    {
        var epoch = Interlocked.Increment(ref _loadEpoch);
        var rows    = await _history.QueryAsync(_searchTerm, limit: 500);
        var summary = await _history.SummarizeAsync(_searchTerm);
        if (epoch != Volatile.Read(ref _loadEpoch)) return; // a newer query landed

        ItemsList.ItemsSource = rows;
        EmptyState.Visibility = rows.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        ListScroll.Visibility = rows.Count == 0 ? Visibility.Collapsed : Visibility.Visible;

        StatTotal.Text = summary.TotalJobs.ToString();
        StatOk.Text    = summary.Succeeded.ToString();
        StatFail.Text  = summary.Failed.ToString();
        StatSaved.Text = HistoryRecord.FormatBytes(summary.SpaceSavedBytes);

        StatusText.Text = string.IsNullOrEmpty(_searchTerm)
            ? $"Showing {rows.Count} most recent of {summary.TotalJobs} total."
            : $"Showing {rows.Count} matches for \"{_searchTerm}\".";
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await LoadAsync();

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileSavePicker
        {
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
            SuggestedFileName = $"ucx-history-{DateTime.Now:yyyyMMdd-HHmmss}",
        };
        picker.FileTypeChoices.Add("JSON report", [".json"]);
        picker.FileTypeChoices.Add("CSV report", [".csv"]);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
        var file = await picker.PickSaveFileAsync();
        if (file is null) return;

        try
        {
            var count = await _history.ExportAsync(file.Path, _searchTerm);
            StatusText.Text = $"Exported {count} history row(s) to {Path.GetFileName(file.Path)}.";
        }
        catch (Exception ex)
        {
            StatusText.Text = $"Report export failed: {ex.Message}";
        }
    }

    private async void Search_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput) return;
        _searchTerm = string.IsNullOrWhiteSpace(sender.Text) ? null : sender.Text.Trim();

        _searchDebounce?.Cancel();
        _searchDebounce?.Dispose();
        var cts = new CancellationTokenSource();
        _searchDebounce = cts;

        try
        {
            await Task.Delay(SearchDebounce, cts.Token);
        }
        catch (OperationCanceledException) { return; }
        if (cts.IsCancellationRequested) return;
        await LoadAsync();
    }

    private async void Clear_Click(object sender, RoutedEventArgs e)
    {
        if (await PageDialogService.ConfirmClearAsync(
                this,
                "Clear conversion history?",
                "This permanently deletes every recorded job. Converted files on disk are not affected.",
                primaryButtonText: "Clear history",
                cancelButtonText: "Keep history"))
        {
            await _history.ClearAsync();
            await LoadAsync();
        }
    }

    private async void Delete_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button b && b.Tag is long id)
        {
            await _history.DeleteAsync(id);
            await LoadAsync();
        }
    }

    private void Reveal_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button b && b.Tag is string outputPath && !string.IsNullOrEmpty(outputPath) && File.Exists(outputPath))
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = "explorer.exe",
                    Arguments = $"/select,\"{outputPath}\"",
                    UseShellExecute = true,
                });
            }
            catch { /* best-effort */ }
        }
    }

    private void Rerun_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button b || b.Tag is not long id) return;
        var record = _history.Recent.FirstOrDefault(r => r.Id == id);
        if (record is null)
        {
            StatusText.Text = "Re-run target not in recent cache; refresh to reload from disk.";
            return;
        }
        // Route the user to the right page with the source pre-set. We use the existing
        // route map, then leave the page to handle file pre-fill via App.RequestNavigation.
        var route = record.Engine switch
        {
            "videocrush" => "compressor",
            "clipforge"  => "editor",
            "heicshift"  => "image-converter",
            "gifstudio"  => "gif-maker",
            _            => "converter",
        };
        App.RequestNavigation(route);
        StatusText.Text = $"Open file from {Path.GetFileName(record.SourcePath)} on the {route} page to re-run.";
    }
}
