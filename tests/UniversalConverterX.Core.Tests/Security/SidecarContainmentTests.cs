using System.Diagnostics;
using System.Runtime.InteropServices;
using FluentAssertions;
using UniversalConverterX.Core.Security;

namespace UniversalConverterX.Core.Tests.Security;

/// <summary>
/// Containment and output-boundary behaviour for the shared sidecar runner
/// (ROADMAP Item 153). Untrusted files reach 212 engines, so a reported output
/// path is untrusted data and a spawned child is untrusted work.
/// </summary>
public sealed class SidecarOutputBoundaryTests : IDisposable
{
    private readonly string _root = Path.Combine(
        Path.GetTempPath(), "ucx-boundary-" + Guid.NewGuid().ToString("N"));

    public SidecarOutputBoundaryTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); } catch { }
    }

    [Fact]
    public void ApprovedRoot_ComesFromTheOutputFlagTheAppItselfPassed()
    {
        var destination = Path.Combine(_root, "out", "clip.mp4");
        SidecarOutputBoundary
            .ResolveApprovedRoot(["--input", "a.mkv", "--output", destination])
            .Should().Be(Path.GetFullPath(Path.Combine(_root, "out")));
    }

    [Fact]
    public void ApprovedRoot_HandlesTheEqualsFormAndDirectoryDestinations()
    {
        var directory = Path.Combine(_root, "frames");
        Directory.CreateDirectory(directory);
        SidecarOutputBoundary
            .ResolveApprovedRoot([$"--output-dir={directory}"])
            .Should().Be(Path.GetFullPath(directory));
    }

    [Fact]
    public void ApprovedRoot_IsNullWhenNoDestinationWasNamed()
    {
        SidecarOutputBoundary
            .ResolveApprovedRoot(["--input", "a.mkv", "--probe"])
            .Should().BeNull();
    }

    [Fact]
    public void OutputInsideTheApprovedDestinationIsAllowedAndCanonicalized()
    {
        var destination = Path.Combine(_root, "out");
        Directory.CreateDirectory(destination);
        var reported = Path.Combine(destination, ".", "clip.mp4");
        File.WriteAllText(Path.Combine(destination, "clip.mp4"), "x");

        var result = SidecarOutputBoundary.Validate(reported, destination);

        result.IsAllowed.Should().BeTrue();
        result.CanonicalPath.Should().Be(Path.Combine(destination, "clip.mp4"));
    }

    [Fact]
    public void TraversalOutOfTheApprovedDestinationIsRejected()
    {
        var destination = Path.Combine(_root, "out");
        Directory.CreateDirectory(destination);

        var result = SidecarOutputBoundary.Validate(
            Path.Combine(destination, "..", "..", "escaped.mp4"),
            destination);

        result.IsAllowed.Should().BeFalse();
        result.CanonicalPath.Should().BeNull();
        result.Rejection.Should().Contain("outside the approved destination");
    }

    [Fact]
    public void AnAbsolutePathElsewhereIsRejected()
    {
        var destination = Path.Combine(_root, "out");
        Directory.CreateDirectory(destination);

        var result = SidecarOutputBoundary.Validate(
            Path.Combine(Path.GetTempPath(), "somewhere-else.mp4"),
            destination);

        result.IsAllowed.Should().BeFalse();
        result.Rejection.Should().Contain("outside the approved destination");
    }

    [Fact]
    public void EmptyReportedPathIsRejected()
    {
        SidecarOutputBoundary.Validate("   ", _root).IsAllowed.Should().BeFalse();
    }

    [Fact]
    public void WithoutAnApprovedRootThePathIsMerelyCanonicalized()
    {
        var result = SidecarOutputBoundary.Validate(
            Path.Combine(_root, ".", "probe.json"),
            approvedRoot: null);

        result.IsAllowed.Should().BeTrue();
        result.CanonicalPath.Should().Be(Path.Combine(_root, "probe.json"));
    }

    [Fact]
    public void ADirectorySymlinkInsideTheDestinationIsRejected()
    {
        var destination = Path.Combine(_root, "out");
        var outside = Path.Combine(_root, "outside");
        Directory.CreateDirectory(destination);
        Directory.CreateDirectory(outside);

        var link = Path.Combine(destination, "link");
        try
        {
            Directory.CreateSymbolicLink(link, outside);
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException)
        {
            // Creating links needs Developer Mode or elevation. Skipping keeps
            // the suite honest on a locked-down box; the traversal and absolute
            // cases above still cover the boundary itself.
            return;
        }

        File.WriteAllText(Path.Combine(outside, "clip.mp4"), "x");
        var result = SidecarOutputBoundary.Validate(
            Path.Combine(link, "clip.mp4"),
            destination);

        result.IsAllowed.Should().BeFalse();
        result.Rejection.Should().Contain("link or junction");
    }

    [Fact]
    public void AFileSymlinkInsideTheDestinationIsRejected()
    {
        var destination = Path.Combine(_root, "out2");
        Directory.CreateDirectory(destination);
        var target = Path.Combine(_root, "real.mp4");
        File.WriteAllText(target, "x");

        var link = Path.Combine(destination, "clip.mp4");
        try
        {
            File.CreateSymbolicLink(link, target);
        }
        catch (Exception exception) when (
            exception is IOException or UnauthorizedAccessException)
        {
            return;
        }

        var result = SidecarOutputBoundary.Validate(link, destination);

        result.IsAllowed.Should().BeFalse();
        result.Rejection.Should().Contain("link or junction");
    }
}

public sealed class SidecarWorkspaceTests
{
    [Fact]
    public void WorkspaceIsPrivateAndDeletedWhenTheJobEnds()
    {
        string path;
        using (var workspace = SidecarWorkspace.Create())
        {
            path = workspace.Path;
            Directory.Exists(path).Should().BeTrue();
            File.WriteAllText(Path.Combine(path, "frame-0001.png"), "x");
            Directory.CreateDirectory(Path.Combine(path, "nested"));
        }

        Directory.Exists(path).Should().BeFalse(
            "an engine's scratch work must not outlive its job");
    }

    [Fact]
    public void TwoJobsNeverShareAWorkspace()
    {
        using var first = SidecarWorkspace.Create();
        using var second = SidecarWorkspace.Create();
        first.Path.Should().NotBe(second.Path);
        first.Root.Should().Be(second.Root);
    }

    [Fact]
    public void ChildProcessTempVariablesPointAtTheWorkspace()
    {
        using var workspace = SidecarWorkspace.Create();
        var startInfo = new ProcessStartInfo();
        workspace.ApplyTo(startInfo.EnvironmentVariables);

        startInfo.EnvironmentVariables["TMP"].Should().Be(workspace.Path);
        startInfo.EnvironmentVariables["TEMP"].Should().Be(workspace.Path);
        startInfo.EnvironmentVariables["UCX_JOB_TEMP"].Should().Be(workspace.Path);
    }

    [Fact]
    public void PurgeStaleReclaimsAbandonedWorkspacesButSparesLiveOnes()
    {
        var baseDirectory = Path.Combine(
            Path.GetTempPath(), "ucx-purge-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(baseDirectory);
        try
        {
            using var live = SidecarWorkspace.Create(baseDirectory);
            var abandoned = Path.Combine(live.Root, "abandoned");
            Directory.CreateDirectory(abandoned);
            Directory.SetLastWriteTimeUtc(abandoned, DateTime.UtcNow.AddDays(-3));

            SidecarWorkspace.PurgeStale(TimeSpan.FromDays(1), baseDirectory)
                .Should().Be(1);

            Directory.Exists(abandoned).Should().BeFalse();
            Directory.Exists(live.Path).Should().BeTrue(
                "a workspace younger than the cutoff may still belong to a running job");
        }
        finally
        {
            try { Directory.Delete(baseDirectory, recursive: true); } catch { }
        }
    }
}

public sealed class ProcessContainmentTests
{
    [Fact]
    public void LimitsCarryAMemoryCeilingByDefault()
    {
        ProcessContainmentLimits.Default.MaxProcesses.Should().BeGreaterThan(0);
        ProcessContainmentLimits.Default.MaxMemoryBytes.Should().BeGreaterThan(0);
        ProcessContainmentLimits.Default.MaxRuntime.Should().Be(TimeSpan.Zero,
            "a hard clock would kill a legitimate long encode; the silence watchdog paces runs");
    }

    [Fact]
    public void ContainmentActivatesOnWindows()
    {
        using var containment = ProcessContainment.Create(ProcessContainmentLimits.Default);

        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            containment.IsActive.Should().BeTrue(containment.FailureReason);
            containment.FailureReason.Should().BeNull();
        }
        else
        {
            containment.IsActive.Should().BeFalse();
            containment.FailureReason.Should().NotBeNull();
        }
    }

    [Fact]
    public void ClosingTheJobKillsTheContainedProcessTree()
    {
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            return;
        }

        // `ping -n` rather than `timeout`, which refuses to run at all when
        // stdin is redirected and would let this test pass without the job ever
        // killing anything. cmd is the child; ping is the grandchild, which is
        // the process an orphan-leak would actually strand.
        var priorGrandchildren = LivePingProcessIds();
        using var process = Process.Start(new ProcessStartInfo
        {
            FileName = "cmd.exe",
            Arguments = "/c ping -n 200 127.0.0.1",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
        });
        process.Should().NotBeNull();

        var containment = ProcessContainment.Create(ProcessContainmentLimits.Default);
        int[] grandchildren;
        try
        {
            containment.TryAssign(process!.Handle).Should().BeTrue(containment.FailureReason);

            // The tree must be genuinely alive before the job closes, otherwise
            // the assertions below would hold for a process that died on its own.
            grandchildren = WaitForNewPingProcesses(priorGrandchildren);
            process.HasExited.Should().BeFalse(
                "the contained child must still be running before the job is closed");
            grandchildren.Should().NotBeEmpty(
                "the child must have spawned a grandchild for tree containment to mean anything");
        }
        catch
        {
            try { process!.Kill(entireProcessTree: true); } catch { }
            containment.Dispose();
            throw;
        }

        // Closing the last job handle must terminate everything inside it. This
        // is the property that keeps an orphaned encoder from surviving the app.
        containment.Dispose();

        process!.WaitForExit(TimeSpan.FromSeconds(15)).Should().BeTrue(
            "closing a KILL_ON_JOB_CLOSE job must terminate the child");
        WaitForExit(grandchildren, TimeSpan.FromSeconds(15)).Should().BeTrue(
            "closing the job must terminate the grandchild too, not just the direct child");
    }

    private static int[] LivePingProcessIds()
    {
        try
        {
            return [.. Process.GetProcessesByName("PING").Select(process => process.Id)];
        }
        catch
        {
            return [];
        }
    }

    private static int[] WaitForNewPingProcesses(int[] before)
    {
        var known = before.ToHashSet();
        var deadline = DateTime.UtcNow + TimeSpan.FromSeconds(10);
        while (DateTime.UtcNow < deadline)
        {
            var fresh = LivePingProcessIds().Where(id => !known.Contains(id)).ToArray();
            if (fresh.Length > 0)
            {
                return fresh;
            }
            Thread.Sleep(50);
        }

        return [];
    }

    private static bool WaitForExit(int[] processIds, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            var alive = processIds.Count(id =>
            {
                try
                {
                    using var process = Process.GetProcessById(id);
                    return !process.HasExited;
                }
                catch (ArgumentException)
                {
                    return false;
                }
            });
            if (alive == 0)
            {
                return true;
            }
            Thread.Sleep(50);
        }

        return false;
    }

    [Fact]
    public void AssignmentIsRefusedOnceTheJobIsDisposed()
    {
        var containment = ProcessContainment.Create(ProcessContainmentLimits.Default);
        containment.Dispose();

        var act = () => containment.TryAssign(new IntPtr(1));
        act.Should().Throw<ObjectDisposedException>();
    }
}
