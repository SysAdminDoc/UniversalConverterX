using FluentAssertions;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public class FormatRecommenderTests
{
    [Theory]
    [InlineData(RecommendationTarget.Web, "mp4", "h264")]
    [InlineData(RecommendationTarget.Apple, "mp4", "hevc")]
    [InlineData(RecommendationTarget.Editing, "mov", "prores")]
    public void RecommendVideo_PicksTargetAppropriateContainerAndCodec(
        RecommendationTarget target, string container, string videoCodec)
    {
        var rec = FormatRecommender.Recommend(FormatCategory.Video, target);

        rec.Container.Should().Be(container);
        rec.VideoCodec.Should().Be(videoCodec);
        rec.Rationale.Should().NotBeNullOrWhiteSpace();
    }

    [Fact]
    public void RecommendVideo_Archive_IsLosslessMatroska()
    {
        var rec = FormatRecommender.Recommend(FormatCategory.Video, RecommendationTarget.Archive);

        rec.Container.Should().Be("mkv");
        rec.VideoCodec.Should().Be("ffv1");
        rec.Lossless.Should().BeTrue();
    }

    [Fact]
    public void RecommendAudio_Web_IsOpus()
    {
        var rec = FormatRecommender.Recommend(FormatCategory.Audio, RecommendationTarget.Web);

        rec.AudioCodec.Should().Be("libopus");
        rec.VideoCodec.Should().BeNull();
    }

    [Fact]
    public void RecommendAudio_Archive_IsLosslessFlac()
    {
        var rec = FormatRecommender.Recommend(FormatCategory.Audio, RecommendationTarget.Archive);

        rec.Container.Should().Be("flac");
        rec.Lossless.Should().BeTrue();
    }

    [Fact]
    public void RecommendImage_Web_IsWebp()
    {
        var rec = FormatRecommender.Recommend(FormatCategory.Image, RecommendationTarget.Web);

        rec.Container.Should().Be("webp");
    }

    [Theory]
    [InlineData("clip.mov", RecommendationTarget.Web, "mp4")]
    [InlineData("song.flac", RecommendationTarget.Web, "opus")]
    [InlineData("photo.png", RecommendationTarget.Apple, "heic")]
    [InlineData("mkv", RecommendationTarget.Archive, "mkv")]
    public void Recommend_ByExtension_ClassifiesThenRecommends(
        string source, RecommendationTarget target, string expectedContainer)
    {
        FormatRecommender.Recommend(source, target).Container.Should().Be(expectedContainer);
    }

    [Fact]
    public void Recommend_UnknownCategory_ReturnsGenericGuidance()
    {
        var rec = FormatRecommender.Recommend(FormatCategory.Document, RecommendationTarget.Web);

        rec.Rationale.Should().NotBeNullOrWhiteSpace();
        rec.Lossless.Should().BeFalse();
    }
}
