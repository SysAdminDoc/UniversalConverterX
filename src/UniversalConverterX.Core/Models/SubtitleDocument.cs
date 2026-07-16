using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace UniversalConverterX.Core.Models;

public sealed record SubtitleCue(int Number, TimeSpan Start, TimeSpan End, string Text);

/// <summary>
/// Minimal, deterministic subtitle interchange model used by the subtitle
/// studio. Whisper and translation stages normalize to SRT, then this model
/// drives the editable preview and SRT/VTT/ASS exports without another process.
/// </summary>
public sealed partial class SubtitleDocument
{
    private readonly List<SubtitleCue> _cues;

    public SubtitleDocument(IEnumerable<SubtitleCue> cues)
    {
        ArgumentNullException.ThrowIfNull(cues);
        _cues = [.. cues];
        Validate(_cues);
    }

    public IReadOnlyList<SubtitleCue> Cues => _cues;

    public static SubtitleDocument ParseSrt(string content)
    {
        if (string.IsNullOrWhiteSpace(content))
            throw new InvalidDataException("The subtitle file is empty.");

        var normalized = content.Replace("\r\n", "\n", StringComparison.Ordinal)
            .Replace('\r', '\n')
            .Trim('\n', '\uFEFF');
        var blocks = BlankLineRegex().Split(normalized);
        var cues = new List<SubtitleCue>(blocks.Length);

        foreach (var block in blocks)
        {
            var lines = block.Split('\n');
            if (lines.Length < 2)
                throw new InvalidDataException("A subtitle cue is missing its timecode or text.");

            var timecodeIndex = lines[0].Trim().All(char.IsDigit) ? 1 : 0;
            if (timecodeIndex >= lines.Length)
                throw new InvalidDataException("A subtitle cue is missing its timecode.");

            var match = SrtTimecodeRegex().Match(lines[timecodeIndex].Trim());
            if (!match.Success)
                throw new InvalidDataException($"Invalid SRT timecode: {lines[timecodeIndex].Trim()}");

            var textStart = timecodeIndex + 1;
            if (textStart >= lines.Length)
                throw new InvalidDataException("A subtitle cue is missing its text.");

            var number = cues.Count + 1;
            var text = string.Join('\n', lines[textStart..]).TrimEnd();
            cues.Add(new SubtitleCue(
                number,
                ParseTimestamp(match.Groups["start"].Value),
                ParseTimestamp(match.Groups["end"].Value),
                text));
        }

        return new SubtitleDocument(cues);
    }

    public string Serialize(string format)
    {
        Validate(_cues);
        return format.TrimStart('.').ToLowerInvariant() switch
        {
            "srt" => SerializeSrt(),
            "vtt" => SerializeVtt(),
            "ass" => SerializeAss(),
            _ => throw new ArgumentOutOfRangeException(nameof(format), format, "Expected srt, vtt, or ass."),
        };
    }

    private string SerializeSrt()
    {
        var output = new StringBuilder();
        for (var index = 0; index < _cues.Count; index++)
        {
            var cue = _cues[index];
            output.AppendLine((index + 1).ToString(CultureInfo.InvariantCulture));
            output.Append(FormatTimestamp(cue.Start, ',')).Append(" --> ")
                .AppendLine(FormatTimestamp(cue.End, ','));
            output.AppendLine(NormalizeText(cue.Text)).AppendLine();
        }

        return output.ToString();
    }

    private string SerializeVtt()
    {
        var output = new StringBuilder("WEBVTT\n\n");
        foreach (var cue in _cues)
        {
            output.Append(FormatTimestamp(cue.Start, '.')).Append(" --> ")
                .AppendLine(FormatTimestamp(cue.End, '.'));
            output.AppendLine(NormalizeText(cue.Text)).AppendLine();
        }

        return output.ToString();
    }

    private string SerializeAss()
    {
        var output = new StringBuilder(
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 0\n\n" +
            "[V4+ Styles]\n" +
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, " +
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, " +
            "Alignment, MarginL, MarginR, MarginV, Encoding\n" +
            "Style: Default,Segoe UI,52,&H00FFFFFF,&H000000FF,&H00101010,&H80000000," +
            "0,0,0,0,100,100,0,0,1,3,1,2,60,60,48,1\n\n" +
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n");

        foreach (var cue in _cues)
        {
            var text = NormalizeText(cue.Text)
                .Replace("\\", "\\\\", StringComparison.Ordinal)
                .Replace("\n", "\\N", StringComparison.Ordinal);
            output.Append("Dialogue: 0,")
                .Append(FormatAssTimestamp(cue.Start)).Append(',')
                .Append(FormatAssTimestamp(cue.End))
                .Append(",Default,,0,0,0,,").AppendLine(text);
        }

        return output.ToString();
    }

    private static void Validate(IReadOnlyList<SubtitleCue> cues)
    {
        if (cues.Count == 0)
            throw new InvalidDataException("At least one subtitle cue is required.");

        TimeSpan? previousStart = null;
        foreach (var cue in cues)
        {
            if (cue.Start < TimeSpan.Zero || cue.End <= cue.Start)
                throw new InvalidDataException($"Cue {cue.Number} must end after a non-negative start time.");
            if (previousStart.HasValue && cue.Start < previousStart.Value)
                throw new InvalidDataException($"Cue {cue.Number} starts before the preceding cue.");
            if (string.IsNullOrWhiteSpace(cue.Text))
                throw new InvalidDataException($"Cue {cue.Number} has no text.");
            previousStart = cue.Start;
        }
    }

    private static TimeSpan ParseTimestamp(string value)
    {
        var normalized = value.Replace('.', ',');
        if (!TimeSpan.TryParseExact(
                normalized,
                @"hh\:mm\:ss\,fff",
                CultureInfo.InvariantCulture,
                out var result))
        {
            throw new InvalidDataException($"Invalid subtitle timestamp: {value}");
        }

        return result;
    }

    private static string FormatTimestamp(TimeSpan value, char separator)
    {
        var totalHours = (int)value.TotalHours;
        return $"{totalHours:00}:{value.Minutes:00}:{value.Seconds:00}{separator}{value.Milliseconds:000}";
    }

    private static string FormatAssTimestamp(TimeSpan value)
    {
        var totalHours = (int)value.TotalHours;
        var centiseconds = value.Milliseconds / 10;
        return $"{totalHours}:{value.Minutes:00}:{value.Seconds:00}.{centiseconds:00}";
    }

    private static string NormalizeText(string text) =>
        text.Replace("\r\n", "\n", StringComparison.Ordinal).Replace('\r', '\n').Trim();

    [GeneratedRegex(@"\n[\t ]*\n+", RegexOptions.CultureInvariant)]
    private static partial Regex BlankLineRegex();

    [GeneratedRegex(
        @"^(?<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?<end>\d{2}:\d{2}:\d{2}[,.]\d{3})(?:\s+.*)?$",
        RegexOptions.CultureInvariant)]
    private static partial Regex SrtTimecodeRegex();
}
