using System.Collections.Concurrent;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Converters;
using UniversalConverterX.Core.Detection;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

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
        _logger?.LogInformation("Starting conversion: {Input} → {Output}", 
            job.InputFileName, job.OutputExtension);

        // Detect format if not specified
        if (job.SourceFormat == null)
        {
            job.SourceFormat = await DetectFormatAsync(job.InputPath, cancellationToken);
        }

        // Find the best converter
        var converter = GetBestConverter(job.InputExtension, job.OutputExtension);
        if (converter == null)
        {
            _logger?.LogError("No converter found for {Input} → {Output}", 
                job.InputExtension, job.OutputExtension);
            
            return ConversionResult.Failed(
                job,
                $"No converter available for {job.InputExtension} → {job.OutputExtension}",
                TimeSpan.Zero);
        }

        // Use forced converter if specified
        if (!string.IsNullOrEmpty(job.Options.ForceConverter))
        {
            var forcedConverter = _converters.FirstOrDefault(c => 
                c.Id.Equals(job.Options.ForceConverter, StringComparison.OrdinalIgnoreCase));
            
            if (forcedConverter != null)
            {
                converter = forcedConverter;
                _logger?.LogDebug("Using forced converter: {Converter}", converter.Id);
            }
        }

        job.ConverterUsed = converter.Id;
        _logger?.LogDebug("Using converter: {Converter}", converter.Name);

        // Execute conversion
        return await converter.ConvertAsync(job, progress, cancellationToken);
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

        await Parallel.ForEachAsync(
            jobList,
            new ParallelOptions
            {
                MaxDegreeOfParallelism = Math.Clamp(maxParallelism, 1, _options.MaxConcurrentConversions),
                CancellationToken = cancellationToken
            },
            async (job, ct) =>
            {
                var jobProgress = new Progress<ConversionProgress>(p =>
                {
                    progress?.Report(new BatchProgress(
                        completed,
                        jobList.Count,
                        failed,
                        job,
                        p));
                });

                var result = await ConvertAsync(job, jobProgress, ct);
                results.Add(result);

                Interlocked.Increment(ref completed);
                if (!result.Success)
                    Interlocked.Increment(ref failed);

                progress?.Report(new BatchProgress(
                    completed,
                    jobList.Count,
                    failed,
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
        var ext = Path.GetExtension(inputPath).TrimStart('.').ToLowerInvariant();
        
        if (_conversionGraph.TryGetValue(ext, out var outputs))
            return outputs;

        return [];
    }

    public IConverterStrategy? GetBestConverter(string inputExtension, string outputExtension)
    {
        var inputExt = inputExtension.ToLowerInvariant().TrimStart('.');
        var outputExt = outputExtension.ToLowerInvariant().TrimStart('.');

        // Find highest priority converter that supports this conversion
        foreach (var converter in _converters)
        {
            var inputFormats = converter.GetSupportedInputFormats();
            var outputFormats = converter.GetOutputFormatsFor(inputExt);

            if (inputFormats.Contains(inputExt) && outputFormats.Contains(outputExt))
            {
                return converter;
            }
        }

        return null;
    }

    public IReadOnlyCollection<IConverterStrategy> GetConverters() => _converters.AsReadOnly();

    public bool CanConvert(string inputExtension, string outputExtension)
    {
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
}
