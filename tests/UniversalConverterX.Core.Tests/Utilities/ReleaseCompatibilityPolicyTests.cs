using FluentAssertions;
using UniversalConverterX.Core.Services;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class ReleaseCompatibilityPolicyTests
{
    [Fact]
    public void ParseManifest_RejectsWrongProductOrMalformedJson()
    {
        ReleaseCompatibilityPolicy.ParseManifest("{not-json").Should().BeNull();
        ReleaseCompatibilityPolicy.ParseManifest(
            """{"schemaVersion":1,"product":"Other","version":"3.0.0"}""").Should().BeNull();
    }

    [Fact]
    public void ParseManifest_ReadsCompatibilityContract()
    {
        var manifest = ReleaseCompatibilityPolicy.ParseManifest(
            """
            {
              "schemaVersion": 1,
              "product": "UniversalConverterX",
              "version": "3.0.0",
              "compatibility": {
                "minimumPresetSchemaVersion": 1,
                "maximumPresetSchemaVersion": 2,
                "minimumQueueSchemaVersion": 1,
                "maximumQueueSchemaVersion": 1,
                "supportedEngines": ["converter", "videocrush"]
              }
            }
            """);

        manifest.Should().NotBeNull();
        manifest!.Compatibility.Should().NotBeNull();
        manifest.Compatibility!.MaximumPresetSchemaVersion.Should().Be(2);
        manifest.Compatibility.SupportedEngines.Should().Equal("converter", "videocrush");
    }

    [Fact]
    public void Assess_ReportsSchemaAndEngineCompatibilityWarnings()
    {
        var requirements = new ReleaseCompatibilityRequirements
        {
            MinimumPresetSchemaVersion = 2,
            MaximumPresetSchemaVersion = 3,
            MinimumQueueSchemaVersion = 1,
            MaximumQueueSchemaVersion = 1,
            SupportedEngines = ["converter", "videocrush"],
        };
        LocalPresetCompatibility[] presets =
        [
            new(true, 1, "legacy-engine"),
            new(false, null, null),
        ];
        PersistedBatchQueue[] queues =
        [
            new()
            {
                SchemaVersion = 2,
                QueueKey = "converter",
                Jobs = [new PersistedBatchJob { Engine = "removed-engine" }],
            },
        ];

        var result = ReleaseCompatibilityPolicy.Assess(requirements, presets, queues);

        result.HasWarnings.Should().BeTrue();
        result.Warnings.Should().Contain(warning => warning.Contains("could not be inspected"));
        result.Warnings.Should().Contain(warning => warning.Contains("preset uses a schema"));
        result.Warnings.Should().Contain(warning => warning.Contains("queue uses a schema"));
        result.Warnings.Should().Contain(warning => warning.Contains("legacy-engine"));
        result.Warnings.Should().Contain(warning => warning.Contains("removed-engine"));
    }

    [Fact]
    public void Assess_CompatibleStateHasNoWarnings()
    {
        var requirements = new ReleaseCompatibilityRequirements
        {
            SupportedEngines = ["converter"],
        };
        LocalPresetCompatibility[] presets = [new(true, 1, "converter")];
        PersistedBatchQueue[] queues =
        [
            new()
            {
                QueueKey = "converter",
                Jobs = [new PersistedBatchJob { Engine = "converter" }],
            },
        ];

        ReleaseCompatibilityPolicy.Assess(requirements, presets, queues)
            .Warnings.Should().BeEmpty();
    }
}
