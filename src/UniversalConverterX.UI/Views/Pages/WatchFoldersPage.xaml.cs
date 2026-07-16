using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using UniversalConverterX.UI.Services;
using Windows.Storage.Pickers;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class WatchFoldersPage : Page
{
    private readonly IWatchFolderService _service;

    public WatchFoldersPage()
    {
        InitializeComponent();
        _service = App.Services.GetRequiredService<IWatchFolderService>();
        ProfilesList.ItemsSource = _service.Profiles;
        EventList.ItemsSource = _service.Recent;
        _service.Profiles.CollectionChanged += (_, _) => UpdateUi();
        _service.Recent.CollectionChanged += (_, _) => UpdateUi();
        UpdateUi();
    }

    private void UpdateUi()
    {
        EmptyState.Visibility = _service.Profiles.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        ProfilesScroll.Visibility = _service.Profiles.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        RecentEmptyState.Visibility = _service.Recent.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        EventScroll.Visibility = _service.Recent.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
        var status = _service.Status;
        WatchStatusText.Text = $"{status.ActiveProfiles} active · {status.InFlightFiles} settling/running · {status.RememberedFiles} recent files remembered";
    }

    private void ProfileToggled(object sender, RoutedEventArgs e)
    {
        if (sender is ToggleSwitch ts && ts.Tag is string id)
            _service.SetEnabled(id, ts.IsOn);
    }

    private async void NewWatch_Click(object sender, RoutedEventArgs e)
    {
        var profile = await ShowProfileDialogAsync(null);
        if (profile is not null) _service.Add(profile);
    }

    private async void EditProfile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button b || b.Tag is not string id) return;
        var existing = _service.Profiles.FirstOrDefault(p => p.Id == id);
        if (existing is null) return;
        var updated = await ShowProfileDialogAsync(existing);
        if (updated is not null) _service.Update(updated);
    }

    private async void RemoveProfile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button b || b.Tag is not string id) return;
        var profile = _service.Profiles.FirstOrDefault(p => p.Id == id);
        var name = profile?.Name ?? "this watch";
        if (await PageDialogService.ConfirmClearAsync(
                this,
                "Remove watch profile?",
                $"UCX will stop monitoring {name}. Files already converted or compressed are not affected.",
                primaryButtonText: "Remove",
                cancelButtonText: "Keep"))
        {
            _service.Remove(id);
        }
    }

    private async Task<WatchProfile?> ShowProfileDialogAsync(WatchProfile? source)
    {
        var nameBox = new TextBox { Header = "Display name", Text = source?.Name ?? "Watch" };
        var pathBox = new TextBox { Header = "Folder to monitor", Text = source?.Path ?? "", IsReadOnly = true };
        var browseBtn = new Button { Content = "Browse", Style = (Style)Application.Current.Resources["SecondaryButtonStyle"] };
        browseBtn.Click += async (_, __) =>
        {
            var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.VideosLibrary };
            picker.FileTypeFilter.Add("*");
            var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(App.MainWindowHandle);
            WinRT.Interop.InitializeWithWindow.Initialize(picker, hwnd);
            var folder = await picker.PickSingleFolderAsync();
            if (folder is not null) pathBox.Text = folder.Path;
        };
        var pathRow = new Grid { ColumnSpacing = 8 };
        pathRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        pathRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        Grid.SetColumn(pathBox, 0);
        Grid.SetColumn(browseBtn, 1);
        browseBtn.VerticalAlignment = VerticalAlignment.Bottom;
        pathRow.Children.Add(pathBox);
        pathRow.Children.Add(browseBtn);

        var filterBox = new TextBox
        {
            Header = "File filters",
            PlaceholderText = "*.mp4;*.mkv;*.mov",
            Text = source?.Filter ?? "*.mp4;*.mkv;*.mov;*.avi;*.webm;*.m4v"
        };

        var actionCombo = new ComboBox { Header = "Action", SelectedIndex = source?.Action == WatchAction.Convert ? 1 : 0 };
        actionCombo.Items.Add(new ComboBoxItem { Content = "Compress (videocrush)", Tag = "compress" });
        actionCombo.Items.Add(new ComboBoxItem { Content = "Convert / rewrap (clipforge)", Tag = "convert" });

        var presetCombo = new ComboBox { Header = "Compress preset" };
        var compressPresets = new[]
        {
            ("web-1080p",  "Web 1080p"),
            ("web-720p",   "Web 720p"),
            ("social-9x16","Social 9:16"),
            ("discord",    "Discord <10MB"),
            ("archive-h265","Archive H.265"),
            ("archive-ffv1","FFV1 archival"),
        };
        foreach (var (tag, label) in compressPresets)
            presetCombo.Items.Add(new ComboBoxItem { Content = label, Tag = tag });
        var idx = Array.FindIndex(compressPresets, t => t.Item1 == (source?.Preset ?? "web-1080p"));
        presetCombo.SelectedIndex = idx >= 0 ? idx : 0;

        var formatBox = new TextBox
        {
            Header = "Convert target extension",
            PlaceholderText = "mp4",
            Text = source?.TargetFormat ?? "mp4"
        };

        var outputBox = new TextBox
        {
            Header = "Output folder (optional)",
            Text = source?.OutputDir ?? "",
            PlaceholderText = "Same as source folder"
        };

        void OnActionChanged(object? _, SelectionChangedEventArgs __)
        {
            var isCompress = (actionCombo.SelectedItem as ComboBoxItem)?.Tag as string == "compress";
            presetCombo.Visibility = isCompress ? Visibility.Visible : Visibility.Collapsed;
            formatBox.Visibility = isCompress ? Visibility.Collapsed : Visibility.Visible;
        }
        actionCombo.SelectionChanged += OnActionChanged;
        OnActionChanged(null, null!);

        var helper = new Border
        {
            Style = (Style)Application.Current.Resources["InfoBannerStyle"],
            Child = new TextBlock
            {
                Text = "UCX waits for files to settle before processing and cancels active work when a watch is disabled.",
                TextWrapping = TextWrapping.Wrap,
                Style = (Style)Application.Current.Resources["MutedTextStyle"],
            }
        };

        var stack = new StackPanel { Spacing = 12, Width = 460 };
        stack.Children.Add(helper);
        stack.Children.Add(nameBox);
        stack.Children.Add(pathRow);
        stack.Children.Add(filterBox);
        stack.Children.Add(actionCombo);
        stack.Children.Add(presetCombo);
        stack.Children.Add(formatBox);
        stack.Children.Add(outputBox);

        var dialog = new ContentDialog
        {
            Title = source is null ? "New watch profile" : "Edit watch profile",
            PrimaryButtonText = "Save",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
            Content = stack,
            XamlRoot = this.XamlRoot,
        };

        var result = await dialog.ShowAsync();
        if (result != ContentDialogResult.Primary) return null;
        if (string.IsNullOrWhiteSpace(pathBox.Text)) return null;

        var actionTag = (actionCombo.SelectedItem as ComboBoxItem)?.Tag as string ?? "compress";
        var presetTag = (presetCombo.SelectedItem as ComboBoxItem)?.Tag as string;

        return new WatchProfile
        {
            Id = source?.Id ?? Guid.NewGuid().ToString("N"),
            Name = string.IsNullOrWhiteSpace(nameBox.Text) ? "Watch" : nameBox.Text.Trim(),
            Path = pathBox.Text.Trim(),
            Filter = string.IsNullOrWhiteSpace(filterBox.Text) ? "*.*" : filterBox.Text.Trim(),
            Action = actionTag == "convert" ? WatchAction.Convert : WatchAction.Compress,
            Preset = actionTag == "compress" ? presetTag : null,
            TargetFormat = actionTag == "convert" ? formatBox.Text.Trim().TrimStart('.') : null,
            OutputDir = string.IsNullOrWhiteSpace(outputBox.Text) ? null : outputBox.Text.Trim(),
            IsEnabled = source?.IsEnabled ?? true,
            CreatedAt = source?.CreatedAt ?? DateTime.UtcNow,
        };
    }
}
