using System.Text.Json;
using System.Text.Json.Serialization;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Services;

/// <summary>
/// Versioned settings needed to repopulate the Converter queue from History.
/// The materialized FFmpeg argument vector remains excluded by
/// <see cref="ConversionOptions"/>; only the validated template is retained.
/// </summary>
public sealed record ConversionRerunRequest
{
    public const int CurrentSchemaVersion = 1;

    public int SchemaVersion { get; init; } = CurrentSchemaVersion;
    public List<string> SourcePaths { get; init; } = [];
    public string OutputFormat { get; init; } = "";
    public string? OutputDirectory { get; init; }
    public string? OutputPath { get; init; }
    public ConversionOptions Options { get; init; } = new();
    public string? FfmpegCommandTemplate { get; init; }
}

public static class ConversionRerunRequestCodec
{
    private const int MaxSourcePaths = 500;
    private const int MaxTemplateLength = 32_768;

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        Converters = { new JsonStringEnumConverter() },
    };

    public static string Serialize(ConversionRerunRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        Validate(request);
        return JsonSerializer.Serialize(request, JsonOptions);
    }

    public static bool TryDeserialize(
        string? json,
        out ConversionRerunRequest? request,
        out string? error)
    {
        request = null;
        error = null;
        if (string.IsNullOrWhiteSpace(json))
        {
            error = "No saved re-run parameters are available.";
            return false;
        }

        try
        {
            var candidate = JsonSerializer.Deserialize<ConversionRerunRequest>(json, JsonOptions)
                ?? throw new InvalidDataException("The re-run payload is empty.");
            Validate(candidate);
            request = candidate;
            return true;
        }
        catch (Exception ex) when (ex is JsonException or InvalidDataException or ArgumentException)
        {
            error = ex.Message;
            return false;
        }
    }

    private static void Validate(ConversionRerunRequest request)
    {
        if (request.SchemaVersion != ConversionRerunRequest.CurrentSchemaVersion)
            throw new InvalidDataException($"Unsupported re-run schema version {request.SchemaVersion}.");
        if (request.SourcePaths is null || request.SourcePaths.Count is < 1 or > MaxSourcePaths)
            throw new InvalidDataException($"A re-run must contain 1-{MaxSourcePaths} source paths.");
        if (request.SourcePaths.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException("Re-run source paths cannot be empty.");
        if (request.Options is null)
            throw new InvalidDataException("Saved conversion options are missing.");
        if (!PathSafety.TryNormalizeExtension(request.OutputFormat, out _))
            throw new InvalidDataException("The saved output format is invalid.");
        if (request.FfmpegCommandTemplate?.Length > MaxTemplateLength)
            throw new InvalidDataException("The saved FFmpeg command template is too large.");
    }
}
