namespace UniversalConverterX.Core.Utilities;

public enum ConverterPreflightSeverity
{
    Warning,
    Error,
}

public sealed record ConverterPreflightWarning(
    string Code,
    string Message,
    ConverterPreflightSeverity Severity);

/// <summary>
/// Produces the per-file warnings shown before a Converter queue starts. The
/// analyzer is deliberately independent of the filesystem and converter
/// registry so the UI can pass one coherent snapshot and the rules remain
/// deterministic under test.
/// </summary>
public static class ConverterPreflightAnalyzer
{
    public static IReadOnlyList<ConverterPreflightWarning> Analyze(
        string sourceExtension,
        long sourceBytes,
        bool sourceExists,
        string? outputExtension,
        bool? routeSupported)
    {
        var warnings = new List<ConverterPreflightWarning>();

        if (!sourceExists)
        {
            warnings.Add(new ConverterPreflightWarning(
                "source_missing",
                "Source file is no longer available.",
                ConverterPreflightSeverity.Error));
        }
        else if (sourceBytes <= 0)
        {
            warnings.Add(new ConverterPreflightWarning(
                "source_empty",
                "Source file is empty.",
                ConverterPreflightSeverity.Error));
        }

        var target = outputExtension?.Trim().TrimStart('.');
        if (string.IsNullOrWhiteSpace(target))
        {
            warnings.Add(new ConverterPreflightWarning(
                "output_required",
                "Choose an output format.",
                ConverterPreflightSeverity.Warning));
            return warnings;
        }

        if (routeSupported == false)
        {
            warnings.Add(new ConverterPreflightWarning(
                "route_unsupported",
                $"No converter supports {Normalize(sourceExtension)} to {Normalize(target)}.",
                ConverterPreflightSeverity.Error));
            return warnings;
        }

        if (Normalize(sourceExtension).Equals(Normalize(target), StringComparison.OrdinalIgnoreCase))
        {
            warnings.Add(new ConverterPreflightWarning(
                "same_format",
                "Output matches the source format and may be re-encoded.",
                ConverterPreflightSeverity.Warning));
        }

        return warnings;
    }

    private static string Normalize(string extension)
    {
        var normalized = extension.Trim().TrimStart('.');
        return string.IsNullOrWhiteSpace(normalized)
            ? "UNKNOWN"
            : normalized.ToUpperInvariant();
    }
}
