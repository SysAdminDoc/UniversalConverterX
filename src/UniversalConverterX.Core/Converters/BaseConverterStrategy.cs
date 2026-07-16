using System.Diagnostics;
using System.Text;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// Abstract base class for converter strategies that wrap CLI tools
/// </summary>
public abstract class BaseConverterStrategy : IConverterStrategy
{
    protected readonly ILogger? Logger;
    protected readonly string ToolsBasePath;

    protected BaseConverterStrategy(string toolsBasePath, ILogger? logger = null)
    {
        ToolsBasePath = toolsBasePath;
        Logger = logger;
    }

    public abstract string Id { get; }
    public abstract string Name { get; }
    public abstract int Priority { get; }
    public abstract string ExecutableName { get; }

    protected abstract HashSet<string> SupportedInputFormats { get; }
    protected abstract HashSet<string> SupportedOutputFormats { get; }
    protected abstract Dictionary<string, HashSet<string>> FormatMappings { get; }

    protected virtual bool RequiresOutputFile => true;
    protected virtual bool AllowsEmptyOutputFile => false;

    public virtual bool CanConvert(FileFormat source, FileFormat target)
    {
        var inputExt = source.Extension.ToLowerInvariant().TrimStart('.');
        var outputExt = target.Extension.ToLowerInvariant().TrimStart('.');

        if (!SupportedInputFormats.Contains(inputExt))
            return false;

        if (!SupportedOutputFormats.Contains(outputExt))
            return false;

        // Check specific mappings if defined
        if (FormatMappings.TryGetValue(inputExt, out var outputs))
            return outputs.Contains(outputExt);

        // Default: allow any supported input to any supported output
        return true;
    }

    public IReadOnlyCollection<string> GetSupportedInputFormats() => SupportedInputFormats;
    public IReadOnlyCollection<string> GetSupportedOutputFormats() => SupportedOutputFormats;

    public virtual IReadOnlyCollection<string> GetOutputFormatsFor(string inputExtension)
    {
        var ext = inputExtension.ToLowerInvariant().TrimStart('.');
        
        if (!SupportedInputFormats.Contains(ext))
            return [];

        if (FormatMappings.TryGetValue(ext, out var outputs))
            return outputs;

        return SupportedOutputFormats;
    }

    public abstract string[] BuildArguments(ConversionJob job, ConversionOptions options);
    public abstract ConversionProgress? ParseProgress(string outputLine, ConversionJob job);

    public virtual ValidationResult ValidateJob(ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(job.InputPath))
            return ValidationResult.Fail("Input path is required");

        if (string.IsNullOrWhiteSpace(job.OutputPath))
            return ValidationResult.Fail("Output path is required");

        if (!File.Exists(job.InputPath))
            return ValidationResult.Fail($"Input file not found: {job.InputPath}");

        if (!job.Options.OverwriteExisting && File.Exists(job.OutputPath))
            return ValidationResult.Fail($"Output file already exists: {job.OutputPath}");

        var inputExtension = NormalizeExtension(job.SourceFormat?.Extension ?? job.InputExtension);
        var outputExtension = NormalizeExtension(job.TargetFormat?.Extension ?? job.OutputExtension);

        if (!SupportedInputFormats.Contains(inputExtension))
            return ValidationResult.Fail($"Unsupported input format: {inputExtension}");

        if (!SupportedOutputFormats.Contains(outputExtension))
            return ValidationResult.Fail($"Unsupported output format: {outputExtension}");

        return ValidationResult.Success;
    }

    public virtual async Task<ConversionResult> ConvertAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var stopwatch = Stopwatch.StartNew();
        var warnings = new List<string>();
        using var timeoutCts = job.Options.Timeout is TimeSpan timeout && timeout > TimeSpan.Zero
            ? new CancellationTokenSource(timeout)
            : null;
        using var linkedCts = timeoutCts is null
            ? null
            : CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeoutCts.Token);
        var effectiveCancellationToken = linkedCts?.Token ?? cancellationToken;

        try
        {
            // Validate
            var validation = ValidateJob(job);
            if (!validation.IsValid)
            {
                return ConversionResult.Failed(job, validation.ErrorMessage!, stopwatch.Elapsed);
            }

            // Get file info
            job.InputFileSize = new FileInfo(job.InputPath).Length;
            job.Status = ConversionStatus.Running;
            job.StartedAt = DateTime.UtcNow;

            // Report initial progress
            progress?.Report(ConversionProgress.Indeterminate("Starting conversion...", ConversionStage.Initializing));

            // Build arguments
            var arguments = BuildArguments(job, job.Options);

            // Get executable path
            var executablePath = GetExecutablePath();
            if (!File.Exists(executablePath))
            {
                return ConversionResult.Failed(job, $"Converter executable not found: {executablePath}", stopwatch.Elapsed);
            }

            var commandLine = FormatCommandLine(executablePath, arguments);
            Logger?.LogDebug("Executing: {CommandLine}", commandLine);

            // Ensure output directory exists
            var outputDir = Path.GetDirectoryName(job.OutputPath);
            if (!string.IsNullOrEmpty(outputDir) && !Directory.Exists(outputDir))
            {
                Directory.CreateDirectory(outputDir);
            }

            // Execute process
            var result = await ExecuteProcessAsync(
                executablePath,
                arguments,
                job,
                progress,
                warnings,
                effectiveCancellationToken);

            stopwatch.Stop();
            job.CompletedAt = DateTime.UtcNow;

            if (result.Success)
            {
                var outputFailure = ValidateSuccessfulOutput(
                    job,
                    stopwatch.Elapsed,
                    result.ExitCode,
                    result.StandardOutput,
                    result.StandardError,
                    Id,
                    commandLine,
                    warnings);

                if (outputFailure != null)
                    return outputFailure;

                job.Status = ConversionStatus.Completed;
                
                return ConversionResult.Succeeded(
                    job,
                    job.OutputPath,
                    stopwatch.Elapsed,
                    Id,
                    commandLine,
                    warnings);
            }
            else
            {
                job.Status = ConversionStatus.Failed;
                return ConversionResult.Failed(
                    job,
                    result.ErrorMessage ?? "Unknown error",
                    stopwatch.Elapsed,
                    result.ExitCode,
                    result.StandardOutput,
                    result.StandardError,
                    Id,
                    commandLine,
                    warnings);
            }
        }
        catch (OperationCanceledException) when (timeoutCts?.IsCancellationRequested == true && !cancellationToken.IsCancellationRequested)
        {
            job.Status = ConversionStatus.Failed;
            job.CompletedAt = DateTime.UtcNow;

            if (File.Exists(job.OutputPath))
            {
                try { File.Delete(job.OutputPath); } catch { }
            }

            return ConversionResult.Failed(
                job,
                $"Conversion timed out after {job.Options.Timeout!.Value}.",
                stopwatch.Elapsed,
                exitCode: -1,
                converter: Id);
        }
        catch (OperationCanceledException)
        {
            job.Status = ConversionStatus.Cancelled;
            job.CompletedAt = DateTime.UtcNow;
            
            // Clean up partial output
            if (File.Exists(job.OutputPath))
            {
                try { File.Delete(job.OutputPath); } catch { }
            }
            
            return ConversionResult.Cancelled(job, stopwatch.Elapsed);
        }
        catch (Exception ex)
        {
            job.Status = ConversionStatus.Failed;
            job.CompletedAt = DateTime.UtcNow;
            
            Logger?.LogError(ex, "Conversion failed for {Input}", job.InputPath);
            return ConversionResult.Failed(job, ex.Message, stopwatch.Elapsed);
        }
    }

    protected virtual string GetExecutablePath()
    {
        var exeName = OperatingSystem.IsWindows() ? $"{ExecutableName}.exe" : ExecutableName;
        
        // Check tools directory first
        var toolPath = Path.Combine(ToolsBasePath, "bin", exeName);
        if (File.Exists(toolPath))
            return toolPath;

        // Check PATH
        var pathDirs = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator) ?? [];
        foreach (var dir in pathDirs)
        {
            var fullPath = Path.Combine(dir, exeName);
            if (File.Exists(fullPath))
                return fullPath;
        }

        return toolPath; // Return expected path even if not found
    }

    protected virtual async Task<ProcessResult> ExecuteProcessAsync(
        string executable,
        string[] arguments,
        ConversionJob job,
        IProgress<ConversionProgress>? progress,
        List<string> warnings,
        CancellationToken cancellationToken)
    {
        var stdout = new StringBuilder();
        var stderr = new StringBuilder();

        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            // Redirect stdin so we can immediately close it. Without this, CLI
            // tools that quietly read from stdin (Ghostscript, Pandoc with no
            // input, ImageMagick in some interactive flows) block forever.
            RedirectStandardInput = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding  = Encoding.UTF8,
        };
        foreach (var argument in arguments)
            startInfo.ArgumentList.Add(argument);

        ConfigureProcessStartInfo(startInfo, job);

        using var process = new Process
        {
            StartInfo = startInfo,
            EnableRaisingEvents = true
        };

        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data == null) return;
            stdout.AppendLine(e.Data);
            ProcessOutputLine(e.Data, job, progress, warnings);
        };

        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data == null) return;
            stderr.AppendLine(e.Data);
            ProcessOutputLine(e.Data, job, progress, warnings);
        };

        process.Start();
        // Close stdin immediately — see comment on RedirectStandardInput above.
        try { process.StandardInput.Close(); } catch { /* never fatal */ }
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        try
        {
            await process.WaitForExitAsync(cancellationToken);
        }
        catch (OperationCanceledException)
        {
            try { process.Kill(entireProcessTree: true); } catch { }
            // Give the OS a moment to flush pipes after the kill before we stop
            // reading. Without this the async readers can swallow the last burst
            // of stderr that often contains the real failure reason.
            try
            {
                using var graceCts = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                await process.WaitForExitAsync(graceCts.Token).ConfigureAwait(false);
            }
            catch { /* timed out — proceed */ }
            throw;
        }

        // Wait for output buffers to drain after natural exit. Without WaitForExit
        // (no token), BeginOutput/Error subscribers can still be flushing data when
        // we read process.ExitCode below.
        try { process.WaitForExit(2_000); } catch { }

        int exitCode;
        try { exitCode = process.ExitCode; }
        catch (InvalidOperationException) { exitCode = -1; }
        var success = exitCode == 0;

        return new ProcessResult
        {
            Success = success,
            ExitCode = exitCode,
            StandardOutput = stdout.ToString(),
            StandardError = stderr.ToString(),
            ErrorMessage = success ? null : GetErrorMessage(stderr.ToString(), exitCode)
        };
    }

    /// <summary>
    /// Allows a converter to add engine-specific environment isolation without
    /// replacing the common hidden-process, cancellation, and output handling.
    /// </summary>
    protected virtual void ConfigureProcessStartInfo(ProcessStartInfo startInfo, ConversionJob job)
    {
    }

    protected virtual ConversionResult? ValidateSuccessfulOutput(
        ConversionJob job,
        TimeSpan duration,
        int exitCode = 0,
        string? standardOutput = null,
        string? standardError = null,
        string? converter = null,
        string? commandLine = null,
        IReadOnlyList<string>? warnings = null)
    {
        if (!RequiresOutputFile)
        {
            job.OutputFileSize = File.Exists(job.OutputPath)
                ? new FileInfo(job.OutputPath).Length
                : 0;
            return null;
        }

        if (!File.Exists(job.OutputPath))
        {
            job.Status = ConversionStatus.Failed;
            job.OutputFileSize = 0;
            return ConversionResult.Failed(
                job,
                $"Converter completed but did not create the expected output file: {job.OutputPath}",
                duration,
                exitCode,
                standardOutput,
                standardError,
                converter,
                commandLine,
                warnings);
        }

        var outputSize = new FileInfo(job.OutputPath).Length;
        job.OutputFileSize = outputSize;

        if (!AllowsEmptyOutputFile && outputSize == 0)
        {
            job.Status = ConversionStatus.Failed;
            return ConversionResult.Failed(
                job,
                $"Converter created an empty output file: {job.OutputPath}",
                duration,
                exitCode,
                standardOutput,
                standardError,
                converter,
                commandLine,
                warnings);
        }

        return null;
    }

    protected virtual void ProcessOutputLine(
        string line,
        ConversionJob job,
        IProgress<ConversionProgress>? progress,
        List<string> warnings)
    {
        if (string.IsNullOrWhiteSpace(line))
            return;

        // Check for warnings
        if (line.Contains("warning", StringComparison.OrdinalIgnoreCase))
        {
            warnings.Add(line.Trim());
        }

        // Try to parse progress
        var progressInfo = ParseProgress(line, job);
        if (progressInfo != null)
        {
            progress?.Report(progressInfo);
        }
    }

    protected virtual string GetErrorMessage(string stderr, int exitCode)
    {
        if (string.IsNullOrWhiteSpace(stderr))
            return $"Process exited with code {exitCode}";

        // Get last non-empty line
        var lines = stderr.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        var errorLine = lines.LastOrDefault(l => 
            l.Contains("error", StringComparison.OrdinalIgnoreCase) ||
            l.Contains("failed", StringComparison.OrdinalIgnoreCase) ||
            l.Contains("invalid", StringComparison.OrdinalIgnoreCase));

        return errorLine?.Trim() ?? lines.LastOrDefault()?.Trim() ?? $"Process exited with code {exitCode}";
    }

    protected static string QuoteArgument(string arg)
    {
        if (string.IsNullOrEmpty(arg))
            return "\"\"";

        if (!arg.Contains(' ') && !arg.Contains('"') && !arg.Contains('\\'))
            return arg;

        return $"\"{arg.Replace("\\", "\\\\").Replace("\"", "\\\"")}\"";
    }

    protected static string FormatCommandLine(string executable, IEnumerable<string> arguments) =>
        $"{QuoteArgument(executable)} {string.Join(" ", arguments.Select(QuoteArgument))}".TrimEnd();

    protected static string NormalizeExtension(string extension) =>
        extension.Trim().TrimStart('.').ToLowerInvariant();

    protected record ProcessResult
    {
        public bool Success { get; init; }
        public int ExitCode { get; init; }
        public string? StandardOutput { get; init; }
        public string? StandardError { get; init; }
        public string? ErrorMessage { get; init; }
    }
}
