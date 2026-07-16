using System.Text.Json.Serialization;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.UI.Services;

public sealed record SidecarHealthRequirement(
    string Engine,
    string Kind,
    string Name,
    string Status,
    string Detail,
    string Remediation,
    string? Path,
    string? Size);

public sealed record SidecarHealthReport(
    string Engine,
    bool CanRun,
    string Summary,
    string Detail,
    IReadOnlyList<SidecarHealthRequirement> Requirements);

public interface ISidecarHealthService
{
    Task<SidecarHealthReport> EvaluateAsync(UiPreset preset, CancellationToken cancellationToken = default);
    Task<SidecarHealthReport> EvaluateEngineAsync(string engine, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<SidecarHealthReport>> EvaluateAllAsync(
        IEnumerable<UiPreset> presets,
        CancellationToken cancellationToken = default);
}

public sealed class SidecarHealthService : ISidecarHealthService
{
    private static readonly HashSet<string> ModelEngines = new(StringComparer.OrdinalIgnoreCase)
    {
        "alphacut", "bgremove", "demucs", "facerestore", "gfpgan", "inpaint",
        "lipsight", "ocrpro", "premiumtts", "realesrgan", "anime-upscale",
        "sdkit", "speechenhance", "stemkit", "superres", "translatekit",
        "vertigo", "video-face-enhance", "videosubtitleremover", "whisper-cpp",
        "whisper-stt"
    };

    private static readonly HashSet<string> VulkanEngines = new(StringComparer.OrdinalIgnoreCase)
    {
        "realesrgan", "anime-upscale", "video-face-enhance"
    };

    private static readonly HashSet<string> CudaOptionalEngines = new(StringComparer.OrdinalIgnoreCase)
    {
        "demucs", "facerestore", "gfpgan", "ocrpro", "premiumtts", "sdkit",
        "speechenhance", "stemkit", "superres", "translatekit", "whisper-stt"
    };

    private static readonly Dictionary<string, ToolRequirement[]> EngineToolRequirements = new(StringComparer.OrdinalIgnoreCase)
    {
        ["ab-av1"] = [ToolRequirement.External("ab-av1", "ab-av1", "ab-av1 encoder helper")],
        ["archive"] = [ToolRequirement.External("7z", "7z", "7-Zip")],
        ["audio-compressor"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["audiomastering"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["audiomore"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["audiopro"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["auto-edit"] = [ToolRequirement.External("auto-editor", "auto-editor", "auto-editor")],
        ["chaptermark"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["clipforge"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["docconvert"] = [ToolRequirement.Managed("libreoffice", "soffice", "LibreOffice")],
        ["ebookconvert"] = [ToolRequirement.Managed("calibre", "ebook-convert", "Calibre")],
        ["ebookmore"] = [ToolRequirement.Managed("calibre", "ebook-convert", "Calibre")],
        ["exiftool-meta"] = [ToolRequirement.External("exiftool", "exiftool", "ExifTool")],
        ["framesnap"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["gifstudio"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["heicshift"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["legacyoffice"] = [ToolRequirement.Managed("libreoffice", "soffice", "LibreOffice")],
        ["ocr"] = [ToolRequirement.External("tesseract", "tesseract", "Tesseract OCR")],
        ["pandoc-cli"] = [ToolRequirement.Managed("pandoc", "pandoc", "Pandoc")],
        ["pdfocr"] = [ToolRequirement.External("tesseract", "tesseract", "Tesseract OCR")],
        ["recordcast"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["scenedetect"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["slideshow"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["streamkeep"] =
        [
            ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg"),
            ToolRequirement.Managed("yt-dlp", "yt-dlp", "yt-dlp"),
            ToolRequirement.Recommended("deno", "deno", "Deno JavaScript runtime"),
        ],
        ["subocr"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg"), ToolRequirement.External("tesseract", "tesseract", "Tesseract OCR")],
        ["vectorkit"] = [ToolRequirement.Managed("inkscape", "inkscape", "Inkscape")],
        ["videocrush"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["video-face-enhance"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["videopro"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["voice-changer"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["whisper-cpp"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
        ["whisper-stt"] = [ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg")],
    };

    private readonly ISidecarRunner _runner;
    private readonly IToolManager _toolManager;
    private readonly IToolDownloader? _toolDownloader;
    private readonly Dictionary<string, SidecarManifest> _manifestCache = new(StringComparer.OrdinalIgnoreCase);

    public SidecarHealthService(
        ISidecarRunner runner,
        IToolManager toolManager,
        IToolDownloader? toolDownloader = null)
    {
        _runner = runner;
        _toolManager = toolManager;
        _toolDownloader = toolDownloader;
    }

    private SidecarManifest? LoadManifest(string engine)
    {
        if (_manifestCache.TryGetValue(engine, out var cached))
            return cached;

        var sidecarPath = _runner.Locate(engine);
        if (sidecarPath is null) return null;

        var manifestPath = Path.Combine(Path.GetDirectoryName(sidecarPath)!, "ucx.sidecar.json");
        if (!File.Exists(manifestPath))
        {
            var toolsDir = Path.GetDirectoryName(Path.GetDirectoryName(sidecarPath));
            if (toolsDir is not null)
                manifestPath = Path.Combine(toolsDir, engine, "ucx.sidecar.json");
        }

        if (!File.Exists(manifestPath)) return null;

        try
        {
            var json = File.ReadAllText(manifestPath);
            var manifest = System.Text.Json.JsonSerializer.Deserialize<SidecarManifest>(json,
                new System.Text.Json.JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            if (manifest is not null)
                _manifestCache[engine] = manifest;
            return manifest;
        }
        catch
        {
            return null;
        }
    }

    private bool HasModels(string engine)
    {
        var manifest = LoadManifest(engine);
        if (manifest?.Models == true) return true;
        return ModelEngines.Contains(engine);
    }

    private string? GpuKind(string engine)
    {
        var manifest = LoadManifest(engine);
        if (manifest?.Gpu is not null) return manifest.Gpu;
        if (VulkanEngines.Contains(engine)) return "vulkan";
        if (CudaOptionalEngines.Contains(engine)) return "cuda-optional";
        return null;
    }

    private IEnumerable<ToolRequirement> ManifestTools(string engine)
    {
        var manifest = LoadManifest(engine);
        if (manifest?.Tools is null or { Count: 0 }) yield break;
        foreach (var t in manifest.Tools)
        {
            yield return !t.Required
                ? ToolRequirement.Recommended(t.Id, t.Executable, t.Display)
                : t.Managed
                    ? ToolRequirement.Managed(t.Id, t.Executable, t.Display)
                    : ToolRequirement.External(t.Id, t.Executable, t.Display);
        }
    }

    private sealed record SidecarManifest(
        string? Engine = null,
        List<ManifestTool>? Tools = null,
        bool? Models = null,
        string? Gpu = null);

    private sealed record ManifestTool(
        string Id = "",
        string Executable = "",
        string Display = "",
        bool Managed = false,
        bool Required = true);

    public async Task<SidecarHealthReport> EvaluateAsync(
        UiPreset preset,
        CancellationToken cancellationToken = default)
        => await EvaluateCoreAsync(preset.Engine, preset.Args, cancellationToken);

    public async Task<SidecarHealthReport> EvaluateEngineAsync(
        string engine,
        CancellationToken cancellationToken = default)
        => await EvaluateCoreAsync(engine, [], cancellationToken);

    private async Task<SidecarHealthReport> EvaluateCoreAsync(
        string engine,
        IReadOnlyList<string> presetArgs,
        CancellationToken cancellationToken)
    {
        var rows = new List<SidecarHealthRequirement>();
        var sidecarPath = _runner.Locate(engine);
        rows.Add(sidecarPath is null
            ? MissingSidecar(engine)
            : Ready(engine, "sidecar", $"{engine}.exe", "Frozen sidecar binary found.", "", sidecarPath, SizeOf(sidecarPath)));

        foreach (var tool in ToolRequirementsFor(engine, presetArgs))
            rows.Add(await EvaluateToolAsync(engine, tool, cancellationToken));

        if (HasModels(engine))
            rows.Add(EvaluateModelCache(engine, sidecarPath));

        var gpu = GpuKind(engine);
        if (gpu == "vulkan")
            rows.Add(EvaluateVulkan(engine));
        else if (gpu == "cuda-optional")
            rows.Add(new SidecarHealthRequirement(
                engine,
                "gpu",
                "CUDA / GPU acceleration",
                "Optional",
                "CPU fallback is expected; GPU speedup is detected by the sidecar runtime.",
                "Install the vendor GPU driver and CUDA/cuDNN packages only when you want accelerated inference.",
                null,
                null));

        var blockers = rows.Where(r => r.Status == "Missing").ToList();
        var warnings = rows.Where(r => r.Status == "Warning").ToList();
        var summary = blockers.Count > 0
            ? $"Blocked: {blockers[0].Name}"
            : warnings.Count > 0
                ? $"Ready with warning: {warnings[0].Name}"
                : "Ready";
        var detail = blockers.Count > 0
            ? blockers[0].Remediation
            : warnings.Count > 0
                ? warnings[0].Detail + " " + warnings[0].Remediation
                : $"All required checks passed for {engine}.";

        return new SidecarHealthReport(
            engine,
            CanRun: blockers.Count == 0,
            Summary: summary,
            Detail: detail.Trim(),
            Requirements: rows);
    }

    public async Task<IReadOnlyList<SidecarHealthReport>> EvaluateAllAsync(
        IEnumerable<UiPreset> presets,
        CancellationToken cancellationToken = default)
    {
        var reports = new List<SidecarHealthReport>();
        var representativePresets = presets
            .GroupBy(p => p.Engine, StringComparer.OrdinalIgnoreCase)
            .Select(g => g.First())
            .ToList();

        // Keep probes serialized. ToolManager caches the first result for each
        // executable, while serialization avoids concurrent process/file races.
        foreach (var preset in representativePresets)
        {
            cancellationToken.ThrowIfCancellationRequested();
            reports.Add(await EvaluateAsync(preset, cancellationToken));
        }

        return reports
            .OrderBy(r => r.CanRun)
            .ThenBy(r => r.Engine, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private IEnumerable<ToolRequirement> ToolRequirementsFor(
        string engine,
        IReadOnlyList<string> presetArgs)
    {
        var fromManifest = ManifestTools(engine).ToList();
        if (fromManifest.Count > 0)
        {
            foreach (var tool in fromManifest)
                yield return tool;
        }
        else if (EngineToolRequirements.TryGetValue(engine, out var tools))
        {
            foreach (var tool in tools)
                yield return tool;
        }

        if (engine.Equals("realesrgan", StringComparison.OrdinalIgnoreCase)
            && presetArgs.Any(arg => arg.Contains("video", StringComparison.OrdinalIgnoreCase)))
        {
            yield return ToolRequirement.Managed("ffmpeg", "ffmpeg", "FFmpeg");
        }
    }

    private async Task<SidecarHealthRequirement> EvaluateToolAsync(
        string engine,
        ToolRequirement tool,
        CancellationToken cancellationToken)
    {
        var canonicalId = ToolVersionPolicy.Canonicalize(tool.Id);
        var requirement = ToolVersionPolicy.GetRequirement(canonicalId);
        var path = tool.IsManaged || requirement is not null
            ? GetManagedToolPath(canonicalId) ?? FindExecutable(tool.Executable)
            : FindExecutable(tool.Executable);
        if (!string.IsNullOrWhiteSpace(path) && File.Exists(path))
        {
            if (requirement is not null)
            {
                string? version = null;
                try
                {
                    version = await _toolManager.GetToolVersionAsync(canonicalId, cancellationToken);
                }
                catch (OperationCanceledException)
                {
                    throw;
                }
                catch
                {
                    // An unreadable version is reported as a warning below.
                }

                var assessment = ToolVersionPolicy.Assess(canonicalId, version);
                if (!assessment.MeetsMinimum)
                {
                    var detail = assessment.VersionKnown
                        ? $"{tool.DisplayName} {assessment.DetectedVersion} is below the security floor {requirement.MinimumVersion}."
                        : $"{tool.DisplayName} was found, but its version could not be verified against the security floor {requirement.MinimumVersion}.";
                    return new SidecarHealthRequirement(
                        engine,
                        "external-tool",
                        tool.DisplayName,
                        "Warning",
                        detail,
                        $"Upgrade {tool.DisplayName} to {requirement.MinimumVersion} or newer ({requirement.SecurityReason}).",
                        path,
                        SizeOf(path));
                }

                return Ready(
                    engine,
                    "external-tool",
                    tool.DisplayName,
                    $"{tool.DisplayName} {assessment.DetectedVersion} meets the security floor {requirement.MinimumVersion}.",
                    "",
                    path,
                    SizeOf(path));
            }

            return Ready(
                engine,
                "external-tool",
                tool.DisplayName,
                $"{tool.DisplayName} found.",
                "",
                path,
                SizeOf(path));
        }

        var downloadInfo = _toolDownloader?.GetToolDownloadInfo(tool.Id);
        var remediation = downloadInfo is null
            ? $"Install {tool.DisplayName} and add '{tool.Executable}' to PATH or the configured UCX tools folder."
            : $"Install from Settings > Converter Tools or run `ucx tools download {tool.Id}`; SHA-256 verification is required before UCX promotes the download.";

        var status = tool.IsRequired ? "Missing" : "Warning";
        var missingDetail = tool.IsRequired
            ? $"{tool.DisplayName} is required before this preset can run."
            : $"{tool.DisplayName} is required for full YouTube format extraction; other sites can still run.";
        return new SidecarHealthRequirement(
            engine,
            "external-tool",
            tool.DisplayName,
            status,
            missingDetail,
            remediation,
            null,
            downloadInfo is null ? null : "Resolved from release metadata during download");
    }

    private string? GetManagedToolPath(string toolId)
    {
        try
        {
            var path = _toolManager.GetToolPath(toolId);
            return File.Exists(path) ? path : null;
        }
        catch
        {
            return null;
        }
    }

    private static SidecarHealthRequirement EvaluateModelCache(string engine, string? sidecarPath)
    {
        var candidates = ModelDirectories(engine, sidecarPath);
        var populated = candidates.FirstOrDefault(HasModelFiles);
        if (populated is not null)
        {
            return Ready(
                engine,
                "model-cache",
                "Model weights",
                "Model files found.",
                "",
                populated,
                null);
        }

        var detail = candidates.Count == 0
            ? "No model cache directory was discovered."
            : "No local model files were found in " + string.Join(", ", candidates.Select(Path.GetFileName));
        return new SidecarHealthRequirement(
            engine,
            "model-cache",
            "Model weights",
            "Warning",
            detail,
            $"Run `pwsh tools/{engine}/build.ps1` or the engine's model/probe command while online, then retry. Offline runs may fail until weights exist under tools/_models or tools/{engine}/models.",
            null,
            null);
    }

    private static SidecarHealthRequirement EvaluateVulkan(string engine)
    {
        var vulkanInfo = FindExecutable("vulkaninfo");
        return vulkanInfo is null
            ? new SidecarHealthRequirement(
                engine,
                "gpu",
                "Vulkan GPU runtime",
                "Warning",
                "Vulkan runtime could not be probed because vulkaninfo.exe is not on PATH.",
                "Install current GPU drivers. Real-ESRGAN ncnn-vulkan engines will report the exact device error at runtime if Vulkan is unavailable.",
                null,
                null)
            : Ready(engine, "gpu", "Vulkan GPU runtime", "vulkaninfo.exe is available for GPU capability probing.", "", vulkanInfo, SizeOf(vulkanInfo));
    }

    private static SidecarHealthRequirement MissingSidecar(string engine) =>
        new(
            engine,
            "sidecar",
            $"{engine}.exe",
            "Missing",
            $"UCX could not locate the frozen {engine} sidecar.",
            $"Build it with `pwsh tools/{engine}/build.ps1` or place {engine}.exe under %LocalAppData%/UniversalConverterX/tools/{engine}/{engine}.exe.",
            null,
            null);

    private static SidecarHealthRequirement Ready(
        string engine,
        string kind,
        string name,
        string detail,
        string remediation,
        string? path,
        string? size) =>
        new(engine, kind, name, "Ready", detail, remediation, path, size);

    private static IReadOnlyList<string> ModelDirectories(string engine, string? sidecarPath)
    {
        var dirs = new List<string>();
        if (!string.IsNullOrWhiteSpace(sidecarPath))
        {
            var sidecarDir = Path.GetDirectoryName(sidecarPath);
            if (!string.IsNullOrWhiteSpace(sidecarDir))
                dirs.Add(Path.Combine(sidecarDir, "models"));
        }

        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var tools = Path.Combine(dir.FullName, "tools");
            if (Directory.Exists(tools))
            {
                dirs.Add(Path.Combine(tools, engine, "models"));
                dirs.Add(Path.Combine(tools, "_models"));
                break;
            }
            dir = dir.Parent;
        }

        var localTools = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX",
            "tools");
        dirs.Add(Path.Combine(localTools, engine, "models"));
        dirs.Add(Path.Combine(localTools, "_models"));

        return dirs
            .Where(d => !string.IsNullOrWhiteSpace(d))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static bool HasModelFiles(string directory)
    {
        try
        {
            return Directory.Exists(directory)
                && Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories)
                    .Any(f => !Path.GetFileName(f).Equals(".gitkeep", StringComparison.OrdinalIgnoreCase));
        }
        catch
        {
            return false;
        }
    }

    private static string? FindExecutable(string executable)
    {
        var exeName = OperatingSystem.IsWindows() && !executable.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
            ? executable + ".exe"
            : executable;
        var path = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var dir in path.Split(Path.PathSeparator))
        {
            try
            {
                if (string.IsNullOrWhiteSpace(dir))
                    continue;

                var candidate = Path.Combine(dir.Trim(), exeName);
                if (File.Exists(candidate))
                    return candidate;
            }
            catch { }
        }
        return null;
    }

    private static string? SizeOf(string path)
    {
        try
        {
            var len = new FileInfo(path).Length;
            return len < 1024 * 1024
                ? $"{len / 1024.0:F1} KB"
                : $"{len / 1024.0 / 1024.0:F1} MB";
        }
        catch
        {
            return null;
        }
    }

    private sealed record ToolRequirement(
        string Id,
        string Executable,
        string DisplayName,
        [property: JsonIgnore] bool IsManaged,
        [property: JsonIgnore] bool IsRequired)
    {
        public static ToolRequirement Managed(string id, string executable, string displayName) =>
            new(id, executable, displayName, true, true);

        public static ToolRequirement External(string id, string executable, string displayName) =>
            new(id, executable, displayName, false, true);

        public static ToolRequirement Recommended(string id, string executable, string displayName) =>
            new(id, executable, displayName, true, false);
    }
}
