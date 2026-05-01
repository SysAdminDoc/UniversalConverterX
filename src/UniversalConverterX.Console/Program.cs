using Spectre.Console.Cli;
using UniversalConverterX.Console.Commands;

namespace UniversalConverterX.Console;

public class Program
{
    public static int Main(string[] args)
    {
        var app = new CommandApp();

        app.Configure(config =>
        {
            config.SetApplicationName("ucx");
            config.SetApplicationVersion("2.1.0");

            config.AddCommand<ConvertCommand>("convert")
                .WithDescription("Convert one or more files to a different format")
                .WithExample("convert", "video.mp4", "-o", "mp3")
                .WithExample("convert", "*.png", "-o", "webp", "-q", "high")
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
        });

        return app.Run(args);
    }
}
