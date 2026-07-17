using Microsoft.UI.Composition.SystemBackdrops;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Foundation.Metadata;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// Applies element-scoped system materials only when both the WinUI control and
/// the requested compositor material are available. Callers keep a solid
/// surface behind each host so unsupported systems retain the normal theme.
/// </summary>
internal static class SystemBackdropMaterialService
{
    private const string SystemBackdropElementType =
        "Microsoft.UI.Xaml.Controls.SystemBackdropElement";

    public static bool TryApplyMica(SystemBackdropElement host) =>
        TryApply(host, MicaController.IsSupported, static () => new MicaBackdrop());

    public static bool TryApplyAcrylic(SystemBackdropElement host) =>
        TryApply(host, DesktopAcrylicController.IsSupported,
            static () => new DesktopAcrylicBackdrop());

    private static bool TryApply(
        SystemBackdropElement host,
        Func<bool> isMaterialSupported,
        Func<SystemBackdrop> createBackdrop)
    {
        ArgumentNullException.ThrowIfNull(host);

        if (!ApiInformation.IsTypePresent(SystemBackdropElementType) ||
            !isMaterialSupported())
        {
            host.SystemBackdrop = null;
            return false;
        }

        try
        {
            host.SystemBackdrop = createBackdrop();
            return true;
        }
        catch (Exception)
        {
            // Remote sessions, disabled transparency, and older graphics
            // drivers can reject a material after a positive support probe.
            host.SystemBackdrop = null;
            return false;
        }
    }
}
