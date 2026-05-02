using FluentAssertions;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public class OutputFilenameTemplateTests
{
    private static readonly DateTime FixedNow =
        new(2026, 5, 2, 12, 30, 0, DateTimeKind.Local);

    [Fact]
    public void Render_NullOrEmptyTemplate_ReturnsEmpty()
    {
        OutputFilenameTemplate.Render(null).Should().Be("");
        OutputFilenameTemplate.Render("").Should().Be("");
    }

    [Fact]
    public void Render_BuiltInPathTokens_FillFromSource()
    {
        var input = Path.Combine("C:", "media", "concert.wav");

        var result = OutputFilenameTemplate.Render(
            "{dir}/{stem}.{ext}",
            sourcePath: input);

        // {dir} preserves the absolute directory; {stem} sanitises but
        // "concert" is already safe.
        result.Should().Be(Path.Combine("C:", "media") + "/concert.wav");
    }

    [Fact]
    public void Render_DateAndYear_FromInjectedNow()
    {
        var result = OutputFilenameTemplate.Render(
            "{stem}_{date}_{year}",
            sourcePath: "/tmp/clip.mp4",
            now: FixedNow);

        result.Should().Be("clip_2026-05-02_2026");
    }

    [Fact]
    public void Render_PresetNameSanitised()
    {
        // Slash in preset name would otherwise produce "MP4 / 1080p"
        // which contains a path separator and would create a directory.
        var result = OutputFilenameTemplate.Render(
            "{preset}_{stem}",
            sourcePath: "/tmp/x.mkv",
            presetName: "MP4 / 1080p");

        result.Should().NotContain("/");
        result.Should().StartWith("MP4 _ 1080p");
    }

    [Fact]
    public void Render_MediaTokensFromCallerDict()
    {
        var tokens = new Dictionary<string, string?>
        {
            ["title"] = "My Song",
            ["artist"] = "Artist Name",
            ["resolution"] = "1920x1080",
            ["bitrate"] = "192",
            ["codec"] = "h264",
        };

        var result = OutputFilenameTemplate.Render(
            "{artist} - {title} [{resolution} {codec} {bitrate}k]",
            sourcePath: "/tmp/x.mp4",
            tokens: tokens);

        result.Should().Be("Artist Name - My Song [1920x1080 h264 192k]");
    }

    [Fact]
    public void Render_UntrustedMetadata_CannotEscapeDirectory()
    {
        // EXIF / ID3 / yt-dlp probes can return arbitrary strings.
        // Path SEPARATORS must be sanitised away from filename-component
        // tokens so users can't accidentally land output in unexpected
        // directories. Naked ".." sequences without a separator are inert
        // (just become part of the filename), so we don't strip those.
        var malicious = new Dictionary<string, string?>
        {
            ["title"] = "../../etc/passwd",
            ["artist"] = "evil\\path:thing",
        };

        var result = OutputFilenameTemplate.Render(
            "{artist}_{title}",
            sourcePath: "/tmp/x.mp3",
            tokens: malicious);

        // Path separators stripped — the security property of "stays in
        // the chosen output directory" holds.
        result.Should().NotContain("/");
        result.Should().NotContain("\\");
        result.Should().NotContain(":");
        // Whole-string check: no separator-prefixed traversal sequence.
        result.Should().NotContain("/..").And.NotContain("\\..");
    }

    [Fact]
    public void Render_UnknownToken_ExpandsToEmpty()
    {
        // Unknown tokens render to empty (NOT left as literal {foo}) so a
        // half-resolved template can't surface in user-visible paths.
        var result = OutputFilenameTemplate.Render(
            "{stem}_{this_token_doesnt_exist}",
            sourcePath: "/tmp/song.mp3");

        result.Should().Be("song_");
    }

    [Fact]
    public void Render_LiteralBraces_PreservedViaEscape()
    {
        // {{ and }} are escapes for literal { and }. Matches yt-dlp's
        // template DSL convention for round-trip compatibility.
        var result = OutputFilenameTemplate.Render(
            "{{escaped}} {stem} {{}}",
            sourcePath: "/tmp/x.mp4");

        result.Should().Be("{escaped} x {}");
    }

    [Fact]
    public void Render_UnterminatedBrace_LeftAsLiteral()
    {
        var result = OutputFilenameTemplate.Render(
            "{stem}_{forgot_to_close",
            sourcePath: "/tmp/x.mp4");

        // Unterminated open-brace is preserved so the user can spot the
        // typo in the rendered path.
        result.Should().Be("x_{forgot_to_close");
    }

    [Fact]
    public void Render_CallerOverridesBuiltIn()
    {
        // Preset can override {stem} (e.g. for batch-output-dir flows).
        var result = OutputFilenameTemplate.Render(
            "{stem}.out",
            sourcePath: "/tmp/x.mp4",
            tokens: new Dictionary<string, string?> { ["stem"] = "custom" });

        result.Should().Be("custom.out");
    }

    [Fact]
    public void Render_TokenNameIsCaseInsensitive()
    {
        var result = OutputFilenameTemplate.Render(
            "{Stem}_{TITLE}",
            sourcePath: "/tmp/x.mp4",
            tokens: new Dictionary<string, string?> { ["Title"] = "Hello" });

        result.Should().Be("x_Hello");
    }

    [Fact]
    public void GetSupportedTokens_ContainsBothBuiltInAndMedia()
    {
        var all = OutputFilenameTemplate.GetSupportedTokens();

        all.Should().Contain("stem");
        all.Should().Contain("dir");
        all.Should().Contain("date");
        all.Should().Contain("title");
        all.Should().Contain("resolution");
        all.Should().Contain("n");
    }

    [Fact]
    public void Render_BatchCounter_FromCaller()
    {
        // {n} is the per-batch counter — caller's responsibility to assign.
        var result = OutputFilenameTemplate.Render(
            "{stem}_{n}",
            sourcePath: "/tmp/x.mp4",
            tokens: new Dictionary<string, string?> { ["n"] = "003" });

        result.Should().Be("x_003");
    }
}
