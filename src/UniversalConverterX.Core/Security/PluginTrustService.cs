using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Security;

public enum PluginTrustState
{
    Untrusted,
    Trusted,
    Changed,
    Invalid,
}

public sealed record PluginDescriptor(
    string Id,
    string Name,
    string Version,
    string Description,
    string Engine,
    string DirectoryPath,
    string ManifestPath,
    string? ExecutablePath,
    IReadOnlyList<string> PresetPaths,
    string? Sha256,
    PluginTrustState TrustState,
    string StatusDetail,
    bool IsAi)
{
    public bool IsTrusted => TrustState == PluginTrustState.Trusted;
    public bool CanTrust => TrustState is PluginTrustState.Untrusted or PluginTrustState.Changed;
}

public sealed record PluginTrustOperationResult(bool Success, string Message, PluginDescriptor? Plugin = null);

public interface IPluginTrustService
{
    string PluginDirectory { get; }
    IReadOnlyList<PluginDescriptor> Discover();
    PluginTrustOperationResult Trust(string pluginId);
    PluginTrustOperationResult Revoke(string pluginId);
    bool TryGetTrustedPlugin(string engine, out PluginDescriptor? plugin);
}

public sealed class PluginTrustService : IPluginTrustService
{
    private const int CurrentSchemaVersion = 1;
    private const int MaxPluginFiles = 2_048;
    private const long MaxPluginBytes = 2L * 1024 * 1024 * 1024;
    private static readonly HashSet<string> ManifestProperties = new(StringComparer.Ordinal)
    {
        "schemaVersion", "id", "name", "version", "description", "engine", "executable",
        "presets", "isAi", "models", "gpu", "tools", "engineVersion",
        "minHostVersion", "maxHostVersion", "capabilities", "architectures",
        "migration",
    };
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        ReadCommentHandling = JsonCommentHandling.Disallow,
        AllowTrailingCommas = false,
        WriteIndented = true,
    };

    private readonly object _gate = new();
    private readonly string _trustStorePath;

    public PluginTrustService()
        : this(
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "UniversalConverterX",
                "plugins"),
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "UniversalConverterX",
                "plugin-trust.json"))
    {
    }

    public PluginTrustService(string pluginDirectory, string trustStorePath)
    {
        PluginDirectory = Path.GetFullPath(pluginDirectory);
        _trustStorePath = Path.GetFullPath(trustStorePath);
    }

    public string PluginDirectory { get; }

    public IReadOnlyList<PluginDescriptor> Discover()
    {
        lock (_gate)
        {
            var trustedHashes = LoadTrustStore();
            if (!Directory.Exists(PluginDirectory))
                return [];

            try
            {
                return Directory.EnumerateDirectories(PluginDirectory, "*", SearchOption.TopDirectoryOnly)
                    .OrderBy(path => Path.GetFileName(path), StringComparer.OrdinalIgnoreCase)
                    .Select(path => InspectPlugin(path, trustedHashes))
                    .ToList();
            }
            catch (Exception exception)
            {
                return
                [
                    InvalidDescriptor(
                        "plugins-directory",
                        PluginDirectory,
                        $"Plugin discovery failed: {exception.Message}")
                ];
            }
        }
    }

    public PluginTrustOperationResult Trust(string pluginId)
    {
        lock (_gate)
        {
            var trustedHashes = LoadTrustStore();
            var plugin = FindPlugin(pluginId, trustedHashes);
            if (plugin is null)
                return new PluginTrustOperationResult(false, $"Plugin '{pluginId}' was not found.");
            if (!plugin.CanTrust || string.IsNullOrWhiteSpace(plugin.Sha256))
                return new PluginTrustOperationResult(false, plugin.StatusDetail, plugin);

            trustedHashes[plugin.Id] = plugin.Sha256;
            if (!SaveTrustStore(trustedHashes, out var error))
                return new PluginTrustOperationResult(false, error, plugin);

            var trusted = plugin with
            {
                TrustState = PluginTrustState.Trusted,
                StatusDetail = "Trusted SHA-256 matches every file in the plugin directory.",
            };
            return new PluginTrustOperationResult(true, $"Trusted {trusted.Name}.", trusted);
        }
    }

    public PluginTrustOperationResult Revoke(string pluginId)
    {
        lock (_gate)
        {
            var trustedHashes = LoadTrustStore();
            var plugin = FindPlugin(pluginId, trustedHashes);
            if (!trustedHashes.Remove(pluginId))
            {
                var canonicalId = plugin?.Id;
                if (canonicalId is null || !trustedHashes.Remove(canonicalId))
                    return new PluginTrustOperationResult(false, $"Plugin '{pluginId}' is not trusted.", plugin);
            }

            if (!SaveTrustStore(trustedHashes, out var error))
                return new PluginTrustOperationResult(false, error, plugin);

            return new PluginTrustOperationResult(
                true,
                $"Revoked trust for {plugin?.Name ?? pluginId}.",
                plugin is null
                    ? null
                    : plugin with
                    {
                        TrustState = PluginTrustState.Untrusted,
                        StatusDetail = "Plugin is present but has not been explicitly trusted.",
                    });
        }
    }

    public bool TryGetTrustedPlugin(string engine, out PluginDescriptor? plugin)
    {
        plugin = null;
        if (!IsSafeId(engine))
            return false;

        lock (_gate)
        {
            var trustedHashes = LoadTrustStore();
            var candidate = FindPlugin(engine, trustedHashes);
            if (candidate is not { IsTrusted: true })
                return false;

            plugin = candidate;
            return true;
        }
    }

    private PluginDescriptor? FindPlugin(
        string pluginId,
        IReadOnlyDictionary<string, string> trustedHashes)
    {
        if (!IsSafeId(pluginId) || !Directory.Exists(PluginDirectory))
            return null;

        string? directory = null;
        try
        {
            directory = Directory.EnumerateDirectories(PluginDirectory, "*", SearchOption.TopDirectoryOnly)
                .FirstOrDefault(path =>
                    Path.GetFileName(path).Equals(pluginId, StringComparison.OrdinalIgnoreCase));
        }
        catch
        {
            return null;
        }

        return directory is null ? null : InspectPlugin(directory, trustedHashes);
    }

    private PluginDescriptor InspectPlugin(
        string directory,
        IReadOnlyDictionary<string, string> trustedHashes)
    {
        var directoryName = Path.GetFileName(directory);
        try
        {
            if (IsReparsePoint(directory))
                return InvalidDescriptor(directoryName, directory, "Plugin directories cannot be links or reparse points.");

            var manifestPath = Path.Combine(directory, "manifest.json");
            if (!File.Exists(manifestPath))
                return InvalidDescriptor(directoryName, directory, "Missing manifest.json.");
            if (IsReparsePoint(manifestPath))
                return InvalidDescriptor(directoryName, directory, "manifest.json cannot be a link or reparse point.");

            using var document = JsonDocument.Parse(File.ReadAllText(manifestPath), new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 32,
            });
            if (document.RootElement.ValueKind != JsonValueKind.Object)
                return InvalidDescriptor(directoryName, directory, "manifest.json must contain one JSON object.");

            var unknown = document.RootElement.EnumerateObject()
                .Select(property => property.Name)
                .Where(name => !ManifestProperties.Contains(name))
                .ToList();
            if (unknown.Count > 0)
            {
                return InvalidDescriptor(
                    directoryName,
                    directory,
                    "Unknown manifest field(s): " + string.Join(", ", unknown));
            }

            var manifest = document.RootElement.Deserialize<PluginManifest>(JsonOptions);
            var compatibility = ExtensionManifestCompatibility.ValidateJson(
                document.RootElement,
                manifest?.Engine ?? directoryName,
                "plugin",
                manifestPath: manifestPath);
            if (!compatibility.IsCompatible)
                return InvalidDescriptor(directoryName, directory, compatibility.Reason!);

            var validationError = ValidateManifest(directoryName, manifest);
            if (validationError is not null)
                return InvalidDescriptor(directoryName, directory, validationError);

            var files = ScanPluginFiles(directory);
            var executablePath = ResolveContainedFile(directory, manifest!.Executable!);
            if (executablePath is null || !Path.GetExtension(executablePath).Equals(".exe", StringComparison.OrdinalIgnoreCase))
                return InvalidDescriptor(manifest.Id!, directory, "The declared executable must be a regular .exe inside the plugin directory.");

            var presetPaths = new List<string>();
            foreach (var preset in manifest.Presets!)
            {
                var presetPath = ResolveContainedFile(directory, preset);
                if (presetPath is null || !presetPath.EndsWith(".preset.xml", StringComparison.OrdinalIgnoreCase))
                {
                    return InvalidDescriptor(
                        manifest.Id!,
                        directory,
                        $"Preset '{preset}' must resolve to a regular .preset.xml file inside the plugin directory.");
                }

                var presetDocument = PresetDocument.Load(presetPath);
                if (!presetDocument.Succeeded || presetDocument.Preset is null)
                {
                    return InvalidDescriptor(
                        manifest.Id!,
                        directory,
                        $"Preset '{preset}' is invalid: {string.Join("; ", presetDocument.Errors)}");
                }
                if (!presetDocument.Preset.Engine.Equals(manifest.Engine, StringComparison.OrdinalIgnoreCase))
                {
                    return InvalidDescriptor(
                        manifest.Id!,
                        directory,
                        $"Preset '{preset}' targets engine '{presetDocument.Preset.Engine}' instead of plugin engine '{manifest.Engine}'.");
                }
                presetPaths.Add(presetPath);
            }

            var digest = ComputeDirectoryHash(directory, files);
            var state = trustedHashes.TryGetValue(manifest.Id!, out var trustedHash)
                ? CryptographicOperations.FixedTimeEquals(
                    Convert.FromHexString(trustedHash),
                    Convert.FromHexString(digest))
                    ? PluginTrustState.Trusted
                    : PluginTrustState.Changed
                : PluginTrustState.Untrusted;
            var detail = state switch
            {
                PluginTrustState.Trusted => "Trusted SHA-256 matches every file in the plugin directory.",
                PluginTrustState.Changed => "Plugin files changed after approval and have been re-quarantined.",
                _ => "Plugin is present but has not been explicitly trusted.",
            };

            return new PluginDescriptor(
                manifest.Id!,
                manifest.Name!,
                manifest.Version!,
                manifest.Description ?? "Third-party local sidecar",
                manifest.Engine!,
                Path.GetFullPath(directory),
                manifestPath,
                executablePath,
                presetPaths,
                digest,
                state,
                detail,
                manifest.IsAi);
        }
        catch (Exception exception)
        {
            return InvalidDescriptor(directoryName, directory, exception.Message);
        }
    }

    private static string? ValidateManifest(string directoryName, PluginManifest? manifest)
    {
        if (manifest is null)
            return "manifest.json could not be parsed.";
        if (!IsSafeId(manifest.Id))
            return "Plugin id must contain only ASCII letters, digits, '.', '_' or '-' and be at most 64 characters.";
        if (!directoryName.Equals(manifest.Id, StringComparison.OrdinalIgnoreCase))
            return "Plugin id must match its directory name.";
        if (!string.Equals(manifest.Engine, manifest.Id, StringComparison.OrdinalIgnoreCase))
            return "Plugin engine must match its id.";
        if (string.IsNullOrWhiteSpace(manifest.Name) || manifest.Name.Length > 100)
            return "Plugin name is required and must be at most 100 characters.";
        if (string.IsNullOrWhiteSpace(manifest.Version) || manifest.Version.Length > 40)
            return "Plugin version is required and must be at most 40 characters.";
        if (!IsSimpleRelativeFile(manifest.Executable))
            return "Plugin executable must be a simple file name without directory components.";
        if (manifest.Presets is not { Count: > 0 and <= 64 })
            return "Plugin manifest must declare between 1 and 64 preset files.";
        if (manifest.Presets.Any(path => !IsSafeRelativePath(path)))
            return "Plugin preset paths must stay inside the plugin directory.";
        if (manifest.Gpu is not null && manifest.Gpu is not ("vulkan" or "cuda-optional" or "cuda-required"))
            return "Plugin gpu must be vulkan, cuda-optional, cuda-required, or omitted.";
        if (manifest.Tools is not null && manifest.Tools.Any(tool =>
                !IsSafeId(tool.Id)
                || !IsSimpleRelativeFile(tool.Executable)
                || string.IsNullOrWhiteSpace(tool.Display)
                || tool.Display.Length > 100))
        {
            return "Plugin tool requirements must use safe ids, simple executable names, and display names.";
        }
        return null;
    }

    private static IReadOnlyList<string> ScanPluginFiles(string root)
    {
        var files = new List<string>();
        var directories = new Stack<string>();
        directories.Push(Path.GetFullPath(root));
        long totalBytes = 0;

        while (directories.Count > 0)
        {
            var current = directories.Pop();
            foreach (var childDirectory in Directory.EnumerateDirectories(current))
            {
                if (IsReparsePoint(childDirectory))
                    throw new InvalidDataException("Plugin subdirectories cannot be links or reparse points.");
                directories.Push(childDirectory);
            }

            foreach (var file in Directory.EnumerateFiles(current))
            {
                if (IsReparsePoint(file))
                    throw new InvalidDataException("Plugin files cannot be links or reparse points.");
                files.Add(file);
                if (files.Count > MaxPluginFiles)
                    throw new InvalidDataException($"Plugin contains more than {MaxPluginFiles} files.");
                totalBytes = checked(totalBytes + new FileInfo(file).Length);
                if (totalBytes > MaxPluginBytes)
                    throw new InvalidDataException("Plugin is larger than the 2 GiB trust-scan limit.");
            }
        }

        return files;
    }

    private static string ComputeDirectoryHash(string root, IReadOnlyList<string> files)
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var buffer = new byte[128 * 1024];
        Span<byte> length = stackalloc byte[sizeof(long)];
        foreach (var file in files.OrderBy(
                     path => Path.GetRelativePath(root, path),
                     StringComparer.OrdinalIgnoreCase))
        {
            var relative = Path.GetRelativePath(root, file).Replace('\\', '/');
            hash.AppendData(Encoding.UTF8.GetBytes(relative));
            hash.AppendData([0]);

            using var stream = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.Read);
            BinaryPrimitives.WriteInt64LittleEndian(length, stream.Length);
            hash.AppendData(length);
            int read;
            while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
                hash.AppendData(buffer.AsSpan(0, read));
        }

        return Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
    }

    private Dictionary<string, string> LoadTrustStore()
    {
        try
        {
            if (!File.Exists(_trustStorePath) || IsReparsePoint(_trustStorePath))
                return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var store = JsonSerializer.Deserialize<PluginTrustStore>(
                File.ReadAllText(_trustStorePath),
                JsonOptions);
            if (store?.SchemaVersion != CurrentSchemaVersion || store.Plugins is null)
                return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

            return store.Plugins
                .Where(pair => IsSafeId(pair.Key) && IsSha256(pair.Value))
                .ToDictionary(pair => pair.Key, pair => pair.Value.ToLowerInvariant(), StringComparer.OrdinalIgnoreCase);
        }
        catch
        {
            return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        }
    }

    private bool SaveTrustStore(IReadOnlyDictionary<string, string> hashes, out string error)
    {
        try
        {
            if (File.Exists(_trustStorePath) && IsReparsePoint(_trustStorePath))
                throw new IOException("The plugin trust store cannot be a link or reparse point.");

            var parent = Path.GetDirectoryName(_trustStorePath)
                ?? throw new IOException("Plugin trust store has no parent directory.");
            Directory.CreateDirectory(parent);
            var temporary = _trustStorePath + ".tmp-" + Guid.NewGuid().ToString("N");
            var store = new PluginTrustStore
            {
                Plugins = hashes.ToDictionary(
                    pair => pair.Key,
                    pair => pair.Value.ToLowerInvariant(),
                    StringComparer.OrdinalIgnoreCase),
            };
            File.WriteAllText(temporary, JsonSerializer.Serialize(store, JsonOptions), new UTF8Encoding(false));
            File.Move(temporary, _trustStorePath, true);
            error = "";
            return true;
        }
        catch (Exception exception)
        {
            error = "Could not update plugin trust: " + exception.Message;
            return false;
        }
    }

    private static string? ResolveContainedFile(string root, string relativePath)
    {
        if (!IsSafeRelativePath(relativePath))
            return null;
        var fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var candidate = Path.GetFullPath(Path.Combine(root, relativePath));
        if (!candidate.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase)
            || !File.Exists(candidate)
            || IsReparsePoint(candidate))
        {
            return null;
        }
        return candidate;
    }

    private static bool IsSafeRelativePath(string? path)
    {
        if (string.IsNullOrWhiteSpace(path) || Path.IsPathRooted(path))
            return false;
        var parts = path.Split(['/', '\\'], StringSplitOptions.RemoveEmptyEntries);
        return parts.Length > 0 && parts.All(part => part is not "." and not "..");
    }

    private static bool IsSimpleRelativeFile(string? path) =>
        IsSafeRelativePath(path)
        && Path.GetFileName(path) == path
        && path!.IndexOfAny(['/', '\\', ':', '\0']) < 0;

    private static bool IsSafeId(string? id) =>
        !string.IsNullOrWhiteSpace(id)
        && id.Length <= 64
        && char.IsAsciiLetterOrDigit(id[0])
        && id.All(character => char.IsAsciiLetterOrDigit(character) || character is '.' or '_' or '-');

    private static bool IsSha256(string? value) =>
        value?.Length == 64 && value.All(Uri.IsHexDigit);

    private static bool IsReparsePoint(string path) =>
        (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;

    private static PluginDescriptor InvalidDescriptor(string id, string directory, string detail) =>
        new(
            id,
            id,
            "",
            "Invalid third-party plugin",
            id,
            Path.GetFullPath(directory),
            Path.Combine(Path.GetFullPath(directory), "manifest.json"),
            null,
            [],
            null,
            PluginTrustState.Invalid,
            detail,
            false);

    private sealed class PluginManifest
    {
        [JsonPropertyName("schemaVersion")]
        public int SchemaVersion { get; init; }

        [JsonPropertyName("id")]
        public string? Id { get; init; }

        [JsonPropertyName("name")]
        public string? Name { get; init; }

        [JsonPropertyName("version")]
        public string? Version { get; init; }

        [JsonPropertyName("description")]
        public string? Description { get; init; }

        [JsonPropertyName("engine")]
        public string? Engine { get; init; }

        [JsonPropertyName("executable")]
        public string? Executable { get; init; }

        [JsonPropertyName("presets")]
        public List<string>? Presets { get; init; }

        [JsonPropertyName("isAi")]
        public bool IsAi { get; init; }

        [JsonPropertyName("models")]
        public bool? Models { get; init; }

        [JsonPropertyName("gpu")]
        public string? Gpu { get; init; }

        [JsonPropertyName("tools")]
        public List<PluginManifestTool>? Tools { get; init; }
    }

    private sealed class PluginManifestTool
    {
        [JsonPropertyName("id")]
        public string? Id { get; init; }

        [JsonPropertyName("executable")]
        public string? Executable { get; init; }

        [JsonPropertyName("display")]
        public string? Display { get; init; }

        [JsonPropertyName("managed")]
        public bool Managed { get; init; }

        [JsonPropertyName("required")]
        public bool Required { get; init; } = true;

        [JsonPropertyName("whenArgContains")]
        public string? WhenArgContains { get; init; }

        [JsonPropertyName("whenArgContainsAny")]
        public List<string>? WhenArgContainsAny { get; init; }
    }

    private sealed class PluginTrustStore
    {
        [JsonPropertyName("schemaVersion")]
        public int SchemaVersion { get; init; } = CurrentSchemaVersion;

        [JsonPropertyName("plugins")]
        public Dictionary<string, string> Plugins { get; init; } = new(StringComparer.OrdinalIgnoreCase);
    }
}
