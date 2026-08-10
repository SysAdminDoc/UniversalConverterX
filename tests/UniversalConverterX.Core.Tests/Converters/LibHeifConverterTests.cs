using FluentAssertions;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Converters;

public class LibHeifConverterTests
{
    [Fact]
    public void BuildArguments_EncodingSmallImageDoesNotEmitIncompleteThumbnailOption()
    {
        var converter = new LibHeifConverter(
            Path.Combine(Path.GetTempPath(), "ucx-test-tools"));
        var job = new ConversionJob
        {
            InputPath = "input.png",
            OutputPath = "output.heic",
        };
        var options = new ConversionOptions
        {
            Image = new ImageOptions { Width = 200 },
        };

        var args = converter.BuildArguments(job, options);

        args.Should().NotContain("-t");
        args.Should().ContainInOrder("-o", "output.heic");
    }
}
