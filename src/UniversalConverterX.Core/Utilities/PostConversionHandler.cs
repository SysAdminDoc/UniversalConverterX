using Microsoft.Extensions.Logging;
using UniversalConverterX.Core.Models;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Handles source-file actions after a successful conversion: keep, move to
/// an archive folder, or delete. The caller is responsible for verifying
/// that the output file was produced successfully before invoking.
/// </summary>
public static class PostConversionHandler
{
    private const string ZoneIdentifierSuffix = ":Zone.Identifier";
    private const int MaxZoneIdentifierBytes = 64 * 1024;

    /// <summary>
    /// Result of executing a post-conversion source-file action.
    /// </summary>
    public sealed record PostConversionResult(
        PostConversionAction Action,
        bool Success,
        string? DestinationPath,
        string? ErrorMessage);

    /// <summary>
    /// Resolve the effective <see cref="PostConversionAction"/> from a
    /// <see cref="ConversionOptions"/> instance, handling the deprecated
    /// <see cref="ConversionOptions.DeleteSourceOnSuccess"/> fallback.
    /// </summary>
    public static PostConversionAction ResolveAction(ConversionOptions options)
    {
        if (options.PostConversionAction != PostConversionAction.Keep)
            return options.PostConversionAction;

        if (options.DeleteSourceOnSuccess)
            return PostConversionAction.Delete;

        return PostConversionAction.Keep;
    }

    /// <summary>
    /// Execute the post-conversion action on the source file.
    /// </summary>
    /// <param name="sourcePath">Absolute path to the original input file.</param>
    /// <param name="outputPath">Absolute path to the successfully produced output file.</param>
    /// <param name="action">Which action to take on the source.</param>
    /// <param name="archiveFolder">
    /// Target folder for <see cref="PostConversionAction.Move"/>. Absolute
    /// paths are used as-is; relative paths resolve from the source file's
    /// parent directory. Ignored for Keep/Delete.
    /// </param>
    /// <param name="logger">Optional logger for auditing.</param>
    public static PostConversionResult Execute(
        string sourcePath,
        string outputPath,
        PostConversionAction action,
        string? archiveFolder = null,
        ILogger? logger = null)
    {
        if (action == PostConversionAction.Keep)
        {
            var keepMarkResult = PropagateMarkOfTheWeb(sourcePath, outputPath, logger);
            return keepMarkResult.Success
                ? new PostConversionResult(action, true, null, null)
                : new PostConversionResult(action, false, null,
                    $"Could not preserve Mark-of-the-Web on the converted output: {keepMarkResult.ErrorMessage}");
        }

        if (!File.Exists(sourcePath))
            return new PostConversionResult(action, false, null,
                $"Source file not found: '{sourcePath}'");

        if (!File.Exists(outputPath))
            return new PostConversionResult(action, false, null,
                $"Output file not found — refusing to {action.ToString().ToLowerInvariant()} " +
                $"source without a verified output: '{outputPath}'");

        try
        {
            var outputSize = new FileInfo(outputPath).Length;
            if (outputSize == 0)
                return new PostConversionResult(action, false, null,
                    $"Output file is zero bytes — refusing to {action.ToString().ToLowerInvariant()} " +
                    $"source when the output may be corrupt: '{outputPath}'");
        }
        catch (IOException)
        {
        }

        // Never operate on the source if it IS the output (in-place conversion).
        if (string.Equals(Path.GetFullPath(sourcePath), Path.GetFullPath(outputPath),
                StringComparison.OrdinalIgnoreCase))
            return new PostConversionResult(PostConversionAction.Keep, true, null, null);

        var markResult = PropagateMarkOfTheWeb(sourcePath, outputPath, logger);
        if (!markResult.Success)
        {
            return new PostConversionResult(action, false, null,
                $"Could not preserve Mark-of-the-Web on the converted output: {markResult.ErrorMessage}");
        }

        try
        {
            return action switch
            {
                PostConversionAction.Delete => ExecuteDelete(sourcePath, logger),
                PostConversionAction.Move => ExecuteMove(sourcePath, archiveFolder, logger),
                _ => new PostConversionResult(action, true, null, null)
            };
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            logger?.LogWarning(ex, "Post-conversion {Action} failed for '{Source}'",
                action, sourcePath);
            return new PostConversionResult(action, false, null, ex.Message);
        }
    }

    /// <summary>
    /// Copies the source file's Windows Zone.Identifier alternate data stream
    /// to a derived output. Files without Mark-of-the-Web and non-Windows
    /// platforms are successful no-ops.
    /// </summary>
    public static MarkOfTheWebResult PropagateMarkOfTheWeb(
        string sourcePath,
        string outputPath,
        ILogger? logger = null)
    {
        if (!OperatingSystem.IsWindows())
            return new MarkOfTheWebResult(false, true, null);

        var sourceStreamPath = sourcePath + ZoneIdentifierSuffix;
        byte[] zoneData;

        try
        {
            using var sourceStream = new FileStream(
                sourceStreamPath,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete,
                bufferSize: 4096,
                FileOptions.SequentialScan);

            if (sourceStream.Length > MaxZoneIdentifierBytes)
            {
                return new MarkOfTheWebResult(
                    true,
                    false,
                    $"Zone.Identifier is larger than the {MaxZoneIdentifierBytes}-byte safety limit.");
            }

            zoneData = new byte[(int)sourceStream.Length];
            sourceStream.ReadExactly(zoneData);
        }
        catch (FileNotFoundException)
        {
            return new MarkOfTheWebResult(false, true, null);
        }
        catch (DirectoryNotFoundException)
        {
            return new MarkOfTheWebResult(false, true, null);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or NotSupportedException)
        {
            logger?.LogWarning(ex, "Unable to read Mark-of-the-Web from '{Source}'", sourcePath);
            return new MarkOfTheWebResult(true, false, ex.Message);
        }

        try
        {
            using var destinationStream = new FileStream(
                outputPath + ZoneIdentifierSuffix,
                FileMode.Create,
                FileAccess.Write,
                FileShare.Read);
            destinationStream.Write(zoneData);
            destinationStream.Flush(flushToDisk: true);

            logger?.LogInformation(
                "Preserved Mark-of-the-Web from '{Source}' on '{Output}'",
                sourcePath,
                outputPath);
            return new MarkOfTheWebResult(true, true, null);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or NotSupportedException)
        {
            logger?.LogWarning(ex, "Unable to write Mark-of-the-Web to '{Output}'", outputPath);
            return new MarkOfTheWebResult(true, false, ex.Message);
        }
    }

    public sealed record MarkOfTheWebResult(
        bool SourceMarked,
        bool Success,
        string? ErrorMessage);

    private static PostConversionResult ExecuteDelete(string sourcePath, ILogger? logger)
    {
        File.Delete(sourcePath);
        logger?.LogInformation("Post-conversion: deleted source '{Source}'", sourcePath);
        return new PostConversionResult(PostConversionAction.Delete, true, null, null);
    }

    private static PostConversionResult ExecuteMove(
        string sourcePath, string? archiveFolder, ILogger? logger)
    {
        if (string.IsNullOrWhiteSpace(archiveFolder))
            return new PostConversionResult(PostConversionAction.Move, false, null,
                "PostConversionAction is Move but no archive folder is configured.");

        var resolvedFolder = Path.IsPathRooted(archiveFolder)
            ? archiveFolder
            : Path.Combine(Path.GetDirectoryName(sourcePath) ?? ".", archiveFolder);

        Directory.CreateDirectory(resolvedFolder);

        var fileName = Path.GetFileName(sourcePath);
        var destination = Path.Combine(resolvedFolder, fileName);

        if (File.Exists(destination))
            destination = UniqueOutputPath.Resolve(destination);

        File.Move(sourcePath, destination);
        logger?.LogInformation(
            "Post-conversion: moved source '{Source}' → '{Destination}'",
            sourcePath, destination);

        return new PostConversionResult(PostConversionAction.Move, true, destination, null);
    }
}
