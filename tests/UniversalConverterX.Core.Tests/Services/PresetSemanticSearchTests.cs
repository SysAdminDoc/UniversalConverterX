using FluentAssertions;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class PresetSemanticSearchTests
{
    private static readonly PresetSearchDocument[] Documents =
    [
        new("video-compress", "Social Video Compression", "Video/Compression", "videocrush", ["mp4", "mov"], "mp4"),
        new("image-webp", "PNG to WebP", "Image/Convert", "converter", ["png"], "webp"),
        new("speech-srt", "Whisper Speech Transcription", "Audio/Subtitles", "whisper-stt", ["wav", "mp3"], "srt"),
        new("audio-flac", "WAV to FLAC", "Audio/Lossless", "converter", ["wav"], "flac"),
        new("video-tags", "AI Video Tags", "Video/Analysis", "videotag", ["mp4"], "json"),
    ];

    [Fact]
    public void Search_ShouldResolveNaturalCompressionAliases()
    {
        var matches = PresetSemanticSearch.Search("make movie smaller", Documents);

        matches.Should().NotBeEmpty();
        matches[0].Id.Should().Be("video-compress");
        matches[0].Score.Should().BeGreaterThan(matches.Single(match => match.Id == "video-tags").Score);
    }

    [Fact]
    public void Search_ShouldPreferActualVideoEncodingVocabularyOverOtherCompressionDomains()
    {
        var documents = new[]
        {
            new PresetSearchDocument("pdf", "PDF Compress", "Documents/PDF", "pdftools", ["pdf"], "pdf"),
            new PresetSearchDocument("audio", "MP3 smaller files", "Audio", "audiopro", ["wav"], "mp3"),
            new PresetSearchDocument("video", "Encode to VMAF 95", "Video/Quality target", "ab-av1", ["mp4"], "mkv"),
        };

        PresetSemanticSearch.Search("make movie smaller", documents)[0].Id.Should().Be("video");
    }

    [Fact]
    public void Search_ShouldResolveSpeechCaptionIntentWithoutExactPhrase()
    {
        PresetSemanticSearch.Search("speech captions", Documents)[0].Id.Should().Be("speech-srt");
    }

    [Fact]
    public void Search_ShouldUseExactMediaAndOutputTerms()
    {
        PresetSemanticSearch.Search("video metadata json", Documents)[0].Id.Should().Be("video-tags");
        PresetSemanticSearch.Search("png webp", Documents)[0].Id.Should().Be("image-webp");
    }

    [Fact]
    public void Search_ShouldBeBoundedAndDeterministic()
    {
        var tied = new[]
        {
            new PresetSearchDocument("z", "Convert video", "Video", "converter", ["mp4"], "mkv"),
            new PresetSearchDocument("a", "Convert video", "Video", "converter", ["mp4"], "mkv"),
        };

        PresetSemanticSearch.Search("convert video", tied, limit: 1)
            .Should().ContainSingle().Which.Id.Should().Be("a");
        PresetSemanticSearch.Search("  ", tied).Should().BeEmpty();
    }
}
