using FluentAssertions;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Converters;

public class PotraceConverterTests
{
    private readonly PotraceConverter _converter =
        new(Path.Combine(Path.GetTempPath(), "ucx-test-tools"));

    [Theory]
    [InlineData("pdf", "pdf")]
    [InlineData("dxf", "dxf")]
    [InlineData("geojson", "geojson")]
    [InlineData("fig", "xfig")]
    public void BuildArguments_BackendFormatsIncludeRequiredBackendName(
        string outputExtension,
        string backendName)
    {
        var args = _converter.BuildArguments(
            new ConversionJob
            {
                InputPath = "input.png",
                OutputPath = $"output.{outputExtension}",
            },
            new ConversionOptions());

        var backendIndex = Array.IndexOf(args, "-b");
        backendIndex.Should().BeGreaterOrEqualTo(0);
        args[backendIndex + 1].Should().Be(backendName);
    }
}
