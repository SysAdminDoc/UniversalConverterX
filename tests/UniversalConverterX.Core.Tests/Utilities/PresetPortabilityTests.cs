using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public class PresetPortabilityTests : IDisposable
{
    private readonly string _tempDir;

    public PresetPortabilityTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "ucx-preset-tests-" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        try { Directory.Delete(_tempDir, recursive: true); } catch { }
        GC.SuppressFinalize(this);
    }

    private string WritePreset(string fileName, string xml)
    {
        var path = Path.Combine(_tempDir, fileName);
        File.WriteAllText(path, xml);
        return path;
    }

    private const string ValidPreset = """
        <?xml version="1.0" encoding="utf-8"?>
        <Preset xmlns="https://universalconverterx.io/preset/v1">
            <Name>Test Preset</Name>
            <Folder>Video/Test</Folder>
            <InputTypes>
                <Extension>mp4</Extension>
            </InputTypes>
            <OutputFileNameTemplate>{dir}/{stem}_test</OutputFileNameTemplate>
            <OutputExtension>mkv</OutputExtension>
            <Engine>videocrush</Engine>
            <InvocationMode>per-file</InvocationMode>
            <Args><Arg>encode</Arg></Args>
        </Preset>
        """;

    #region Validate

    [Fact]
    public void Validate_ValidPreset_ReturnsIsValid()
    {
        var path = WritePreset("valid.preset.xml", ValidPreset);

        var result = PresetPortability.Validate(path);

        result.IsValid.Should().BeTrue();
        result.PresetName.Should().Be("Test Preset");
        result.Engine.Should().Be("videocrush");
        result.Errors.Should().BeEmpty();
    }

    [Fact]
    public void Validate_MissingFile_ReturnsInvalid()
    {
        var result = PresetPortability.Validate(Path.Combine(_tempDir, "nope.xml"));

        result.IsValid.Should().BeFalse();
        result.Errors.Should().ContainSingle().Which.Should().Contain("not found");
    }

    [Fact]
    public void Validate_MissingName_ReturnsInvalid()
    {
        var xml = ValidPreset.Replace("<Name>Test Preset</Name>", "<Name></Name>");
        var path = WritePreset("no-name.preset.xml", xml);

        var result = PresetPortability.Validate(path);

        result.IsValid.Should().BeFalse();
        result.Errors.Should().Contain(e => e.Contains("Name"));
    }

    [Fact]
    public void Validate_UnsafeEngine_ReturnsInvalid()
    {
        var xml = ValidPreset.Replace("videocrush", "../../../evil");
        var path = WritePreset("bad-engine.preset.xml", xml);

        var result = PresetPortability.Validate(path);

        result.IsValid.Should().BeFalse();
        result.Errors.Should().Contain(e => e.Contains("Unsafe engine"));
    }

    [Fact]
    public void Validate_PathTraversalTemplate_ReturnsInvalid()
    {
        var xml = ValidPreset.Replace("{dir}/{stem}_test", "../../{stem}_evil");
        var path = WritePreset("traversal.preset.xml", xml);

        var result = PresetPortability.Validate(path);

        result.IsValid.Should().BeFalse();
        result.Errors.Should().Contain(e => e.Contains("path traversal"));
    }

    [Fact]
    public void Validate_MalformedXml_ReturnsInvalid()
    {
        var path = WritePreset("bad.preset.xml", "<not valid xml");

        var result = PresetPortability.Validate(path);

        result.IsValid.Should().BeFalse();
        result.Errors.Should().Contain(e => e.Contains("Invalid XML"));
    }

    #endregion

    #region Import

    [Fact]
    public void Import_ValidPreset_CopiesAndReturnsSuccess()
    {
        var source = WritePreset("my.preset.xml", ValidPreset);
        var importDir = Path.Combine(_tempDir, "imported");

        var result = PresetPortability.Import(source, importDir);

        result.Success.Should().BeTrue();
        result.PresetName.Should().Be("Test Preset");
        result.DestinationPath.Should().NotBeNull();
        File.Exists(result.DestinationPath!).Should().BeTrue();
    }

    [Fact]
    public void Import_InvalidPreset_FailsWithoutCopying()
    {
        var xml = ValidPreset.Replace("videocrush", "../../evil");
        var source = WritePreset("evil.preset.xml", xml);
        var importDir = Path.Combine(_tempDir, "imported");

        var result = PresetPortability.Import(source, importDir);

        result.Success.Should().BeFalse();
        result.ErrorMessage.Should().Contain("Validation failed");
        Directory.Exists(importDir).Should().BeFalse();
    }

    [Fact]
    public void Import_CollisionHandled_RenamesAutomatically()
    {
        var source = WritePreset("test.preset.xml", ValidPreset);
        var importDir = Path.Combine(_tempDir, "imported");
        Directory.CreateDirectory(importDir);
        File.WriteAllText(Path.Combine(importDir, "test.preset.xml"), "existing");

        var result = PresetPortability.Import(source, importDir);

        result.Success.Should().BeTrue();
        result.DestinationPath.Should().NotBe(Path.Combine(importDir, "test.preset.xml"));
        File.Exists(result.DestinationPath!).Should().BeTrue();
    }

    #endregion

    #region Export

    [Fact]
    public void Export_ValidPreset_CopiesToDestination()
    {
        var source = WritePreset("source.preset.xml", ValidPreset);
        var exportPath = Path.Combine(_tempDir, "exported", "shared.preset.xml");

        var result = PresetPortability.Export(source, exportPath);

        result.Success.Should().BeTrue();
        result.ExportedPath.Should().Be(exportPath);
        File.Exists(exportPath).Should().BeTrue();
    }

    [Fact]
    public void Export_MissingSource_Fails()
    {
        var result = PresetPortability.Export(
            Path.Combine(_tempDir, "nope.xml"),
            Path.Combine(_tempDir, "out.xml"));

        result.Success.Should().BeFalse();
        result.ErrorMessage.Should().Contain("not found");
    }

    #endregion
}
