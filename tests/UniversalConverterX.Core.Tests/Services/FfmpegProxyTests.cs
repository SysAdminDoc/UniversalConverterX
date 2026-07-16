using System.Diagnostics;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using FluentAssertions;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class FfmpegProxyTests
{
    [Fact]
    public async Task Proxy_ShouldDispatchReviewedArgumentVectorWithoutShell()
    {
        var result = await RunProxyAsync(["--version"]);

        result.ExitCode.Should().Be(0, result.StandardError);
        result.RequestArguments.Should().Equal("--definitely-not-a-dotnet-option");
    }

    [Fact]
    public async Task Proxy_ShouldRejectIntroducedShellMetacharacters()
    {
        var result = await RunProxyAsync(["--version", ";"]);

        result.ExitCode.Should().Be(2);
        result.StandardError.Should().Contain("forbidden shell metacharacter");
    }

    private static async Task<ProxyResult> RunProxyAsync(string[] reviewedArguments)
    {
        var pipeName = $"ucx-ffmpeg-{Guid.NewGuid():N}";
        await using var server = new NamedPipeServerStream(
            pipeName,
            PipeDirection.InOut,
            1,
            PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);

        var startInfo = new ProcessStartInfo
        {
            FileName = FindProxy(),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        startInfo.ArgumentList.Add("--definitely-not-a-dotnet-option");
        startInfo.Environment["UCX_FFMPEG_PIPE"] = pipeName;
        startInfo.Environment["UCX_REAL_FFMPEG"] = FindDotnet();

        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("Could not start FFmpeg review proxy test process.");
        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        await server.WaitForConnectionAsync(timeout.Token);

        using var reader = new StreamReader(server, new UTF8Encoding(false), leaveOpen: true);
        using var writer = new StreamWriter(server, new UTF8Encoding(false), leaveOpen: true)
        {
            AutoFlush = true,
        };
        var requestLine = await reader.ReadLineAsync(timeout.Token);
        using var request = JsonDocument.Parse(requestLine!);
        var requestArguments = request.RootElement
            .GetProperty("arguments")
            .EnumerateArray()
            .Select(element => element.GetString()!)
            .ToArray();

        await writer.WriteLineAsync(JsonSerializer.Serialize(new
        {
            approved = true,
            arguments = reviewedArguments,
            error = (string?)null,
        }));
        await process.WaitForExitAsync(timeout.Token);

        return new ProxyResult(
            process.ExitCode,
            await stdoutTask,
            await stderrTask,
            requestArguments);
    }

    private static string FindProxy()
    {
        var root = FindRepositoryRoot();
        var executable = OperatingSystem.IsWindows() ? "ffmpeg.exe" : "ffmpeg";
        var bin = Path.Combine(root, "src", "UniversalConverterX.FfmpegProxy", "bin");
        return Directory
            .EnumerateFiles(bin, executable, SearchOption.AllDirectories)
            .OrderByDescending(path => path.Contains(
                $"{Path.DirectorySeparatorChar}Release{Path.DirectorySeparatorChar}",
                StringComparison.OrdinalIgnoreCase))
            .ThenByDescending(File.GetLastWriteTimeUtc)
            .First();
    }

    private static string FindDotnet()
    {
        var executable = OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet";
        foreach (var directory in (Environment.GetEnvironmentVariable("PATH") ?? "")
                     .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            var candidate = Path.Combine(directory.Trim(), executable);
            if (File.Exists(candidate))
                return candidate;
        }

        throw new FileNotFoundException("dotnet executable was not found on PATH.");
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "src", "UniversalConverterX.sln")))
                return directory.FullName;
            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("UniversalConverterX repository root was not found.");
    }

    private sealed record ProxyResult(
        int ExitCode,
        string StandardOutput,
        string StandardError,
        string[] RequestArguments);
}
