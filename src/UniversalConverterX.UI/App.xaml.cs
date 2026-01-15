using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Options;
using Microsoft.UI.Xaml;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Interfaces;
using UniversalConverterX.Core.Services;
using UniversalConverterX.UI.Services;
using UniversalConverterX.UI.ViewModels;
using UniversalConverterX.UI.Views;

namespace UniversalConverterX.UI;

public partial class App : Application
{
    private Window? _mainWindow;

    public static IServiceProvider Services { get; private set; } = null!;

    public App()
    {
        InitializeComponent();
        ConfigureServices();
    }

    private static void ConfigureServices()
    {
        var services = new ServiceCollection();

        // Configuration
        services.Configure<ConverterXOptions>(options =>
        {
            options.ToolsBasePath = GetDefaultToolsPath();
        });

        // Core services
        services.AddSingleton<IConversionOrchestrator, ConversionOrchestrator>();
        services.AddSingleton<IToolManager, ToolManager>();

        // UI services
        services.AddSingleton<INavigationService, NavigationService>();
        services.AddSingleton<IDialogService, DialogService>();
        services.AddSingleton<ISettingsService, SettingsService>();

        // ViewModels
        services.AddTransient<MainViewModel>();
        services.AddTransient<ConversionViewModel>();
        services.AddTransient<SettingsViewModel>();
        services.AddTransient<ProgressViewModel>();

        Services = services.BuildServiceProvider();
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        _mainWindow = new MainWindow();
        _mainWindow.Activate();
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
}
