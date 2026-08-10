using System.Diagnostics;
using System.ComponentModel;
using System.Globalization;
using System.Text.Json;

namespace UniversalConverterX.Core.Utilities;

/// <summary>
/// A bounded, metadata-focused FFprobe snapshot. The snapshot deliberately
/// excludes packet data and byte offsets so it can be compared after a
/// stream-copy or encode without retaining a copy of the media.
/// </summary>
public sealed record MediaFidelitySnapshot(
    string SourcePath,
    double? DurationSeconds,
    int? StreamCount,
    IReadOnlyList<MediaFidelityStream> Streams,
    IReadOnlyList<MediaFidelityChapter> Chapters,
    IReadOnlyDictionary<string, string> FormatTags);

public sealed record MediaFidelityStream(
    string Type,
    int? Index,
    string? Codec,
    IReadOnlyDictionary<string, string> Tags,
    IReadOnlyDictionary<string, int> Disposition,
    IReadOnlyDictionary<string, string> Properties,
    IReadOnlyList<string> SideData,
    bool AttachedPicture,
    string? Rotation);

public sealed record MediaFidelityChapter(
    int? Id,
    double? StartSeconds,
    double? EndSeconds,
    IReadOnlyDictionary<string, string> Tags);

public sealed record MediaFidelityProbeResult(
    bool Succeeded,
    MediaFidelitySnapshot? Snapshot,
    string? Diagnostic)
{
    public static MediaFidelityProbeResult Success(MediaFidelitySnapshot snapshot) =>
        new(true, snapshot, null);

    public static MediaFidelityProbeResult Failure(string diagnostic) =>
        new(false, null, diagnostic);
}

public sealed record MediaFidelityComparisonOptions
{
    /// <summary>Compare codec names in addition to stream metadata.</summary>
    public bool RequireCodecIdentity { get; init; } = true;

    /// <summary>Permitted duration difference caused by container time bases.</summary>
    public double DurationToleranceSeconds { get; init; } = 0.25;

    /// <summary>Format tags emitted by encoders rather than the source.</summary>
    public IReadOnlySet<string> IgnoredFormatTags { get; init; } =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "encoder" };

    /// <summary>
    /// Container-generated stream tags whose rounded time base or muxer name
    /// can change during an otherwise lossless remux.
    /// </summary>
    public IReadOnlySet<string> IgnoredStreamTags { get; init; } =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "duration", "encoder" };
}

public sealed record MediaFidelityComparison(
    bool IsMatch,
    IReadOnlyList<string> Mismatches);

/// <summary>
/// Probes and compares the metadata that a conversion must preserve. It is
/// safe for untrusted media: FFprobe is run without a shell, both redirected
/// pipes are drained concurrently, malformed JSON becomes a diagnostic, and
/// cancellation kills only the probe process tree.
/// </summary>
public static class MediaFidelityProbe
{
    private static readonly IReadOnlySet<string> EmptyTags =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    private static readonly string[] StreamProperties =
    [
        "width", "height", "pix_fmt", "profile", "level", "field_order",
        "sample_aspect_ratio", "display_aspect_ratio", "color_space",
        "color_transfer", "color_primaries", "chroma_location", "sample_rate",
        "channels", "channel_layout", "bits_per_raw_sample", "codec_tag_string",
        "time_base", "avg_frame_rate", "r_frame_rate"
    ];

    public static async Task<MediaFidelityProbeResult> ProbeAsync(
        string ffprobePath,
        string mediaPath,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(ffprobePath))
            return MediaFidelityProbeResult.Failure("FFprobe path is required.");

        if (string.IsNullOrWhiteSpace(mediaPath) || !File.Exists(mediaPath))
            return MediaFidelityProbeResult.Failure("The media file does not exist.");

        var startInfo = new ProcessStartInfo
        {
            FileName = ffprobePath,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
        };
        foreach (var argument in new[]
        {
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            mediaPath,
        })
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
                return MediaFidelityProbeResult.Failure("FFprobe could not be started.");

            var stdoutTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
            var stderrTask = process.StandardError.ReadToEndAsync(cancellationToken);
            await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);

            var stdout = await stdoutTask.ConfigureAwait(false);
            var stderr = await stderrTask.ConfigureAwait(false);
            if (process.ExitCode != 0)
                return MediaFidelityProbeResult.Failure(
                    string.IsNullOrWhiteSpace(stderr)
                        ? $"FFprobe exited with code {process.ExitCode}."
                        : stderr.Trim());

            try
            {
                return MediaFidelityProbeResult.Success(Parse(stdout, mediaPath));
            }
            catch (JsonException ex)
            {
                return MediaFidelityProbeResult.Failure($"FFprobe returned invalid JSON: {ex.Message}");
            }
            catch (InvalidDataException ex)
            {
                return MediaFidelityProbeResult.Failure(ex.Message);
            }
        }
        catch (OperationCanceledException)
        {
            TryKill(process);
            return MediaFidelityProbeResult.Failure("FFprobe was cancelled.");
        }
        catch (Exception ex) when (ex is InvalidOperationException or Win32Exception)
        {
            return MediaFidelityProbeResult.Failure($"FFprobe could not inspect the media: {ex.Message}");
        }
    }

    /// <summary>
    /// Extracts user-facing per-track names using the FFprobe stream type and
    /// zero-based ordinal that FFmpeg accepts in a stream metadata specifier.
    /// QuickTime/MOV exposes its <c>udta</c> track name as the stream
    /// <c>name</c> tag; <c>title</c> is accepted as a fallback for other
    /// containers.
    /// </summary>
    public static IReadOnlyDictionary<string, string> ExtractTrackNames(
        MediaFidelitySnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);

        var names = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var ordinals = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var stream in snapshot.Streams)
        {
            var type = stream.Type.ToLowerInvariant() switch
            {
                "video" => "v",
                "audio" => "a",
                "subtitle" => "s",
                _ => null,
            };
            if (type is null)
                continue;

            var ordinal = ordinals.TryGetValue(type, out var current) ? current : 0;
            ordinals[type] = ordinal + 1;

            if ((!stream.Tags.TryGetValue("name", out var name)
                    || string.IsNullOrWhiteSpace(name))
                && (!stream.Tags.TryGetValue("title", out name)
                    || string.IsNullOrWhiteSpace(name)))
            {
                continue;
            }

            names[$"{type}:{ordinal}"] = name;
        }

        return names;
    }

    /// <summary>
    /// Parses a previously captured FFprobe JSON document. Keeping this parser
    /// public lets release tests prove malformed-input handling without needing
    /// a native media fixture or a process invocation.
    /// </summary>
    public static MediaFidelitySnapshot Parse(string json, string sourcePath = "")
    {
        if (string.IsNullOrWhiteSpace(json))
            throw new InvalidDataException("FFprobe returned an empty document.");

        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object)
            throw new InvalidDataException("FFprobe returned a non-object document.");

        var streams = new List<MediaFidelityStream>();
        if (root.TryGetProperty("streams", out var streamArray))
        {
            if (streamArray.ValueKind != JsonValueKind.Array)
                throw new InvalidDataException("FFprobe streams is not an array.");

            foreach (var stream in streamArray.EnumerateArray())
            {
                if (stream.ValueKind != JsonValueKind.Object)
                    throw new InvalidDataException("FFprobe contains a non-object stream.");

                streams.Add(ParseStream(stream));
            }
        }

        var chapters = new List<MediaFidelityChapter>();
        if (root.TryGetProperty("chapters", out var chapterArray))
        {
            if (chapterArray.ValueKind != JsonValueKind.Array)
                throw new InvalidDataException("FFprobe chapters is not an array.");

            foreach (var chapter in chapterArray.EnumerateArray())
            {
                if (chapter.ValueKind != JsonValueKind.Object)
                    throw new InvalidDataException("FFprobe contains a non-object chapter.");

                chapters.Add(new MediaFidelityChapter(
                    ReadInt(chapter, "id"),
                    ReadDouble(chapter, "start_time"),
                    ReadDouble(chapter, "end_time"),
                    ReadTags(chapter, "tags")));
            }
        }

        var format = root.TryGetProperty("format", out var formatElement)
            && formatElement.ValueKind == JsonValueKind.Object
            ? formatElement
            : default;

        return new MediaFidelitySnapshot(
            sourcePath,
            ReadDouble(format, "duration"),
            ReadInt(format, "nb_streams"),
            streams,
            chapters,
            ReadTags(format, "tags"));
    }

    public static MediaFidelityComparison Compare(
        MediaFidelitySnapshot expected,
        MediaFidelitySnapshot actual,
        MediaFidelityComparisonOptions? options = null)
    {
        options ??= new MediaFidelityComparisonOptions();
        var mismatches = new List<string>();

        CompareOptionalNumber(
            "format duration",
            expected.DurationSeconds,
            actual.DurationSeconds,
            options.DurationToleranceSeconds,
            mismatches);

        if (expected.StreamCount.HasValue && actual.StreamCount.HasValue
            && expected.StreamCount != actual.StreamCount)
        {
            mismatches.Add($"stream count: expected {expected.StreamCount}, actual {actual.StreamCount}");
        }

        CompareTags(
            "format tags",
            expected.FormatTags,
            actual.FormatTags,
            options.IgnoredFormatTags,
            mismatches);

        if (expected.Streams.Count != actual.Streams.Count)
        {
            mismatches.Add($"stream list count: expected {expected.Streams.Count}, actual {actual.Streams.Count}");
        }

        var streamCount = Math.Min(expected.Streams.Count, actual.Streams.Count);
        for (var i = 0; i < streamCount; i++)
        {
            var expectedStream = expected.Streams[i];
            var actualStream = actual.Streams[i];
            var prefix = $"stream {i} ({expectedStream.Type})";

            if (!string.Equals(expectedStream.Type, actualStream.Type, StringComparison.OrdinalIgnoreCase))
                mismatches.Add($"{prefix} type: actual {actualStream.Type}");

            if (options.RequireCodecIdentity
                && !string.Equals(expectedStream.Codec, actualStream.Codec, StringComparison.OrdinalIgnoreCase))
            {
                mismatches.Add($"{prefix} codec: expected {expectedStream.Codec}, actual {actualStream.Codec}");
            }

            CompareTags(
                $"{prefix} tags",
                expectedStream.Tags,
                actualStream.Tags,
                options.IgnoredStreamTags,
                mismatches);
            CompareDictionary($"{prefix} disposition", expectedStream.Disposition, actualStream.Disposition, mismatches);
            CompareDictionary($"{prefix} properties", expectedStream.Properties, actualStream.Properties, mismatches);
            CompareList($"{prefix} side data", expectedStream.SideData, actualStream.SideData, mismatches);

            if (expectedStream.AttachedPicture != actualStream.AttachedPicture)
            {
                mismatches.Add(
                    $"{prefix} attached-picture flag: expected {expectedStream.AttachedPicture}, actual {actualStream.AttachedPicture}");
            }

            if (!string.Equals(expectedStream.Rotation, actualStream.Rotation, StringComparison.OrdinalIgnoreCase))
            {
                mismatches.Add($"{prefix} rotation: expected {expectedStream.Rotation}, actual {actualStream.Rotation}");
            }
        }

        if (expected.Chapters.Count != actual.Chapters.Count)
        {
            mismatches.Add($"chapter count: expected {expected.Chapters.Count}, actual {actual.Chapters.Count}");
        }

        var chapterCount = Math.Min(expected.Chapters.Count, actual.Chapters.Count);
        for (var i = 0; i < chapterCount; i++)
        {
            var expectedChapter = expected.Chapters[i];
            var actualChapter = actual.Chapters[i];
            var prefix = $"chapter {i}";
            if (expectedChapter.Id != actualChapter.Id)
                mismatches.Add($"{prefix} id: expected {expectedChapter.Id}, actual {actualChapter.Id}");

            CompareOptionalNumber(
                $"{prefix} start",
                expectedChapter.StartSeconds,
                actualChapter.StartSeconds,
                options.DurationToleranceSeconds,
                mismatches);
            CompareOptionalNumber(
                $"{prefix} end",
                expectedChapter.EndSeconds,
                actualChapter.EndSeconds,
                options.DurationToleranceSeconds,
                mismatches);
            CompareTags(
                $"{prefix} tags",
                expectedChapter.Tags,
                actualChapter.Tags,
                EmptyTags,
                mismatches);
        }

        return new MediaFidelityComparison(mismatches.Count == 0, mismatches);
    }

    private static MediaFidelityStream ParseStream(JsonElement stream)
    {
        var properties = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var property in StreamProperties)
        {
            var value = ReadString(stream, property);
            if (value is not null)
                properties[property] = value;
        }

        var sideData = new List<string>();
        if (stream.TryGetProperty("side_data_list", out var sideDataArray)
            && sideDataArray.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in sideDataArray.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.Object)
                    sideData.Add(CanonicalJson(item));
            }
        }

        var tags = ReadTags(stream, "tags");
        var rotation = tags.TryGetValue("rotate", out var tagRotation) ? tagRotation : null;
        if (rotation is null)
        {
            rotation = sideData
                .Select(ExtractRotation)
                .FirstOrDefault(value => value is not null);
        }

        return new MediaFidelityStream(
            ReadString(stream, "codec_type") ?? "unknown",
            ReadInt(stream, "index"),
            ReadString(stream, "codec_name"),
            tags,
            ReadIntDictionary(stream, "disposition"),
            properties,
            sideData,
            ReadInt(stream, "disposition", "attached_pic") == 1,
            rotation);
    }

    private static void CompareTags(
        string label,
        IReadOnlyDictionary<string, string> expected,
        IReadOnlyDictionary<string, string> actual,
        IReadOnlySet<string> ignored,
        ICollection<string> mismatches)
    {
        var expectedFiltered = expected
            .Where(pair => !ignored.Contains(pair.Key))
            .ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.OrdinalIgnoreCase);
        var actualFiltered = actual
            .Where(pair => !ignored.Contains(pair.Key))
            .ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.OrdinalIgnoreCase);
        CompareDictionary(label, expectedFiltered, actualFiltered, mismatches);
    }

    private static void CompareDictionary<T>(
        string label,
        IReadOnlyDictionary<string, T> expected,
        IReadOnlyDictionary<string, T> actual,
        ICollection<string> mismatches)
    {
        var keys = expected.Keys
            .Concat(actual.Keys)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(key => key, StringComparer.OrdinalIgnoreCase);
        foreach (var key in keys)
        {
            expected.TryGetValue(key, out var expectedValue);
            actual.TryGetValue(key, out var actualValue);
            if (!EqualityComparer<T>.Default.Equals(expectedValue, actualValue))
            {
                var expectedText = expected.ContainsKey(key) ? expectedValue?.ToString() : "<missing>";
                var actualText = actual.ContainsKey(key) ? actualValue?.ToString() : "<missing>";
                mismatches.Add($"{label} {key}: expected {expectedText}, actual {actualText}");
            }
        }
    }

    private static void CompareList<T>(
        string label,
        IReadOnlyList<T> expected,
        IReadOnlyList<T> actual,
        ICollection<string> mismatches)
    {
        if (expected.Count != actual.Count)
        {
            mismatches.Add($"{label} count: expected {expected.Count}, actual {actual.Count}");
            return;
        }

        for (var i = 0; i < expected.Count; i++)
        {
            if (!EqualityComparer<T>.Default.Equals(expected[i], actual[i]))
                mismatches.Add($"{label}[{i}] differs");
        }
    }

    private static void CompareOptionalNumber(
        string label,
        double? expected,
        double? actual,
        double tolerance,
        ICollection<string> mismatches)
    {
        if (expected.HasValue != actual.HasValue)
        {
            mismatches.Add($"{label}: expected {expected?.ToString(CultureInfo.InvariantCulture) ?? "<missing>"}, actual {actual?.ToString(CultureInfo.InvariantCulture) ?? "<missing>"}");
            return;
        }

        if (expected.HasValue && Math.Abs(expected.Value - actual!.Value) > tolerance)
        {
            mismatches.Add($"{label}: expected {expected.Value.ToString(CultureInfo.InvariantCulture)}, actual {actual.Value.ToString(CultureInfo.InvariantCulture)}");
        }
    }

    private static IReadOnlyDictionary<string, string> ReadTags(JsonElement parent, string propertyName)
    {
        if (!parent.TryGetProperty(propertyName, out var tags) || tags.ValueKind != JsonValueKind.Object)
            return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var property in tags.EnumerateObject())
            result[property.Name] = ScalarText(property.Value);
        return result;
    }

    private static IReadOnlyDictionary<string, int> ReadIntDictionary(JsonElement parent, string propertyName)
    {
        if (!parent.TryGetProperty(propertyName, out var values) || values.ValueKind != JsonValueKind.Object)
            return new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        var result = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var property in values.EnumerateObject())
        {
            if (TryReadInt(property.Value, out var value))
                result[property.Name] = value;
        }
        return result;
    }

    private static string? ReadString(JsonElement parent, string propertyName)
    {
        if (parent.ValueKind != JsonValueKind.Object || !parent.TryGetProperty(propertyName, out var value))
            return null;
        return ScalarText(value);
    }

    private static int? ReadInt(JsonElement parent, string propertyName)
    {
        if (TryReadInt(parent, propertyName, out var value))
            return value;
        return null;
    }

    private static int? ReadInt(JsonElement parent, string objectProperty, string nestedProperty)
    {
        if (parent.ValueKind != JsonValueKind.Object || !parent.TryGetProperty(objectProperty, out var nested))
            return null;
        return ReadInt(nested, nestedProperty);
    }

    private static bool TryReadInt(JsonElement parent, string propertyName, out int value)
    {
        value = default;
        return parent.ValueKind == JsonValueKind.Object
            && parent.TryGetProperty(propertyName, out var element)
            && TryReadInt(element, out value);
    }

    private static bool TryReadInt(JsonElement element, out int value)
    {
        if (element.ValueKind == JsonValueKind.Number && element.TryGetInt32(out value))
            return true;

        return int.TryParse(
            ScalarText(element),
            NumberStyles.Integer,
            CultureInfo.InvariantCulture,
            out value);
    }

    private static double? ReadDouble(JsonElement parent, string propertyName)
    {
        if (parent.ValueKind != JsonValueKind.Object || !parent.TryGetProperty(propertyName, out var element))
            return null;

        var text = ScalarText(element);
        return double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var value)
            ? value
            : null;
    }

    private static string ScalarText(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.String => value.GetString() ?? string.Empty,
        JsonValueKind.Null => string.Empty,
        _ => value.ToString(),
    };

    private static string CanonicalJson(JsonElement value)
    {
        using var document = JsonDocument.Parse(value.GetRawText());
        using var stream = new MemoryStream();
        using (var writer = new Utf8JsonWriter(stream))
            WriteCanonical(writer, document.RootElement);
        return System.Text.Encoding.UTF8.GetString(stream.ToArray());
    }

    private static void WriteCanonical(Utf8JsonWriter writer, JsonElement value)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                writer.WriteStartObject();
                foreach (var property in value.EnumerateObject().OrderBy(item => item.Name, StringComparer.Ordinal))
                {
                    writer.WritePropertyName(property.Name);
                    WriteCanonical(writer, property.Value);
                }
                writer.WriteEndObject();
                break;
            case JsonValueKind.Array:
                writer.WriteStartArray();
                foreach (var item in value.EnumerateArray())
                    WriteCanonical(writer, item);
                writer.WriteEndArray();
                break;
            default:
                value.WriteTo(writer);
                break;
        }
    }

    private static string? ExtractRotation(string sideData)
    {
        try
        {
            using var document = JsonDocument.Parse(sideData);
            return ReadString(document.RootElement, "rotation");
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static void TryKill(Process process)
    {
        try
        {
            if (!process.HasExited)
                process.Kill(entireProcessTree: true);
        }
        catch
        {
            // Cancellation must remain best-effort even if the child exited.
        }
    }
}
