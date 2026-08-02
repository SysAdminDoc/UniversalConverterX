using FluentAssertions;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Security;

namespace UniversalConverterX.Core.Tests.Models;

/// <summary>
/// Immutable job provenance (ROADMAP Item 154): users could not previously
/// reproduce which preset, binary, arguments, or fallback produced an output.
/// </summary>
public sealed class JobProvenanceTests
{
    private static JobProvenance Sample() => new()
    {
        StartedUtc = new DateTime(2026, 8, 2, 9, 30, 0, DateTimeKind.Utc),
        DurationSeconds = 42.5,
        Engine = "videocrush",
        PresetName = "web-1080p",
        PresetSha256 = new string('a', 64),
        RedactedArgs = ["--input", "clip.mkv", "--token", ArgumentRedactor.Placeholder],
        Executable = new ExecutableIdentity("videocrush", @"D:\tools\videocrush.exe", "1.4.0", 2048, null),
        Input = new FileIdentity("clip.mkv", 1024, null),
        Output = new FileIdentity("out.mp4", 512, null),
        Capability = new CapabilityDecision("h264_nvenc", "libx264", true, "no NVENC device"),
        OutputProbe = new OutputProbeSummary(512, 30.0, 30.1, true, null),
        ProductVersion = "2.33.0",
        ExitCode = 0,
        Succeeded = true,
    };

    [Fact]
    public void RoundTripsEveryRecordedField()
    {
        var json = JobProvenanceCodec.Serialize(Sample());

        JobProvenanceCodec.TryDeserialize(json, out var restored, out var error)
            .Should().BeTrue(error);
        restored!.Engine.Should().Be("videocrush");
        restored.PresetName.Should().Be("web-1080p");
        restored.PresetSha256.Should().Be(new string('a', 64));
        restored.RedactedArgs.Should().Equal(
            "--input", "clip.mkv", "--token", ArgumentRedactor.Placeholder);
        restored.Executable!.Version.Should().Be("1.4.0");
        restored.Input!.SizeBytes.Should().Be(1024);
        restored.Output!.Path.Should().Be("out.mp4");
        restored.Capability!.FellBack.Should().BeTrue();
        restored.Capability.Selected.Should().Be("libx264");
        restored.OutputProbe!.DurationWithinTolerance.Should().BeTrue();
        restored.ExitCode.Should().Be(0);
        restored.Succeeded.Should().BeTrue();
    }

    [Fact]
    public void ADifferentSchemaVersionIsRejectedRatherThanPartiallyTrusted()
    {
        var json = JobProvenanceCodec.Serialize(Sample())
            .Replace("\"schemaVersion\":1", "\"schemaVersion\":99", StringComparison.Ordinal);

        JobProvenanceCodec.TryDeserialize(json, out var restored, out var error)
            .Should().BeFalse();
        restored.Should().BeNull();
        error.Should().Contain("schema");
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("{not json")]
    public void UnusablePayloadsAreRejected(string? json)
    {
        JobProvenanceCodec.TryDeserialize(json, out var restored, out var error)
            .Should().BeFalse();
        restored.Should().BeNull();
        error.Should().NotBeNullOrWhiteSpace();
    }

    [Fact]
    public void APayloadWithoutAnEngineIsRejected()
    {
        var provenance = Sample();
        provenance.Engine = "";
        var json = JobProvenanceCodec.Serialize(provenance);

        JobProvenanceCodec.TryDeserialize(json, out _, out var error).Should().BeFalse();
        error.Should().Contain("engine");
    }

    [Fact]
    public void APathologicalArgumentVectorIsTrimmedRatherThanDroppingTheRecord()
    {
        var provenance = Sample();
        provenance.RedactedArgs = [.. Enumerable.Range(0, 20_000).Select(i => $"--flag-{i}")];

        var json = JobProvenanceCodec.Serialize(provenance);

        json.Length.Should().BeLessThan(JobProvenanceCodec.MaxSerializedLength * 2);
        JobProvenanceCodec.TryDeserialize(json, out var restored, out var error)
            .Should().BeTrue(error);
        restored!.Engine.Should().Be("videocrush",
            "engine and binary matter more than the full argv when trimming");
        restored.RedactedArgs.Should().ContainSingle()
            .Which.Should().Contain("omitted");
    }

    [Fact]
    public void FileIdentityCapturesSizeAndModificationTime()
    {
        var path = Path.Combine(Path.GetTempPath(), "ucx-prov-" + Guid.NewGuid().ToString("N"));
        File.WriteAllText(path, "hello");
        try
        {
            var identity = FileIdentity.Capture(path);

            identity.Should().NotBeNull();
            identity!.SizeBytes.Should().Be(5);
            identity.LastWriteUtc.Should().NotBeNull();
            identity.Sha256.Should().BeNull("hashing is opt-in so a large source is not read twice");
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void FileIdentityHashesOnlyWhenAsked()
    {
        var path = Path.Combine(Path.GetTempPath(), "ucx-prov-" + Guid.NewGuid().ToString("N"));
        File.WriteAllText(path, "hello");
        try
        {
            var identity = FileIdentity.Capture(path, includeHash: true);

            identity!.Sha256.Should().Be(
                "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824");
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void FileIdentityIsNullForAMissingFile()
    {
        FileIdentity.Capture(Path.Combine(Path.GetTempPath(), "definitely-not-here-" + Guid.NewGuid()))
            .Should().BeNull();
        FileIdentity.Capture(null).Should().BeNull();
        FileIdentity.Capture("   ").Should().BeNull();
    }

    [Fact]
    public void ExecutableIdentityFallsBackWhenTheBinaryIsNotOnDisk()
    {
        var identity = ExecutableIdentity.Capture(
            "ghost", Path.Combine(Path.GetTempPath(), "ghost-" + Guid.NewGuid() + ".exe"), "9.9");

        identity.Should().NotBeNull();
        identity!.Name.Should().Be("ghost");
        identity.Version.Should().Be("9.9");
        identity.SizeBytes.Should().Be(0);
    }
}
