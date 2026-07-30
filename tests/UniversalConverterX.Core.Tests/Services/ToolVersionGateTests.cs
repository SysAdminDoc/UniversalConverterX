using FluentAssertions;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public class ToolVersionGateTests
{
    [Fact]
    public void IsBlocked_KnownOldVersion_Blocks()
    {
        var assessment = ToolVersionPolicy.Assess("libheif", "1.18.1");

        ToolVersionGate.IsBlocked(assessment).Should().BeTrue();
    }

    [Fact]
    public void IsBlocked_MeetsFloor_DoesNotBlock()
    {
        var assessment = ToolVersionPolicy.Assess("libheif", "1.22.0");

        ToolVersionGate.IsBlocked(assessment).Should().BeFalse();
    }

    [Fact]
    public void IsBlocked_ExplicitlyRejectedVersion_Blocks()
    {
        var assessment = ToolVersionPolicy.Assess("vips", "8.19.0");

        ToolVersionGate.IsBlocked(assessment).Should().BeTrue();
        ToolVersionGate.BuildBlockedMessage(assessment)
            .Should().Contain("explicitly blocked")
            .And.Contain("CVE-2026-3281");
    }

    [Fact]
    public void IsBlocked_UnknownVersion_DoesNotBlock()
    {
        // A custom/nightly build whose version we cannot parse must never block.
        var assessment = ToolVersionPolicy.Assess("libheif", "custom nightly");

        assessment.VersionKnown.Should().BeFalse();
        ToolVersionGate.IsBlocked(assessment).Should().BeFalse();
    }

    [Fact]
    public void IsBlocked_ToolWithNoFloor_DoesNotBlock()
    {
        var assessment = ToolVersionPolicy.Assess("pandoc", "3.7.0");

        ToolVersionGate.IsBlocked(assessment).Should().BeFalse();
    }

    [Fact]
    public void BuildBlockedMessage_MentionsToolFloorAndReason()
    {
        var assessment = ToolVersionPolicy.Assess("libheif", "1.18.1");

        var message = ToolVersionGate.BuildBlockedMessage(assessment);

        message.Should().Contain("libheif");
        message.Should().Contain("1.18.1");
        message.Should().Contain("1.22.0");
        message.Should().Contain("CVE-2026-32740");
    }
}
