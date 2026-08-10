using FluentAssertions;
using UniversalConverterX.Core.Security;

namespace UniversalConverterX.Core.Tests.Security;

public sealed class PluginTrustServiceTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "ucx-plugin-trust-" + Guid.NewGuid().ToString("N"));
    private readonly string _plugins;
    private readonly string _trustStore;

    public PluginTrustServiceTests()
    {
        _plugins = Path.Combine(_root, "plugins");
        _trustStore = Path.Combine(_root, "plugin-trust.json");
        Directory.CreateDirectory(_plugins);
    }

    [Fact]
    public void Discover_DroppedPlugin_IsQuarantinedByDefault()
    {
        CreatePlugin("sample");
        var service = CreateService();

        var plugin = service.Discover().Should().ContainSingle().Subject;

        plugin.TrustState.Should().Be(PluginTrustState.Untrusted);
        plugin.CanTrust.Should().BeTrue();
        service.TryGetTrustedPlugin("sample", out _).Should().BeFalse();
    }

    [Fact]
    public void Trust_ThenFileChange_RequarantinesPlugin()
    {
        var directory = CreatePlugin("sample");
        File.WriteAllText(Path.Combine(directory, "dependency.dll"), "v1");
        var service = CreateService();

        service.Trust("sample").Success.Should().BeTrue();
        service.TryGetTrustedPlugin("sample", out var trusted).Should().BeTrue();
        trusted!.ExecutablePath.Should().Be(Path.Combine(directory, "sample.exe"));

        File.WriteAllText(Path.Combine(directory, "dependency.dll"), "v2");

        var changed = service.Discover().Should().ContainSingle().Subject;
        changed.TrustState.Should().Be(PluginTrustState.Changed);
        changed.StatusDetail.Should().Contain("re-quarantined");
        service.TryGetTrustedPlugin("sample", out _).Should().BeFalse();
    }

    [Fact]
    public void Revoke_RemovesExecutionTrust()
    {
        CreatePlugin("sample");
        var service = CreateService();
        service.Trust("sample").Success.Should().BeTrue();

        service.Revoke("sample").Success.Should().BeTrue();

        service.TryGetTrustedPlugin("sample", out _).Should().BeFalse();
        service.Discover().Single().TrustState.Should().Be(PluginTrustState.Untrusted);
    }

    [Fact]
    public void Discover_TraversalPreset_IsInvalid()
    {
        CreatePlugin("sample", presetPath: "../outside.preset.xml");

        var plugin = CreateService().Discover().Should().ContainSingle().Subject;

        plugin.TrustState.Should().Be(PluginTrustState.Invalid);
        plugin.StatusDetail.Should().Contain("inside the plugin directory");
    }

    [Fact]
    public void Discover_OldManifestSchema_IsQuarantinedWithMigrationAction()
    {
        var plugin = CreatePlugin("old", schemaVersion: 1);

        var descriptor = CreateService().Discover().Should().ContainSingle().Subject;

        descriptor.TrustState.Should().Be(PluginTrustState.Invalid);
        descriptor.StatusDetail.Should().Contain("reinstall");
        Directory.Exists(plugin).Should().BeTrue();
    }

    [Fact]
    public void Discover_SymlinkExecutable_IsInvalidWhenSymlinksAreAvailable()
    {
        var directory = CreatePlugin("sample");
        var executable = Path.Combine(directory, "sample.exe");
        File.Delete(executable);
        var target = Path.Combine(_root, "outside.exe");
        File.WriteAllText(target, "outside");
        try
        {
            File.CreateSymbolicLink(executable, target);
        }
        catch (Exception exception) when (exception is UnauthorizedAccessException or IOException or PlatformNotSupportedException)
        {
            return;
        }

        var plugin = CreateService().Discover().Should().ContainSingle().Subject;

        plugin.TrustState.Should().Be(PluginTrustState.Invalid);
        plugin.StatusDetail.Should().Contain("links or reparse points");
    }

    private PluginTrustService CreateService() => new(_plugins, _trustStore);

    private string CreatePlugin(
        string id,
        string presetPath = "presets/sample.preset.xml",
        int schemaVersion = 2)
    {
        var directory = Path.Combine(_plugins, id);
        Directory.CreateDirectory(directory);
        File.WriteAllText(Path.Combine(directory, id + ".exe"), "not-an-executable-but-hashable");
        if (!presetPath.StartsWith("..", StringComparison.Ordinal))
        {
            var preset = Path.Combine(directory, presetPath);
            Directory.CreateDirectory(Path.GetDirectoryName(preset)!);
            File.WriteAllText(
                preset,
                $$"""
                <Preset xmlns="https://universalconverterx.io/preset/v1">
                  <Name>Sample conversion</Name>
                  <OutputFileNameTemplate>{dir}/{stem}_converted</OutputFileNameTemplate>
                  <OutputExtension>out</OutputExtension>
                  <Engine>{{id}}</Engine>
                  <InvocationMode>per-file</InvocationMode>
                  <Args><Arg>convert</Arg></Args>
                </Preset>
                """);
        }
        File.WriteAllText(
            Path.Combine(directory, "manifest.json"),
            $$"""
            {
              "schemaVersion": {{schemaVersion}},
              "engineVersion": "1.0.0",
              "minHostVersion": "2.34.0",
              "maxHostVersion": null,
              "capabilities": ["ndjson"],
              "architectures": ["win-x64"],
              "migration": {
                "strategy": "reinstall",
                "fromSchemaVersions": [1],
                "notes": "Reinstall when the manifest schema changes."
              },
              "id": "{{id}}",
              "name": "Sample plugin",
              "version": "1.0.0",
              "description": "Test plugin",
              "engine": "{{id}}",
              "executable": "{{id}}.exe",
              "presets": ["{{presetPath.Replace("\\", "/")}}"]
            }
            """);
        return directory;
    }

    public void Dispose()
    {
        if (Directory.Exists(_root))
            Directory.Delete(_root, true);
    }
}
