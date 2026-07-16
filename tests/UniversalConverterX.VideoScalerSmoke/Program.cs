using System.Diagnostics;
using Microsoft.Graphics.Imaging;
using Microsoft.Windows.AI;
using Microsoft.Windows.AI.Video;
using Windows.Graphics.Imaging;

const int inputSize = 192;
const int outputSize = 384;
const int iterations = 12;

var readyState = VideoScaler.GetReadyState();
Console.WriteLine($"VideoScaler readiness: {readyState}");
if (readyState != AIFeatureReadyState.Ready)
{
    Console.WriteLine("SKIP: Windows AI VSR is optional; Real-ESRGAN remains the portable export backend.");
    return 0;
}

using var inputBitmap = new SoftwareBitmap(
    BitmapPixelFormat.Bgra8,
    inputSize,
    inputSize,
    BitmapAlphaMode.Ignore);
using var outputBitmap = new SoftwareBitmap(
    BitmapPixelFormat.Bgra8,
    outputSize,
    outputSize,
    BitmapAlphaMode.Ignore);
using var input = ImageBuffer.CreateForSoftwareBitmap(inputBitmap);
using var output = ImageBuffer.CreateForSoftwareBitmap(outputBitmap);
using var scaler = await VideoScaler.CreateAsync();
var options = new VideoScalerOptions();

var warmup = scaler.ScaleImageBuffer(input, output, options);
if (warmup.Status != VideoScalerStatus.Success)
{
    Console.Error.WriteLine($"FAIL: warm-up frame returned {warmup.Status}.");
    return 1;
}

var stopwatch = Stopwatch.StartNew();
for (var index = 0; index < iterations; index++)
{
    var result = scaler.ScaleImageBuffer(input, output, options);
    if (result.Status != VideoScalerStatus.Success)
    {
        Console.Error.WriteLine($"FAIL: frame {index + 1} returned {result.Status}.");
        return 1;
    }
}
stopwatch.Stop();

var averageMilliseconds = stopwatch.Elapsed.TotalMilliseconds / iterations;
Console.WriteLine(
    $"PASS: {iterations} BGRA frames {inputSize}x{inputSize} -> {outputSize}x{outputSize}; " +
    $"average {averageMilliseconds:F2} ms/frame.");
return 0;
