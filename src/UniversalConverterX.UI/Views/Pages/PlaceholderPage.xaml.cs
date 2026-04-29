using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Navigation;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class PlaceholderPage : Page
{
    public PlaceholderPage()
    {
        InitializeComponent();
    }

    protected override void OnNavigatedTo(NavigationEventArgs e)
    {
        base.OnNavigatedTo(e);
        if (e.Parameter is PlaceholderInfo info)
        {
            ApplyInfo(info);
        }
    }

    private void ApplyInfo(PlaceholderInfo info)
    {
        ModuleTitle.Text = info.Title;
        ModuleSubtitle.Text = info.Subtitle;
        ModuleIcon.Glyph = info.IconGlyph;
        HeadlineText.Text = info.Headline;
        DescriptionText.Text = info.Description;
        StatusBadge.Text = info.StatusBadge;

        if (!string.IsNullOrWhiteSpace(info.PoweredBy))
        {
            PoweredByText.Text = $"Powered by {info.PoweredBy}";
            PoweredByBox.Visibility = Microsoft.UI.Xaml.Visibility.Visible;
        }
    }
}

public sealed record PlaceholderInfo(
    string Title,
    string Subtitle,
    string IconGlyph,
    string Headline,
    string Description,
    string StatusBadge = "Coming Soon",
    string? PoweredBy = null);
