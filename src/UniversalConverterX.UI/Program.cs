using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;

namespace UniversalConverterX.UI;

public static class Program
{
    private const string MainInstanceKey = "UniversalConverterX.Main";
    private static AppInstance? _mainInstance;

    internal static AppActivationArguments InitialActivationArguments { get; private set; } = null!;
    internal static IReadOnlyList<string> InitialCommandLine { get; private set; } =
        Array.Empty<string>();

    [STAThread]
    private static void Main(string[] args)
    {
        WinRT.ComWrappersSupport.InitializeComWrappers();

        var activationArguments = AppInstance.GetCurrent().GetActivatedEventArgs();
        var instance = AppInstance.FindOrRegisterForKey(MainInstanceKey);
        if (!instance.IsCurrent)
        {
            instance.RedirectActivationToAsync(activationArguments)
                .AsTask()
                .GetAwaiter()
                .GetResult();
            return;
        }

        _mainInstance = instance;
        InitialActivationArguments = activationArguments;
        InitialCommandLine = args;
        _mainInstance.Activated += (_, activation) =>
            App.DispatchActivation(activation);

        Application.Start(_ =>
        {
            var dispatcher = DispatcherQueue.GetForCurrentThread();
            SynchronizationContext.SetSynchronizationContext(
                new DispatcherQueueSynchronizationContext(dispatcher));
            new App();
        });
    }
}
