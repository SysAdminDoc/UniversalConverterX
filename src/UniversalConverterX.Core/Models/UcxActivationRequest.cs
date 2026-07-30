namespace UniversalConverterX.Core.Models;

public enum UcxActivationSource
{
    Launch,
    File,
    Protocol,
    StartupTask,
    AppNotification,
}

public sealed record UcxActivationRequest(
    string RouteKey,
    IReadOnlyList<string> Paths,
    UcxActivationSource Source);
