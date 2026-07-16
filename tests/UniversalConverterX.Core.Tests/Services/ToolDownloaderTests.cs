using System.Net;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using FluentAssertions;
using Microsoft.Extensions.Options;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public class ToolDownloaderTests : IDisposable
{
    private readonly string _toolsBasePath = Path.Combine(
        Path.GetTempPath(),
        "ucx-tool-downloader-tests",
        Guid.NewGuid().ToString("N"));

    [Fact]
    public async Task DownloadToolAsync_WithChecksumMismatch_ShouldFailBeforeInstall()
    {
        Directory.CreateDirectory(Path.Combine(_toolsBasePath, "bin"));
        var previousBytes = new byte[] { 9, 9, 9 };
        await File.WriteAllBytesAsync(ExpectedToolPath("ffmpeg"), previousBytes);

        var downloader = CreateDownloader([1, 2, 3]);
        var info = downloader.GetToolDownloadInfo("ffmpeg");
        info.Should().NotBeNull();
        info!.ExpectedChecksum = new string('0', 64);
        SetAllPlatformUrls(info, "https://example.test/ffmpeg.zip");

        var result = await downloader.DownloadToolAsync("ffmpeg");

        result.Success.Should().BeFalse();
        result.ErrorMessage.Should().Contain("Checksum mismatch");
        File.ReadAllBytes(ExpectedToolPath("ffmpeg")).Should().Equal(previousBytes);
    }

    [Fact]
    public async Task DownloadToolAsync_WithInstallerExecutable_ShouldFailClosed()
    {
        var payload = new byte[] { 1, 2, 3 };
        var downloader = CreateDownloader(payload);
        var info = downloader.GetToolDownloadInfo("ffmpeg");
        info.Should().NotBeNull();
        info!.ExpectedChecksum = Sha256(payload);
        SetAllPlatformUrls(info, "https://example.test/setup.exe");

        var result = await downloader.DownloadToolAsync("ffmpeg");

        result.Success.Should().BeFalse();
        result.ErrorMessage.Should().Contain("Automatic execution of downloaded installers is disabled");
        File.Exists(ExpectedToolPath("ffmpeg")).Should().BeFalse();
    }

    [Fact]
    public async Task DownloadToolAsync_WithZip_ShouldExtractExecutableAndCompanionFiles()
    {
        var exeName = "ffmpeg" + (OperatingSystem.IsWindows() ? ".exe" : "");
        var companionName = "ffprobe" + (OperatingSystem.IsWindows() ? ".exe" : "");
        var payload = CreateZip(
            ("nested/" + exeName, [1, 2, 3]),
            ("nested/" + companionName, [4, 5, 6]));
        var downloader = CreateDownloader(payload);
        var info = downloader.GetToolDownloadInfo("ffmpeg");
        info.Should().NotBeNull();
        info!.ExpectedChecksum = Sha256(payload);
        SetAllPlatformUrls(info, "https://example.test/ffmpeg.zip");

        var result = await downloader.DownloadToolAsync("ffmpeg");

        result.Success.Should().BeTrue();
        File.Exists(ExpectedToolPath("ffmpeg")).Should().BeTrue();
        File.Exists(Path.Combine(_toolsBasePath, "bin", companionName)).Should().BeTrue();
    }

    [Fact]
    public async Task DownloadToolAsync_WithExistingTool_ShouldRetainRollbackBackup()
    {
        var exeName = "ffmpeg" + (OperatingSystem.IsWindows() ? ".exe" : "");
        var companionName = "ffprobe" + (OperatingSystem.IsWindows() ? ".exe" : "");
        var binDir = Path.Combine(_toolsBasePath, "bin");
        Directory.CreateDirectory(binDir);
        await File.WriteAllBytesAsync(Path.Combine(binDir, exeName), [7, 7, 7]);
        await File.WriteAllBytesAsync(Path.Combine(binDir, companionName), [8, 8, 8]);

        var payload = CreateZip(
            ("nested/" + exeName, [1, 2, 3]),
            ("nested/" + companionName, [4, 5, 6]));
        var downloader = CreateDownloader(payload);
        var info = downloader.GetToolDownloadInfo("ffmpeg");
        info.Should().NotBeNull();
        info!.ExpectedChecksum = Sha256(payload);
        SetAllPlatformUrls(info, "https://example.test/ffmpeg.zip");

        var result = await downloader.DownloadToolAsync("ffmpeg");

        result.Success.Should().BeTrue();
        File.ReadAllBytes(Path.Combine(binDir, exeName)).Should().Equal([1, 2, 3]);
        File.ReadAllBytes(Path.Combine(binDir, companionName)).Should().Equal([4, 5, 6]);

        var rollbackDirs = Directory.GetDirectories(Path.Combine(_toolsBasePath, "rollback", "ffmpeg"));
        rollbackDirs.Should().ContainSingle();
        File.ReadAllBytes(Path.Combine(rollbackDirs[0], exeName)).Should().Equal([7, 7, 7]);
        File.ReadAllBytes(Path.Combine(rollbackDirs[0], companionName)).Should().Equal([8, 8, 8]);
        File.Exists(Path.Combine(rollbackDirs[0], "manifest.json")).Should().BeTrue();
    }

    [Fact]
    public async Task DownloadToolAsync_WithExactGitHubAsset_ShouldVerifyDigestAndPromote()
    {
        var payload = new byte[] { 7, 6, 5, 4 };
        var assetName = OperatingSystem.IsWindows() ? "yt-dlp.exe" : "yt-dlp";
        var assetUrl = $"https://github.com/yt-dlp/yt-dlp/releases/download/2099.01.01/{assetName}";
        var releaseJson = $$"""
            {
              "tag_name": "2099.01.01",
              "assets": [
                {
                  "name": "{{assetName}}",
                  "browser_download_url": "{{assetUrl}}",
                  "digest": "sha256:{{Sha256(payload)}}"
                }
              ]
            }
            """;
        var downloader = CreateDownloader(new ReleasePayloadHandler(releaseJson, payload));
        var info = downloader.GetToolDownloadInfo("yt-dlp");
        info.Should().NotBeNull();
        info!.RequireReleaseVersionMatch = false;
        info.AssetNames = info.AssetNames!.Keys.ToDictionary(key => key, _ => assetName);

        var result = await downloader.DownloadToolAsync("yt-dlp");

        result.Success.Should().BeTrue(result.ErrorMessage);
        File.ReadAllBytes(ExpectedToolPath("yt-dlp")).Should().Equal(payload);
    }

    [Theory]
    [InlineData("yt-dlp 2026.07.04", "2026.07.04", true)]
    [InlineData("2026.07.04\r\n", "2026.07.04", true)]
    [InlineData("deno 2.9.3", "v2.9.3", true)]
    [InlineData("deno 2.2.0", "v2.9.3", false)]
    [InlineData("not a version", "v2.9.3", false)]
    public void ReleaseVersionMatches_ShouldRequireExactParsedVersion(
        string reported,
        string release,
        bool expected)
    {
        ToolDownloader.ReleaseVersionMatches(reported, release).Should().Be(expected);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_toolsBasePath))
                Directory.Delete(_toolsBasePath, recursive: true);
        }
        catch { }
    }

    private ToolDownloader CreateDownloader(byte[] payload)
    {
        var options = Options.Create(new ConverterXOptions
        {
            ToolsBasePath = _toolsBasePath,
            SearchSystemTools = false,
        });
        return new ToolDownloader(options, new HttpClient(new StaticPayloadHandler(payload)));
    }

    private ToolDownloader CreateDownloader(HttpMessageHandler handler)
    {
        var options = Options.Create(new ConverterXOptions
        {
            ToolsBasePath = _toolsBasePath,
            SearchSystemTools = false,
        });
        return new ToolDownloader(options, new HttpClient(handler));
    }

    private static byte[] CreateZip(params (string Name, byte[] Content)[] entries)
    {
        using var stream = new MemoryStream();
        using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, leaveOpen: true))
        {
            foreach (var (name, content) in entries)
            {
                var entry = archive.CreateEntry(name);
                using var entryStream = entry.Open();
                entryStream.Write(content);
            }
        }
        return stream.ToArray();
    }

    private static string Sha256(byte[] payload)
    {
        var hash = SHA256.HashData(payload);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private string ExpectedToolPath(string executableName)
    {
        var exeName = executableName + (OperatingSystem.IsWindows() ? ".exe" : "");
        return Path.Combine(_toolsBasePath, "bin", exeName);
    }

    private static void SetAllPlatformUrls(ToolDownloadInfo info, string url)
    {
        info.PlatformUrls = new Dictionary<string, string>
        {
            ["windows-x64"] = url,
            ["windows-arm64"] = url,
            ["linux-x64"] = url,
            ["linux-arm64"] = url,
            ["macos-x64"] = url,
            ["macos-arm64"] = url,
            ["windows"] = url,
            ["linux"] = url,
            ["macos"] = url,
        };
    }

    private sealed class StaticPayloadHandler(byte[] payload) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var response = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new ByteArrayContent(payload)
            };
            response.Content.Headers.ContentLength = payload.Length;
            return Task.FromResult(response);
        }
    }

    private sealed class ReleasePayloadHandler(string releaseJson, byte[] payload) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            HttpContent content = request.RequestUri!.AbsolutePath.EndsWith("/releases/latest", StringComparison.Ordinal)
                ? new StringContent(releaseJson, Encoding.UTF8, "application/json")
                : new ByteArrayContent(payload);
            var response = new HttpResponseMessage(HttpStatusCode.OK) { Content = content };
            content.Headers.ContentLength ??= content is ByteArrayContent ? payload.Length : null;
            return Task.FromResult(response);
        }
    }
}
