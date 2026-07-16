using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class ExplorerPresetCommandBuilderTests
{
    [Fact]
    public void Build_ShouldPreserveSpacesQuotesUnicodeAndMetacharactersAsArguments()
    {
        const string preset = "Creator's \"HQ\" — 日本語 & safe";
        string[] files =
        [
            @"C:\Media Files\clip one.mov",
            "C:\\Media Files\\quote\"clip\".mkv",
            @"C:\Média\雪 & rain.mp4",
        ];

        var plan = ExplorerPresetCommandBuilder.Build(preset, files);
        var startInfo = plan.CreateStartInfo(@"C:\Program Files\UniversalConverterX\ucx.exe");

        plan.UsesInputList.Should().BeFalse();
        startInfo.UseShellExecute.Should().BeFalse();
        startInfo.Arguments.Should().BeEmpty("ArgumentList avoids shell-string interpolation");
        startInfo.ArgumentList.Should().Equal(
            "convert-preset",
            "--preset",
            preset,
            files[0],
            files[1],
            files[2]);
    }

    [Fact]
    public void Build_ShouldUseDeterministicListFilePlanPastCommandLineLimit()
    {
        string[] files =
        [
            @"C:\Long Folder\first input with spaces.mov",
            @"C:\Long Folder\second input with spaces.mov",
        ];
        const string listPath = @"C:\Temp\ucx inputs 雪.txt";

        var plan = ExplorerPresetCommandBuilder.Build(
            "To MP4",
            files,
            maxCommandLineChars: 40,
            inputListPathFactory: () => listPath);

        plan.UsesInputList.Should().BeTrue();
        plan.InputListPath.Should().Be(listPath);
        plan.InputListEntries.Should().Equal(files);
        plan.Arguments.Should().Equal(
            "convert-preset",
            "--preset",
            "To MP4",
            "--input-files",
            listPath);
        plan.Arguments.Should().NotContain(files);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void Build_ShouldRejectMissingPresetName(string presetName)
    {
        var action = () => ExplorerPresetCommandBuilder.Build(presetName, ["input.mp4"]);
        action.Should().Throw<ArgumentException>();
    }
}
