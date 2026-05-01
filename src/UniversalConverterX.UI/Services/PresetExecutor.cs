namespace UniversalConverterX.UI.Services;

/// <summary>
/// Runs a <see cref="UiPreset"/> against a list of input files via the configured
/// <see cref="ISidecarRunner"/>. Centralises the four invocation modes so callers
/// (PresetsPage, UniversalConvertPage, the future shell-extension trampoline)
/// don't each maintain their own copy of the dispatch table.
/// </summary>
public sealed record PresetExecutionResult(
    bool Success,
    string? ErrorCode,
    string? ErrorMessage,
    int ExitCode,
    int RanCount);

public interface IPresetExecutor
{
    Task<PresetExecutionResult> RunAsync(
        UiPreset preset,
        IReadOnlyList<string> inputs,
        string? outputDir,
        IProgress<SidecarProgress>? progress = null,
        IProgress<SidecarLog>? log = null,
        CancellationToken cancellationToken = default);
}

public sealed class PresetExecutor : IPresetExecutor
{
    private readonly ISidecarRunner _runner;

    public PresetExecutor(ISidecarRunner runner)
    {
        _runner = runner;
    }

    public async Task<PresetExecutionResult> RunAsync(
        UiPreset preset,
        IReadOnlyList<string> inputs,
        string? outputDir,
        IProgress<SidecarProgress>? progress = null,
        IProgress<SidecarLog>? log = null,
        CancellationToken cancellationToken = default)
    {
        if (inputs is null || inputs.Count == 0)
            return new PresetExecutionResult(false, "no_inputs", "No input files were provided.", -1, 0);

        try
        {
            switch (preset.Mode)
            {
                case PresetInvocationMode.PerFile:
                    return await RunPerFileAsync(preset, inputs, progress, log, cancellationToken).ConfigureAwait(false);

                case PresetInvocationMode.BatchOutputDir:
                    if (string.IsNullOrWhiteSpace(outputDir))
                        return new PresetExecutionResult(false, "missing_output_dir",
                            "BatchOutputDir presets need an output directory.", -1, 0);
                    return await RunBatchOutputDirAsync(preset, inputs, outputDir!, progress, log, cancellationToken).ConfigureAwait(false);

                case PresetInvocationMode.BatchSingleOutput:
                    return await RunBatchSingleOutputAsync(preset, inputs, outputDir, progress, log, cancellationToken).ConfigureAwait(false);

                case PresetInvocationMode.ExtractEach:
                    return await RunExtractEachAsync(preset, inputs, outputDir, progress, log, cancellationToken).ConfigureAwait(false);

                default:
                    return new PresetExecutionResult(false, "unknown_mode",
                        $"Unsupported preset invocation mode: {preset.Mode}", -1, 0);
            }
        }
        catch (OperationCanceledException)
        {
            return new PresetExecutionResult(false, "cancelled", "Cancelled by user.", -1, 0);
        }
        catch (Exception ex)
        {
            return new PresetExecutionResult(false, "internal", ex.Message, -1, 0);
        }
    }

    private async Task<PresetExecutionResult> RunPerFileAsync(
        UiPreset preset, IReadOnlyList<string> inputs,
        IProgress<SidecarProgress>? progress, IProgress<SidecarLog>? log, CancellationToken ct)
    {
        int exit = 0, ran = 0;
        for (var i = 0; i < inputs.Count; i++)
        {
            ct.ThrowIfCancellationRequested();
            var input = inputs[i];
            var output = UiPresetLoader.ResolveOutputPath(preset, input);
            if (!TryCreateDirectory(Path.GetDirectoryName(output)))
            {
                return new PresetExecutionResult(false, "output_dir_unavailable",
                    $"Could not create output directory for '{output}'.", -1, ran);
            }

            var args = new List<string>(preset.Args) { "--input", input, "--output", output };
            var r = await _runner.RunAsync(preset.Engine, args, progress, log, ct).ConfigureAwait(false);
            ran++;
            if (!r.Success)
                return new PresetExecutionResult(false, r.ErrorCode, r.ErrorMessage, r.ExitCode, ran);
            exit = r.ExitCode;
        }
        return new PresetExecutionResult(true, null, null, exit, ran);
    }

    private async Task<PresetExecutionResult> RunBatchOutputDirAsync(
        UiPreset preset, IReadOnlyList<string> inputs, string outputDir,
        IProgress<SidecarProgress>? progress, IProgress<SidecarLog>? log, CancellationToken ct)
    {
        if (!TryCreateDirectory(outputDir))
            return new PresetExecutionResult(false, "output_dir_unavailable",
                $"Could not create output directory '{outputDir}'.", -1, 0);

        var args = new List<string>(preset.Args);
        args.AddRange(["--output-dir", outputDir, "--input"]);
        args.AddRange(inputs);
        var r = await _runner.RunAsync(preset.Engine, args, progress, log, ct).ConfigureAwait(false);
        return new PresetExecutionResult(r.Success, r.ErrorCode, r.ErrorMessage, r.ExitCode, r.Success ? inputs.Count : 0);
    }

    private async Task<PresetExecutionResult> RunBatchSingleOutputAsync(
        UiPreset preset, IReadOnlyList<string> inputs, string? outputDir,
        IProgress<SidecarProgress>? progress, IProgress<SidecarLog>? log, CancellationToken ct)
    {
        var first = inputs[0];
        var output = outputDir is null
            ? UiPresetLoader.ResolveOutputPath(preset, first)
            : Path.Combine(outputDir, Path.GetFileNameWithoutExtension(first) + "." + preset.OutputExtension);
        if (!TryCreateDirectory(Path.GetDirectoryName(output)))
            return new PresetExecutionResult(false, "output_dir_unavailable",
                $"Could not create output directory for '{output}'.", -1, 0);

        var args = new List<string>(preset.Args);
        args.AddRange(["--output", output, "--input"]);
        args.AddRange(inputs);
        var r = await _runner.RunAsync(preset.Engine, args, progress, log, ct).ConfigureAwait(false);
        return new PresetExecutionResult(r.Success, r.ErrorCode, r.ErrorMessage, r.ExitCode, r.Success ? inputs.Count : 0);
    }

    private async Task<PresetExecutionResult> RunExtractEachAsync(
        UiPreset preset, IReadOnlyList<string> inputs, string? outputDir,
        IProgress<SidecarProgress>? progress, IProgress<SidecarLog>? log, CancellationToken ct)
    {
        int exit = 0, ran = 0;
        for (var i = 0; i < inputs.Count; i++)
        {
            ct.ThrowIfCancellationRequested();
            var input = inputs[i];
            var perOut = outputDir is null
                ? UiPresetLoader.ResolveOutputPath(preset, input)
                : Path.Combine(outputDir, Path.GetFileNameWithoutExtension(input));
            if (!TryCreateDirectory(perOut))
            {
                return new PresetExecutionResult(false, "output_dir_unavailable",
                    $"Could not create output directory '{perOut}'.", -1, ran);
            }

            var args = new List<string>(preset.Args) { "--input", input, "--output-dir", perOut };
            var r = await _runner.RunAsync(preset.Engine, args, progress, log, ct).ConfigureAwait(false);
            ran++;
            if (!r.Success)
                return new PresetExecutionResult(false, r.ErrorCode, r.ErrorMessage, r.ExitCode, ran);
            exit = r.ExitCode;
        }
        return new PresetExecutionResult(true, null, null, exit, ran);
    }

    /// <summary>
    /// Wraps Directory.CreateDirectory so a permission/disk-full failure surfaces
    /// as a structured error instead of an unhandled exception. Returns true if
    /// the directory exists (or was created), false otherwise.
    /// </summary>
    private static bool TryCreateDirectory(string? dir)
    {
        if (string.IsNullOrEmpty(dir)) return true;
        try { Directory.CreateDirectory(dir); return true; }
        catch { return false; }
    }
}
