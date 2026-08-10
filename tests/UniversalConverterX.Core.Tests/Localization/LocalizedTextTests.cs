using FluentAssertions;
using UniversalConverterX.Core.Configuration;
using UniversalConverterX.Core.Localization;

namespace UniversalConverterX.Core.Tests.Localization;

[CollectionDefinition("LocalizedText", DisableParallelization = true)]
public sealed class LocalizedTextCollection;

[Collection("LocalizedText")]
public sealed class LocalizedTextTests : IDisposable
{
    public LocalizedTextTests() => LocalizedText.Configure(null);

    public void Dispose() => LocalizedText.Configure(null);

    [Fact]
    public void Get_WithoutHostResolver_UsesEnglishFallback()
    {
        LocalizedText.Get("Missing", "English fallback").Should().Be("English fallback");
    }

    [Fact]
    public void Format_UsesHostResourceAndCurrentCultureFormatting()
    {
        LocalizedText.Configure((key, fallback) =>
            key == "Greeting" ? "Localized {0}" : fallback);

        LocalizedText.Format("Greeting", "Hello {0}", "world")
            .Should().Be("Localized world");
    }

    [Fact]
    public void Options_RoundTripLanguageOverride()
    {
        var loaded = ConverterXOptions.LoadFromJson(
            $$"""{"SchemaVersion":{{ConverterXOptions.CurrentSchemaVersion}},"Language":"pl-PL"}""",
            persistMigrated: false);

        loaded.Language.Should().Be("pl-PL");
    }

    [Theory]
    [InlineData("Ready", "［Ŕēȧḋŷ··］")]
    [InlineData("Value {0}", "［Ṿȧŀūē {0}··］")]
    public void PseudoLocalization_ExpandsCopyButPreservesPlaceholders(
        string value,
        string expected)
    {
        PseudoLocalization.Transform(value).Should().Be(expected);
    }

    [Fact]
    public void PseudoLocalization_LeavesEmptyValuesEmptyContent()
    {
        PseudoLocalization.Transform(string.Empty).Should().Be("" /* no visible copy */);
    }
}
