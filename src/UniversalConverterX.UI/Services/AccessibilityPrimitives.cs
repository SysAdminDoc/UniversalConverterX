using System.Runtime.CompilerServices;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace UniversalConverterX.UI.Services;

/// <summary>
/// Shared accessibility and responsive-layout behaviors for the desktop shell
/// and its pages. These behaviors deliberately change layout only; they never
/// move focus or synthesize input on behalf of the user.
/// </summary>
public sealed class AccessibilityPrimitives
{
    // The class is also the owner for the attached dependency property below;
    // the instance constructor keeps the WinUI XAML compiler's local type
    // resolver happy while all behavior remains stateless and static.
    public AccessibilityPrimitives()
    {
    }

    /// <summary>
    /// Width at which page padding and wide fixed columns switch to the compact
    /// layout. The UI smoke harness exercises this boundary at 640 px.
    /// </summary>
    public const double NarrowWindowWidth = 760;

    private const double WideFixedColumnThreshold = 280;
    private static readonly ConditionalWeakTable<Grid, GridLayoutState> GridStates = new();
    private static readonly ConditionalWeakTable<FrameworkElement, PaddingState> PaddingStates = new();

    public static readonly DependencyProperty ResponsiveLayoutEnabledProperty =
        DependencyProperty.RegisterAttached(
            "ResponsiveLayoutEnabled",
            typeof(bool),
            typeof(AccessibilityPrimitives),
            new PropertyMetadata(false, OnResponsiveLayoutEnabledChanged));

    public static bool GetResponsiveLayoutEnabled(DependencyObject obj) =>
        (bool)obj.GetValue(ResponsiveLayoutEnabledProperty);

    public static void SetResponsiveLayoutEnabled(DependencyObject obj, bool value) =>
        obj.SetValue(ResponsiveLayoutEnabledProperty, value);

    /// <summary>
    /// Applies polite UI Automation live regions to status-bearing controls in
    /// a page. Live regions announce changes without taking keyboard focus.
    /// </summary>
    public static void ApplyLiveRegions(DependencyObject? root)
    {
        if (root is null)
        {
            return;
        }

        ApplyLiveSetting(root);
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            ApplyLiveRegions(VisualTreeHelper.GetChild(root, index));
        }
    }

    private static void OnResponsiveLayoutEnabledChanged(
        DependencyObject dependencyObject,
        DependencyPropertyChangedEventArgs args)
    {
        if (dependencyObject is not FrameworkElement element)
        {
            return;
        }

        if ((bool)args.NewValue)
        {
            element.Loaded += ResponsiveElement_Loaded;
            element.SizeChanged += ResponsiveElement_SizeChanged;
            if (element.IsLoaded)
            {
                ApplyResponsiveLayout(element);
                ApplyLiveRegions(element);
            }
        }
        else
        {
            element.Loaded -= ResponsiveElement_Loaded;
            element.SizeChanged -= ResponsiveElement_SizeChanged;
            RestoreResponsiveLayout(element);
        }
    }

    private static void ResponsiveElement_Loaded(object sender, RoutedEventArgs args)
    {
        if (sender is FrameworkElement element)
        {
            ApplyResponsiveLayout(element);
            ApplyLiveRegions(element);
        }
    }

    private static void ResponsiveElement_SizeChanged(object sender, SizeChangedEventArgs args)
    {
        if (sender is FrameworkElement element)
        {
            ApplyResponsiveLayout(element);
        }
    }

    private static void ApplyResponsiveLayout(FrameworkElement root)
    {
        var isNarrow = root.ActualWidth > 0 && root.ActualWidth < NarrowWindowWidth;
        ApplyRootPadding(root, isNarrow);
        ApplyGridColumns(root, isNarrow);
    }

    private static void RestoreResponsiveLayout(FrameworkElement root)
    {
        ApplyRootPadding(root, isNarrow: false);
        ApplyGridColumns(root, isNarrow: false);
    }

    private static void ApplyRootPadding(FrameworkElement root, bool isNarrow)
    {
        switch (root)
        {
            case Grid grid:
            {
                var state = PaddingStates.GetValue(grid, _ => new PaddingState(grid.Padding));
                grid.Padding = isNarrow
                    ? new Thickness(16, 16, 16, 20)
                    : state.Original;
                break;
            }
            case StackPanel stackPanel:
            {
                var state = PaddingStates.GetValue(
                    stackPanel,
                    _ => new PaddingState(stackPanel.Padding));
                stackPanel.Padding = isNarrow
                    ? new Thickness(16, 16, 16, 20)
                    : state.Original;
                break;
            }
        }
    }

    private static void ApplyGridColumns(DependencyObject current, bool isNarrow)
    {
        if (current is Grid grid && grid.ColumnDefinitions.Count > 0)
        {
            var state = GridStates.GetValue(grid, _ => new GridLayoutState(
                grid.ColumnDefinitions.Select(column => column.Width).ToArray()));

            // A page may be retemplated after load. Re-capture only when the
            // collection shape changed; normal size changes always restore the
            // original widths from this snapshot.
            if (state.OriginalWidths.Length != grid.ColumnDefinitions.Count)
            {
                state.OriginalWidths = grid.ColumnDefinitions
                    .Select(column => column.Width)
                    .ToArray();
            }

            for (var index = 0; index < grid.ColumnDefinitions.Count; index++)
            {
                var original = state.OriginalWidths[index];
                if (isNarrow
                    && original.GridUnitType == GridUnitType.Pixel
                    && original.Value >= WideFixedColumnThreshold)
                {
                    grid.ColumnDefinitions[index].Width = new GridLength(1, GridUnitType.Star);
                }
                else
                {
                    grid.ColumnDefinitions[index].Width = original;
                }
            }
        }

        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(current); index++)
        {
            ApplyGridColumns(VisualTreeHelper.GetChild(current, index), isNarrow);
        }
    }

    private static void ApplyLiveSetting(DependencyObject dependencyObject)
    {
        var isStatusControl = dependencyObject is InfoBar
            or ProgressBar
            or ProgressRing;

        if (dependencyObject is TextBlock textBlock)
        {
            isStatusControl = IsStatusText(textBlock);
        }

        if (isStatusControl && AutomationProperties.GetLiveSetting(dependencyObject) == AutomationLiveSetting.Off)
        {
            AutomationProperties.SetLiveSetting(dependencyObject, AutomationLiveSetting.Polite);
        }
    }

    private static bool IsStatusText(TextBlock textBlock)
    {
        var identity = string.Join(
            " ",
            textBlock.Name,
            AutomationProperties.GetAutomationId(textBlock),
            AutomationProperties.GetName(textBlock))
            .ToLowerInvariant();

        return identity.Contains("status", StringComparison.Ordinal)
            || identity.Contains("message", StringComparison.Ordinal)
            || identity.Contains("progress", StringComparison.Ordinal)
            || identity.Contains("success", StringComparison.Ordinal)
            || identity.Contains("error", StringComparison.Ordinal)
            || identity.Contains("warning", StringComparison.Ordinal)
            || identity.Contains("result", StringComparison.Ordinal)
            || identity.Contains("complete", StringComparison.Ordinal);
    }

    private sealed class GridLayoutState(GridLength[] originalWidths)
    {
        public GridLength[] OriginalWidths { get; set; } = originalWidths;
    }

    private sealed class PaddingState(Thickness original)
    {
        public Thickness Original { get; } = original;
    }
}
