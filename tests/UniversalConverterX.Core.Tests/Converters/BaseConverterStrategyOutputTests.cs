using FluentAssertions;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Tests.Converters;

public sealed class BaseConverterStrategyOutputTests : IDisposable
{
    private readonly string _tempDir;
    private readonly string _scriptPath;

    public BaseConverterStrategyOutputTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "ucx-output-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tempDir);

        _scriptPath = Path.Combine(_tempDir, "fake-converter.ps1");
        File.WriteAllText(_scriptPath, """
            param([string]$Mode, [string]$OutputPath)

            if ($Mode -eq 'write') {
                Set-Content -LiteralPath $OutputPath -Value 'converted' -NoNewline
                exit 0
            }

            if ($Mode -eq 'empty') {
                New-Item -ItemType File -Force -Path $OutputPath | Out-Null
                Clear-Content -LiteralPath $OutputPath
                exit 0
            }

            if ($Mode -eq 'missing') {
                exit 0
            }

            Write-Error 'forced failure'
            exit 2
            """);
    }

    [Fact]
    public async Task ConvertAsync_WhenProcessCreatesOutput_ReturnsSuccess()
    {
        var converter = new FakeConverterStrategy(_scriptPath, "write");
        var job = CreateJob();

        var result = await converter.ConvertAsync(job);

        result.Success.Should().BeTrue();
        result.OutputPath.Should().Be(job.OutputPath);
        result.OutputSize.Should().BeGreaterThan(0);
        job.OutputFileSize.Should().BeGreaterThan(0);
        job.Status.Should().Be(ConversionStatus.Completed);
    }

    [Fact]
    public async Task ConvertAsync_WhenOutputIsMissing_ReturnsActionableFailure()
    {
        var converter = new FakeConverterStrategy(_scriptPath, "missing");
        var job = CreateJob();

        var result = await converter.ConvertAsync(job);

        result.Success.Should().BeFalse();
        result.ErrorMessage.Should().Contain("did not create the expected output file");
        result.ExitCode.Should().Be(0);
        job.OutputFileSize.Should().Be(0);
        job.Status.Should().Be(ConversionStatus.Failed);
    }

    [Fact]
    public async Task ConvertAsync_WhenOutputIsZeroBytes_ReturnsActionableFailure()
    {
        var converter = new FakeConverterStrategy(_scriptPath, "empty");
        var job = CreateJob();

        var result = await converter.ConvertAsync(job);

        result.Success.Should().BeFalse();
        result.ErrorMessage.Should().Contain("empty output file");
        result.ExitCode.Should().Be(0);
        job.OutputFileSize.Should().Be(0);
        job.Status.Should().Be(ConversionStatus.Failed);
    }

    [Fact]
    public async Task ConvertAsync_WhenConverterOptsOutOfFileOutput_AllowsMissingOutput()
    {
        var converter = new FakeConverterStrategy(_scriptPath, "missing", requiresOutputFile: false);
        var job = CreateJob();

        var result = await converter.ConvertAsync(job);

        result.Success.Should().BeTrue();
        result.OutputSize.Should().Be(0);
        job.Status.Should().Be(ConversionStatus.Completed);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempDir))
            Directory.Delete(_tempDir, recursive: true);
    }

    private ConversionJob CreateJob()
    {
        var inputPath = Path.Combine(_tempDir, Guid.NewGuid().ToString("N") + ".source");
        var outputPath = Path.Combine(_tempDir, Guid.NewGuid().ToString("N") + ".target");
        File.WriteAllText(inputPath, "input");

        return new ConversionJob
        {
            InputPath = inputPath,
            OutputPath = outputPath,
            Options = new ConversionOptions()
        };
    }

    private sealed class FakeConverterStrategy : BaseConverterStrategy
    {
        private readonly string _scriptPath;
        private readonly string _mode;
        private readonly bool _requiresOutputFile;

        public FakeConverterStrategy(string scriptPath, string mode, bool requiresOutputFile = true)
            : base(Path.GetDirectoryName(scriptPath)!)
        {
            _scriptPath = scriptPath;
            _mode = mode;
            _requiresOutputFile = requiresOutputFile;
        }

        public override string Id => "fake";
        public override string Name => "Fake";
        public override int Priority => 1;
        public override string ExecutableName => "powershell";

        protected override bool RequiresOutputFile => _requiresOutputFile;

        protected override HashSet<string> SupportedInputFormats { get; } = ["source"];
        protected override HashSet<string> SupportedOutputFormats { get; } = ["target"];
        protected override Dictionary<string, HashSet<string>> FormatMappings { get; } = [];

        public override string[] BuildArguments(ConversionJob job, ConversionOptions options) =>
        [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            _scriptPath,
            _mode,
            job.OutputPath
        ];

        public override ConversionProgress? ParseProgress(string outputLine, ConversionJob job) => null;

        protected override string GetExecutablePath() =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
    }
}
