using System.Text;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// Formats and validates editable FFmpeg argument templates without invoking a
/// command shell. Templates must retain the exact <c>{input}</c> and
/// <c>{output}</c> argument tokens so a batch cannot accidentally reuse paths
/// from the first queued file.
/// </summary>
public static class FfmpegCommandTemplate
{
    public const string InputPlaceholder = "{input}";
    public const string OutputPlaceholder = "{output}";

    private static readonly char[] ForbiddenShellCharacters = ['&', '|', ';', '<', '>', '`', '\r', '\n', '\0'];

    public static string Create(
        IReadOnlyList<string> arguments,
        string inputPath,
        string outputPath)
    {
        var templateArguments = arguments
            .Select(argument => string.Equals(argument, inputPath, StringComparison.Ordinal)
                ? InputPlaceholder
                : string.Equals(argument, outputPath, StringComparison.Ordinal)
                    ? OutputPlaceholder
                    : argument)
            .ToList();

        return "ffmpeg " + string.Join(' ', templateArguments.Select(QuoteArgument));
    }

    public static bool TryMaterialize(
        string? template,
        string inputPath,
        string outputPath,
        out string[] arguments,
        out string? error)
    {
        arguments = [];
        error = null;

        if (string.IsNullOrWhiteSpace(template))
        {
            error = "The FFmpeg command cannot be empty.";
            return false;
        }

        if (template.IndexOfAny(ForbiddenShellCharacters) >= 0)
        {
            error = "Shell metacharacters (& | ; < > `) and line breaks are not allowed.";
            return false;
        }

        if (!TryTokenize(template, out var tokens, out error))
            return false;

        if (tokens.Count == 0
            || !(tokens[0].Equals("ffmpeg", StringComparison.OrdinalIgnoreCase)
                || tokens[0].Equals("ffmpeg.exe", StringComparison.OrdinalIgnoreCase)))
        {
            error = "The command must start with ffmpeg.";
            return false;
        }

        tokens.RemoveAt(0);
        if (tokens.Count(token => token == InputPlaceholder) != 1
            || tokens.Count(token => token == OutputPlaceholder) != 1)
        {
            error = "The command must contain one {input} token and one {output} token.";
            return false;
        }

        if (tokens.Any(token =>
                (token.Contains(InputPlaceholder, StringComparison.Ordinal) && token != InputPlaceholder)
                || (token.Contains(OutputPlaceholder, StringComparison.Ordinal) && token != OutputPlaceholder)))
        {
            error = "Input and output placeholders must be separate arguments.";
            return false;
        }

        arguments = tokens
            .Select(token => token == InputPlaceholder
                ? inputPath
                : token == OutputPlaceholder
                    ? outputPath
                    : token)
            .ToArray();

        return ValidateMaterialized(arguments, inputPath, outputPath, out error);
    }

    public static bool ValidateMaterialized(
        IReadOnlyList<string>? arguments,
        string inputPath,
        string outputPath,
        out string? error)
    {
        error = null;
        if (arguments is null || arguments.Count == 0)
        {
            error = "FFmpeg override arguments cannot be empty.";
            return false;
        }

        if (arguments.Any(argument =>
                string.IsNullOrEmpty(argument)
                || (argument.IndexOfAny(ForbiddenShellCharacters) >= 0
                    && !string.Equals(argument, inputPath, StringComparison.Ordinal)
                    && !string.Equals(argument, outputPath, StringComparison.Ordinal))))
        {
            error = "FFmpeg override arguments contain a forbidden shell metacharacter or empty token.";
            return false;
        }

        if (arguments.Count(argument => string.Equals(argument, inputPath, StringComparison.Ordinal)) != 1
            || arguments.Count(argument => string.Equals(argument, outputPath, StringComparison.Ordinal)) != 1)
        {
            error = "FFmpeg override arguments must preserve the exact input and output paths once each.";
            return false;
        }

        return true;
    }

    public static string FormatCommand(IReadOnlyList<string> arguments) =>
        "ffmpeg " + string.Join(' ', arguments.Select(QuoteArgument));

    public static bool TryParseReviewedCommand(
        string? command,
        IReadOnlyList<string> originalArguments,
        out string[] arguments,
        out string? error)
    {
        arguments = [];
        error = null;
        if (string.IsNullOrWhiteSpace(command))
        {
            error = "The FFmpeg command cannot be empty.";
            return false;
        }

        if (!TryTokenize(command, out var tokens, out error))
            return false;
        if (tokens.Count == 0
            || !(tokens[0].Equals("ffmpeg", StringComparison.OrdinalIgnoreCase)
                || tokens[0].Equals("ffmpeg.exe", StringComparison.OrdinalIgnoreCase)))
        {
            error = "The command must start with ffmpeg.";
            return false;
        }

        tokens.RemoveAt(0);
        if (tokens.Count == 0 || tokens.Any(string.IsNullOrEmpty))
        {
            error = "The FFmpeg argument vector cannot be empty and cannot contain empty arguments.";
            return false;
        }

        var introducedShellToken = tokens.FirstOrDefault(token =>
            token.IndexOfAny(ForbiddenShellCharacters) >= 0
            && !originalArguments.Contains(token, StringComparer.Ordinal));
        if (introducedShellToken is not null)
        {
            error = "Edited arguments cannot introduce shell metacharacters (& | ; < > `) or line breaks.";
            return false;
        }

        arguments = [.. tokens];
        return true;
    }

    private static bool TryTokenize(string command, out List<string> tokens, out string? error)
    {
        tokens = [];
        error = null;
        var current = new StringBuilder();
        var inQuotes = false;
        var tokenStarted = false;

        for (var index = 0; index < command.Length;)
        {
            if (!inQuotes && char.IsWhiteSpace(command[index]))
            {
                if (tokenStarted)
                {
                    tokens.Add(current.ToString());
                    current.Clear();
                    tokenStarted = false;
                }
                index++;
                continue;
            }

            tokenStarted = true;
            var slashCount = 0;
            while (index < command.Length && command[index] == '\\')
            {
                slashCount++;
                index++;
            }

            if (index < command.Length && command[index] == '"')
            {
                current.Append('\\', slashCount / 2);
                if (slashCount % 2 == 0)
                    inQuotes = !inQuotes;
                else
                    current.Append('"');
                index++;
                continue;
            }

            current.Append('\\', slashCount);
            if (index < command.Length)
            {
                current.Append(command[index]);
                index++;
            }
        }

        if (inQuotes)
        {
            error = "The FFmpeg command contains an unmatched quote.";
            return false;
        }

        if (tokenStarted)
            tokens.Add(current.ToString());
        return true;
    }

    private static string QuoteArgument(string argument)
    {
        if (argument.Length > 0 && !argument.Any(character => char.IsWhiteSpace(character) || character == '"'))
            return argument;

        var quoted = new StringBuilder("\"");
        var slashCount = 0;
        foreach (var character in argument)
        {
            if (character == '\\')
            {
                slashCount++;
                continue;
            }

            if (character == '"')
            {
                quoted.Append('\\', slashCount * 2 + 1);
                quoted.Append('"');
                slashCount = 0;
                continue;
            }

            quoted.Append('\\', slashCount);
            slashCount = 0;
            quoted.Append(character);
        }

        quoted.Append('\\', slashCount * 2);
        quoted.Append('"');
        return quoted.ToString();
    }
}
