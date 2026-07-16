# UCX Conversion Presets

Each `.preset.xml` file in this folder is a named conversion recipe that the
shell extension exposes as a right-click menu item, and that the CLI runs
via `ucx convert-preset --preset "<Name>" <file>...`.

## Schema

```xml
<?xml version="1.0" encoding="utf-8"?>
<Preset xmlns="https://universalconverterx.io/preset/v1">
    <!-- The text shown in the right-click submenu. Required. -->
    <Name>To MP4 (H.264 1080p)</Name>

    <!-- Optional folder path in the right-click menu (forward-slash
         delimited; auto-creates submenus). Skip for top-level entries. -->
    <Folder>Video</Folder>

    <!-- Lowercase extensions (no dot). The preset only appears in the
         right-click menu when EVERY selected file matches one of these. -->
    <InputTypes>
        <Extension>mov</Extension>
        <Extension>mkv</Extension>
        <Extension>avi</Extension>
    </InputTypes>

    <!-- Output filename template:
           {stem}      = source filename without extension
           {dir}       = source directory
           {preset}    = preset name (sanitised for paths)
         The extension is appended automatically from <OutputExtension>. -->
    <OutputFileNameTemplate>{dir}/{stem}_h264-1080p</OutputFileNameTemplate>
    <OutputExtension>mp4</OutputExtension>

    <!-- Which UCX sidecar / engine handles this preset. -->
    <Engine>videocrush</Engine>

    <!-- Invocation mode -- two patterns for how the runner calls the sidecar:
         per-file       (default) one invocation per input;
                                  runner appends --input <f> --output <built>.
         batch-output-dir          one invocation for all inputs;
                                  runner appends --input <f1> <f2> ... --output-dir <d>.
         Use batch-output-dir for sidecars that already accept lists
         (docconvert / archive / subconvert / fontconvert / ebookconvert / ocr / pdftools.split). -->
    <InvocationMode>per-file</InvocationMode>

    <!-- Sidecar arguments. The runner appends --input / --output flags
         appropriate to the invocation mode; everything below is the shared
         portion. -->
    <Args>
        <Arg>--preset</Arg>
        <Arg>web-1080p</Arg>
        <Arg>--codec</Arg>
        <Arg>libx264</Arg>
    </Args>
</Preset>
```

## Engine catalogue

The `<Engine>` value selects a sidecar; `--input` and `--output` flags
are appended automatically. Common engines:

| Engine          | Purpose                                 |
|-----------------|-----------------------------------------|
| `videocrush`    | Video compression / preset transcode    |
| `clipforge`     | Trim / crop / rotate / loudnorm / rewrap / vmaf / timeline / track-* |
| `gifstudio`     | GIF generation (palettegen + paletteuse) |
| `heicshift`     | Image format conversion                  |
| `framesnap`     | Frame extraction                         |
| `rnnoise`       | Audio denoise (RNNoise / arnndn)         |
| `edge-tts`      | TTS                                      |
| `whisper-cpp`   | Speech-to-text                           |
| `parakeet-stt`  | CUDA Parakeet TDT v3 speech-to-text      |
| `docconvert`    | LibreOffice document conversion          |
| `archive`       | 7-Zip pack / unpack                      |
| `pdftools`      | PDF merge / split / rotate / etc.        |
| `subconvert`    | Subtitle conversion                      |
| `fontconvert`   | TTF / OTF / WOFF / WOFF2                 |
| `ebookconvert`  | Calibre eBook conversion                 |
| `ocr`           | Tesseract OCR                            |

## Where presets live

Search order at runtime:

1. `%LocalAppData%\UniversalConverterX\presets\` — user customisations
2. `%ProgramFiles%\UniversalConverterX\presets\` — installer-shipped defaults
3. `<repo>/presets/` — source-tree defaults (dev mode)

User presets override built-ins by `<Name>`.
