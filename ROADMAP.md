# UniversalConverterX — Product Roadmap

**Status:** v2.29.0 · 211 sidecar engines · 299+ presets · 45+ UI pages
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

## Tier 2 — Next _(v2.23–v2.27)_

### 148. Commercial / Ad Detection (Comskip)

Add a local, non-destructive commercial-detection workflow that accepts a
user-provisioned Comskip executable or a UCX-built binary from a pinned,
license-reviewed source recipe. Emit EDL and chapter metadata, optionally
export detected keep ranges atomically through FFmpeg, and never fetch an
unverified Windows binary. Acceptance requires source and frozen sidecar
contract tests plus a reproducible synthetic fixture.

Impact: 2 · Effort: 2 · Type: optional external engine

### 149. Community Preset Repository

Ship a SysAdminDoc-owned, versioned catalog in this repository with explicit
review, license, takedown, revocation, checksum, and immutable-publication
rules. Add a user-initiated client that previews the exact engine and
arguments, validates the preset locally, verifies SHA-256, installs atomically,
and never auto-updates installed presets. Acceptance requires offline catalog
and tamper/revocation tests.

Impact: 3 · Effort: 3 · Type: ecosystem

## Tier 3 — Later _(v2.27+)_

### 44. Blu-ray Authoring (Disc Tools residual)

Complete single-title BDMV authoring through a pinned, license-compatible
Windows backend with a reproducible build or verified immutable distribution
path. Reuse the existing Disc Tools ISO/write boundary, preserve an inspectable
BDMV folder, and prove the workflow headlessly with a synthetic input and
filesystem/playlist inspection before exposing it as ready.

Impact: 2 · Effort: 4 · Type: parity

### 66-a. Guarded FFmpeg 8.1 D3D12 Zero-Copy Pipeline

Wire D3D12 decode, `scale_d3d12`, optional `deinterlace_d3d12`, and D3D12
encode into VideoCrush behind an explicit opt-in. Probe the requested pipeline
before the real job and automatically fall back to the existing portable path
when any device/filter/encoder stage is unavailable. Acceptance requires
argument-planning tests and a headless fallback smoke on the available GPU;
successful zero-copy execution on supported hardware remains Item 66's device
validation residual.

Impact: 3 · Effort: 2 · Type: platform + leapfrog

### 47-a. ARM64 Publish and QNN Readiness

Add a repeatable `win-arm64` publish path, audit bundled sidecars and native
dependencies for architecture compatibility, and expose a local QNN capability
probe that fails closed when the provider/runtime is absent. Acceptance
requires headless ARM64 publish artifact inspection and provider-probe tests;
actual QNN inference and WinUI rendering remain Item 47's Snapdragon hardware
validation residual.

Impact: 2 · Effort: 4 · Type: platform

## Under Consideration
