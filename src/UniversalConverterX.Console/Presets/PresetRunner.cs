using System.Diagnostics;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Console.Presets;

/// <summary>
/// Spawns sidecar processes from a resolved preset + input list. Mirrors the
/// SidecarRunner discovery rules used by the WinUI app so the CLI agrees with
/// the GUI on which sidecar binary to invoke.
/// </summary>
public static class PresetRunner
{
    public static int RunRaw(
        string engine,
        IReadOnlyList<string> args,
        ConverterXOptions? options = null)
    {
        var executable = ResolveSidecar(engine);
        if (executable is null)
        {
            System.Console.Error.WriteLine(
                $"Sidecar '{engine}' not found. Build it with `pwsh tools/{engine}/build.ps1` " +
                "or install a release bundle containing that engine.");
            return 3;
        }

        return SpawnWithOutputPolicy(
            executable,
            args,
            engine,
            options ?? ConverterXOptions.Load());
    }

    public static int Run(
        ConversionPreset preset,
        IReadOnlyList<string> inputs,
        ConverterXOptions? options = null)
    {
        if (inputs.Count == 0)
        {
            System.Console.Error.WriteLine("No input files provided.");
            return 2;
        }

        var exe = ResolveSidecar(preset.Engine);
        if (exe is null)
        {
            System.Console.Error.WriteLine(
                $"Sidecar '{preset.Engine}' not found. Build it with " +
                $"`pwsh tools/{preset.Engine}/build.ps1` or install UCX " +
                $"so the sidecars are bundled.");
            return 3;
        }

        var effectiveOptions = options ?? ConverterXOptions.Load();
        return preset.Mode switch
        {
            PresetInvocationMode.PerFile => RunPerFile(exe, preset, inputs, effectiveOptions),
            PresetInvocationMode.BatchInputList => RunBatchInputList(exe, preset, inputs, effectiveOptions),
            PresetInvocationMode.BatchOutputDir => RunBatchOutputDir(exe, preset, inputs, effectiveOptions),
            PresetInvocationMode.BatchSingleOutput => RunBatchSingleOutput(exe, preset, inputs, effectiveOptions),
            PresetInvocationMode.ExtractEach => RunExtractEach(exe, preset, inputs, effectiveOptions),
            _ => 4,
        };
    }

    private static int RunPerFile(
        string exe,
        ConversionPreset preset,
        IReadOnlyList<string> inputs,
        ConverterXOptions options)
    {
        int rc = 0;
        for (int i = 0; i < inputs.Count; i++)
        {
            var input = inputs[i];
            var output = PresetLoader.ResolveOutputPath(preset, input);
            EnsureDir(output);

            var args = BuildArgList(preset, ["--input", input, "--output", output]);
            var code = SpawnWithOutputPolicy(
                exe, args, $"[{i + 1}/{inputs.Count}] {Path.GetFileName(input)}", options);
            if (code != 0) rc = code;
        }
        return rc;
    }

    private static int RunBatchOutputDir(
        string exe,
        ConversionPreset preset,
        IReadOnlyList<string> inputs,
        ConverterXOptions options)
    {
        // All outputs land in the directory of the first input (or a
        // template-resolved one). Sidecar names files by stem internally.
        var first = inputs[0];
        var outDir = Path.GetDirectoryName(PresetLoader.ResolveOutputPath(preset, first))
                     ?? Path.GetDirectoryName(first)
                     ?? Environment.CurrentDirectory;
        Directory.CreateDirectory(outDir);

        var args = new List<string>(preset.Args)
        {
            "--output-dir", outDir,
            "--input",
        };
        args.AddRange(inputs);
        return SpawnWithOutputPolicy(exe, args, $"batch -> {outDir}", options);
    }

    private static int RunBatchInputList(
        string exe,
        ConversionPreset preset,
        IReadOnlyList<string> inputs,
        ConverterXOptions options)
    {
        var args = PresetInvocationModes.BuildBatchInputArguments(preset.Args, inputs);
        return SpawnWithOutputPolicy(exe, args, $"batch inputs ({inputs.Count})", options);
    }

    private static int RunBatchSingleOutput(
        string exe,
        ConversionPreset preset,
        IReadOnlyList<string> inputs,
        ConverterXOptions options)
    {
        // Pack -> single archive named after the first input's stem.
        var first = inputs[0];
        var output = PresetLoader.ResolveOutputPath(preset, first);
        EnsureDir(output);

        var args = new List<string>(preset.Args)
        {
            "--output", output,
            "--input",
        };
        args.AddRange(inputs);
        return SpawnWithOutputPolicy(exe, args, $"pack -> {Path.GetFileName(output)}", options);
    }

    private static int RunExtractEach(
        string exe,
        ConversionPreset preset,
        IReadOnlyList<string> inputs,
        ConverterXOptions options)
    {
        int rc = 0;
        for (int i = 0; i < inputs.Count; i++)
        {
            var input = inputs[i];
            var desiredOutDir = PresetLoader.ResolveOutputPath(preset, input);
            if (!OutputCollisionPolicy.TryResolvePath(
                    desiredOutDir,
                    options.OverwriteBehavior,
                    out var outDir,
                    out var shouldSkip,
                    out var error))
            {
                System.Console.Error.WriteLine(error);
                if (rc == 0) rc = 4;
                continue;
            }

            if (shouldSkip)
            {
                System.Console.WriteLine(
                    $">> skipped [{i + 1}/{inputs.Count}] {Path.GetFileName(input)}: " +
                    $"output directory already exists at '{desiredOutDir}'.");
                continue;
            }

            Directory.CreateDirectory(outDir);

            var args = BuildArgList(preset, ["--input", input, "--output-dir", outDir]);
            var code = SpawnWithOutputPolicy(
                exe, args, $"[{i + 1}/{inputs.Count}] {Path.GetFileName(input)}", options);
            if (code != 0) rc = code;
        }
        return rc;
    }

    private static List<string> BuildArgList(ConversionPreset preset, IEnumerable<string> tail)
    {
        var list = new List<string>(preset.Args);
        list.AddRange(tail);
        return list;
    }

    private static int Spawn(string exe, IReadOnlyList<string> args, string label)
    {
        System.Console.WriteLine($">> {label}");
        var psi = new ProcessStartInfo
        {
            FileName = exe,
            UseShellExecute = false,
        };
        foreach (var a in args) psi.ArgumentList.Add(a);
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        try
        {
            using var p = Process.Start(psi)
                ?? throw new InvalidOperationException($"Failed to start {exe}");
            p.WaitForExit();
            return p.ExitCode;
        }
        catch (Exception ex)
        {
            System.Console.Error.WriteLine($"Spawn failed: {ex.Message}");
            return -1;
        }
    }

    private static int SpawnWithOutputPolicy(
        string exe,
        IReadOnlyList<string> args,
        string label,
        ConverterXOptions options)
    {
        if (!OutputCollisionPolicy.TryProtectArguments(
                args,
                options.OverwriteBehavior,
                out var protectedArguments,
                out var skippedOutput,
                out var error))
        {
            System.Console.Error.WriteLine(error);
            return 4;
        }

        if (skippedOutput is not null)
        {
            System.Console.WriteLine(
                $">> skipped {label}: output already exists at '{skippedOutput}' " +
                "and the overwrite policy is Skip.");
            return 0;
        }

        return Spawn(exe, protectedArguments, label);
    }

    private static void EnsureDir(string path)
    {
        var dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
    }

    /// <summary>Mirror of SidecarRunner.Locate semantics.</summary>
    public static string? ResolveSidecar(string toolName) => SidecarCatalog.Resolve(toolName);
}
