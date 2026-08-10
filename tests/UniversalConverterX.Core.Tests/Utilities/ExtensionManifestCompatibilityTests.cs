using System.Text.Json;
using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class ExtensionManifestCompatibilityTests
{
    [Fact]
    public void ValidateJson_AcceptsCurrentContract()
    {
        var result = Validate(CurrentManifest());

        result.IsCompatible.Should().BeTrue();
        result.Reason.Should().BeNull();
    }

    [Fact]
    public void ValidateJson_RejectsOlderSchemaWithMigrationAction()
    {
        var result = Validate(CurrentManifest(schemaVersion: 1));

        result.IsCompatible.Should().BeFalse();
        result.Reason.Should().Contain("reinstall");
        result.Reason.Should().Contain("schema");
    }

    [Fact]
    public void ValidateJson_RejectsHostOutsideDeclaredRange()
    {
        var result = Validate(CurrentManifest(minHostVersion: "3.0.0"), hostVersion: "2.34.0");

        result.IsCompatible.Should().BeFalse();
        result.Reason.Should().Contain("requires host 3.0.0");
    }

    [Fact]
    public void ValidateJson_RejectsUnsupportedArchitectureBeforeExecution()
    {
        var result = Validate(CurrentManifest(architectures: ["win-arm64"]), architecture: "win-x64");

        result.IsCompatible.Should().BeFalse();
        result.Reason.Should().Contain("win-arm64");
        result.Reason.Should().Contain("win-x64");
    }

    private static ExtensionCompatibilityResult Validate(
        string json,
        string hostVersion = "2.34.0",
        string architecture = "win-x64")
    {
        using var document = JsonDocument.Parse(json);
        return ExtensionManifestCompatibility.ValidateJson(
            document.RootElement,
            expectedEngine: "sample",
            extensionKind: "plugin",
            expectedHostVersion: hostVersion,
            expectedArchitecture: architecture);
    }

    private static string CurrentManifest(
        int schemaVersion = 2,
        string minHostVersion = "2.34.0",
        string[]? architectures = null) =>
        $$"""
        {
          "schemaVersion": {{schemaVersion}},
          "engine": "sample",
          "engineVersion": "1.0.0",
          "minHostVersion": "{{minHostVersion}}",
          "maxHostVersion": null,
          "capabilities": ["conversion"],
          "architectures": {{JsonSerializer.Serialize(architectures ?? ["win-x64"])}},
          "migration": {
            "strategy": "reinstall",
            "fromSchemaVersions": [1],
            "notes": "Reinstall on a schema change."
          }
        }
        """;
}
