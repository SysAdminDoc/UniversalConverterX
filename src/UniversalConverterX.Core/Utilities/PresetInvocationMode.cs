namespace UniversalConverterX.Core.Utilities;

/// <summary>How a preset supplies input and output arguments to a sidecar.</summary>
public enum PresetInvocationMode
{
    PerFile,
    BatchInputList,
    BatchOutputDir,
    BatchSingleOutput,
    ExtractEach,
}

public static class PresetInvocationModes
{
    public const string PerFile = "per-file";
    public const string BatchInputList = "batch-input-list";
    public const string BatchOutputDir = "batch-output-dir";
    public const string BatchSingleOutput = "batch-single-output";
    public const string ExtractEach = "extract-each";

    public static readonly IReadOnlySet<string> SupportedNames =
        new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            PerFile,
            BatchInputList,
            BatchOutputDir,
            BatchSingleOutput,
            ExtractEach,
        };

    public static PresetInvocationMode Parse(string? value) => value?.Trim().ToLowerInvariant() switch
    {
        BatchInputList => PresetInvocationMode.BatchInputList,
        BatchOutputDir => PresetInvocationMode.BatchOutputDir,
        BatchSingleOutput => PresetInvocationMode.BatchSingleOutput,
        ExtractEach => PresetInvocationMode.ExtractEach,
        _ => PresetInvocationMode.PerFile,
    };

    public static string ToWireName(PresetInvocationMode mode) => mode switch
    {
        PresetInvocationMode.BatchInputList => BatchInputList,
        PresetInvocationMode.BatchOutputDir => BatchOutputDir,
        PresetInvocationMode.BatchSingleOutput => BatchSingleOutput,
        PresetInvocationMode.ExtractEach => ExtractEach,
        _ => PerFile,
    };

    public static bool RequiresOutputDirectory(PresetInvocationMode mode) => mode is
        PresetInvocationMode.BatchOutputDir
        or PresetInvocationMode.BatchSingleOutput
        or PresetInvocationMode.ExtractEach;

    public static bool ProducesOutputPath(PresetInvocationMode mode) =>
        mode != PresetInvocationMode.BatchInputList;

    public static List<string> BuildBatchInputArguments(
        IReadOnlyList<string> presetArguments,
        IReadOnlyList<string> inputs)
    {
        ArgumentNullException.ThrowIfNull(presetArguments);
        ArgumentNullException.ThrowIfNull(inputs);
        var arguments = new List<string>(presetArguments) { "--input" };
        arguments.AddRange(inputs);
        return arguments;
    }
}
