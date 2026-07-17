using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class PresetInvocationModeTests
{
    [Theory]
    [InlineData("per-file", PresetInvocationMode.PerFile)]
    [InlineData("batch-input-list", PresetInvocationMode.BatchInputList)]
    [InlineData("batch-output-dir", PresetInvocationMode.BatchOutputDir)]
    [InlineData("batch-single-output", PresetInvocationMode.BatchSingleOutput)]
    [InlineData("extract-each", PresetInvocationMode.ExtractEach)]
    public void ParseAndWireName_RoundTripEveryEditorMode(
        string wireName,
        PresetInvocationMode expected)
    {
        PresetInvocationModes.Parse(wireName).Should().Be(expected);
        PresetInvocationModes.ToWireName(expected).Should().Be(wireName);
    }

    [Fact]
    public void BatchInputList_AppendsOneInputMarkerAndNoOutputArgument()
    {
        var arguments = PresetInvocationModes.BuildBatchInputArguments(
            ["auto-populate", "--overwrite"],
            ["one.mp3", "two.flac"]);

        arguments.Should().Equal(
            "auto-populate", "--overwrite", "--input", "one.mp3", "two.flac");
        arguments.Should().NotContain("--output");
        arguments.Should().NotContain("--output-dir");
        PresetInvocationModes.RequiresOutputDirectory(PresetInvocationMode.BatchInputList)
            .Should().BeFalse();
        PresetInvocationModes.ProducesOutputPath(PresetInvocationMode.BatchInputList)
            .Should().BeFalse();
    }

    [Theory]
    [InlineData(PresetInvocationMode.BatchOutputDir)]
    [InlineData(PresetInvocationMode.BatchSingleOutput)]
    [InlineData(PresetInvocationMode.ExtractEach)]
    public void OutputBatchModes_RequestADestination(PresetInvocationMode mode)
    {
        PresetInvocationModes.RequiresOutputDirectory(mode).Should().BeTrue();
    }
}
