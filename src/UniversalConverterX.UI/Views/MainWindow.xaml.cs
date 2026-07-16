using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Animation;
using UniversalConverterX.UI.Views.Pages;

namespace UniversalConverterX.UI.Views;

public sealed partial class MainWindow : Window
{
    private bool _isSelectingNavigationItem;

    private readonly List<NavSearchSuggestion> _searchSuggestions =
    [
        new("Home", "Start a workflow or search tools", "home"),
        new("Converter", "Batch convert video, audio, image, document, and archive formats", "converter"),
        new("AI Lab", "AI tool status and planned workflows", "ai-lab"),
        new("Compressor", "Shrink videos for web, email, archive, and social delivery", "compressor"),
        new("Editor", "Trim, crop, rotate, upscale, filter, and export clips", "editor"),
        new("Lossless Cut", "Keyframe-accurate stream-copy trimming with a visual timeline — no re-encode", "lossless-cut"),
        new("DVD Rip", "Rip titles from an unprotected VIDEO_TS folder to MP4 or MKV", "dvd-rip"),
        new("Downloader", "Download video or audio from supported URLs", "downloader"),
        new("Recorder", "Screen recording plus planned webcam and audio capture", "recorder"),
        new("Toolbox", "Specialized media utilities and availability", "toolbox"),
        new("Format Inspector", "Probe codecs, streams, metadata, and conversion targets", "format-inspector"),
        new("Frame Snapshot", "Export still frames and image-sequence samples from video", "frame-snapshot"),
        new("GIF Maker", "Convert video clips to high-quality animated GIFs", "gif-maker"),
        new("Slideshow Maker", "Turn image folders into videos with motion, transitions, text, and music", "slideshow-maker"),
        new("Image Converter", "Convert HEIC, AVIF, JPEG, PNG, WebP, TIFF, BMP", "image-converter"),
        new("Auto Reframe", "Convert horizontal video to 9:16 / 1:1 / 4:5 with optional face tracking", "auto-reframe"),
        new("Image Upscaler", "Real-ESRGAN super-resolution up to 4× for photos / illustrations", "ai-image-enhancer"),
        new("Video Upscaler", "Real-ESRGAN frame-by-frame video super-resolution", "ai-video-enhancer"),
        new("Video Denoise", "Real-ESRGAN frame-by-frame cleanup presets", "presets:realesrgan"),
        new("Anime Video Sharpen", "Anime-focused Real-ESRGAN video presets", "presets:anime-upscale"),
        new("Video Face Enhance", "CodeFormer frame-by-frame face enhancement presets", "presets:video-face-enhance"),
        new("Auto Crop", "ClipForge cropdetect presets for video crop cleanup", "presets:clipforge"),
        new("Intro & Outro", "ClipForge presets for branded intro and outro assembly", "presets:clipforge"),
        new("Lens Correction", "ClipForge lens correction and stabilization presets", "presets:clipforge"),
        new("VR Converter", "ClipForge 360 / VR projection conversion presets", "presets:clipforge"),
        new("Metadata Editor", "ExifTool metadata read, write, and clear presets", "presets:exiftool-meta"),
        new("Subtitle Remover", "VideoSubtitleRemover preset workflow", "presets:videosubtitleremover"),
        new("Photo Restoration", "GFPGAN blind face restoration for old / degraded portraits", "ai-photo-restore"),
        new("Colorize", "Add colour to black-and-white photos and video offline on the CPU", "ai-colorize"),
        new("AI Portrait", "CodeFormer / GFPGAN portrait upscale + restoration with fidelity slider", "ai-portrait"),
        new("Chapter Marks", "Read, edit, and rewrite MKV / MP4 / MOV chapter markers", "chapter-marks"),
        new("Watch Folders", "Auto-process new files dropped into a watched folder", "watch-folders"),
        new("History", "Persistent log of every conversion / compression job (search + re-run)", "history"),
        new("VMAF Quality", "Score a compressed clip against its reference (libvmaf)", "vmaf"),
        new("Scene Detection", "Find scene cuts in a video and export to CSV / EDL", "scene-detect"),
        new("Auto Highlight", "Rank scene-change and motion peaks, then export a reel / EDL / OTIO", "auto-highlight"),
        new("Timeline Preview", "Render a thumbnail strip + audio waveform for any video", "timeline-preview"),
        new("Track Manager", "Add or remove audio / subtitle / data tracks (no re-encode)", "track-manager"),
        new("Document Converter", "Convert DOCX / PDF / ODT / XLSX / PPTX / EPUB / HTML and friends", "document-converter"),
        new("Archive Tool", "Pack / unpack 7z / ZIP / TAR / RAR (read) / ISO via 7-Zip", "archive"),
        new("PDF Tools", "Merge / split / rotate / extract / encrypt / compress PDFs (pikepdf)", "pdf-tools"),
        new("Subtitle Converter", "Convert SRT / VTT / ASS / SSA / SUB plus shift / retime", "subtitle-converter"),
        new("Font Converter", "Convert TTF / OTF / WOFF / WOFF2 (fonttools)", "font-converter"),
        new("eBook Converter", "Convert EPUB / MOBI / AZW3 / PDF / FB2 / DOCX (Calibre)", "ebook-converter"),
        new("OCR", "Extract text from images and scans -> TXT / hOCR / PDF (Tesseract)", "ocr"),
        new("Presets", "Browse and run any of the shipped or user-defined conversion presets", "presets"),
        new("3D Models", "Convert STL / OBJ / PLY / GLB / GLTF / FBX / DAE / 3DS via trimesh", "presets:meshconvert"),
        new("Pandoc Documents", "Markdown / RST / DOCX / EPUB / HTML / LaTeX / PDF universal markup", "presets:pandoc-cli"),
        new("RAW Photos", "Develop CR2 / CR3 / NEF / ARW / DNG / RAF -> JPEG / TIFF / PNG", "presets:rawphoto"),
        new("Scanned PDF OCR", "Add a searchable text layer to scanned PDFs (ocrmypdf)", "presets:pdfocr"),
        new("GIS Data", "KML / GPX / GeoJSON / Shapefile / GeoPackage via GDAL", "presets:gisconvert"),
        new("Settings", "Preferences, tool paths, shell integration, and performance", "settings"),
    ];

    private SettingsWindow? _settingsWindow;

    public MainWindow()
    {
        InitializeComponent();
        NavSearchBox.ItemsSource = _searchSuggestions;

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
        var appWindow = Microsoft.UI.Windowing.AppWindow.GetFromWindowId(windowId);
        appWindow.Resize(new Windows.Graphics.SizeInt32(1280, 820));

        var displayArea = Microsoft.UI.Windowing.DisplayArea.GetFromWindowId(windowId,
            Microsoft.UI.Windowing.DisplayAreaFallback.Primary);
        var centerX = (displayArea.WorkArea.Width - 1280) / 2;
        var centerY = (displayArea.WorkArea.Height - 820) / 2;
        appWindow.Move(new Windows.Graphics.PointInt32(centerX, centerY));

        if (appWindow.TitleBar is not null)
        {
            var titleBar = appWindow.TitleBar;
            titleBar.ExtendsContentIntoTitleBar = true;
            titleBar.PreferredHeightOption = Microsoft.UI.Windowing.TitleBarHeightOption.Tall;

            // Match design system: transparent title-bar background, primary text,
            // surface-light hover/pressed for system buttons.
            titleBar.BackgroundColor = Microsoft.UI.Colors.Transparent;
            titleBar.InactiveBackgroundColor = Microsoft.UI.Colors.Transparent;
            titleBar.ButtonBackgroundColor = Microsoft.UI.Colors.Transparent;
            titleBar.ButtonInactiveBackgroundColor = Microsoft.UI.Colors.Transparent;
            titleBar.ButtonForegroundColor = Windows.UI.Color.FromArgb(0xff, 0xe8, 0xec, 0xf3);
            titleBar.ButtonInactiveForegroundColor = Windows.UI.Color.FromArgb(0xff, 0x6d, 0x7d, 0x96);
            titleBar.ButtonHoverBackgroundColor = Windows.UI.Color.FromArgb(0xff, 0x1f, 0x23, 0x38);
            titleBar.ButtonHoverForegroundColor = Windows.UI.Color.FromArgb(0xff, 0xe8, 0xec, 0xf3);
            titleBar.ButtonPressedBackgroundColor = Windows.UI.Color.FromArgb(0xff, 0x25, 0x2a, 0x38);
            titleBar.ButtonPressedForegroundColor = Windows.UI.Color.FromArgb(0xff, 0xe8, 0xec, 0xf3);
        }

        App.Register(this);
        Activated += MainWindow_Activated;
    }

    private void MainWindow_Activated(object sender, WindowActivatedEventArgs args)
    {
        Activated -= MainWindow_Activated;
        // Default landing — JumpList passes `--route <key>` as activation arg
        // (see App.ConfigureJumpListAsync); honour it on first activate.
        var route = ParseJumpListRoute(Environment.GetCommandLineArgs());
        RequestNavigation(route ?? "home");
    }

    private static string? ParseJumpListRoute(string[] argv)
    {
        for (int i = 0; i < argv.Length - 1; i++)
        {
            if (argv[i] == "--route")
                return argv[i + 1];
        }
        return null;
    }

    public void RequestNavigation(string routeKey, object? parameter = null)
    {
        NavigateTo(routeKey, parameter);
        SelectMenuItem(GetNavigationSelectionTag(routeKey));
    }

    public void NavigateTo(string routeKey, object? parameter = null)
    {
        // "presets:meshconvert" -> nav to PresetsPage with "meshconvert" engine filter.
        string? routeParam = null;
        var colonIdx = routeKey.IndexOf(':');
        if (colonIdx > 0)
        {
            routeParam = routeKey[(colonIdx + 1)..];
            routeKey = routeKey[..colonIdx];
        }

        Type? pageType = routeKey switch
        {
            "home" => typeof(HomePage),
            "converter" => typeof(ConverterPage),
            "ai-lab" => typeof(AiLabPage),
            "compressor" => typeof(CompressorPage),
            "audio-converter" => typeof(AudioConverterPage),
            "audio-compressor" => typeof(AudioCompressorPage),
            "editor" => typeof(EditorPage),
            "lossless-cut" => typeof(LosslessCutPage),
            "dvd-rip" => typeof(DvdRipPage),
            "downloader" => typeof(DownloaderPage),
            "recorder" => typeof(RecorderPage),
            "toolbox" => typeof(ToolboxPage),
            "format-inspector" => typeof(FormatInspectorPage),
            "frame-snapshot" => typeof(FrameSnapshotPage),
            "ai-bgremove" => typeof(BackgroundRemoverPage),
            "ai-video-enhancer" => typeof(VideoEnhancerPage),
            "ai-image-enhancer" => typeof(ImageEnhancerPage),
            "ai-watermark" => typeof(WatermarkRemoverPage),
            "ai-subtitle" => typeof(AiSubtitlePage),
            "ai-summarizer" => typeof(VideoSummarizerPage),
            "ai-noise" => typeof(NoiseRemoverPage),
            "ai-vocal" => typeof(VocalRemoverPage),
            "ai-voice-changer" => typeof(VoiceChangerPage),
            "ai-tts" => typeof(TextToSpeechPage),
            "ai-stt" => typeof(SpeechToTextPage),
            "ai-photo-restore" => typeof(PhotoRestorationPage),
            "ai-colorize" => typeof(ColorizeVideoPage),
            // ROADMAP Item 27 — AI Portrait wires to PresetsPage with the
            // facerestore engine filter (CodeFormer fidelity slider +
            // GFPGAN side-by-side). The fidelity-vs-restoration nuance lives
            // in the preset args; the page UX is the existing PresetsPage.
            "ai-portrait" => typeof(PresetsPage),
            "lip-reading" => typeof(LipReadingPage),
            "gif-maker" => typeof(GifMakerPage),
            "slideshow-maker" => typeof(SlideshowPage),
            "image-converter" => typeof(ImageConverterPage),
            "auto-reframe" => typeof(AutoReframePage),
            "chapter-marks" => typeof(ChapterMarksPage),
            "watch-folders" => typeof(WatchFoldersPage),
            "history" => typeof(HistoryPage),
            "vmaf" => typeof(VmafAnalysisPage),
            "scene-detect" => typeof(SceneDetectPage),
            "auto-highlight" => typeof(AutoHighlightPage),
            "timeline-preview" => typeof(TimelinePreviewPage),
            "track-manager" => typeof(TrackManagerPage),
            "document-converter" => typeof(DocumentConverterPage),
            "archive" => typeof(ArchivePage),
            "pdf-tools" => typeof(PdfToolsPage),
            "subtitle-converter" => typeof(SubtitleConverterPage),
            "font-converter" => typeof(FontConverterPage),
            "ebook-converter" => typeof(EbookConverterPage),
            "ocr" => typeof(OcrPage),
            "presets" => typeof(PresetsPage),
            "universal-convert" => typeof(UniversalConvertPage),
            "batch-rename" => typeof(BatchRenamePage),
            _ => typeof(PlaceholderPage)
        };

        parameter ??= routeParam;
        if (pageType == typeof(PresetsPage) && parameter is null && routeKey == "ai-portrait")
            parameter = "facerestore";

        ContentFrame.Navigate(pageType, parameter, new EntranceNavigationTransitionInfo());
    }

    public void NavigateToPlaceholder(PlaceholderInfo info)
    {
        ContentFrame.Navigate(typeof(PlaceholderPage), info, new EntranceNavigationTransitionInfo());
    }

    private void SelectMenuItem(string tag)
    {
        // Search both the main pane and the footer pane (Settings, downloads,
        // etc. live in FooterMenuItems). The previous version walked only
        // MenuItems, so the selection chevron silently desynced for any nav
        // item that lived in the footer.
        if (TrySelectIn(MainNav.MenuItems, tag)) return;
        TrySelectIn(MainNav.FooterMenuItems, tag);
    }

    private bool TrySelectIn(IList<object> items, string tag)
    {
        foreach (var item in items)
        {
            if (item is not NavigationViewItem nvi) continue;
            if ((nvi.Tag as string) != tag) continue;
            if (ReferenceEquals(MainNav.SelectedItem, nvi)) return true;
            try
            {
                _isSelectingNavigationItem = true;
                MainNav.SelectedItem = nvi;
            }
            finally { _isSelectingNavigationItem = false; }
            return true;
        }
        return false;
    }

    private void MainNav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (_isSelectingNavigationItem)
            return;

        if (args.IsSettingsSelected)
        {
            OpenSettingsWindow();
            return;
        }

        if (args.SelectedItem is NavigationViewItem item && item.Tag is string tag)
        {
            NavigateTo(tag);
        }
    }

    private void NavSearchBox_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput)
            return;

        var query = sender.Text.Trim();
        sender.ItemsSource = string.IsNullOrWhiteSpace(query)
            ? _searchSuggestions
            : _searchSuggestions
                .Where(s => s.Title.Contains(query, StringComparison.OrdinalIgnoreCase)
                    || s.Subtitle.Contains(query, StringComparison.OrdinalIgnoreCase))
                .ToList();
    }

    private void NavSearchBox_SuggestionChosen(AutoSuggestBox sender, AutoSuggestBoxSuggestionChosenEventArgs args)
    {
        if (args.SelectedItem is NavSearchSuggestion suggestion)
            sender.Text = suggestion.Title;
    }

    private void NavSearchBox_QuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
    {
        var suggestion = args.ChosenSuggestion as NavSearchSuggestion
            ?? _searchSuggestions.FirstOrDefault(s =>
                s.Title.Equals(args.QueryText, StringComparison.OrdinalIgnoreCase))
            ?? _searchSuggestions.FirstOrDefault(s =>
                s.Title.Contains(args.QueryText, StringComparison.OrdinalIgnoreCase)
                || s.Subtitle.Contains(args.QueryText, StringComparison.OrdinalIgnoreCase));

        if (suggestion is null)
            return;

        if (suggestion.RouteKey == "settings")
            OpenSettingsWindow();
        else
            RequestNavigation(suggestion.RouteKey);
    }

    private void OpenSettingsWindow()
    {
        if (_settingsWindow is null)
        {
            _settingsWindow = new SettingsWindow(App.Services);
            _settingsWindow.Closed += (_, _) => _settingsWindow = null;
        }

        _settingsWindow.Activate();
    }

    private static string GetNavigationSelectionTag(string routeKey) => routeKey switch
    {
        _ when routeKey.StartsWith("presets:", StringComparison.OrdinalIgnoreCase) => "toolbox",
        "format-inspector" or "frame-snapshot" or "slideshow-maker" or "vmaf" or "scene-detect" or "auto-highlight" or "timeline-preview" or "track-manager" or "document-converter" or "archive" or "pdf-tools" or "subtitle-converter" or "font-converter" or "ebook-converter" or "ocr" or "batch-rename" => "toolbox",
        "ai-bgremove"
            or "ai-video-enhancer"
            or "ai-image-enhancer"
            or "ai-watermark"
            or "ai-subtitle"
            or "ai-summarizer"
            or "ai-noise"
            or "ai-vocal"
            or "ai-voice-changer"
            or "ai-tts"
            or "ai-stt"
            or "ai-photo-restore"
            or "lip-reading" => "ai-lab",
        _ => routeKey
    };
}

public sealed class NavSearchSuggestion
{
    public string Title { get; set; }
    public string Subtitle { get; set; }
    public string RouteKey { get; set; }

    public NavSearchSuggestion(string title, string subtitle, string routeKey)
    {
        Title = title;
        Subtitle = subtitle;
        RouteKey = routeKey;
    }
}
