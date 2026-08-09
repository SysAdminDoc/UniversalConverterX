using FluentAssertions;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class OutputCollisionPolicyTests : IDisposable
{
    private readonly string _tempDir = Path.Combine(
        Path.GetTempPath(),
        "ucx-output-policy-tests-" + Guid.NewGuid().ToString("N"));

    public OutputCollisionPolicyTests() => Directory.CreateDirectory(_tempDir);

    [Fact]
    public void TryProtectArguments_Never_RenamesExistingExplicitOutput()
    {
        var output = Path.Combine(_tempDir, "clip.mp4");
        File.WriteAllText(output, "prior");

        var ok = OutputCollisionPolicy.TryProtectArguments(
            ["--input", "clip.mov", "--output", output],
            OverwriteBehavior.Never,
            out var protectedArguments,
            out var skipped,
            out var error);

        ok.Should().BeTrue(error);
        skipped.Should().BeNull();
        protectedArguments.Should().Contain(Path.Combine(_tempDir, "clip (1).mp4"));
        File.ReadAllText(output).Should().Be("prior");
    }

    [Fact]
    public void TryProtectArguments_Skip_ReportsExistingOutputWithoutRewritingArguments()
    {
        var output = Path.Combine(_tempDir, "clip.mp4");
        File.WriteAllText(output, "prior");
        var args = new[] { "--input", "clip.mov", "--output", output };

        var ok = OutputCollisionPolicy.TryProtectArguments(
            args,
            OverwriteBehavior.Skip,
            out var protectedArguments,
            out var skipped,
            out var error);

        ok.Should().BeTrue(error);
        skipped.Should().Be(output);
        protectedArguments.Should().Equal(args);
    }

    [Theory]
    [InlineData(OverwriteBehavior.Always)]
    [InlineData(OverwriteBehavior.Ask)]
    public void TryProtectArguments_InteractiveOrExplicitOverwrite_PreservesExistingOutput(
        OverwriteBehavior behavior)
    {
        var output = Path.Combine(_tempDir, "clip.mp4");
        File.WriteAllText(output, "prior");

        var ok = OutputCollisionPolicy.TryProtectArguments(
            ["--output-file", output],
            behavior,
            out var protectedArguments,
            out var skipped,
            out var error);

        ok.Should().BeTrue(error);
        skipped.Should().BeNull();
        protectedArguments.Should().Equal("--output-file", output);
    }

    [Fact]
    public void TryProtectArguments_Never_ReservesDuplicateOutputsWithinOneInvocation()
    {
        var output = Path.Combine(_tempDir, "clip.mp4");
        var args = new[] { "--output", output, "--output", output };

        var ok = OutputCollisionPolicy.TryProtectArguments(
            args,
            OverwriteBehavior.Never,
            out var protectedArguments,
            out var skipped,
            out var error);

        ok.Should().BeTrue(error);
        skipped.Should().BeNull();
        protectedArguments.Should().Equal(
            "--output", output,
            "--output", Path.Combine(_tempDir, "clip (1).mp4"));
    }

    [Fact]
    public void TryProtectArguments_Never_RewritesEqualsForm()
    {
        var output = Path.Combine(_tempDir, "clip.mp4");
        File.WriteAllText(output, "prior");

        var ok = OutputCollisionPolicy.TryProtectArguments(
            [$"--output={output}"],
            OverwriteBehavior.Never,
            out var protectedArguments,
            out var skipped,
            out var error);

        ok.Should().BeTrue(error);
        skipped.Should().BeNull();
        protectedArguments.Should().Equal(
            $"--output={Path.Combine(_tempDir, "clip (1).mp4")}");
    }

    [Fact]
    public void TryResolvePath_Skip_ProtectsPerInputExtractionDirectory()
    {
        var outputDirectory = Path.Combine(_tempDir, "clip");
        Directory.CreateDirectory(outputDirectory);

        var ok = OutputCollisionPolicy.TryResolvePath(
            outputDirectory,
            OverwriteBehavior.Skip,
            out var resolved,
            out var shouldSkip,
            out var error);

        ok.Should().BeTrue(error);
        shouldSkip.Should().BeTrue();
        resolved.Should().Be(outputDirectory);
    }

    public void Dispose()
    {
        try { Directory.Delete(_tempDir, recursive: true); }
        catch (IOException) { }
    }
}
