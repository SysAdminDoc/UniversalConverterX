using System.Diagnostics;
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

    // LibreOffice writes the filter's native extension, so requesting .jpeg
    // produces .jpg beside the requested path. The fresh alias file must be
    // relocated to the requested name.
    [Fact]
    public void ValidateSuccessfulOutput_RelocatesNativeExtensionAlias()
    {
        var input = Path.Combine(_tempDir, "slide.pptx");
        File.WriteAllText(input, "source");
        var requestedOutput = Path.Combine(_tempDir, "slide.jpeg");
        // LibreOffice's jpeg filter writes .jpg.
        var producedByLibreOffice = Path.Combine(_tempDir, "slide.jpg");
        File.WriteAllText(producedByLibreOffice, "converted");

        var converter = new TestableLibreOfficeConverter(_tempDir);
        var job = ConversionJob.Create(input, requestedOutput);

        var failure = converter.Validate(job);

        failure.Should().BeNull("the aliased .jpg output was relocated to the requested .jpeg");
        File.Exists(requestedOutput).Should().BeTrue();
        File.Exists(producedByLibreOffice).Should().BeFalse();
        File.ReadAllText(requestedOutput).Should().Be("converted");
    }

    // A stale same-stem alias file (written before this conversion) must not be
    // mistaken for the produced output.
    [Fact]
    public void ValidateSuccessfulOutput_IgnoresStaleAliasFile()
    {
        var input = Path.Combine(_tempDir, "chart.pptx");
        File.WriteAllText(input, "source");
        var requestedOutput = Path.Combine(_tempDir, "chart.jpeg");
        var staleAlias = Path.Combine(_tempDir, "chart.jpg");
        File.WriteAllText(staleAlias, "old");
        File.SetLastWriteTimeUtc(staleAlias, DateTime.UtcNow.AddHours(-2));

        var converter = new TestableLibreOfficeConverter(_tempDir);
        var job = ConversionJob.Create(input, requestedOutput);

        var failure = converter.Validate(job);

        // No fresh output exists, so validation should report failure and the
        // stale file is left where it was.
        failure.Should().NotBeNull();
        File.Exists(requestedOutput).Should().BeFalse();
        File.Exists(staleAlias).Should().BeTrue();
        File.ReadAllText(staleAlias).Should().Be("old");
    }

    [Fact]
    public void ValidateSuccessfulOutput_IgnoresStaleExactFile()
    {
        var input = Path.Combine(_tempDir, "report.docx");
        File.WriteAllText(input, "source");
        var staleOutput = Path.Combine(_tempDir, "report.pdf");
        File.WriteAllText(staleOutput, "old");
        File.SetLastWriteTimeUtc(staleOutput, DateTime.UtcNow.AddHours(-2));

        var converter = new TestableLibreOfficeConverter(_tempDir);
        var job = ConversionJob.Create(input, staleOutput);

        var failure = converter.Validate(job);

        failure.Should().NotBeNull("an exit-code-zero run without a fresh file must not trust a stale output");
        File.ReadAllText(staleOutput).Should().Be("old");
    }

    [Fact]
    public async Task ConvertAsync_StagesOutputBeforeRelocatingAroundAnExistingSibling()
    {
        var input = Path.Combine(_tempDir, "report.docx");
        File.WriteAllText(input, "source");
        var existingSibling = Path.Combine(_tempDir, "report.pdf");
        File.WriteAllText(existingSibling, "keep me");
        var requestedOutput = Path.Combine(_tempDir, "report (1).pdf");

        var converter = new StagingProbeLibreOfficeConverter(_tempDir);
        var job = ConversionJob.Create(input, requestedOutput);

        var result = await converter.ConvertAsync(
            job,
            cancellationToken: TestContext.Current.CancellationToken);

        result.Success.Should().BeTrue(result.ErrorMessage ?? result.StandardError ?? "conversion failed without diagnostics");
        File.ReadAllText(existingSibling).Should().Be("keep me");
        File.ReadAllText(requestedOutput).Trim().Should().Be("converted");

        var profileArgument = converter.CapturedStartArguments
            .Should().ContainSingle(argument =>
                argument.StartsWith("-env:UserInstallation=file:", StringComparison.Ordinal));
        var profileUri = new Uri(profileArgument.Subject["-env:UserInstallation=".Length..]);
        Directory.Exists(profileUri.LocalPath).Should().BeFalse();
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

    private sealed class StagingProbeLibreOfficeConverter(string toolsBasePath)
        : LibreOfficeConverter(toolsBasePath)
    {
        private string? _stagedOutput;

        public IReadOnlyList<string> CapturedStartArguments { get; private set; } = [];

        protected override string GetExecutablePath() =>
            Environment.GetEnvironmentVariable("ComSpec")
            ?? throw new InvalidOperationException("cmd.exe is required for this test");

        public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
        {
            var libreOfficeArguments = base.BuildArguments(job, options);
            var outDirIndex = Array.IndexOf(libreOfficeArguments, "--outdir");
            outDirIndex.Should().BeGreaterOrEqualTo(0);

            var stagedOutput = Path.Combine(
                libreOfficeArguments[outDirIndex + 1],
                Path.GetFileNameWithoutExtension(job.InputPath) + ".pdf");
            _stagedOutput = stagedOutput;

            return ["/c", $"echo converted>{stagedOutput}"];
        }

        protected override Task<ProcessResult> ExecuteProcessAsync(
            string executable,
            string[] arguments,
            ConversionJob job,
            IProgress<ConversionProgress>? progress,
            List<string> warnings,
            CancellationToken cancellationToken)
        {
            var startInfo = new ProcessStartInfo { FileName = executable };
            foreach (var argument in arguments)
                startInfo.ArgumentList.Add(argument);
            ConfigureProcessStartInfo(startInfo, job);
            CapturedStartArguments = [.. startInfo.ArgumentList];

            if (_stagedOutput is null)
                throw new InvalidOperationException("The staged output was not prepared.");
            File.WriteAllText(_stagedOutput, "converted");

            return Task.FromResult(new ProcessResult { Success = true, ExitCode = 0 });
        }
    }
}
