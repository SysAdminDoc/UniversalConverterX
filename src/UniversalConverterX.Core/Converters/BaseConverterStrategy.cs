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

        if (!SupportedInputFormats.Contains(job.InputExtension))
            return ValidationResult.Fail($"Unsupported input format: {job.InputExtension}");

        if (!SupportedOutputFormats.Contains(job.OutputExtension))
            return ValidationResult.Fail($"Unsupported output format: {job.OutputExtension}");

        return ValidationResult.Success;
    }

    public virtual async Task<ConversionResult> ConvertAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var stopwatch = Stopwatch.StartNew();
        var warnings = new List<string>();

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
            var argumentString = string.Join(" ", arguments.Select(QuoteArgument));

            // Get executable path
            var executablePath = GetExecutablePath();
            if (!File.Exists(executablePath))
            {
                return ConversionResult.Failed(job, $"Converter executable not found: {executablePath}", stopwatch.Elapsed);
            }

            Logger?.LogDebug("Executing: {Executable} {Arguments}", executablePath, argumentString);

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
                cancellationToken);

            stopwatch.Stop();
            job.CompletedAt = DateTime.UtcNow;

            if (result.Success)
            {
                job.Status = ConversionStatus.Completed;
                job.OutputFileSize = File.Exists(job.OutputPath) ? new FileInfo(job.OutputPath).Length : 0;
                
                return ConversionResult.Succeeded(
                    job,
                    job.OutputPath,
                    stopwatch.Elapsed,
                    Id,
                    $"{executablePath} {argumentString}",
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
                    $"{executablePath} {argumentString}");
            }
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

        using var process = new Process
        {
            StartInfo = new ProcessStartInfo
            {
                FileName = executable,
                Arguments = string.Join(" ", arguments.Select(QuoteArgument)),
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                RedirectStandardInput = true
            },
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
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        try
        {
            await process.WaitForExitAsync(cancellationToken);
        }
        catch (OperationCanceledException)
        {
            try
            {
                process.Kill(true);
            }
            catch { }
            throw;
        }

        var exitCode = process.ExitCode;
        var success = exitCode == 0 && File.Exists(job.OutputPath) && new FileInfo(job.OutputPath).Length > 0;

        return new ProcessResult
        {
            Success = success,
            ExitCode = exitCode,
            StandardOutput = stdout.ToString(),
            StandardError = stderr.ToString(),
            ErrorMessage = success ? null : GetErrorMessage(stderr.ToString(), exitCode)
        };
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

    protected record ProcessResult
    {
        public bool Success { get; init; }
        public int ExitCode { get; init; }
        public string? StandardOutput { get; init; }
        public string? StandardError { get; init; }
        public string? ErrorMessage { get; init; }
    }
}
