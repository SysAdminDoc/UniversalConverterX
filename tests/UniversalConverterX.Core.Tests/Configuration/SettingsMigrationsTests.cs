using System.Text.Json.Nodes;
using FluentAssertions;
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
}
