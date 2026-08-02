using FluentAssertions;
using UniversalConverterX.Core.Security;

namespace UniversalConverterX.Core.Tests.Security;

/// <summary>
/// Provenance is only useful if a user can attach it to a bug report, and the
/// argument vectors reaching sidecars carry cookies, tokens, signed URLs, and
/// the operator's home directory (ROADMAP Item 154).
/// </summary>
public sealed class ArgumentRedactorTests
{
    [Fact]
    public void SecretFlagValuesAreRemovedInTheSeparateArgumentForm()
    {
        var redacted = ArgumentRedactor.Redact(
            ["--input", "a.mkv", "--token", "ghp_supersecret", "--verbose"]);

        redacted.Should().Equal(
            "--input", "a.mkv", "--token", ArgumentRedactor.Placeholder, "--verbose");
    }

    [Fact]
    public void SecretFlagValuesAreRemovedInTheEqualsForm()
    {
        ArgumentRedactor.Redact(["--api-key=abc123"])
            .Should().Equal($"--api-key={ArgumentRedactor.Placeholder}");
    }

    [Fact]
    public void SecretFlagMatchingIsCaseInsensitive()
    {
        ArgumentRedactor.Redact(["--PASSWORD", "hunter2"])
            .Should().Equal("--PASSWORD", ArgumentRedactor.Placeholder);
    }

    [Fact]
    public void OnlyTheValueImmediatelyAfterASecretFlagIsRemoved()
    {
        ArgumentRedactor.Redact(["--cookies", "jar.txt", "--output", "out.mp4"])
            .Should().Equal(
                "--cookies", ArgumentRedactor.Placeholder, "--output", "out.mp4");
    }

    [Fact]
    public void UrlCredentialsAndQueryStringsAreStripped()
    {
        var redacted = ArgumentRedactor.Redact(
            ["--url", "https://user:pw@cdn.example.com/video.m3u8?Signature=abcdef&Expires=1"]);

        var value = redacted[1];
        value.Should().StartWith("https://cdn.example.com/video.m3u8");
        value.Should().NotContain("user");
        value.Should().NotContain("pw");
        value.Should().NotContain("Signature");
        value.Should().NotContain("abcdef");
    }

    [Fact]
    public void AUrlWithoutAQueryStringKeepsItsShape()
    {
        ArgumentRedactor.RedactValue("https://example.com/clip.mp4")
            .Should().Be("https://example.com/clip.mp4");
    }

    [Fact]
    public void PathsUnderTheUserProfileAreRewrittenRelativeToIt()
    {
        var profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (string.IsNullOrEmpty(profile))
        {
            return;
        }

        var path = Path.Combine(profile, "Videos", "holiday.mkv");
        var redacted = ArgumentRedactor.RedactValue(path);

        redacted.Should().StartWith("~");
        redacted.Should().NotContain(Path.GetFileName(
            Path.TrimEndingDirectorySeparator(profile)));
        redacted.Should().EndWith(Path.Combine("Videos", "holiday.mkv"));
    }

    [Fact]
    public void APathOutsideTheUserProfileIsUnchanged()
    {
        ArgumentRedactor.RedactValue(@"D:\media\clip.mkv")
            .Should().Be(@"D:\media\clip.mkv");
    }

    [Theory]
    [InlineData("failed: token=abc123 rejected")]
    [InlineData("Authorization: Bearer eyJhbGciOi")]
    [InlineData("api_key = 9f8e7d")]
    public void InlineSecretsInMessagesAreScrubbed(string message)
    {
        var redacted = ArgumentRedactor.RedactMessage(message);

        redacted.Should().Contain(ArgumentRedactor.Placeholder);
        redacted.Should().NotContain("abc123");
        redacted.Should().NotContain("eyJhbGciOi");
        redacted.Should().NotContain("9f8e7d");
    }

    [Fact]
    public void NullAndEmptyInputsAreHandled()
    {
        ArgumentRedactor.Redact(null).Should().BeEmpty();
        ArgumentRedactor.RedactValue(null).Should().BeEmpty();
        ArgumentRedactor.RedactMessage(null).Should().BeEmpty();
    }

    [Fact]
    public void OrdinaryArgumentsSurviveUntouched()
    {
        ArgumentRedactor.Redact(["--crf", "23", "--preset", "slow"])
            .Should().Equal("--crf", "23", "--preset", "slow");
    }
}
