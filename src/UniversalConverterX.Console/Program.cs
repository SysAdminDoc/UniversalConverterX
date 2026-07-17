using System.Reflection;
using Spectre.Console.Cli;
using UniversalConverterX.Console.Commands;

namespace UniversalConverterX.Console;

public class Program
{
    /// <summary>
    /// Read the version from the assembly's InformationalVersion (or AssemblyVersion
    /// as a fallback) so a single Directory.Build.props bump propagates here without
    /// a literal-string update. Strips the "+commitsha" suffix that the SDK appends.
    /// </summary>
    internal static string GetAssemblyVersion()
    {
        var asm = typeof(Program).Assembly;
        var info = asm.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;
        if (!string.IsNullOrWhiteSpace(info))
        {
            var plus = info!.IndexOf('+');
            return plus < 0 ? info : info[..plus];
        }
        return asm.GetName().Version?.ToString(3) ?? "0.0.0";
    }

    public static int Main(string[] args)
    {
        var app = new CommandApp();

        app.Configure(config =>
        {
            config.SetApplicationName("ucx");
            config.SetApplicationVersion(GetAssemblyVersion());

            config.AddCommand<ConvertCommand>("convert")
                .WithDescription("Convert one or more files to a different format")
                .WithExample("convert", "video.mp4", "-o", "mp3")
                .WithExample("convert", "*.png", "-o", "webp", "-q", "high")
                .WithExample("convert", "*.mov", "-o", "mp4", "--report", "batch.json")
                .WithExample("convert", "document.docx", "-o", "pdf");

            config.AddCommand<ListCommand>("list")
                .WithDescription("List supported formats and converters")
                .WithExample("list", "formats")
                .WithExample("list", "converters")
                .WithExample("list", "formats", "--input", "mp4");

            config.AddCommand<InfoCommand>("info")
                .WithDescription("Show information about a file")
                .WithExample("info", "video.mp4");

            config.AddCommand<ConfigCommand>("config")
                .WithDescription("View or modify configuration")
                .WithExample("config", "show")
                .WithExample("config", "set", "tools-path", "C:\\Tools");

            config.AddCommand<ToolsCommand>("tools")
                .WithDescription("Manage converter tools")
                .WithExample("tools", "list")
                .WithExample("tools", "check")
                .WithExample("tools", "download", "ffmpeg");

            config.AddCommand<ServeCommand>("serve")
                .WithDescription("Bind a localhost HTTP API for headless integration")
                .WithExample("serve")
                .WithExample("serve", "--port", "17654");

            config.AddCommand<ConvertPresetCommand>("convert-preset")
                .WithDescription("Run a named conversion preset (used by the right-click shell extension)")
                .WithExample("convert-preset", "--list")
                .WithExample("convert-preset", "--preset", "To MP4 (H.264 1080p)", "video.mov")
                .WithExample("convert-preset", "--preset", "To PNG", "--input-files", "files.txt");

            config.AddCommand<EnginesCommand>("engines")
                .WithDescription("List the shared UI, CLI, REST, and PowerShell engine catalogue")
                .WithExample("engines", "--json")
                .WithExample("engines", "--available");

            config.AddCommand<InvokeEngineCommand>("invoke-engine")
                .WithDescription("Invoke any installed sidecar with a JSON argument array")
                .WithExample("invoke-engine", "scenedetect", "--args-json", "[\"presets\"]");
        });

        return app.Run(args);
    }
}
