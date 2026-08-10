using System.Collections.ObjectModel;
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Storage;
using Windows.Storage.Pickers;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;
using UniversalConverterX.Core.Security;
using Microsoft.Extensions.DependencyInjection;
using WinRT.Interop;
using Windows.System;
using UniversalConverterX.UI.Services;

namespace UniversalConverterX.UI.Views;

public sealed partial class SettingsWindow : Window
{
    private const string ReleasesUrl = "https://github.com/SysAdminDoc/UniversalConverterX/releases";
    private static readonly string[] LanguageTags = ["", "en-US", "de-DE", "fr-FR", "es-ES", "pl-PL", "zh-Hans"];

    private readonly IServiceProvider _serviceProvider;
    private readonly ConverterXOptions _options;
    private ConverterXOptions _draftOptions;
    private readonly IToolManager _toolManager;
    private readonly IToolDownloader? _toolDownloader;
    private readonly IPluginTrustService _pluginTrustService;
    private readonly IUiPresetCache _presetCache;
    private readonly ObservableCollection<ToolViewModel> _tools = [];
    private readonly ObservableCollection<PluginViewModel> _plugins = [];
    private string? _availableReleaseUrl;

    private bool _isDirty = false;

    public SettingsWindow(IServiceProvider serviceProvider)
    {
        _serviceProvider = serviceProvider;
        _options = serviceProvider.GetRequiredService<Microsoft.Extensions.Options.IOptions<ConverterXOptions>>().Value;
        _draftOptions = CloneOptions(_options);
        _toolManager = serviceProvider.GetRequiredService<IToolManager>();
        _toolDownloader = serviceProvider.GetService<IToolDownloader>();
        _pluginTrustService = serviceProvider.GetRequiredService<IPluginTrustService>();
        _presetCache = serviceProvider.GetRequiredService<IUiPresetCache>();

        InitializeComponent();
        SystemBackdropMaterialService.TryApplyMica(SettingsBackdropHost);

        // Set window size
        var hwnd = WindowNative.GetWindowHandle(this);
        var windowId = Win32Interop.GetWindowIdFromWindow(hwnd);
        var appWindow = Microsoft.UI.Windowing.AppWindow.GetFromWindowId(windowId);
        appWindow.Resize(new Windows.Graphics.SizeInt32(820, 920));
        appWindow.Title = AppLocalizer.Get(
            "SettingsWindow_Item_001.Title", "Settings - UniversalConverter X");

        Closed += (_, _) => RestorePreview();

        LoadSettings();
        LoadTools();
        _ = LoadPluginsAsync();
    }

    private async Task LoadPluginsAsync()
    {
        var discovered = await Task.Run(_pluginTrustService.Discover);
        _plugins.Clear();
        PluginsListView.ItemsSource = _plugins;
        foreach (var plugin in discovered)
        {
            var trusted = plugin.TrustState == PluginTrustState.Trusted;
            var invalid = plugin.TrustState == PluginTrustState.Invalid;
            _plugins.Add(new PluginViewModel
            {
                Id = plugin.Id,
                Name = string.IsNullOrWhiteSpace(plugin.Version)
                    ? plugin.Name
                    : $"{plugin.Name} {plugin.Version}",
                State = plugin.TrustState,
                StatusGlyph = trusted ? "\uE73E" : invalid ? "\uE711" : "\uE7BA",
                StatusColor = (SolidColorBrush)Application.Current.Resources[
                    trusted ? "AccentGreenBrush" : invalid ? "AccentRedBrush" : "AccentOrangeBrush"],
                StatusText = plugin.StatusDetail,
                Sha256Display = plugin.Sha256 is null ? "No trusted digest" : "SHA-256 " + plugin.Sha256[..16] + "…",
                ActionText = plugin.TrustState switch
                {
                    PluginTrustState.Trusted => AppLocalizer.Get("Revoke"),
                    PluginTrustState.Changed => AppLocalizer.Get("Re-trust"),
                    PluginTrustState.Untrusted => AppLocalizer.Get("Trust"),
                    _ => AppLocalizer.Get("Invalid"),
                },
                CanChangeTrust = plugin.CanTrust || plugin.IsTrusted,
            });
        }

        NoPluginsText.Visibility = _plugins.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        PluginsListView.Visibility = _plugins.Count == 0 ? Visibility.Collapsed : Visibility.Visible;
    }

    private async void PluginTrustAction_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button { Tag: string pluginId })
            return;
        var plugin = (await Task.Run(_pluginTrustService.Discover))
            .FirstOrDefault(item => item.Id.Equals(pluginId, StringComparison.OrdinalIgnoreCase));
        if (plugin is null)
        {
            await ShowMessageAsync(AppLocalizer.Get("Plugin unavailable"), AppLocalizer.Get("The plugin was removed before its trust state could be changed."));
            await LoadPluginsAsync();
            return;
        }

        var revoke = plugin.IsTrusted;
        var dialog = new ContentDialog
        {
            Title = revoke
                ? AppLocalizer.Format($"Revoke trust for {plugin.Name}?")
                : AppLocalizer.Format($"Trust {plugin.Name}?"),
            Content = revoke
                ? AppLocalizer.Get("The plugin will disappear from Presets and Toolbox and cannot execute until trusted again.")
                : AppLocalizer.Format($"Third-party plugins run with your user permissions. Review the publisher and files before approving.\n\nSHA-256: {plugin.Sha256}"),
            PrimaryButtonText = revoke
                ? AppLocalizer.Get("Revoke")
                : AppLocalizer.Get("Trust this hash"),
            CloseButtonText = AppLocalizer.Get("Cancel"),
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = Content.XamlRoot,
        };
        if (revoke)
            ApplyDangerPrimary(dialog);
        if (await dialog.ShowAsync() != ContentDialogResult.Primary)
            return;

        var result = await Task.Run(() => revoke
            ? _pluginTrustService.Revoke(plugin.Id)
            : _pluginTrustService.Trust(plugin.Id));
        _presetCache.Invalidate();
        await LoadPluginsAsync();
        await ShowMessageAsync(
            result.Success ? AppLocalizer.Get("Plugin trust updated") : AppLocalizer.Get("Plugin trust failed"),
            result.Message);
    }

    private async void OpenPluginsFolder_Click(object sender, RoutedEventArgs e)
    {
        Directory.CreateDirectory(_pluginTrustService.PluginDirectory);
        var folder = await StorageFolder.GetFolderFromPathAsync(_pluginTrustService.PluginDirectory);
        if (!await Launcher.LaunchFolderAsync(folder))
            await ShowMessageAsync(AppLocalizer.Get("Plugins folder"), _pluginTrustService.PluginDirectory);
    }

    private void LoadSettings()
    {
        // General
        OutputDirectoryTextBox.Text = _draftOptions.DefaultOutputDirectory ?? "";
        OverwriteBehaviorComboBox.SelectedIndex = (int)_draftOptions.OverwriteBehavior;
        PostConversionActionComboBox.SelectedIndex = (int)_draftOptions.PostConversionAction;
        PostConversionArchiveTextBox.Text = _draftOptions.PostConversionArchiveFolder ?? "";
        UpdatePostConversionArchiveState();
        NotificationsToggle.IsOn = _draftOptions.ShowNotifications;
        SoundToggle.IsOn = _draftOptions.PlaySoundOnComplete;
        QueueCompletionActionComboBox.SelectedIndex = (int)_draftOptions.QueueCompletionAction;
        QueueCompletionScriptTextBox.Text = _draftOptions.QueueCompletionScriptPath ?? "";
        UpdateQueueCompletionScriptState();

        // Quality & Performance
        DefaultQualityComboBox.SelectedIndex = (int)_draftOptions.DefaultQuality;
        HardwareAccelComboBox.SelectedIndex = GetHardwareAccelerationIndex(
            _draftOptions.DefaultHardwareAcceleration);
        ParallelSlider.Value = _draftOptions.MaxParallelConversions;
        PreserveMetadataToggle.IsOn = _draftOptions.PreserveMetadataByDefault;

        // Tools
        ToolsPathTextBox.Text = _draftOptions.ToolsBasePath;

        // Shell Integration
        ContextMenuToggle.IsOn = _draftOptions.ShellIntegrationEnabled;
        ContextMenuStyleComboBox.SelectedIndex = (int)_draftOptions.ContextMenuStyle;

        // Load preset checkboxes
        var presets = _draftOptions.QuickConvertPresets ?? [];
        PresetWebpCheckBox.IsChecked = presets.Contains("webp");
        PresetPngCheckBox.IsChecked = presets.Contains("png");
        PresetJpgCheckBox.IsChecked = presets.Contains("jpg");
        PresetMp4CheckBox.IsChecked = presets.Contains("mp4");
        PresetMp3CheckBox.IsChecked = presets.Contains("mp3");
        PresetPdfCheckBox.IsChecked = presets.Contains("pdf");

        // Appearance
        ThemeComboBox.SelectedIndex = (int)_draftOptions.Theme;
        var languageIndex = Array.FindIndex(
            LanguageTags,
            tag => tag.Equals(_draftOptions.Language ?? "", StringComparison.OrdinalIgnoreCase));
        LanguageComboBox.SelectedIndex = languageIndex >= 0 ? languageIndex : 0;
        StartMinimizedToggle.IsOn = _draftOptions.StartMinimized;
        App.ApplyAccentColor(_draftOptions.AccentColor);

        // Advanced
        FfmpegCommandEditingToggle.IsOn = _draftOptions.EnableFfmpegCommandEditing;

        // Version
        var version = typeof(SettingsWindow).Assembly.GetName().Version;
        VersionText.Text = AppLocalizer.Format($"Version {version?.Major ?? 1}.{version?.Minor ?? 0}.{version?.Build ?? 0}");

        _isDirty = false;
        UpdateDirtyState();
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
            var assessment = ToolVersionPolicy.Assess(tool.Id, version);
            var hasVersionWarning = tool.IsInstalled
                && assessment.HasRequirement
                && !assessment.MeetsMinimum;
            var statusText = !tool.IsInstalled
                ? AppLocalizer.Format($"Not installed • {tool.Description}")
                : hasVersionWarning
                    ? assessment.IsExplicitlyRejected
                        ? AppLocalizer.Format($"Security update required: {assessment.DetectedVersion} is blocked")
                        : assessment.VersionKnown
                        ? AppLocalizer.Format($"Security update required: {assessment.DetectedVersion} < {assessment.Requirement!.MinimumVersion}")
                        : AppLocalizer.Format($"Version unverified; requires {assessment.Requirement!.MinimumVersion}+")
                    : AppLocalizer.Format($"Installed • {tool.Description}");

            _tools.Add(new ToolViewModel
            {
                Id = tool.Id,
                Name = tool.Name,
                Version = version ?? "",
                IsInstalled = tool.IsInstalled,
                StatusGlyph = tool.IsInstalled && !hasVersionWarning ? "\uE73E" : "\uE711",
                StatusColor = tool.IsInstalled && !hasVersionWarning
                    ? (SolidColorBrush)Application.Current.Resources["AccentGreenBrush"]
                    : (SolidColorBrush)Application.Current.Resources["AccentOrangeBrush"],
                StatusText = statusText,
                ActionText = tool.IsInstalled
                    ? AppLocalizer.Get("Update")
                    : AppLocalizer.Get("Install")
            });
        }
    }

    private void SettingsSelection_Changed(object sender, SelectionChangedEventArgs e)
    {
        if (Content is FrameworkElement { IsLoaded: true })
            MarkDirty();
    }

    private void SettingsToggle_Changed(object sender, RoutedEventArgs e) => MarkDirty();

    private void SettingsCheck_Changed(object sender, RoutedEventArgs e) => MarkDirty();

    private void SettingsText_Changed(object sender, TextChangedEventArgs e)
    {
        if (Content is FrameworkElement { IsLoaded: true })
            MarkDirty();
    }

    private void PostConversionAction_Changed(object sender, SelectionChangedEventArgs e)
    {
        UpdatePostConversionArchiveState();
        SettingsSelection_Changed(sender, e);
    }

    private void QueueCompletionAction_Changed(object sender, SelectionChangedEventArgs e)
    {
        UpdateQueueCompletionScriptState();
        SettingsSelection_Changed(sender, e);
    }

    private void ParallelSlider_ValueChanged(object sender, Microsoft.UI.Xaml.Controls.Primitives.RangeBaseValueChangedEventArgs e)
    {
        if (Content is FrameworkElement { IsLoaded: true })
            MarkDirty();
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
            MarkDirty();
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
            MarkDirty();
        }
    }

    private async void ToolAction_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not Button button || button.Tag is not string toolId)
            return;

        if (_toolDownloader == null)
        {
            await ShowMessageAsync(AppLocalizer.Get("Tool Download"),
                AppLocalizer.Get("Tool downloading is not available. Please install tools manually."));
            return;
        }

        var toolVm = _tools.FirstOrDefault(t => t.Id == toolId);
        if (toolVm == null) return;

        button.IsEnabled = false;
        toolVm.ActionText = AppLocalizer.Get("Downloading...");
        toolVm.StatusText = AppLocalizer.Get("Downloading...");
        try
        {
            var progress = new Progress<DownloadProgress>(p =>
            {
                DispatcherQueue.TryEnqueue(() =>
                {
                    toolVm.StatusText = AppLocalizer.Format($"Downloading... {p.Percent:F0}%");
                });
            });

            var result = await _toolDownloader.DownloadToolAsync(toolId, progress);

            if (result.Success)
            {
                toolVm.IsInstalled = true;
                toolVm.Version = result.Version ?? "";
                toolVm.StatusGlyph = "\uE73E";
                toolVm.StatusColor = (SolidColorBrush)Application.Current.Resources["AccentGreenBrush"];
                toolVm.StatusText = AppLocalizer.Get("Installed successfully!");
                toolVm.ActionText = AppLocalizer.Get("Update");
            }
            else
            {
                toolVm.StatusText = AppLocalizer.Format($"Failed: {result.ErrorMessage}");
                toolVm.ActionText = AppLocalizer.Get("Retry");
            }
        }
        catch (Exception ex)
        {
            toolVm.StatusText = AppLocalizer.Format($"Error: {ex.Message}");
            toolVm.ActionText = AppLocalizer.Get("Retry");
        }
        finally
        {
            button.IsEnabled = true;
        }
    }

    private async void DownloadAllTools_Click(object sender, RoutedEventArgs e)
    {
        if (_toolDownloader == null)
        {
            await ShowMessageAsync(AppLocalizer.Get("Tool Download"),
                AppLocalizer.Get("Tool downloading is not available. Please install tools manually."));
            return;
        }

        var missingTools = _tools.Where(t => !t.IsInstalled).Select(t => t.Id).ToList();
        if (missingTools.Count == 0)
        {
            await ShowMessageAsync(AppLocalizer.Get("All Tools Installed"), AppLocalizer.Get("All converter tools are already installed."));
            return;
        }

        DownloadAllToolsButton.IsEnabled = false;
        DownloadAllToolsButton.Content = AppLocalizer.Get("Downloading...");

        try
        {
            var progress = new Progress<BatchDownloadProgress>(p =>
            {
                DispatcherQueue.TryEnqueue(() =>
                {
                    DownloadAllToolsButton.Content =
                        AppLocalizer.Format($"Downloading {p.CurrentTool} ({p.ToolsCompleted + 1}/{p.TotalTools})...");

                    var tool = _tools.FirstOrDefault(t => t.Id == p.CurrentTool);
                    if (tool != null)
                    {
                        tool.StatusText = AppLocalizer.Format($"Downloading... {p.CurrentProgress.Percent:F0}%");
                    }
                });
            });

            var results = await _toolDownloader.DownloadToolsAsync(missingTools, progress);

            var succeeded = results.Count(r => r.Success);
            var failed = results.Count(r => !r.Success);

            await ShowMessageAsync(
                AppLocalizer.Get("Download Complete"),
                AppLocalizer.Format($"Downloaded {succeeded} tools successfully.\n{(failed > 0 ? $"{failed} tools failed to download." : "")}"));

            LoadTools();
        }
        finally
        {
            DownloadAllToolsButton.IsEnabled = true;
            DownloadAllToolsButton.Content = AppLocalizer.Get("Install missing tools");
        }
    }

    private async void BrowsePostConversionArchive_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FolderPicker();
        picker.SuggestedStartLocation = PickerLocationId.DocumentsLibrary;
        picker.FileTypeFilter.Add("*");

        var hwnd = WindowNative.GetWindowHandle(this);
        InitializeWithWindow.Initialize(picker, hwnd);

        var folder = await picker.PickSingleFolderAsync();
        if (folder != null)
        {
            PostConversionArchiveTextBox.Text = folder.Path;
            MarkDirty();
        }
    }

    private async void BrowseQueueCompletionScript_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker
        {
            SuggestedStartLocation = PickerLocationId.DocumentsLibrary,
            ViewMode = PickerViewMode.List,
        };
        picker.FileTypeFilter.Add(".ps1");

        var hwnd = WindowNative.GetWindowHandle(this);
        InitializeWithWindow.Initialize(picker, hwnd);
        var file = await picker.PickSingleFileAsync();
        if (file is null) return;

        QueueCompletionScriptTextBox.Text = file.Path;
        MarkDirty();
    }

    private void ContextMenuToggle_Toggled(object sender, RoutedEventArgs e)
    {
        MarkDirty();
    }

    private async void RegisterShell_Click(object sender, RoutedEventArgs e)
    {
        await RunShellRegistrationAsync(register: true);
    }

    private async void UnregisterShell_Click(object sender, RoutedEventArgs e)
    {
        await RunShellRegistrationAsync(register: false);
    }

    private async Task RunShellRegistrationAsync(bool register)
    {
        var shellDll = FindShellExtensionComHost();
        if (shellDll is null)
        {
            await ShowMessageAsync(
                AppLocalizer.Get("Shell Integration"),
                AppLocalizer.Get("The shell extension is not present in this installation. Re-run the installer with Explorer integration enabled."));
            return;
        }

        var verb = register ? AppLocalizer.Get("registered") : AppLocalizer.Get("removed");
        var arguments = register
            ? $"/s \"{shellDll}\""
            : $"/u /s \"{shellDll}\"";
        try
        {
            using var process = Process.Start(new ProcessStartInfo
            {
                FileName = Path.Combine(Environment.SystemDirectory, "regsvr32.exe"),
                Arguments = arguments,
                UseShellExecute = true,
                Verb = "runas",
            });
            if (process is null)
            {
                await ShowMessageAsync(
                    AppLocalizer.Get("Shell Integration"),
                    AppLocalizer.Get("Windows could not start the elevated registration command."));
                return;
            }

            await process.WaitForExitAsync();
            await ShowMessageAsync(
                AppLocalizer.Get("Shell Integration"),
                process.ExitCode == 0
                    ? AppLocalizer.Format($"Explorer integration was {verb} successfully.")
                    : AppLocalizer.Format($"Explorer integration could not be {verb}. Windows returned exit code {process.ExitCode}."));
        }
        catch (Exception ex)
        {
            await ShowMessageAsync(
                AppLocalizer.Get("Shell Integration"),
                AppLocalizer.Format($"Explorer integration was not changed: {ex.Message}"));
        }
    }

    private static string? FindShellExtensionComHost()
    {
        const string fileName = "UniversalConverterX.ShellExtension.comhost.dll";
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "shell", fileName),
            Path.Combine(AppContext.BaseDirectory, fileName),
        };
        return candidates.FirstOrDefault(File.Exists);
    }

    private void ThemeComboBox_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (Content is FrameworkElement { IsLoaded: true })
            MarkDirty();

        var theme = ThemeComboBox.SelectedIndex switch
        {
            0 => ElementTheme.Light,
            1 => ElementTheme.Dark,
            _ => ElementTheme.Default
        };

        ApplyThemePreview(theme);
    }

    private void AccentColor_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button button && button.Tag is string colorHex)
        {
            _draftOptions.AccentColor = colorHex;
            App.ApplyAccentColor(colorHex);
            MarkDirty();
        }
    }

    private async void CheckUpdates_Click(object sender, RoutedEventArgs e)
    {
        CheckUpdatesButton.IsEnabled = false;
        CheckUpdatesButton.Content = AppLocalizer.Get("Checking...");
        OpenReleaseButton.Visibility = Visibility.Collapsed;
        _availableReleaseUrl = null;

        try
        {
            var checker = _serviceProvider.GetRequiredService<IUpdateCheckService>();
            var results = await checker.CheckAsync(force: true);
            if (results is null)
            {
                ShowUpdateStatus(
                    "Update check unavailable",
                    "No cached or live update information is available.",
                    InfoBarSeverity.Warning);
                return;
            }

            var appUpdate = results.Application;
            var toolUpdates = results.Tools.Where(tool => tool.UpdateAvailable).ToList();
            if (appUpdate?.UpdateAvailable == true)
            {
                _availableReleaseUrl = appUpdate.ReleaseUrl;
                OpenReleaseButton.Visibility = string.IsNullOrWhiteSpace(_availableReleaseUrl)
                    ? Visibility.Collapsed
                    : Visibility.Visible;

                if (appUpdate.CompatibilityWarnings.Count > 0)
                {
                    ShowUpdateStatus(
                        $"Version {appUpdate.LatestVersion ?? "update"} needs review",
                        "Before updating: " + string.Join(" ", appUpdate.CompatibilityWarnings),
                        InfoBarSeverity.Warning);
                }
                else
                {
                    ShowUpdateStatus(
                        $"Version {appUpdate.LatestVersion ?? "update"} is available",
                        appUpdate.CompatibilityMetadataAvailable
                            ? "Custom preset and saved queue compatibility checks passed."
                            : "No local compatibility issues were reported.",
                        InfoBarSeverity.Informational);
                }
                return;
            }

            if (toolUpdates.Count > 0)
            {
                ShowUpdateStatus(
                    "Tool updates available",
                    string.Join(", ", toolUpdates.Select(tool =>
                        string.IsNullOrWhiteSpace(tool.LatestVersion)
                            ? tool.DisplayName
                            : $"{tool.DisplayName} {tool.LatestVersion}")),
                    InfoBarSeverity.Informational);
                return;
            }

            if (!string.IsNullOrWhiteSpace(appUpdate?.Error))
            {
                ShowUpdateStatus(
                    "Application update check failed",
                    appUpdate.Error,
                    InfoBarSeverity.Warning);
                return;
            }

            ShowUpdateStatus(
                "You're up to date",
                "No UniversalConverter X or tracked tool updates were found.",
                InfoBarSeverity.Success);
        }
        catch (Exception ex)
        {
            ShowUpdateStatus(
                "Update check failed",
                ex.Message,
                InfoBarSeverity.Error);
        }
        finally
        {
            CheckUpdatesButton.IsEnabled = true;
            CheckUpdatesButton.Content = AppLocalizer.Get("Check again");
        }
    }

    private async void OpenRelease_Click(object sender, RoutedEventArgs e)
    {
        var url = string.IsNullOrWhiteSpace(_availableReleaseUrl)
            ? ReleasesUrl
            : _availableReleaseUrl;
        if (!await Launcher.LaunchUriAsync(new Uri(url)))
        {
            await ShowMessageAsync(
                AppLocalizer.Get("Releases"),
                AppLocalizer.Format($"Open the releases page manually:\n{url}"));
        }
    }

    private void ShowUpdateStatus(string title, string message, InfoBarSeverity severity)
    {
        UpdateStatusInfoBar.Title = title;
        UpdateStatusInfoBar.Message = message;
        UpdateStatusInfoBar.Severity = severity;
        UpdateStatusInfoBar.IsOpen = true;
    }

    private async void ResetSettings_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new ContentDialog
        {
            Title = AppLocalizer.Get("Reset Settings"),
            Content = AppLocalizer.Get("Reset preferences to their default values? Your files and installed tools are not changed."),
            PrimaryButtonText = AppLocalizer.Get("Reset"),
            CloseButtonText = AppLocalizer.Get("Cancel"),
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = Content.XamlRoot
        };
        ApplyDangerPrimary(dialog);

        var result = await dialog.ShowAsync();
        if (result == ContentDialogResult.Primary)
        {
            _draftOptions.ResetToDefaults();
            LoadSettings();
            MarkDirty();
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        if (_isDirty)
        {
            _ = ConfirmDiscardAndCloseAsync();
            return;
        }

        RestorePreview();
        Close();
    }

    private async Task ConfirmDiscardAndCloseAsync()
    {
        var dialog = new ContentDialog
        {
            Title = AppLocalizer.Get("Discard unsaved changes?"),
            Content = AppLocalizer.Get("You have changed settings that have not been saved."),
            PrimaryButtonText = AppLocalizer.Get("Discard"),
            CloseButtonText = AppLocalizer.Get("Keep editing"),
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = Content.XamlRoot
        };
        ApplyDangerPrimary(dialog);

        var result = await dialog.ShowAsync();
        if (result == ContentDialogResult.Primary)
        {
            RestorePreview();
            Close();
        }
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        // Save all settings
        SaveSettings();

        await ShowMessageAsync(AppLocalizer.Get("Settings Saved"), AppLocalizer.Get("Your settings have been saved successfully."));
        Close();
    }

    private void SaveSettings()
    {
        // General
        _options.DefaultOutputDirectory = string.IsNullOrWhiteSpace(OutputDirectoryTextBox.Text)
            ? null
            : OutputDirectoryTextBox.Text;
        _options.OverwriteBehavior = (OverwriteBehavior)OverwriteBehaviorComboBox.SelectedIndex;
        _options.PostConversionAction = (PostConversionAction)Math.Clamp(
            PostConversionActionComboBox.SelectedIndex,
            (int)PostConversionAction.Keep,
            (int)PostConversionAction.Delete);
        _options.PostConversionArchiveFolder = string.IsNullOrWhiteSpace(PostConversionArchiveTextBox.Text)
            ? (_options.PostConversionAction == PostConversionAction.Move ? "_converted-sources" : null)
            : PostConversionArchiveTextBox.Text.Trim();
        _options.DeleteSourceOnSuccess = _options.PostConversionAction == PostConversionAction.Delete;
        _options.ShowNotifications = NotificationsToggle.IsOn;
        _options.PlaySoundOnComplete = SoundToggle.IsOn;
        _options.QueueCompletionAction = (QueueCompletionAction)Math.Clamp(
            QueueCompletionActionComboBox.SelectedIndex,
            (int)QueueCompletionAction.None,
            (int)QueueCompletionAction.RunScript);
        _options.QueueCompletionScriptPath = string.IsNullOrWhiteSpace(QueueCompletionScriptTextBox.Text)
            ? null
            : QueueCompletionScriptTextBox.Text.Trim();

        // Quality & Performance
        _options.DefaultQuality = (Core.Models.QualityPreset)DefaultQualityComboBox.SelectedIndex;
        _options.DefaultHardwareAcceleration = GetSelectedHardwareAcceleration();
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
        _options.Language = LanguageTags[Math.Clamp(LanguageComboBox.SelectedIndex, 0, LanguageTags.Length - 1)];
        _options.StartMinimized = StartMinimizedToggle.IsOn;
        _options.AccentColor = _draftOptions.AccentColor;

        // Advanced
        _options.EnableFfmpegCommandEditing = FfmpegCommandEditingToggle.IsOn;

        // Save to file
        _options.Save();
        _draftOptions = CloneOptions(_options);

        _isDirty = false;
        UpdateDirtyState();
    }

    private static ConverterXOptions CloneOptions(ConverterXOptions options)
    {
        var serializerOptions = new JsonSerializerOptions
        {
            Converters = { new JsonStringEnumConverter() }
        };
        var json = JsonSerializer.Serialize(options, serializerOptions);
        return JsonSerializer.Deserialize<ConverterXOptions>(json, serializerOptions)
               ?? new ConverterXOptions();
    }

    private static int GetHardwareAccelerationIndex(HardwareAcceleration value) => value switch
    {
        HardwareAcceleration.Nvenc or HardwareAcceleration.Cuda => 1,
        HardwareAcceleration.Qsv => 2,
        HardwareAcceleration.Amf => 3,
        HardwareAcceleration.None => 4,
        _ => 0,
    };

    private HardwareAcceleration GetSelectedHardwareAcceleration()
    {
        if (HardwareAccelComboBox.SelectedItem is ComboBoxItem { Tag: string tag }
            && Enum.TryParse<HardwareAcceleration>(tag, ignoreCase: true, out var value))
        {
            return value;
        }

        return HardwareAcceleration.Auto;
    }

    private static ElementTheme ToElementTheme(AppTheme theme) => theme switch
    {
        AppTheme.Light => ElementTheme.Light,
        AppTheme.Dark => ElementTheme.Dark,
        _ => ElementTheme.Default,
    };

    private void ApplyThemePreview(ElementTheme theme)
    {
        if (Content is FrameworkElement root)
            root.RequestedTheme = theme;

        App.ApplyTheme(theme);
        App.ApplyAccentColor(_draftOptions.AccentColor);
    }

    private void RestorePreview()
    {
        ApplyThemePreview(ToElementTheme(_options.Theme));
        App.ApplyAccentColor(_options.AccentColor);
    }

    private void UpdatePostConversionArchiveState()
    {
        if (PostConversionArchiveTextBox is null || BrowsePostConversionArchiveButton is null)
            return;

        var isMove = PostConversionActionComboBox.SelectedIndex == (int)PostConversionAction.Move;
        PostConversionArchiveTextBox.IsEnabled = isMove;
        BrowsePostConversionArchiveButton.IsEnabled = isMove;
        if (isMove && string.IsNullOrWhiteSpace(PostConversionArchiveTextBox.Text))
            PostConversionArchiveTextBox.PlaceholderText = AppLocalizer.Get("_converted-sources");
    }

    private void UpdateQueueCompletionScriptState()
    {
        if (QueueCompletionScriptTextBox is null || BrowseQueueCompletionScriptButton is null)
            return;

        var enabled = QueueCompletionActionComboBox.SelectedIndex == (int)QueueCompletionAction.RunScript;
        QueueCompletionScriptTextBox.IsEnabled = enabled;
        BrowseQueueCompletionScriptButton.IsEnabled = enabled;
    }

    private void MarkDirty()
    {
        _isDirty = true;
        UpdateDirtyState();
    }

    private void UpdateDirtyState()
    {
        if (SaveButton is not null)
            SaveButton.IsEnabled = _isDirty;
        if (UnsavedStatusText is not null)
        {
            UnsavedStatusText.Text = _isDirty
                ? AppLocalizer.Get("Unsaved changes")
                : AppLocalizer.Get("No unsaved changes");
            UnsavedStatusText.Foreground = (SolidColorBrush)Application.Current.Resources[
                _isDirty ? "AccentOrangeBrush" : "TextMutedBrush"];
        }
        if (CancelButton is not null)
            CancelButton.Content = _isDirty
                ? AppLocalizer.Get("Cancel")
                : AppLocalizer.Get("Close");
    }

    private static void ApplyDangerPrimary(ContentDialog dialog)
    {
        if (Application.Current.Resources.TryGetValue("DangerButtonStyle", out var style)
            && style is Style dangerStyle)
        {
            dialog.PrimaryButtonStyle = dangerStyle;
        }
    }

    private async Task ShowMessageAsync(string title, string message)
    {
        var dialog = new ContentDialog
        {
            Title = title,
            Content = message,
            CloseButtonText = AppLocalizer.Get("OK"),
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

public sealed class PluginViewModel : CommunityToolkit.Mvvm.ComponentModel.ObservableObject
{
    private string _id = "";
    private string _name = "";
    private PluginTrustState _state;
    private string _statusGlyph = "";
    private SolidColorBrush _statusColor = new(Colors.Gray);
    private string _statusText = "";
    private string _sha256Display = "";
    private string _actionText = "";
    private bool _canChangeTrust;

    public string Id { get => _id; set => SetProperty(ref _id, value); }
    public string Name { get => _name; set => SetProperty(ref _name, value); }
    public PluginTrustState State { get => _state; set => SetProperty(ref _state, value); }
    public string StatusGlyph { get => _statusGlyph; set => SetProperty(ref _statusGlyph, value); }
    public SolidColorBrush StatusColor { get => _statusColor; set => SetProperty(ref _statusColor, value); }
    public string StatusText { get => _statusText; set => SetProperty(ref _statusText, value); }
    public string Sha256Display { get => _sha256Display; set => SetProperty(ref _sha256Display, value); }
    public string ActionText { get => _actionText; set => SetProperty(ref _actionText, value); }
    public bool CanChangeTrust { get => _canChangeTrust; set => SetProperty(ref _canChangeTrust, value); }
}
