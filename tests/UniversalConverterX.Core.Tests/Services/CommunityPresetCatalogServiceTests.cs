using FluentAssertions;
using UniversalConverterX.Core.Services;

namespace UniversalConverterX.Core.Tests.Services;

public sealed class CommunityPresetCatalogServiceTests : IDisposable
{
    private readonly string _tempRoot = Path.Combine(
        Path.GetTempPath(), "ucx-community-catalog-tests", Guid.NewGuid().ToString("N"));
    private readonly CommunityPresetCatalogService _service = new();

    [Fact]
    public void RepositoryCatalog_LoadsAndPreviewsExactEngineArguments()
    {
        var catalogPath = Path.Combine(FindRepositoryRoot(), "community-presets", "catalog.json");

        var loaded = _service.Load(catalogPath);
        var preview = _service.Preview(catalogPath, "community-h264-720p-compact");

        loaded.Succeeded.Should().BeTrue(string.Join("; ", loaded.Errors));
        loaded.Catalog!.Operator.Should().Be("SysAdminDoc");
        preview.Valid.Should().BeTrue(string.Join("; ", preview.Errors));
        preview.Engine.Should().Be("videocrush");
        preview.Arguments.Should().ContainInOrder("--crf", "24", "--resolution", "720p");
        preview.ActualSha256.Should().Be(preview.ExpectedSha256);
    }

    [Fact]
    public void Preview_RejectsTamperedPayload()
    {
        var catalogPath = CopyCatalog();
        var payloadPath = Path.Combine(_tempRoot, "presets", "community-h264-720p-compact.preset.xml");
        File.AppendAllText(payloadPath, "<!-- tampered -->");

        var preview = _service.Preview(catalogPath, "community-h264-720p-compact");

        preview.Valid.Should().BeFalse();
        preview.Errors.Should().Contain(error => error.Contains("SHA-256 mismatch", StringComparison.Ordinal));
    }

    [Fact]
    public void Preview_RejectsRevokedDigest()
    {
        var catalogPath = CopyCatalog();
        var catalog = File.ReadAllText(catalogPath);
        catalog = catalog.Replace(
            "\"revocations\": []",
            "\"revocations\": [{\"id\":\"community-h264-720p-compact\",\"sha256\":\"942c66f5dcb4f2174283946d6f8ed1bb6f712ef9d9b059e831e571f8c8f50c32\",\"reason\":\"acceptance test\",\"revokedAt\":\"2026-07-17\"}]");
        File.WriteAllText(catalogPath, catalog);

        var preview = _service.Preview(catalogPath, "community-h264-720p-compact");

        preview.Valid.Should().BeFalse();
        preview.Revoked.Should().BeTrue();
        preview.Errors.Should().Contain(error => error.Contains("revoked", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Install_RequiresExactAcceptanceAndNeverOverwrites()
    {
        var catalogPath = CopyCatalog();
        var destination = Path.Combine(_tempRoot, "installed");

        var refused = _service.Install(
            catalogPath, "community-h264-720p-compact", destination, new string('0', 64));
        refused.Succeeded.Should().BeFalse();

        var installed = _service.Install(
            catalogPath, "community-h264-720p-compact", destination,
            "942c66f5dcb4f2174283946d6f8ed1bb6f712ef9d9b059e831e571f8c8f50c32");
        installed.Succeeded.Should().BeTrue(string.Join("; ", installed.Errors));
        installed.AlreadyInstalled.Should().BeFalse();
        File.Exists(installed.InstalledPath).Should().BeTrue();

        var idempotent = _service.Install(
            catalogPath, "community-h264-720p-compact", destination,
            "942c66f5dcb4f2174283946d6f8ed1bb6f712ef9d9b059e831e571f8c8f50c32");
        idempotent.Succeeded.Should().BeTrue();
        idempotent.AlreadyInstalled.Should().BeTrue();

        File.WriteAllText(installed.InstalledPath!, "different local preset");
        var overwrite = _service.Install(
            catalogPath, "community-h264-720p-compact", destination,
            "942c66f5dcb4f2174283946d6f8ed1bb6f712ef9d9b059e831e571f8c8f50c32");
        overwrite.Succeeded.Should().BeFalse();
        File.ReadAllText(installed.InstalledPath!).Should().Be("different local preset");
    }

    [Fact]
    public void Preview_RejectsCatalogPathTraversal()
    {
        var catalogPath = CopyCatalog();
        var catalog = File.ReadAllText(catalogPath).Replace(
            "presets/community-h264-720p-compact.preset.xml", "../outside.preset.xml");
        File.WriteAllText(catalogPath, catalog);

        var preview = _service.Preview(catalogPath, "community-h264-720p-compact");

        preview.Valid.Should().BeFalse();
        preview.Errors.Should().Contain(error => error.Contains("escapes", StringComparison.Ordinal));
    }

    private string CopyCatalog()
    {
        var source = Path.Combine(FindRepositoryRoot(), "community-presets");
        Directory.CreateDirectory(Path.Combine(_tempRoot, "presets"));
        File.Copy(Path.Combine(source, "catalog.json"), Path.Combine(_tempRoot, "catalog.json"));
        File.Copy(Path.Combine(source, "policy.json"), Path.Combine(_tempRoot, "policy.json"));
        File.Copy(
            Path.Combine(source, "presets", "community-h264-720p-compact.preset.xml"),
            Path.Combine(_tempRoot, "presets", "community-h264-720p-compact.preset.xml"));
        return Path.Combine(_tempRoot, "catalog.json");
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "ROADMAP.md")))
                return directory.FullName;
            directory = directory.Parent;
        }
        throw new DirectoryNotFoundException("Repository root not found.");
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempRoot))
            Directory.Delete(_tempRoot, recursive: true);
    }
}
