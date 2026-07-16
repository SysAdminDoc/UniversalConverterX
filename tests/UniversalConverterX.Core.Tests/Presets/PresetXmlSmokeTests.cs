using System.Xml.Linq;
using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Presets;

public class PresetXmlSmokeTests
{
    private const string Ns = "https://universalconverterx.io/preset/v1";
    private static readonly string PresetsDir = FindPresetsDir();

    private static string FindPresetsDir()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            if (File.Exists(Path.Combine(dir.FullName, "Directory.Build.props")) &&
                Directory.Exists(Path.Combine(dir.FullName, "presets")))
                return Path.Combine(dir.FullName, "presets");
            dir = dir.Parent;
        }
        throw new DirectoryNotFoundException("Could not find presets/ directory from " + AppContext.BaseDirectory);
    }

    public static IEnumerable<object[]> PresetFiles()
    {
        foreach (var file in Directory.EnumerateFiles(PresetsDir, "*.preset.xml"))
            yield return [file];
    }

    [Theory]
    [MemberData(nameof(PresetFiles))]
    public void Preset_ShouldPassEditableSchema(string path)
    {
        var result = PresetDocument.Load(path);

        result.Succeeded.Should().BeTrue(
            $"{Path.GetFileName(path)} must be editable: {string.Join("; ", result.Errors)}");
    }

    [Theory]
    [MemberData(nameof(PresetFiles))]
    public void Preset_ShouldHaveRequiredElements(string path)
    {
        var doc = XDocument.Load(path);
        var root = doc.Root!;

        var name = root.Element(XName.Get("Name", Ns))?.Value
                   ?? root.Element("Name")?.Value;
        name.Should().NotBeNullOrWhiteSpace($"{Path.GetFileName(path)} must have a <Name>");

        var engine = root.Element(XName.Get("Engine", Ns))?.Value
                     ?? root.Element("Engine")?.Value;
        engine.Should().NotBeNullOrWhiteSpace($"{Path.GetFileName(path)} must have an <Engine>");

        // OutputExtension may be empty for multi-file/directory-output presets (e.g. stems, extract)
    }

    [Theory]
    [MemberData(nameof(PresetFiles))]
    public void Preset_InputTypesShouldBeLowercaseNoDot(string path)
    {
        var doc = XDocument.Load(path);
        var root = doc.Root!;
        var inputTypes = root.Element(XName.Get("InputTypes", Ns))
                         ?? root.Element("InputTypes");
        if (inputTypes is null) return;

        foreach (var ext in inputTypes.Elements())
        {
            var val = ext.Value.Trim();
            val.Should().NotStartWith(".", $"InputType in {Path.GetFileName(path)} should not start with dot");
            val.Should().Be(val.ToLowerInvariant(), $"InputType in {Path.GetFileName(path)} should be lowercase");
        }
    }

    [Theory]
    [MemberData(nameof(PresetFiles))]
    public void Preset_ArgsShouldNotContainShellInjection(string path)
    {
        var doc = XDocument.Load(path);
        var root = doc.Root!;
        var args = root.Element(XName.Get("Args", Ns))
                   ?? root.Element("Args");
        if (args is null) return;

        var dangerous = new[] { "|", ";", "&", ">", "<", "`", "$(" };
        foreach (var arg in args.Elements())
        {
            var val = arg.Value;
            foreach (var d in dangerous)
                val.Should().NotContain(d,
                    $"Arg '{val}' in {Path.GetFileName(path)} contains shell metacharacter '{d}'");
        }
    }

    [Fact]
    public void PresetDirectory_ShouldHaveAtLeastOnePreset()
    {
        Directory.GetFiles(PresetsDir, "*.preset.xml")
            .Should().NotBeEmpty("the presets/ directory should contain preset XML files");
    }

    [Fact]
    public void PreservationAndProductionFamilies_ShouldExposeCuratedPresets()
    {
        var expected = new Dictionary<string, (string Folder, string Output, string SidecarPreset)>
        {
            ["archive-ffv1.preset.xml"] = ("Video/Preservation", "mkv", "archive-ffv1"),
            ["production-prores-422.preset.xml"] = ("Video/Production", "mov", "prores-422"),
            ["production-dnxhr.preset.xml"] = ("Video/Production", "mov", "dnxhr-hq"),
        };

        foreach (var (fileName, contract) in expected)
        {
            var path = Path.Combine(PresetsDir, fileName);
            File.Exists(path).Should().BeTrue($"{fileName} is part of the curated family");
            var preset = PresetDocument.Load(path);
            preset.Succeeded.Should().BeTrue();
            preset.Preset!.Folder.Should().Be(contract.Folder);
            preset.Preset.OutputExtension.Should().Be(contract.Output);
            preset.Preset.Engine.Should().Be("videocrush");
            preset.Preset.Args.Should().ContainInOrder("--preset", contract.SidecarPreset);
        }
    }
}
