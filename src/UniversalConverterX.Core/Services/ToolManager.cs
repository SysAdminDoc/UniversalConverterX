using System.Diagnostics;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;

namespace UniversalConverterX.Core.Services;

/// <summary>
/// Manages CLI tool binaries and their availability
/// </summary>
public class ToolManager : IToolManager
{
    private readonly ILogger<ToolManager>? _logger;
    private readonly ConverterXOptions _options;
    private readonly Dictionary<string, ToolDefinition> _toolDefinitions;
    private readonly Dictionary<string, string?> _versionCache = [];

    public ToolManager(IOptions<ConverterXOptions> options, ILogger<ToolManager>? logger = null)
    {
        _options = options.Value;
        _logger = logger;
        _toolDefinitions = InitializeToolDefinitions();
    }

    public string ToolsBasePath => _options.ToolsBasePath;

    public string GetToolPath(string toolName)
    {
        if (!_toolDefinitions.TryGetValue(toolName.ToLowerInvariant(), out var def))
        {
            throw new ArgumentException($"Unknown tool: {toolName}", nameof(toolName));
        }

        var exeName = OperatingSystem.IsWindows() ? $"{def.Executable}.exe" : def.Executable;

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

        // Check common installation paths
        var commonPaths = GetCommonPaths(def.Executable);
        foreach (var path in commonPaths)
        {
            if (File.Exists(path))
                return path;
        }

        // Return expected path even if not found
        return toolPath;
    }

    public bool IsToolAvailable(string toolName)
    {
        var path = GetToolPath(toolName);
        return File.Exists(path);
    }

    public async Task<string?> GetToolVersionAsync(string toolName, CancellationToken cancellationToken = default)
    {
        if (_versionCache.TryGetValue(toolName, out var cachedVersion))
            return cachedVersion;

        if (!IsToolAvailable(toolName))
        {
            _versionCache[toolName] = null;
            return null;
        }

        var path = GetToolPath(toolName);
        var def = _toolDefinitions[toolName.ToLowerInvariant()];

        try
        {
            using var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = path,
                    Arguments = def.VersionArg,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                }
            };

            process.Start();
            var output = await process.StandardOutput.ReadToEndAsync(cancellationToken);
            var error = await process.StandardError.ReadToEndAsync(cancellationToken);
            
            await process.WaitForExitAsync(cancellationToken);

            var allOutput = output + error;
            var version = ExtractVersion(allOutput);
            _versionCache[toolName] = version;
            
            return version;
        }
        catch (Exception ex)
        {
            _logger?.LogWarning(ex, "Failed to get version for {Tool}", toolName);
            _versionCache[toolName] = null;
            return null;
        }
    }

    public Task<ToolDownloadResult> DownloadToolAsync(
        string toolName,
        IProgress<DownloadProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        // Placeholder - actual download implementation would go here
        _logger?.LogWarning("Tool download not implemented. Please install {Tool} manually.", toolName);
        
        return Task.FromResult(new ToolDownloadResult(
            Success: false,
            ToolName: toolName,
            Version: null,
            ErrorMessage: "Automatic download not implemented. Please install manually."));
    }

    public IReadOnlyCollection<ToolInfo> GetAvailableTools()
    {
        var tools = new List<ToolInfo>();

        foreach (var (id, def) in _toolDefinitions)
        {
            var path = GetToolPath(id);
            var isInstalled = File.Exists(path);
            long? size = null;
            
            if (isInstalled)
            {
                try
                {
                    size = new FileInfo(path).Length;
                }
                catch { }
            }

            _versionCache.TryGetValue(id, out var version);

            tools.Add(new ToolInfo(
                Id: id,
                Name: def.Name,
                Version: version,
                ExecutableName: def.Executable,
                IsInstalled: isInstalled,
                SizeBytes: size,
                Description: def.Description));
        }

        return tools;
    }

    public async Task<bool> VerifyToolIntegrityAsync(string toolName, CancellationToken cancellationToken = default)
    {
        if (!IsToolAvailable(toolName))
            return false;

        // Basic verification - try to run version command
        var version = await GetToolVersionAsync(toolName, cancellationToken);
        return version != null;
    }

    private static Dictionary<string, ToolDefinition> InitializeToolDefinitions()
    {
        return new Dictionary<string, ToolDefinition>
        {
            ["ffmpeg"] = new("ffmpeg", "FFmpeg", "-version", "Video and audio processing"),
            ["imagemagick"] = new("magick", "ImageMagick", "--version", "Image processing and conversion"),
            ["pandoc"] = new("pandoc", "Pandoc", "--version", "Universal document converter"),
            ["calibre"] = new("ebook-convert", "Calibre", "--version", "E-book conversion"),
            ["libreoffice"] = new("soffice", "LibreOffice", "--version", "Office document conversion"),
            ["inkscape"] = new("inkscape", "Inkscape", "--version", "Vector graphics editor"),
            ["ghostscript"] = new(OperatingSystem.IsWindows() ? "gswin64c" : "gs", "Ghostscript", "--version", "PDF and PostScript processing"),
        };
    }

    private static string[] GetCommonPaths(string executable)
    {
        if (OperatingSystem.IsWindows())
        {
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);

            return executable switch
            {
                "ffmpeg" => [
                    $@"{programFiles}\FFmpeg\bin\ffmpeg.exe",
                    $@"{programFilesX86}\FFmpeg\bin\ffmpeg.exe"
                ],
                "magick" => [
                    $@"{programFiles}\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
                ],
                "soffice" => [
                    $@"{programFiles}\LibreOffice\program\soffice.exe"
                ],
                "ebook-convert" => [
                    $@"{programFiles}\Calibre2\ebook-convert.exe"
                ],
                "inkscape" => [
                    $@"{programFiles}\Inkscape\bin\inkscape.exe"
                ],
                "gswin64c" => [
                    $@"{programFiles}\gs\gs10.02.1\bin\gswin64c.exe"
                ],
                _ => []
            };
        }
        else if (OperatingSystem.IsMacOS())
        {
            return executable switch
            {
                "soffice" => ["/Applications/LibreOffice.app/Contents/MacOS/soffice"],
                "ebook-convert" => ["/Applications/calibre.app/Contents/MacOS/ebook-convert"],
                "inkscape" => ["/Applications/Inkscape.app/Contents/MacOS/inkscape"],
                _ => [$"/usr/local/bin/{executable}", $"/opt/homebrew/bin/{executable}"]
            };
        }

        return [$"/usr/bin/{executable}", $"/usr/local/bin/{executable}"];
    }

    private static string? ExtractVersion(string output)
    {
        if (string.IsNullOrWhiteSpace(output))
            return null;

        var lines = output.Split('\n');
        var firstLine = lines.FirstOrDefault()?.Trim();

        if (string.IsNullOrEmpty(firstLine))
            return null;

        // Try to extract version number
        var parts = firstLine.Split(' ');
        foreach (var part in parts)
        {
            if (part.Any(char.IsDigit) && part.Contains('.'))
            {
                var cleaned = part.Trim(',', ')', '(', 'v', 'V');
                if (cleaned.Length > 0 && char.IsDigit(cleaned[0]))
                    return cleaned;
            }
        }

        return firstLine.Length > 50 ? firstLine[..50] + "..." : firstLine;
    }

    private record ToolDefinition(string Executable, string Name, string VersionArg, string Description);
}
