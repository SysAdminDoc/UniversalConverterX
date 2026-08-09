using System.Diagnostics;
using System.Security.Cryptography;
using FluentAssertions;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public sealed class MediaFidelityProbeTests
{
    [Fact]
    public void Parse_ExtractsMetadataFamiliesUsedByTheCorpus()
    {
        const string json = """
            {
              "format": {
                "duration": "1.250000",
                "nb_streams": 4,
                "tags": {
                  "title": "fixture",
                  "c2pa_manifest": "local-test-manifest.json",
                  "ultrahdr_gain_map": "iso-21496-1"
                }
              },
              "streams": [
                {
                  "index": 0,
                  "codec_name": "h264",
                  "codec_type": "video",
                  "width": 320,
                  "height": 180,
                  "color_space": "bt2020nc",
                  "color_transfer": "smpte2084",
                  "color_primaries": "bt2020",
                  "tags": { "rotate": "90", "title": "picture" },
                  "disposition": { "default": 1, "attached_pic": 0 },
                  "side_data_list": [
                    { "side_data_type": "Display Matrix", "rotation": 90 }
                  ]
                },
                {
                  "index": 1,
                  "codec_name": "flac",
                  "codec_type": "audio",
                  "tags": { "language": "eng", "title": "commentary" },
                  "disposition": { "default": 1, "original": 1 }
                },
                {
                  "index": 2,
                  "codec_name": "ass",
                  "codec_type": "subtitle",
                  "tags": { "language": "spa", "title": "captions" },
                  "disposition": { "forced": 1 }
                },
                {
                  "index": 3,
                  "codec_name": "bin_data",
                  "codec_type": "attachment",
                  "tags": { "filename": "cover-art.svg", "mimetype": "image/svg+xml" },
                  "disposition": { "attached_pic": 0 }
                }
              ],
              "chapters": [
                { "id": 0, "start_time": "0.000000", "end_time": "0.600000", "tags": { "title": "Opening" } }
              ]
            }
            """;

        var snapshot = MediaFidelityProbe.Parse(json, "fixture.mkv");

        snapshot.DurationSeconds.Should().BeApproximately(1.25, 0.0001);
        snapshot.StreamCount.Should().Be(4);
        snapshot.FormatTags.Should().Contain(new KeyValuePair<string, string>("c2pa_manifest", "local-test-manifest.json"));
        snapshot.Streams.Should().HaveCount(4);
        snapshot.Streams[0].Rotation.Should().Be("90");
        snapshot.Streams[0].Properties["color_transfer"].Should().Be("smpte2084");
        snapshot.Streams[1].Tags["language"].Should().Be("eng");
        snapshot.Streams[1].Disposition["original"].Should().Be(1);
        snapshot.Streams[3].Tags["mimetype"].Should().Be("image/svg+xml");
        snapshot.Chapters.Should().ContainSingle();
        snapshot.Chapters[0].Tags["title"].Should().Be("Opening");
    }

    [Fact]
    public void Compare_IgnoresEncoderTagButDetectsMetadataLoss()
    {
        var expected = MediaFidelityProbe.Parse("""
            {
              "format": { "duration": "1", "nb_streams": 1, "tags": { "title": "keep", "encoder": "source" } },
              "streams": [
                { "index": 0, "codec_name": "flac", "codec_type": "audio", "tags": { "language": "eng" }, "disposition": { "default": 1 } }
              ],
              "chapters": []
            }
            """);
        var actual = MediaFidelityProbe.Parse("""
            {
              "format": { "duration": "1.05", "nb_streams": 1, "tags": { "title": "keep", "encoder": "new-tool" } },
              "streams": [
                { "index": 0, "codec_name": "flac", "codec_type": "audio", "tags": { "language": "eng" }, "disposition": { "default": 1 } }
              ],
              "chapters": []
            }
            """);

        var comparison = MediaFidelityProbe.Compare(expected, actual);

        comparison.IsMatch.Should().BeTrue();
        comparison.Mismatches.Should().BeEmpty();

        var lostMetadata = MediaFidelityProbe.Parse("""
            {
              "format": { "duration": "1", "nb_streams": 1, "tags": { "encoder": "new-tool" } },
              "streams": [
                { "index": 0, "codec_name": "flac", "codec_type": "audio", "tags": {}, "disposition": { "default": 1 } }
              ],
              "chapters": []
            }
            """);

        var mismatch = MediaFidelityProbe.Compare(expected, lostMetadata);
        mismatch.IsMatch.Should().BeFalse();
        mismatch.Mismatches.Should().Contain(item => item.Contains("tags language", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public async Task Probe_MalformedFixtureReturnsDiagnostic()
    {
        var ffprobe = FindExecutable("ffprobe");
        if (ffprobe is null)
            return;

        var fixture = FindFixture("malformed.mkv");
        var result = await MediaFidelityProbe.ProbeAsync(ffprobe, fixture);

        result.Succeeded.Should().BeFalse();
        result.Snapshot.Should().BeNull();
        result.Diagnostic.Should().NotBeNullOrWhiteSpace();
    }

    [Fact]
    public async Task FfmpegStreamCopyRoundTripPreservesCorpusAndSource()
    {
        var ffmpeg = FindExecutable("ffmpeg");
        var ffprobe = FindExecutable("ffprobe");
        if (ffmpeg is null || ffprobe is null)
            return;

        var fixtureRoot = FindFixtureDirectory();
        var tempRoot = Path.Combine(Path.GetTempPath(), $"ucx-media-fidelity-{Guid.NewGuid():N}");
        Directory.CreateDirectory(tempRoot);

        try
        {
            var source = Path.Combine(tempRoot, "source.mkv");
            var output = Path.Combine(tempRoot, "round-trip.mkv");
            var sourceArguments =
                new[]
                {
                    "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24:d=1.2",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.2",
                    "-f", "srt", "-i", Path.Combine(fixtureRoot, "subtitles-en.srt"),
                    "-f", "srt", "-i", Path.Combine(fixtureRoot, "subtitles-es.srt"),
                    "-i", Path.Combine(fixtureRoot, "fixture.ffmetadata"),
                    "-map", "0:v:0", "-map", "1:a:0", "-map", "2:0", "-map", "3:0",
                    "-map_metadata", "4", "-map_chapters", "4",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "flac", "-c:s", "srt",
                    "-metadata:s:v:0", "rotate=90",
                    "-colorspace", "bt2020nc", "-color_primaries", "bt2020", "-color_trc", "smpte2084",
                    "-metadata:s:a:0", "language=eng", "-metadata:s:a:0", "title=English commentary",
                    "-disposition:a:0", "default+original",
                    "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "title=English captions",
                    "-disposition:s:0", "default",
                    "-metadata:s:s:1", "language=spa", "-metadata:s:s:1", "title=Subtítulos",
                    "-disposition:s:1", "forced",
                    "-attach", Path.Combine(fixtureRoot, "cover-art.svg"),
                    "-metadata:s:t:0", "mimetype=image/svg+xml", "-metadata:s:t:0", "filename=cover-art.svg",
                    "-attach", Path.Combine(FindFixtureDirectory(), "..", "c2pa", "local-test-manifest.json"),
                    "-metadata:s:t:1", "mimetype=application/json", "-metadata:s:t:1", "filename=local-test-manifest.json",
                    source,
                };

            var generated = await RunToolAsync(ffmpeg, sourceArguments);
            generated.ExitCode.Should().Be(0, generated.StandardError);
            File.Exists(source).Should().BeTrue();

            var originalHash = await HashAsync(source);
            var before = await MediaFidelityProbe.ProbeAsync(ffprobe, source);
            before.Succeeded.Should().BeTrue(before.Diagnostic);
            before.Snapshot!.Streams.Should().HaveCount(6);
            before.Snapshot.Chapters.Should().HaveCount(2);
            before.Snapshot.FormatTags.Should().ContainKey("c2pa_manifest");
            before.Snapshot.FormatTags.Should().ContainKey("ultrahdr_gain_map");

            var job = ConversionJob.Create(
                source,
                output,
                new ConversionOptions
                {
                    OverwriteExisting = true,
                    PreserveMetadata = true,
                    StreamCopy = true,
                });
            var conversion = await new FFmpegConverter(Path.Combine(tempRoot, "no-managed-tools"))
                .ConvertAsync(job);

            conversion.Success.Should().BeTrue(conversion.ErrorMessage);
            var after = await MediaFidelityProbe.ProbeAsync(ffprobe, output);
            after.Succeeded.Should().BeTrue(after.Diagnostic);
            var comparison = MediaFidelityProbe.Compare(
                before.Snapshot,
                after.Snapshot!,
                new MediaFidelityComparisonOptions { RequireCodecIdentity = true });
            comparison.IsMatch.Should().BeTrue(string.Join(Environment.NewLine, comparison.Mismatches));
            after.Snapshot!.Streams.Select(stream => stream.Type)
                .Should().ContainInOrder("video", "audio", "subtitle", "subtitle", "attachment", "attachment");
            (await HashAsync(source)).Should().Be(originalHash);
        }
        finally
        {
            try { Directory.Delete(tempRoot, recursive: true); } catch { }
        }
    }

    [Fact]
    public async Task FfmpegCancellationDoesNotLeaveAnOutputOrChangeTheSource()
    {
        var ffmpeg = FindExecutable("ffmpeg");
        if (ffmpeg is null)
            return;

        var fixtureRoot = FindFixtureDirectory();
        var tempRoot = Path.Combine(Path.GetTempPath(), $"ucx-media-cancel-{Guid.NewGuid():N}");
        Directory.CreateDirectory(tempRoot);

        try
        {
            var source = Path.Combine(tempRoot, "source.mkv");
            var output = Path.Combine(tempRoot, "cancelled.mkv");
            var generated = await RunToolAsync(ffmpeg,
            [
                "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24:d=1.2",
                "-c:v", "libx264", "-preset", "ultrafast", source,
            ]);
            generated.ExitCode.Should().Be(0, generated.StandardError);
            var originalHash = await HashAsync(source);

            using var cancellation = new CancellationTokenSource();
            cancellation.Cancel();
            var result = await new FFmpegConverter(Path.Combine(tempRoot, "no-managed-tools"))
                .ConvertAsync(
                    ConversionJob.Create(source, output, new ConversionOptions
                    {
                        OverwriteExisting = true,
                        StreamCopy = true,
                    }),
                    cancellationToken: cancellation.Token);

            result.WasCancelled.Should().BeTrue();
            File.Exists(output).Should().BeFalse();
            (await HashAsync(source)).Should().Be(originalHash);
        }
        finally
        {
            try { Directory.Delete(tempRoot, recursive: true); } catch { }
        }
    }

    private static string FindFixture(string fileName) =>
        Path.Combine(FindFixtureDirectory(), fileName);

    private static string FindFixtureDirectory()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory);
             directory is not null;
             directory = directory.Parent)
        {
            var candidate = Path.Combine(directory.FullName, "tests", "fixtures", "media-fidelity");
            if (File.Exists(Path.Combine(candidate, "manifest.json")))
                return candidate;
        }

        throw new DirectoryNotFoundException("The media fidelity fixture directory could not be located.");
    }

    private static string? FindExecutable(string name)
    {
        var executable = OperatingSystem.IsWindows() && !name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
            ? name + ".exe"
            : name;
        var path = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        foreach (var directory in path.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            var candidate = Path.Combine(directory.Trim(), executable);
            if (File.Exists(candidate))
                return candidate;
        }

        return null;
    }

    private static async Task<ToolResult> RunToolAsync(string executable, IEnumerable<string> arguments)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var argument in arguments)
            startInfo.ArgumentList.Add(argument);

        using var process = Process.Start(startInfo)!;
        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        return new ToolResult(process.ExitCode, await stdoutTask, await stderrTask);
    }

    private static async Task<string> HashAsync(string path)
    {
        await using var stream = File.OpenRead(path);
        return Convert.ToHexString(await SHA256.HashDataAsync(stream));
    }

    private sealed record ToolResult(int ExitCode, string StandardOutput, string StandardError);
}
