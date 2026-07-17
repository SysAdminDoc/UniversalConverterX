using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class SidecarCatalogTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "ucx-catalog-" + Guid.NewGuid().ToString("N"));

    [Fact]
    public void Discover_ReportsSourceOnlyAndInstalledEnginesFromOneSharedRoot()
    {
        var sourceOnly = Path.Combine(_root, "tools", "source-only");
        var installed = Path.Combine(_root, "tools", "installed", "dist");
        Directory.CreateDirectory(sourceOnly);
        Directory.CreateDirectory(installed);
        File.WriteAllText(Path.Combine(sourceOnly, "sidecar.py"), "print('ok')");
        File.WriteAllText(Path.Combine(installed, SidecarNaming.ExecutableName("installed")), "fixture");
        File.WriteAllText(Path.Combine(_root, "tools", "installed", "ucx.sidecar.json"), "{}");

        var entries = SidecarCatalog.Discover(_root, Path.Combine(_root, "local"));

        entries.Should().ContainSingle(entry => entry.Name == "source-only")
            .Which.Available.Should().BeFalse();
        var built = entries.Should().ContainSingle(entry => entry.Name == "installed").Subject;
        built.Available.Should().BeTrue();
        built.ManifestPath.Should().NotBeNull();
        SidecarCatalog.Resolve("installed", _root, Path.Combine(_root, "local"))
            .Should().Be(built.ExecutablePath);
    }

    [Theory]
    [InlineData("")]
    [InlineData("..")]
    [InlineData("../escape")]
    [InlineData("folder\\escape")]
    [InlineData("C:drive")]
    public void Resolve_RejectsUnsafeNames(string name)
    {
        SidecarCatalog.Resolve(name, _root, Path.Combine(_root, "local")).Should().BeNull();
    }

    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, recursive: true);
    }
}
