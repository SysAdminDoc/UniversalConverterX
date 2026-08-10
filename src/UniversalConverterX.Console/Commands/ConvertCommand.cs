using System.ComponentModel;
using Microsoft.Extensions.Options;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Console.Configuration;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Console.Commands;

public class ConvertCommand : AsyncCommand<ConvertCommand.Settings>
{
    public class Settings : CommandSettings
    {
        [CommandArgument(0, "<FILES>")]
        [Description("Input file(s) to convert. Supports glob patterns like *.png")]
        public string[] Files { get; set; } = [];

        [CommandOption("-o|--output <FORMAT>")]
        [Description("Output format (e.g., mp4, png, pdf)")]
        public string? OutputFormat { get; set; }

        [CommandOption("-d|--directory <PATH>")]
        [Description("Output directory (default: same as input)")]
        public string? OutputDirectory { get; set; }

        [CommandOption("-q|--quality <QUALITY>")]
        [Description("Quality preset: lowest, low, medium, high, highest, lossless")]
        public string? Quality { get; set; }

        [CommandOption("-f|--force")]
        [Description("Overwrite existing files")]
        [DefaultValue(false)]
        public bool Force { get; set; }

        [CommandOption("-p|--parallel <COUNT>")]
        [Description("Maximum parallel conversions")]
        public int? Parallel { get; set; }

        [CommandOption("--no-progress")]
        [Description("Disable progress display")]
        [DefaultValue(false)]
        public bool NoProgress { get; set; }

        [CommandOption("--converter <ID>")]
        [Description("Force a specific converter (e.g., ffmpeg, imagemagick)")]
        public string? Converter { get; set; }

        [CommandOption("--keep-metadata")]
        [Description("Preserve metadata from source file")]
        public bool? KeepMetadata { get; set; }

        [CommandOption("--hw-accel")]
        [Description("Enable hardware acceleration")]
        public bool? HardwareAccel { get; set; }

        [CommandOption("--width <PIXELS>")]
        [Description("Output width (images/video)")]
        public int? Width { get; set; }

        [CommandOption("--height <PIXELS>")]
        [Description("Output height (images/video)")]
        public int? Height { get; set; }

        [CommandOption("--bitrate <KBPS>")]
        [Description("Output bitrate in kbps (audio/video)")]
        public int? Bitrate { get; set; }

        [CommandOption("--tools-path <PATH>")]
        [Description("Path to converter tools")]
        public string? ToolsPath { get; set; }

        [CommandOption("--source-action <ACTION>")]
        [Description("After successful conversion: keep, move, or delete the source file")]
        public string? SourceAction { get; set; }

        [CommandOption("--source-archive <PATH>")]
        [Description("Archive folder for --source-action move. Relative paths resolve beside each source file.")]
        public string? SourceArchive { get; set; }

        [CommandOption("--report <PATH>")]
        [Description("Write a per-file batch report. The path must end in .json or .csv.")]
        public string? ReportPath { get; set; }

        [CommandOption("--copy|--remux")]
        [Description("Remux only: change the container without re-encoding (FFmpeg -c copy). Fast and lossless when the source codecs are allowed in the target container.")]
        public bool StreamCopy { get; set; }

        [CommandOption("--audio-tracks <INDICES>")]
        [Description("Keep only these zero-based audio streams (comma-separated, e.g. 0,2). Omit to keep all; pass 'none' to drop all audio.")]
        public string? AudioTracks { get; set; }

        [CommandOption("--subtitle-tracks <INDICES>")]
        [Description("Keep only these zero-based subtitle streams (comma-separated). Omit to keep all; pass 'none' to drop all subtitles.")]
        public string? SubtitleTracks { get; set; }
    }

    private static List<int>? ParseTrackSelection(string? value)
    {
        if (value is null)
            return null;

        var trimmed = value.Trim();
        if (trimmed.Length == 0 || trimmed.Equals("none", StringComparison.OrdinalIgnoreCase))
            return [];

        var indices = new List<int>();
        foreach (var part in trimmed.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (int.TryParse(part, out var index) && index >= 0)
                indices.Add(index);
        }
        return indices;
    }

    protected override async Task<int> ExecuteAsync(CommandContext context, Settings settings, CancellationToken cancellationToken)
    {
        var options = CliConfiguration.Get(context);
        ApplyConfigurationDefaults(settings, options);
        if (!CliConfiguration.TryNormalizeToolsPath(settings.ToolsPath, out var normalizedToolsPath, out var pathError))
        {
            AnsiConsole.MarkupLine($"[red]Error:[/] Invalid --tools-path: {Markup.Escape(pathError)}");
            return 1;
        }

        settings.ToolsPath = normalizedToolsPath;
        options.ToolsBasePath = normalizedToolsPath;
        options.MaxParallelConversions = Math.Max(1, settings.Parallel!.Value);

        // Validate input
        if (settings.Files.Length == 0)
        {
            AnsiConsole.MarkupLine("[red]Error:[/] No input files specified.");
            return 1;
        }

        if (string.IsNullOrEmpty(settings.OutputFormat))
        {
            AnsiConsole.MarkupLine("[red]Error:[/] Output format is required. Use -o or --output.");
            return 1;
        }

        if (!PathSafety.TryNormalizeExtension(settings.OutputFormat, out var normalizedOutputFormat))
        {
            AnsiConsole.MarkupLine(
                $"[red]Error:[/] Invalid output format [yellow]{Esc(settings.OutputFormat)}[/]. " +
                "Use a filename-safe extension such as [cyan]mp4[/], [cyan]png[/], or [cyan]tar.gz[/].");
            return 1;
        }
        settings.OutputFormat = normalizedOutputFormat;

        if (!string.IsNullOrWhiteSpace(settings.ReportPath)
            && !ConversionReportWriter.SupportsPath(settings.ReportPath))
        {
            AnsiConsole.MarkupLine(
                $"[red]Error:[/] Report path [yellow]{Esc(settings.ReportPath)}[/] must end in " +
                "[cyan].json[/] or [cyan].csv[/].");
            return 1;
        }

        if (!TryParsePostConversionAction(settings.SourceAction, out var sourceAction))
        {
            AnsiConsole.MarkupLine(
                $"[red]Error:[/] Invalid source action [yellow]{Esc(settings.SourceAction)}[/]. " +
                "Use [cyan]keep[/], [cyan]move[/], or [cyan]delete[/].");
            return 1;
        }

        if (sourceAction == PostConversionAction.Move && string.IsNullOrWhiteSpace(settings.SourceArchive))
        {
            AnsiConsole.MarkupLine("[red]Error:[/] --source-archive is required when --source-action is move.");
            return 1;
        }

        // Expand glob patterns and find files
        var inputFiles = ExpandFiles(settings.Files);
        if (inputFiles.Count == 0)
        {
            AnsiConsole.MarkupLine("[red]Error:[/] No matching files found.");
            return 1;
        }

        // Create orchestrator
        var orchestrator = new ConversionOrchestrator(Options.Create(options));

        // Validate every distinct extension in the batch — otherwise a mixed
        // selection like "*.png *.jpg -o webp" would silently skip whichever
        // type the orchestrator can't handle while still claiming success.
        var distinctExts = inputFiles
            .Select(f => Path.GetExtension(f).TrimStart('.').ToLowerInvariant())
            .Where(e => !string.IsNullOrEmpty(e))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        var unsupported = distinctExts
            .Where(e => !orchestrator.CanConvert(e, settings.OutputFormat!))
            .ToList();
        if (unsupported.Count > 0)
        {
            AnsiConsole.MarkupLine(
                $"[red]Error:[/] Cannot convert from [yellow]{EscList(unsupported)}[/] to " +
                $"[yellow]{Esc(settings.OutputFormat)}[/]");
            var sampleExt = unsupported[0];
            var availableFormats = orchestrator.GetOutputFormatsFor(sampleExt);
            if (availableFormats.Count > 0)
            {
                AnsiConsole.MarkupLine(
                    $"[dim]Available output formats for {Esc(sampleExt)}:[/] {EscList(availableFormats.Take(20))}");
            }
            return 1;
        }

        // Build conversion options
        var conversionOptions = BuildOptions(settings, options, sourceAction);

        // Create jobs
        var jobs = inputFiles.Select(f => CreateJob(f, settings, conversionOptions)).ToList();

        AnsiConsole.MarkupLine($"[green]Converting[/] {jobs.Count} file(s) to [cyan]{Esc(settings.OutputFormat)}[/]");
        AnsiConsole.WriteLine();

        (int ExitCode, IReadOnlyList<ConversionResult> Results) outcome;
        if (jobs.Count == 1)
        {
            outcome = await ConvertSingleFile(orchestrator, jobs[0], settings, cancellationToken);
        }
        else
        {
            outcome = await ConvertBatch(orchestrator, jobs, settings, cancellationToken);
        }

        if (!string.IsNullOrWhiteSpace(settings.ReportPath))
        {
            try
            {
                var report = ConversionReportWriter.Create(outcome.Results);
                await ConversionReportWriter.WriteAsync(settings.ReportPath, report, cancellationToken);
                AnsiConsole.MarkupLine(
                    $"[green]Report:[/] {Esc(Path.GetFullPath(settings.ReportPath))} " +
                    $"[dim]({outcome.Results.Count} file(s))[/]");
            }
            catch (Exception ex)
            {
                AnsiConsole.MarkupLine($"[red]Report failed:[/] {Esc(ex.Message)}");
                return 1;
            }
        }

        return outcome.ExitCode;
    }

    private async Task<(int ExitCode, IReadOnlyList<ConversionResult> Results)> ConvertSingleFile(
        IConversionOrchestrator orchestrator,
        ConversionJob job,
        Settings settings,
        CancellationToken cancellationToken)
    {
        var success = false;
        ConversionResult? result = null;

        if (settings.NoProgress)
        {
            result = await orchestrator.ConvertAsync(job, cancellationToken: cancellationToken);
            success = result.Success;
        }
        else
        {
            await AnsiConsole.Progress()
                .AutoClear(false)
                .HideCompleted(false)
                .Columns(
                    new TaskDescriptionColumn(),
                    new ProgressBarColumn(),
                    new PercentageColumn(),
                    new RemainingTimeColumn(),
                    new SpinnerColumn())
                .StartAsync(async ctx =>
                {
                    var task = ctx.AddTask(FileTaskDescription(job.InputFileName), maxValue: 100);

                    var progress = new Progress<ConversionProgress>(p =>
                    {
                        if (p.IsIndeterminate)
                        {
                            task.IsIndeterminate = true;
                            task.Description = $"{FileTaskDescription(job.InputFileName)} - {Esc(p.StatusMessage)}";
                        }
                        else
                        {
                            task.IsIndeterminate = false;
                            task.Value = p.Percent;

                            if (p.EstimatedTimeRemaining.HasValue)
                            {
                                task.Description = $"{FileTaskDescription(job.InputFileName)} - ETA: {p.EstimatedTimeRemaining.Value:mm\\:ss}";
                            }
                        }
                    });

                    result = await orchestrator.ConvertAsync(job, progress, cancellationToken);
                    task.Value = 100;
                    success = result.Success;
                });
        }

        AnsiConsole.WriteLine();

        if (success && result != null)
        {
            PrintSuccess(result);
            return (0, [result]);
        }
        else if (result != null)
        {
            PrintError(result);
            return (1, [result]);
        }

        return (1, []);
    }

    private async Task<(int ExitCode, IReadOnlyList<ConversionResult> Results)> ConvertBatch(
        IConversionOrchestrator orchestrator,
        List<ConversionJob> jobs,
        Settings settings,
        CancellationToken cancellationToken)
    {
        var failedCount = 0;
        BatchConversionResult? batchResult = null;

        if (settings.NoProgress)
        {
            batchResult = await orchestrator.ConvertBatchAsync(jobs, settings.Parallel!.Value, cancellationToken: cancellationToken);
            failedCount = batchResult.FailureCount;

            foreach (var result in batchResult.Results)
            {
                if (result.Success)
                {
                    AnsiConsole.MarkupLine($"[green]✓[/] {Esc(result.Job.InputFileName)} → {Esc(result.Job.OutputFileName)}");
                }
                else
                {
                    AnsiConsole.MarkupLine($"[red]✗[/] {Esc(result.Job.InputFileName)}: {Esc(result.ErrorMessage)}");
                }
            }
        }
        else
        {
            await AnsiConsole.Progress()
                .AutoClear(false)
                .HideCompleted(false)
                .Columns(
                    new TaskDescriptionColumn(),
                    new ProgressBarColumn(),
                    new PercentageColumn(),
                    new SpinnerColumn())
                .StartAsync(async ctx =>
                {
                    var overallTask = ctx.AddTask("[bold]Overall Progress[/]", maxValue: jobs.Count);
                    var currentTask = ctx.AddTask("[dim]Waiting...[/]", maxValue: 100);

                    var progress = new Progress<BatchProgress>(p =>
                    {
                        overallTask.Value = p.CompletedJobs;

                        if (p.CurrentJob != null)
                        {
                            currentTask.Description = FileTaskDescription(p.CurrentJob.InputFileName);
                            
                            if (p.CurrentJobProgress != null)
                            {
                                currentTask.Value = p.CurrentJobProgress.IsIndeterminate ? 50 : p.CurrentJobProgress.Percent;
                            }
                        }
                    });

                    batchResult = await orchestrator.ConvertBatchAsync(jobs, settings.Parallel!.Value, progress, cancellationToken);
                    
                    overallTask.Value = jobs.Count;
                    currentTask.Value = 100;
                    currentTask.Description = "[green]Complete[/]";

                    failedCount = batchResult.FailureCount;

                    // Print summary
                    AnsiConsole.WriteLine();
                    foreach (var result in batchResult.Results.Where(r => !r.Success))
                    {
                        AnsiConsole.MarkupLine($"[red]✗[/] {Esc(result.Job.InputFileName)}: {Esc(result.ErrorMessage)}");
                    }
                });
        }

        AnsiConsole.WriteLine();
        
        var successCount = jobs.Count - failedCount;
        if (failedCount == 0)
        {
            AnsiConsole.MarkupLine($"[green]✓ All {successCount} file(s) converted successfully![/]");
            return (0, batchResult?.Results ?? []);
        }
        else
        {
            AnsiConsole.MarkupLine($"[yellow]Completed:[/] {successCount} succeeded, [red]{failedCount} failed[/]");
            return (1, batchResult?.Results ?? []);
        }
    }

    private static void PrintSuccess(ConversionResult result)
    {
        var table = new Table();
        table.Border = TableBorder.Rounded;
        table.AddColumn("Property");
        table.AddColumn("Value");

        table.AddRow("[green]Status[/]", "[green]Success[/]");
        table.AddRow("Output", Esc(result.OutputPath ?? "N/A"));
        table.AddRow("Duration", $"{result.Duration.TotalSeconds:F2}s");
        table.AddRow("Input Size", FormatSize(result.Job.InputFileSize));
        table.AddRow("Output Size", FormatSize(result.OutputSize));

        if (result.SizeReductionPercent.HasValue)
        {
            var reduction = result.SizeReductionPercent.Value;
            var color = reduction > 0 ? "green" : "yellow";
            table.AddRow("Size Change", $"[{color}]{reduction:+0.0;-0.0}%[/]");
        }

        table.AddRow("Converter", Esc(result.ConverterUsed ?? "N/A"));

        AnsiConsole.Write(table);
    }

    private static void PrintError(ConversionResult result)
    {
        AnsiConsole.MarkupLine($"[red]✗ Conversion failed[/]");
        AnsiConsole.MarkupLine($"[red]Error:[/] {Esc(result.ErrorMessage)}");

        if (!string.IsNullOrEmpty(result.StandardError))
        {
            AnsiConsole.WriteLine();
            AnsiConsole.MarkupLine("[dim]Converter output:[/]");
            var lines = result.StandardError.Split('\n').TakeLast(5);
            foreach (var line in lines)
            {
                AnsiConsole.MarkupLine($"[dim]  {Markup.Escape(line.Trim())}[/]");
            }
        }
    }

    internal static void ApplyConfigurationDefaults(Settings settings, ConverterXOptions options)
    {
        if (string.IsNullOrWhiteSpace(settings.Quality))
            settings.Quality = options.DefaultQuality.ToString();
        settings.Parallel ??= options.MaxParallelConversions;
        settings.KeepMetadata ??= options.PreserveMetadataByDefault;
        settings.HardwareAccel ??= options.EnableHardwareAcceleration;
        settings.ToolsPath ??= options.ToolsBasePath;
        settings.OutputDirectory ??= options.DefaultOutputDirectory;
        settings.SourceAction ??= options.PostConversionAction.ToString();
        settings.SourceArchive ??= options.PostConversionArchiveFolder;
    }

    private static ConversionOptions BuildOptions(
        Settings settings,
        ConverterXOptions options,
        PostConversionAction sourceAction)
    {
        var quality = (settings.Quality ?? options.DefaultQuality.ToString()).ToLowerInvariant() switch
        {
            "lowest" => QualityPreset.Lowest,
            "low" => QualityPreset.Low,
            "medium" => QualityPreset.Medium,
            "high" => QualityPreset.High,
            "highest" => QualityPreset.Highest,
            "lossless" => QualityPreset.Lossless,
            _ => QualityPreset.High
        };

        return new ConversionOptions
        {
            Quality = quality,
            OverwriteExisting = settings.Force,
            PreserveMetadata = settings.KeepMetadata ?? options.PreserveMetadataByDefault,
            UseHardwareAcceleration = settings.HardwareAccel ?? options.EnableHardwareAcceleration,
            HardwareAccel = options.DefaultHardwareAcceleration,
            Timeout = options.DefaultTimeout > TimeSpan.Zero ? options.DefaultTimeout : null,
            StreamCopy = settings.StreamCopy,
            AudioTrackSelection = ParseTrackSelection(settings.AudioTracks),
            SubtitleTrackSelection = ParseTrackSelection(settings.SubtitleTracks),
            ForceConverter = settings.Converter,
            OutputDirectory = settings.OutputDirectory,
            PostConversionAction = sourceAction,
            PostConversionArchiveFolder = settings.SourceArchive,
            Video = new VideoOptions
            {
                Width = settings.Width,
                Height = settings.Height,
                Bitrate = settings.Bitrate
            },
            Image = new ImageOptions
            {
                Width = settings.Width,
                Height = settings.Height
            },
            Audio = new AudioOptions
            {
                Bitrate = settings.Bitrate
            }
        };
    }

    private static ConversionJob CreateJob(string inputPath, Settings settings, ConversionOptions options)
    {
        var outputDir = settings.OutputDirectory ?? Path.GetDirectoryName(inputPath) ?? ".";
        var baseName = Path.GetFileNameWithoutExtension(inputPath);
        var outputExt = PathSafety.NormalizeExtensionOrThrow(settings.OutputFormat, nameof(settings.OutputFormat));
        var outputPath = Path.Combine(outputDir, $"{baseName}.{outputExt}");

        return ConversionJob.Create(inputPath, outputPath, options);
    }

    private static bool TryParsePostConversionAction(string? value, out PostConversionAction action)
    {
        action = PostConversionAction.Keep;
        if (string.IsNullOrWhiteSpace(value))
            return true;

        return value.Trim().ToLowerInvariant() switch
        {
            "keep" => Set(PostConversionAction.Keep, out action),
            "move" or "archive" => Set(PostConversionAction.Move, out action),
            "delete" or "remove" => Set(PostConversionAction.Delete, out action),
            _ => false
        };

        static bool Set(PostConversionAction selected, out PostConversionAction target)
        {
            target = selected;
            return true;
        }
    }

    private static List<string> ExpandFiles(string[] patterns)
    {
        // Always emit absolute paths so downstream output-dir computation and
        // de-duplication don't disagree based on whether the pattern was given
        // relative or absolute. On Windows we also normalise case for de-dup
        // since `image.PNG` and `image.png` refer to the same file.
        var seen = new HashSet<string>(OperatingSystem.IsWindows()
            ? StringComparer.OrdinalIgnoreCase
            : StringComparer.Ordinal);
        var files = new List<string>();

        void Add(string path)
        {
            try
            {
                var full = Path.GetFullPath(path);
                if (seen.Add(full)) files.Add(full);
            }
            catch
            {
                // GetFullPath throws on bizarre inputs (very long paths, NUL
                // bytes). Skip silently so a single bad pattern doesn't kill
                // the whole batch.
            }
        }

        foreach (var pattern in patterns)
        {
            if (string.IsNullOrWhiteSpace(pattern)) continue;
            if (pattern.Contains('*') || pattern.Contains('?'))
            {
                var dir = Path.GetDirectoryName(pattern);
                if (string.IsNullOrEmpty(dir)) dir = ".";

                var filePattern = Path.GetFileName(pattern);
                if (string.IsNullOrEmpty(filePattern)) continue;

                if (Directory.Exists(dir))
                {
                    foreach (var f in Directory.EnumerateFiles(dir, filePattern))
                        Add(f);
                }
            }
            else if (File.Exists(pattern))
            {
                Add(pattern);
            }
        }

        return files;
    }

    private static string GetDefaultToolsPath()
    {
        var locations = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "tools"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "UniversalConverterX", "tools"),
        };

        foreach (var loc in locations)
        {
            if (Directory.Exists(loc))
                return loc;
        }

        return locations[0];
    }

    private static string FormatSize(long bytes)
    {
        string[] suffixes = ["B", "KB", "MB", "GB", "TB"];
        int i = 0;
        double size = bytes;

        while (size >= 1024 && i < suffixes.Length - 1)
        {
            size /= 1024;
            i++;
        }

        return $"{size:F2} {suffixes[i]}";
    }

    private static string Esc(string? value) => Markup.Escape(value ?? string.Empty);

    private static string EscList(IEnumerable<string> values) => string.Join(", ", values.Select(Esc));

    private static string FileTaskDescription(string fileName) => $"[cyan]{Esc(fileName)}[/]";
}
