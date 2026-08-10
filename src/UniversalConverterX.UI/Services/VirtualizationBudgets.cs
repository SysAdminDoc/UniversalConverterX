namespace UniversalConverterX.UI.Services;

/// <summary>
/// Headless performance contract for the large catalog pages. The UI tests
/// assert these values alongside the virtualized XAML so a future page change
/// cannot silently turn a bounded list back into an unbounded materialization.
/// </summary>
internal static class VirtualizationBudgets
{
    internal const int HistoryPageSize = 100;
    internal const int HistoryMaxRows = 500;
    internal const int PresetSearchResultLimit = 100;
    internal const int PresetSearchDebounceMilliseconds = 120;
    internal const int HistorySearchDebounceMilliseconds = 200;

    // Budgets used by the headless contract gate when a Windows UI runner is
    // available to record cold navigation and realized-container telemetry.
    internal const int ColdNavigationBudgetMilliseconds = 1_000;
    internal const int MaxRealizedContainers = 64;
    internal const long MaxWorkingSetGrowthBytes = 128L * 1024L * 1024L;
}
