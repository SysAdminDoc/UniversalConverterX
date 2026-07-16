using System.Diagnostics;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;

namespace UniversalConverterX.FfmpegProxy;

internal static class Program
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private static readonly char[] ForbiddenShellCharacters = ['&', '|', ';', '<', '>', '`', '\r', '\n', '\0'];

    public static async Task<int> Main(string[] args)
    {
        try
        {
            var pipeName = Environment.GetEnvironmentVariable("UCX_FFMPEG_PIPE");
            var realFfmpeg = Environment.GetEnvironmentVariable("UCX_REAL_FFMPEG");
            if (!IsValidPipeName(pipeName)
                || string.IsNullOrWhiteSpace(realFfmpeg)
                || !File.Exists(realFfmpeg))
            {
                Console.Error.WriteLine("UCX FFmpeg review proxy is missing its trusted pipe or real executable path.");
                return 2;
            }

            if (args.Length == 0 || args.Length > 4096 || args.Sum(argument => argument.Length) > 30_000)
            {
                Console.Error.WriteLine("UCX FFmpeg review proxy rejected an invalid argument vector size.");
                return 2;
            }

            using var pipe = new NamedPipeClientStream(
                ".",
                pipeName!,
                PipeDirection.InOut,
                PipeOptions.Asynchronous);
            await pipe.ConnectAsync(30_000, CancellationToken.None).ConfigureAwait(false);

            using var reader = new StreamReader(pipe, new UTF8Encoding(false), leaveOpen: true);
            using var writer = new StreamWriter(pipe, new UTF8Encoding(false), leaveOpen: true)
            {
                AutoFlush = true,
            };
            await writer.WriteLineAsync(JsonSerializer.Serialize(
                new ReviewRequest(Environment.ProcessId, args),
                JsonOptions)).ConfigureAwait(false);

            var responseLine = await reader.ReadLineAsync().ConfigureAwait(false);
            var response = string.IsNullOrWhiteSpace(responseLine)
                ? null
                : JsonSerializer.Deserialize<ReviewResponse>(responseLine, JsonOptions);
            if (response is null || !response.Approved)
            {
                if (!string.IsNullOrWhiteSpace(response?.Error))
                    Console.Error.WriteLine(response.Error);
                return 1223;
            }

            if (!ValidateResponseArguments(response.Arguments, args, out var validationError))
            {
                Console.Error.WriteLine(validationError);
                return 2;
            }

            var startInfo = new ProcessStartInfo
            {
                FileName = Path.GetFullPath(realFfmpeg),
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            foreach (var argument in response.Arguments!)
                startInfo.ArgumentList.Add(argument);

            using var process = Process.Start(startInfo);
            if (process is null)
            {
                Console.Error.WriteLine("UCX FFmpeg review proxy could not start the real FFmpeg executable.");
                return 2;
            }

            await process.WaitForExitAsync().ConfigureAwait(false);
            return process.ExitCode;
        }
        catch (TimeoutException)
        {
            Console.Error.WriteLine("UCX FFmpeg command review did not become available within 30 seconds.");
            return 2;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"UCX FFmpeg review proxy failed: {exception.Message}");
            return 2;
        }
    }

    private static bool ValidateResponseArguments(
        string[]? reviewed,
        IReadOnlyList<string> original,
        out string? error)
    {
        error = null;
        if (reviewed is null
            || reviewed.Length == 0
            || reviewed.Length > 4096
            || reviewed.Any(string.IsNullOrEmpty)
            || reviewed.Sum(argument => argument.Length) > 30_000)
        {
            error = "UCX FFmpeg review returned an invalid argument vector.";
            return false;
        }

        if (reviewed.Any(argument =>
                argument.IndexOfAny(ForbiddenShellCharacters) >= 0
                && !original.Contains(argument, StringComparer.Ordinal)))
        {
            error = "UCX FFmpeg review attempted to introduce a forbidden shell metacharacter.";
            return false;
        }

        return true;
    }

    private static bool IsValidPipeName(string? value) =>
        !string.IsNullOrWhiteSpace(value)
        && value.StartsWith("ucx-ffmpeg-", StringComparison.Ordinal)
        && value.Length == "ucx-ffmpeg-".Length + 32
        && value["ucx-ffmpeg-".Length..].All(char.IsAsciiHexDigit);

    private sealed record ReviewRequest(int ProcessId, string[] Arguments);

    private sealed record ReviewResponse(bool Approved, string[]? Arguments, string? Error);
}
