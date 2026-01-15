using System.Diagnostics;
using System.IO.Compression;
using System.Net.Http.Json;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;

namespace UniversalConverterX.Core.Services;

/// <summary>
/// Service for downloading, installing, and managing CLI tool binaries
/// </summary>
public class ToolDownloader : IToolDownloader
{
    private readonly ILogger<ToolDownloader>? _logger;
    private readonly ConverterXOptions _options;
    private readonly HttpClient _httpClient;
    private readonly Dictionary<string, ToolDownloadInfo> _toolDownloadInfo;
    
    private static readonly string _platform = GetPlatformIdentifier();
    private static readonly string _architecture = GetArchitectureIdentifier();

    public ToolDownloader(
        IOptions<ConverterXOptions> options,
        HttpClient httpClient,
        ILogger<ToolDownloader>? logger = null)
    {
        _options = options.Value;
        _httpClient = httpClient;
        _logger = logger;
        _toolDownloadInfo = InitializeToolDownloadInfo();
        
        // Ensure tools directory exists
        var binDir = Path.Combine(_options.ToolsBasePath, "bin");
        if (!Directory.Exists(binDir))
            Directory.CreateDirectory(binDir);
    }

    /// <summary>
    /// Download and install a tool
    /// </summary>
    public async Task<ToolDownloadResult> DownloadToolAsync(
        string toolName,
        IProgress<DownloadProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        toolName = toolName.ToLowerInvariant();
        
        if (!_toolDownloadInfo.TryGetValue(toolName, out var downloadInfo))
        {
            return new ToolDownloadResult(
                Success: false,
                ToolName: toolName,
                Version: null,
                ErrorMessage: $"Unknown tool: {toolName}");
        }

        try
        {
            _logger?.LogInformation("Starting download of {Tool}", toolName);

            // Get the download URL for current platform
            var downloadUrl = await GetDownloadUrlAsync(downloadInfo, cancellationToken);
            if (string.IsNullOrEmpty(downloadUrl))
            {
                return new ToolDownloadResult(
                    Success: false,
                    ToolName: toolName,
                    Version: null,
                    ErrorMessage: $"No download available for {toolName} on {_platform}-{_architecture}");
            }

            _logger?.LogDebug("Download URL: {Url}", downloadUrl);

            // Create temp directory for download
            var tempDir = Path.Combine(Path.GetTempPath(), $"ucx-download-{Guid.NewGuid()}");
            Directory.CreateDirectory(tempDir);

            try
            {
                // Download the file
                var downloadPath = Path.Combine(tempDir, GetFilenameFromUrl(downloadUrl));
                await DownloadFileAsync(downloadUrl, downloadPath, progress, cancellationToken);

                // Verify checksum if available
                if (!string.IsNullOrEmpty(downloadInfo.ExpectedChecksum))
                {
                    var actualChecksum = await ComputeFileChecksumAsync(downloadPath, cancellationToken);
                    if (!string.Equals(actualChecksum, downloadInfo.ExpectedChecksum, StringComparison.OrdinalIgnoreCase))
                    {
                        _logger?.LogWarning("Checksum mismatch for {Tool}. Expected: {Expected}, Got: {Actual}",
                            toolName, downloadInfo.ExpectedChecksum, actualChecksum);
                        // Continue anyway with warning - checksums change between versions
                    }
                }

                // Extract and install
                var installPath = Path.Combine(_options.ToolsBasePath, "bin");
                await ExtractAndInstallAsync(downloadPath, installPath, downloadInfo, cancellationToken);

                // Verify installation
                var exePath = GetExecutablePath(toolName);
                if (!File.Exists(exePath))
                {
                    return new ToolDownloadResult(
                        Success: false,
                        ToolName: toolName,
                        Version: null,
                        ErrorMessage: "Installation failed - executable not found after extraction");
                }

                // Make executable on Unix
                if (!OperatingSystem.IsWindows())
                {
                    await MakeExecutableAsync(exePath, cancellationToken);
                }

                // Get version
                var version = await GetInstalledVersionAsync(toolName, cancellationToken);

                _logger?.LogInformation("Successfully installed {Tool} version {Version}", toolName, version);

                return new ToolDownloadResult(
                    Success: true,
                    ToolName: toolName,
                    Version: version,
                    ErrorMessage: null);
            }
            finally
            {
                // Cleanup temp directory
                try
                {
                    if (Directory.Exists(tempDir))
                        Directory.Delete(tempDir, recursive: true);
                }
                catch { }
            }
        }
        catch (OperationCanceledException)
        {
            return new ToolDownloadResult(
                Success: false,
                ToolName: toolName,
                Version: null,
                ErrorMessage: "Download cancelled");
        }
        catch (Exception ex)
        {
            _logger?.LogError(ex, "Failed to download {Tool}", toolName);
            return new ToolDownloadResult(
                Success: false,
                ToolName: toolName,
                Version: null,
                ErrorMessage: ex.Message);
        }
    }

    /// <summary>
    /// Download multiple tools
    /// </summary>
    public async Task<IReadOnlyList<ToolDownloadResult>> DownloadToolsAsync(
        IEnumerable<string> toolNames,
        IProgress<BatchDownloadProgress>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var tools = toolNames.ToList();
        var results = new List<ToolDownloadResult>();
        var completed = 0;

        foreach (var tool in tools)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var toolProgress = new Progress<DownloadProgress>(p =>
            {
                progress?.Report(new BatchDownloadProgress(
                    CurrentTool: tool,
                    ToolsCompleted: completed,
                    TotalTools: tools.Count,
                    CurrentProgress: p));
            });

            var result = await DownloadToolAsync(tool, toolProgress, cancellationToken);
            results.Add(result);
            completed++;
        }

        return results;
    }

    /// <summary>
    /// Check for available updates
    /// </summary>
    public async Task<ToolUpdateInfo?> CheckForUpdateAsync(
        string toolName,
        CancellationToken cancellationToken = default)
    {
        toolName = toolName.ToLowerInvariant();

        if (!_toolDownloadInfo.TryGetValue(toolName, out var downloadInfo))
            return null;

        try
        {
            var currentVersion = await GetInstalledVersionAsync(toolName, cancellationToken);
            var latestVersion = await GetLatestVersionAsync(downloadInfo, cancellationToken);

            if (string.IsNullOrEmpty(currentVersion))
            {
                return new ToolUpdateInfo(
                    ToolName: toolName,
                    CurrentVersion: null,
                    LatestVersion: latestVersion,
                    UpdateAvailable: true,
                    IsInstalled: false);
            }

            var updateAvailable = !string.Equals(currentVersion, latestVersion, StringComparison.OrdinalIgnoreCase);

            return new ToolUpdateInfo(
                ToolName: toolName,
                CurrentVersion: currentVersion,
                LatestVersion: latestVersion,
                UpdateAvailable: updateAvailable,
                IsInstalled: true);
        }
        catch (Exception ex)
        {
            _logger?.LogWarning(ex, "Failed to check for updates for {Tool}", toolName);
            return null;
        }
    }

    /// <summary>
    /// Get download information for a tool
    /// </summary>
    public ToolDownloadInfo? GetToolDownloadInfo(string toolName)
    {
        return _toolDownloadInfo.GetValueOrDefault(toolName.ToLowerInvariant());
    }

    /// <summary>
    /// Get list of all downloadable tools
    /// </summary>
    public IReadOnlyList<string> GetDownloadableTools()
    {
        return _toolDownloadInfo.Keys.ToList();
    }

    private async Task DownloadFileAsync(
        string url,
        string destinationPath,
        IProgress<DownloadProgress>? progress,
        CancellationToken cancellationToken)
    {
        using var response = await _httpClient.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        response.EnsureSuccessStatusCode();

        var totalBytes = response.Content.Headers.ContentLength ?? -1;
        var bytesDownloaded = 0L;
        var lastReportTime = DateTime.UtcNow;

        await using var contentStream = await response.Content.ReadAsStreamAsync(cancellationToken);
        await using var fileStream = new FileStream(destinationPath, FileMode.Create, FileAccess.Write, FileShare.None, 8192, true);

        var buffer = new byte[8192];
        var startTime = DateTime.UtcNow;
        int bytesRead;

        while ((bytesRead = await contentStream.ReadAsync(buffer, cancellationToken)) > 0)
        {
            await fileStream.WriteAsync(buffer.AsMemory(0, bytesRead), cancellationToken);
            bytesDownloaded += bytesRead;

            // Report progress at most every 100ms
            if ((DateTime.UtcNow - lastReportTime).TotalMilliseconds >= 100)
            {
                var elapsed = DateTime.UtcNow - startTime;
                var speed = elapsed.TotalSeconds > 0 ? bytesDownloaded / elapsed.TotalSeconds : 0;

                progress?.Report(new DownloadProgress(
                    BytesDownloaded: bytesDownloaded,
                    TotalBytes: totalBytes,
                    SpeedBytesPerSecond: speed));

                lastReportTime = DateTime.UtcNow;
            }
        }

        // Final progress report
        var finalElapsed = DateTime.UtcNow - startTime;
        var finalSpeed = finalElapsed.TotalSeconds > 0 ? bytesDownloaded / finalElapsed.TotalSeconds : 0;
        progress?.Report(new DownloadProgress(bytesDownloaded, totalBytes, finalSpeed));
    }

    private async Task ExtractAndInstallAsync(
        string archivePath,
        string installPath,
        ToolDownloadInfo downloadInfo,
        CancellationToken cancellationToken)
    {
        var extension = Path.GetExtension(archivePath).ToLowerInvariant();

        switch (extension)
        {
            case ".zip":
                await ExtractZipAsync(archivePath, installPath, downloadInfo, cancellationToken);
                break;
            case ".gz":
            case ".tgz":
                await ExtractTarGzAsync(archivePath, installPath, downloadInfo, cancellationToken);
                break;
            case ".7z":
                await Extract7zAsync(archivePath, installPath, downloadInfo, cancellationToken);
                break;
            case ".exe":
            case ".msi":
                // For installers, we might need to run them silently
                await RunInstallerAsync(archivePath, downloadInfo, cancellationToken);
                break;
            default:
                // Assume it's a direct executable
                var destPath = Path.Combine(installPath, downloadInfo.ExecutableName + (OperatingSystem.IsWindows() ? ".exe" : ""));
                File.Copy(archivePath, destPath, overwrite: true);
                break;
        }
    }

    private async Task ExtractZipAsync(
        string zipPath,
        string installPath,
        ToolDownloadInfo downloadInfo,
        CancellationToken cancellationToken)
    {
        using var archive = ZipFile.OpenRead(zipPath);

        // Find the executable in the archive
        var exeName = downloadInfo.ExecutableName + (OperatingSystem.IsWindows() ? ".exe" : "");
        var entry = archive.Entries.FirstOrDefault(e => 
            e.Name.Equals(exeName, StringComparison.OrdinalIgnoreCase) ||
            e.FullName.EndsWith("/" + exeName, StringComparison.OrdinalIgnoreCase) ||
            e.FullName.EndsWith("\\" + exeName, StringComparison.OrdinalIgnoreCase));

        if (entry != null)
        {
            // Extract just the executable
            var destPath = Path.Combine(installPath, exeName);
            entry.ExtractToFile(destPath, overwrite: true);
        }
        else
        {
            // Extract all contents (might be nested in a folder)
            foreach (var e in archive.Entries)
            {
                cancellationToken.ThrowIfCancellationRequested();

                if (string.IsNullOrEmpty(e.Name))
                    continue;

                // Check if this looks like an executable we need
                if (ShouldExtractFile(e.Name, downloadInfo))
                {
                    var destPath = Path.Combine(installPath, e.Name);
                    e.ExtractToFile(destPath, overwrite: true);
                }
            }
        }
    }

    private async Task ExtractTarGzAsync(
        string tarGzPath,
        string installPath,
        ToolDownloadInfo downloadInfo,
        CancellationToken cancellationToken)
    {
        // Use tar command on Unix systems
        if (!OperatingSystem.IsWindows())
        {
            var tempExtract = Path.Combine(Path.GetTempPath(), $"ucx-extract-{Guid.NewGuid()}");
            Directory.CreateDirectory(tempExtract);

            try
            {
                var startInfo = new ProcessStartInfo
                {
                    FileName = "tar",
                    Arguments = $"-xzf \"{tarGzPath}\" -C \"{tempExtract}\"",
                    UseShellExecute = false,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                };

                using var process = Process.Start(startInfo);
                if (process != null)
                {
                    await process.WaitForExitAsync(cancellationToken);
                }

                // Find and copy the executable
                var exeName = downloadInfo.ExecutableName;
                var files = Directory.GetFiles(tempExtract, exeName, SearchOption.AllDirectories);
                if (files.Length > 0)
                {
                    File.Copy(files[0], Path.Combine(installPath, exeName), overwrite: true);
                }
            }
            finally
            {
                if (Directory.Exists(tempExtract))
                    Directory.Delete(tempExtract, recursive: true);
            }
        }
        else
        {
            // On Windows, use SharpCompress or 7-Zip
            _logger?.LogWarning("tar.gz extraction on Windows requires 7-Zip or manual extraction");
            throw new NotSupportedException("tar.gz extraction on Windows requires additional tools");
        }
    }

    private async Task Extract7zAsync(
        string archivePath,
        string installPath,
        ToolDownloadInfo downloadInfo,
        CancellationToken cancellationToken)
    {
        // Try to find 7z executable
        var sevenZipPath = Find7ZipExecutable();
        if (sevenZipPath == null)
        {
            throw new FileNotFoundException("7-Zip not found. Please install 7-Zip to extract this archive.");
        }

        var tempExtract = Path.Combine(Path.GetTempPath(), $"ucx-extract-{Guid.NewGuid()}");
        Directory.CreateDirectory(tempExtract);

        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = sevenZipPath,
                Arguments = $"x \"{archivePath}\" -o\"{tempExtract}\" -y",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            using var process = Process.Start(startInfo);
            if (process != null)
            {
                await process.WaitForExitAsync(cancellationToken);
            }

            // Find and copy the executable
            var exeName = downloadInfo.ExecutableName + (OperatingSystem.IsWindows() ? ".exe" : "");
            var files = Directory.GetFiles(tempExtract, exeName, SearchOption.AllDirectories);
            if (files.Length > 0)
            {
                File.Copy(files[0], Path.Combine(installPath, exeName), overwrite: true);
            }
        }
        finally
        {
            if (Directory.Exists(tempExtract))
                Directory.Delete(tempExtract, recursive: true);
        }
    }

    private async Task RunInstallerAsync(
        string installerPath,
        ToolDownloadInfo downloadInfo,
        CancellationToken cancellationToken)
    {
        _logger?.LogWarning("Running installer for {Tool}. This may require elevation.", downloadInfo.ToolName);

        var args = downloadInfo.InstallerArgs ?? "/S"; // Silent install

        var startInfo = new ProcessStartInfo
        {
            FileName = installerPath,
            Arguments = args,
            UseShellExecute = true,
            Verb = "runas" // Request elevation on Windows
        };

        using var process = Process.Start(startInfo);
        if (process != null)
        {
            await process.WaitForExitAsync(cancellationToken);

            if (process.ExitCode != 0)
            {
                throw new Exception($"Installer exited with code {process.ExitCode}");
            }
        }
    }

    private static bool ShouldExtractFile(string fileName, ToolDownloadInfo downloadInfo)
    {
        var name = Path.GetFileName(fileName);
        
        // Check if it matches the executable
        var exeName = downloadInfo.ExecutableName;
        if (OperatingSystem.IsWindows())
        {
            return name.Equals(exeName + ".exe", StringComparison.OrdinalIgnoreCase) ||
                   (downloadInfo.AdditionalFiles?.Any(f => name.Equals(f, StringComparison.OrdinalIgnoreCase)) ?? false);
        }
        
        return name.Equals(exeName, StringComparison.OrdinalIgnoreCase) ||
               (downloadInfo.AdditionalFiles?.Any(f => name.Equals(f, StringComparison.OrdinalIgnoreCase)) ?? false);
    }

    private async Task<string> GetDownloadUrlAsync(ToolDownloadInfo downloadInfo, CancellationToken cancellationToken)
    {
        // Check for platform-specific URLs
        if (downloadInfo.PlatformUrls != null)
        {
            var platformKey = $"{_platform}-{_architecture}";
            if (downloadInfo.PlatformUrls.TryGetValue(platformKey, out var url))
                return url;

            // Try architecture-agnostic
            if (downloadInfo.PlatformUrls.TryGetValue(_platform, out url))
                return url;
        }

        // Check for GitHub release API
        if (!string.IsNullOrEmpty(downloadInfo.GitHubRepo))
        {
            return await GetGitHubReleaseUrlAsync(downloadInfo, cancellationToken);
        }

        // Return base URL
        return downloadInfo.BaseDownloadUrl ?? "";
    }

    private async Task<string> GetGitHubReleaseUrlAsync(ToolDownloadInfo downloadInfo, CancellationToken cancellationToken)
    {
        var apiUrl = $"https://api.github.com/repos/{downloadInfo.GitHubRepo}/releases/latest";
        
        _httpClient.DefaultRequestHeaders.UserAgent.ParseAdd("UniversalConverterX/1.0");
        
        var response = await _httpClient.GetFromJsonAsync<GitHubRelease>(apiUrl, cancellationToken);
        if (response?.Assets == null)
            return "";

        // Find the appropriate asset for our platform
        var assetPattern = GetAssetPattern(downloadInfo);
        var asset = response.Assets.FirstOrDefault(a => 
            assetPattern.Any(p => a.Name.Contains(p, StringComparison.OrdinalIgnoreCase)));

        return asset?.BrowserDownloadUrl ?? "";
    }

    private static string[] GetAssetPattern(ToolDownloadInfo downloadInfo)
    {
        var patterns = new List<string>();

        if (OperatingSystem.IsWindows())
        {
            if (_architecture == "x64")
            {
                patterns.AddRange(["win64", "win-x64", "windows-x64", "windows64", "win_x64"]);
            }
            else if (_architecture == "arm64")
            {
                patterns.AddRange(["win-arm64", "windows-arm64"]);
            }
            patterns.Add("windows");
            patterns.Add("win");
        }
        else if (OperatingSystem.IsLinux())
        {
            if (_architecture == "x64")
            {
                patterns.AddRange(["linux64", "linux-x64", "linux-amd64", "linux_amd64"]);
            }
            else if (_architecture == "arm64")
            {
                patterns.AddRange(["linux-arm64", "linux-aarch64"]);
            }
            patterns.Add("linux");
        }
        else if (OperatingSystem.IsMacOS())
        {
            if (_architecture == "arm64")
            {
                patterns.AddRange(["macos-arm64", "darwin-arm64", "mac-arm64", "osx-arm64"]);
            }
            else
            {
                patterns.AddRange(["macos-x64", "darwin-x64", "mac-x64", "osx64"]);
            }
            patterns.AddRange(["macos", "darwin", "osx"]);
        }

        return [.. patterns];
    }

    private async Task<string?> GetLatestVersionAsync(ToolDownloadInfo downloadInfo, CancellationToken cancellationToken)
    {
        if (!string.IsNullOrEmpty(downloadInfo.GitHubRepo))
        {
            var apiUrl = $"https://api.github.com/repos/{downloadInfo.GitHubRepo}/releases/latest";
            _httpClient.DefaultRequestHeaders.UserAgent.ParseAdd("UniversalConverterX/1.0");
            
            var response = await _httpClient.GetFromJsonAsync<GitHubRelease>(apiUrl, cancellationToken);
            return response?.TagName?.TrimStart('v');
        }

        return downloadInfo.LatestVersion;
    }

    private async Task<string?> GetInstalledVersionAsync(string toolName, CancellationToken cancellationToken)
    {
        var exePath = GetExecutablePath(toolName);
        if (!File.Exists(exePath))
            return null;

        if (!_toolDownloadInfo.TryGetValue(toolName, out var downloadInfo))
            return null;

        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = exePath,
                Arguments = downloadInfo.VersionArg ?? "--version",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            using var process = Process.Start(startInfo);
            if (process == null)
                return null;

            var output = await process.StandardOutput.ReadToEndAsync(cancellationToken);
            var error = await process.StandardError.ReadToEndAsync(cancellationToken);
            await process.WaitForExitAsync(cancellationToken);

            var fullOutput = output + error;
            return ExtractVersion(fullOutput);
        }
        catch
        {
            return null;
        }
    }

    private static string? ExtractVersion(string output)
    {
        if (string.IsNullOrWhiteSpace(output))
            return null;

        // Try to find version pattern
        var lines = output.Split('\n');
        foreach (var line in lines)
        {
            var parts = line.Split([' ', '\t'], StringSplitOptions.RemoveEmptyEntries);
            foreach (var part in parts)
            {
                var cleaned = part.Trim(',', '(', ')', 'v', 'V');
                if (cleaned.Length > 0 && char.IsDigit(cleaned[0]) && cleaned.Contains('.'))
                {
                    return cleaned;
                }
            }
        }

        return null;
    }

    private string GetExecutablePath(string toolName)
    {
        if (!_toolDownloadInfo.TryGetValue(toolName, out var info))
            return "";

        var exeName = info.ExecutableName + (OperatingSystem.IsWindows() ? ".exe" : "");
        return Path.Combine(_options.ToolsBasePath, "bin", exeName);
    }

    private static async Task<string> ComputeFileChecksumAsync(string filePath, CancellationToken cancellationToken)
    {
        await using var stream = File.OpenRead(filePath);
        var hash = await SHA256.HashDataAsync(stream, cancellationToken);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static async Task MakeExecutableAsync(string filePath, CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "chmod",
            Arguments = $"+x \"{filePath}\"",
            UseShellExecute = false,
            CreateNoWindow = true
        };

        using var process = Process.Start(startInfo);
        if (process != null)
        {
            await process.WaitForExitAsync(cancellationToken);
        }
    }

    private static string GetFilenameFromUrl(string url)
    {
        var uri = new Uri(url);
        return Path.GetFileName(uri.LocalPath);
    }

    private static string? Find7ZipExecutable()
    {
        if (OperatingSystem.IsWindows())
        {
            var paths = new[]
            {
                @"C:\Program Files\7-Zip\7z.exe",
                @"C:\Program Files (x86)\7-Zip\7z.exe",
                Environment.ExpandEnvironmentVariables(@"%LOCALAPPDATA%\Programs\7-Zip\7z.exe")
            };

            return paths.FirstOrDefault(File.Exists);
        }

        // On Unix, check if 7z is in PATH
        var pathDirs = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator) ?? [];
        foreach (var dir in pathDirs)
        {
            var fullPath = Path.Combine(dir, "7z");
            if (File.Exists(fullPath))
                return fullPath;
        }

        return null;
    }

    private static string GetPlatformIdentifier()
    {
        if (OperatingSystem.IsWindows()) return "windows";
        if (OperatingSystem.IsLinux()) return "linux";
        if (OperatingSystem.IsMacOS()) return "macos";
        return "unknown";
    }

    private static string GetArchitectureIdentifier()
    {
        return RuntimeInformation.ProcessArchitecture switch
        {
            Architecture.X64 => "x64",
            Architecture.X86 => "x86",
            Architecture.Arm64 => "arm64",
            Architecture.Arm => "arm",
            _ => "unknown"
        };
    }

    private static Dictionary<string, ToolDownloadInfo> InitializeToolDownloadInfo()
    {
        return new Dictionary<string, ToolDownloadInfo>
        {
            ["ffmpeg"] = new ToolDownloadInfo
            {
                ToolName = "ffmpeg",
                ExecutableName = "ffmpeg",
                GitHubRepo = "BtbN/FFmpeg-Builds",
                VersionArg = "-version",
                Description = "Video and audio processing",
                PlatformUrls = new Dictionary<string, string>
                {
                    ["windows-x64"] = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                    ["linux-x64"] = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
                },
                AdditionalFiles = ["ffprobe", "ffplay"]
            },
            ["imagemagick"] = new ToolDownloadInfo
            {
                ToolName = "imagemagick",
                ExecutableName = "magick",
                GitHubRepo = "ImageMagick/ImageMagick",
                VersionArg = "--version",
                Description = "Image processing and conversion",
                PlatformUrls = new Dictionary<string, string>
                {
                    ["windows-x64"] = "https://imagemagick.org/archive/binaries/ImageMagick-7.1.1-29-portable-Q16-x64.zip"
                }
            },
            ["pandoc"] = new ToolDownloadInfo
            {
                ToolName = "pandoc",
                ExecutableName = "pandoc",
                GitHubRepo = "jgm/pandoc",
                VersionArg = "--version",
                Description = "Universal document converter"
            },
            ["potrace"] = new ToolDownloadInfo
            {
                ToolName = "potrace",
                ExecutableName = "potrace",
                GitHubRepo = null,
                BaseDownloadUrl = "https://potrace.sourceforge.io/download/potrace-1.16.win64.zip",
                VersionArg = "--version",
                Description = "Bitmap to vector conversion",
                AdditionalFiles = ["mkbitmap"]
            },
            ["resvg"] = new ToolDownloadInfo
            {
                ToolName = "resvg",
                ExecutableName = "resvg",
                GitHubRepo = "RazrFalcon/resvg",
                VersionArg = "--version",
                Description = "High-quality SVG renderer"
            },
            ["vips"] = new ToolDownloadInfo
            {
                ToolName = "vips",
                ExecutableName = "vips",
                GitHubRepo = "libvips/libvips",
                VersionArg = "--version",
                Description = "Fast image processing library"
            },
            ["libjxl"] = new ToolDownloadInfo
            {
                ToolName = "libjxl",
                ExecutableName = "cjxl",
                GitHubRepo = "libjxl/libjxl",
                VersionArg = "--version",
                Description = "JPEG XL encoder/decoder",
                AdditionalFiles = ["djxl"]
            },
            ["libheif"] = new ToolDownloadInfo
            {
                ToolName = "libheif",
                ExecutableName = "heif-convert",
                GitHubRepo = "nicochristiaens/libheif-windows",
                VersionArg = "--version",
                Description = "HEIC/HEIF image converter",
                AdditionalFiles = ["heif-enc", "heif-info"]
            }
        };
    }

    private class GitHubRelease
    {
        [JsonPropertyName("tag_name")]
        public string? TagName { get; set; }

        [JsonPropertyName("assets")]
        public List<GitHubAsset>? Assets { get; set; }
    }

    private class GitHubAsset
    {
        [JsonPropertyName("name")]
        public string? Name { get; set; }

        [JsonPropertyName("browser_download_url")]
        public string? BrowserDownloadUrl { get; set; }
    }
}

/// <summary>
/// Interface for tool downloading
/// </summary>
public interface IToolDownloader
{
    Task<ToolDownloadResult> DownloadToolAsync(
        string toolName,
        IProgress<DownloadProgress>? progress = null,
        CancellationToken cancellationToken = default);

    Task<IReadOnlyList<ToolDownloadResult>> DownloadToolsAsync(
        IEnumerable<string> toolNames,
        IProgress<BatchDownloadProgress>? progress = null,
        CancellationToken cancellationToken = default);

    Task<ToolUpdateInfo?> CheckForUpdateAsync(
        string toolName,
        CancellationToken cancellationToken = default);

    ToolDownloadInfo? GetToolDownloadInfo(string toolName);

    IReadOnlyList<string> GetDownloadableTools();
}

/// <summary>
/// Information about a tool download source
/// </summary>
public class ToolDownloadInfo
{
    public string ToolName { get; set; } = "";
    public string ExecutableName { get; set; } = "";
    public string? GitHubRepo { get; set; }
    public string? BaseDownloadUrl { get; set; }
    public Dictionary<string, string>? PlatformUrls { get; set; }
    public string? VersionArg { get; set; }
    public string? ExpectedChecksum { get; set; }
    public string? LatestVersion { get; set; }
    public string? Description { get; set; }
    public string? InstallerArgs { get; set; }
    public string[]? AdditionalFiles { get; set; }
}

/// <summary>
/// Information about available tool updates
/// </summary>
public record ToolUpdateInfo(
    string ToolName,
    string? CurrentVersion,
    string? LatestVersion,
    bool UpdateAvailable,
    bool IsInstalled);

/// <summary>
/// Progress information for batch downloads
/// </summary>
public record BatchDownloadProgress(
    string CurrentTool,
    int ToolsCompleted,
    int TotalTools,
    DownloadProgress CurrentProgress);
