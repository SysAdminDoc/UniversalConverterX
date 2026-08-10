using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Microsoft.Windows.AppLifecycle;
using Microsoft.Windows.AppNotifications;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Localization;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Services;
using UniversalConverterX.Core.Security;
using UniversalConverterX.UI.Services;
using UniversalConverterX.UI.ViewModels;
using UniversalConverterX.UI.Views;
using UniversalConverterX.UI.Views.Pages;
using Windows.ApplicationModel.Activation;

namespace UniversalConverterX.UI;

public partial class App : Application
{
    private static readonly object ActivationSync = new();
    private static readonly Queue<UcxActivationRequest> PendingActivations = new();
    private static MainWindow? _mainWindow;
    private static DispatcherQueue? _dispatcherQueue;
    private static bool _notificationsRegistered;
    private static ConverterXOptions? _startupOptions;

    public static IServiceProvider Services { get; private set; } = null!;

    public static Window MainWindowHandle => _mainWindow
        ?? throw new InvalidOperationException("Main window not registered yet.");

    public App()
    {
        var persistedOptions = ConverterXOptions.Load();
        _startupOptions = persistedOptions;
        ApplyLanguageOverride(persistedOptions.Language);
        InitializeComponent();
        ApplyAccentColor(persistedOptions.AccentColor);
        ConfigureServices(persistedOptions);
        LocalizedText.Configure(AppLocalizer.Get);
    }

    private static void ConfigureServices(ConverterXOptions persistedOptions)
    {
        var services = new ServiceCollection();

        if (string.IsNullOrWhiteSpace(persistedOptions.ToolsBasePath))
            persistedOptions.ToolsBasePath = GetDefaultToolsPath();
        services.AddSingleton<Microsoft.Extensions.Options.IOptions<ConverterXOptions>>(
            Microsoft.Extensions.Options.Options.Create(persistedOptions));

        services.AddSingleton<IConversionOrchestrator, ConversionOrchestrator>();
        services.AddSingleton<IBatchQueueStore>(_ => new JsonBatchQueueStore(
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "UniversalConverterX",
                "queues")));
        services.AddSingleton<IAppJobCoordinator, AppJobCoordinator>();
        services.AddSingleton<IToolDownloader>(sp => new ToolDownloader(
            sp.GetRequiredService<Microsoft.Extensions.Options.IOptions<ConverterXOptions>>(),
            new HttpClient()));
        services.AddSingleton<IToolManager>(sp => new ToolManager(
            sp.GetRequiredService<Microsoft.Extensions.Options.IOptions<ConverterXOptions>>(),
            sp.GetRequiredService<IToolDownloader>()));

        services.AddSingleton<INavigationService, NavigationService>();
        services.AddSingleton<IDialogService, DialogService>();
        services.AddSingleton<ISettingsService, SettingsService>();
        services.AddSingleton<IFfmpegCommandReviewService, FfmpegCommandReviewService>();
        services.AddSingleton<IPluginTrustService, PluginTrustService>();
        services.AddSingleton<ISidecarRunner, SidecarRunner>();
        services.AddSingleton<IHistoryService, HistoryService>();
        services.AddSingleton<IPostQueueActionService, PostQueueActionService>();
        services.AddSingleton<IWatchFolderService, WatchFolderService>();
        services.AddSingleton<IPresetExecutor, PresetExecutor>();
        services.AddSingleton<IUiPresetCache, UiPresetCache>();
        services.AddSingleton<ISidecarHealthService, SidecarHealthService>();
        services.AddSingleton<IUpdateCheckService, UpdateCheckService>();
        services.AddSingleton<IStructuredLogger, StructuredLogger>();

        services.AddTransient<MainViewModel>();
        services.AddTransient<ConversionViewModel>();
        services.AddTransient<SettingsViewModel>();
        services.AddTransient<ProgressViewModel>();

        Services = services.BuildServiceProvider();
    }

    private static void ApplyLanguageOverride(string? language)
    {
        var supported = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "en-US", "de-DE", "fr-FR", "es-ES", "pl-PL", "zh-Hans", "qps-ploc",
        };
        if (string.Equals(Environment.GetEnvironmentVariable("UCX_PSEUDO_LOCALE"), "1", StringComparison.OrdinalIgnoreCase)
            || string.Equals(Environment.GetEnvironmentVariable("UCX_PSEUDO_LOCALE"), "true", StringComparison.OrdinalIgnoreCase))
        {
            Windows.Globalization.ApplicationLanguages.PrimaryLanguageOverride = "qps-ploc";
        }
        else if (!string.IsNullOrWhiteSpace(language) && supported.Contains(language))
        {
            Windows.Globalization.ApplicationLanguages.PrimaryLanguageOverride = language;
        }
    }

    protected override void OnLaunched(
        Microsoft.UI.Xaml.LaunchActivatedEventArgs args)
    {
        _dispatcherQueue = DispatcherQueue.GetForCurrentThread();

        // Eager-resolve the structured logger so the ring buffer is live for
        // the rest of launch — including the unhandled-exception bundler.
        var logger = Services.GetRequiredService<IStructuredLogger>();

        var smokeOptions = UiSmokeHarness.TryParse(Program.InitialCommandLine);

        UnhandledException += (_, e) =>
        {
            LogUnhandledException(e.Exception);
            try
            {
                logger.Log(LogLevel.Crash, "app", "unhandled XAML exception", e.Exception);
                CrashBundle.Capture(logger, e.Exception);
            }
            catch { /* never throw from inside the unhandled-exception path */ }

            // Under the smoke harness the run must survive a broken page so the
            // report names every failure instead of only the first one. The
            // exception is still recorded and still fails the run.
            if (smokeOptions is not null)
            {
                UiSmokeHarness.RecordUnhandled("xaml", e.Exception);
                e.Handled = true;
                return;
            }

            e.Handled = false;
        };

        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
        {
            var ex = e.ExceptionObject as Exception;
            LogUnhandledException(ex);
            if (smokeOptions is not null)
            {
                UiSmokeHarness.RecordUnhandled("appdomain", ex);
            }
            try
            {
                logger.Log(LogLevel.Crash, "appdomain", "unhandled native-side exception", ex);
                CrashBundle.Capture(logger, ex);
            }
            catch { }
        };

        TaskScheduler.UnobservedTaskException += (_, e) =>
        {
            try { logger.Log(LogLevel.Error, "tasks", "unobserved task exception", e.Exception); }
            catch { }
        };

        RegisterNotificationActivation();
        DispatchActivation(
            Program.InitialActivationArguments,
            Program.InitialCommandLine);

        _mainWindow = new MainWindow();
        _mainWindow.Activate();
        if (_startupOptions?.StartMinimized == true)
            _mainWindow.HideToBackground();
        DrainPendingActivations();

        if (smokeOptions is not null)
        {
            // Runtime UI gate: sweep every registered route in both themes and
            // at the narrow reflow width, then exit with the verdict. Nothing
            // below this point should start background work during a sweep.
            var smokeWindow = _mainWindow;
            _ = _dispatcherQueue.TryEnqueue(async () =>
                await UiSmokeHarness.RunAsync(smokeWindow, smokeOptions));
            return;
        }

        // Eagerly resolve singletons that need to start before any page is opened:
        //   * HistoryService: SQLite warm-up + initial Recent[] load on background thread.
        //   * WatchFolderService: saved profiles begin watching folders immediately.
        // WatchFolderService also depends on HistoryService for job logging, so order matters.
        _ = Services.GetRequiredService<IAppJobCoordinator>();
        _ = Services.GetRequiredService<IHistoryService>();
        _ = Services.GetRequiredService<IWatchFolderService>();

        // Reclaim job workspaces left behind by a hard kill or power loss. A
        // day-old directory cannot belong to a live job, so this never disturbs
        // a concurrent run.
        _ = Task.Run(() =>
        {
            try { SidecarWorkspace.PurgeStale(TimeSpan.FromDays(1)); }
            catch { /* housekeeping must never affect launch */ }
        });

        // Fire-and-forget app/tool update and compatibility probe
        // (24h-throttled, honours ConverterXOptions.CheckForUpdates opt-out,
        // never blocks launch). Results land in update-cache.json.
        _ = Task.Run(async () =>
        {
            try
            {
                var checker = Services.GetRequiredService<IUpdateCheckService>();
                await checker.CheckAsync().ConfigureAwait(false);
            }
            catch { /* probe failures must never crash the app */ }
        });

        _ = ConfigureJumpListAsync();
    }

    internal static void DispatchActivation(AppActivationArguments arguments) =>
        DispatchActivation(arguments, null);

    private static void DispatchActivation(
        AppActivationArguments arguments,
        IReadOnlyList<string>? initialCommandLine)
    {
        UcxActivationRequest request;
        try
        {
            request = arguments.Kind switch
            {
                ExtendedActivationKind.File
                    when arguments.Data is IFileActivatedEventArgs files =>
                    UcxActivationParser.ParseFiles(files.Files.Select(item => item.Path)),
                ExtendedActivationKind.Protocol
                    when arguments.Data is IProtocolActivatedEventArgs protocol =>
                    UcxActivationParser.ParseProtocol(protocol.Uri),
                ExtendedActivationKind.StartupTask =>
                    UcxActivationParser.Startup(),
                ExtendedActivationKind.AppNotification
                    when arguments.Data is AppNotificationActivatedEventArgs notification =>
                    UcxActivationParser.ParseToast(notification.Argument),
                ExtendedActivationKind.Launch =>
                    ParseLaunchActivation(arguments.Data, initialCommandLine),
                _ => UcxActivationParser.ParseCommandLine(Array.Empty<string>()),
            };
        }
        catch
        {
            request = UcxActivationParser.ParseCommandLine(Array.Empty<string>());
        }

        QueueActivation(request);
    }

    private static UcxActivationRequest ParseLaunchActivation(
        object data,
        IReadOnlyList<string>? initialCommandLine)
    {
        if (initialCommandLine is { Count: > 0 })
            return UcxActivationParser.ParseCommandLine(initialCommandLine);
        if (data is ILaunchActivatedEventArgs launch
            && !string.IsNullOrWhiteSpace(launch.Arguments))
        {
            return UcxActivationParser.ParseCommandLine(launch.Arguments);
        }
        return UcxActivationParser.ParseCommandLine(Array.Empty<string>());
    }

    private static void QueueActivation(UcxActivationRequest request)
    {
        var dispatcher = _dispatcherQueue;
        if (_mainWindow is null || dispatcher is null)
        {
            lock (ActivationSync)
                PendingActivations.Enqueue(request);
            return;
        }

        if (dispatcher.HasThreadAccess)
            ApplyActivation(request);
        else if (!dispatcher.TryEnqueue(() => ApplyActivation(request)))
        {
            lock (ActivationSync)
                PendingActivations.Enqueue(request);
        }
    }

    private static void DrainPendingActivations()
    {
        while (true)
        {
            UcxActivationRequest? request;
            lock (ActivationSync)
                request = PendingActivations.Count > 0
                    ? PendingActivations.Dequeue()
                    : null;
            if (request is null)
                return;
            ApplyActivation(request);
        }
    }

    private static void ApplyActivation(UcxActivationRequest request)
    {
        if (_mainWindow is null)
            return;

        _mainWindow.Activate();
        if (request.Paths.Count > 0)
            _mainWindow.RequestNavigation(
                "converter",
                new FileIntakeRequest(request.Paths));
        else
            _mainWindow.RequestNavigation(request.RouteKey);
    }

    private static void RegisterNotificationActivation()
    {
        if (_notificationsRegistered)
            return;
        try
        {
            var manager = AppNotificationManager.Default;
            manager.NotificationInvoked += (_, notification) =>
                QueueActivation(UcxActivationParser.ParseToast(notification.Argument));
            manager.Register();
            _notificationsRegistered = true;
        }
        catch
        {
            // App notifications are optional on unsupported or policy-blocked systems.
        }
    }

    /// <summary>
    /// Quick-launch entries on the taskbar icon (right-click) and Start menu
    /// tile flyout. Maps the most-used UCX modules to a JumpList task each, so
    /// users can land directly on Convert / Compress / Trim / Record from
    /// outside the app. Activation goes through `--route &lt;key&gt;` which
    /// MainWindow already understands.
    /// </summary>
    private static async Task ConfigureJumpListAsync()
    {
        try
        {
            if (!Windows.UI.StartScreen.JumpList.IsSupported())
                return;

            var list = await Windows.UI.StartScreen.JumpList.LoadCurrentAsync();
            list.Items.Clear();
            list.SystemGroupKind = Windows.UI.StartScreen.JumpListSystemGroupKind.Frequent;

            void Add(string routeKey, string display, string description)
            {
                var item = Windows.UI.StartScreen.JumpListItem.CreateWithArguments($"--route {routeKey}", display);
                item.Description = description;
                item.GroupName = "UCX shortcuts";
                list.Items.Add(item);
            }

            Add("converter", "Converter", "Batch convert media to any of 1000+ formats");
            Add("compressor", "Compressor", "Shrink videos for web, email, and social");
            Add("editor", "Editor", "Trim, crop, rotate, normalize, rewrap clips");
            Add("downloader", "Downloader", "Pull video / audio from supported URLs");
            Add("recorder", "Recorder", "Record screen, webcam, and microphone");
            Add("toolbox", "Toolbox", "Browse all 30+ specialized media tools");

            await list.SaveAsync();
        }
        catch
        {
            // Windows JumpList is best-effort; never block app launch on failures
            // (locked-down profile policies / packaged-vs-unpackaged differences).
        }
    }

    internal static void Register(MainWindow window) => _mainWindow = window;

    public static void RequestNavigation(string routeKey, object? parameter = null) =>
        _mainWindow?.RequestNavigation(routeKey, parameter);

    public static void RequestPlaceholderNavigation(PlaceholderInfo info) =>
        _mainWindow?.NavigateToPlaceholder(info);

    public static void ApplyTheme(ElementTheme theme)
    {
        if (_mainWindow?.Content is Microsoft.UI.Xaml.FrameworkElement root)
            root.RequestedTheme = theme;
    }

    /// <summary>
    /// Applies the user-selected primary accent to the shared brush instances.
    /// Semantic success/warning/error colors remain distinct so status meaning
    /// is not conveyed by accent color alone.
    /// </summary>
    public static void ApplyAccentColor(string? hex)
    {
        if (!TryParseColor(hex, out var color) || Current?.Resources is not { } resources)
            return;

        SetBrushColor(resources, "AccentPrimaryBrush", color);
        SetBrushColor(resources, "AccentPrimaryHoverBrush", Blend(color, 0.18, 255, 255, 255));
        SetBrushColor(resources, "AccentPrimaryPressedBrush", Blend(color, 0.22, 0, 0, 0));
        SetBrushColor(resources, "AccentPrimarySoftBrush", Blend(color, 0.82, 255, 255, 255));
    }

    private static void SetBrushColor(ResourceDictionary resources, string key, Windows.UI.Color color)
    {
        if (resources.TryGetValue(key, out var resource) && resource is SolidColorBrush brush)
            brush.Color = color;
    }

    private static Windows.UI.Color Blend(
        Windows.UI.Color color,
        double amount,
        byte red,
        byte green,
        byte blue) => Windows.UI.Color.FromArgb(
            color.A,
            (byte)(color.R + (red - color.R) * amount),
            (byte)(color.G + (green - color.G) * amount),
            (byte)(color.B + (blue - color.B) * amount));

    private static bool TryParseColor(string? hex, out Windows.UI.Color color)
    {
        color = default;
        if (string.IsNullOrWhiteSpace(hex))
            return false;

        var value = hex.Trim().TrimStart('#');
        if (value.Length != 6
            || !byte.TryParse(value[0..2], System.Globalization.NumberStyles.HexNumber, null, out var red)
            || !byte.TryParse(value[2..4], System.Globalization.NumberStyles.HexNumber, null, out var green)
            || !byte.TryParse(value[4..6], System.Globalization.NumberStyles.HexNumber, null, out var blue))
        {
            return false;
        }

        color = Windows.UI.Color.FromArgb(255, red, green, blue);
        return true;
    }

    private static string GetDefaultToolsPath()
    {
        var locations = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "tools"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "UniversalConverterX", "tools"),
        };

        foreach (var loc in locations)
        {
            if (Directory.Exists(loc))
                return loc;
        }

        return locations[0];
    }

    private static void LogUnhandledException(Exception? exception)
    {
        try
        {
            var logDirectory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "UniversalConverterX",
                "logs");
            Directory.CreateDirectory(logDirectory);

            var log = Path.Combine(logDirectory, "ucx_crash.log");
            File.AppendAllText(log,
                $"[{DateTime.Now:o}] {exception?.GetType().FullName}: {exception?.Message}\n{exception?.StackTrace}\n---\n");
        }
        catch
        {
            // Never let crash logging throw inside the unhandled-exception path.
        }
    }
}
