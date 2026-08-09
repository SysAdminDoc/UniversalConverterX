using UniversalConverterX.UI.Views.Pages;

namespace UniversalConverterX.UI.Views;

/// <summary>
/// The single source of truth mapping a navigation route key to the page that
/// serves it. MainWindow resolves user navigation through this table, and the
/// runtime UI smoke harness enumerates it so a newly added page cannot ship
/// without being exercised.
/// </summary>
public static class NavigationRoutes
{
    /// <summary>Route used when a key has no registered page.</summary>
    public const string FallbackRouteKey = "placeholder";

    private static readonly Dictionary<string, Type> RouteTable =
        new(StringComparer.OrdinalIgnoreCase)
        {
            ["home"] = typeof(HomePage),
            ["converter"] = typeof(ConverterPage),
            ["ai-lab"] = typeof(AiLabPage),
            ["compressor"] = typeof(CompressorPage),
            ["audio-converter"] = typeof(AudioConverterPage),
            ["audio-compressor"] = typeof(AudioCompressorPage),
            ["editor"] = typeof(EditorPage),
            ["lossless-cut"] = typeof(LosslessCutPage),
            ["dvd-rip"] = typeof(DvdRipPage),
            ["disc-burn"] = typeof(DiscBurnPage),
            ["downloader"] = typeof(DownloaderPage),
            ["recorder"] = typeof(RecorderPage),
            ["toolbox"] = typeof(ToolboxPage),
            ["format-inspector"] = typeof(FormatInspectorPage),
            ["frame-snapshot"] = typeof(FrameSnapshotPage),
            ["ai-bgremove"] = typeof(BackgroundRemoverPage),
            ["ai-video-enhancer"] = typeof(VideoEnhancerPage),
            ["ai-image-enhancer"] = typeof(ImageEnhancerPage),
            ["ai-watermark"] = typeof(WatermarkRemoverPage),
            ["ai-subtitle"] = typeof(AiSubtitlePage),
            ["ai-summarizer"] = typeof(VideoSummarizerPage),
            ["ai-noise"] = typeof(NoiseRemoverPage),
            ["ai-vocal"] = typeof(VocalRemoverPage),
            ["ai-voice-changer"] = typeof(VoiceChangerPage),
            ["ai-tts"] = typeof(TextToSpeechPage),
            ["ai-stt"] = typeof(SpeechToTextPage),
            ["ai-photo-restore"] = typeof(PhotoRestorationPage),
            ["ai-colorize"] = typeof(ColorizeVideoPage),
            // ROADMAP Item 27 — AI Portrait wires to PresetsPage with the
            // facerestore engine filter (CodeFormer fidelity slider + GFPGAN
            // side-by-side). The fidelity-vs-restoration nuance lives in the
            // preset args; the page UX is the existing PresetsPage.
            ["ai-portrait"] = typeof(PresetsPage),
            ["lip-reading"] = typeof(LipReadingPage),
            ["gif-maker"] = typeof(GifMakerPage),
            ["slideshow-maker"] = typeof(SlideshowPage),
            ["image-converter"] = typeof(ImageConverterPage),
            ["auto-reframe"] = typeof(AutoReframePage),
            ["chapter-marks"] = typeof(ChapterMarksPage),
            ["watch-folders"] = typeof(WatchFoldersPage),
            ["history"] = typeof(HistoryPage),
            ["job-center"] = typeof(JobCenterPage),
            ["vmaf"] = typeof(VmafAnalysisPage),
            ["scene-detect"] = typeof(SceneDetectPage),
            ["auto-highlight"] = typeof(AutoHighlightPage),
            ["timeline-preview"] = typeof(TimelinePreviewPage),
            ["track-manager"] = typeof(TrackManagerPage),
            ["document-converter"] = typeof(DocumentConverterPage),
            ["archive"] = typeof(ArchivePage),
            ["pdf-tools"] = typeof(PdfToolsPage),
            ["subtitle-converter"] = typeof(SubtitleConverterPage),
            ["font-converter"] = typeof(FontConverterPage),
            ["ebook-converter"] = typeof(EbookConverterPage),
            ["ocr"] = typeof(OcrPage),
            ["presets"] = typeof(PresetsPage),
            ["preset-editor"] = typeof(PresetEditorPage),
            ["universal-convert"] = typeof(UniversalConvertPage),
            ["batch-rename"] = typeof(BatchRenamePage),
            [FallbackRouteKey] = typeof(PlaceholderPage),
        };

    /// <summary>Every registered route key, in stable alphabetical order.</summary>
    public static IReadOnlyList<string> RouteKeys { get; } =
        RouteTable.Keys.OrderBy(key => key, StringComparer.Ordinal).ToArray();

    /// <summary>Route key to page type. Unknown keys resolve to the placeholder.</summary>
    public static IReadOnlyDictionary<string, Type> All => RouteTable;

    /// <summary>
    /// Splits a route key of the form <c>presets:engine</c> into its page type
    /// and navigation parameter. Unknown keys fall back to the placeholder page
    /// rather than throwing, matching the shell's historical behavior.
    /// </summary>
    public static (Type PageType, object? Parameter) Resolve(
        string routeKey,
        object? parameter = null)
    {
        ArgumentNullException.ThrowIfNull(routeKey);

        string? routeParameter = null;
        var separator = routeKey.IndexOf(':');
        if (separator > 0)
        {
            routeParameter = routeKey[(separator + 1)..];
            routeKey = routeKey[..separator];
        }

        var pageType = RouteTable.TryGetValue(routeKey, out var resolved)
            ? resolved
            : typeof(PlaceholderPage);

        parameter ??= routeParameter;
        if (pageType == typeof(PresetsPage)
            && parameter is null
            && routeKey.Equals("ai-portrait", StringComparison.OrdinalIgnoreCase))
        {
            parameter = "facerestore";
        }

        return (pageType, parameter);
    }
}
