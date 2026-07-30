using FluentAssertions;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class UcxActivationParserTests
{
    [Fact]
    public void CommandLine_PreservesEveryAbsolutePathAndExplicitRoute()
    {
        var first = Path.GetFullPath(Path.Combine("activation", "one file.mp4"));
        var second = Path.GetFullPath(Path.Combine("activation", "two.png"));

        var request = UcxActivationParser.ParseCommandLine(
            $"--route converter \"{first}\" \"{second}\" \"{first}\"");

        request.RouteKey.Should().Be("converter");
        request.Paths.Should().Equal(first, second);
        request.Source.Should().Be(UcxActivationSource.Launch);
    }

    [Fact]
    public void PlainExplorerArguments_DefaultToConverterAndIgnoreOptions()
    {
        var first = Path.GetFullPath(Path.Combine("activation", "first.mkv"));
        var second = Path.GetFullPath(Path.Combine("activation", "second.wav"));

        var request = UcxActivationParser.ParseCommandLine([
            @"C:\Program Files\UniversalConverterX\UniversalConverterX.exe",
            "--unknown",
            "relative.txt",
            first,
            second,
        ]);

        request.RouteKey.Should().Be("converter");
        request.Paths.Should().Equal(first, second);
    }

    [Fact]
    public void Protocol_MapsRouteAndRepeatedEncodedPaths()
    {
        var first = Path.GetFullPath(Path.Combine("activation", "first image.png"));
        var second = Path.GetFullPath(Path.Combine("activation", "second.mp4"));
        var uri = new Uri(
            "ucx://converter"
            + $"?path={Uri.EscapeDataString(first)}"
            + $"&file={Uri.EscapeDataString(second)}");

        var request = UcxActivationParser.ParseProtocol(uri);

        request.RouteKey.Should().Be("converter");
        request.Paths.Should().Equal(first, second);
        request.Source.Should().Be(UcxActivationSource.Protocol);
    }

    [Theory]
    [InlineData("ucx:history", "history")]
    [InlineData("ucx://toolbox", "toolbox")]
    [InlineData("ucx:convert", "converter")]
    [InlineData("ucx:../../settings", "home")]
    public void Protocol_NormalizesSupportedRouteShapes(string value, string route)
    {
        UcxActivationParser.ParseProtocol(new Uri(value))
            .RouteKey.Should().Be(route);
    }

    [Fact]
    public void ToastAndStartup_HaveDeterministicDestinations()
    {
        var toast = UcxActivationParser.ParseToast("route=history");
        var startup = UcxActivationParser.Startup();

        toast.RouteKey.Should().Be("history");
        toast.Source.Should().Be(UcxActivationSource.AppNotification);
        startup.RouteKey.Should().Be("home");
        startup.Source.Should().Be(UcxActivationSource.StartupTask);
    }

    [Fact]
    public void ExternalActivation_IsBoundedAndDeduplicated()
    {
        var paths = Enumerable.Range(0, 600)
            .Select(index => Path.GetFullPath(
                Path.Combine("activation", $"{index:D3}.bin")))
            .ToArray();

        var request = UcxActivationParser.ParseFiles(
            paths.Concat(paths.Take(10)));

        request.Paths.Should().HaveCount(512);
        request.Paths.Should().OnlyHaveUniqueItems();
    }
}
