using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class FfmpegCommandTemplateTests
{
    private const string Input = @"C:\media files\input 雪.mp4";
    private const string Output = @"C:\output files\result.mp3";

    [Fact]
    public void CreateAndMaterialize_ShouldRoundTripQuotedPathsAndArguments()
    {
        string[] original = ["-y", "-i", Input, "-metadata", "title=A \"quote\"", Output];

        var template = FfmpegCommandTemplate.Create(original, Input, Output);
        var success = FfmpegCommandTemplate.TryMaterialize(
            template,
            Input,
            Output,
            out var materialized,
            out var error);

        success.Should().BeTrue(error);
        template.Should().Contain("{input}").And.Contain("{output}");
        materialized.Should().Equal(original);
    }

    [Theory]
    [InlineData("ffmpeg -i {input} ; calc {output}")]
    [InlineData("ffmpeg -i {input} & whoami {output}")]
    [InlineData("ffmpeg -i {input} | more {output}")]
    [InlineData("ffmpeg -i {input} > stolen.txt {output}")]
    [InlineData("ffmpeg -i {input}\n{output}")]
    public void TryMaterialize_ShouldRejectShellMetacharacters(string template)
    {
        FfmpegCommandTemplate.TryMaterialize(
            template,
            Input,
            Output,
            out _,
            out var error).Should().BeFalse();

        error.Should().Contain("Shell metacharacters");
    }

    [Theory]
    [InlineData("ffmpeg -i input.mp4 {output}")]
    [InlineData("ffmpeg -i {input} output.mp4")]
    [InlineData("ffmpeg -i {input} {input} {output}")]
    [InlineData("ffmpeg -i prefix-{input} {output}")]
    public void TryMaterialize_ShouldRequireExactSinglePlaceholders(string template)
    {
        FfmpegCommandTemplate.TryMaterialize(
            template,
            Input,
            Output,
            out _,
            out var error).Should().BeFalse();

        error.Should().NotBeNullOrWhiteSpace();
    }

    [Fact]
    public void TryMaterialize_ShouldRejectUnmatchedQuotes()
    {
        FfmpegCommandTemplate.TryMaterialize(
            "ffmpeg -i \"{input} {output}",
            Input,
            Output,
            out _,
            out var error).Should().BeFalse();

        error.Should().Contain("unmatched quote");
    }

    [Fact]
    public void TryParseReviewedCommand_ShouldAllowOriginalPathMetacharactersButRejectIntroducedOnes()
    {
        string[] original = ["-i", @"C:\media & audio\input.mp4", Output];
        var command = FfmpegCommandTemplate.FormatCommand(original);

        FfmpegCommandTemplate.TryParseReviewedCommand(
            command,
            original,
            out var parsed,
            out var error).Should().BeTrue(error);
        parsed.Should().Equal(original);

        FfmpegCommandTemplate.TryParseReviewedCommand(
            command + " ; calc",
            original,
            out _,
            out error).Should().BeFalse();
        error.Should().Contain("shell metacharacters");
    }

    [Fact]
    public void TryMaterialize_ShouldAllowMetacharactersInsideExactFilePaths()
    {
        const string input = @"C:\media & audio\input.mp4";
        const string output = @"C:\converted & ready\output.mp3";

        FfmpegCommandTemplate.TryMaterialize(
            "ffmpeg -i {input} {output}",
            input,
            output,
            out var arguments,
            out var error).Should().BeTrue(error);

        arguments.Should().Equal("-i", input, output);
    }
}
