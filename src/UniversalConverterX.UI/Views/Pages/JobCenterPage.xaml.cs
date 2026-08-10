using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class JobCenterPage : Page
{
    private readonly IAppJobCoordinator _coordinator;
    private string? _searchTerm;

    public JobCenterPage()
    {
        InitializeComponent();
        _coordinator = App.Services.GetRequiredService<IAppJobCoordinator>();
        RefreshJobs();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        _coordinator.JobsChanged += Coordinator_JobsChanged;
        RefreshJobs();
    }

    protected override void OnNavigatedFrom(NavigationEventArgs e)
    {
        _coordinator.JobsChanged -= Coordinator_JobsChanged;
        base.OnNavigatedFrom(e);
    }

    private void Coordinator_JobsChanged(object? sender, EventArgs e)
    {
        if (!DispatcherQueue.TryEnqueue(RefreshJobs))
            RefreshJobs();
    }

    private void Refresh_Click(object sender, RoutedEventArgs e) => RefreshJobs();

    private void Search_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput)
            return;

        _searchTerm = string.IsNullOrWhiteSpace(sender.Text) ? null : sender.Text.Trim();
        RefreshJobs();
    }

    private void RefreshJobs()
    {
        var jobs = _coordinator.GetJobs(_searchTerm);
        JobsList.ItemsSource = jobs;
        EmptyState.Visibility = jobs.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        JobsList.Visibility = jobs.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        StatusText.Text = string.IsNullOrWhiteSpace(_searchTerm)
            ? AppLocalizer.Format($"Showing {jobs.Count} durable job(s).")
            : AppLocalizer.Format($"Showing {jobs.Count} job(s) matching \"{_searchTerm}\".");
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (!TryGetHandle(sender, out var handle))
            return;

        StatusText.Text = _coordinator.Cancel(handle)
            ? AppLocalizer.Get("Cancellation requested.")
            : AppLocalizer.Get("That job could not be cancelled from its current state.");
        RefreshJobs();
    }

    private void Retry_Click(object sender, RoutedEventArgs e)
    {
        if (!TryGetHandle(sender, out var handle))
            return;

        if (!_coordinator.Retry(handle))
        {
            StatusText.Text = AppLocalizer.Get("That job is not ready to retry.");
            RefreshJobs();
            return;
        }

        App.RequestNavigation(handle.QueueKey);
    }

    private void Skip_Click(object sender, RoutedEventArgs e)
    {
        if (!TryGetHandle(sender, out var handle))
            return;

        StatusText.Text = _coordinator.Skip(handle)
            ? AppLocalizer.Get("Job skipped.")
            : AppLocalizer.Get("That job could not be skipped from its current state.");
        RefreshJobs();
    }

    private static bool TryGetHandle(object sender, out AppJobHandle handle)
    {
        handle = default;
        if (sender is not Button { Tag: string key })
            return false;

        var separator = key.IndexOf(':');
        if (separator <= 0 || separator == key.Length - 1)
            return false;

        handle = new AppJobHandle(key[..separator], key[(separator + 1)..]);
        return true;
    }
}
