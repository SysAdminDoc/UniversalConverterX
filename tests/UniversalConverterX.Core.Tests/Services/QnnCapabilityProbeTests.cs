using System.Runtime.InteropServices;
using FluentAssertions;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class QnnCapabilityProbeTests
{
    [Fact]
    public void Assess_RequiresArm64OperatingSystem()
    {
        var report = QnnCapabilityProbe.Assess(
            Architecture.X64, Architecture.X64, "AMD64", "1.25.1",
            ["QNNExecutionProvider", "CPUExecutionProvider"]);

        report.Ready.Should().BeFalse();
        report.Status.Should().Be(QnnProbeStatus.NotArm64);
    }

    [Fact]
    public void Assess_RequiresArm64Python()
    {
        var report = QnnCapabilityProbe.Assess(
            Architecture.Arm64, Architecture.Arm64, "AMD64", "1.25.1",
            ["QNNExecutionProvider", "CPUExecutionProvider"]);

        report.Ready.Should().BeFalse();
        report.Status.Should().Be(QnnProbeStatus.WrongPythonArchitecture);
    }

    [Fact]
    public void Assess_FailsClosedWithoutQnnProvider()
    {
        var report = QnnCapabilityProbe.Assess(
            Architecture.Arm64, Architecture.Arm64, "ARM64", "1.25.1",
            ["CPUExecutionProvider"]);

        report.Ready.Should().BeFalse();
        report.Status.Should().Be(QnnProbeStatus.ProviderUnavailable);
    }

    [Fact]
    public void Assess_ReportsReadyOnlyForArm64QnnCombination()
    {
        var report = QnnCapabilityProbe.Assess(
            Architecture.Arm64, Architecture.Arm64, "aarch64", "1.25.1",
            ["QNNExecutionProvider", "CPUExecutionProvider"]);

        report.Ready.Should().BeTrue();
        report.Status.Should().Be(QnnProbeStatus.Ready);
        report.Providers.Should().Equal("CPUExecutionProvider", "QNNExecutionProvider");
    }

    [Fact]
    public void Assess_ReportsRuntimeImportFailureBeforeProviderClaims()
    {
        var report = QnnCapabilityProbe.Assess(
            Architecture.Arm64, Architecture.Arm64, "ARM64", null, [],
            "ModuleNotFoundError: onnxruntime");

        report.Ready.Should().BeFalse();
        report.Status.Should().Be(QnnProbeStatus.RuntimeUnavailable);
    }
}
