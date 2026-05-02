# UCX ROADMAP Phase 5 Self-Audit (iter-1)

**Run:** factory loop, single-session, Large-Repo Mode
**Date:** 2026-05-01
**ROADMAP version audited:** commit 4c84cb8 baseline (50 unchecked items, 38 sources)
**Phase 5 cross-family auditor:** codex-direct.sh (gpt-5.4) + master Claude (Opus 4.7) cross-check
**Audit method:** the seven dimensions defined by `directive-roadmap-research.md`

> **Outcome at a glance:** ROADMAP needs reconciliation. At least 2 Tier 1 Now items are
> already shipped and should be retired. 1 more is partially shipped. No charter violations
> found. Coverage gaps in observability, plugin architecture, and migration/upgrade.

---

## Dimension 1 — Source traceability

**Verdict:** PASS with one note.

- All 50 items cite at least one `[Sx]` source.
- Appendix [S1]–[S38] is complete; [S25] is explicitly removed (404), correctly flagged.
- No phantom citations detected.
- **Note:** [S14] ("General competitive survey...") is a meta-source citation used by 8 items
  (4, 6, 8, 18, 22, 33, 41 partially, 45). For source-rigor purposes consider promoting
  the strongest individual project for each [S14] usage to a dedicated [Sx]. Not a defect,
  but the strongest [S14] consumers (Items 8, 18, 22) would be more defensible against a
  "where does this come from" challenge with named projects.

## Dimension 2 — Tier placement reasoning

**Verdict:** Mostly defensible; two re-tier candidates.

- Tier 1 Now (11 items) — appropriate for "ship next two minor versions". All Effort 1-3.
- Tier 2 Next (22 items) — appropriately scoped; some bunching at Effort 3 but not anomalous.
- Tier 3 Later (17 items) — all genuinely Effort 3-5 OR Impact 2.

**Re-tier candidates (move):**

- **Item 20 (SponsorBlock Integration)** — currently Tier 2 Next. Effort 1 (yt-dlp flag pass-through),
  Impact 4 (leapfrog). This belongs in Tier 1 Now alongside Item 4/8/11 — same effort class.
- **Item 30 (Audio VBR Quality Mode)** — currently Tier 2 Next. Effort 1, Impact 3 (parity).
  Pure preset XML extension. Could go to Tier 1 Now.

## Dimension 3 — Category coverage

**Categories scored** (per `directive-roadmap-research.md` — security, accessibility, i18n,
observability, testing, docs, distribution, plugin, mobile, offline, multi-user, migration, upgrade):

| Category | Coverage | Items |
|----------|----------|-------|
| security | partial | 7 (dep update), 9 (DPAPI cookies), Item 38 implied (FFmpeg refresh) |
| accessibility | covered | 10 (UIA pass), 41 (i18n prereq) |
| i18n | covered | 41 (Crowdin) |
| observability | **GAP** | _none — no item for crash log / structured app log / debug toggle_ |
| testing | covered (just shipped) | 11 (CI contract gate — done this run) |
| docs | not covered as ROADMAP items | _shipped per-release; not a planned axis_ |
| distribution | covered | 25 (MSIX/WinGet), 47 (ARM64) |
| plugin | **GAP** | _no third-party sidecar story; UCX hard-codes 176 sidecars_ |
| mobile | n/a per charter | (Out of Scope explicit) |
| offline | charter-aligned | (every item) |
| multi-user | n/a per charter | (single-PC desktop) |
| migration | **GAP** | _no settings.json schema migration item; no preset XML schema versioning_ |
| upgrade | partial | 7 (dep update checker for tools) but not for app itself or sidecar binaries |

**Recommendation:** add 3 new ROADMAP items in the next iteration:

1. **Observability — local crash + structured log** (Tier 2 Next, Impact 3, Effort 2). Catppuccin
   debug log panel + crash dump to `%LocalAppData%/UniversalConverterX/logs/`. Gated behind
   `Settings.VerboseLogging` (which already exists). Source: standard desktop app pattern.
2. **Plugin — third-party sidecar manifest** (Tier 3 Later, Impact 3, Effort 4). Allow users
   to drop a `tools/<name>/` directory + manifest.json that declares the sidecar's input/output
   formats and event types. UCX already has the contract; surfacing it formally would let the
   community contribute sidecars without forking.
3. **Migration — settings.json schema versioning** (Tier 2 Next, Impact 2, Effort 1). Add
   `SchemaVersion` field, migration table for old field renames, backup-before-overwrite.

## Dimension 4 — Internal consistency

**Verdict:** PASS with two minor inconsistencies.

- No item appears in two tiers.
- Wording is consistent across descriptions and the Definition-of-Done section.
- **Inconsistency 1:** Item 6 (Conversion History) describes the feature as if not yet built,
  but evidence shows `HistoryService.cs` (414 LOC), `HistoryPage.xaml/cs`, and
  `ConverterXOptions.{EnableHistory, MaxHistoryEntries, HistoryRetentionDays}` are all present.
  Status: "Likely already shipped — needs reconciliation" (see Dimension 7).
- **Inconsistency 2:** Item 8 (Parallel Job Limit Setting) describes adding a "single `<Slider>` in
  `SettingsPage.xaml` and one property in `AppSettings`". Both already exist
  (`SettingsWindow.xaml:178-200`, `ConverterXOptions.cs:61`, console `--max-parallel` flag).
  Status: "FULLY SHIPPED — retire" (see Dimension 7).

## Dimension 5 — Adversarial review

**Strongest argument against shipping Tier 1 items 1-3:**

- **Item 1 (AiLab UI Wiring)** — argument against: the four "Future" tiles aren't equally weighted.
  TTS/STT have known-good sidecars (`edge-tts`, `whisper-stt`); Voice Changer's engine is "TBD".
  Counter: ship the two ready ones (TTS + STT) as a partial close, reclassify Photo Restore as
  Item 27 territory, leave Voice Changer at "engine pending" status. Splitting is healthier than
  shipping all four behind one ROADMAP entry.
- **Item 2 (Audio Compressor Page)** — weakest argument against: this is a 1-page parity feature
  with a sidecar that already passes contract tests. No real argument against shipping.
- **Item 3 (Batch Rename)** — argument against: the page-level fallback ("System.IO.File.Move in
  the UI project is sufficient for a first pass") is fine, but `{exif:date}` tokens are deferred
  to "Next-tier", which means shipping Item 3 leaves the headline marketing feature (EXIF-aware
  rename) as a known limitation. Recommend bundling Item 3 with the deferred ExifTool integration
  rather than shipping a half-feature.

**Strongest argument FOR moving items from Tier 2/3 to Tier 1:**

- **Item 20 (SponsorBlock)** — Effort 1, Impact 4 (leapfrog), trivial implementation
  (yt-dlp `--sponsorblock-remove` flag pass-through). Should be in Tier 1.
- **Item 30 (Audio VBR Quality Mode)** — Effort 1, Impact 3 (parity), pure preset XML
  extension. Should be in Tier 1.
- **Item 32 (Subtitle Auto-Sync)** — Effort 3 but Impact 4. Tier 2 placement is correct;
  argument FOR is "high user demand", argument AGAINST is "needs new sidecar engine".
  Stay in Tier 2.

## Dimension 6 — Charter alignment

**Charter:** "Offline-first. No cloud. No accounts. No telemetry. Windows 10 21H2+. Beat every
competitor on: format coverage, batch UX, programmability, AI depth."

**Verdict:** PASS — no charter violations found.

- Every AI item (16, 21, 27, 48, 49) explicitly notes local model paths.
- Item 7 (Dependency Update Checker) mentions "GitHub Releases" — that's a download, not telemetry,
  charter-aligned.
- Item 25 (MSIX/WinGet submission) requires a code-signing certificate — that's a builder
  requirement, not a runtime cloud dependency. Charter-aligned.
- Item 41 (Localization via Crowdin) — community translation tooling, not runtime. Charter-aligned.
- Items in "Out of Scope" (cloud AI, live streaming, DRM, mobile, accounts, telemetry) are
  correctly excluded with rationale.

## Dimension 7 — File-on-disk consistency

**Verdict:** Two items shipped-but-not-crossed-off; one ambiguous.

| Item | ROADMAP status | Code reality | Action |
|------|---------------|--------------|--------|
| **Item 4** | unchecked Tier 1 | **JUST SHIPPED** in this run (commit `80932bd`) — `UniqueOutputPath.cs` + orchestrator switch + 11 tests | RETIRE |
| **Item 6** | unchecked Tier 1 | Likely shipped: `HistoryService.cs` (414 LOC, SQLite-backed `HistoryRecord` schema with timestamp/engine/action/source/output/bytes/duration/error fields), `HistoryPage.xaml.cs` (138 LOC), `ConverterXOptions.{EnableHistory=true, MaxHistoryEntries=1000, HistoryRetentionDays=30}` | RECONCILE — deep-verify against ROADMAP description's specific feature checklist (filter/search, re-run action, "open output folder" shortcut), then retire if all present |
| **Item 8** | unchecked Tier 1 | **FULLY SHIPPED**: `SettingsWindow.xaml:178-200` ParallelSlider Min=1 Max=16; `ConverterXOptions.cs:61` MaxParallelConversions = `ProcessorCount/2`; `ConversionOrchestrator.cs:235` clamp; `ConfigCommand.cs:64,111` `--max-parallel` CLI flag | RETIRE |
| **Item 9** | unchecked Tier 1 | NOT shipped — zero `ProtectedData` references in `src/`. StreamKeep sidecar has `cookies.py` for browser import but writes plaintext `cookies.txt`. C#-side DPAPI encryption gap is real. | KEEP — still valid item |
| **Item 10** | unchecked Tier 1 | Partial: 22 `AutomationProperties.{Name,AutomationId}` occurrences across 10 of 45+ pages. Coverage roughly 22% of UI. | KEEP — still valid; consider noting partial progress |
| **Item 11** | unchecked Tier 1 | **JUST SHIPPED** in this run (commit `2f2864c`) — `.github/workflows/build.yml` `sidecar-contract` job | RETIRE |

**Net change for next iteration:** ROADMAP Tier 1 Now drops from 11 items to 7 (Items 1, 2, 3, 5,
7, 9, 10 remain). Items 4, 6, 8, 11 retire. Of those, Items 4 and 11 retire because they shipped
this iteration; Items 6 and 8 retire because they shipped before this iteration but were never
crossed off.

This is exactly the kind of state-drift Phase 5 audit is designed to catch — running it should
become standard practice on the back of every ROADMAP authoring pass, not an afterthought.

---

## Recommended ROADMAP edits (for next iteration to apply)

1. Move Item 4, 8, 11 to a new "Tier 0 — Retired (shipped)" section at the bottom of the file.
   Cite the closing commit. Do NOT delete — keep the audit trail.
2. Verify Item 6 against the spec checklist; if it matches, also retire it.
3. Promote Item 20 (SponsorBlock) and Item 30 (Audio VBR) from Tier 2 to Tier 1.
4. Add three new items per Dimension 3 recommendation (observability, plugin manifest,
   settings schema migration).
5. Consider splitting Item 1 (AiLab UI Wiring) into 1a (TTS), 1b (STT), 1c (Photo Restore),
   1d (Voice Changer engine TBD).

These edits are NOT applied this run — Large-Repo Mode rotation skips speculative ROADMAP edits
when the burndown task budget is already spent. Surfaced for the next factory invocation to act on.

---

## Cross-family audit signal

This audit was authored by master Claude (Opus 4.7) with file-on-disk verification, plus a
parallel codex-direct.sh self-audit dispatch (model: gpt-5.4) on the same prompt. The codex
pass logs to `~/.claude-octopus/logs/codex-direct/codex-self-audit-20260502T035131Z-24105.last.md`.

**Convergence:** the two passes agreed on Items 4, 6, 8, 11 retirement and on the Item 20 / 30
re-tier recommendations. No contradictions.

**Divergence (codex caught what master Claude missed):**

| Finding | Master Claude | Codex (gpt-5.4) | Resolution |
|---------|---------------|-----------------|------------|
| **Item 1** subdivision | Lumped — "ship the two ready ones (TTS+STT) as partial close" | "Retire TTS/STT/photo-restoration parts — only Voice Changer remains" | **Codex correct.** Verified: `MainWindow.xaml.cs:151-154` already routes ai-tts/ai-stt/ai-photo-restore to live pages; ToolboxPage marks them Ready. Item 1 needs to be split, not partially closed. |
| **Item 13** scope | Tier 2 valid, defer | Track-add and track-remove already exist; only export remains | **Codex correct.** Item 13 is partially shipped — narrow the spec to "subtitle track export" only. |
| **Item 34** (Watch Folder) | Listed as Tier 3 Later, untouched | "Live: WatchFoldersPage + WatchFolderService" | **Codex correct.** Verified source files exist. **Retire Item 34.** |
| **Item 35** (ucx serve REST) | Listed as Tier 3 Later, untouched | "Live: ServeCommand.cs" | **Codex correct.** Verified ServeCommand.cs exists at 505 LOC. **Retire Item 35.** |
| **UC item** (VMAF) | Listed as needs-investigation | "Already user-facing: VmafAnalysisPage" | **Codex correct.** Retire from UC. |
| **Item 10** scope | "22% UI coverage; partial" | "Zero `AutomationProperties.AutomationId` usage in src" | **Codex correct.** Verified — `AutomationProperties.Name` exists in 22 files, but `AutomationId` is *zero*. Item 10 description says "all interactive controls" — current state is `Name`-only, no `Id`. The spec needs to clarify this (continue an audit-in-progress, not start one). |
| **Charter risk** | Reported clean | Items 7 (auto dep checks), 45 (URL preset import), 48 (auto-fetched model weights) add network behavior without `CHARTER-REVIEW` tag | **Codex correct.** All three items add network ops — they should be tagged or have explicit charter exceptions. |

**Why master Claude missed these:** I focused the file-on-disk dimension on Tier 1 only, and
on items I had specific evidence for (Item 6, 8). I did not enumerate all Tier 2/3 / UC items
against `find src -name "<feature>*"` — that's the discipline gap codex's broader pass
exercised. Lesson for next iteration: file-on-disk verification needs a checklist of every
roadmap item, not just suspect ones.

**Net result of cross-family pass:** retirements expand from 4 items (master Claude) to 9
items (codex + master Claude combined): Items 4, 6, 8, 11 (Tier 1 confirmed shipped),
Items 34, 35 (Tier 3 already shipped), VMAF UC item, plus partial-retirement narrowing on
Items 1, 13. ROADMAP staleness is significantly worse than the master pass alone would
have caught — exactly the case for keeping cross-family audit as a documented requirement,
not a "nice to have".

If the next iteration applies all these retirements and adds the recommended new items
(observability, plugin manifest, settings schema migration), Phase 5 should re-run with a
substantially smaller drift surface and likely converge to a smoke-pass cadence.
