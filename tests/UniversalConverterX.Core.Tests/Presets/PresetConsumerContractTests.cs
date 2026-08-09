using FluentAssertions;
using System.Runtime.Versioning;
using UniversalConverterX.Core.Utilities;
using ConsolePresetLoader = UniversalConverterX.Console.Presets.PresetLoader;
using ShellPresetReader = UniversalConverterX.ShellExtension.Presets.PresetReader;

namespace UniversalConverterX.Core.Tests.Presets;

[SupportedOSPlatform("windows")]
public sealed class PresetConsumerContractTests : IDisposable
{
    private const string Namespace = PresetDocument.NamespaceUri;
    private readonly string _directory = Path.Combine(
        Path.GetTempPath(),
        "ucx-preset-consumer-contract-tests",
        Guid.NewGuid().ToString("N"));

    public PresetConsumerContractTests() => Directory.CreateDirectory(_directory);

    public static IEnumerable<object[]> SharedFixtures() =>
    [
        ["valid", $$"""
            <Preset xmlns="{{Namespace}}">
              <Name>Shared fixture</Name>
              <Folder>Video/Fixtures</Folder>
              <InputTypes><Extension>.MP4</Extension><Extension>mkv</Extension></InputTypes>
              <OutputFileNameTemplate>{dir}/{stem}_fixture</OutputFileNameTemplate>
              <OutputExtension>.MKV</OutputExtension>
              <Engine>videocrush</Engine>
              <InvocationMode>batch-output-dir</InvocationMode>
              <Args><Arg>--preset</Arg><Arg>web-1080p</Arg></Args>
            </Preset>
            """, true],
        ["future-schema", """
            <Preset xmlns="https://universalconverterx.io/preset/v7">
              <Name>Future schema</Name>
              <OutputFileNameTemplate>{dir}/{stem}</OutputFileNameTemplate>
              <Engine>future-engine</Engine>
            </Preset>
            """, false],
        ["xxe", """
            <?xml version="1.0"?>
            <!DOCTYPE Preset [<!ENTITY xxe SYSTEM "file:///windows/win.ini">]>
            <Preset><Name>&xxe;</Name></Preset>
            """, false],
        ["traversal", $$"""
            <Preset xmlns="{{Namespace}}">
              <Name>Traversal</Name>
              <OutputFileNameTemplate>../escape/{stem}</OutputFileNameTemplate>
              <OutputExtension>mp4</OutputExtension>
              <Engine>videocrush</Engine>
            </Preset>
            """, false],
        ["invocation-mode", $$"""
            <Preset xmlns="{{Namespace}}">
              <Name>Unknown mode</Name>
              <OutputFileNameTemplate>{dir}/{stem}</OutputFileNameTemplate>
              <OutputExtension>mp4</OutputExtension>
              <Engine>videocrush</Engine>
              <InvocationMode>future-mode</InvocationMode>
            </Preset>
            """, false],
        ["rooted-output", $$"""
            <Preset xmlns="{{Namespace}}">
              <Name>Rooted output</Name>
              <OutputFileNameTemplate>C:\\escape\\{stem}</OutputFileNameTemplate>
              <OutputExtension>mp4</OutputExtension>
              <Engine>videocrush</Engine>
            </Preset>
            """, false],
    ];

    [Theory]
    [MemberData(nameof(SharedFixtures))]
    public void ConsoleAndShell_UseTheSameCoreAcceptanceAndDiagnostics(
        string fixtureName,
        string xml,
        bool expectedValid)
    {
        var path = Path.Combine(_directory, fixtureName + ".preset.xml");
        File.WriteAllText(path, xml);

        var canonical = PresetDocument.Load(path);
        var console = ConsolePresetLoader.TryLoad(path, out var consoleErrors);
        var shell = ShellPresetReader.TryLoad(path, out var shellErrors);

        canonical.Succeeded.Should().Be(expectedValid, fixtureName);
        consoleErrors.Should().Equal(canonical.Errors, fixtureName);
        shellErrors.Should().Equal(canonical.Errors, fixtureName);
        (console is not null).Should().Be(expectedValid, fixtureName);
        (shell is not null).Should().Be(expectedValid, fixtureName);

        if (!expectedValid)
            return;

        console!.Name.Should().Be(canonical.Preset!.Name);
        console.Folder.Should().Be(canonical.Preset.Folder);
        console.InputTypes.Should().Equal(canonical.Preset.InputTypes);
        console.OutputFileNameTemplate.Should().Be(canonical.Preset.OutputFileNameTemplate);
        console.OutputExtension.Should().Be(canonical.Preset.OutputExtension);
        console.Engine.Should().Be(canonical.Preset.Engine);
        console.Mode.Should().Be(PresetInvocationMode.BatchOutputDir);
        console.Args.Should().Equal(canonical.Preset.Args);

        shell!.Name.Should().Be(canonical.Preset.Name);
        shell.Folder.Should().Be(canonical.Preset.Folder);
        shell.InputTypes.Should().Equal(canonical.Preset.InputTypes);
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
