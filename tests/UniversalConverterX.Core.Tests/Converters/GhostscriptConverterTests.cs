using FluentAssertions;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Converters;

public class GhostscriptConverterTests
{
    [Fact]
    public void BuildArguments_EscapesPercentInOutputPath()
    {
        var converter = new GhostscriptConverter(
            Path.Combine(Path.GetTempPath(), "ucx-test-tools"));
        var outputPath = Path.Combine(
            Path.GetTempPath(),
            "report 100%d.png");
        var job = new ConversionJob
        {
            InputPath = "input.pdf",
            OutputPath = outputPath,
        };

        var args = converter.BuildArguments(job, new ConversionOptions());

        args.Should().Contain(
            $"-sOutputFile={outputPath.Replace("%", "%%", StringComparison.Ordinal)}");
    }
}
