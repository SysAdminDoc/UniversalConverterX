using FluentAssertions;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Models;

public sealed class SubtitleDocumentTests
{
    private const string Sample = """
        1
        00:00:01,250 --> 00:00:03,500
        First line
        second line

        2
        00:00:04,000 --> 00:00:05,125
        Snow 雪
        """;

    [Fact]
    public void ParseSrt_ShouldPreserveMultilineUnicodeCues()
    {
        var document = SubtitleDocument.ParseSrt(Sample);

        document.Cues.Should().HaveCount(2);
        document.Cues[0].Start.Should().Be(TimeSpan.FromMilliseconds(1250));
        document.Cues[0].Text.Should().Be("First line\nsecond line");
        document.Cues[1].Text.Should().Be("Snow 雪");
    }

    [Fact]
    public void SerializeSrt_ShouldRoundTrip()
    {
        var serialized = SubtitleDocument.ParseSrt(Sample).Serialize("srt");

        SubtitleDocument.ParseSrt(serialized).Cues.Should().BeEquivalentTo(
            SubtitleDocument.ParseSrt(Sample).Cues);
    }

    [Fact]
    public void SerializeVtt_ShouldUseWebVttTimecodes()
    {
        var output = SubtitleDocument.ParseSrt(Sample).Serialize("vtt");

        output.Should().StartWith("WEBVTT\n\n");
        output.Should().Contain("00:00:01.250 --> 00:00:03.500");
        output.Should().Contain("Snow 雪");
    }

    [Fact]
    public void SerializeAss_ShouldIncludeEditableCuesAndLineBreaks()
    {
        var output = SubtitleDocument.ParseSrt(Sample).Serialize("ass");

        output.Should().Contain("[V4+ Styles]");
        output.Should().Contain("Dialogue: 0,0:00:01.25,0:00:03.50");
        output.Should().Contain(@"First line\Nsecond line");
    }

    [Fact]
    public void Constructor_ShouldRejectInvalidCueTiming()
    {
        FluentActions.Invoking(() => new SubtitleDocument(
                [new SubtitleCue(1, TimeSpan.FromSeconds(2), TimeSpan.FromSeconds(1), "Bad")]))
            .Should().Throw<InvalidDataException>()
            .WithMessage("*end after*");
    }
}
