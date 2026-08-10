using FluentAssertions;
using UniversalConverterX.Console.Commands;
using UniversalConverterX.Console.Configuration;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Commands;

public sealed class CliConfigurationTests
{
    [Fact]
    public void TryNormalizeToolsPath_ExpandsDefinedPercentEnvironmentVariables()
    {
        var temp = Environment.GetEnvironmentVariable("TEMP") ?? Environment.GetEnvironmentVariable("TMP");
        temp.Should().NotBeNullOrWhiteSpace();

        CliConfiguration.TryNormalizeToolsPath(
                @"%TEMP%\ucx-cli-tools",
                out var normalized,
                out var error)
            .Should().BeTrue(error);

        normalized.Should().Be(Path.GetFullPath(Path.Combine(temp!, "ucx-cli-tools")));
    }

    [Theory]
    [InlineData(@"%UCX_MISSING_TOOLS_PATH_9F31%\tools")]
    [InlineData(@"$env:TEMP\tools")]
    [InlineData(@"$Env:TEMP\tools")]
    [InlineData(@"relative%tools")]
    public void TryNormalizeToolsPath_RejectsUnresolvedEnvironmentSyntax(string rawPath)
    {
        CliConfiguration.TryNormalizeToolsPath(rawPath, out _, out var error)
            .Should().BeFalse();

        error.Should().Contain("unresolved environment-variable");
    }

    [Fact]
    public void ApplyConfigurationDefaults_UsesPersistedValuesWhenFlagsAreAbsent()
    {
        var settings = new ConvertCommand.Settings();
        var options = new ConverterXOptions
        {
            DefaultQuality = QualityPreset.Low,
            MaxParallelConversions = 7,
            PreserveMetadataByDefault = false,
            EnableHardwareAcceleration = false,
            ToolsBasePath = @"C:\configured-tools",
            DefaultOutputDirectory = @"C:\configured-output",
            PostConversionAction = PostConversionAction.Move,
            PostConversionArchiveFolder = @"C:\configured-archive"
        };

        ConvertCommand.ApplyConfigurationDefaults(settings, options);

        settings.Quality.Should().Be("Low");
        settings.Parallel.Should().Be(7);
        settings.KeepMetadata.Should().BeFalse();
        settings.HardwareAccel.Should().BeFalse();
        settings.ToolsPath.Should().Be(options.ToolsBasePath);
        settings.OutputDirectory.Should().Be(options.DefaultOutputDirectory);
        settings.SourceAction.Should().Be("Move");
        settings.SourceArchive.Should().Be(options.PostConversionArchiveFolder);
    }

    [Fact]
    public void ApplyConfigurationDefaults_DoesNotReplaceExplicitFlags()
    {
        var settings = new ConvertCommand.Settings
        {
            Quality = "lossless",
            Parallel = 2,
            KeepMetadata = true,
            HardwareAccel = true,
            ToolsPath = @"C:\explicit-tools",
            OutputDirectory = @"C:\explicit-output",
            SourceAction = "keep",
            SourceArchive = @"C:\explicit-archive"
        };
        var options = new ConverterXOptions
        {
            DefaultQuality = QualityPreset.Low,
            MaxParallelConversions = 7,
            PreserveMetadataByDefault = false,
            EnableHardwareAcceleration = false,
            ToolsBasePath = @"C:\configured-tools",
            DefaultOutputDirectory = @"C:\configured-output",
            PostConversionAction = PostConversionAction.Delete,
            PostConversionArchiveFolder = @"C:\configured-archive"
        };

        ConvertCommand.ApplyConfigurationDefaults(settings, options);

        settings.Quality.Should().Be("lossless");
        settings.Parallel.Should().Be(2);
        settings.KeepMetadata.Should().BeTrue();
        settings.HardwareAccel.Should().BeTrue();
        settings.ToolsPath.Should().Be(@"C:\explicit-tools");
        settings.OutputDirectory.Should().Be(@"C:\explicit-output");
        settings.SourceAction.Should().Be("keep");
        settings.SourceArchive.Should().Be(@"C:\explicit-archive");
    }
}
