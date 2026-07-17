using System.ComponentModel;
using System.Text.Json;
using Spectre.Console;
using Spectre.Console.Cli;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Console.Commands;

public sealed class CommunityPresetsCommand : Command<CommunityPresetsCommand.Settings>
{
    public sealed class Settings : CommandSettings
    {
        [CommandArgument(0, "<ACTION>")]
        [Description("Action: list, preview, install")]
        public string Action { get; set; } = "list";

        [CommandArgument(1, "[ID]")]
        [Description("Catalog preset id (for preview/install)")]
        public string? Id { get; set; }

        [CommandOption("--catalog <PATH>")]
        [Description("Local catalog.json path; no network URLs are accepted")]
        public string? CatalogPath { get; set; }

        [CommandOption("--destination <PATH>")]
        [Description("Installed preset directory")]
        public string? Destination { get; set; }

        [CommandOption("--accept-sha256 <DIGEST>")]
        [Description("Exact digest shown by preview; required for install")]
        public string? AcceptedSha256 { get; set; }

        [CommandOption("--json")]
        [Description("Emit machine-readable JSON")]
        public bool Json { get; set; }
    }

    protected override int Execute(CommandContext context, Settings settings, CancellationToken cancellationToken)
    {
        var catalogPath = ResolveCatalogPath(settings.CatalogPath);
        if (catalogPath is null)
        {
            AnsiConsole.MarkupLine("[red]Community catalog not found.[/] Pass --catalog with a local catalog.json path.");
            return 1;
        }

        var service = new CommunityPresetCatalogService();
        return settings.Action.ToLowerInvariant() switch
        {
            "list" => List(service, catalogPath, settings.Json),
            "preview" => Preview(service, catalogPath, settings.Id, settings.Json),
            "install" => Install(service, catalogPath, settings, settings.Json),
            _ => InvalidAction(settings.Action),
        };
    }

    private static int List(CommunityPresetCatalogService service, string catalogPath, bool json)
    {
        var loaded = service.Load(catalogPath);
        if (json)
        {
            WriteJson(loaded);
            return loaded.Succeeded ? 0 : 1;
        }
        if (!loaded.Succeeded || loaded.Catalog is null)
            return WriteErrors(loaded.Errors);

        AnsiConsole.MarkupLine($"[green]{Markup.Escape(loaded.Catalog.CatalogId)}[/] v{Markup.Escape(loaded.Catalog.CatalogVersion)}");
        var table = new Table().Border(TableBorder.Rounded)
            .AddColumn("Id").AddColumn("Version").AddColumn("Author").AddColumn("License").AddColumn("SHA-256");
        foreach (var entry in loaded.Catalog.Entries)
            table.AddRow(Markup.Escape(entry.Id), Markup.Escape(entry.Version),
                Markup.Escape(entry.Author), Markup.Escape(entry.License), entry.Sha256[..16] + "…");
        AnsiConsole.Write(table);
        AnsiConsole.MarkupLine("[dim]Use preview to inspect the exact engine and arguments before install.[/]");
        return 0;
    }

    private static int Preview(
        CommunityPresetCatalogService service,
        string catalogPath,
        string? id,
        bool json)
    {
        if (string.IsNullOrWhiteSpace(id))
            return MissingId("preview");
        var preview = service.Preview(catalogPath, id);
        if (json)
        {
            WriteJson(preview);
            return preview.Valid ? 0 : 1;
        }
        WritePreview(preview);
        return preview.Valid ? 0 : 1;
    }

    private static int Install(
        CommunityPresetCatalogService service,
        string catalogPath,
        Settings settings,
        bool json)
    {
        if (string.IsNullOrWhiteSpace(settings.Id))
            return MissingId("install");
        if (string.IsNullOrWhiteSpace(settings.AcceptedSha256))
        {
            var preview = service.Preview(catalogPath, settings.Id);
            if (json)
                WriteJson(preview);
            else
            {
                WritePreview(preview);
                if (preview.Valid)
                    AnsiConsole.MarkupLine("[yellow]Review the values above, then rerun install with --accept-sha256 and the exact digest.[/]");
            }
            return 2;
        }

        var destination = settings.Destination ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalConverterX", "presets");
        var result = service.Install(
            catalogPath, settings.Id, destination, settings.AcceptedSha256);
        if (json)
            WriteJson(result);
        else if (result.Succeeded)
            AnsiConsole.MarkupLine(result.AlreadyInstalled
                ? $"[green]Already installed:[/] {Markup.Escape(result.InstalledPath!)}"
                : $"[green]Installed atomically:[/] {Markup.Escape(result.InstalledPath!)}");
        else
            WriteErrors(result.Errors);
        return result.Succeeded ? 0 : 1;
    }

    private static void WritePreview(CommunityPresetPreview preview)
    {
        if (!preview.Valid)
        {
            WriteErrors(preview.Errors);
            return;
        }
        AnsiConsole.MarkupLine($"[green]{Markup.Escape(preview.Name)}[/] ({Markup.Escape(preview.Id)} v{Markup.Escape(preview.Version)})");
        AnsiConsole.MarkupLine($"Author/license: {Markup.Escape(preview.Author)} / {Markup.Escape(preview.License)}");
        AnsiConsole.MarkupLine($"Engine: [cyan]{Markup.Escape(preview.Engine!)}[/]");
        AnsiConsole.MarkupLine("Arguments:");
        foreach (var argument in preview.Arguments)
            AnsiConsole.WriteLine("  " + argument);
        AnsiConsole.MarkupLine($"SHA-256: [yellow]{preview.ActualSha256}[/]");
    }

    private static int WriteErrors(IReadOnlyList<string> errors)
    {
        foreach (var error in errors)
            AnsiConsole.MarkupLine($"[red]Error:[/] {Markup.Escape(error)}");
        return 1;
    }

    private static int MissingId(string action)
    {
        AnsiConsole.MarkupLine($"[red]Error:[/] Preset id is required for {action}.");
        return 1;
    }

    private static int InvalidAction(string action)
    {
        AnsiConsole.MarkupLine($"[red]Unknown action:[/] {Markup.Escape(action)}");
        AnsiConsole.MarkupLine("[dim]Valid actions: list, preview, install[/]");
        return 1;
    }

    private static void WriteJson<T>(T value) =>
        AnsiConsole.WriteLine(JsonSerializer.Serialize(value, new JsonSerializerOptions { WriteIndented = true }));

    private static string? ResolveCatalogPath(string? requested)
    {
        if (!string.IsNullOrWhiteSpace(requested))
        {
            if (Uri.TryCreate(requested, UriKind.Absolute, out var uri) && !uri.IsFile)
                return null;
            return File.Exists(requested) ? Path.GetFullPath(requested) : null;
        }

        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, "community-presets", "catalog.json");
            if (File.Exists(candidate))
                return candidate;
            directory = directory.Parent;
        }
        return null;
    }
}
