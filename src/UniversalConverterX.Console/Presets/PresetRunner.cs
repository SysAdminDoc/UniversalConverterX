using System.Diagnostics;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Console.Presets;

/// <summary>
/// Spawns sidecar processes from a resolved preset + input list. Mirrors the
/// SidecarRunner discovery rules used by the WinUI app so the CLI agrees with
/// the GUI on which sidecar binary to invoke.
/// </summary>
public static class PresetRunner
{
    public static int RunRaw(string engine, IReadOnlyList<string> args)
    {
        var executable = ResolveSidecar(engine);
        if (executable is null)
        {
            System.Console.Error.WriteLine(
                $"Sidecar '{engine}' not found. Build it with `pwsh tools/{engine}/build.ps1` " +
                "or install a release bundle containing that engine.");
            return 3;
        }

        return Spawn(executable, args, engine);
    }

    public static int Run(ConversionPreset preset, IReadOnlyList<string> inputs)
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

        return preset.Mode switch
        {
            PresetInvocationMode.PerFile => RunPerFile(exe, preset, inputs),
            PresetInvocationMode.BatchInputList => RunBatchInputList(exe, preset, inputs),
            PresetInvocationMode.BatchOutputDir => RunBatchOutputDir(exe, preset, inputs),
            PresetInvocationMode.BatchSingleOutput => RunBatchSingleOutput(exe, preset, inputs),
            PresetInvocationMode.ExtractEach => RunExtractEach(exe, preset, inputs),
            _ => 4,
        };
    }

    private static int RunPerFile(string exe, ConversionPreset preset, IReadOnlyList<string> inputs)
    {
        int rc = 0;
        for (int i = 0; i < inputs.Count; i++)
        {
            var input = inputs[i];
            var output = PresetLoader.ResolveOutputPath(preset, input);
            EnsureDir(output);

            var args = BuildArgList(preset, ["--input", input, "--output", output]);
            var code = Spawn(exe, args, $"[{i + 1}/{inputs.Count}] {Path.GetFileName(input)}");
            if (code != 0) rc = code;
        }
        return rc;
    }

    private static int RunBatchOutputDir(string exe, ConversionPreset preset, IReadOnlyList<string> inputs)
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
        return Spawn(exe, args, $"batch -> {outDir}");
    }

    private static int RunBatchInputList(string exe, ConversionPreset preset, IReadOnlyList<string> inputs)
    {
        var args = PresetInvocationModes.BuildBatchInputArguments(preset.Args, inputs);
        return Spawn(exe, args, $"batch inputs ({inputs.Count})");
    }

    private static int RunBatchSingleOutput(string exe, ConversionPreset preset, IReadOnlyList<string> inputs)
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
        return Spawn(exe, args, $"pack -> {Path.GetFileName(output)}");
    }

    private static int RunExtractEach(string exe, ConversionPreset preset, IReadOnlyList<string> inputs)
    {
        int rc = 0;
        for (int i = 0; i < inputs.Count; i++)
        {
            var input = inputs[i];
            var outDir = PresetLoader.ResolveOutputPath(preset, input);
            Directory.CreateDirectory(outDir);

            var args = BuildArgList(preset, ["--input", input, "--output-dir", outDir]);
            var code = Spawn(exe, args, $"[{i + 1}/{inputs.Count}] {Path.GetFileName(input)}");
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

    private static void EnsureDir(string path)
    {
        var dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
    }

    /// <summary>Mirror of SidecarRunner.Locate semantics.</summary>
    public static string? ResolveSidecar(string toolName) => SidecarCatalog.Resolve(toolName);
}
