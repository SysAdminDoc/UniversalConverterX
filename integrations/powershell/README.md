# UniversalConverterX PowerShell module

PowerShell 5.1+ cmdlets that wrap the `ucx` CLI and the bundled sidecar
binaries for sysadmin batch workflows.

## Install (developer / repo checkout)

```powershell
Import-Module .\integrations\powershell\UniversalConverterX.psm1 -Force
```

## Install (release bundle)

Drop the `integrations\powershell` folder into one of:

| Path                                                                             | Scope        |
|----------------------------------------------------------------------------------|--------------|
| `C:\Program Files\WindowsPowerShell\Modules\UniversalConverterX\`                | All users    |
| `$HOME\Documents\WindowsPowerShell\Modules\UniversalConverterX\`                 | Current user |

Then:

```powershell
Import-Module UniversalConverterX
Test-Ucx
```

## Resolution order for the UCX install root

1. `$env:UCX_HOME` -- explicit override
2. The directory containing the running PowerShell module (auto-detected when run from the repo)
3. `C:\Program Files\UniversalConverterX`
4. `%LocalAppData%\UniversalConverterX`

Override at any time:

```powershell
$env:UCX_HOME = 'D:\Tools\UniversalConverterX'
Get-UcxRoot
```

## Cmdlets

| Cmdlet                | Wraps                                | Purpose                                                  |
|-----------------------|--------------------------------------|----------------------------------------------------------|
| `Get-UcxRoot`         | --                                   | Resolve install root                                     |
| `Get-UcxExe`          | --                                   | Locate `ucx.exe`                                         |
| `Get-UcxSidecar`      | --                                   | Locate any built sidecar (`videocrush`, `clipforge`, ...) |
| `Test-Ucx`            | --                                   | Smoke test the install                                   |
| `Convert-MediaFile`   | `ucx.exe convert`                    | Pipeline-friendly format conversion                      |
| `Compress-MediaFile`  | `tools\videocrush\dist\videocrush.exe` | CRF, target-MB, preset (incl. ProRes/DNxHR/FFV1)       |
| `Get-MediaInfo`       | `ffprobe`                            | Returns a structured `[PSCustomObject]`                  |
| `Watch-MediaFolder`   | `FileSystemWatcher`                  | Auto-convert / auto-compress on file arrival             |

## Examples

### Convert a folder of MOVs to MP4

```powershell
Get-ChildItem .\source\*.mov |
    Convert-MediaFile -OutputFormat mp4 -OutputDirectory .\converted
```

### Compress to a Discord-friendly 9 MB

```powershell
Compress-MediaFile -Path .\big.mp4 -TargetMb 9 -Codec libx264
```

### Re-encode for an editing timeline (ProRes 422 HQ)

```powershell
Compress-MediaFile -Path .\camera.mov -Preset prores-422-hq -Output .\edit.prores.mov
```

### Probe metadata

```powershell
Get-MediaInfo .\source.mp4 | Select-Object Width, Height, Duration, VideoCodec
```

### Watch an inbox folder and convert as new files arrive

```powershell
Watch-MediaFolder -Path D:\incoming -Action Convert -OutputFormat mp4
```

```powershell
Watch-MediaFolder -Path D:\incoming -Action Compress -Preset web-1080p
```

Press Ctrl+C to stop the watcher.

## NDJSON event handling

`Compress-MediaFile` (and any future cmdlet that calls `Invoke-UcxNdjson`)
parses the NDJSON event stream emitted by UCX sidecars:

| Event       | Behavior                                       |
|-------------|------------------------------------------------|
| `progress`  | Surfaces as `Write-Progress` (percent + stage) |
| `log`       | `warn`/`error` -> `Write-Warning`; rest -> `Write-Verbose` |
| `error`     | `Write-Error "UCX error [code]: message"`      |
| (other)     | Forwarded to the pipeline as a PSObject        |

This means you can pipe `Compress-MediaFile` output into `Where-Object` to
filter on domain events emitted by individual sidecars (`format`, `voice`,
`chapter`, etc.).
