using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace UniversalConverterX.UI.Views.Pages;

public sealed partial class TextToSpeechPage : Page
{
    public TextToSpeechPage()
    {
        InitializeComponent();
        ScriptBox.TextChanged += ScriptBox_TextChanged;
    }

    private void ScriptBox_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (CharCountLabel is null) return;
        CharCountLabel.Text = $"{ScriptBox.Text.Length:N0} characters";
    }
}
