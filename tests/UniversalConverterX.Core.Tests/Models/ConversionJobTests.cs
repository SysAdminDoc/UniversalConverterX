using FluentAssertions;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Models;

public class ConversionJobTests
{
    [Fact]
    public void CreateForExtension_WithMultipartExtension_ShouldCreateSiblingOutput()
    {
        var input = Path.Combine(Path.GetTempPath(), "clip.mov");

        var job = ConversionJob.CreateForExtension(input, ".tar.gz");

        job.OutputPath.Should().EndWith(Path.Combine(Path.GetTempPath(), "clip.tar.gz"));
    }

    [Theory]
    [InlineData("../mp4")]
    [InlineData(@"mp4\png")]
    [InlineData("mp4/png")]
    [InlineData("mp4:png")]
    [InlineData("bad ext")]
    public void CreateForExtension_WithUnsafeExtension_ShouldThrow(string outputExtension)
    {
        var input = Path.Combine(Path.GetTempPath(), "clip.mov");

        var action = () => ConversionJob.CreateForExtension(input, outputExtension);

        action.Should().Throw<ArgumentException>()
            .WithMessage("*Output extension*filename-safe*");
    }
}
