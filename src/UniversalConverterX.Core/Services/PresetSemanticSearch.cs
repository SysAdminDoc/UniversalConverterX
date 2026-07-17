namespace UniversalConverterX.Core.Services;

/// <summary>
/// A framework-neutral preset document for local semantic ranking.
/// </summary>
public sealed record PresetSearchDocument(
    string Id,
    string Name,
    string? Category,
    string Engine,
    IReadOnlyList<string> InputTypes,
    string OutputExtension);

public sealed record PresetSearchMatch(string Id, double Score);

/// <summary>
/// Dependency-free sparse-vector search for the preset catalogue. Media-domain
/// aliases are expanded before TF-IDF/cosine ranking, allowing natural queries
/// such as "make movie smaller" to find video compression presets without a
/// model download, local server, account, network access, or telemetry.
/// </summary>
public static class PresetSemanticSearch
{
    private const int MaxDocuments = 10_000;
    private const int MaxQueryCharacters = 512;

    private static readonly IReadOnlySet<string> StopWords = new HashSet<string>(
        ["a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "make", "my", "of", "on", "or", "the", "to", "with"],
        StringComparer.Ordinal);

    private static readonly IReadOnlyDictionary<string, IReadOnlySet<string>> Aliases = BuildAliases(
        [
            ["archive", "archival", "lossless", "preserve", "preservation"],
            ["audio", "music", "sound", "soundtrack"],
            ["caption", "captions", "subtitle", "subtitles", "srt", "vtt"],
            ["colorize", "colourise", "color", "colour", "blackwhite", "monochrome"],
            ["compress", "compression", "bitrate", "crf", "encode", "encoding", "optimize", "reduce", "shrink", "small", "smaller"],
            ["convert", "change", "transform", "transcode"],
            ["denoise", "clean", "cleanup", "noise", "restore"],
            ["find", "locate", "search"],
            ["image", "photo", "picture", "still"],
            ["metadata", "label", "labels", "tag", "tags"],
            ["ocr", "recognize", "scan", "text"],
            ["remove", "delete", "erase", "strip"],
            ["speech", "captioning", "dictation", "transcribe", "transcription"],
            ["upscale", "enlarge", "resolution", "superresolution"],
            ["video", "clip", "film", "movie"],
            ["voice", "speak", "speaker", "tts"],
        ]);

    public static IReadOnlyList<PresetSearchMatch> Search(
        string? query,
        IEnumerable<PresetSearchDocument> documents,
        int limit = 100)
    {
        ArgumentNullException.ThrowIfNull(documents);
        if (string.IsNullOrWhiteSpace(query))
            return [];

        var boundedLimit = Math.Clamp(limit, 1, 1_000);
        var items = documents
            .Where(document => !string.IsNullOrWhiteSpace(document.Id))
            .Take(MaxDocuments)
            .ToList();
        if (items.Count == 0)
            return [];

        var queryText = query.Length > MaxQueryCharacters ? query[..MaxQueryCharacters] : query;
        var queryVector = Vectorize([(queryText, 1.0)]);
        if (queryVector.Count == 0)
            return [];
        var queryConcepts = Tokenize(queryText)
            .Select(Concept)
            .DistinctBy(concept => string.Join('\0', concept), StringComparer.Ordinal)
            .ToList();

        var documentVectors = items.Select(Vectorize).ToList();
        var documentFrequency = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var vector in documentVectors)
        {
            foreach (var term in vector.Keys)
                documentFrequency[term] = documentFrequency.GetValueOrDefault(term) + 1;
        }

        var idf = documentFrequency.ToDictionary(
            pair => pair.Key,
            pair => Math.Log((items.Count + 1.0) / (pair.Value + 1.0)) + 1.0,
            StringComparer.Ordinal);
        ApplyIdf(queryVector, idf);
        var queryMagnitude = Magnitude(queryVector);
        if (queryMagnitude == 0)
            return [];

        var normalizedQuery = NormalizePhrase(queryText);
        var matches = new List<(PresetSearchMatch Match, double Coverage)>(items.Count);
        for (var index = 0; index < items.Count; index++)
        {
            var vector = documentVectors[index];
            ApplyIdf(vector, idf);
            var magnitude = Magnitude(vector);
            if (magnitude == 0)
                continue;
            var dot = queryVector.Sum(pair => pair.Value * vector.GetValueOrDefault(pair.Key));
            var score = dot / (queryMagnitude * magnitude);
            if (normalizedQuery.Length > 1 && NormalizePhrase(DocumentText(items[index])).Contains(
                    normalizedQuery, StringComparison.Ordinal))
            {
                score += 0.2;
            }
            if (score > 0)
            {
                var coverage = queryConcepts.Count == 0
                    ? 0
                    : queryConcepts.Count(concept => concept.Any(vector.ContainsKey)) /
                      (double)queryConcepts.Count;
                matches.Add((
                    new PresetSearchMatch(items[index].Id, Math.Round(score, 8)),
                    coverage));
            }
        }

        return matches
            .OrderByDescending(item => item.Coverage)
            .ThenByDescending(item => item.Match.Score)
            .ThenBy(item => item.Match.Id, StringComparer.OrdinalIgnoreCase)
            .Take(boundedLimit)
            .Select(item => item.Match)
            .ToList();
    }

    private static Dictionary<string, double> Vectorize(PresetSearchDocument document) =>
        Vectorize(
        [
            (document.Name, 3.0),
            (document.Category ?? "", 2.0),
            (document.Engine, 1.5),
            (string.Join(' ', document.InputTypes), 0.75),
            (document.OutputExtension, 1.0),
        ]);

    private static Dictionary<string, double> Vectorize(
        IEnumerable<(string Text, double Weight)> fields)
    {
        var vector = new Dictionary<string, double>(StringComparer.Ordinal);
        foreach (var (text, weight) in fields)
        {
            foreach (var token in Tokenize(text))
            {
                vector[token] = vector.GetValueOrDefault(token) + weight;
                if (!Aliases.TryGetValue(token, out var aliases))
                    continue;
                foreach (var alias in aliases)
                    vector[alias] = vector.GetValueOrDefault(alias) + weight * 0.6;
            }
        }
        return vector;
    }

    private static IEnumerable<string> Tokenize(string text)
    {
        var token = new char[Math.Min(text.Length, MaxQueryCharacters)];
        var length = 0;
        foreach (var character in text.Take(MaxQueryCharacters))
        {
            if (char.IsLetterOrDigit(character))
            {
                token[length++] = char.ToLowerInvariant(character);
                continue;
            }
            if (length == 0)
                continue;
            var value = new string(token, 0, length);
            length = 0;
            if (value.Length > 1 && !StopWords.Contains(value))
                yield return value;
        }
        if (length > 0)
        {
            var value = new string(token, 0, length);
            if (value.Length > 1 && !StopWords.Contains(value))
                yield return value;
        }
    }

    private static void ApplyIdf(Dictionary<string, double> vector, IReadOnlyDictionary<string, double> idf)
    {
        foreach (var term in vector.Keys.ToList())
            vector[term] *= idf.GetValueOrDefault(term, 1.0);
    }

    private static double Magnitude(IReadOnlyDictionary<string, double> vector) =>
        Math.Sqrt(vector.Values.Sum(value => value * value));

    private static string DocumentText(PresetSearchDocument document) =>
        $"{document.Name} {document.Category} {document.Engine} {string.Join(' ', document.InputTypes)} {document.OutputExtension}";

    private static string NormalizePhrase(string text) =>
        string.Join(' ', Tokenize(text));

    private static IReadOnlyList<string> Concept(string token) =>
        Aliases.TryGetValue(token, out var aliases)
            ? aliases.Append(token).Order(StringComparer.Ordinal).ToList()
            : [token];

    private static IReadOnlyDictionary<string, IReadOnlySet<string>> BuildAliases(
        IEnumerable<string[]> groups)
    {
        var aliases = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        foreach (var group in groups)
        {
            foreach (var token in group)
            {
                if (!aliases.TryGetValue(token, out var values))
                {
                    values = new HashSet<string>(StringComparer.Ordinal);
                    aliases[token] = values;
                }
                values.UnionWith(group.Where(value => value != token));
            }
        }
        return aliases.ToDictionary(
            pair => pair.Key,
            pair => (IReadOnlySet<string>)pair.Value,
            StringComparer.Ordinal);
    }
}
