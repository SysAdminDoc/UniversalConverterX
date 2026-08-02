using System.Runtime.InteropServices;
using Microsoft.UI.Xaml;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// Deterministic shell manipulation used by automated UI passes: theme
/// switching and window sizing, applied to the real window rather than to a
/// test double. Kept separate from the smoke harness so the accessibility,
/// contrast, and reflow passes can drive the same hooks.
/// </summary>
internal static class UiTestHooks
{
    /// <summary>Applies a theme to the whole visual tree of a window.</summary>
    internal static void ApplyTheme(Window window, ElementTheme theme)
    {
        ArgumentNullException.ThrowIfNull(window);
        if (window.Content is FrameworkElement root)
        {
            root.RequestedTheme = theme;
        }
    }

    /// <summary>
    /// Resizes a window in device-independent pixels so reflow checks are
    /// stable at the 125% scaling this project's screenshots are captured at.
    /// </summary>
    internal static void ResizeWindow(Window window, int width, int height)
    {
        ArgumentNullException.ThrowIfNull(window);
        ArgumentOutOfRangeException.ThrowIfLessThan(width, 320);
        ArgumentOutOfRangeException.ThrowIfLessThan(height, 240);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window);
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
        var appWindow = Microsoft.UI.Windowing.AppWindow.GetFromWindowId(windowId);

        // AppWindow.Resize takes physical pixels while XAML lays out in DIPs.
        // Ignoring the difference silently shrinks every reflow check on a
        // scaled display; this machine runs at 125%.
        var dpi = GetDpiForWindow(hwnd);
        var scale = dpi <= 0 ? 1.0 : dpi / 96.0;
        appWindow.Resize(new Windows.Graphics.SizeInt32(
            (int)Math.Round(width * scale),
            (int)Math.Round(height * scale)));
    }

    [DllImport("user32.dll", ExactSpelling = true)]
    private static extern uint GetDpiForWindow(IntPtr hwnd);
}
