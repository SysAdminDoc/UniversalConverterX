using FluentAssertions;
using UniversalConverterX.Console.Commands;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class ServeRequestSecurityTests
{
    [Fact]
    public void HostPolicy_AllowsOnlyExactLoopbackAuthorities()
    {
        var security = ServeRequestSecurity.Create("127.0.0.1", 17654);

        security.IsHostAllowed("127.0.0.1:17654").Should().BeTrue();
        security.IsHostAllowed("LOCALHOST:17654").Should().BeTrue();
        security.IsHostAllowed("evil.example:17654").Should().BeFalse();
        security.IsHostAllowed("127.0.0.1:17655").Should().BeFalse();
        security.IsHostAllowed("127.0.0.1").Should().BeFalse();
    }

    [Fact]
    public void Authorization_RequiresTheFreshBearerToken()
    {
        var security = ServeRequestSecurity.Create("127.0.0.1", 17654);

        security.IsAuthorized($"Bearer {security.Token}").Should().BeTrue();
        security.IsAuthorized($"bearer {security.Token}").Should().BeTrue();
        security.IsAuthorized("Bearer wrong").Should().BeFalse();
        security.IsAuthorized(security.Token).Should().BeFalse();
        security.IsAuthorized(null).Should().BeFalse();
    }

    [Fact]
    public void BrowserMetadata_IsRejectedEvenWhenTheTokenIsValid()
    {
        var security = ServeRequestSecurity.Create("127.0.0.1", 17654);

        security.IsCrossOrigin(["Origin"], "same-origin").Should().BeTrue();
        security.IsCrossOrigin([], "cross-site").Should().BeTrue();
        security.IsCrossOrigin([], "same-origin").Should().BeFalse();
        security.IsCrossOrigin([], null).Should().BeFalse();
    }

    [Fact]
    public void RequestValidation_RejectsSimpleBrowserRequestsAndRebindingHosts()
    {
        var security = ServeRequestSecurity.Create("127.0.0.1", 17654);
        var validAuthorization = $"Bearer {security.Token}";

        var browserRequest = security.Validate(
            "/convert",
            "POST",
            "127.0.0.1:17654",
            ["Origin"],
            null,
            validAuthorization,
            "text/plain");
        browserRequest.Should().Be(new ServeRequestRejection(403, "cross_origin_forbidden"));

        var rebindingRequest = security.Validate(
            "/engines",
            "GET",
            "evil.example:17654",
            [],
            null,
            validAuthorization,
            null);
        rebindingRequest.Should().Be(new ServeRequestRejection(403, "forbidden_host"));

        var missingToken = security.Validate(
            "/convert",
            "POST",
            "127.0.0.1:17654",
            [],
            null,
            null,
            "application/json");
        missingToken.Should().Be(new ServeRequestRejection(401, "unauthorized"));
    }

    [Fact]
    public void ConvertRequests_RequireApplicationJsonWithOptionalParameters()
    {
        ServeRequestSecurity.IsJsonContentType("application/json").Should().BeTrue();
        ServeRequestSecurity.IsJsonContentType("Application/JSON; charset=utf-8").Should().BeTrue();
        ServeRequestSecurity.IsJsonContentType("text/plain").Should().BeFalse();
        ServeRequestSecurity.IsJsonContentType(null).Should().BeFalse();
    }
}
