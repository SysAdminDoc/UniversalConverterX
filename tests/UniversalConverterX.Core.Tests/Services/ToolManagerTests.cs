using FluentAssertions;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public class ToolManagerTests
{
    private readonly Mock<IOptions<ConverterXOptions>> _optionsMock;
    private readonly Mock<ILogger<ToolManager>> _loggerMock;
    private readonly string _toolsBasePath;
    private readonly ToolManager _toolManager;

    public ToolManagerTests()
    {
        _toolsBasePath = Path.Combine(Path.GetTempPath(), "ucx-test-tools");

        var options = new ConverterXOptions
        {
            ToolsBasePath = _toolsBasePath,
            SearchSystemTools = false
        };
        _optionsMock = new Mock<IOptions<ConverterXOptions>>();
        _optionsMock.Setup(x => x.Value).Returns(options);

        _loggerMock = new Mock<ILogger<ToolManager>>();

        _toolManager = new ToolManager(_optionsMock.Object, _loggerMock.Object);
    }

    [Fact]
    public void ToolsBasePath_ShouldReturnConfiguredPath()
    {
        _toolManager.ToolsBasePath.Should().Be(_toolsBasePath);
    }

    [Theory]
    [InlineData("ffmpeg")]
    [InlineData("imagemagick")]
    [InlineData("pandoc")]
    [InlineData("calibre")]
    [InlineData("libreoffice")]
    [InlineData("7zip")]
    [InlineData("inkscape")]
    [InlineData("ghostscript")]
    public void GetToolPath_KnownTool_ShouldReturnPath(string toolName)
    {
        var path = _toolManager.GetToolPath(toolName);

        path.Should().NotBeNullOrEmpty();
        path.Should().StartWith(_toolsBasePath);
        path.Should().Contain(toolName == "imagemagick" ? "magick" :
                             toolName == "ghostscript" ? "gs" :
                             toolName == "calibre" ? "ebook-convert" :
                             toolName == "libreoffice" ? "soffice" :
                             toolName == "7zip" ? "7z" :
                             toolName);
    }

    [Fact]
    public void GetToolPath_UnknownTool_ShouldThrowArgumentException()
    {
        var action = () => _toolManager.GetToolPath("unknown-tool");

        action.Should().Throw<ArgumentException>();
    }

    [Fact]
    public void IsToolAvailable_NonExistentTool_ShouldReturnFalse()
    {
        var result = _toolManager.IsToolAvailable("ffmpeg");

        result.Should().BeFalse();
    }

    [Fact]
    public void IsToolAvailable_ExistentTool_ShouldReturnTrue()
    {
        // Create a fake tool in the tools directory
        var binDir = Path.Combine(_toolsBasePath, "bin");
        Directory.CreateDirectory(binDir);

        var toolPath = Path.Combine(binDir, OperatingSystem.IsWindows() ? "ffmpeg.exe" : "ffmpeg");
        File.WriteAllText(toolPath, "fake executable");

        try
        {
            var result = _toolManager.IsToolAvailable("ffmpeg");
            result.Should().BeTrue();
        }
        finally
        {
            if (File.Exists(toolPath))
                File.Delete(toolPath);
        }
    }

    [Fact]
    public async Task GetToolVersionAsync_NonExistentTool_ShouldReturnNull()
    {
        var version = await _toolManager.GetToolVersionAsync("ffmpeg");

        version.Should().BeNull();
    }

    [Fact]
    public void GetAvailableTools_ShouldReturnAllKnownTools()
    {
        var tools = _toolManager.GetAvailableTools();

        tools.Should().NotBeEmpty();
        tools.Should().Contain(t => t.Id == "ffmpeg");
        tools.Should().Contain(t => t.Id == "imagemagick");
        tools.Should().Contain(t => t.Id == "pandoc");
        tools.Should().Contain(t => t.Id == "calibre");
        tools.Should().Contain(t => t.Id == "libreoffice");
        tools.Should().Contain(t => t.Id == "7zip");
        tools.Should().Contain(t => t.Id == "inkscape");
        tools.Should().Contain(t => t.Id == "ghostscript");
        tools.Should().Contain(t => t.Id == "yt-dlp");
        tools.Should().Contain(t => t.Id == "deno");
    }

    [Fact]
    public void GetAvailableTools_ShouldIncludeToolDetails()
    {
        var tools = _toolManager.GetAvailableTools();
        var ffmpeg = tools.FirstOrDefault(t => t.Id == "ffmpeg");

        ffmpeg.Should().NotBeNull();
        ffmpeg!.Name.Should().Be("FFmpeg");
        ffmpeg.ExecutableName.Should().Be("ffmpeg");
        ffmpeg.Description.Should().NotBeNullOrEmpty();
    }

    [Fact]
    public async Task VerifyToolIntegrityAsync_NonExistentTool_ShouldReturnFalse()
    {
        var result = await _toolManager.VerifyToolIntegrityAsync("ffmpeg");

        result.Should().BeFalse();
    }

    [Fact]
    public async Task DownloadToolAsync_WithoutConfiguredDownloader_ShouldReturnFailure()
    {
        var result = await _toolManager.DownloadToolAsync("ffmpeg");

        result.Success.Should().BeFalse();
        result.ErrorMessage.Should().NotBeNullOrEmpty();
    }

    [Fact]
    public async Task DownloadToolAsync_WithConfiguredDownloader_ShouldDelegate()
    {
        var expected = new ToolDownloadResult(true, "ffmpeg", "1.0.0", null);
        var downloader = new RecordingToolDownloader(expected);
        var manager = new ToolManager(_optionsMock.Object, downloader);

        var result = await manager.DownloadToolAsync("ffmpeg");

        result.Should().Be(expected);
        downloader.ToolName.Should().Be("ffmpeg");
    }

    [Fact]
    public void GetToolPath_CaseInsensitive_ShouldWork()
    {
        var path1 = _toolManager.GetToolPath("FFmpeg");
        var path2 = _toolManager.GetToolPath("ffmpeg");
        var path3 = _toolManager.GetToolPath("FFMPEG");

        path1.Should().Be(path2);
        path2.Should().Be(path3);
    }

    private sealed class RecordingToolDownloader(ToolDownloadResult result) : IToolDownloader
    {
        public string? ToolName { get; private set; }

        public Task<ToolDownloadResult> DownloadToolAsync(
            string toolName,
            IProgress<DownloadProgress>? progress = null,
            CancellationToken cancellationToken = default)
        {
            ToolName = toolName;
            return Task.FromResult(result);
        }

        public Task<IReadOnlyList<ToolDownloadResult>> DownloadToolsAsync(
            IEnumerable<string> toolNames,
            IProgress<BatchDownloadProgress>? progress = null,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<ToolDownloadResult>>([result]);

        public Task<ToolUpdateInfo?> CheckForUpdateAsync(
            string toolName,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<ToolUpdateInfo?>(null);

        public ToolDownloadInfo? GetToolDownloadInfo(string toolName) => null;

        public IReadOnlyList<string> GetDownloadableTools() => [];
    }
}
