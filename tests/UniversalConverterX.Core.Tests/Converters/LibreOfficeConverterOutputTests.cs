using FluentAssertions;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Converters;

public sealed class LibreOfficeConverterOutputTests : IDisposable
{
    private readonly string _tempDir;

    public LibreOfficeConverterOutputTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "ucx-lo-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tempDir);
    }

    // LibreOffice writes <outdir>/<sourceStem>.<ext>, ignoring the requested
    // output filename. When the target stem differs (collision suffix, template),
    // the produced file must be relocated so validation succeeds.
    [Fact]
    public void ValidateSuccessfulOutput_RelocatesProducedFileToRequestedPath()
    {
        var input = Path.Combine(_tempDir, "report.docx");
        File.WriteAllText(input, "source");
        // Requested output has a collision-avoidance suffix — different stem.
        var requestedOutput = Path.Combine(_tempDir, "report (1).pdf");
        // LibreOffice actually produced this file, keyed off the source stem.
        var producedByLibreOffice = Path.Combine(_tempDir, "report.pdf");
        File.WriteAllText(producedByLibreOffice, "converted");

        var converter = new TestableLibreOfficeConverter(_tempDir);
        var job = ConversionJob.Create(input, requestedOutput);

        var failure = converter.Validate(job);

        failure.Should().BeNull("the produced file was relocated to the requested path");
        File.Exists(requestedOutput).Should().BeTrue();
        File.Exists(producedByLibreOffice).Should().BeFalse();
        File.ReadAllText(requestedOutput).Should().Be("converted");
    }

    [Fact]
    public void ValidateSuccessfulOutput_LeavesCorrectlyNamedOutputUntouched()
    {
        var input = Path.Combine(_tempDir, "memo.docx");
        File.WriteAllText(input, "source");
        var output = Path.Combine(_tempDir, "memo.pdf");
        File.WriteAllText(output, "converted");

        var converter = new TestableLibreOfficeConverter(_tempDir);
        var job = ConversionJob.Create(input, output);

        var failure = converter.Validate(job);

        failure.Should().BeNull();
        File.Exists(output).Should().BeTrue();
        File.ReadAllText(output).Should().Be("converted");
    }

    public void Dispose()
    {
        try { Directory.Delete(_tempDir, recursive: true); }
        catch (IOException) { }
    }

    private sealed class TestableLibreOfficeConverter(string toolsBasePath)
        : LibreOfficeConverter(toolsBasePath)
    {
        public ConversionResult? Validate(ConversionJob job) =>
            ValidateSuccessfulOutput(job, TimeSpan.Zero, 0, null, null, "libreoffice", null, null);
    }
}
