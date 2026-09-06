using System.ComponentModel;
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
    private const int SmXVirtualScreen = 76;
    private const int SmYVirtualScreen = 77;
    private const int SmCxVirtualScreen = 78;
    private const int GwlExStyle = -20;
    private const long WsExToolWindow = 0x00000080L;
    private const long WsExLayered = 0x00080000L;
    private const long WsExNoActivate = 0x08000000L;
    private const uint LwaAlpha = 0x00000002;
    private const uint SwpNoSize = 0x0001;
    private const uint SwpNoZOrder = 0x0004;
    private const uint SwpNoActivate = 0x0010;
    private const uint SwpShowWindow = 0x0040;

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
        if (UiSmokeHarness.IsActive)
        {
            // AppWindow.Resize can clamp an offscreen window back onto the
            // nearest monitor. Put it beyond the virtual desktop again before
            // the next route is rendered.
            ShowOffscreen(window);
        }
    }

    /// <summary>
    /// Makes the real shell render without touching the operator's visible
    /// desktop or stealing foreground focus. WinUI cannot initialize on a raw
    /// private desktop, so the smoke runner uses a composited window placed
    /// beyond the complete virtual-screen rectangle instead.
    /// </summary>
    internal static void ShowOffscreen(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);

        var hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window);
        var windowId = Microsoft.UI.Win32Interop.GetWindowIdFromWindow(hwnd);
        var appWindow = Microsoft.UI.Windowing.AppWindow.GetFromWindowId(windowId);
        appWindow.IsShownInSwitchers = false;

        // Windows can clamp a newly shown top-level window partly back onto a
        // physical monitor. Make it non-activating and fully transparent while
        // hidden, before any show operation, so even that OS safeguard cannot
        // expose the automated route sweep to the operator.
        var extendedStyle = GetWindowLongPtr(hwnd, GwlExStyle).ToInt64();
        SetWindowLongPtr(
            hwnd,
            GwlExStyle,
            new IntPtr(extendedStyle | WsExToolWindow | WsExLayered | WsExNoActivate));
        if (!SetLayeredWindowAttributes(hwnd, 0, 0, LwaAlpha))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(),
                "Could not make the UI smoke window transparent.");
        }

        var virtualRight = GetSystemMetrics(SmXVirtualScreen)
            + GetSystemMetrics(SmCxVirtualScreen);
        var virtualTop = GetSystemMetrics(SmYVirtualScreen);
        if (!SetWindowPos(
                hwnd,
                IntPtr.Zero,
                virtualRight + 512,
                virtualTop,
                0,
                0,
                SwpNoSize | SwpNoZOrder | SwpNoActivate | SwpShowWindow))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(),
                "Could not show the UI smoke window offscreen.");
        }
    }

    [DllImport("user32.dll", ExactSpelling = true)]
    private static extern uint GetDpiForWindow(IntPtr hwnd);

    [DllImport("user32.dll", ExactSpelling = true)]
    private static extern int GetSystemMetrics(int index);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW", ExactSpelling = true)]
    private static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW", ExactSpelling = true)]
    private static extern IntPtr SetWindowLongPtr(IntPtr hwnd, int index, IntPtr newLong);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetLayeredWindowAttributes(
        IntPtr hwnd,
        uint colorKey,
        byte alpha,
        uint flags);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetWindowPos(
        IntPtr hwnd,
        IntPtr hwndInsertAfter,
        int x,
        int y,
        int width,
        int height,
        uint flags);
}
