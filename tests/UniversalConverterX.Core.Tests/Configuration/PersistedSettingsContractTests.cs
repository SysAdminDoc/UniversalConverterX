using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Configuration;

public sealed class PersistedSettingsContractTests
{
    [Fact]
    public void RemovedSettings_ShouldNotRemainAsPersistedNoOps()
    {
        var root = FindRepoRoot();
        var options = Read(root, "src/UniversalConverterX.Core/Configuration/ConverterXOptions.cs");
        var settings = Read(root, "src/UniversalConverterX.UI/Views/SettingsWindow.xaml");
        var migrations = Read(root, "src/UniversalConverterX.Core/Configuration/SettingsMigrations.cs");

        options.Should().NotContain("public bool MinimizeToTray");
        options.Should().NotContain("public bool StartWithWindows");
        settings.Should().NotContain("MinimizeToTrayToggle");
        migrations.Should().Contain("v3 -> v4");
        migrations.Should().Contain("v3.Remove(\"MinimizeToTray\")");
        migrations.Should().Contain("v3.Remove(\"StartWithWindows\")");
    }

    [Fact]
    public void VisibleSettings_ShouldHaveObservableRuntimeConsumers()
    {
        var root = FindRepoRoot();
        var settingsCode = Read(root, "src/UniversalConverterX.UI/Views/SettingsWindow.xaml.cs");
        var converter = Read(root, "src/UniversalConverterX.UI/Views/Pages/ConverterPage.xaml.cs");
        var progress = Read(root, "src/UniversalConverterX.UI/Views/ProgressWindow.xaml.cs");
        var app = Read(root, "src/UniversalConverterX.UI/App.xaml.cs");

        settingsCode.Should().Contain("_options.ShowNotifications = NotificationsToggle.IsOn");
        settingsCode.Should().Contain("_options.PlaySoundOnComplete = SoundToggle.IsOn");
        settingsCode.Should().Contain("_options.DefaultOutputDirectory");
        settingsCode.Should().Contain("_options.DefaultQuality");
        settingsCode.Should().Contain("_options.DefaultHardwareAcceleration");
        settingsCode.Should().Contain("_options.PreserveMetadataByDefault");
        settingsCode.Should().Contain("_options.AccentColor = _draftOptions.AccentColor");
        settingsCode.Should().Contain("regsvr32.exe");
        settingsCode.Should().Contain("StartMinimizedToggle.IsOn");

        converter.Should().Contain("_appOptions.DefaultQuality");
        converter.Should().Contain("_appOptions.DefaultHardwareAcceleration");
        converter.Should().Contain("_appOptions.PreserveMetadataByDefault");
        converter.Should().Contain("_appOptions.DefaultOutputDirectory");
        progress.Should().Contain("if (_options.PlaySoundOnComplete)");
        progress.Should().Contain("if (_options.ShowNotifications)");
        progress.Should().Contain("MessageBeep");
        app.Should().Contain("_startupOptions?.StartMinimized");
        app.Should().Contain("HideToBackground");
    }

    [Fact]
    public void ShellSettings_ShouldControlVisibilityStyleAndQuickPresetProjection()
    {
        var root = FindRepoRoot();
        var shellCommand = Read(root, "src/UniversalConverterX.ShellExtension/ExplorerCommand.cs");
        var shellSettings = Read(root, "src/UniversalConverterX.ShellExtension/ShellSettings.cs");

        shellCommand.Should().Contain("ShellIntegrationEnabled");
        shellCommand.Should().Contain("ContextMenuStyle.Single");
        shellCommand.Should().Contain("ContextMenuStyle.Flat");
        shellCommand.Should().Contain("ShellSettings.IsQuickPreset");
        shellSettings.Should().Contain("ConverterXOptions.Load()");
        shellSettings.Should().Contain("QuickConvertPresets");
    }

    private static string Read(string root, string relativePath) =>
        File.ReadAllText(Path.Combine(root, relativePath.Replace('/', Path.DirectorySeparatorChar)));

    private static string FindRepoRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Directory.Build.props")) &&
                File.Exists(Path.Combine(directory.FullName, "src", "UniversalConverterX.sln")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate the repository root.");
    }
}
