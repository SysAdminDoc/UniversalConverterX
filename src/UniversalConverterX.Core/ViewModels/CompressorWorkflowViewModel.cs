using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;

namespace UniversalConverterX.Core.ViewModels;

public enum CompressionWorkflowMode { Standard, TargetSize, Vmaf }

public sealed class CompressorWorkflowViewModel : ObservableObject
{
    private const double TargetSizeHeadroom = 0.95;
    public CompressionWorkflowMode Mode { get; set; }
    public string Preset { get; set; } = "web-1080p";
    public string HardwareAcceleration { get; set; } = "none";
    public bool D3D12Deinterlace { get; set; }
    public string TargetPreset { get; set; } = "discord-10mb";
    public double TargetMegabytes { get; set; } = 10;
    public string VmafEncoder { get; set; } = "libsvtav1";
    public double VmafTarget { get; set; } = 93;
    public string Engine => Mode == CompressionWorkflowMode.Vmaf ? "ab-av1" : "videocrush";

    public WorkflowInvocation BuildInvocation(string inputPath, string outputPath)
    {
        List<string> arguments;
        if (Mode == CompressionWorkflowMode.Vmaf)
        {
            arguments = [
                "auto-encode", "--input", inputPath, "--output", outputPath,
                "--encoder", VmafEncoder,
                "--target-vmaf", Math.Clamp(VmafTarget, 50, 100).ToString("0.##", CultureInfo.InvariantCulture),
                "--preset", EncoderPreset(VmafEncoder), "--verify-vmaf",
            ];
        }
        else
        {
            arguments = ["--input", inputPath, "--output", outputPath];
            if (Mode == CompressionWorkflowMode.TargetSize)
            {
                if (TargetPreset == "custom")
                {
                    var target = double.IsFinite(TargetMegabytes) && TargetMegabytes >= 1 ? TargetMegabytes : 10;
                    arguments.AddRange([
                        "--target-mb", (target * TargetSizeHeadroom).ToString("0.###", CultureInfo.InvariantCulture),
                        "--codec", "libx264", "--ffmpeg-preset", "slow",
                        "--resolution", "720p", "--audio-codec", "aac", "--audio-bitrate", "96",
                    ]);
                }
                else
                {
                    arguments.AddRange(["--preset", TargetPreset]);
                }
                arguments.AddRange(["--hwaccel", "none"]);
            }
            else
            {
                arguments.AddRange(["--preset", Preset, "--hwaccel", HardwareAcceleration]);
                if (HardwareAcceleration == "d3d12" && D3D12Deinterlace)
                    arguments.Add("--d3d12-deinterlace");
            }
        }
        return new WorkflowInvocation(Engine, arguments, outputPath);
    }

    public static string EncoderPreset(string encoder) => encoder switch
    {
        "libx265" => "medium",
        "libx264" => "slow",
        _ => "6",
    };
}
