using CommunityToolkit.Mvvm.ComponentModel;

namespace UniversalConverterX.Core.ViewModels;

public sealed class BackgroundRemovalWorkflowViewModel : ObservableObject
{
    public string Model { get; set; } = "u2net";
    public string Format { get; set; } = "webm";
    public int Quality { get; set; } = 80;
    public int Edge { get; set; }
    public bool InvertMask { get; set; }
    public bool KeepAudio { get; set; } = true;
    public string? BackgroundColor { get; set; }
    public string? BackgroundImagePath { get; set; }

    public WorkflowInvocation BuildInvocation(string inputPath, string outputPath)
    {
        var arguments = new List<string>
        {
            "--input", inputPath, "--output", outputPath,
            "--model", Model, "--format", Format,
            "--quality", Math.Clamp(Quality, 1, 100).ToString(),
        };
        if (Edge > 0)
            arguments.AddRange(["--edge", Edge.ToString()]);
        if (InvertMask)
            arguments.Add("--invert");
        if (!KeepAudio)
            arguments.Add("--no-audio");
        if (!string.IsNullOrWhiteSpace(BackgroundColor))
            arguments.AddRange(["--bg-color", BackgroundColor.Trim()]);
        if (!string.IsNullOrWhiteSpace(BackgroundImagePath) && File.Exists(BackgroundImagePath))
            arguments.AddRange(["--bg-image", BackgroundImagePath]);
        return new WorkflowInvocation("alphacut", arguments, outputPath);
    }
}
