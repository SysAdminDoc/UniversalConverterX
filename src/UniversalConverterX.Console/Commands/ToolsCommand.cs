using System.ComponentModel;
using System.Diagnostics;
using Spectre.Console;
using Spectre.Console.Cli;

namespace UniversalConverterX.Console.Commands;

public class ToolsCommand : AsyncCommand<ToolsCommand.Settings>
{
    public class Settings : CommandSettings
    {
        [CommandArgument(0, "<ACTION>")]
        [Description("Action: list, check, download, path")]
        public string Action { get; set; } = "list";

        [CommandArgument(1, "[TOOL]")]
        [Description("Tool name (for download)")]
        public string? ToolName { get; set; }

        [CommandOption("--tools-path <PATH>")]
        [Description("Path to converter tools")]
        public string? ToolsPath { get; set; }
    }

    private static readonly Dictionary<string, ToolDefinition> KnownTools = new()
    {
        ["ffmpeg"] = new("ffmpeg", "FFmpeg", "https://ffmpeg.org/", "Video and audio processing"),
        ["imagemagick"] = new("magick", "ImageMagick", "https://imagemagick.org/", "Image processing"),
        ["pandoc"] = new("pandoc", "Pandoc", "https://pandoc.org/", "Document conversion"),
        ["calibre"] = new("ebook-convert", "Calibre", "https://calibre-ebook.com/", "Ebook conversion"),
        ["libreoffice"] = new("soffice", "LibreOffice", "https://www.libreoffice.org/", "Office document conversion"),
        ["inkscape"] = new("inkscape", "Inkscape", "https://inkscape.org/", "Vector graphics"),
        ["ghostscript"] = new("gs", "Ghostscript", "https://www.ghostscript.com/", "PDF processing"),
    };

    public override async Task<int> ExecuteAsync(CommandContext context, Settings settings)
    {
        return settings.Action.ToLowerInvariant() switch
        {
            "list" => ListTools(settings),
            "check" => await CheckTools(settings),
            "download" => await DownloadTool(settings),
            "path" => ShowToolsPath(settings),
            _ => InvalidAction(settings.Action)
        };
    }

    private int ListTools(Settings settings)
    {
        var toolsPath = settings.ToolsPath ?? GetDefaultToolsPath();

        AnsiConsole.MarkupLine("[green]Converter Tools:[/]");
        AnsiConsole.WriteLine();

        var table = new Table();
        table.Border = TableBorder.Rounded;
        table.AddColumn("Tool");
        table.AddColumn("Executable");
        table.AddColumn("Description");
        table.AddColumn("Website");

        foreach (var (id, tool) in KnownTools)
        {
            table.AddRow(
                $"[cyan]{tool.Name}[/]",
                tool.Executable,
                tool.Description,
                $"[link={tool.Website}]{tool.Website}[/]");
        }

        AnsiConsole.Write(table);

        AnsiConsole.WriteLine();
        AnsiConsole.MarkupLine("[dim]Use 'ucx tools check' to verify which tools are available[/]");

        return 0;
    }

    private async Task<int> CheckTools(Settings settings)
    {
        var toolsPath = settings.ToolsPath ?? GetDefaultToolsPath();

        AnsiConsole.MarkupLine("[green]Checking tool availability...[/]");
        AnsiConsole.WriteLine();

        var table = new Table();
        table.Border = TableBorder.Rounded;
        table.AddColumn("Tool");
        table.AddColumn("Status");
        table.AddColumn("Version");
        table.AddColumn("Path");

        foreach (var (id, tool) in KnownTools)
        {
            var (found, version, path) = await FindTool(tool.Executable, toolsPath);

            var status = found ? "[green]✓ Found[/]" : "[red]✗ Not Found[/]";
            var versionStr = version ?? "[dim]N/A[/]";
            var pathStr = found ? $"[dim]{TruncatePath(path!, 40)}[/]" : "[dim]N/A[/]";

            table.AddRow(tool.Name, status, versionStr, pathStr);
        }

        AnsiConsole.Write(table);

        AnsiConsole.WriteLine();
        AnsiConsole.MarkupLine($"[dim]Tools path: {toolsPath}[/]");

        return 0;
    }

    private async Task<int> DownloadTool(Settings settings)
    {
        if (string.IsNullOrEmpty(settings.ToolName))
        {
            AnsiConsole.MarkupLine("[red]Error:[/] Tool name is required for download");
            AnsiConsole.MarkupLine("[dim]Available tools: " + string.Join(", ", KnownTools.Keys) + "[/]");
            return 1;
        }

        var toolId = settings.ToolName.ToLowerInvariant();
        if (!KnownTools.TryGetValue(toolId, out var tool))
        {
            AnsiConsole.MarkupLine($"[red]Error:[/] Unknown tool: {settings.ToolName}");
            AnsiConsole.MarkupLine("[dim]Available tools: " + string.Join(", ", KnownTools.Keys) + "[/]");
            return 1;
        }

        AnsiConsole.MarkupLine($"[yellow]Automatic download is not yet implemented.[/]");
        AnsiConsole.WriteLine();
        AnsiConsole.MarkupLine($"Please download [cyan]{tool.Name}[/] manually from:");
        AnsiConsole.MarkupLine($"  [link={tool.Website}]{tool.Website}[/]");
        AnsiConsole.WriteLine();

        // Provide platform-specific instructions
        if (OperatingSystem.IsWindows())
        {
            AnsiConsole.MarkupLine("[green]Windows installation options:[/]");
            AnsiConsole.MarkupLine($"  • winget install {GetWingetId(toolId)}");
            AnsiConsole.MarkupLine($"  • choco install {toolId}");
            AnsiConsole.MarkupLine($"  • scoop install {toolId}");
        }
        else if (OperatingSystem.IsMacOS())
        {
            AnsiConsole.MarkupLine("[green]macOS installation:[/]");
            AnsiConsole.MarkupLine($"  brew install {GetBrewId(toolId)}");
        }
        else
        {
            AnsiConsole.MarkupLine("[green]Linux installation:[/]");
            AnsiConsole.MarkupLine($"  sudo apt install {GetAptId(toolId)}");
            AnsiConsole.MarkupLine("  or use your distribution's package manager");
        }

        return 0;
    }

    private int ShowToolsPath(Settings settings)
    {
        var toolsPath = settings.ToolsPath ?? GetDefaultToolsPath();
        
        AnsiConsole.MarkupLine($"[green]Tools path:[/] {toolsPath}");
        
        if (Directory.Exists(toolsPath))
        {
            AnsiConsole.MarkupLine("[dim]Directory exists[/]");
            
            var binPath = Path.Combine(toolsPath, "bin");
            if (Directory.Exists(binPath))
            {
                var files = Directory.GetFiles(binPath);
                if (files.Length > 0)
                {
                    AnsiConsole.MarkupLine($"[dim]Found {files.Length} file(s) in bin directory[/]");
                }
            }
        }
        else
        {
            AnsiConsole.MarkupLine("[yellow]Directory does not exist[/]");
        }

        return 0;
    }

    private static int InvalidAction(string action)
    {
        AnsiConsole.MarkupLine($"[red]Unknown action:[/] {action}");
        AnsiConsole.MarkupLine("[dim]Valid actions: list, check, download, path[/]");
        return 1;
    }

    private static async Task<(bool Found, string? Version, string? Path)> FindTool(string executable, string toolsPath)
    {
        var exeName = OperatingSystem.IsWindows() ? $"{executable}.exe" : executable;

        // Check tools directory first
        var toolPath = Path.Combine(toolsPath, "bin", exeName);
        if (File.Exists(toolPath))
        {
            var version = await GetToolVersion(toolPath, executable);
            return (true, version, toolPath);
        }

        // Check PATH
        var pathDirs = Environment.GetEnvironmentVariable("PATH")?.Split(Path.PathSeparator) ?? [];
        foreach (var dir in pathDirs)
        {
            var fullPath = Path.Combine(dir, exeName);
            if (File.Exists(fullPath))
            {
                var version = await GetToolVersion(fullPath, executable);
                return (true, version, fullPath);
            }
        }

        // Check common installation paths
        var commonPaths = GetCommonPaths(executable);
        foreach (var path in commonPaths)
        {
            if (File.Exists(path))
            {
                var version = await GetToolVersion(path, executable);
                return (true, version, path);
            }
        }

        return (false, null, null);
    }

    private static async Task<string?> GetToolVersion(string path, string toolName)
    {
        try
        {
            var versionArg = toolName switch
            {
                "ffmpeg" => "-version",
                "magick" => "--version",
                "pandoc" => "--version",
                "ebook-convert" => "--version",
                "soffice" => "--version",
                "inkscape" => "--version",
                "gs" => "--version",
                _ => "--version"
            };

            using var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = path,
                    Arguments = versionArg,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    CreateNoWindow = true
                }
            };

            process.Start();
            var output = await process.StandardOutput.ReadToEndAsync();
            await process.WaitForExitAsync();

            // Extract version from first line
            var firstLine = output.Split('\n').FirstOrDefault()?.Trim();
            if (!string.IsNullOrEmpty(firstLine))
            {
                // Try to extract just the version number
                var parts = firstLine.Split(' ');
                foreach (var part in parts)
                {
                    if (part.Any(char.IsDigit) && part.Contains('.'))
                    {
                        return part.Trim(',', ')', '(');
                    }
                }
                return firstLine.Length > 30 ? firstLine[..30] + "..." : firstLine;
            }
        }
        catch
        {
            // Ignore errors
        }

        return null;
    }

    private static string[] GetCommonPaths(string executable)
    {
        if (OperatingSystem.IsWindows())
        {
            var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);

            return executable switch
            {
                "ffmpeg" => [$@"{programFiles}\FFmpeg\bin\ffmpeg.exe", $@"{programFilesX86}\FFmpeg\bin\ffmpeg.exe"],
                "magick" => [$@"{programFiles}\ImageMagick-7.1.1-Q16-HDRI\magick.exe"],
                "soffice" => [$@"{programFiles}\LibreOffice\program\soffice.exe"],
                "ebook-convert" => [$@"{programFiles}\Calibre2\ebook-convert.exe"],
                "inkscape" => [$@"{programFiles}\Inkscape\bin\inkscape.exe"],
                "gs" => [$@"{programFiles}\gs\gs10.02.1\bin\gswin64c.exe"],
                _ => []
            };
        }
        else if (OperatingSystem.IsMacOS())
        {
            return executable switch
            {
                "soffice" => ["/Applications/LibreOffice.app/Contents/MacOS/soffice"],
                "ebook-convert" => ["/Applications/calibre.app/Contents/MacOS/ebook-convert"],
                "inkscape" => ["/Applications/Inkscape.app/Contents/MacOS/inkscape"],
                _ => [$"/usr/local/bin/{executable}", $"/opt/homebrew/bin/{executable}"]
            };
        }

        return [$"/usr/bin/{executable}", $"/usr/local/bin/{executable}"];
    }

    private static string GetWingetId(string toolId) => toolId switch
    {
        "ffmpeg" => "Gyan.FFmpeg",
        "imagemagick" => "ImageMagick.ImageMagick",
        "pandoc" => "JohnMacFarlane.Pandoc",
        "calibre" => "calibre.calibre",
        "libreoffice" => "TheDocumentFoundation.LibreOffice",
        "inkscape" => "Inkscape.Inkscape",
        "ghostscript" => "ArtifexSoftware.GhostScript",
        _ => toolId
    };

    private static string GetBrewId(string toolId) => toolId switch
    {
        "imagemagick" => "imagemagick",
        "libreoffice" => "libreoffice",
        _ => toolId
    };

    private static string GetAptId(string toolId) => toolId switch
    {
        "imagemagick" => "imagemagick",
        "libreoffice" => "libreoffice",
        "ghostscript" => "ghostscript",
        _ => toolId
    };

    private static string TruncatePath(string path, int maxLength)
    {
        if (path.Length <= maxLength) return path;
        return "..." + path[^(maxLength - 3)..];
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

    private record ToolDefinition(string Executable, string Name, string Website, string Description);
}
