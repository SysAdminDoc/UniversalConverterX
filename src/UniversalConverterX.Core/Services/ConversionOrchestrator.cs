using System.Collections.Concurrent;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Detection;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Localization;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Services;

/// <summary>
/// Main orchestrator for routing conversions to appropriate converter strategies
/// </summary>
public class ConversionOrchestrator : IConversionOrchestrator
{
    private readonly ILogger<ConversionOrchestrator>? _logger;
    private readonly List<IConverterStrategy> _converters;
    private readonly Dictionary<string, HashSet<string>> _conversionGraph;
    private readonly MagicBytesDetector _formatDetector;
    private readonly ConverterXOptions _options;

    public ConversionOrchestrator(
        IOptions<ConverterXOptions> options,
        ILogger<ConversionOrchestrator>? logger = null)
    {
        _options = options.Value;
        _logger = logger;
        _formatDetector = new MagicBytesDetector();
        _converters = [];
        _conversionGraph = [];

        InitializeConverters();
        BuildConversionGraph();
    }

    public ConversionOrchestrator(
        IEnumerable<IConverterStrategy> converters,
        IOptions<ConverterXOptions> options,
        ILogger<ConversionOrchestrator>? logger = null)
    {
        _options = options.Value;
        _logger = logger;
        _formatDetector = new MagicBytesDetector();
        _converters = converters.OrderByDescending(c => c.Priority).ToList();
        _conversionGraph = [];

        BuildConversionGraph();
    }

    public ConversionOrchestrator(string toolsBasePath, ILogger<ConversionOrchestrator>? logger = null)
        : this(Options.Create(new ConverterXOptions { ToolsBasePath = toolsBasePath }), logger)
    {
    }

    private void InitializeConverters()
    {
        var toolsPath = _options.ToolsBasePath;

        // Add all converters - they will be sorted by priority
        // Video/Audio converters
        _converters.Add(new FFmpegConverter(toolsPath));                    // Priority 100
        
        // Image converters
        _converters.Add(new ResvgConverter(toolsPath));                     // Priority 97 - SVG rendering
        _converters.Add(new LibHeifConverter(toolsPath));                   // Priority 96 - HEIC/HEIF
        _converters.Add(new InkscapeConverter(toolsPath));                  // Priority 95 - Vector graphics
        _converters.Add(new LibJxlConverter(toolsPath));                    // Priority 94 - JPEG XL
        _converters.Add(new VipsConverter(toolsPath));                      // Priority 92 - High-perf images
        _converters.Add(new ImageMagickConverter(toolsPath));               // Priority 90 - General images
        _converters.Add(new PotraceConverter(toolsPath));                   // Priority 88 - Raster to vector
        
        // Document converters
        _converters.Add(new CalibreConverter(toolsPath));                   // Priority 85 - Ebooks
        _converters.Add(new AssimpConverter(toolsPath));                    // Priority 85 - 3D models
        _converters.Add(new PandocConverter(toolsPath));                    // Priority 80 - Documents
        _converters.Add(new GhostscriptConverter(toolsPath));               // Priority 75 - PDF
        _converters.Add(new LibreOfficeConverter(toolsPath));               // Priority 70 - Office docs

        // Sort by priority (highest first)
        _converters.Sort((a, b) => b.Priority.CompareTo(a.Priority));

        _logger?.LogInformation("Initialized {Count} converters", _converters.Count);
    }

    private void BuildConversionGraph()
    {
        foreach (var converter in _converters)
        {
            foreach (var input in converter.GetSupportedInputFormats())
            {
                var normalizedInput = input.ToLowerInvariant();
                
                if (!_conversionGraph.ContainsKey(normalizedInput))
                    _conversionGraph[normalizedInput] = [];

                foreach (var output in converter.GetOutputFormatsFor(input))
                {
                    _conversionGraph[normalizedInput].Add(output.ToLowerInvariant());
                }
            }
        }

        _logger?.LogDebug("Built conversion graph with {Count} input formats", _conversionGraph.Count);
    }

    public async Task<ConversionResult> ConvertAsync(
        string inputPath,
        string outputPath,
        ConversionOptions? options = null,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var job = ConversionJob.Create(inputPath, outputPath, options);
        return await ConvertAsync(job, progress, cancellationToken);
    }

    public async Task<ConversionResult> ConvertAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var startedAt = DateTime.UtcNow;
        _logger?.LogInformation("Starting conversion: {Input} → {Output}", 
            job.InputFileName, job.OutputExtension);

        try
        {
            // Validate inputs at the orchestrator boundary so callers get a clean
            // error instead of a NullReferenceException deep inside a strategy.
            if (string.IsNullOrWhiteSpace(job.InputPath))
            {
                job.Status = ConversionStatus.Failed;
                job.CompletedAt = DateTime.UtcNow;
                return ConversionResult.Failed(
                    job, LocalizedText.Get("Core_InputPathRequired", "Input path is required."),
                    DateTime.UtcNow - startedAt);
            }
            if (string.IsNullOrWhiteSpace(job.OutputPath))
            {
                job.Status = ConversionStatus.Failed;
                job.CompletedAt = DateTime.UtcNow;
                return ConversionResult.Failed(
                    job, LocalizedText.Get("Core_OutputPathRequired", "Output path is required."),
                    DateTime.UtcNow - startedAt);
            }

            // Apply overwrite behavior at the orchestrator boundary so every
            // converter strategy and CLI/UI caller benefits uniformly. Ask
            // and Always fall through to the converter unchanged — Ask is a
            // UI-layer concern (Core has no prompt surface, and silently
            // remapping it here would change behaviour for upgraders with
            // OverwriteBehavior=Ask persisted in settings.json).
            switch (ResolveOverwriteBehavior(job))
            {
                case OverwriteBehavior.Skip when File.Exists(job.OutputPath):
                    _logger?.LogInformation(
                        "Skipping {Output}: file exists and OverwriteBehavior=Skip",
                        job.OutputPath);
                    job.Status = ConversionStatus.Skipped;
                    job.CompletedAt = DateTime.UtcNow;
                    return ConversionResult.Skipped(
                        job,
                        LocalizedText.Format(
                            "Core_OutputExistsSkip",
                            "Output already exists at '{0}' and the overwrite policy is Skip.",
                            job.OutputPath),
                        DateTime.UtcNow - startedAt);

                case OverwriteBehavior.Never when File.Exists(job.OutputPath):
                    try
                    {
                        var renamed = UniqueOutputPath.Resolve(job.OutputPath);
                        if (!string.Equals(renamed, job.OutputPath, StringComparison.Ordinal))
                        {
                            _logger?.LogInformation(
                                "Output file collision: '{Original}' exists; auto-renamed to '{Renamed}'",
                                job.OutputPath, renamed);
                            job.OutputPath = renamed;
                        }
                    }
                    catch (IOException ioex)
                    {
                        // Saturation: every (1)..(9999) suffix taken. Surface
                        // as a normal failed result rather than crashing the
                        // calling CLI / UI batch loop.
                        _logger?.LogWarning(ioex,
                            "UniqueOutputPath saturated for '{Output}'", job.OutputPath);
                        job.Status = ConversionStatus.Failed;
                        job.CompletedAt = DateTime.UtcNow;
                        return ConversionResult.Failed(job, ioex.Message, DateTime.UtcNow - startedAt);
                    }
                    break;

                case OverwriteBehavior.Ask:
                case OverwriteBehavior.Always:
                default:
                    break;
            }

            // Detect format if not specified
            if (job.SourceFormat == null)
            {
                job.SourceFormat = await DetectFormatAsync(job.InputPath, cancellationToken);
            }

            var sourceExtension = job.SourceFormat?.Extension ?? job.InputExtension;

            IConverterStrategy? converter;

            // Honour ForceConverter first — but verify it can actually do the
            // requested conversion. Silently substituting a different converter
            // (the prior behaviour) hid bugs where the user's `--converter ffmpeg`
            // ended up running ImageMagick.
            if (!string.IsNullOrEmpty(job.Options.ForceConverter))
            {
                var forced = _converters.FirstOrDefault(c =>
                    c.Id.Equals(job.Options.ForceConverter, StringComparison.OrdinalIgnoreCase));
                if (forced is null)
                {
                    job.Status = ConversionStatus.Failed;
                    job.CompletedAt = DateTime.UtcNow;
                    return ConversionResult.Failed(
                        job,
                        LocalizedText.Format(
                            "Core_ForcedConverterNotRegistered",
                            "Forced converter '{0}' is not registered. Available: {1}",
                            job.Options.ForceConverter,
                            string.Join(", ", _converters.Select(c => c.Id))),
                        DateTime.UtcNow - startedAt);
                }
                var src = job.SourceFormat ?? new FileFormat(sourceExtension, GetMimeType(sourceExtension), DetermineCategory(sourceExtension));
                var tgt = new FileFormat(job.OutputExtension, GetMimeType(job.OutputExtension), DetermineCategory(job.OutputExtension));
                if (!forced.CanConvert(src, tgt))
                {
                    job.Status = ConversionStatus.Failed;
                    job.CompletedAt = DateTime.UtcNow;
                    return ConversionResult.Failed(
                        job,
                        LocalizedText.Format(
                            "Core_ForcedConverterCannotConvert",
                            "Forced converter '{0}' cannot convert {1} → {2}.",
                            forced.Id, sourceExtension, job.OutputExtension),
                        DateTime.UtcNow - startedAt);
                }
                converter = forced;
                _logger?.LogDebug("Using forced converter: {Converter}", converter.Id);
            }
            else
            {
                // Find the best converter
                converter = GetBestConverter(sourceExtension, job.OutputExtension);
                if (converter == null)
                {
                    _logger?.LogError("No converter found for {Input} → {Output}",
                        sourceExtension, job.OutputExtension);

                    job.Status = ConversionStatus.Failed;
                    job.CompletedAt = DateTime.UtcNow;

                    return ConversionResult.Failed(
                        job,
                        LocalizedText.Format(
                            "Core_NoConverterAvailable",
                            "No converter is available for {0} → {1}.",
                            sourceExtension, job.OutputExtension),
                        DateTime.UtcNow - startedAt);
                }
            }

            job.ConverterUsed = converter.Id;
            _logger?.LogDebug("Using converter: {Converter}", converter.Name);

            // Execute conversion, then apply any source-file action at the
            // orchestrator boundary so CLI, UI, and batch callers agree.
            var result = await converter.ConvertAsync(job, progress, cancellationToken);
            if (result.Success)
                cancellationToken.ThrowIfCancellationRequested();
            return ApplyPostConversionAction(result);
        }
        catch (OperationCanceledException)
        {
            job.Status = ConversionStatus.Cancelled;
            job.CompletedAt = DateTime.UtcNow;
            return ConversionResult.Cancelled(job, DateTime.UtcNow - startedAt);
        }
    }

    private ConversionResult ApplyPostConversionAction(ConversionResult result)
    {
        if (!result.Success || string.IsNullOrWhiteSpace(result.OutputPath))
            return result;

        var action = PostConversionHandler.ResolveAction(result.Job.Options);
        var postResult = PostConversionHandler.Execute(
            result.Job.InputPath,
            result.OutputPath,
            action,
            result.Job.Options.PostConversionArchiveFolder,
            _logger);

        if (postResult.Success)
            return result;

        // A failed Mark-of-the-Web propagation under the non-destructive Keep
        // action (the default) must NOT fail an otherwise-successful conversion.
        // The output artifact is fully produced; only the source's download
        // security zone could not be copied onto it — a common, benign case when
        // the output lives on a filesystem without alternate-data-stream support
        // (FAT32/exFAT USB sticks, many SMB shares) or the zone data exceeds the
        // safety cap. Surface it as a warning instead of a hard failure.
        if (postResult.Action == PostConversionAction.Keep)
        {
            _logger?.LogWarning(
                "Conversion succeeded but Mark-of-the-Web could not be preserved on '{Output}': {Message}",
                result.OutputPath,
                postResult.ErrorMessage);

            return new ConversionResult
            {
                Success = true,
                Job = result.Job,
                OutputPath = result.OutputPath,
                OutputSize = result.OutputSize,
                Duration = result.Duration,
                ExitCode = result.ExitCode,
                StandardOutput = result.StandardOutput,
                StandardError = result.StandardError,
                ConverterUsed = result.ConverterUsed,
                CommandLine = result.CommandLine,
                Warnings = [.. result.Warnings, LocalizedText.Format(
                    "Core_MarkOfWebWarning",
                    "The converted file was created, but its download security zone could not be copied from the source: {0}",
                    postResult.ErrorMessage ?? "unknown error")]
            };
        }

        result.Job.Status = ConversionStatus.Failed;
        result.Job.CompletedAt = DateTime.UtcNow;

        return new ConversionResult
        {
            Success = false,
            Job = result.Job,
            OutputPath = result.OutputPath,
            OutputSize = result.OutputSize,
            Duration = result.Duration,
            ErrorMessage = LocalizedText.Format(
                "Core_PostActionFailed",
                "Conversion succeeded, but the post-conversion source action failed: {0}",
                postResult.ErrorMessage),
            ExitCode = -1,
            StandardOutput = result.StandardOutput,
            StandardError = result.StandardError,
            ConverterUsed = result.ConverterUsed,
            CommandLine = result.CommandLine,
            Warnings = result.Warnings
        };
    }

    public async Task<BatchConversionResult> ConvertBatchAsync(
        IEnumerable<ConversionJob> jobs,
        int maxParallelism = 4,
        IProgress<BatchProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var jobList = jobs.ToList();
        var results = new ConcurrentBag<ConversionResult>();
        var completed = 0;
        var failed = 0;
        var startTime = DateTime.UtcNow;

        _logger?.LogInformation("Starting batch conversion of {Count} files", jobList.Count);

        // Defensive floors: a misconfigured Options.MaxParallelConversions of 0
        // (or a caller passing 0) would otherwise produce a runtime exception.
        var hardCap   = Math.Max(1, _options.MaxParallelConversions);
        var requested = Math.Max(1, maxParallelism);
        var degree    = Math.Min(hardCap, requested);

        await Parallel.ForEachAsync(
            jobList,
            new ParallelOptions
            {
                MaxDegreeOfParallelism = degree,
                CancellationToken = cancellationToken
            },
            async (job, ct) =>
            {
                var jobProgress = new Progress<ConversionProgress>(p =>
                {
                    // Volatile reads so per-job updates aren't reporting stale
                    // counters when other workers race ahead.
                    progress?.Report(new BatchProgress(
                        Volatile.Read(ref completed),
                        jobList.Count,
                        Volatile.Read(ref failed),
                        job,
                        p));
                });

                var result = await ConvertAsync(job, jobProgress, ct);
                results.Add(result);

                if (!result.Success)
                    Interlocked.Increment(ref failed);
                Interlocked.Increment(ref completed);

                progress?.Report(new BatchProgress(
                    Volatile.Read(ref completed),
                    jobList.Count,
                    Volatile.Read(ref failed),
                    null,
                    null));
            });

        var duration = DateTime.UtcNow - startTime;

        _logger?.LogInformation(
            "Batch conversion complete: {Success}/{Total} succeeded in {Duration:F1}s",
            results.Count(r => r.Success),
            jobList.Count,
            duration.TotalSeconds);

        return new BatchConversionResult(results.ToList(), duration);
    }

    public IReadOnlyCollection<string> GetOutputFormatsFor(string inputPath)
    {
        if (string.IsNullOrWhiteSpace(inputPath))
            return [];

        var trimmed = inputPath.Trim();
        var ext = Path.HasExtension(trimmed)
            ? Path.GetExtension(trimmed).TrimStart('.').ToLowerInvariant()
            : trimmed.TrimStart('.').ToLowerInvariant();
        
        if (_conversionGraph.TryGetValue(ext, out var outputs))
            return outputs;

        return [];
    }

    public IConverterStrategy? GetBestConverter(string inputExtension, string outputExtension)
    {
        if (string.IsNullOrWhiteSpace(inputExtension) || string.IsNullOrWhiteSpace(outputExtension))
            return null;
        var inputExt = inputExtension.ToLowerInvariant().TrimStart('.');
        var outputExt = outputExtension.ToLowerInvariant().TrimStart('.');
        var source = new FileFormat(inputExt, GetMimeType(inputExt), DetermineCategory(inputExt));
        var target = new FileFormat(outputExt, GetMimeType(outputExt), DetermineCategory(outputExt));

        // Find highest priority converter that supports this conversion
        foreach (var converter in _converters)
        {
            if (converter.CanConvert(source, target))
            {
                return converter;
            }
        }

        return null;
    }

    public IReadOnlyCollection<IConverterStrategy> GetConverters() => _converters.AsReadOnly();

    public IReadOnlyCollection<IConverterStrategy> GetAvailableConverters() => GetConverters();

    public IConverterStrategy? GetConverterById(string id) =>
        _converters.FirstOrDefault(c => c.Id.Equals(id, StringComparison.OrdinalIgnoreCase));

    public IReadOnlyCollection<IConverterStrategy> GetConvertersFor(FileFormat source, FileFormat target) =>
        _converters
            .Where(c => c.CanConvert(source, target))
            .OrderByDescending(c => c.Priority)
            .ToList();

    public IReadOnlyCollection<string> GetSupportedInputFormats() =>
        _conversionGraph.Keys.OrderBy(f => f, StringComparer.OrdinalIgnoreCase).ToList();

    public IReadOnlyCollection<string> GetSupportedOutputFormats() =>
        _conversionGraph.Values
            .SelectMany(outputs => outputs)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(f => f, StringComparer.OrdinalIgnoreCase)
            .ToList();

    public bool CanConvert(string inputExtension, string outputExtension)
    {
        if (string.IsNullOrWhiteSpace(inputExtension) || string.IsNullOrWhiteSpace(outputExtension))
            return false;

        var inputExt = inputExtension.ToLowerInvariant().TrimStart('.');
        var outputExt = outputExtension.ToLowerInvariant().TrimStart('.');

        return _conversionGraph.TryGetValue(inputExt, out var outputs) && outputs.Contains(outputExt);
    }

    public async Task<FileFormat> DetectFormatAsync(string filePath, CancellationToken cancellationToken = default)
    {
        // First try magic bytes detection
        var detected = await _formatDetector.DetectAsync(filePath, cancellationToken);
        if (detected != null)
            return detected;

        // Fall back to extension-based detection
        var ext = Path.GetExtension(filePath).TrimStart('.').ToLowerInvariant();
        var category = DetermineCategory(ext);
        var mimeType = GetMimeType(ext);

        return new FileFormat(ext, mimeType, category);
    }

    public FileFormat? DetectFormat(string filePath)
    {
        if (!File.Exists(filePath))
            return null;

        return _formatDetector.DetectFormat(filePath);
    }

    private static FormatCategory DetermineCategory(string extension) => extension switch
    {
        // Video
        "mp4" or "mkv" or "avi" or "mov" or "wmv" or "flv" or "webm" or 
        "m4v" or "mpg" or "mpeg" or "3gp" or "ts" or "mts" => FormatCategory.Video,

        // Audio
        "mp3" or "wav" or "flac" or "aac" or "ogg" or "wma" or "m4a" or 
        "opus" or "aiff" or "ape" or "ac3" => FormatCategory.Audio,

        // Image
        "jpg" or "jpeg" or "png" or "gif" or "bmp" or "tiff" or "tif" or 
        "webp" or "ico" or "heic" or "heif" or "avif" or "jxl" or 
        "psd" or "raw" or "cr2" or "nef" => FormatCategory.Image,

        // Document
        "pdf" or "doc" or "docx" or "odt" or "rtf" or "txt" or 
        "html" or "htm" or "md" or "tex" => FormatCategory.Document,

        // Ebook
        "epub" or "mobi" or "azw" or "azw3" or "fb2" or "lit" => FormatCategory.Ebook,

        // Vector
        "svg" or "eps" or "ai" => FormatCategory.Vector,

        // 3D
        "obj" or "fbx" or "stl" or "gltf" or "glb" or "3ds" or "dae" => FormatCategory.ThreeD,

        // Data
        "json" or "xml" or "yaml" or "yml" or "csv" or "tsv" => FormatCategory.Data,

        _ => FormatCategory.Unknown
    };

    private static string GetMimeType(string extension) => extension switch
    {
        // Video
        "mp4" => "video/mp4",
        "mkv" => "video/x-matroska",
        "avi" => "video/x-msvideo",
        "mov" => "video/quicktime",
        "webm" => "video/webm",

        // Audio
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "flac" => "audio/flac",
        "aac" => "audio/aac",
        "ogg" => "audio/ogg",
        "m4a" => "audio/mp4",

        // Image
        "jpg" or "jpeg" => "image/jpeg",
        "png" => "image/png",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        "bmp" => "image/bmp",
        "tiff" or "tif" => "image/tiff",
        "heic" or "heif" => "image/heif",
        "avif" => "image/avif",

        // Document
        "pdf" => "application/pdf",
        "doc" => "application/msword",
        "docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "html" or "htm" => "text/html",
        "txt" => "text/plain",
        "md" => "text/markdown",

        // Ebook
        "epub" => "application/epub+zip",
        "mobi" => "application/x-mobipocket-ebook",

        // Data
        "json" => "application/json",
        "xml" => "application/xml",
        "csv" => "text/csv",

        _ => "application/octet-stream"
    };

    /// <summary>
    /// Combine the global <see cref="ConverterXOptions.OverwriteBehavior"/>
    /// with the per-job <see cref="ConversionOptions.OverwriteExisting"/>
    /// flag. A per-job opt-in to overwrite always wins so callers can short
    /// circuit auto-rename when they have already negotiated the path with
    /// the user (e.g. "Save As" dialogs that already confirmed overwrite).
    /// Ask is preserved as-is — the orchestrator does NOT remap it. UI
    /// layers that want a true prompt should show one and set
    /// <see cref="ConversionOptions.OverwriteExisting"/> on the job after
    /// the user clicks "Yes". CLI / batch contexts get Never as the new
    /// default for fresh installs (see <see cref="ConverterXOptions"/>),
    /// while users with persisted Ask preferences keep their behaviour.
    /// </summary>
    private OverwriteBehavior ResolveOverwriteBehavior(ConversionJob job)
    {
        if (job.Options.OverwriteExisting)
            return OverwriteBehavior.Always;

        return _options.OverwriteBehavior;
    }
}
