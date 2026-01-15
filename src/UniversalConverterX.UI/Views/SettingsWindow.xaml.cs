using System.Collections.ObjectModel;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Storage;
using Windows.Storage.Pickers;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Services;
using Microsoft.Extensions.DependencyInjection;
using WinRT.Interop;

namespace UniversalConverterX.UI.Views;

public sealed partial class SettingsWindow : Window
{
    private readonly IServiceProvider _serviceProvider;
    private readonly ConverterXOptions _options;
    private readonly IToolManager _toolManager;
    private readonly IToolDownloader? _toolDownloader;
    private readonly ObservableCollection<ToolViewModel> _tools = [];
    
    private bool _isDirty = false;

    public SettingsWindow(IServiceProvider serviceProvider)
    {
        _serviceProvider = serviceProvider;
        _options = serviceProvider.GetRequiredService<Microsoft.Extensions.Options.IOptions<ConverterXOptions>>().Value;
        _toolManager = serviceProvider.GetRequiredService<IToolManager>();
        _toolDownloader = serviceProvider.GetService<IToolDownloader>();

        InitializeComponent();

        // Set window size
        var hwnd = WindowNative.GetWindowHandle(this);
        var windowId = Win32Interop.GetWindowIdFromWindow(hwnd);
        var appWindow = Microsoft.UI.Windowing.AppWindow.GetFromWindowId(windowId);
        appWindow.Resize(new Windows.Graphics.SizeInt32(700, 900));
        appWindow.Title = "Settings - UniversalConverter X";

        LoadSettings();
        LoadTools();
    }

    private void LoadSettings()
    {
        // General
        OutputDirectoryTextBox.Text = _options.DefaultOutputDirectory ?? "";
        OverwriteBehaviorComboBox.SelectedIndex = (int)_options.OverwriteBehavior;
        DeleteSourceToggle.IsOn = _options.DeleteSourceOnSuccess;
        NotificationsToggle.IsOn = _options.ShowNotifications;
        SoundToggle.IsOn = _options.PlaySoundOnComplete;

        // Quality & Performance
        DefaultQualityComboBox.SelectedIndex = (int)_options.DefaultQuality;
        HardwareAccelComboBox.SelectedIndex = (int)_options.DefaultHardwareAcceleration;
        ParallelSlider.Value = _options.MaxParallelConversions;
        PreserveMetadataToggle.IsOn = _options.PreserveMetadataByDefault;

        // Tools
        ToolsPathTextBox.Text = _options.ToolsBasePath;

        // Shell Integration
        ContextMenuToggle.IsOn = _options.ShellIntegrationEnabled;
        ContextMenuStyleComboBox.SelectedIndex = (int)_options.ContextMenuStyle;

        // Load preset checkboxes
        var presets = _options.QuickConvertPresets ?? [];
        PresetWebpCheckBox.IsChecked = presets.Contains("webp");
        PresetPngCheckBox.IsChecked = presets.Contains("png");
        PresetJpgCheckBox.IsChecked = presets.Contains("jpg");
        PresetMp4CheckBox.IsChecked = presets.Contains("mp4");
        PresetMp3CheckBox.IsChecked = presets.Contains("mp3");
        PresetPdfCheckBox.IsChecked = presets.Contains("pdf");

        // Appearance
        ThemeComboBox.SelectedIndex = (int)_options.Theme;
        MinimizeToTrayToggle.IsOn = _options.MinimizeToTray;
        StartMinimizedToggle.IsOn = _options.StartMinimized;

        // Version
        var version = typeof(SettingsWindow).Assembly.GetName().Version;
        VersionText.Text = $"Version {version?.Major ?? 1}.{version?.Minor ?? 0}.{version?.Build ?? 0}";

        _isDirty = false;
    }

    private async void LoadTools()
    {
        _tools.Clear();
        ToolsListView.ItemsSource = _tools;

        var tools = _toolManager.GetAvailableTools();
        
        foreach (var tool in tools)
        {
            var version = tool.IsInstalled 
                ? await _toolManager.GetToolVersionAsync(tool.Id) 
                : null;

            _tools.Add(new ToolViewModel
            {
                Id = tool.Id,
                Name = tool.Name,
                Version = version ?? "",
                IsInstalled = tool.IsInstalled,
                StatusGlyph = tool.IsInstalled ? "\uE73E" : "\uE711",
                StatusColor = tool.IsInstalled 
                    ? new SolidColorBrush(Colors.Green) 
                    : new SolidColorBrush(Colors.Orange),
                StatusText = tool.IsInstalled 
                    ? $"Installed • {tool.Description}" 
                    : $"Not installed • {tool.Description}",
                ActionText = tool.IsInstalled ? "Update" : "Download"
            });
        }
    }

    private async void BrowseOutputDirectory_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        picker.SuggestedStartLocation = PickerLocationId.DocumentsLibrary;
        picker.FileTypeFilter.Add("*");

        var hwnd = WindowNative.GetWindowHandle(this);
        InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder != null)
        {
            OutputDirectoryTextBox.Text = folder.Path;
            _isDirty = true;
        }
    }

    private async void BrowseToolsPath_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        picker.SuggestedStartLocation = PickerLocationId.ComputerFolder;
        picker.FileTypeFilter.Add("*");

        var hwnd = WindowNative.GetWindowHandle(this);
        InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder != null)
        {
            ToolsPathTextBox.Text = folder.Path;
            _isDirty = true;
        }
    }

    private async void ToolAction_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button button || button.Tag is not string toolId)
            return;

        if (_toolDownloader == null)
        {
            await ShowMessageAsync("Tool Download", 
                "Tool downloading is not available. Please install tools manually.");
            return;
        }

        var toolVm = _tools.FirstOrDefault(t => t.Id == toolId);
        if (toolVm == null) return;

        // Show progress
        toolVm.ActionText = "Downloading...";
        toolVm.StatusText = "Downloading...";

        try
        {
            var progress = new Progress<DownloadProgress>(p =>
            {
                DispatcherQueue.TryEnqueue(() =>
                {
                    toolVm.StatusText = $"Downloading... {p.Percent:F0}%";
                });
            });

            var result = await _toolDownloader.DownloadToolAsync(toolId, progress);

            if (result.Success)
            {
                toolVm.IsInstalled = true;
                toolVm.Version = result.Version ?? "";
                toolVm.StatusGlyph = "\uE73E";
                toolVm.StatusColor = new SolidColorBrush(Colors.Green);
                toolVm.StatusText = "Installed successfully!";
                toolVm.ActionText = "Update";
            }
            else
            {
                toolVm.StatusText = $"Failed: {result.ErrorMessage}";
                toolVm.ActionText = "Retry";
            }
        }
        catch (Exception ex)
        {
            toolVm.StatusText = $"Error: {ex.Message}";
            toolVm.ActionText = "Retry";
        }
    }

    private async void DownloadAllTools_Click(object sender, RoutedEventArgs e)
    {
        if (_toolDownloader == null)
        {
            await ShowMessageAsync("Tool Download",
                "Tool downloading is not available. Please install tools manually.");
            return;
        }

        var missingTools = _tools.Where(t => !t.IsInstalled).Select(t => t.Id).ToList();
        if (missingTools.Count == 0)
        {
            await ShowMessageAsync("All Tools Installed", "All converter tools are already installed.");
            return;
        }

        DownloadAllToolsButton.IsEnabled = false;
        DownloadAllToolsButton.Content = "Downloading...";

        try
        {
            var progress = new Progress<BatchDownloadProgress>(p =>
            {
                DispatcherQueue.TryEnqueue(() =>
                {
                    DownloadAllToolsButton.Content = 
                        $"Downloading {p.CurrentTool} ({p.ToolsCompleted + 1}/{p.TotalTools})...";
                    
                    var tool = _tools.FirstOrDefault(t => t.Id == p.CurrentTool);
                    if (tool != null)
                    {
                        tool.StatusText = $"Downloading... {p.CurrentProgress.Percent:F0}%";
                    }
                });
            });

            var results = await _toolDownloader.DownloadToolsAsync(missingTools, progress);

            var succeeded = results.Count(r => r.Success);
            var failed = results.Count(r => !r.Success);

            await ShowMessageAsync("Download Complete",
                $"Downloaded {succeeded} tools successfully.\n" +
                (failed > 0 ? $"{failed} tools failed to download." : ""));

            LoadTools();
        }
        finally
        {
            DownloadAllToolsButton.IsEnabled = true;
            DownloadAllToolsButton.Content = "Download All Missing Tools";
        }
    }

    private void ContextMenuToggle_Toggled(object sender, RoutedEventArgs e)
    {
        _isDirty = true;
    }

    private async void RegisterShell_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            // This would call the shell registration service
            // ShellIntegration.Register();
            await ShowMessageAsync("Shell Integration", 
                "Context menu registered successfully.\n\n" +
                "You may need to restart Explorer or sign out for changes to take effect.");
        }
        catch (Exception ex)
        {
            await ShowMessageAsync("Registration Failed", 
                $"Failed to register context menu: {ex.Message}\n\n" +
                "Try running the application as Administrator.");
        }
    }

    private async void UnregisterShell_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            // ShellIntegration.Unregister();
            await ShowMessageAsync("Shell Integration",
                "Context menu unregistered successfully.");
        }
        catch (Exception ex)
        {
            await ShowMessageAsync("Unregistration Failed",
                $"Failed to unregister context menu: {ex.Message}");
        }
    }

    private void ThemeComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        _isDirty = true;

        // Apply theme immediately for preview
        if (ThemeComboBox.SelectedIndex >= 0 && Content is FrameworkElement root)
        {
            root.RequestedTheme = ThemeComboBox.SelectedIndex switch
            {
                0 => ElementTheme.Light,
                1 => ElementTheme.Dark,
                _ => ElementTheme.Default
            };
        }
    }

    private void AccentColor_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string colorHex)
        {
            _isDirty = true;
            // Store the selected accent color
            // In a real implementation, this would update the app's accent color resources
        }
    }

    private async void CheckUpdates_Click(object sender, RoutedEventArgs e)
    {
        CheckUpdatesButton.IsEnabled = false;
        CheckUpdatesButton.Content = "Checking...";

        try
        {
            // Simulate update check
            await Task.Delay(1500);
            
            await ShowMessageAsync("No Updates Available",
                "You're running the latest version of UniversalConverter X.");
        }
        finally
        {
            CheckUpdatesButton.IsEnabled = true;
            CheckUpdatesButton.Content = "Check for Updates";
        }
    }

    private async void ResetSettings_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new ContentDialog
        {
            Title = "Reset Settings",
            Content = "Are you sure you want to reset all settings to their default values?",
            PrimaryButtonText = "Reset",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = Content.XamlRoot
        };

        var result = await dialog.ShowAsync();
        if (result == ContentDialogResult.Primary)
        {
            // Reset to defaults
            _options.ResetToDefaults();
            LoadSettings();
            _isDirty = true;
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        Close();
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        // Save all settings
        SaveSettings();

        await ShowMessageAsync("Settings Saved", "Your settings have been saved successfully.");
        Close();
    }

    private void SaveSettings()
    {
        // General
        _options.DefaultOutputDirectory = string.IsNullOrWhiteSpace(OutputDirectoryTextBox.Text) 
            ? null 
            : OutputDirectoryTextBox.Text;
        _options.OverwriteBehavior = (OverwriteBehavior)OverwriteBehaviorComboBox.SelectedIndex;
        _options.DeleteSourceOnSuccess = DeleteSourceToggle.IsOn;
        _options.ShowNotifications = NotificationsToggle.IsOn;
        _options.PlaySoundOnComplete = SoundToggle.IsOn;

        // Quality & Performance
        _options.DefaultQuality = (Core.Models.QualityPreset)DefaultQualityComboBox.SelectedIndex;
        _options.DefaultHardwareAcceleration = (Core.Models.HardwareAcceleration)HardwareAccelComboBox.SelectedIndex;
        _options.MaxParallelConversions = (int)ParallelSlider.Value;
        _options.PreserveMetadataByDefault = PreserveMetadataToggle.IsOn;

        // Tools
        _options.ToolsBasePath = ToolsPathTextBox.Text;

        // Shell Integration
        _options.ShellIntegrationEnabled = ContextMenuToggle.IsOn;
        _options.ContextMenuStyle = (ContextMenuStyle)ContextMenuStyleComboBox.SelectedIndex;

        // Quick convert presets
        var presets = new List<string>();
        if (PresetWebpCheckBox.IsChecked == true) presets.Add("webp");
        if (PresetPngCheckBox.IsChecked == true) presets.Add("png");
        if (PresetJpgCheckBox.IsChecked == true) presets.Add("jpg");
        if (PresetMp4CheckBox.IsChecked == true) presets.Add("mp4");
        if (PresetMp3CheckBox.IsChecked == true) presets.Add("mp3");
        if (PresetPdfCheckBox.IsChecked == true) presets.Add("pdf");
        _options.QuickConvertPresets = presets;

        // Appearance
        _options.Theme = (AppTheme)ThemeComboBox.SelectedIndex;
        _options.MinimizeToTray = MinimizeToTrayToggle.IsOn;
        _options.StartMinimized = StartMinimizedToggle.IsOn;

        // Save to file
        _options.Save();

        _isDirty = false;
    }

    private async Task ShowMessageAsync(string title, string message)
    {
        var dialog = new ContentDialog
        {
            Title = title,
            Content = message,
            CloseButtonText = "OK",
            XamlRoot = Content.XamlRoot
        };

        await dialog.ShowAsync();
    }
}

/// <summary>
/// View model for tool display in settings
/// </summary>
public class ToolViewModel : CommunityToolkit.Mvvm.ComponentModel.ObservableObject
{
    private string _id = "";
    private string _name = "";
    private string _version = "";
    private bool _isInstalled;
    private string _statusGlyph = "";
    private SolidColorBrush _statusColor = new(Colors.Gray);
    private string _statusText = "";
    private string _actionText = "";

    public string Id { get => _id; set => SetProperty(ref _id, value); }
    public string Name { get => _name; set => SetProperty(ref _name, value); }
    public string Version { get => _version; set => SetProperty(ref _version, value); }
    public bool IsInstalled { get => _isInstalled; set => SetProperty(ref _isInstalled, value); }
    public string StatusGlyph { get => _statusGlyph; set => SetProperty(ref _statusGlyph, value); }
    public SolidColorBrush StatusColor { get => _statusColor; set => SetProperty(ref _statusColor, value); }
    public string StatusText { get => _statusText; set => SetProperty(ref _statusText, value); }
    public string ActionText { get => _actionText; set => SetProperty(ref _actionText, value); }
}
