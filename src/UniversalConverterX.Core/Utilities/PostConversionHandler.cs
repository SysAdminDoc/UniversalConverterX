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
            return new PostConversionResult(action, true, null, null);

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
