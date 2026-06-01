# UniversalConverterX Research Report

This file is the current research synthesis. Historical phase and audit
artifacts are archived under [`docs/archive/`](docs/archive/) and
[`docs/research/`](docs/research/).

## Current Product Thesis

UniversalConverterX should remain an offline-first Windows conversion suite:
broad local format coverage, batch UX, programmable surfaces, and optional local
AI tooling without accounts, telemetry, or cloud processing. Its strongest
advantage is the shared NDJSON sidecar contract that lets specialized engines
plug into one shell, CLI, history, preset, and diagnostics model.

## What The Research Concluded

- Format-coverage waves A-X are complete; the roadmap focus shifted to UI
  wiring, batch reliability, platform/security hardening, developer experience,
  and distribution quality.
- Phase 3 gap analysis produced a realistic action set after filtering 150
  candidate features through charter fit, dependencies, effort, and impact.
- v2.21.0 closed the first two Phase 3 items: parallel job limit enforcement and
  DPAPI encryption infrastructure.
- The remaining roadmap should avoid rebuilding a cloud converter or account
  service; every feature should preserve local processing and explicit user
  control.

## Active Research Risks

- **Roadmap drift:** root roadmap, release notes, and phase artifacts have grown
  large enough that stale duplicate planning files need periodic consolidation.
- **Sidecar availability:** many wrappers discover upstream binaries at runtime;
  contract tests can pass while end-to-end user flows still need binaries on
  disk.
- **GPU/hardware acceleration:** vendor encoder and upscaler paths need clear
  capability probing, graceful fallback, and user-visible reason strings.
- **Security:** downloader cookies, external binary wrappers, and sidecar config
  need consistent DPAPI/encryption, redaction, and local-only diagnostics.
- **UI scale:** dozens of WinUI pages require consistent polish, accessibility,
  navigation, and AutomationId coverage as new engines are surfaced.

## Current Canonical Sources

- [`ROADMAP.md`](ROADMAP.md) - active roadmap.
- [`COMPLETED.md`](COMPLETED.md) - shipped feature summary.
- [`CHANGELOG.md`](CHANGELOG.md) - release-level evidence.
- [`docs/research/`](docs/research/) - audit and state-of-repo evidence.
- [`docs/archive/roadmap/`](docs/archive/roadmap/) - archived phase roadmap artifacts.
