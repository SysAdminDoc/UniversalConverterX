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
    private static readonly TimeSpan VersionProbeTimeout = TimeSpan.FromSeconds(10);
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

        if (!_httpClient.DefaultRequestHeaders.UserAgent.Any())
            _httpClient.DefaultRequestHeaders.UserAgent.ParseAdd("UniversalConverterX/1.0");

        var binDir = Path.Combine(_options.ToolsBasePath, "bin");
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

            var resolved = await ResolveDownloadAsync(downloadInfo, cancellationToken);
            if (string.IsNullOrEmpty(resolved.Url))
            {
                return new ToolDownloadResult(
                    Success: false,
                    ToolName: toolName,
                    Version: null,
                    ErrorMessage: $"No download available for {toolName} on {_platform}-{_architecture}");
            }

            _logger?.LogDebug("Download URL: {Url}", resolved.Url);

            // Create temp directory for download
            var tempDir = Path.Combine(Path.GetTempPath(), $"ucx-download-{Guid.NewGuid()}");
            Directory.CreateDirectory(tempDir);

            try
            {
                // Download the file
                var downloadPath = Path.Combine(tempDir, GetFilenameFromUrl(resolved.Url));
                await DownloadFileAsync(resolved.Url, downloadPath, progress, cancellationToken);

                var configuredChecksum = NormalizeSha256(downloadInfo.ExpectedChecksum);
                if (!string.IsNullOrWhiteSpace(downloadInfo.ExpectedChecksum) && configuredChecksum is null)
                    throw new InvalidDataException($"Invalid SHA-256 checksum configured for {toolName}.");

                var expectedChecksum = configuredChecksum ?? resolved.Sha256;
                if (string.IsNullOrWhiteSpace(expectedChecksum) && downloadInfo.RequireChecksum)
                    throw new InvalidDataException(
                        $"No SHA-256 checksum is available for {toolName}; refusing to install an unchecked download.");

                if (!string.IsNullOrEmpty(expectedChecksum))
                {
                    var actualChecksum = await ComputeFileChecksumAsync(downloadPath, cancellationToken);
                    if (!string.Equals(actualChecksum, expectedChecksum, StringComparison.OrdinalIgnoreCase))
                    {
                        _logger?.LogError("Checksum mismatch for {Tool}. Expected: {Expected}, Got: {Actual}",
                            toolName, expectedChecksum, actualChecksum);
                        throw new InvalidDataException(
                            $"Checksum mismatch for {toolName}. Expected {expectedChecksum}, got {actualChecksum}.");
                    }
                }

                var installPath = Path.Combine(_options.ToolsBasePath, "bin");
                var stagePath = Path.Combine(tempDir, "stage");
                await ExtractAndInstallAsync(downloadPath, stagePath, downloadInfo, cancellationToken);
                await VerifyStagedReleaseAsync(stagePath, downloadInfo, resolved, cancellationToken);
                await PromoteStagedInstallAsync(stagePath, installPath, downloadInfo, toolName, cancellationToken);

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
        if (!url.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException($"Refusing to download over insecure HTTP: {url}");

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
        Directory.CreateDirectory(installPath);

        var extension = Path.GetExtension(archivePath).ToLowerInvariant();

        switch (extension)
        {
            case ".zip":
                await ExtractZipAsync(archivePath, installPath, downloadInfo, cancellationToken);
                break;
            case ".gz" when archivePath.EndsWith(".tar.gz", StringComparison.OrdinalIgnoreCase):
            case ".tgz":
                await ExtractTarGzAsync(archivePath, installPath, downloadInfo, cancellationToken);
                break;
            case ".xz" when archivePath.EndsWith(".tar.xz", StringComparison.OrdinalIgnoreCase):
                await ExtractTarXzAsync(archivePath, installPath, downloadInfo, cancellationToken);
                break;
            case ".7z":
                await Extract7zAsync(archivePath, installPath, downloadInfo, cancellationToken);
                break;
            case ".exe":
                if (!CopyDirectExecutableIfExpected(archivePath, installPath, downloadInfo))
                    throw new NotSupportedException(
                        "Automatic execution of downloaded installers is disabled. Install this tool manually or provide a portable executable.");
                break;
            case ".msi":
                throw new NotSupportedException(
                    "Automatic execution of downloaded MSI installers is disabled. Install this tool manually or provide a portable executable.");
            default:
                if (!CopyDirectExecutableIfExpected(archivePath, installPath, downloadInfo))
                    throw new NotSupportedException(
                        $"Unsupported download archive type '{extension}'. Refusing to install it as an executable.");
                break;
        }
    }

    private Task ExtractZipAsync(
        string zipPath,
        string installPath,
        ToolDownloadInfo downloadInfo,
        CancellationToken cancellationToken)
    {
        using var archive = ZipFile.OpenRead(zipPath);

        var extracted = false;
        foreach (var entry in archive.Entries)
        {
            cancellationToken.ThrowIfCancellationRequested();

            if (string.IsNullOrEmpty(entry.Name))
                continue;

            // Extract only the expected executable and declared companion files,
            // flattening nested archive folders so zip entries cannot write
            // outside the tools/bin install directory.
            if (ShouldExtractFile(entry.Name, downloadInfo))
            {
                var destPath = Path.Combine(installPath, Path.GetFileName(entry.Name));
                entry.ExtractToFile(destPath, overwrite: true);
                extracted = true;
            }
        }

        if (!extracted)
            throw new InvalidDataException($"Archive did not contain {downloadInfo.ExecutableName}.");

        return Task.CompletedTask;
    }

    private async Task ExtractTarGzAsync(
        string tarGzPath,
        string installPath,
        ToolDownloadInfo downloadInfo,
        CancellationToken cancellationToken)
    {
        await ExtractTarAsync(tarGzPath, installPath, downloadInfo, "-xzf", "tar.gz", cancellationToken);
    }

    private async Task ExtractTarXzAsync(
        string tarXzPath,
        string installPath,
        ToolDownloadInfo downloadInfo,
        CancellationToken cancellationToken)
    {
        await ExtractTarAsync(tarXzPath, installPath, downloadInfo, "-xJf", "tar.xz", cancellationToken);
    }

    private async Task ExtractTarAsync(
        string archivePath,
        string installPath,
        ToolDownloadInfo downloadInfo,
        string tarExtractFlag,
        string archiveLabel,
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
                    UseShellExecute = false,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                };
                startInfo.ArgumentList.Add(tarExtractFlag);
                startInfo.ArgumentList.Add(archivePath);
                startInfo.ArgumentList.Add("-C");
                startInfo.ArgumentList.Add(tempExtract);

                using var process = Process.Start(startInfo);
                if (process == null)
                    throw new InvalidOperationException("Failed to start tar extraction process.");

                var errorTask = process.StandardError.ReadToEndAsync(cancellationToken);
                await process.WaitForExitAsync(cancellationToken);
                var error = await errorTask;
                if (process.ExitCode != 0)
                    throw new InvalidOperationException($"tar exited with code {process.ExitCode}: {error.Trim()}");

                var copied = CopyExtractedToolFiles(tempExtract, installPath, downloadInfo);
                if (copied == 0)
                    throw new InvalidDataException($"Archive did not contain {downloadInfo.ExecutableName}.");
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
            _logger?.LogWarning("{ArchiveLabel} extraction on Windows requires 7-Zip or manual extraction", archiveLabel);
            throw new NotSupportedException($"{archiveLabel} extraction on Windows requires additional tools");
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
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };
            startInfo.ArgumentList.Add("x");
            startInfo.ArgumentList.Add(archivePath);
            startInfo.ArgumentList.Add($"-o{tempExtract}");
            startInfo.ArgumentList.Add("-y");

            using var process = Process.Start(startInfo);
            if (process == null)
                throw new InvalidOperationException("Failed to start 7-Zip extraction process.");

            var outputTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
            var errorTask = process.StandardError.ReadToEndAsync(cancellationToken);
            await process.WaitForExitAsync(cancellationToken);
            var output = await outputTask;
            var error = await errorTask;
            if (process.ExitCode != 0)
                throw new InvalidOperationException($"7-Zip exited with code {process.ExitCode}: {(error + output).Trim()}");

            var copied = CopyExtractedToolFiles(tempExtract, installPath, downloadInfo);
            if (copied == 0)
                throw new InvalidDataException($"Archive did not contain {downloadInfo.ExecutableName}.");
        }
        finally
        {
            if (Directory.Exists(tempExtract))
                Directory.Delete(tempExtract, recursive: true);
        }
    }

    private static bool CopyDirectExecutableIfExpected(
        string sourcePath,
        string installPath,
        ToolDownloadInfo downloadInfo)
    {
        var expectedName = downloadInfo.ExecutableName + (OperatingSystem.IsWindows() ? ".exe" : "");
        var actualName = Path.GetFileName(sourcePath);
        var isDeclaredAsset = downloadInfo.AssetNames?.Values.Any(name =>
            name.Equals(actualName, StringComparison.OrdinalIgnoreCase)) == true;
        if (!actualName.Equals(expectedName, StringComparison.OrdinalIgnoreCase) && !isDeclaredAsset)
            return false;

        var destPath = Path.Combine(installPath, expectedName);
        File.Copy(sourcePath, destPath, overwrite: true);
        return true;
    }

    private static int CopyExtractedToolFiles(
        string extractedRoot,
        string installPath,
        ToolDownloadInfo downloadInfo)
    {
        var copied = 0;
        foreach (var file in Directory.EnumerateFiles(extractedRoot, "*", SearchOption.AllDirectories))
        {
            var name = Path.GetFileName(file);
            if (!ShouldExtractFile(name, downloadInfo))
                continue;

            File.Copy(file, Path.Combine(installPath, name), overwrite: true);
            copied++;
        }
        return copied;
    }

    private async Task PromoteStagedInstallAsync(
        string stagePath,
        string installPath,
        ToolDownloadInfo downloadInfo,
        string toolName,
        CancellationToken cancellationToken)
    {
        var stagedFiles = GetStagedInstallFiles(stagePath, downloadInfo).ToList();
        if (stagedFiles.Count == 0)
            throw new InvalidDataException($"Archive did not contain {downloadInfo.ExecutableName}.");

        Directory.CreateDirectory(installPath);

        var rollbackRoot = Path.Combine(
            _options.ToolsBasePath,
            "rollback",
            toolName,
            DateTime.UtcNow.ToString("yyyyMMddHHmmssfff"));
        var backups = new List<RollbackFile>();
        var installed = new List<string>();

        try
        {
            foreach (var stagedFile in stagedFiles)
            {
                cancellationToken.ThrowIfCancellationRequested();

                var fileName = Path.GetFileName(stagedFile);
                var destination = Path.Combine(installPath, fileName);
                if (File.Exists(destination))
                {
                    Directory.CreateDirectory(rollbackRoot);
                    var backup = Path.Combine(rollbackRoot, fileName);
                    File.Move(destination, backup, overwrite: true);
                    backups.Add(new RollbackFile(fileName, backup, destination));
                }

                File.Move(stagedFile, destination, overwrite: true);
                installed.Add(destination);
            }

            if (backups.Count > 0)
                await WriteRollbackManifestAsync(rollbackRoot, toolName, backups, cancellationToken).ConfigureAwait(false);
        }
        catch
        {
            RestoreRollback(backups, installed);
            throw;
        }
    }

    private static IEnumerable<string> GetStagedInstallFiles(
        string stagePath,
        ToolDownloadInfo downloadInfo)
    {
        if (!Directory.Exists(stagePath))
            yield break;

        foreach (var file in Directory.EnumerateFiles(stagePath, "*", SearchOption.TopDirectoryOnly))
        {
            if (ShouldExtractFile(Path.GetFileName(file), downloadInfo))
                yield return file;
        }
    }

    private static async Task WriteRollbackManifestAsync(
        string rollbackRoot,
        string toolName,
        IReadOnlyList<RollbackFile> backups,
        CancellationToken cancellationToken)
    {
        var manifest = new RollbackManifest(
            ToolName: toolName,
            InstalledAtUtc: DateTime.UtcNow,
            Files: backups.Select(f => f.FileName).ToArray());
        var json = JsonSerializer.Serialize(manifest, new JsonSerializerOptions { WriteIndented = true });
        await File.WriteAllTextAsync(Path.Combine(rollbackRoot, "manifest.json"), json, cancellationToken)
            .ConfigureAwait(false);
    }

    private static void RestoreRollback(
        IEnumerable<RollbackFile> backups,
        IEnumerable<string> installed)
    {
        foreach (var file in installed)
        {
            try { if (File.Exists(file)) File.Delete(file); } catch { }
        }

        foreach (var backup in backups.Reverse())
        {
            try
            {
                var dir = Path.GetDirectoryName(backup.DestinationPath);
                if (!string.IsNullOrEmpty(dir))
                    Directory.CreateDirectory(dir);
                if (File.Exists(backup.BackupPath))
                    File.Move(backup.BackupPath, backup.DestinationPath, overwrite: true);
            }
            catch { }
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
                   (downloadInfo.AdditionalFiles?.Any(f =>
                       name.Equals(f, StringComparison.OrdinalIgnoreCase) ||
                       name.Equals(f + ".exe", StringComparison.OrdinalIgnoreCase)) ?? false);
        }

        return name.Equals(exeName, StringComparison.OrdinalIgnoreCase) ||
               (downloadInfo.AdditionalFiles?.Any(f => name.Equals(f, StringComparison.OrdinalIgnoreCase)) ?? false);
    }

    private async Task<ResolvedDownload> ResolveDownloadAsync(
        ToolDownloadInfo downloadInfo,
        CancellationToken cancellationToken)
    {
        var configuredChecksum = NormalizeSha256(downloadInfo.ExpectedChecksum);

        // Check for platform-specific URLs
        if (downloadInfo.PlatformUrls != null)
        {
            var platformKey = $"{_platform}-{_architecture}";
            if (downloadInfo.PlatformUrls.TryGetValue(platformKey, out var url))
            {
                var digest = configuredChecksum
                    ?? await TryGetGitHubAssetDigestAsync(downloadInfo, url, cancellationToken).ConfigureAwait(false);
                return new ResolvedDownload(url, digest, downloadInfo.LatestVersion);
            }

            // Try architecture-agnostic
            if (downloadInfo.PlatformUrls.TryGetValue(_platform, out url))
            {
                var digest = configuredChecksum
                    ?? await TryGetGitHubAssetDigestAsync(downloadInfo, url, cancellationToken).ConfigureAwait(false);
                return new ResolvedDownload(url, digest, downloadInfo.LatestVersion);
            }
        }

        // Check for GitHub release API
        if (!string.IsNullOrEmpty(downloadInfo.GitHubRepo))
        {
            return await GetGitHubReleaseDownloadAsync(downloadInfo, configuredChecksum, cancellationToken)
                .ConfigureAwait(false);
        }

        // Return base URL
        return new ResolvedDownload(downloadInfo.BaseDownloadUrl ?? "", configuredChecksum, downloadInfo.LatestVersion);
    }

    private async Task<ResolvedDownload> GetGitHubReleaseDownloadAsync(
        ToolDownloadInfo downloadInfo,
        string? configuredChecksum,
        CancellationToken cancellationToken)
    {
        var response = await GetGitHubReleaseAsync(downloadInfo.GitHubRepo!, cancellationToken)
            .ConfigureAwait(false);
        if (response?.Assets == null)
            return new ResolvedDownload("", configuredChecksum, null);

        GitHubAsset? asset;
        var exactAssetName = GetPlatformValue(downloadInfo.AssetNames);
        if (downloadInfo.AssetNames is not null)
        {
            asset = string.IsNullOrWhiteSpace(exactAssetName)
                ? null
                : response.Assets.FirstOrDefault(a =>
                    string.Equals(a.Name, exactAssetName, StringComparison.OrdinalIgnoreCase));
        }
        else
        {
            // Legacy tool definitions do not declare an exact artifact. Keep
            // the existing platform-token selection until each is migrated.
            var assetPattern = GetAssetPattern(downloadInfo);
            asset = response.Assets.FirstOrDefault(a =>
                !string.IsNullOrWhiteSpace(a.Name) &&
                assetPattern.Any(p => a.Name.Contains(p, StringComparison.OrdinalIgnoreCase)));
        }

        return new ResolvedDownload(
            asset?.BrowserDownloadUrl ?? "",
            configuredChecksum ?? NormalizeSha256(asset?.Digest),
            response.TagName?.TrimStart('v'));
    }

    private static string? GetPlatformValue(IReadOnlyDictionary<string, string>? values)
    {
        if (values is null)
            return null;

        var platformKey = $"{_platform}-{_architecture}";
        return values.GetValueOrDefault(platformKey)
            ?? values.GetValueOrDefault(_platform);
    }

    private async Task<string?> TryGetGitHubAssetDigestAsync(
        ToolDownloadInfo downloadInfo,
        string downloadUrl,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(downloadInfo.GitHubRepo))
            return null;

        var response = await GetGitHubReleaseAsync(downloadInfo.GitHubRepo, cancellationToken)
            .ConfigureAwait(false);
        if (response?.Assets == null)
            return null;

        var fileName = GetFilenameFromUrl(downloadUrl);
        var asset = response.Assets.FirstOrDefault(a =>
                string.Equals(a.BrowserDownloadUrl, downloadUrl, StringComparison.OrdinalIgnoreCase))
            ?? response.Assets.FirstOrDefault(a =>
                string.Equals(a.Name, fileName, StringComparison.OrdinalIgnoreCase));

        return NormalizeSha256(asset?.Digest);
    }

    private async Task<GitHubRelease?> GetGitHubReleaseAsync(string repo, CancellationToken cancellationToken)
    {
        var apiUrl = $"https://api.github.com/repos/{repo}/releases/latest";

        return await _httpClient.GetFromJsonAsync<GitHubRelease>(apiUrl, cancellationToken)
            .ConfigureAwait(false);
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
            var response = await GetGitHubReleaseAsync(downloadInfo.GitHubRepo, cancellationToken)
                .ConfigureAwait(false);
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

        return await ProbeExecutableVersionAsync(exePath, downloadInfo.VersionArg, cancellationToken)
            .ConfigureAwait(false);
    }

    private async Task VerifyStagedReleaseAsync(
        string stagePath,
        ToolDownloadInfo downloadInfo,
        ResolvedDownload resolved,
        CancellationToken cancellationToken)
    {
        if (!downloadInfo.RequireReleaseVersionMatch)
            return;

        if (string.IsNullOrWhiteSpace(resolved.Version))
            throw new InvalidDataException(
                $"Release metadata did not include a version for {downloadInfo.ToolName}; refusing to promote it.");

        var stagedExecutable = GetStagedInstallFiles(stagePath, downloadInfo)
            .FirstOrDefault(path => Path.GetFileNameWithoutExtension(path)
                .Equals(downloadInfo.ExecutableName, StringComparison.OrdinalIgnoreCase));
        if (stagedExecutable is null)
            throw new InvalidDataException($"Staged {downloadInfo.ToolName} executable was not found.");

        if (!OperatingSystem.IsWindows())
            await MakeExecutableAsync(stagedExecutable, cancellationToken).ConfigureAwait(false);

        var stagedVersion = await ProbeExecutableVersionAsync(
            stagedExecutable,
            downloadInfo.VersionArg,
            cancellationToken).ConfigureAwait(false);
        if (!ReleaseVersionMatches(stagedVersion, resolved.Version))
        {
            throw new InvalidDataException(
                $"Staged {downloadInfo.ToolName} version '{stagedVersion ?? "unknown"}' " +
                $"does not match release {resolved.Version}; the installed tool was left unchanged.");
        }
    }

    internal static bool ReleaseVersionMatches(string? reportedVersion, string? releaseVersion)
    {
        var reported = ExtractVersion(reportedVersion ?? "");
        var release = ExtractVersion(releaseVersion?.TrimStart('v', 'V') ?? "");
        return reported is not null
            && release is not null
            && string.Equals(reported, release, StringComparison.OrdinalIgnoreCase);
    }

    private static async Task<string?> ProbeExecutableVersionAsync(
        string exePath,
        string? versionArg,
        CancellationToken cancellationToken)
    {
        Process? process = null;
        try
        {
            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeoutCts.CancelAfter(VersionProbeTimeout);
            var probeToken = timeoutCts.Token;

            var startInfo = new ProcessStartInfo
            {
                FileName = exePath,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };
            startInfo.ArgumentList.Add(versionArg ?? "--version");

            process = Process.Start(startInfo);
            if (process == null)
                return null;

            var outputTask = process.StandardOutput.ReadToEndAsync(probeToken);
            var errorTask = process.StandardError.ReadToEndAsync(probeToken);
            await process.WaitForExitAsync(probeToken);
            var output = await outputTask;
            var error = await errorTask;

            var fullOutput = output + error;
            return ExtractVersion(fullOutput);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            try { if (process is not null && !process.HasExited) process.Kill(entireProcessTree: true); } catch { }
            return null;
        }
        catch
        {
            try { if (process is not null && !process.HasExited) process.Kill(entireProcessTree: true); } catch { }
            return null;
        }
        finally
        {
            process?.Dispose();
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
                var cleaned = part.Trim().Trim(',', '(', ')', 'v', 'V');
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

    private static string? NormalizeSha256(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return null;

        var normalized = value.Trim();
        if (normalized.StartsWith("sha256:", StringComparison.OrdinalIgnoreCase))
            normalized = normalized["sha256:".Length..];

        return normalized.Length == 64 && normalized.All(Uri.IsHexDigit)
            ? normalized.ToLowerInvariant()
            : null;
    }

    private static async Task MakeExecutableAsync(string filePath, CancellationToken cancellationToken)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "chmod",
            UseShellExecute = false,
            CreateNoWindow = true
        };
        startInfo.ArgumentList.Add("+x");
        startInfo.ArgumentList.Add(filePath);

        using var process = Process.Start(startInfo);
        if (process != null)
        {
            await process.WaitForExitAsync(cancellationToken);
        }
    }

    private static string GetFilenameFromUrl(string url)
    {
        var uri = new Uri(url);
        var fileName = Path.GetFileName(uri.LocalPath);
        if (string.IsNullOrWhiteSpace(fileName))
            throw new InvalidOperationException($"Download URL does not include a filename: {url}");
        if (fileName.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
            throw new InvalidOperationException($"Download URL includes an unsafe filename: {url}");
        return fileName;
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
            },
            ["yt-dlp"] = new ToolDownloadInfo
            {
                ToolName = "yt-dlp",
                ExecutableName = "yt-dlp",
                GitHubRepo = "yt-dlp/yt-dlp",
                VersionArg = "--version",
                Description = "Downloader extractor and update channel",
                RequireChecksum = true,
                RequireReleaseVersionMatch = true,
                AssetNames = new Dictionary<string, string>
                {
                    ["windows-x64"] = "yt-dlp.exe",
                    ["windows-arm64"] = "yt-dlp_arm64.exe",
                    ["linux-x64"] = "yt-dlp_linux",
                    ["linux-arm64"] = "yt-dlp_linux_aarch64",
                    ["macos-x64"] = "yt-dlp_macos",
                    ["macos-arm64"] = "yt-dlp_macos",
                },
            },
            ["deno"] = new ToolDownloadInfo
            {
                ToolName = "deno",
                ExecutableName = "deno",
                GitHubRepo = "denoland/deno",
                VersionArg = "--version",
                Description = "Sandboxed JavaScript runtime for full YouTube extraction",
                RequireChecksum = true,
                RequireReleaseVersionMatch = true,
                AssetNames = new Dictionary<string, string>
                {
                    ["windows-x64"] = "deno-x86_64-pc-windows-msvc.zip",
                    ["windows-arm64"] = "deno-aarch64-pc-windows-msvc.zip",
                    ["linux-x64"] = "deno-x86_64-unknown-linux-gnu.zip",
                    ["linux-arm64"] = "deno-aarch64-unknown-linux-gnu.zip",
                    ["macos-x64"] = "deno-x86_64-apple-darwin.zip",
                    ["macos-arm64"] = "deno-aarch64-apple-darwin.zip",
                },
            }
        };
    }

    private sealed record ResolvedDownload(string Url, string? Sha256, string? Version);

    private sealed record RollbackFile(string FileName, string BackupPath, string DestinationPath);

    private sealed record RollbackManifest(string ToolName, DateTime InstalledAtUtc, string[] Files);

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

        [JsonPropertyName("digest")]
        public string? Digest { get; set; }
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
    public bool RequireChecksum { get; set; } = false;
    public string? LatestVersion { get; set; }
    public string? Description { get; set; }
    public string? InstallerArgs { get; set; }
    public string[]? AdditionalFiles { get; set; }
    public Dictionary<string, string>? AssetNames { get; set; }
    public bool RequireReleaseVersionMatch { get; set; }
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
