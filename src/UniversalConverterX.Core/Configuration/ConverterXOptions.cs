using System.Text.Json;
using System.Text.Json.Nodes;
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

    /// <summary>
    /// Current on-disk schema version. Bump this whenever a field is renamed,
    /// removed, or changes semantics in a way that needs a migration. Add
    /// the corresponding entry to <see cref="SettingsMigrations.Migrations"/>
    /// in the same commit.
    /// </summary>
    /// <remarks>
    /// History:
    ///   v1 — implicit (pre-2026-05-02). No <c>SchemaVersion</c> field.
    ///        OverwriteBehavior default was "Ask".
    ///   v2 — 2026-05-02. SchemaVersion field added. OverwriteBehavior default
    ///        flipped to "Never" for fresh installs (persisted user values
    ///        unchanged by the migrator).
    ///   v3 — 2026-06-28. PostConversionAction replaces DeleteSourceOnSuccess.
    ///        Migration: DeleteSourceOnSuccess=true → PostConversionAction="Delete".
    /// </remarks>
    public const int CurrentSchemaVersion = 3;

    private static readonly string SettingsFilePath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "UniversalConverterX", "settings.json");

    /// <summary>
    /// On-disk schema version this options instance was loaded from / will
    /// be saved as. New instances default to <see cref="CurrentSchemaVersion"/>.
    /// </summary>
    public int SchemaVersion { get; set; } = CurrentSchemaVersion;

    #region General Settings

    /// <summary>
    /// Base path where CLI tools are stored
    /// </summary>
    public string ToolsBasePath { get; set; } = GetDefaultToolsPath();

    /// <summary>
    /// Search PATH and common install locations for converter tools when they are not bundled locally
    /// </summary>
    public bool SearchSystemTools { get; set; } = true;

    /// <summary>
    /// Default output directory (null = same as input)
    /// </summary>
    public string? DefaultOutputDirectory { get; set; }

    /// <summary>
    /// Behavior when output file already exists. Default is <c>Never</c>
    /// (auto-rename to "stem (1).ext", "stem (2).ext", ...) so jobs never
    /// silently overwrite existing files. UI surfaces that genuinely prompt
    /// the user can flip this to <c>Ask</c>; CLI / batch contexts get the
    /// safer default.
    /// </summary>
    public OverwriteBehavior OverwriteBehavior { get; set; } = OverwriteBehavior.Never;

    /// <summary>
    /// Delete source files after successful conversion.
    /// Deprecated — use <see cref="PostConversionAction"/> instead.
    /// Retained for JSON backward compatibility; v2→v3 migration
    /// converts true values to PostConversionAction.Delete.
    /// </summary>
    public bool DeleteSourceOnSuccess { get; set; } = false;

    /// <summary>
    /// Action to take on source files after a successful conversion.
    /// Keep (default) = leave the source untouched.
    /// Move = relocate the source to <see cref="PostConversionArchiveFolder"/>.
    /// Delete = remove the source file permanently.
    /// </summary>
    public PostConversionAction PostConversionAction { get; set; } = PostConversionAction.Keep;

    /// <summary>
    /// Folder to move source files to when <see cref="PostConversionAction"/>
    /// is Move. Absolute paths are used as-is; relative paths resolve from
    /// the source file's parent directory.
    /// </summary>
    public string? PostConversionArchiveFolder { get; set; }

    /// <summary>
    /// Show system notifications on completion
    /// </summary>
    public bool ShowNotifications { get; set; } = true;

    /// <summary>
    /// Play sound when conversion completes
    /// </summary>
    public bool PlaySoundOnComplete { get; set; } = true;

    /// <summary>
    /// Optional action after a Converter, Compressor, or Downloader queue completes.
    /// Power actions are safety-gated to completely successful queues.
    /// </summary>
    public QueueCompletionAction QueueCompletionAction { get; set; } = QueueCompletionAction.Notify;

    /// <summary>
    /// PowerShell script launched for <see cref="Models.QueueCompletionAction.RunScript"/>.
    /// The first argument is the generated JSON queue-summary path.
    /// </summary>
    public string? QueueCompletionScriptPath { get; set; }

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
    public AppTheme Theme { get; set; } = AppTheme.Dark;

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

    /// <summary>
    /// Allow Advanced Mode to pause FFmpeg dispatch so the generated argument
    /// vector can be edited. Off by default because edited commands bypass the
    /// normal codec/profile guardrails.
    /// </summary>
    public bool EnableFfmpegCommandEditing { get; set; } = false;

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

    #region Output Duration Validation (ROADMAP Item 72)

    /// <summary>
    /// After every successful media job, probe the output file with FFprobe and
    /// compare its duration against the input. When the gap is larger than
    /// <see cref="MinDurationDeltaSeconds"/> (or 1% of the input, whichever is
    /// smaller), the result is flagged as <c>PARTIAL / TRUNCATED</c> so the
    /// user notices silent video truncation (HandBrake #7828 class of bug).
    /// Local-only check via the bundled FFprobe binary.
    /// </summary>
    public bool ValidateOutputDuration { get; set; } = true;

    /// <summary>
    /// Maximum tolerated input/output duration delta in seconds before the job
    /// is flagged as truncated. Default 2 seconds — generous enough to cover
    /// container-rounding error but tight enough to surface the seconds-to-
    /// minutes truncations the validator targets.
    /// </summary>
    public double MinDurationDeltaSeconds { get; set; } = 2.0;

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
        var tmp = SettingsFilePath + ".tmp";
        File.WriteAllText(tmp, json);
        try { File.Move(tmp, SettingsFilePath, overwrite: true); }
        catch
        {
            File.WriteAllText(SettingsFilePath, json);
            try { File.Delete(tmp); } catch { }
        }
    }

    /// <summary>
    /// Load settings from file. Older schema versions are migrated through
    /// <see cref="SettingsMigrations"/> before deserialization; the upgraded
    /// JSON is persisted back to disk so the next load skips the migration
    /// chain. Corrupt files are backed up and a default instance is returned.
    /// </summary>
    public static ConverterXOptions Load()
    {
        if (!File.Exists(SettingsFilePath))
            return new ConverterXOptions();

        try
        {
            var json = File.ReadAllText(SettingsFilePath);
            return LoadFromJson(json, persistMigrated: true);
        }
        catch
        {
            try
            {
                var backup = SettingsFilePath + ".corrupt." + DateTime.UtcNow.ToString("yyyyMMddHHmmss");
                File.Copy(SettingsFilePath, backup, overwrite: true);
            }
            catch { }
            return new ConverterXOptions();
        }
    }

    /// <summary>
    /// Parse a settings JSON string, applying schema migrations if the on-disk
    /// version is older than <see cref="CurrentSchemaVersion"/>. Public so the
    /// CLI / any future external caller routes legacy reads through the same
    /// migration chain.
    /// </summary>
    /// <param name="json">Raw JSON contents.</param>
    /// <param name="persistMigrated">When true, the upgraded JSON is written
    /// back to <see cref="SettingsFilePath"/> after a successful migration.
    /// External callers should pass false unless they specifically intend to
    /// rewrite the user's primary settings file.</param>
    public static ConverterXOptions LoadFromJson(string json, bool persistMigrated = false)
    {
        var node = JsonNode.Parse(json) as JsonObject
                   ?? throw new JsonException("settings root is not a JSON object");

        var fromVersion = (int?)node["SchemaVersion"] ?? 1;
        var migrated = SettingsMigrations.Migrate(node, fromVersion, CurrentSchemaVersion,
                                                  out var didMigrate);

        var serializerOptions = new JsonSerializerOptions
        {
            Converters = { new JsonStringEnumConverter() }
        };
        var loaded = migrated.Deserialize<ConverterXOptions>(serializerOptions)
                     ?? new ConverterXOptions();
        loaded.SchemaVersion = CurrentSchemaVersion;

        if (didMigrate && persistMigrated)
        {
            try
            {
                loaded.Save();
            }
            catch
            {
                // Save is best-effort; if it fails (read-only profile, locked
                // file) the next process will just re-run the migration.
            }
        }

        return loaded;
    }

    /// <summary>
    /// Reset all settings to default values
    /// </summary>
    public void ResetToDefaults()
    {
        var defaults = new ConverterXOptions();

        // Copy all properties
        ToolsBasePath = defaults.ToolsBasePath;
        SearchSystemTools = defaults.SearchSystemTools;
        DefaultOutputDirectory = defaults.DefaultOutputDirectory;
        OverwriteBehavior = defaults.OverwriteBehavior;
        DeleteSourceOnSuccess = defaults.DeleteSourceOnSuccess;
        PostConversionAction = defaults.PostConversionAction;
        PostConversionArchiveFolder = defaults.PostConversionArchiveFolder;
        ShowNotifications = defaults.ShowNotifications;
        PlaySoundOnComplete = defaults.PlaySoundOnComplete;
        QueueCompletionAction = defaults.QueueCompletionAction;
        QueueCompletionScriptPath = defaults.QueueCompletionScriptPath;
        MaxParallelConversions = defaults.MaxParallelConversions;
        DefaultTimeout = defaults.DefaultTimeout;
        DefaultQuality = defaults.DefaultQuality;
        DefaultHardwareAcceleration = defaults.DefaultHardwareAcceleration;
        EnableHardwareAcceleration = defaults.EnableHardwareAcceleration;
        PreserveMetadataByDefault = defaults.PreserveMetadataByDefault;
        ShellIntegrationEnabled = defaults.ShellIntegrationEnabled;
        ContextMenuStyle = defaults.ContextMenuStyle;
        QuickConvertPresets = defaults.QuickConvertPresets;
        ShellExtension = defaults.ShellExtension;
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
        EnableFfmpegCommandEditing = defaults.EnableFfmpegCommandEditing;
        EnableHistory = defaults.EnableHistory;
        MaxHistoryEntries = defaults.MaxHistoryEntries;
        HistoryRetentionDays = defaults.HistoryRetentionDays;
        ValidateOutputDuration = defaults.ValidateOutputDuration;
        MinDurationDeltaSeconds = defaults.MinDurationDeltaSeconds;
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
