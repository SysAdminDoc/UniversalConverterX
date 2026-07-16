using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class PresetDocumentTests : IDisposable
{
    private readonly string _tempDirectory = Path.Combine(
        Path.GetTempPath(),
        "ucx-preset-document-tests-" + Guid.NewGuid().ToString("N"));

    public PresetDocumentTests() => Directory.CreateDirectory(_tempDirectory);

    [Fact]
    public void SaveAndLoad_RoundTripsEveryEditableField()
    {
        var source = new PresetDefinition(
            "My & Custom Preset",
            "Video/Custom",
            [".MP4", "mkv", "mp4"],
            "{dir}/{stem}_custom",
            ".MKV",
            "videocrush",
            "batch-output-dir",
            ["encode", "--filter", "scale=1280:720&format=yuv420p"],
            RequiresExtraInput: true,
            ExtraInputPrompt: "Choose a logo <image>.");
        var path = Path.Combine(_tempDirectory, "roundtrip.preset.xml");

        var saved = PresetDocument.Save(source, path);
        var loaded = PresetDocument.Load(path);

        saved.Succeeded.Should().BeTrue(string.Join("; ", saved.Errors));
        loaded.Succeeded.Should().BeTrue(string.Join("; ", loaded.Errors));
        loaded.Preset.Should().NotBeNull();
        loaded.Preset!.Name.Should().Be(source.Name);
        loaded.Preset.Folder.Should().Be(source.Folder);
        loaded.Preset.InputTypes.Should().Equal("mp4", "mkv");
        loaded.Preset.OutputFileNameTemplate.Should().Be(source.OutputFileNameTemplate);
        loaded.Preset.OutputExtension.Should().Be("mkv");
        loaded.Preset.Engine.Should().Be(source.Engine);
        loaded.Preset.InvocationMode.Should().Be(source.InvocationMode);
        loaded.Preset.Args.Should().Equal(source.Args);
        loaded.Preset.RequiresExtraInput.Should().BeTrue();
        loaded.Preset.ExtraInputPrompt.Should().Be(source.ExtraInputPrompt);
    }

    [Fact]
    public void DuplicateShippedPreset_ModifiedArgumentsSurviveReload()
    {
        var sourcePath = Path.Combine(FindRepositoryRoot(), "presets", "aiff-to-flac.preset.xml");
        var loadedSource = PresetDocument.Load(sourcePath);
        loadedSource.Succeeded.Should().BeTrue(string.Join("; ", loadedSource.Errors));
        var duplicate = loadedSource.Preset! with
        {
            Name = loadedSource.Preset!.Name + " (Custom test)",
            Args = [.. loadedSource.Preset.Args, "--custom-test-argument"],
        };
        var duplicatePath = Path.Combine(_tempDirectory, "duplicate.preset.xml");

        var saved = PresetDocument.Save(duplicate, duplicatePath);
        var reloaded = PresetDocument.Load(duplicatePath);

        saved.Succeeded.Should().BeTrue(string.Join("; ", saved.Errors));
        reloaded.Succeeded.Should().BeTrue(string.Join("; ", reloaded.Errors));
        reloaded.Preset!.Name.Should().Be(duplicate.Name);
        reloaded.Preset.Args.Should().EndWith("--custom-test-argument");
    }

    [Fact]
    public void Save_InvalidDefinition_DoesNotCreateFile()
    {
        var path = Path.Combine(_tempDirectory, "invalid.preset.xml");
        var invalid = ValidPreset() with
        {
            Engine = "..\\unsafe.exe",
            OutputFileNameTemplate = "../../escape",
        };

        var result = PresetDocument.Save(invalid, path);

        result.Succeeded.Should().BeFalse();
        result.Errors.Should().Contain(error => error.Contains("Unsafe engine"));
        result.Errors.Should().Contain(error => error.Contains("path traversal"));
        File.Exists(path).Should().BeFalse();
    }

    [Fact]
    public void Save_WithoutOverwrite_PreservesExistingFile()
    {
        var path = Path.Combine(_tempDirectory, "existing.preset.xml");
        File.WriteAllText(path, "existing-value");

        var result = PresetDocument.Save(ValidPreset(), path);

        result.Succeeded.Should().BeFalse();
        File.ReadAllText(path).Should().Be("existing-value");
        Directory.GetFiles(_tempDirectory, "*.tmp").Should().BeEmpty();
    }

    [Fact]
    public void Save_WithOverwrite_ReplacesDocumentAndRemainsReadable()
    {
        var path = Path.Combine(_tempDirectory, "existing.preset.xml");
        File.WriteAllText(path, "existing-value");

        var result = PresetDocument.Save(ValidPreset(), path, overwrite: true);
        var loaded = PresetDocument.Load(path);

        result.Succeeded.Should().BeTrue(string.Join("; ", result.Errors));
        loaded.Succeeded.Should().BeTrue(string.Join("; ", loaded.Errors));
        loaded.Preset!.Name.Should().Be("Custom Encode");
        Directory.GetFiles(_tempDirectory, "*.tmp").Should().BeEmpty();
    }

    [Fact]
    public void Load_RejectsExternalEntities()
    {
        var path = Path.Combine(_tempDirectory, "xxe.preset.xml");
        File.WriteAllText(
            path,
            """
            <?xml version="1.0"?>
            <!DOCTYPE Preset [<!ENTITY xxe SYSTEM "file:///windows/win.ini">]>
            <Preset><Name>&xxe;</Name></Preset>
            """);

        var result = PresetDocument.Load(path);

        result.Succeeded.Should().BeFalse();
        result.Errors.Should().Contain(error => error.Contains("Invalid XML"));
    }

    [Fact]
    public void InspectMetadata_ReadsFutureSchemaWithoutLoadingPreset()
    {
        var path = Path.Combine(_tempDirectory, "future.preset.xml");
        File.WriteAllText(
            path,
            """
            <Preset xmlns="https://universalconverterx.io/preset/v7">
              <Name>Future preset</Name>
              <Engine>future-engine</Engine>
            </Preset>
            """);

        var metadata = PresetDocument.InspectMetadata(path);
        var loaded = PresetDocument.Load(path);

        metadata.Should().Be(new PresetDocumentMetadata(true, 7, "future-engine"));
        loaded.Succeeded.Should().BeFalse();
    }

    [Theory]
    [InlineData("custom/path")]
    [InlineData("unknown-mode")]
    public void Validate_RejectsUnsafeEngineOrUnknownMode(string value)
    {
        var preset = value.Contains('/')
            ? ValidPreset() with { Engine = value }
            : ValidPreset() with { InvocationMode = value };

        PresetDocument.Validate(preset).Should().NotBeEmpty();
    }

    public void Dispose()
    {
        try { Directory.Delete(_tempDirectory, recursive: true); } catch { }
        GC.SuppressFinalize(this);
    }

    private static PresetDefinition ValidPreset() => new(
        "Custom Encode",
        "Video/Custom",
        ["mp4", "mkv"],
        "{dir}/{stem}_custom",
        "mkv",
        "videocrush",
        "per-file",
        ["encode"]);

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "Directory.Build.props")) &&
                Directory.Exists(Path.Combine(directory.FullName, "presets")))
            {
                return directory.FullName;
            }
            directory = directory.Parent;
        }
        throw new DirectoryNotFoundException("Could not find repository root.");
    }
}
