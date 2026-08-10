using FluentAssertions;
using System.Runtime.Versioning;
using UniversalConverterX.Core.Utilities;
using UniversalConverterX.ShellExtension.Presets;

namespace UniversalConverterX.Core.Tests.Presets;

[SupportedOSPlatform("windows")]
public sealed class PresetReaderCacheTests : IDisposable
{
    private readonly string _directory = Path.Combine(
        Path.GetTempPath(),
        "ucx-preset-reader-cache-tests",
        Guid.NewGuid().ToString("N"));

    public PresetReaderCacheTests() => Directory.CreateDirectory(_directory);

    [Fact]
    public void LoadAll_ReusesSnapshotUntilDirectoryChanges()
    {
        WritePreset("first", "First");

        var first = PresetReader.LoadAll([_directory]);
        var second = PresetReader.LoadAll([_directory]);

        ReferenceEquals(first, second).Should().BeTrue();

        WritePreset("second", "Second");
        Directory.SetLastWriteTimeUtc(_directory, DateTime.UtcNow.AddSeconds(2));

        var refreshed = PresetReader.LoadAll([_directory]);

        ReferenceEquals(second, refreshed).Should().BeFalse();
        refreshed.Select(p => p.Name).Should().Contain("First").And.Contain("Second");
    }

    [Fact]
    public void LoadAll_HardCapsUncachedFileCount()
    {
        for (var index = 0; index < PresetReader.MaxPresetFiles + 8; index++)
            WritePreset($"preset-{index:0000}", $"Preset {index:0000}");

        var presets = PresetReader.LoadAll([_directory]);

        presets.Count.Should().BeLessOrEqualTo(PresetReader.MaxPresetFiles);
    }

    private void WritePreset(string fileStem, string name)
    {
        var xml = $$"""
            <Preset xmlns="{{PresetDocument.NamespaceUri}}">
              <Name>{{name}}</Name>
              <OutputFileNameTemplate>{dir}/{stem}</OutputFileNameTemplate>
              <OutputExtension>pdf</OutputExtension>
              <Engine>ghostscript</Engine>
              <InvocationMode>batch-output-dir</InvocationMode>
            </Preset>
            """;
        File.WriteAllText(Path.Combine(_directory, fileStem + ".preset.xml"), xml);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_directory))
                Directory.Delete(_directory, recursive: true);
        }
        catch { }
    }
}
