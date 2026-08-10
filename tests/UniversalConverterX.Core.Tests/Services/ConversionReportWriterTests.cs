using System.Text.Json;
using FluentAssertions;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class ConversionReportWriterTests : IDisposable
{
    private readonly string _tempDirectory = Path.Combine(
        Path.GetTempPath(),
        $"ucx-report-tests-{Guid.NewGuid():N}");

    [Fact]
    public async Task WriteJson_ShouldIncludeEveryResultAndAggregateByteDelta()
    {
        var results = CreateResults();
        var generatedAt = new DateTime(2026, 7, 16, 12, 0, 0, DateTimeKind.Utc);
        var report = ConversionReportWriter.Create(results, generatedAt);
        var path = Path.Combine(_tempDirectory, "nested", "batch.json");

        await ConversionReportWriter.WriteAsync(
            path,
            report,
            TestContext.Current.CancellationToken);

        using var json = JsonDocument.Parse(await File.ReadAllTextAsync(
            path,
            TestContext.Current.CancellationToken));
        json.RootElement.GetProperty("schemaVersion").GetInt32().Should().Be(1);
        json.RootElement.GetProperty("generatedAtUtc").GetDateTime().Should().Be(generatedAt);

        var summary = json.RootElement.GetProperty("summary");
        summary.GetProperty("totalFiles").GetInt32().Should().Be(2);
        summary.GetProperty("succeeded").GetInt32().Should().Be(1);
        summary.GetProperty("failed").GetInt32().Should().Be(1);
        summary.GetProperty("byteDelta").GetInt64().Should().Be(-40);

        var files = json.RootElement.GetProperty("files");
        files.GetArrayLength().Should().Be(2);
        files[0].GetProperty("status").GetString().Should().Be("succeeded");
        files[0].GetProperty("byteDelta").GetInt64().Should().Be(-40);
        files[0].GetProperty("warnings")[0].GetString().Should().Be("metadata profile changed");
        files[1].GetProperty("status").GetString().Should().Be("failed");
        files[1].GetProperty("errorCode").GetString().Should().Be("exit_7");
    }

    [Fact]
    public async Task WriteCsv_ShouldUseInvariantValuesAndRfc4180Escaping()
    {
        var report = ConversionReportWriter.Create(CreateResults());
        var path = Path.Combine(_tempDirectory, "batch.csv");

        await ConversionReportWriter.WriteAsync(
            path,
            report,
            TestContext.Current.CancellationToken);

        var csv = await File.ReadAllTextAsync(
            path,
            TestContext.Current.CancellationToken);
        csv.Should().StartWith("timestamp_utc,source_path,output_path,status,source_bytes,output_bytes,byte_delta,duration_seconds,");
        csv.Should().Contain(",succeeded,100,60,-40,1.25,");
        csv.Should().Contain(",metadata profile changed,,");
        csv.Should().Contain("bad, \"\"quoted\"\" input.dat\"");
        csv.Split("\r\n", StringSplitOptions.RemoveEmptyEntries).Should().HaveCount(3);
    }

    [Fact]
    public async Task WriteCsv_ShouldNeutralizeFormulaInjectionButKeepNegativeNumbers()
    {
        Directory.CreateDirectory(_tempDirectory);
        var job = ConversionJob.Create(
            Path.Combine(_tempDirectory, "clip.dat"),
            Path.Combine(_tempDirectory, "out.dat"));
        job.InputFileSize = 10;
        var results = new[]
        {
            ConversionResult.Failed(
                job,
                "=cmd|'/c calc'!A1",
                TimeSpan.FromSeconds(0.5),
                exitCode: 1,
                converter: "test-engine"),
        };
        var report = ConversionReportWriter.Create(results);
        var path = Path.Combine(_tempDirectory, "inject.csv");

        await ConversionReportWriter.WriteAsync(
            path,
            report,
            TestContext.Current.CancellationToken);

        var csv = await File.ReadAllTextAsync(
            path,
            TestContext.Current.CancellationToken);
        // Formula-triggering error text is prefixed with an apostrophe...
        csv.Should().Contain("'=cmd|'/c calc'!A1");
        csv.Should().NotContain(",=cmd");
        // ...while genuine negative numbers (byte delta) are left intact.
        csv.Should().NotContain("'-");
    }

    [Fact]
    public async Task CreateFromHistory_ShouldPreservePersistedStatusAndDurations()
    {
        var report = ConversionReportWriter.CreateFromHistory(
        [
            new ConversionHistoryEntry
            {
                Timestamp = new DateTime(2026, 7, 16, 8, 0, 0, DateTimeKind.Local),
                Engine = "clipforge",
                Action = "crop-meta",
                SourcePath = "source.mp4",
                OutputPath = "output.mp4",
                SourceBytes = 1_000,
                OutputBytes = 990,
                DurationSeconds = 0.5,
                Success = true,
                Profile = "Lossless crop",
            },
        ]);

        report.Files.Should().ContainSingle().Which.Should().BeEquivalentTo(new
        {
            Status = "succeeded",
            Engine = "clipforge",
            Action = "crop-meta",
            Profile = "Lossless crop",
            ByteDelta = -10L,
            DurationSeconds = 0.5,
        });
        report.Files[0].TimestampUtc.Kind.Should().Be(DateTimeKind.Utc);

        var act = () => ConversionReportWriter.WriteAsync(
            Path.Combine(_tempDirectory, "report.txt"),
            report);
        await act.Should().ThrowAsync<ArgumentException>()
            .WithMessage("*must end in .json or .csv*");
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_tempDirectory))
                Directory.Delete(_tempDirectory, recursive: true);
        }
        catch
        {
            // A failed assertion may leave an async file handle unwinding.
        }
    }

    private IReadOnlyList<ConversionResult> CreateResults()
    {
        Directory.CreateDirectory(_tempDirectory);
        var source = Path.Combine(_tempDirectory, "source.dat");
        var output = Path.Combine(_tempDirectory, "output.dat");
        File.WriteAllBytes(source, new byte[100]);
        File.WriteAllBytes(output, new byte[60]);

        var successJob = ConversionJob.Create(source, output);
        successJob.InputFileSize = 100;
        successJob.CompletedAt = new DateTime(2026, 7, 16, 10, 0, 0, DateTimeKind.Utc);
        var failedJob = ConversionJob.Create(
            Path.Combine(_tempDirectory, "bad, \"quoted\" input.dat"),
            Path.Combine(_tempDirectory, "unused.dat"));
        failedJob.InputFileSize = 50;

        return
        [
            ConversionResult.Succeeded(
                successJob,
                output,
                TimeSpan.FromSeconds(1.25),
                converter: "test-engine",
                warnings: ["metadata profile changed"]),
            ConversionResult.Failed(
                failedJob,
                "decoder rejected input",
                TimeSpan.FromSeconds(0.75),
                exitCode: 7,
                converter: "test-engine"),
        ];
    }
}
