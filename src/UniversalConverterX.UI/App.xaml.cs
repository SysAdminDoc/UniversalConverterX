using Microsoft.Extensions.DependencyInjection;
using Microsoft.UI.Xaml;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Services;
using UniversalConverterX.UI.Services;
using UniversalConverterX.UI.ViewModels;
using UniversalConverterX.UI.Views;
using UniversalConverterX.UI.Views.Pages;

namespace UniversalConverterX.UI;

public partial class App : Application
{
    private static MainWindow? _mainWindow;

    public static IServiceProvider Services { get; private set; } = null!;

    public static Window MainWindowHandle => _mainWindow
        ?? throw new InvalidOperationException("Main window not registered yet.");

    public App()
    {
        InitializeComponent();
        ConfigureServices();
    }

    private static void ConfigureServices()
    {
        var services = new ServiceCollection();

        services.Configure<ConverterXOptions>(options =>
        {
            options.ToolsBasePath = GetDefaultToolsPath();
        });

        services.AddSingleton<IConversionOrchestrator, ConversionOrchestrator>();
        services.AddSingleton<IBatchQueueStore>(_ => new JsonBatchQueueStore(
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "UniversalConverterX",
                "queues")));
        services.AddSingleton<IToolDownloader>(sp => new ToolDownloader(
            sp.GetRequiredService<Microsoft.Extensions.Options.IOptions<ConverterXOptions>>(),
            new HttpClient()));
        services.AddSingleton<IToolManager>(sp => new ToolManager(
            sp.GetRequiredService<Microsoft.Extensions.Options.IOptions<ConverterXOptions>>(),
            sp.GetRequiredService<IToolDownloader>()));

        services.AddSingleton<INavigationService, NavigationService>();
        services.AddSingleton<IDialogService, DialogService>();
        services.AddSingleton<ISettingsService, SettingsService>();
        services.AddSingleton<ISidecarRunner, SidecarRunner>();
        services.AddSingleton<IHistoryService, HistoryService>();
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

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        // Eager-resolve the structured logger so the ring buffer is live for
        // the rest of launch — including the unhandled-exception bundler.
        var logger = Services.GetRequiredService<IStructuredLogger>();

        UnhandledException += (_, e) =>
        {
            LogUnhandledException(e.Exception);
            try
            {
                logger.Log(LogLevel.Crash, "app", "unhandled XAML exception", e.Exception);
                CrashBundle.Capture(logger, e.Exception);
            }
            catch { /* never throw from inside the unhandled-exception path */ }
            e.Handled = false;
        };

        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
        {
            var ex = e.ExceptionObject as Exception;
            LogUnhandledException(ex);
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

        _mainWindow = new MainWindow();
        _mainWindow.Activate();

        // Eagerly resolve singletons that need to start before any page is opened:
        //   * HistoryService: SQLite warm-up + initial Recent[] load on background thread.
        //   * WatchFolderService: saved profiles begin watching folders immediately.
        // WatchFolderService also depends on HistoryService for job logging, so order matters.
        _ = Services.GetRequiredService<IHistoryService>();
        _ = Services.GetRequiredService<IWatchFolderService>();

        // ROADMAP Item 7 — fire-and-forget update probe (24h-throttled,
        // honours ConverterXOptions.CheckForUpdates opt-out, never blocks
        // launch). Results land in update-cache.json for the dashboard.
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

    public static void RequestNavigation(string routeKey) => _mainWindow?.RequestNavigation(routeKey);

    public static void RequestPlaceholderNavigation(PlaceholderInfo info) =>
        _mainWindow?.NavigateToPlaceholder(info);

    public static void ApplyTheme(ElementTheme theme)
    {
        if (_mainWindow?.Content is Microsoft.UI.Xaml.FrameworkElement root)
            root.RequestedTheme = theme;
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
