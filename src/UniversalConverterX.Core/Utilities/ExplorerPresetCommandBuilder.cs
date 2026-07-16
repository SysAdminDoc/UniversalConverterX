using System.Diagnostics;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// A side-effect-free Explorer-to-CLI invocation plan. Large selections carry
/// their paths separately so the shell extension can materialize the list file
/// immediately before process launch and reliably clean it up afterward.
/// </summary>
public sealed record ExplorerPresetCommandPlan(
    IReadOnlyList<string> Arguments,
    string? InputListPath,
    IReadOnlyList<string> InputListEntries)
{
    public bool UsesInputList => InputListPath is not null;

    public ProcessStartInfo CreateStartInfo(string executablePath, bool createNoWindow = false)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(executablePath);
        var startInfo = new ProcessStartInfo
        {
            FileName = executablePath,
            UseShellExecute = false,
            CreateNoWindow = createNoWindow,
        };
        foreach (var argument in Arguments)
            startInfo.ArgumentList.Add(argument);
        return startInfo;
    }
}

/// <summary>
/// Builds the argument-vector used by the Explorer preset submenu. Arguments
/// remain discrete values (never a shell command string), so spaces, quotes,
/// Unicode, and metacharacters in preset names or file paths are data rather
/// than executable syntax.
/// </summary>
public static class ExplorerPresetCommandBuilder
{
    public const int DefaultMaxCommandLineChars = 7_000;

    public static ExplorerPresetCommandPlan Build(
        string presetName,
        IReadOnlyList<string> inputFiles,
        int maxCommandLineChars = DefaultMaxCommandLineChars,
        Func<string>? inputListPathFactory = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(presetName);
        ArgumentNullException.ThrowIfNull(inputFiles);
        if (maxCommandLineChars < 1)
            throw new ArgumentOutOfRangeException(nameof(maxCommandLineChars));
        if (inputFiles.Any(string.IsNullOrWhiteSpace))
            throw new ArgumentException("Input file paths cannot be empty.", nameof(inputFiles));

        var prefix = new List<string> { "convert-preset", "--preset", presetName };
        var inline = new List<string>(prefix.Count + inputFiles.Count);
        inline.AddRange(prefix);
        inline.AddRange(inputFiles);
        if (EstimateWindowsCommandLineLength(inline) <= maxCommandLineChars)
            return new ExplorerPresetCommandPlan(inline, null, []);

        var listPath = inputListPathFactory?.Invoke()
            ?? Path.Combine(Path.GetTempPath(), $"ucx-input-{Guid.NewGuid():N}.txt");
        ArgumentException.ThrowIfNullOrWhiteSpace(listPath);

        prefix.Add("--input-files");
        prefix.Add(listPath);
        return new ExplorerPresetCommandPlan(prefix, listPath, inputFiles.ToArray());
    }

    internal static int EstimateWindowsCommandLineLength(IReadOnlyList<string> arguments)
    {
        var length = 0;
        foreach (var argument in arguments)
        {
            if (length > 0)
                length++;
            length += EncodedArgumentLength(argument);
        }
        return length;
    }

    private static int EncodedArgumentLength(string argument)
    {
        if (argument.Length > 0 &&
            !argument.Any(character => char.IsWhiteSpace(character) || character == '"'))
        {
            return argument.Length;
        }

        // Windows CommandLineToArgvW quoting: surround the value with quotes,
        // double backslashes before a quote, and double trailing backslashes.
        var length = 2;
        var backslashes = 0;
        foreach (var character in argument)
        {
            if (character == '\\')
            {
                backslashes++;
                continue;
            }

            if (character == '"')
                length += (backslashes * 2) + 2;
            else
                length += backslashes + 1;
            backslashes = 0;
        }

        return length + (backslashes * 2);
    }
}
