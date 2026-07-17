[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$SourceImage,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $SourceImage -PathType Leaf)) {
    throw "MSIX source image not found: $SourceImage"
}

Add-Type -AssemblyName System.Drawing
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$assets = [ordered]@{
    'StoreLogo.png' = @(50, 50)
    'Square44x44Logo.png' = @(44, 44)
    'Square150x150Logo.png' = @(150, 150)
    'SmallTile.png' = @(71, 71)
    'LargeTile.png' = @(310, 310)
    'Wide310x150Logo.png' = @(310, 150)
    'ImageIcon.png' = @(44, 44)
    'VideoIcon.png' = @(44, 44)
    'AudioIcon.png' = @(44, 44)
    'DocumentIcon.png' = @(44, 44)
}

$source = [System.Drawing.Image]::FromFile((Resolve-Path -LiteralPath $SourceImage))
try {
    foreach ($entry in $assets.GetEnumerator()) {
        $width = [int]$entry.Value[0]
        $height = [int]$entry.Value[1]
        $canvas = [System.Drawing.Bitmap]::new($width, $height)
        try {
            $graphics = [System.Drawing.Graphics]::FromImage($canvas)
            try {
                $graphics.Clear([System.Drawing.Color]::FromArgb(2, 6, 23))
                $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
                $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality

                $scale = [Math]::Min($width / $source.Width, $height / $source.Height)
                $drawWidth = [int][Math]::Round($source.Width * $scale)
                $drawHeight = [int][Math]::Round($source.Height * $scale)
                $left = [int](($width - $drawWidth) / 2)
                $top = [int](($height - $drawHeight) / 2)
                $graphics.DrawImage($source, $left, $top, $drawWidth, $drawHeight)
            } finally {
                $graphics.Dispose()
            }

            $outputPath = Join-Path $OutputDirectory $entry.Key
            $canvas.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
        } finally {
            $canvas.Dispose()
        }
    }
} finally {
    $source.Dispose()
}
