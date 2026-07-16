using System.Text.Json.Serialization;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Services;
using UniversalConverterX.Core.Utilities;

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

        var manifestPath = FindManifestPath(engine);
        if (manifestPath is null) return null;

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

    private string? FindManifestPath(string engine)
    {
        if (string.IsNullOrWhiteSpace(engine)
            || engine is "." or ".."
            || engine.Any(character =>
                !(char.IsAsciiLetterOrDigit(character) || character is '-' or '_' or '.')))
        {
            return null;
        }

        var candidates = new List<string>();
        var sidecarPath = _runner.Locate(engine);
        if (!string.IsNullOrWhiteSpace(sidecarPath))
        {
            var sidecarDirectory = Path.GetDirectoryName(sidecarPath);
            if (!string.IsNullOrWhiteSpace(sidecarDirectory))
            {
                candidates.Add(Path.Combine(sidecarDirectory, "ucx.sidecar.json"));
                var directoryName = Path.GetFileName(sidecarDirectory);
                var engineDirectory = directoryName.Equals("dist", StringComparison.OrdinalIgnoreCase)
                    || directoryName.Equals("bin", StringComparison.OrdinalIgnoreCase)
                        ? Path.GetDirectoryName(sidecarDirectory)
                        : sidecarDirectory;
                if (!string.IsNullOrWhiteSpace(engineDirectory))
                    candidates.Add(Path.Combine(engineDirectory, "ucx.sidecar.json"));
                var toolsDirectory = string.IsNullOrWhiteSpace(engineDirectory)
                    ? null
                    : Path.GetDirectoryName(engineDirectory);
                if (!string.IsNullOrWhiteSpace(toolsDirectory))
                    candidates.Add(Path.Combine(toolsDirectory, engine, "ucx.sidecar.json"));
            }
        }

        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            candidates.Add(Path.Combine(directory.FullName, "tools", engine, "ucx.sidecar.json"));
            directory = directory.Parent;
        }

        candidates.Add(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX",
            "tools",
            engine,
            "ucx.sidecar.json"));

        return candidates
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .FirstOrDefault(File.Exists);
    }

    private bool HasModels(string engine)
    {
        return LoadManifest(engine)?.Models == true;
    }

    private string? GpuKind(string engine)
    {
        return LoadManifest(engine)?.Gpu;
    }

    private IEnumerable<ToolRequirement> ManifestTools(
        string engine,
        IReadOnlyList<string> presetArgs)
    {
        var manifest = LoadManifest(engine);
        if (manifest?.Tools is null or { Count: 0 }) yield break;
        foreach (var t in manifest.Tools)
        {
            if (!string.IsNullOrWhiteSpace(t.WhenArgContains)
                && !presetArgs.Any(argument =>
                    argument.Contains(t.WhenArgContains, StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

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
        bool Required = true,
        string? WhenArgContains = null);

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
            : Ready(engine, "sidecar", Path.GetFileName(sidecarPath), "Frozen sidecar binary found.", "", sidecarPath, SizeOf(sidecarPath)));

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
        foreach (var tool in ManifestTools(engine, presetArgs))
            yield return tool;
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
        path ??= FindBundledExecutable(engine, tool.Executable);
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
            SidecarNaming.ExecutableName(engine),
            "Missing",
            $"UCX could not locate the frozen {engine} sidecar.",
            $"Build it with `pwsh tools/{engine}/build.ps1` or place {SidecarNaming.ExecutableName(engine)} under %LocalAppData%/UniversalConverterX/tools/{engine}/.",
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

    private string? FindBundledExecutable(string engine, string executable)
    {
        var sidecarPath = _runner.Locate(engine);
        var sidecarDir = sidecarPath is null ? null : Path.GetDirectoryName(sidecarPath);
        if (string.IsNullOrWhiteSpace(sidecarDir))
            return null;

        var engineDir = Path.GetFileName(sidecarDir).Equals("dist", StringComparison.OrdinalIgnoreCase)
            || Path.GetFileName(sidecarDir).Equals("bin", StringComparison.OrdinalIgnoreCase)
                ? Path.GetDirectoryName(sidecarDir)
                : sidecarDir;
        if (string.IsNullOrWhiteSpace(engineDir))
            return null;

        var exeName = OperatingSystem.IsWindows() && !executable.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)
            ? executable + ".exe"
            : executable;
        var toolsDir = Path.GetDirectoryName(engineDir);
        var directories = new[]
        {
            sidecarDir,
            engineDir,
            toolsDir is null ? null : Path.Combine(toolsDir, "_bin"),
        };
        foreach (var directory in directories.Where(d => !string.IsNullOrWhiteSpace(d)).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var candidate = Path.Combine(directory!, exeName);
            if (File.Exists(candidate))
                return candidate;
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
