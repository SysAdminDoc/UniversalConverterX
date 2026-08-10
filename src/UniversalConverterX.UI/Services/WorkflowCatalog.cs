using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using UniversalConverterX.UI.Views.Pages;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// The discovery taxonomy shared by the shell, Toolbox, Home, preset browser,
/// and Universal Convert. Routes are navigation details; <see cref="WorkflowCatalogItem.Id"/>
/// identifies the workflow even when several workflows intentionally share a
/// route (for example the ClipForge preset family).
/// </summary>
public enum WorkflowCatalogCategory
{
    Navigation,
    Image,
    Video,
    Ai,
    Audio,
    Documents,
    Disc,
    Other,
    Plugin,
    Preset,
}

public enum WorkflowReadiness
{
    Ready,
    Bundled,
    Install,
    Unavailable,
    Planned,
    Future,
}

public enum WorkflowExecutionDisclosure
{
    Local,
    LocalWithOneTimeDownload,
    Network,
    Unknown,
}

public sealed record WorkflowCatalogItem(
    string Id,
    string RouteKey,
    string Title,
    string Description,
    string Glyph,
    WorkflowCatalogCategory Category,
    IReadOnlyList<string> InputCapabilities,
    IReadOnlyList<string> OutputCapabilities,
    WorkflowReadiness Readiness,
    WorkflowExecutionDisclosure ExecutionDisclosure,
    string? PoweredBy,
    string? Engine,
    bool IsAi,
    string? AvailabilityDetail = null,
    UiPreset? Preset = null,
    bool IsFavorite = false,
    bool IsRecent = false)
{
    /// <summary>Localized display title resolved at bind time.</summary>
    public string LocalizedTitle => AppLocalizer.Get(Title);

    /// <summary>Localized description and search metadata resolved at bind time.</summary>
    public string LocalizedDescription => AppLocalizer.Get(Description);

    public string SearchMetadata => string.Join(
        " ",
        LocalizedTitle,
        LocalizedDescription,
        string.Join(" ", InputCapabilities),
        string.Join(" ", OutputCapabilities),
        Engine ?? "",
        Id);

    public bool IsLocalOnly => ExecutionDisclosure == WorkflowExecutionDisclosure.Local;
}

public interface IWorkflowCatalog
{
    IReadOnlyList<WorkflowCatalogItem> GetAll();
    IReadOnlyList<WorkflowCatalogItem> GetNavigation();
    IReadOnlyList<WorkflowCatalogItem> GetToolbox();
    IReadOnlyList<WorkflowCatalogItem> GetPresets();
    IReadOnlyList<WorkflowCatalogItem> Search(string query, int limit = 100);
    void SetFavorite(string workflowId, bool isFavorite);
    void Invalidate();
}

/// <summary>
/// Builds one stable discovery catalog from the navigation definitions, the
/// Toolbox source list, and the shared preset cache. Favorite state is stored
/// in the existing local settings store; recent state is derived from the
/// existing history ring so it survives restart without a second database.
/// </summary>
public sealed class WorkflowCatalog : IWorkflowCatalog
{
    private const string FavoriteIdsKey = "FavoriteWorkflowIds";

    private readonly IUiPresetCache _presetCache;
    private readonly IHistoryService _history;
    private readonly ISettingsService _settings;
    private readonly object _gate = new();
    private IReadOnlyList<WorkflowCatalogItem>? _toolbox;

    public WorkflowCatalog(
        IUiPresetCache presetCache,
        IHistoryService history,
        ISettingsService settings)
    {
        _presetCache = presetCache;
        _history = history;
        _settings = settings;
    }

    public IReadOnlyList<WorkflowCatalogItem> GetAll()
    {
        var byId = new Dictionary<string, WorkflowCatalogItem>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in GetNavigation().Concat(GetToolbox()).Concat(GetPresets()))
            byId.TryAdd(item.Id, item);
        return byId.Values.ToList();
    }

    public IReadOnlyList<WorkflowCatalogItem> GetNavigation() =>
        NavigationDefinitions.Select(definition => ApplyState(new WorkflowCatalogItem(
            WorkflowCatalogIds.ForNavigation(definition.Key),
            definition.RouteKey,
            definition.Title,
            definition.Description,
            definition.Glyph,
            WorkflowCatalogCategory.Navigation,
            [],
            [],
            WorkflowReadiness.Ready,
            WorkflowExecutionDisclosure.Local,
            PoweredBy: null,
            Engine: null,
            IsAi: false))).ToList();

    public IReadOnlyList<WorkflowCatalogItem> GetToolbox()
    {
        IReadOnlyList<WorkflowCatalogItem> baseItems;
        lock (_gate)
        {
            if (_toolbox is null)
            {
                _toolbox = ToolboxPage.CreateCatalogTiles()
                    .Select(tile => FromToolboxTile(tile, tile.Category))
                    .ToList();
            }

            baseItems = _toolbox;
        }

        return baseItems.Select(ApplyState).ToList();
    }

    public IReadOnlyList<WorkflowCatalogItem> GetPresets() =>
        _presetCache.Get().Select(FromPreset).Select(ApplyState).ToList();

    public IReadOnlyList<WorkflowCatalogItem> Search(string query, int limit = 100)
    {
        if (string.IsNullOrWhiteSpace(query))
            return GetAll().Take(Math.Max(1, limit)).ToList();

        var normalized = query.Trim();
        return GetAll()
            .Where(item => item.SearchMetadata.Contains(normalized, StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(item => item.IsFavorite)
            .ThenByDescending(item => item.IsRecent)
            .ThenBy(item => item.LocalizedTitle, StringComparer.CurrentCultureIgnoreCase)
            .Take(Math.Max(1, limit))
            .ToList();
    }

    public void SetFavorite(string workflowId, bool isFavorite)
    {
        if (string.IsNullOrWhiteSpace(workflowId))
            return;

        var ids = _settings.Get<List<string>>(FavoriteIdsKey, []) ?? [];
        ids.RemoveAll(id => string.IsNullOrWhiteSpace(id));
        if (isFavorite)
        {
            if (!ids.Contains(workflowId, StringComparer.OrdinalIgnoreCase))
                ids.Add(workflowId);
        }
        else
        {
            ids.RemoveAll(id => string.Equals(id, workflowId, StringComparison.OrdinalIgnoreCase));
        }

        _settings.Set(FavoriteIdsKey, ids.Distinct(StringComparer.OrdinalIgnoreCase).ToList());
        _settings.Save();
    }

    public void Invalidate()
    {
        lock (_gate)
            _toolbox = null;
        _presetCache.Invalidate();
    }

    private WorkflowCatalogItem ApplyState(WorkflowCatalogItem item)
    {
        var favoriteIds = _settings.Get<List<string>>(FavoriteIdsKey, []) ?? [];
        var isFavorite = favoriteIds.Contains(item.Id, StringComparer.OrdinalIgnoreCase);
        var isRecent = _history.Recent.Any(record =>
            (!string.IsNullOrWhiteSpace(item.Engine)
                && string.Equals(item.Engine, record.Engine, StringComparison.OrdinalIgnoreCase))
            || (!string.IsNullOrWhiteSpace(record.Profile)
                && string.Equals(item.Title, record.Profile, StringComparison.OrdinalIgnoreCase)));
        return item with { IsFavorite = isFavorite, IsRecent = isRecent };
    }

    private static WorkflowCatalogItem FromToolboxTile(
        ToolboxTile tile,
        WorkflowCatalogCategory category)
    {
        var capabilities = WorkflowCapabilities.FromDescription(tile.Description);
        return new WorkflowCatalogItem(
            tile.StableId,
            tile.RouteKey,
            tile.Title,
            tile.Description,
            tile.Glyph,
            category,
            capabilities.Inputs,
            capabilities.Outputs,
            ParseReadiness(tile.StatusBadge),
            InferDisclosure(tile.RouteKey, tile.IsAi, tile.Description),
            tile.PoweredBy,
            EngineForTile(tile.RouteKey, tile.PoweredBy),
            tile.IsAi,
            tile.AvailabilityDetail);
    }

    private static WorkflowCatalogItem FromPreset(UiPreset preset)
    {
        var engine = preset.Engine;
        var disclosure = engine.Equals("streamkeep", StringComparison.OrdinalIgnoreCase)
            || engine.Equals("edge-tts", StringComparison.OrdinalIgnoreCase)
            ? WorkflowExecutionDisclosure.Network
            : IsModelBacked(engine)
                ? WorkflowExecutionDisclosure.LocalWithOneTimeDownload
                : WorkflowExecutionDisclosure.Local;

        return new WorkflowCatalogItem(
            WorkflowCatalogIds.ForPreset(preset.Engine, preset.Name),
            $"presets:{preset.Engine}",
            preset.Name,
            BuildPresetDescription(preset),
            "\uE8B7",
            WorkflowCatalogCategory.Preset,
            preset.InputTypes,
            string.IsNullOrWhiteSpace(preset.OutputExtension) ? [] : [preset.OutputExtension],
            WorkflowReadiness.Ready,
            disclosure,
            preset.Engine,
            preset.Engine,
            IsModelBacked(engine),
            Preset: preset);
    }

    private static string BuildPresetDescription(UiPreset preset)
    {
        var inputs = preset.InputTypes.Count == 0
            ? "any input"
            : string.Join(", ", preset.InputTypes);
        var output = string.IsNullOrWhiteSpace(preset.OutputExtension)
            ? "workflow output"
            : $".{preset.OutputExtension}";
        return $"{preset.Engine}: {inputs} -> {output}";
    }

    private static string? EngineForTile(string routeKey, string? poweredBy)
    {
        if (routeKey.StartsWith("presets:", StringComparison.OrdinalIgnoreCase))
            return routeKey["presets:".Length..];
        return string.IsNullOrWhiteSpace(poweredBy) ? null : poweredBy;
    }

    private static WorkflowReadiness ParseReadiness(string status) => status switch
    {
        "Bundled" => WorkflowReadiness.Bundled,
        "Install" => WorkflowReadiness.Install,
        "Unavailable" => WorkflowReadiness.Unavailable,
        "Planned" => WorkflowReadiness.Planned,
        "Future" => WorkflowReadiness.Future,
        _ => WorkflowReadiness.Ready,
    };

    private static WorkflowExecutionDisclosure InferDisclosure(
        string routeKey,
        bool isAi,
        string description)
    {
        if (routeKey.Equals("downloader", StringComparison.OrdinalIgnoreCase)
            || routeKey.Contains("streamkeep", StringComparison.OrdinalIgnoreCase))
            return WorkflowExecutionDisclosure.Network;

        if (isAi
            || description.Contains("model", StringComparison.OrdinalIgnoreCase)
            || description.Contains("download", StringComparison.OrdinalIgnoreCase))
            return WorkflowExecutionDisclosure.LocalWithOneTimeDownload;

        return WorkflowExecutionDisclosure.Local;
    }

    private static bool IsModelBacked(string engine) =>
        engine.Contains("whisper", StringComparison.OrdinalIgnoreCase)
        || engine.Contains("parakeet", StringComparison.OrdinalIgnoreCase)
        || engine.Contains("demucs", StringComparison.OrdinalIgnoreCase)
        || engine.Contains("realesrgan", StringComparison.OrdinalIgnoreCase)
        || engine.Contains("gfpgan", StringComparison.OrdinalIgnoreCase)
        || engine.Contains("alphacut", StringComparison.OrdinalIgnoreCase)
        || engine.Contains("bgremove", StringComparison.OrdinalIgnoreCase)
        || engine.Contains("ocr", StringComparison.OrdinalIgnoreCase);

    private static readonly WorkflowNavigationDefinition[] NavigationDefinitions =
    [
        new("home", "home", "Home", "Start a workflow or search tools", "\uE80F"),
        new("converter", "converter", "Converter", "Batch convert video, audio, image, document, and archive formats", "\uE895"),
        new("compressor", "compressor", "Compressor", "Shrink videos for web, email, archive, and social delivery", "\uE91F"),
        new("downloader", "downloader", "Downloader", "Download video or audio from supported URLs", "\uE896"),
        new("recorder", "recorder", "Recorder", "Screen recording plus planned webcam and audio capture", "\uE7C8"),
        new("editor", "editor", "Editor", "Trim, crop, rotate, upscale, filter, and export clips", "\uE71D"),
        new("lossless-cut", "lossless-cut", "Lossless Cut", "Keyframe-accurate stream-copy trimming with no re-encode", "\uE8AC"),
        new("ai-lab", "ai-lab", "AI Lab", "Local AI tool status and model-backed workflows", "\uE91B"),
        new("toolbox", "toolbox", "Toolbox", "Specialized media utilities and availability", "\uE713"),
        new("universal-convert", "universal-convert", "Universal Convert", "Drop any file to see every compatible preset", "\uED0C"),
        new("presets", "presets", "Presets", "Browse and run shipped or custom conversion presets", "\uE71D"),
        new("history", "history", "History", "Persistent log of every conversion and compression job", "\uE81C"),
        new("job-center", "job-center", "Job Center", "Queued, running, interrupted, and retryable jobs", "\uE8A5"),
        new("settings", "settings", "Settings", "Preferences, tool paths, shell integration, and performance", "\uE713"),
    ];

    private sealed record WorkflowNavigationDefinition(
        string Key,
        string RouteKey,
        string Title,
        string Description,
        string Glyph);
}

public static class WorkflowCatalogIds
{
    public static string ForNavigation(string semanticKey) =>
        $"navigation-{Slug(semanticKey)}";

    public static string ForPreset(string engine, string name) =>
        $"preset-{Slug(engine)}-{Slug(name)}";

    public static string ForTool(string title, string description)
    {
        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(description));
        return $"tool-{Slug(title)}-{Convert.ToHexString(digest.AsSpan(0, 5)).ToLowerInvariant()}";
    }

    private static string Slug(string value)
    {
        var builder = new StringBuilder();
        var separatorPending = false;
        foreach (var character in value.Trim().ToLowerInvariant())
        {
            if (char.IsLetterOrDigit(character))
            {
                if (separatorPending && builder.Length > 0)
                    builder.Append('-');
                builder.Append(character);
                separatorPending = false;
            }
            else
            {
                separatorPending = true;
            }
        }

        return builder.Length == 0 ? "workflow" : builder.ToString().Trim('-');
    }
}

public static class WorkflowCapabilities
{
    private static readonly Regex Arrow = new(
        @"(?:<->|->|=>|\bto\b)",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    public static (IReadOnlyList<string> Inputs, IReadOnlyList<string> Outputs)
        FromDescription(string description)
    {
        var match = Arrow.Match(description);
        if (!match.Success)
            return ([], []);

        return (Split(description[..match.Index]), Split(description[(match.Index + match.Length)..]));
    }

    private static IReadOnlyList<string> Split(string value) => value
        .Split([',', '/', '|', '·', ';', ':', '(', ')'], StringSplitOptions.RemoveEmptyEntries)
        .Select(token => token.Trim().Trim('.', '\'', '"'))
        .Where(token => token.Length is >= 1 and <= 48)
        .Where(token => token.Any(char.IsLetterOrDigit))
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .Take(24)
        .ToList();
}
