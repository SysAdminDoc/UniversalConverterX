using FluentAssertions;
using UniversalConverterX.Core.Models;
using UniversalConverterX.Core.Utilities;

namespace UniversalConverterX.Core.Tests.Utilities;

public class PostConversionHandlerTests : IDisposable
{
    private readonly string _tempDir;

    public PostConversionHandlerTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "ucx-pch-tests-" + Guid.NewGuid().ToString("N")[..8]);
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        try { Directory.Delete(_tempDir, recursive: true); } catch { }
        GC.SuppressFinalize(this);
    }

    private string CreateFile(string name, string content = "test")
    {
        var path = Path.Combine(_tempDir, name);
        var dir = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(dir))
            Directory.CreateDirectory(dir);
        File.WriteAllText(path, content);
        return path;
    }

    #region ResolveAction

    [Fact]
    public void ResolveAction_ExplicitDelete_ReturnsDelete()
    {
        var opts = new ConversionOptions { PostConversionAction = PostConversionAction.Delete };
        PostConversionHandler.ResolveAction(opts).Should().Be(PostConversionAction.Delete);
    }

    [Fact]
    public void ResolveAction_ExplicitMove_ReturnsMove()
    {
        var opts = new ConversionOptions { PostConversionAction = PostConversionAction.Move };
        PostConversionHandler.ResolveAction(opts).Should().Be(PostConversionAction.Move);
    }

    [Fact]
    public void ResolveAction_LegacyDeleteTrue_FallsBackToDelete()
    {
        var opts = new ConversionOptions { DeleteSourceOnSuccess = true };
        PostConversionHandler.ResolveAction(opts).Should().Be(PostConversionAction.Delete);
    }

    [Fact]
    public void ResolveAction_ExplicitMoveOverridesLegacyDelete()
    {
        var opts = new ConversionOptions
        {
            PostConversionAction = PostConversionAction.Move,
            DeleteSourceOnSuccess = true
        };
        PostConversionHandler.ResolveAction(opts).Should().Be(PostConversionAction.Move);
    }

    [Fact]
    public void ResolveAction_DefaultsToKeep()
    {
        var opts = new ConversionOptions();
        PostConversionHandler.ResolveAction(opts).Should().Be(PostConversionAction.Keep);
    }

    #endregion

    #region Execute — Keep

    [Fact]
    public void Execute_Keep_LeavesSourceUntouched()
    {
        var source = CreateFile("input.mp4");
        var output = CreateFile("output.mp4");

        var result = PostConversionHandler.Execute(source, output, PostConversionAction.Keep);

        result.Success.Should().BeTrue();
        result.Action.Should().Be(PostConversionAction.Keep);
        File.Exists(source).Should().BeTrue();
    }

    #endregion

    #region Execute — Delete

    [Fact]
    public void Execute_Delete_RemovesSourceFile()
    {
        var source = CreateFile("input.mp4");
        var output = CreateFile("output.mp4");

        var result = PostConversionHandler.Execute(source, output, PostConversionAction.Delete);

        result.Success.Should().BeTrue();
        result.Action.Should().Be(PostConversionAction.Delete);
        File.Exists(source).Should().BeFalse();
        File.Exists(output).Should().BeTrue();
    }

    [Fact]
    public void Execute_Delete_FailsWhenOutputMissing()
    {
        var source = CreateFile("input.mp4");
        var output = Path.Combine(_tempDir, "nonexistent-output.mp4");

        var result = PostConversionHandler.Execute(source, output, PostConversionAction.Delete);

        result.Success.Should().BeFalse();
        result.ErrorMessage.Should().Contain("Output file not found");
        File.Exists(source).Should().BeTrue();
    }

    [Fact]
    public void Execute_Delete_FailsWhenSourceMissing()
    {
        var source = Path.Combine(_tempDir, "nonexistent-input.mp4");
        var output = CreateFile("output.mp4");

        var result = PostConversionHandler.Execute(source, output, PostConversionAction.Delete);

        result.Success.Should().BeFalse();
        result.ErrorMessage.Should().Contain("Source file not found");
    }

    #endregion

    #region Execute — Move

    [Fact]
    public void Execute_Move_AbsoluteArchiveFolder()
    {
        var source = CreateFile("input.mp4");
        var output = CreateFile("output.mp4");
        var archive = Path.Combine(_tempDir, "archive");

        var result = PostConversionHandler.Execute(source, output,
            PostConversionAction.Move, archive);

        result.Success.Should().BeTrue();
        result.Action.Should().Be(PostConversionAction.Move);
        result.DestinationPath.Should().NotBeNullOrEmpty();
        File.Exists(source).Should().BeFalse();
        File.Exists(result.DestinationPath!).Should().BeTrue();
        Path.GetDirectoryName(result.DestinationPath)!.Should().StartWith(archive);
    }

    [Fact]
    public void Execute_Move_RelativeArchiveFolder()
    {
        var source = CreateFile("input.mp4");
        var output = CreateFile("output.mp4");

        var result = PostConversionHandler.Execute(source, output,
            PostConversionAction.Move, "_archived");

        result.Success.Should().BeTrue();
        var expectedDir = Path.Combine(_tempDir, "_archived");
        Path.GetDirectoryName(result.DestinationPath)!.Should().Be(expectedDir);
        File.Exists(source).Should().BeFalse();
    }

    [Fact]
    public void Execute_Move_HandlesCollisionInArchiveFolder()
    {
        var source = CreateFile("input.mp4");
        var output = CreateFile("output.mp4");
        var archive = Path.Combine(_tempDir, "archive");
        CreateFile(Path.Combine("archive", "input.mp4"), "existing");

        var result = PostConversionHandler.Execute(source, output,
            PostConversionAction.Move, archive);

        result.Success.Should().BeTrue();
        result.DestinationPath.Should().NotBe(Path.Combine(archive, "input.mp4"));
        File.Exists(result.DestinationPath!).Should().BeTrue();
    }

    [Fact]
    public void Execute_Move_FailsWhenNoArchiveFolder()
    {
        var source = CreateFile("input.mp4");
        var output = CreateFile("output.mp4");

        var result = PostConversionHandler.Execute(source, output,
            PostConversionAction.Move, archiveFolder: null);

        result.Success.Should().BeFalse();
        result.ErrorMessage.Should().Contain("no archive folder");
        File.Exists(source).Should().BeTrue();
    }

    [Fact]
    public void Execute_Move_FailsWhenOutputMissing()
    {
        var source = CreateFile("input.mp4");
        var output = Path.Combine(_tempDir, "missing-output.mp4");
        var archive = Path.Combine(_tempDir, "archive");

        var result = PostConversionHandler.Execute(source, output,
            PostConversionAction.Move, archive);

        result.Success.Should().BeFalse();
        File.Exists(source).Should().BeTrue();
    }

    #endregion

    #region Execute — Safety

    [Fact]
    public void Execute_Keep_PropagatesMarkOfTheWebToOutput()
    {
        if (!OperatingSystem.IsWindows())
            return;

        var source = CreateFile("downloaded.docx");
        var output = CreateFile("converted.pdf");
        const string zoneIdentifier = "[ZoneTransfer]\r\nZoneId=3\r\nReferrerUrl=https://example.test/file\r\n";
        File.WriteAllText(source + ":Zone.Identifier", zoneIdentifier);

        var result = PostConversionHandler.Execute(
            source,
            output,
            PostConversionAction.Keep);

        result.Success.Should().BeTrue();
        File.ReadAllText(output + ":Zone.Identifier").Should().Be(zoneIdentifier);
    }

    [Fact]
    public void PropagateMarkOfTheWeb_WhenSourceIsUnmarked_IsSuccessfulNoOp()
    {
        var source = CreateFile("local.docx");
        var output = CreateFile("local.pdf");

        var result = PostConversionHandler.PropagateMarkOfTheWeb(source, output);

        result.Success.Should().BeTrue();
        result.SourceMarked.Should().BeFalse();
    }

    [Fact]
    public void Execute_RefusesToDeleteWhenSourceIsOutput()
    {
        var samePath = CreateFile("same.mp4");

        var result = PostConversionHandler.Execute(samePath, samePath, PostConversionAction.Delete);

        result.Success.Should().BeTrue();
        result.Action.Should().Be(PostConversionAction.Keep);
        File.Exists(samePath).Should().BeTrue();
    }

    [Fact]
    public void Execute_RefusesToMoveWhenSourceIsOutput()
    {
        var samePath = CreateFile("same.mp4");
        var archive = Path.Combine(_tempDir, "archive");

        var result = PostConversionHandler.Execute(samePath, samePath,
            PostConversionAction.Move, archive);

        result.Success.Should().BeTrue();
        result.Action.Should().Be(PostConversionAction.Keep);
        File.Exists(samePath).Should().BeTrue();
    }

    #endregion
}
