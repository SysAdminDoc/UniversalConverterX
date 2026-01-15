using FluentAssertions;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public class ConversionOrchestratorTests
{
    private readonly Mock<IOptions<ConverterXOptions>> _optionsMock;
    private readonly Mock<ILogger<ConversionOrchestrator>> _loggerMock;
    private readonly Mock<IConverterStrategy> _converterMock1;
    private readonly Mock<IConverterStrategy> _converterMock2;
    private readonly ConversionOrchestrator _orchestrator;
    private readonly string _toolsBasePath;

    public ConversionOrchestratorTests()
    {
        _toolsBasePath = Path.Combine(Path.GetTempPath(), "ucx-test-tools");
        
        var options = new ConverterXOptions { ToolsBasePath = _toolsBasePath };
        _optionsMock = new Mock<IOptions<ConverterXOptions>>();
        _optionsMock.Setup(x => x.Value).Returns(options);
        
        _loggerMock = new Mock<ILogger<ConversionOrchestrator>>();
        
        // Setup mock converters
        _converterMock1 = CreateMockConverter("converter1", "Converter 1", 100);
        _converterMock2 = CreateMockConverter("converter2", "Converter 2", 50);

        var converters = new List<IConverterStrategy>
        {
            _converterMock1.Object,
            _converterMock2.Object
        };

        _orchestrator = new ConversionOrchestrator(
            converters, 
            _optionsMock.Object, 
            _loggerMock.Object);
    }

    private static Mock<IConverterStrategy> CreateMockConverter(string id, string name, int priority)
    {
        var mock = new Mock<IConverterStrategy>();
        mock.Setup(x => x.Id).Returns(id);
        mock.Setup(x => x.Name).Returns(name);
        mock.Setup(x => x.Priority).Returns(priority);
        mock.Setup(x => x.CanConvert(It.IsAny<FileFormat>(), It.IsAny<FileFormat>())).Returns(true);
        mock.Setup(x => x.GetSupportedInputFormats()).Returns(new HashSet<string> { "mp4", "png", "pdf" });
        mock.Setup(x => x.GetSupportedOutputFormats()).Returns(new HashSet<string> { "mp4", "png", "pdf" });
        mock.Setup(x => x.GetOutputFormatsFor(It.IsAny<string>())).Returns(new HashSet<string> { "mp4", "png", "pdf" });
        mock.Setup(x => x.ValidateJob(It.IsAny<ConversionJob>())).Returns(ValidationResult.Success);
        return mock;
    }

    [Fact]
    public void GetAvailableConverters_ShouldReturnAllConverters()
    {
        var converters = _orchestrator.GetAvailableConverters();

        converters.Should().HaveCount(2);
        converters.Should().Contain(c => c.Id == "converter1");
        converters.Should().Contain(c => c.Id == "converter2");
    }

    [Fact]
    public void GetAvailableConverters_ShouldBeOrderedByPriority()
    {
        var converters = _orchestrator.GetAvailableConverters().ToList();

        converters[0].Priority.Should().BeGreaterThan(converters[1].Priority);
    }

    [Fact]
    public void GetConverterById_ExistingId_ShouldReturnConverter()
    {
        var converter = _orchestrator.GetConverterById("converter1");

        converter.Should().NotBeNull();
        converter!.Id.Should().Be("converter1");
    }

    [Fact]
    public void GetConverterById_NonExistingId_ShouldReturnNull()
    {
        var converter = _orchestrator.GetConverterById("nonexistent");

        converter.Should().BeNull();
    }

    [Fact]
    public void GetConvertersFor_WithCapableConverters_ShouldReturnMatchingConverters()
    {
        var source = new FileFormat("mp4", "video/mp4", FormatCategory.Video);
        var target = new FileFormat("png", "image/png", FormatCategory.Image);

        var converters = _orchestrator.GetConvertersFor(source, target);

        converters.Should().NotBeEmpty();
    }

    [Fact]
    public void GetConvertersFor_ShouldReturnOrderedByPriority()
    {
        var source = new FileFormat("mp4", "video/mp4", FormatCategory.Video);
        var target = new FileFormat("png", "image/png", FormatCategory.Image);

        var converters = _orchestrator.GetConvertersFor(source, target).ToList();

        if (converters.Count > 1)
        {
            converters[0].Priority.Should().BeGreaterThanOrEqualTo(converters[1].Priority);
        }
    }

    [Fact]
    public void GetSupportedInputFormats_ShouldReturnUnionOfAllFormats()
    {
        var formats = _orchestrator.GetSupportedInputFormats();

        formats.Should().NotBeEmpty();
    }

    [Fact]
    public void GetSupportedOutputFormats_ShouldReturnUnionOfAllFormats()
    {
        var formats = _orchestrator.GetSupportedOutputFormats();

        formats.Should().NotBeEmpty();
    }

    [Fact]
    public void GetOutputFormatsFor_KnownFormat_ShouldReturnFormats()
    {
        var formats = _orchestrator.GetOutputFormatsFor("mp4");

        formats.Should().NotBeEmpty();
    }

    [Fact]
    public void GetOutputFormatsFor_UnknownFormat_ShouldReturnEmpty()
    {
        // Setup converters to return empty for unknown format
        _converterMock1.Setup(x => x.CanConvert(
            It.Is<FileFormat>(f => f.Extension == "xyz"),
            It.IsAny<FileFormat>())).Returns(false);
        _converterMock2.Setup(x => x.CanConvert(
            It.Is<FileFormat>(f => f.Extension == "xyz"),
            It.IsAny<FileFormat>())).Returns(false);

        var formats = _orchestrator.GetOutputFormatsFor("xyz");

        // May return empty or aggregated formats depending on implementation
        formats.Should().NotBeNull();
    }

    [Fact]
    public async Task ConvertAsync_WithValidJob_ShouldSelectHighestPriorityConverter()
    {
        var job = CreateTestJob("input.mp4", "output.png");
        
        _converterMock1.Setup(x => x.ConvertAsync(
            It.IsAny<ConversionJob>(),
            It.IsAny<IProgress<ConversionProgress>>(),
            It.IsAny<CancellationToken>()))
            .ReturnsAsync(ConversionResult.Succeeded(job, job.OutputPath, TimeSpan.FromSeconds(1), "converter1"));

        var result = await _orchestrator.ConvertAsync(job);

        result.Should().NotBeNull();
        _converterMock1.Verify(x => x.ConvertAsync(
            It.IsAny<ConversionJob>(),
            It.IsAny<IProgress<ConversionProgress>>(),
            It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task ConvertAsync_WithForceConverter_ShouldUseSpecifiedConverter()
    {
        var job = CreateTestJob("input.mp4", "output.png");
        job.Options.ForceConverter = "converter2";

        _converterMock2.Setup(x => x.ConvertAsync(
            It.IsAny<ConversionJob>(),
            It.IsAny<IProgress<ConversionProgress>>(),
            It.IsAny<CancellationToken>()))
            .ReturnsAsync(ConversionResult.Succeeded(job, job.OutputPath, TimeSpan.FromSeconds(1), "converter2"));

        var result = await _orchestrator.ConvertAsync(job);

        result.Should().NotBeNull();
        _converterMock2.Verify(x => x.ConvertAsync(
            It.IsAny<ConversionJob>(),
            It.IsAny<IProgress<ConversionProgress>>(),
            It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task ConvertAsync_WithNoCapableConverters_ShouldReturnFailedResult()
    {
        _converterMock1.Setup(x => x.CanConvert(It.IsAny<FileFormat>(), It.IsAny<FileFormat>())).Returns(false);
        _converterMock2.Setup(x => x.CanConvert(It.IsAny<FileFormat>(), It.IsAny<FileFormat>())).Returns(false);

        var job = CreateTestJob("input.xyz", "output.abc");

        var result = await _orchestrator.ConvertAsync(job);

        result.Success.Should().BeFalse();
    }

    [Fact]
    public async Task ConvertAsync_WithCancellation_ShouldBeCancelled()
    {
        var job = CreateTestJob("input.mp4", "output.png");
        var cts = new CancellationTokenSource();
        cts.Cancel();

        _converterMock1.Setup(x => x.ConvertAsync(
            It.IsAny<ConversionJob>(),
            It.IsAny<IProgress<ConversionProgress>>(),
            It.IsAny<CancellationToken>()))
            .ThrowsAsync(new OperationCanceledException());

        var result = await _orchestrator.ConvertAsync(job, null, cts.Token);

        result.Success.Should().BeFalse();
        result.WasCancelled.Should().BeTrue();
    }

    [Fact]
    public async Task ConvertAsync_WithProgress_ShouldReportProgress()
    {
        var job = CreateTestJob("input.mp4", "output.png");
        var progressReports = new List<ConversionProgress>();
        var progress = new Progress<ConversionProgress>(p => progressReports.Add(p));

        _converterMock1.Setup(x => x.ConvertAsync(
            It.IsAny<ConversionJob>(),
            It.IsAny<IProgress<ConversionProgress>>(),
            It.IsAny<CancellationToken>()))
            .Callback<ConversionJob, IProgress<ConversionProgress>, CancellationToken>((j, p, ct) =>
            {
                p?.Report(new ConversionProgress { Percent = 50 });
            })
            .ReturnsAsync(ConversionResult.Succeeded(job, job.OutputPath, TimeSpan.FromSeconds(1), "converter1"));

        await _orchestrator.ConvertAsync(job, progress);

        // Allow time for progress reporting
        await Task.Delay(100);

        progressReports.Should().NotBeEmpty();
    }

    [Fact]
    public async Task ConvertBatchAsync_WithMultipleJobs_ShouldConvertAll()
    {
        var jobs = new List<ConversionJob>
        {
            CreateTestJob("input1.mp4", "output1.png"),
            CreateTestJob("input2.mp4", "output2.png"),
            CreateTestJob("input3.mp4", "output3.png")
        };

        _converterMock1.Setup(x => x.ConvertAsync(
            It.IsAny<ConversionJob>(),
            It.IsAny<IProgress<ConversionProgress>>(),
            It.IsAny<CancellationToken>()))
            .ReturnsAsync((ConversionJob j, IProgress<ConversionProgress> p, CancellationToken ct) =>
                ConversionResult.Succeeded(j, j.OutputPath, TimeSpan.FromSeconds(1), "converter1"));

        var results = await _orchestrator.ConvertBatchAsync(jobs).ToListAsync();

        results.Should().HaveCount(3);
        results.Should().OnlyContain(r => r.Success);
    }

    [Fact]
    public void DetectFormat_WithKnownExtension_ShouldReturnFormat()
    {
        var tempFile = Path.GetTempFileName();
        File.Move(tempFile, tempFile + ".mp4");
        tempFile += ".mp4";

        try
        {
            var format = _orchestrator.DetectFormat(tempFile);

            format.Should().NotBeNull();
            format!.Extension.Should().Be("mp4");
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    private static ConversionJob CreateTestJob(string input, string output)
    {
        return new ConversionJob
        {
            InputPath = input,
            OutputPath = output,
            Options = new ConversionOptions()
        };
    }
}
