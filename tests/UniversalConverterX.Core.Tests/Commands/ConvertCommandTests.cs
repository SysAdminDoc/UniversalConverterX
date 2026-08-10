using FluentAssertions;
using UniversalConverterX.Console.Commands;

namespace UniversalConverterX.Core.Tests.Commands;

public sealed class ConvertCommandTests : IDisposable
{
    private readonly string _directory = Path.Combine(
        Path.GetTempPath(),
        "ucx-convert-command-tests",
        Guid.NewGuid().ToString("N"));

    [Fact]
    public void ExpandFiles_ReportsMissingLiteralInputsWithoutDroppingExistingFiles()
    {
        Directory.CreateDirectory(_directory);
        var existing = Path.Combine(_directory, "existing.mp4");
        var missing = Path.Combine(_directory, "missing.mp4");
        File.WriteAllText(existing, "fixture");

        var files = ConvertCommand.ExpandFiles([existing, missing], out var missingFiles);

        files.Should().ContainSingle().Which.Should().Be(Path.GetFullPath(existing));
        missingFiles.Should().ContainSingle().Which.Should().Be(missing);
    }

    [Fact]
    public void ExpandFiles_DoesNotTreatAnUnmatchedGlobAsAnExplicitMissingFile()
    {
        Directory.CreateDirectory(_directory);
        var pattern = Path.Combine(_directory, "*.mp4");

        var files = ConvertCommand.ExpandFiles([pattern], out var missingFiles);

        files.Should().BeEmpty();
        missingFiles.Should().BeEmpty();
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_directory))
                Directory.Delete(_directory, recursive: true);
        }
        catch
        {
            // Best effort; the test uses an isolated directory.
        }
    }
}
