# UCX Factory Iteration — Phase 0 Repo Recon

**Run:** factory loop, single-session, Large-Repo Mode
**Date:** 2026-05-01
**Baseline:** v2.20.1 @ 4c84cb8 (main, clean)

## State summary

| Metric | Value | Source |
|--------|-------|--------|
| Version | 2.20.1 | `Directory.Build.props`, csproj, README badge |
| Tracked files | 1,315 | `git ls-files \| wc -l` |
| C# LOC | 28,571 | `find src -name '*.cs' \| xargs wc -l` |
| Source files (cs/xaml/py/ps1/md) | 1,086 | git ls-files filter |
| UI pages | 45+ | `src/UniversalConverterX.UI/Views/Pages/` count |
| Sidecar engines | 176 | per CLAUDE.md v2.20.1 entry |
| Presets | 274 | per ROADMAP header |
| ROADMAP unchecked items | 50 | `ROADMAP.md` Tier 1/2/3 + UC items |
| Build path | VS MSBuild (NOT bare dotnet) | per `ucx-build-path.md` memory |
| Working tree | clean | `git status --porcelain` empty |
| AI references in history | 0 | grep over `git log --all` |
| AI files committed | 0 | gitignore covers CLAUDE.md / .claude/ / CODEX_CHANGELOG.md |

## Stack

- C# / .NET 10 / WinUI 3 (Microsoft.WindowsAppSDK 1.7.250606001)
- CommunityToolkit.Mvvm + Microsoft.Extensions.DependencyInjection
- Python 3 sidecars under `tools/<engine>/` with PyInstaller-frozen distribution
- NDJSON CLI contract for sidecars (`progress`/`log`/`complete`/`error` events)

## Why no full L1 external research this iteration

ROADMAP.md was rebuilt 7 commits ago (commit `4c84cb8` — "ROADMAP: Round 2 research — 8 new items, 11 new sources (50 items total, 38 sources)"). Phase 1-4 outputs are still warm; the Tier 1 Now bucket has 11 well-scoped items with sources [S1]–[S38]. Re-running Phase 1 (30-60 distinct sources floor) on a delta-mode pass would be wasted effort against fresh data. **Phase 5 self-audit was not committed** — flagged for next iteration but not gating this run.

This iteration consumes the existing scored ROADMAP rather than expanding it. Large-Repo Mode rotation (1 iteration, 3 tasks) further reinforces "ship from existing scored work" over "re-research".

## Selected tasks

Three Tier 1 Now items chosen for Impact*1/Effort and atomic-commit independence:

1. **Item 4** — Output Filename Collision Protection (Impact 5, Effort 1, Type: parity)
2. **Item 8** — Parallel Job Limit Setting (Impact 3, Effort 1, Type: parity)
3. **Item 11** — CI Sidecar Contract Test Gate (Impact 3, Effort 1, Type: dx)

Rationale: high-impact, low-blast-radius, no shared coupling — three independent commits possible.
Items deferred to next run: 1 (AiLab UI wiring, multi-page), 2 (AudioCompressor page), 3 (Batch Rename — needs UX design pass), 5 (Output Filename Template DSL — depends on Item 4 first), 6 (HistoryPage — already partially shipped per v2.4.0 CLAUDE.md), 7 (Dependency Update Checker — needs design pass), 9 (DPAPI cookie encryption — security-critical, candidate for next run with focused audit), 10 (Accessibility UIA pass — large cross-cutting change, separate iteration).

## Next iteration setup (deferred to next run)

- Phase 5 audit on existing ROADMAP (verify 7 dimensions per directive-roadmap-research.md)
- Tier 1 Items 9 + 10 (security + accessibility focus iteration)
- Tier 1 Items 1 + 2 (UI wiring focus iteration; multiple pages)
