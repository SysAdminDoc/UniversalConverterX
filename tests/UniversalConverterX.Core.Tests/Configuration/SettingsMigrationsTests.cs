using FluentAssertions;
using System.Text.Json;
using System.Text.Json.Nodes;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Configuration;

public class SettingsMigrationsTests
{
    [Fact]
    public void LoadFromJson_LegacyJsonWithoutSchemaVersion_TreatedAsV1AndUpgraded()
    {
        // Pre-Item-53 settings.json had no SchemaVersion key. The migrator
        // must default it to v1 and stamp the upgraded version after.
        var legacyJson = """
        {
          "OverwriteBehavior": "Ask",
          "MaxParallelConversions": 4
        }
        """;

        var loaded = ConverterXOptions.LoadFromJson(legacyJson, persistMigrated: false);

        loaded.SchemaVersion.Should().Be(ConverterXOptions.CurrentSchemaVersion);
        loaded.MaxParallelConversions.Should().Be(4);
        // Persisted user value is preserved — the iter-1 default flip from
        // Ask to Never only affects fresh installs.
        loaded.OverwriteBehavior.Should().Be(OverwriteBehavior.Ask);
    }

    [Fact]
    public void LoadFromJson_CurrentSchemaVersion_NoMigrationNeeded()
    {
        var currentJson = $$"""
        {
          "SchemaVersion": {{ConverterXOptions.CurrentSchemaVersion}},
          "OverwriteBehavior": "Skip",
          "MaxParallelConversions": 8
        }
        """;

        var loaded = ConverterXOptions.LoadFromJson(currentJson, persistMigrated: false);

        loaded.SchemaVersion.Should().Be(ConverterXOptions.CurrentSchemaVersion);
        loaded.OverwriteBehavior.Should().Be(OverwriteBehavior.Skip);
        loaded.MaxParallelConversions.Should().Be(8);
    }

    [Fact]
    public void LoadFromJson_FutureSchemaVersion_DoesNotCrash()
    {
        // A SettingsJson written by a future UCX. The current binary should
        // load whatever fields it understands and not loop or throw.
        var futureJson = """
        {
          "SchemaVersion": 999,
          "OverwriteBehavior": "Always",
          "FutureUnknownField": "ignored"
        }
        """;

        var loaded = ConverterXOptions.LoadFromJson(futureJson, persistMigrated: false);

        // The migrator clamps SchemaVersion back to CurrentSchemaVersion on
        // its way out — the in-memory instance always reports the schema it
        // can faithfully serialize.
        loaded.SchemaVersion.Should().Be(ConverterXOptions.CurrentSchemaVersion);
        loaded.OverwriteBehavior.Should().Be(OverwriteBehavior.Always);
    }

    [Fact]
    public void Migrate_StampsTargetVersion_OnLegacyTree()
    {
        var root = new JsonObject { ["OverwriteBehavior"] = "Ask" };

        var result = SettingsMigrations.Migrate(root, fromVersion: 1, toVersion: 2,
                                                out var didMigrate);

        didMigrate.Should().BeTrue();
        ((int?)result["SchemaVersion"]).Should().Be(2);
        ((string?)result["OverwriteBehavior"]).Should().Be("Ask");
    }

    [Fact]
    public void Migrate_OnMigrationGap_StampsOnlyTheVersionReached()
    {
        // A future target with no migration for the gap must not falsely stamp
        // the tree as fully migrated — otherwise the loader persists the false
        // stamp and permanently skips the (later-added) transform.
        var root = new JsonObject { ["OverwriteBehavior"] = "Ask" };

        // toVersion far beyond the known migrations (v1->v2, v2->v3).
        var result = SettingsMigrations.Migrate(root, fromVersion: 1, toVersion: 99,
                                                out var didMigrate);

        didMigrate.Should().BeTrue();
        // Only the migrations that actually ran advance the stamp — not toVersion.
        ((int?)result["SchemaVersion"]).Should().BeLessThan(99);
        ((int?)result["SchemaVersion"]).Should().BeGreaterThanOrEqualTo(3);
    }

    [Fact]
    public void Migrate_NoOpWhenAlreadyAtTarget()
    {
        var root = new JsonObject
        {
            ["SchemaVersion"] = 2,
            ["OverwriteBehavior"] = "Never",
        };

        SettingsMigrations.Migrate(root, fromVersion: 2, toVersion: 2, out var didMigrate);

        didMigrate.Should().BeFalse();
    }

    [Fact]
    public void LoadFromJson_NewInstance_UsesCurrentSchemaVersion()
    {
        // A new ConverterXOptions in C# (not loaded from disk) defaults to
        // CurrentSchemaVersion so freshly-created instances serialize
        // unambiguously.
        var fresh = new ConverterXOptions();

        fresh.SchemaVersion.Should().Be(ConverterXOptions.CurrentSchemaVersion);
    }

    [Fact]
    public void NewInstance_DisablesFfmpegCommandEditingByDefault()
    {
        new ConverterXOptions().EnableFfmpegCommandEditing.Should().BeFalse();
    }

    [Fact]
    public void LoadFromJson_ShouldPreservePostQueueAutomationSettings()
    {
        var json = $$"""
        {
          "SchemaVersion": {{ConverterXOptions.CurrentSchemaVersion}},
          "QueueCompletionAction": "RunScript",
          "QueueCompletionScriptPath": "C:\\Automation\\after-queue.ps1"
        }
        """;

        var loaded = ConverterXOptions.LoadFromJson(json, persistMigrated: false);

        loaded.QueueCompletionAction.Should().Be(QueueCompletionAction.RunScript);
        loaded.QueueCompletionScriptPath.Should().Be(@"C:\Automation\after-queue.ps1");

        loaded.ResetToDefaults();
        loaded.QueueCompletionAction.Should().Be(QueueCompletionAction.Notify);
        loaded.QueueCompletionScriptPath.Should().BeNull();
    }

    [Fact]
    public void MergeSerializedSettings_PreservesUiOwnedKeysAndUpdatesCoreKeys()
    {
        var existing = """
        {
          "ToolsPath": "C:\\ui-tools",
          "UseCustomOutputDirectory": true,
          "MaxParallelConversions": 2,
          "UiOnlyObject": { "keep": true }
        }
        """;
        var current = """
        {
          "SchemaVersion": 3,
          "ToolsBasePath": "C:\\core-tools",
          "MaxParallelConversions": 8
        }
        """;

        var merged = JsonNode.Parse(
            ConverterXOptions.MergeSerializedSettings(existing, current))!.AsObject();

        ((string?)merged["ToolsPath"]).Should().Be(@"C:\ui-tools");
        ((bool?)merged["UseCustomOutputDirectory"]).Should().BeTrue();
        ((int?)merged["MaxParallelConversions"]).Should().Be(8);
        ((string?)merged["ToolsBasePath"]).Should().Be(@"C:\core-tools");
        ((bool?)merged["UiOnlyObject"]?["keep"]).Should().BeTrue();
    }

    [Fact]
    public void ResetToDefaults_RestoresEveryPublicSettableProperty()
    {
        var options = new ConverterXOptions
        {
            ContainSidecarProcesses = false,
            SidecarMaxProcesses = 1,
            SidecarMaxMemoryMegabytes = 512,
            SidecarMaxRuntime = TimeSpan.FromMinutes(5),
            UsePrivateSidecarTemp = false,
            EnforceSidecarOutputBoundary = false,
            Language = "fr-FR",
            MaxParallelConversions = 1,
            DefaultQuality = QualityPreset.Low,
            QuickConvertPresets = ["changed"],
        };

        options.ResetToDefaults();

        var expected = JsonSerializer.Serialize(new ConverterXOptions());
        var actual = JsonSerializer.Serialize(options);
        actual.Should().Be(expected);
    }

    [Fact]
    public void LoadFromJson_InvalidRoot_Throws()
    {
        // The Load() entry point catches this and falls back to defaults; the
        // internal helper surfaces it so tests can distinguish corruption
        // from valid empty objects.
        var notAnObject = "[1, 2, 3]";

        FluentActions.Invoking(() => ConverterXOptions.LoadFromJson(notAnObject, persistMigrated: false))
            .Should().Throw<System.Text.Json.JsonException>();
    }

    [Fact]
    public void Migrate_V2ToV3_DeleteSourceTrue_SetsPostConversionActionDelete()
    {
        var root = new JsonObject
        {
            ["SchemaVersion"] = 2,
            ["DeleteSourceOnSuccess"] = true,
        };

        SettingsMigrations.Migrate(root, fromVersion: 2, toVersion: 3, out var didMigrate);

        didMigrate.Should().BeTrue();
        ((string?)root["PostConversionAction"]).Should().Be("Delete");
    }

    [Fact]
    public void Migrate_V2ToV3_DeleteSourceFalse_LeavesPostConversionActionAbsent()
    {
        var root = new JsonObject
        {
            ["SchemaVersion"] = 2,
            ["DeleteSourceOnSuccess"] = false,
        };

        SettingsMigrations.Migrate(root, fromVersion: 2, toVersion: 3, out _);

        root.ContainsKey("PostConversionAction").Should().BeFalse();
    }

    [Fact]
    public void Migrate_V2ToV3_ExplicitPostConversionAction_NotOverwritten()
    {
        var root = new JsonObject
        {
            ["SchemaVersion"] = 2,
            ["DeleteSourceOnSuccess"] = true,
            ["PostConversionAction"] = "Move",
        };

        SettingsMigrations.Migrate(root, fromVersion: 2, toVersion: 3, out _);

        ((string?)root["PostConversionAction"]).Should().Be("Move");
    }

    [Fact]
    public void LoadFromJson_V2WithDeleteTrue_LoadsAsPostConversionDelete()
    {
        var json = """
        {
          "SchemaVersion": 2,
          "DeleteSourceOnSuccess": true
        }
        """;

        var loaded = ConverterXOptions.LoadFromJson(json, persistMigrated: false);

        loaded.PostConversionAction.Should().Be(PostConversionAction.Delete);
    }

    [Fact]
    public void Migrate_V3ToV4_RemovesUnsupportedWindowLifecycleToggles()
    {
        var root = new JsonObject
        {
            ["SchemaVersion"] = 3,
            ["MinimizeToTray"] = true,
            ["StartWithWindows"] = true,
            ["StartMinimized"] = true,
        };

        SettingsMigrations.Migrate(root, fromVersion: 3, toVersion: 4, out var didMigrate);

        didMigrate.Should().BeTrue();
        ((int?)root["SchemaVersion"]).Should().Be(4);
        root.ContainsKey("MinimizeToTray").Should().BeFalse();
        root.ContainsKey("StartWithWindows").Should().BeFalse();
        ((bool?)root["StartMinimized"]).Should().BeTrue();
    }
}
