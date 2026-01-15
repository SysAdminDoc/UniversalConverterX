using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Converters;

/// <summary>
/// Assimp (Open Asset Import Library) converter for 3D model formats.
/// Supports a wide range of 3D file formats including FBX, OBJ, GLTF, STL, etc.
/// Uses assimp_cmd command-line tool.
/// </summary>
public partial class AssimpConverter : BaseConverterStrategy
{
    public AssimpConverter(string toolsBasePath, ILogger<AssimpConverter>? logger = null)
        : base(toolsBasePath, logger) { }

    public override string Id => "assimp";
    public override string Name => "Assimp";
    public override int Priority => 85; // Primary 3D model converter
    public override string ExecutableName => "assimp";

    [GeneratedRegex(@"(\d+)%", RegexOptions.Compiled)]
    private static partial Regex PercentRegex();

    [GeneratedRegex(@"Mesh\s+(\d+)/(\d+)", RegexOptions.Compiled)]
    private static partial Regex MeshProgressRegex();

    protected override HashSet<string> SupportedInputFormats => _inputFormats;
    protected override HashSet<string> SupportedOutputFormats => _outputFormats;
    protected override Dictionary<string, HashSet<string>> FormatMappings => [];

    #region Format Definitions

    private static readonly HashSet<string> _inputFormats =
    [
        // Common 3D formats
        "obj", "fbx", "gltf", "glb", "dae", "stl", "ply", "3ds",
        
        // Blender
        "blend",
        
        // CAD/Industrial
        "step", "stp", "iges", "igs", "ifc",
        
        // Game engines
        "x", "ms3d", "mdl", "md2", "md3", "md5mesh", "md5anim",
        
        // Other 3D formats
        "lwo", "lws", "lxo", "ac", "acc", "ac3d",
        "ase", "ask", "assbin", "b3d",
        "bvh", "cob", "csm", "dxf",
        "hmp", "irr", "irrmesh",
        "m3", "nff", "ndo", "off",
        "ogex", "pk3", "pmx", "q3o", "q3s",
        "raw", "smd", "ter", "uc",
        "vta", "x3d", "x3db", "xgl", "zgl",
        
        // Point clouds
        "xyz", "pts", "pcd"
    ];

    private static readonly HashSet<string> _outputFormats =
    [
        // Standard interchange formats
        "obj", "stl", "ply", "dae", "gltf", "glb",
        
        // Assimp binary format
        "assbin",
        
        // X format
        "x",
        
        // STL variants
        "stla", "stlb", // ASCII and binary STL
        
        // 3DS format
        "3ds",
        
        // JSON for inspection
        "json"
    ];

    #endregion

    public override string[] BuildArguments(ConversionJob job, ConversionOptions options)
    {
        var args = new List<string>();
        var outputExt = job.OutputExtension.ToLowerInvariant();

        // Export command
        args.Add("export");

        // Input file
        args.Add(job.InputPath);

        // Output file
        args.Add(job.OutputPath);

        // Output format (if not auto-detected from extension)
        var formatId = GetFormatId(outputExt);
        if (!string.IsNullOrEmpty(formatId))
        {
            args.AddRange(["-f", formatId]);
        }

        // Post-processing options based on quality
        var postProcess = GetPostProcessingFlags(options);
        if (postProcess.Length > 0)
        {
            args.AddRange(postProcess);
        }

        // Verbose output for progress tracking
        args.Add("-v");

        return [.. args];
    }

    private static string GetFormatId(string ext) => ext switch
    {
        "obj" => "obj",
        "stl" or "stla" => "stl",
        "stlb" => "stlb",
        "ply" => "ply",
        "dae" => "collada",
        "gltf" => "gltf2",
        "glb" => "glb2",
        "x" => "x",
        "3ds" => "3ds",
        "assbin" => "assbin",
        "json" => "assjson",
        _ => ""
    };

    private static string[] GetPostProcessingFlags(ConversionOptions options)
    {
        var flags = new List<string>();

        // Quality-based post-processing
        switch (options.Quality)
        {
            case QualityPreset.Lowest:
                // Minimal processing
                flags.Add("-ptv"); // Pre-transform vertices (simpler mesh)
                flags.Add("-fd");  // Find degenerates and remove
                break;

            case QualityPreset.Low:
                flags.Add("-ptv");
                flags.Add("-fd");
                flags.Add("-jiv"); // Join identical vertices
                break;

            case QualityPreset.Medium:
                flags.Add("-ptv");
                flags.Add("-fd");
                flags.Add("-jiv");
                flags.Add("-tri"); // Triangulate
                flags.Add("-gen"); // Generate normals
                break;

            case QualityPreset.High:
                flags.Add("-ptv");
                flags.Add("-fd");
                flags.Add("-jiv");
                flags.Add("-tri");
                flags.Add("-gen");
                flags.Add("-guv"); // Generate UV coords
                flags.Add("-obc"); // Optimize mesh for cache
                break;

            case QualityPreset.Highest:
            case QualityPreset.Lossless:
                flags.Add("-ptv");
                flags.Add("-fd");
                flags.Add("-jiv");
                flags.Add("-tri");
                flags.Add("-cts"); // Calculate tangent space
                flags.Add("-gen");
                flags.Add("-guv");
                flags.Add("-obc");
                flags.Add("-og");  // Optimize graph
                flags.Add("-sbc"); // Split by bone count
                break;
        }

        // Image-specific options for scaling
        if (options.Image.Width.HasValue || options.Image.Height.HasValue)
        {
            // Scale factor calculation would go here
            // Assimp doesn't have direct scale options, would need custom processing
        }

        return [.. flags];
    }

    public override ValidationResult ValidateJob(ConversionJob job)
    {
        var baseResult = base.ValidateJob(job);
        if (!baseResult.IsValid)
            return baseResult;

        // Additional validation for 3D-specific constraints
        var inputExt = job.InputExtension.ToLowerInvariant();
        var outputExt = job.OutputExtension.ToLowerInvariant();

        // Some formats have specific limitations
        if (outputExt == "stl" && inputExt == "blend")
        {
            // STL only supports single meshes; Blender files may have multiple
            Logger?.LogWarning("Converting Blender file to STL may merge multiple objects");
        }

        if (outputExt == "3ds" && inputExt is "gltf" or "glb")
        {
            // 3DS has limitations on materials and textures
            Logger?.LogWarning("Converting to 3DS may lose some material/texture information");
        }

        return ValidationResult.Success;
    }

    public override async Task<ConversionResult> ConvertAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        // Check if assimp is available
        var executablePath = GetExecutablePath();
        if (!File.Exists(executablePath))
        {
            return ConversionResult.Failed(job,
                "Assimp command-line tool not found. Please install assimp-cmd or assimp-utils.",
                TimeSpan.Zero);
        }

        // For some conversions, we may need to use specific tools
        var inputExt = job.InputExtension.ToLowerInvariant();
        var outputExt = job.OutputExtension.ToLowerInvariant();

        // GLTF/GLB conversions might benefit from specialized tools
        if ((outputExt is "gltf" or "glb") && IsComplexFormat(inputExt))
        {
            // Try gltf-pipeline if available for optimization
            var gltfOptimized = await TryOptimizeGltfAsync(job, progress, cancellationToken);
            if (gltfOptimized != null)
                return gltfOptimized;
        }

        return await base.ConvertAsync(job, progress, cancellationToken);
    }

    private async Task<ConversionResult?> TryOptimizeGltfAsync(
        ConversionJob job,
        IProgress<ConversionProgress>? progress,
        CancellationToken cancellationToken)
    {
        // Try to find gltf-pipeline for optimized GLTF output
        var gltfPipeline = OperatingSystem.IsWindows() ? "gltf-pipeline.cmd" : "gltf-pipeline";
        var pipelinePath = FindExecutable(gltfPipeline);

        if (pipelinePath == null)
            return null; // Fall back to assimp

        // First convert to GLTF with assimp, then optimize
        var tempGltf = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid()}.gltf");
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();
        var warnings = new List<string>();

        try
        {
            // Step 1: Convert to GLTF with assimp
            progress?.Report(ConversionProgress.Indeterminate("Converting to GLTF...", ConversionStage.Initializing));

            var tempJob = new ConversionJob
            {
                InputPath = job.InputPath,
                OutputPath = tempGltf,
                Options = job.Options
            };

            var assimpArgs = BuildArguments(tempJob, job.Options);
            var assimpPath = GetExecutablePath();

            var convertResult = await ExecuteProcessAsync(
                assimpPath,
                assimpArgs,
                tempJob,
                null,
                warnings,
                cancellationToken);

            if (!convertResult.Success)
                return null; // Fall back to assimp-only conversion

            // Step 2: Optimize with gltf-pipeline
            progress?.Report(new ConversionProgress
            {
                Percent = 50,
                Stage = ConversionStage.Encoding,
                StatusMessage = "Optimizing GLTF..."
            });

            var pipelineArgs = new List<string>
            {
                "-i", tempGltf,
                "-o", job.OutputPath
            };

            // Add optimization options
            if (job.OutputExtension.ToLowerInvariant() == "glb")
            {
                pipelineArgs.Add("-b"); // Binary output
            }

            if (job.Options.Quality >= QualityPreset.High)
            {
                pipelineArgs.Add("--draco.compressionLevel=10"); // Draco compression
            }

            var optimizeResult = await ExecuteProcessAsync(
                pipelinePath,
                [.. pipelineArgs],
                job,
                progress,
                warnings,
                cancellationToken);

            stopwatch.Stop();

            if (optimizeResult.Success)
            {
                job.Status = ConversionStatus.Completed;
                job.OutputFileSize = File.Exists(job.OutputPath) ? new FileInfo(job.OutputPath).Length : 0;

                return ConversionResult.Succeeded(job, job.OutputPath, stopwatch.Elapsed, Id,
                    warnings: warnings);
            }

            return null; // Fall back to assimp-only
        }
        finally
        {
            // Clean up temp file
            if (File.Exists(tempGltf))
            {
                try { File.Delete(tempGltf); } catch { }
            }
        }
    }

    private string? FindExecutable(string name)
    {
        // Check tools directory
        var toolPath = Path.Combine(ToolsBasePath, "bin", name);
        if (File.Exists(toolPath))
            return toolPath;

        // Check PATH
        var pathDirs = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator) ?? [];
        foreach (var dir in pathDirs)
        {
            var fullPath = Path.Combine(dir, name);
            if (File.Exists(fullPath))
                return fullPath;
        }

        return null;
    }

    private static bool IsComplexFormat(string ext) => ext switch
    {
        "fbx" or "blend" or "dae" or "x" => true,
        _ => false
    };

    protected override string GetExecutablePath()
    {
        var exeName = OperatingSystem.IsWindows() ? "assimp.exe" : "assimp";

        // Check tools directory
        var toolPath = Path.Combine(ToolsBasePath, "bin", exeName);
        if (File.Exists(toolPath))
            return toolPath;

        // Check for assimp_cmd variant
        var cmdName = OperatingSystem.IsWindows() ? "assimp_cmd.exe" : "assimp_cmd";
        var cmdPath = Path.Combine(ToolsBasePath, "bin", cmdName);
        if (File.Exists(cmdPath))
            return cmdPath;

        // Check common installation paths
        if (OperatingSystem.IsWindows())
        {
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var assimpPath = Path.Combine(programFiles, "Assimp", "bin", "x64", "assimp.exe");
            if (File.Exists(assimpPath))
                return assimpPath;
        }

        // Check PATH
        var pathDirs = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator) ?? [];
        foreach (var dir in pathDirs)
        {
            var fullPath = Path.Combine(dir, exeName);
            if (File.Exists(fullPath))
                return fullPath;

            var cmdFullPath = Path.Combine(dir, cmdName);
            if (File.Exists(cmdFullPath))
                return cmdFullPath;
        }

        return toolPath;
    }

    public override ConversionProgress? ParseProgress(string line, ConversionJob job)
    {
        if (string.IsNullOrWhiteSpace(line))
            return null;

        // Try percentage format
        var percentMatch = PercentRegex().Match(line);
        if (percentMatch.Success)
        {
            var percent = int.Parse(percentMatch.Groups[1].Value);
            return new ConversionProgress
            {
                Percent = percent,
                Stage = ConversionStage.Encoding,
                StatusMessage = $"Processing... {percent}%",
                RawOutput = line
            };
        }

        // Try mesh progress format
        var meshMatch = MeshProgressRegex().Match(line);
        if (meshMatch.Success)
        {
            var current = int.Parse(meshMatch.Groups[1].Value);
            var total = int.Parse(meshMatch.Groups[2].Value);
            var percent = total > 0 ? (double)current / total * 100 : 0;

            return new ConversionProgress
            {
                Percent = percent,
                Stage = ConversionStage.Encoding,
                StatusMessage = $"Processing mesh {current}/{total}",
                RawOutput = line
            };
        }

        // Check for stage indicators
        if (line.Contains("Loading", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Stage = ConversionStage.Initializing,
                StatusMessage = "Loading model...",
                RawOutput = line
            };
        }

        if (line.Contains("Exporting", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Percent = 90,
                Stage = ConversionStage.Finalizing,
                StatusMessage = "Exporting...",
                RawOutput = line
            };
        }

        if (line.Contains("Successfully", StringComparison.OrdinalIgnoreCase))
        {
            return new ConversionProgress
            {
                Percent = 100,
                Stage = ConversionStage.Finalizing,
                StatusMessage = "Completed",
                RawOutput = line
            };
        }

        return null;
    }
}
