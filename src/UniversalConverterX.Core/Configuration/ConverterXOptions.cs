using System.Text.Json;
using System.Text.Json.Serialization;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Configuration;

/// <summary>
/// Configuration options for UniversalConverter X
/// </summary>
public class ConverterXOptions
{
    /// <summary>
    /// Configuration section name
    /// </summary>
    public const string SectionName = "ConverterX";

    private static readonly string SettingsFilePath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "UniversalConverterX", "settings.json");

    #region General Settings

    /// <summary>
    /// Base path where CLI tools are stored
    /// </summary>
    public string ToolsBasePath { get; set; } = GetDefaultToolsPath();

    /// <summary>
    /// Default output directory (null = same as input)
    /// </summary>
    public string? DefaultOutputDirectory { get; set; }

    /// <summary>
    /// Behavior when output file already exists
    /// </summary>
    public OverwriteBehavior OverwriteBehavior { get; set; } = OverwriteBehavior.Ask;

    /// <summary>
    /// Delete source files after successful conversion
    /// </summary>
    public bool DeleteSourceOnSuccess { get; set; } = false;

    /// <summary>
    /// Show system notifications on completion
    /// </summary>
    public bool ShowNotifications { get; set; } = true;

    /// <summary>
    /// Play sound when conversion completes
    /// </summary>
    public bool PlaySoundOnComplete { get; set; } = true;

    /// <summary>
    /// Maximum concurrent conversions
    /// </summary>
    public int MaxParallelConversions { get; set; } = Math.Max(1, Environment.ProcessorCount / 2);

    /// <summary>
    /// Default timeout for conversions
    /// </summary>
    public TimeSpan DefaultTimeout { get; set; } = TimeSpan.FromHours(1);

    #endregion

    #region Quality & Performance

    /// <summary>
    /// Default quality preset
    /// </summary>
    public QualityPreset DefaultQuality { get; set; } = QualityPreset.High;

    /// <summary>
    /// Default hardware acceleration method
    /// </summary>
    public HardwareAcceleration DefaultHardwareAcceleration { get; set; } = HardwareAcceleration.Auto;

    /// <summary>
    /// Enable hardware acceleration by default
    /// </summary>
    public bool EnableHardwareAcceleration { get; set; } = true;

    /// <summary>
    /// Preserve metadata by default
    /// </summary>
    public bool PreserveMetadataByDefault { get; set; } = true;

    #endregion

    #region Shell Integration

    /// <summary>
    /// Enable shell context menu integration
    /// </summary>
    public bool ShellIntegrationEnabled { get; set; } = true;

    /// <summary>
    /// Context menu display style
    /// </summary>
    public ContextMenuStyle ContextMenuStyle { get; set; } = ContextMenuStyle.Cascading;

    /// <summary>
    /// Quick convert presets shown in context menu
    /// </summary>
    public List<string> QuickConvertPresets { get; set; } = ["webp", "png", "jpg", "mp4", "mp3", "pdf"];

    /// <summary>
    /// Shell extension detailed settings
    /// </summary>
    public ShellExtensionOptions ShellExtension { get; set; } = new();

    #endregion

    #region Appearance

    /// <summary>
    /// Application theme
    /// </summary>
    public AppTheme Theme { get; set; } = AppTheme.System;

    /// <summary>
    /// Accent color hex value
    /// </summary>
    public string AccentColor { get; set; } = "#22c55e";

    /// <summary>
    /// Minimize to system tray instead of taskbar
    /// </summary>
    public bool MinimizeToTray { get; set; } = false;

    /// <summary>
    /// Start application minimized
    /// </summary>
    public bool StartMinimized { get; set; } = false;

    /// <summary>
    /// Start with Windows
    /// </summary>
    public bool StartWithWindows { get; set; } = false;

    #endregion

    #region Advanced

    /// <summary>
    /// Temporary directory for intermediate files
    /// </summary>
    public string TempDirectory { get; set; } = Path.GetTempPath();

    /// <summary>
    /// Keep failed conversion output files for debugging
    /// </summary>
    public bool KeepFailedOutput { get; set; } = false;

    /// <summary>
    /// Log converter output for debugging
    /// </summary>
    public bool VerboseLogging { get; set; } = false;

    /// <summary>
    /// Auto-download missing tools
    /// </summary>
    public bool AutoDownloadTools { get; set; } = false;

    /// <summary>
    /// Verify tool checksums before use
    /// </summary>
    public bool VerifyToolIntegrity { get; set; } = true;

    /// <summary>
    /// Check for application updates on startup
    /// </summary>
    public bool CheckForUpdates { get; set; } = true;

    #endregion

    #region Conversion History

    /// <summary>
    /// Enable conversion history tracking
    /// </summary>
    public bool EnableHistory { get; set; } = true;

    /// <summary>
    /// Maximum history entries to keep
    /// </summary>
    public int MaxHistoryEntries { get; set; } = 1000;

    /// <summary>
    /// Days to keep history
    /// </summary>
    public int HistoryRetentionDays { get; set; } = 30;

    #endregion

    #region Methods

    /// <summary>
    /// Save settings to file
    /// </summary>
    public void Save()
    {
        var directory = Path.GetDirectoryName(SettingsFilePath);
        if (!string.IsNullOrEmpty(directory) && !Directory.Exists(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var options = new JsonSerializerOptions
        {
            WriteIndented = true,
            Converters = { new JsonStringEnumConverter() }
        };

        var json = JsonSerializer.Serialize(this, options);
        File.WriteAllText(SettingsFilePath, json);
    }

    /// <summary>
    /// Load settings from file
    /// </summary>
    public static ConverterXOptions Load()
    {
        if (!File.Exists(SettingsFilePath))
            return new ConverterXOptions();

        try
        {
            var json = File.ReadAllText(SettingsFilePath);
            var options = new JsonSerializerOptions
            {
                Converters = { new JsonStringEnumConverter() }
            };
            return JsonSerializer.Deserialize<ConverterXOptions>(json, options) ?? new ConverterXOptions();
        }
        catch
        {
            return new ConverterXOptions();
        }
    }

    /// <summary>
    /// Reset all settings to default values
    /// </summary>
    public void ResetToDefaults()
    {
        var defaults = new ConverterXOptions();

        // Copy all properties
        ToolsBasePath = defaults.ToolsBasePath;
        DefaultOutputDirectory = defaults.DefaultOutputDirectory;
        OverwriteBehavior = defaults.OverwriteBehavior;
        DeleteSourceOnSuccess = defaults.DeleteSourceOnSuccess;
        ShowNotifications = defaults.ShowNotifications;
        PlaySoundOnComplete = defaults.PlaySoundOnComplete;
        MaxParallelConversions = defaults.MaxParallelConversions;
        DefaultTimeout = defaults.DefaultTimeout;
        DefaultQuality = defaults.DefaultQuality;
        DefaultHardwareAcceleration = defaults.DefaultHardwareAcceleration;
        EnableHardwareAcceleration = defaults.EnableHardwareAcceleration;
        PreserveMetadataByDefault = defaults.PreserveMetadataByDefault;
        ShellIntegrationEnabled = defaults.ShellIntegrationEnabled;
        ContextMenuStyle = defaults.ContextMenuStyle;
        QuickConvertPresets = defaults.QuickConvertPresets;
        Theme = defaults.Theme;
        AccentColor = defaults.AccentColor;
        MinimizeToTray = defaults.MinimizeToTray;
        StartMinimized = defaults.StartMinimized;
        StartWithWindows = defaults.StartWithWindows;
        TempDirectory = defaults.TempDirectory;
        KeepFailedOutput = defaults.KeepFailedOutput;
        VerboseLogging = defaults.VerboseLogging;
        AutoDownloadTools = defaults.AutoDownloadTools;
        VerifyToolIntegrity = defaults.VerifyToolIntegrity;
        CheckForUpdates = defaults.CheckForUpdates;
        EnableHistory = defaults.EnableHistory;
        MaxHistoryEntries = defaults.MaxHistoryEntries;
        HistoryRetentionDays = defaults.HistoryRetentionDays;
    }

    private static string GetDefaultToolsPath()
    {
        // Check common locations
        var locations = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "tools"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), 
                "UniversalConverterX", "tools"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                "UniversalConverterX", "tools")
        };

        foreach (var loc in locations)
        {
            if (Directory.Exists(loc))
                return loc;
        }

        // Return user-local option as default
        return locations[1];
    }

    #endregion
}

/// <summary>
/// Behavior when output file already exists
/// </summary>
public enum OverwriteBehavior
{
    Ask,
    Always,
    Never,
    Skip
}

/// <summary>
/// Context menu display style
/// </summary>
public enum ContextMenuStyle
{
    Cascading,
    Flat,
    Single
}

/// <summary>
/// Application theme
/// </summary>
public enum AppTheme
{
    Light,
    Dark,
    System
}

/// <summary>
/// Shell extension configuration
/// </summary>
public class ShellExtensionOptions
{
    /// <summary>
    /// Enable context menu integration
    /// </summary>
    public bool Enabled { get; set; } = true;

    /// <summary>
    /// Show sub-menu or direct format options
    /// </summary>
    public bool UseSubMenu { get; set; } = true;

    /// <summary>
    /// Maximum formats to show in context menu
    /// </summary>
    public int MaxContextMenuItems { get; set; } = 10;

    /// <summary>
    /// Show icon in context menu
    /// </summary>
    public bool ShowIcon { get; set; } = true;

    /// <summary>
    /// Position in context menu (lower = higher in menu)
    /// </summary>
    public int MenuPosition { get; set; } = 100;

    /// <summary>
    /// Quick convert presets
    /// </summary>
    public List<QuickConvertPreset> Presets { get; set; } =
    [
        new() { Name = "Images", Formats = ["png", "jpg", "webp", "gif"] },
        new() { Name = "Video", Formats = ["mp4", "mkv", "webm", "gif"] },
        new() { Name = "Audio", Formats = ["mp3", "wav", "flac", "m4a"] },
        new() { Name = "Documents", Formats = ["pdf", "docx", "html", "md"] }
    ];
}

/// <summary>
/// Quick convert preset definition
/// </summary>
public class QuickConvertPreset
{
    /// <summary>
    /// Preset name
    /// </summary>
    public string Name { get; set; } = "";

    /// <summary>
    /// Target formats in this preset
    /// </summary>
    public List<string> Formats { get; set; } = [];

    /// <summary>
    /// Icon for the preset
    /// </summary>
    public string? Icon { get; set; }

    /// <summary>
    /// Whether this preset is enabled
    /// </summary>
    public bool Enabled { get; set; } = true;
}
