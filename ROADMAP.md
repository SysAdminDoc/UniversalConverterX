# UniversalConverterX — Product Roadmap

**Status:** v2.31.4 · 212 sidecar engines · 300+ presets · 53 UI pages
**Last updated:** 2026-07-17

Blocked items live in [`Roadmap_Blocked.md`](Roadmap_Blocked.md).
Shipped work is recorded in [`CHANGELOG.md`](CHANGELOG.md).

**Design charter:** Offline-first. No cloud. No accounts. No telemetry.
Windows 10 21H2+. Beat every competitor on: format coverage, batch UX,
programmability (CLI + REST + PS module), and AI depth.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| **Now** | Ship next (v2.21–v2.22). High certainty, well-scoped. |
| **Next** | v2.23–v2.27 window. Design complete or dependencies blocked on Now items. |
| **Later** | v2.27+. Higher effort, lower urgency, or needs community signal. |
| **UC** | Under Consideration — needs more investigation before placement. |
| **Impact** | User value 1 (niche) – 5 (universal). |
| **Effort** | Engineering cost 1 (hours) – 5 (weeks of cross-cutting work). |

---

## Tier 1 — Now _(v2.21–v2.22)_

- [ ] P2 — Vips resize discards quality/strip/compression options
  Why: When a width/height is set, `BuildConversionArguments` calls `args.Clear()` and rebuilds a bare `thumbnail in out <size>` command, dropping every previously-selected `Q=`, `compression=`, `lossless=`, `effort=`, `strip=` option — so any resized output is default-quality with metadata intact, contradicting the user's settings. Needs the vips binary to verify the correct thumbnail save-option suffix syntax (`out.jpg[Q=80,strip]`).
  Where: src/UniversalConverterX.Core/Converters/VipsConverter.cs (~163-190)

## Tier 2 — Next _(v2.23–v2.27)_

- [ ] P3 — Downloads have no maximum-size cap
  Why: `DownloadFileAsync` streams the response body to disk unbounded; a compromised/mis-pinned GitHub asset for a non-checksum-required tool (resvg/vips/libjxl/libheif/imagemagick/potrace) can fill the disk before the post-download checksum runs. Reject `Content-Length` beyond a per-tool cap and abort the copy loop when exceeded.
  Where: src/UniversalConverterX.Core/Services/ToolDownloader.cs (~279-317)

- [ ] P3 — Sidecar subprocess calls lack per-call timeouts
  Why: ~114 `subprocess.run`/`Popen` calls across sidecars omit `timeout=`. The C# host silence-watchdog force-kills a stuck child only after ~10 min, and CLI/test invocations run without that watchdog at all. Per-call timeouts would fail stuck jobs in seconds with a clean error. DEBT.
  Where: tools/**/sidecar.py (subprocess calls operating on user files)

## Tier 3 — Later _(v2.27+)_

- [ ] P3 — LibreOffice output extension aliasing not reconciled
  Why: The relocation fix keys on the requested extension, but LibreOffice writes the filter's native extension (e.g. requesting `.jpeg` yields `.jpg`, `.text` yields `.txt`), so alias mismatches still land beside the requested path. Enumerate the produced `<sourceStem>.*` and relocate the actual file.
  Where: src/UniversalConverterX.Core/Converters/LibreOfficeConverter.cs (ValidateSuccessfulOutput override)

- [ ] P3 — PathSafety does not neutralize Windows reserved device names
  Why: `SanitizeFileNameComponent` blocks separators/`..` but lets a stem resolve to `CON`/`NUL`/`PRN`/`COM1`… or a trailing dot/space through from untrusted metadata (EXIF/ID3/probe titles), which can make the downstream file create fail. Not a traversal escape — a failed write.
  Where: src/UniversalConverterX.Core/Utilities/PathSafety.cs (~60-70)

## Under Consideration
