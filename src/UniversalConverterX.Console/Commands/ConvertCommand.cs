using System.ComponentModel;
using Microsoft.Extensions.Options;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;

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
        [DefaultValue("high")]
        public string Quality { get; set; } = "high";

        [CommandOption("-f|--force")]
        [Description("Overwrite existing files")]
        [DefaultValue(false)]
        public bool Force { get; set; }

        [CommandOption("-p|--parallel <COUNT>")]
        [Description("Maximum parallel conversions")]
        [DefaultValue(4)]
        public int Parallel { get; set; } = 4;

        [CommandOption("--no-progress")]
        [Description("Disable progress display")]
        [DefaultValue(false)]
        public bool NoProgress { get; set; }

        [CommandOption("--converter <ID>")]
        [Description("Force a specific converter (e.g., ffmpeg, imagemagick)")]
        public string? Converter { get; set; }

        [CommandOption("--keep-metadata")]
        [Description("Preserve metadata from source file")]
        [DefaultValue(true)]
        public bool KeepMetadata { get; set; } = true;

        [CommandOption("--hw-accel")]
        [Description("Enable hardware acceleration")]
        [DefaultValue(true)]
        public bool HardwareAccel { get; set; } = true;

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
    }

    public override async Task<int> ExecuteAsync(CommandContext context, Settings settings)
    {
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

        // Expand glob patterns and find files
        var inputFiles = ExpandFiles(settings.Files);
        if (inputFiles.Count == 0)
        {
            AnsiConsole.MarkupLine("[red]Error:[/] No matching files found.");
            return 1;
        }

        // Create orchestrator
        var toolsPath = settings.ToolsPath ?? GetDefaultToolsPath();
        var options = Options.Create(new ConverterXOptions { ToolsBasePath = toolsPath });
        var orchestrator = new ConversionOrchestrator(options);

        // Check if conversion is supported
        var sampleExt = Path.GetExtension(inputFiles[0]).TrimStart('.').ToLowerInvariant();
        if (!orchestrator.CanConvert(sampleExt, settings.OutputFormat))
        {
            AnsiConsole.MarkupLine($"[red]Error:[/] Cannot convert from [yellow]{sampleExt}[/] to [yellow]{settings.OutputFormat}[/]");
            
            var availableFormats = orchestrator.GetOutputFormatsFor(inputFiles[0]);
            if (availableFormats.Count > 0)
            {
                AnsiConsole.MarkupLine($"[dim]Available output formats for {sampleExt}:[/] {string.Join(", ", availableFormats.Take(20))}");
            }
            return 1;
        }

        // Build conversion options
        var conversionOptions = BuildOptions(settings);

        // Create jobs
        var jobs = inputFiles.Select(f => CreateJob(f, settings, conversionOptions)).ToList();

        AnsiConsole.MarkupLine($"[green]Converting[/] {jobs.Count} file(s) to [cyan]{settings.OutputFormat}[/]");
        AnsiConsole.WriteLine();

        // Single file conversion
        if (jobs.Count == 1)
        {
            return await ConvertSingleFile(orchestrator, jobs[0], settings);
        }

        // Batch conversion
        return await ConvertBatch(orchestrator, jobs, settings);
    }

    private async Task<int> ConvertSingleFile(IConversionOrchestrator orchestrator, ConversionJob job, Settings settings)
    {
        var success = false;
        ConversionResult? result = null;

        if (settings.NoProgress)
        {
            result = await orchestrator.ConvertAsync(job);
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
                    var task = ctx.AddTask($"[cyan]{job.InputFileName}[/]", maxValue: 100);

                    var progress = new Progress<ConversionProgress>(p =>
                    {
                        if (p.IsIndeterminate)
                        {
                            task.IsIndeterminate = true;
                            task.Description = $"[cyan]{job.InputFileName}[/] - {p.StatusMessage}";
                        }
                        else
                        {
                            task.IsIndeterminate = false;
                            task.Value = p.Percent;

                            if (p.EstimatedTimeRemaining.HasValue)
                            {
                                task.Description = $"[cyan]{job.InputFileName}[/] - ETA: {p.EstimatedTimeRemaining.Value:mm\\:ss}";
                            }
                        }
                    });

                    result = await orchestrator.ConvertAsync(job, progress);
                    task.Value = 100;
                    success = result.Success;
                });
        }

        AnsiConsole.WriteLine();

        if (success && result != null)
        {
            PrintSuccess(result);
            return 0;
        }
        else if (result != null)
        {
            PrintError(result);
            return 1;
        }

        return 1;
    }

    private async Task<int> ConvertBatch(IConversionOrchestrator orchestrator, List<ConversionJob> jobs, Settings settings)
    {
        var failedCount = 0;

        if (settings.NoProgress)
        {
            var batchResult = await orchestrator.ConvertBatchAsync(jobs, settings.Parallel);
            failedCount = batchResult.FailureCount;

            foreach (var result in batchResult.Results)
            {
                if (result.Success)
                {
                    AnsiConsole.MarkupLine($"[green]✓[/] {result.Job.InputFileName} → {result.Job.OutputFileName}");
                }
                else
                {
                    AnsiConsole.MarkupLine($"[red]✗[/] {result.Job.InputFileName}: {result.ErrorMessage}");
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
                            currentTask.Description = $"[cyan]{p.CurrentJob.InputFileName}[/]";
                            
                            if (p.CurrentJobProgress != null)
                            {
                                currentTask.Value = p.CurrentJobProgress.IsIndeterminate ? 50 : p.CurrentJobProgress.Percent;
                            }
                        }
                    });

                    var batchResult = await orchestrator.ConvertBatchAsync(jobs, settings.Parallel, progress);
                    
                    overallTask.Value = jobs.Count;
                    currentTask.Value = 100;
                    currentTask.Description = "[green]Complete[/]";

                    failedCount = batchResult.FailureCount;

                    // Print summary
                    AnsiConsole.WriteLine();
                    foreach (var result in batchResult.Results.Where(r => !r.Success))
                    {
                        AnsiConsole.MarkupLine($"[red]✗[/] {result.Job.InputFileName}: {result.ErrorMessage}");
                    }
                });
        }

        AnsiConsole.WriteLine();
        
        var successCount = jobs.Count - failedCount;
        if (failedCount == 0)
        {
            AnsiConsole.MarkupLine($"[green]✓ All {successCount} file(s) converted successfully![/]");
            return 0;
        }
        else
        {
            AnsiConsole.MarkupLine($"[yellow]Completed:[/] {successCount} succeeded, [red]{failedCount} failed[/]");
            return 1;
        }
    }

    private static void PrintSuccess(ConversionResult result)
    {
        var table = new Table();
        table.Border = TableBorder.Rounded;
        table.AddColumn("Property");
        table.AddColumn("Value");

        table.AddRow("[green]Status[/]", "[green]Success[/]");
        table.AddRow("Output", result.OutputPath ?? "N/A");
        table.AddRow("Duration", $"{result.Duration.TotalSeconds:F2}s");
        table.AddRow("Input Size", FormatSize(result.Job.InputFileSize));
        table.AddRow("Output Size", FormatSize(result.OutputSize));

        if (result.SizeReductionPercent.HasValue)
        {
            var reduction = result.SizeReductionPercent.Value;
            var color = reduction > 0 ? "green" : "yellow";
            table.AddRow("Size Change", $"[{color}]{reduction:+0.0;-0.0}%[/]");
        }

        table.AddRow("Converter", result.ConverterUsed ?? "N/A");

        AnsiConsole.Write(table);
    }

    private static void PrintError(ConversionResult result)
    {
        AnsiConsole.MarkupLine($"[red]✗ Conversion failed[/]");
        AnsiConsole.MarkupLine($"[red]Error:[/] {result.ErrorMessage}");

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

    private static ConversionOptions BuildOptions(Settings settings)
    {
        var quality = settings.Quality.ToLowerInvariant() switch
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
            PreserveMetadata = settings.KeepMetadata,
            UseHardwareAcceleration = settings.HardwareAccel,
            ForceConverter = settings.Converter,
            OutputDirectory = settings.OutputDirectory,
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
        var outputExt = settings.OutputFormat!.TrimStart('.');
        var outputPath = Path.Combine(outputDir, $"{baseName}.{outputExt}");

        return ConversionJob.Create(inputPath, outputPath, options);
    }

    private static List<string> ExpandFiles(string[] patterns)
    {
        var files = new List<string>();

        foreach (var pattern in patterns)
        {
            if (pattern.Contains('*') || pattern.Contains('?'))
            {
                var dir = Path.GetDirectoryName(pattern);
                if (string.IsNullOrEmpty(dir)) dir = ".";
                
                var filePattern = Path.GetFileName(pattern);
                
                if (Directory.Exists(dir))
                {
                    files.AddRange(Directory.GetFiles(dir, filePattern));
                }
            }
            else if (File.Exists(pattern))
            {
                files.Add(Path.GetFullPath(pattern));
            }
        }

        return files.Distinct().ToList();
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
}
