using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public class ConverterPreflightAnalyzerTests
{
    [Fact]
    public void Analyze_ReadyRoute_HasNoWarnings()
    {
        var result = ConverterPreflightAnalyzer.Analyze("mkv", 1024, true, "mp4", true);

        result.Should().BeEmpty();
    }

    [Fact]
    public void Analyze_MissingSource_IsBlocking()
    {
        var result = ConverterPreflightAnalyzer.Analyze("mkv", 1024, false, "mp4", true);

        result.Should().ContainSingle(item =>
            item.Code == "source_missing"
            && item.Severity == ConverterPreflightSeverity.Error);
    }

    [Fact]
    public void Analyze_EmptySource_IsBlocking()
    {
        var result = ConverterPreflightAnalyzer.Analyze("mkv", 0, true, "mp4", true);

        result.Should().ContainSingle(item =>
            item.Code == "source_empty"
            && item.Severity == ConverterPreflightSeverity.Error);
    }

    [Fact]
    public void Analyze_MissingOutput_AsksForFormat()
    {
        var result = ConverterPreflightAnalyzer.Analyze("mkv", 1024, true, null, null);

        result.Should().ContainSingle(item =>
            item.Code == "output_required"
            && item.Severity == ConverterPreflightSeverity.Warning);
    }

    [Fact]
    public void Analyze_UnsupportedRoute_IsBlocking()
    {
        var result = ConverterPreflightAnalyzer.Analyze("docx", 1024, true, "mp4", false);

        result.Should().ContainSingle(item =>
            item.Code == "route_unsupported"
            && item.Message.Contains("DOCX to MP4")
            && item.Severity == ConverterPreflightSeverity.Error);
    }

    [Fact]
    public void Analyze_SameFormat_WarnsAboutReencode()
    {
        var result = ConverterPreflightAnalyzer.Analyze(".MP4", 1024, true, "mp4", true);

        result.Should().ContainSingle(item =>
            item.Code == "same_format"
            && item.Severity == ConverterPreflightSeverity.Warning);
    }
}
