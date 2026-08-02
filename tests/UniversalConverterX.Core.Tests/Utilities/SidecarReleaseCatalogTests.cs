using System.Text.Json;
using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class SidecarReleaseCatalogTests : IDisposable
{
    private readonly string _root = Path.Combine(
        Path.GetTempPath(),
        "ucx-release-catalog-" + Guid.NewGuid().ToString("N"));

    [Fact]
    public void FindAndLoad_UsesParentReleaseRootAndPreservesUnavailableReason()
    {
        var nested = Path.Combine(_root, "ui");
        Directory.CreateDirectory(nested);
        WriteManifest(
            new
            {
                schemaVersion = 1,
                architecture = "win-x64",
                engines = new[]
                {
                    new
                    {
                        id = "demo",
                        status = "unavailable",
                        reason = "No authenticated artifact.",
                        entrypoint = (string?)null,
                    },
                },
            });

        var result = SidecarReleaseCatalogLoader.FindAndLoad(nested, "win-x64");

        result.IsValid.Should().BeTrue();
        result.Catalog!.Engines["demo"].Status
            .Should().Be(SidecarReleaseStatus.Unavailable);
        result.Catalog.Engines["demo"].Reason
            .Should().Be("No authenticated artifact.");
    }

    [Fact]
    public void Load_RejectsBundledEntryWhoseFileIsMissing()
    {
        Directory.CreateDirectory(_root);
        var manifest = WriteManifest(
            new
            {
                schemaVersion = 1,
                architecture = "win-x64",
                engines = new[]
                {
                    new
                    {
                        id = "demo",
                        status = "bundled",
                        reason = "Bundled.",
                        entrypoint = "tools/demo/demo.exe",
                    },
                },
            });

        var result = SidecarReleaseCatalogLoader.Load(manifest, "win-x64");

        result.Found.Should().BeTrue();
        result.IsValid.Should().BeFalse();
        result.Error.Should().Contain("entrypoint is missing");
    }

    [Fact]
    public void Load_RejectsManifestForAnotherArchitecture()
    {
        Directory.CreateDirectory(_root);
        var manifest = WriteManifest(
            new
            {
                schemaVersion = 1,
                architecture = "win-arm64",
                engines = new[]
                {
                    new
                    {
                        id = "demo",
                        status = "unavailable",
                        reason = "Unavailable.",
                        entrypoint = (string?)null,
                    },
                },
            });

        SidecarReleaseCatalogLoader.Load(manifest, "win-x64")
            .Error.Should().Contain("win-arm64");
    }

    private string WriteManifest(object value)
    {
        Directory.CreateDirectory(_root);
        var path = Path.Combine(_root, SidecarReleaseCatalogLoader.FileName);
        File.WriteAllText(path, JsonSerializer.Serialize(value));
        return path;
    }

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }
}
