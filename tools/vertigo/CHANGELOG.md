# Changelog

All notable changes to Vertigo are documented here.

## [Unreleased]

- **Segment proposal duration controls.** The preview trim tool now exposes
  min / target / max sliders for Suggest segments, and the controller passes
  that band into `SegmentProposalsWorker` instead of hard-coding 30-90 s /
  45 s. The popup menu and toast echo the active band so candidate lists are
  easier to trust.
- **Regression coverage.** `test_main_window_smoke.py` now checks the segment
  band defaults, UI setters, and worker kwargs. Added `pytest.ini` so
  `pytest-qt` consistently selects PyQt6 when PySide6 is also installed.

## [0.12.3] - 2026-04-24

### Iter 1 — polish + perf (Tier 8)

Factory-loop iteration advancing the "Next up" punch list from the v0.12.2 continuation brief. No new features; every task is visible only in the form of code that no longer scans, leaks, or drops warnings.

- **Audit PNGs pruned from repo root.** `_polish_iconstrip.png` and `_polish_modes.png` pre-dated the `_*.png` gitignore rule and had been sitting in the repo as obsolete QA artifacts since v0.10. Deleted; nothing referenced them.
- **`WORKER_CANCELLED_MSG` constant.** Replaces the `"Cancelled."` magic string across nine non-test files (six worker modules, three controller slots). Defined once in `workers/__init__.py`; a future rename is now a one-line change instead of a nine-file grep. Tests that pin the literal value are unchanged — the runtime string is identical.
- **Shutdown-warning breadcrumbs survive frozen builds.** `ui/main_controller.shutdown()` previously logged worker-hang warnings via `print(..., file=sys.stderr)`. PyInstaller one-file builds discard stderr, so the warning was effectively lost exactly when it mattered most. New `core/crashlog.py` appends timestamped lines to a platform-appropriate user-data path (`%LOCALAPPDATA%\Vertigo\crash.log`, `~/Library/Logs/Vertigo/`, `$XDG_STATE_HOME/vertigo/`). No-op safe, cap-rotated at 256 KiB via `os.replace` atomic swap, explicit guard that refuses any candidate path under `sys._MEIPASS`.
- **Captions-has-text gate is O(1).** `MainController.refresh_segments_button()` used to do `any(c.text.strip() ...)` over the cached caption list on every UI refresh — and the gate fires on queue change, subs ready, subs cleared, trim change, and duration probe. New `_captions_has_text: dict[int, bool]` flag is populated once at caption-write time by the new `_set_cached_captions()` helper, and invalidated in `drop_clip_subs` / `on_subs_cleared`. 2-hour lecture transcripts no longer re-scan 20 k captions per click.
- **`_gap_before` / `_gap_after` use bisect.** Linear scan over every caption per `_score_segment` call was O(N·M) for M candidate segments — ~100 k comparisons on a two-hour clip. New shared `_straddling_gap()` takes a precomputed `starts` array and does `bisect_left`, dropping the cost to O(log N) per lookup. `propose_segments` precomputes the array once and threads it through scoring. New regression test pins scaling and bit-for-bit equivalence against the prior linear path.
- **Test suite**: 144 → 154 passing (+8 `tests/test_crashlog.py`, +2 `tests/test_segment_proposals.py` for bisect scaling + parity).

### Iter 2 — multilingual + observability parity (Tier 9)

- **Multilingual stop-list for segment proposals.** `_STOP_WORDS` was English-only, so TextTiling cohesion over-counted every `le` / `la` / `der` / `die` on non-English transcripts and produced lumpy segment boundaries. Extended with `_STOP_WORDS_ES` / `_FR` / `_DE` / `_PT` / `_IT` sibling frozensets unioned into the main set. Charter-safe — no new deps, no NLTK, tables fit in-source.
- **`core/_lazy.py` pip failures now land in `crash.log`.** The every-strategy-failed branch still printed via `sys.stderr`, which PyInstaller one-file builds discard. Routed through `core.crashlog.append` so the breadcrumb survives frozen builds — same fix R3 applied to the shutdown path, now applied to the opt-in-dep install path.
- **`core/crashlog.py` path harmonised with the bootstrap.** `vertigo.py::_log_dir` writes fatal errors to `Vertigo\` on Windows / `Library/Logs/Vertigo/` on macOS / `$XDG_STATE_HOME/Vertigo/` on Linux. The crashlog module was lowercasing the Linux path (`vertigo/`), so bootstrap crashes and runtime breadcrumbs landed in different directories depending on where the failure happened. Capitalised the Linux dir, added the APPDATA fallback on Windows, honoured the TEMP fallback so sandboxed environments still leave breadcrumbs somewhere.
- **Test suite**: 154 → 161 passing (+4 stop-list / tokenizer parity, +2 lazy-install crashlog breadcrumb, +1 Windows APPDATA branch). `test_append_is_noop_on_bad_parent` renamed + upgraded to prove the TEMP fallback kicks in.

## [0.12.2] - 2026-04-24

### Postflight security + review findings

Factory-loop postflight pass on top of v0.12.1 — an adversarial security audit and a release-candidate review turned up two real fixes and a pile of documentation drift. No new features.

- **`subtitles=` filter-path injection hole closed.** `core.encode._subtitles_filter` previously escaped only the Windows drive colon (`C:/foo` → `C\:/foo`). A caption file whose path held a second colon — trivial on POSIX timestamped paths or adversarial filenames — slipped the inner colon through libavfilter's filter-graph parser, which then split the `subtitles=...` argument at that colon and interpreted the tail as additional filter options. Escaping every colon as `\:` closes the hole. Added `tests/test_subtitles_filter_escape.py` to pin the fix.
- **Partial encode output cleaned up on cancel / FFmpeg non-zero exit.** `workers/encode_worker.py::_unlink_partial` now scrubs `self._job.out_path` in all three failure branches (cancel, non-zero rc, exception). Matches the pycaps-swap hygiene we already had and stops half-written multi-GB orphans from piling up next to real exports.
- **README architecture tree rebuilt.** The `## Architecture` block was still listing the v0.10-era layout — no `core/_lazy.py`, no `core/caption_types.py`, no `segment_proposals`, no `pycaps_worker`, no `highlights_worker`, no `main_controller`. Swept through and matched current tree.
- **README "Suggest segments" feature bullet** now explicitly calls out that AI captions must be generated first (matching the in-app tooltip).
- **`requirements-optional.txt` + README licensing section** annotate every opt-in dep with its license. Calls out `boxmot>=11` (AGPL-3.0) and `pyannote.audio` HuggingFace model weights (often CC-BY-NC-4.0) so downstream packagers — SaaS builds especially — know where they stand.
- **Tightened `test_pycaps_failed_without_usable_output_routes_to_failure`** to actually assert the status pill reads "Export failed" rather than just that `last_output_path` wasn't corrupted to `Path('.')`. Name now matches the behaviour it pins.
- **Test suite**: 139 → 144 passing (+5 from the new filter-escape regression class).

## [0.12.1] - 2026-04-24

### Audit-cycle hardening — pycaps + worker lifecycle + segment cancel

A point release across three unrelated defects the post-0.12.0 audit surfaced. All production-facing, zero new features.

- **`_on_pycaps_failed` no longer crashes when the clip was cleared mid-export.** Resolves `reframed_out` through `ctx["reframed_out"]` → `ctx["tmp_out"]` → `self.last_output_path`, then checks that the candidate file actually exists. If nothing usable survives (first-run pycaps crash, user cleared the queue before pycaps returned), the slot now routes through `_on_export_fail` instead of finalising an empty `Path('.')` as "Complete" — the user sees an honest "Export failed" toast instead of a lying success UI.
- **Worker-handle cleanup across every slot.** `vad_worker`, `highlights_worker`, `auto_edit_worker`, and `pycaps_worker` now get nulled out in both their `_on_*_ready` and `_on_*_failed` slots, matching the pattern `segments_worker` introduced in v0.12.0. Drops the stale QThread references the moment the run finishes instead of pinning them until the next run replaces them.
- **Segment proposals honour user-cancel on pathological clips.** Threaded `cancel_cb` through `propose_segments`, `_boundaries`, `_assemble_segments`, and `_score_segment` so the TextTiling sweep + scoring pass both poll the worker's `_cancel` flag. Previously the worker's `cancel()` was a false facade — a user who hit Cancel on a 2-hour transcript would wait seconds for the synchronous scoring loop to exit.
- **`BatchQueue.clear()` now emits `entry_removed` per id.** Pre-existing bug surfaced by the iter-2 focus on subs-clear invalidation: the toolbar's "Clear queue" wiped `_items` / `_entries` without emitting per-entry signals, so `MainController.drop_clip_subs` never ran for cleared entries. Cached SRT/ASS files, `clip_captions`, and `animated_styles` leaked. Now routes every removal through the same signal path.
- **`on_subs_cleared` drops the cached caption list + animated-style selection.** Clearing the SRT from the subtitles panel used to preserve `clip_captions[entry.id]`, so the Suggest-segments button stayed lit against stale data. Now the cached captions + animated style are dropped and `refresh_segments_button()` runs so the gate re-evaluates.
- **`Caption` / `Word` extracted to `core/caption_types.py`.** New callers import from there; `core.subtitles` re-exports via `from .caption_types import Caption, Word` (both `__all__` + class identity preserved) so existing imports still work. Lets `core/segment_proposals.py` import the dataclass shape without dragging the transcoder's `caption_layout` + `caption_styles` + `face_samples` chain.
- **Counter-audit found the audit's own gaps.** `test_gap_after_mirrors_gap_before` now asserts the two symmetric straddling cases that the original test skipped. New `BatchQueueClearTests` pins the `entry_removed` emission. New `test_pycaps_failed_without_usable_output_routes_to_failure` guards against the Path('.') regression.
- **Test suite**: 128 → 139 passing (+11 new regression cases).

## [0.12.0] - 2026-04-24

### Segment proposals + fork-bomb hardening across opt-in modules

Two themes: ship **T3b · Segment proposals** (the last explicit open ROADMAP item) and close a real P0 hazard that had been hiding across every opt-in `core/*` module.

#### T3b · Suggest segments trim button

- **`core/segment_proposals.py`** — new, pure-stdlib TextTiling-style segmenter. Takes the already-cached `faster-whisper` caption list, slides K=20-token windows, computes Jaccard similarity between adjacent windows, promotes silence gaps >= 2.5 s as boundaries, then greedily assembles 30-90 s candidate segments targeting 45 s. Scoring is a deterministic weighted sum: `?`-count (40 %), laughter tokens (20 %, regex-matched against `haha`/`hehe`/`lol`/`[laughter]`/`*laughs*`), length-fit around `target_sec` (40 %), plus a silence-edge bonus when clean cut points abut either side. No LLM, no network, no new dep — per charter "stop before the LLM step". Original ROADMAP line pointed at ClipsAI; that fork is MIT but drags WhisperX + torch, so we reject it and use the already-cached transcript.
- **`workers/segment_proposals_worker.py`** — `QThread` wrapper around `propose_segments` so the TextTiling sweep stays off the UI thread even though it's fast. Wired into `MainController.has_running_worker` / `shutdown` / `cancel_active`.
- **`ui/video_player.py`** — new **"Suggest segments"** button on the trim row, controller-gated on `clip_duration > 10 min` + cached transcript. Tooltip rotates between "load a clip", "too short", "generate captions first", and the fully-unlocked help text.
- **`ui/main_controller.py`** — `run_suggest_segments`, popup menu formatter `_format_segment_label` (timerange + score % + title hint + reasons), `_apply_segment_trim` drops the trim handles on the chosen span. `refresh_segments_button()` re-runs the gate from `_on_queue_select` and `_on_subs_done` so the button lights up the moment captions finish for a long clip.
- **Tests** — 13 new cases in `tests/test_segment_proposals.py` including an explicit silence-boundary regression (the audit pass caught the synthetic fixture claiming silence gaps it didn't actually insert).

#### H1 · Fork-bomb hardening across eight opt-in modules

- **`core/_lazy.py`** — new shared `pip_install(spec)` helper with one `is_frozen()` short-circuit. PyInstaller builds get `sys.executable == Vertigo.exe`, so a missing opt-in dep hitting any of the previous eight per-file `_try_pip_install` helpers would have relaunched the GUI recursively — the same fork-bomb class that `vertigo.py::_pip_install` has guarded against since day one. The eight opt-in modules did not. They do now. Also adds a `threading.Lock` around the install call so two worker threads both discovering a missing dep don't run parallel pip installs (known to corrupt site-packages metadata).
- **Refactored** `core/subtitles.py`, `core/vad.py`, `core/animated_captions.py`, `core/tracker_boxmot.py`, `core/highlights.py`, `core/keyframes.py`, `core/diarize.py`, `core/broll.py` (three call sites) to route through `core._lazy.pip_install`. Dead `import subprocess` / `import sys` removed where they became unused.
- **`tests/test_lazy_install.py`** — 7 new regression tests pin the fix. `test_opt_in_ensure_funcs_block_install_when_frozen` monkey-patches `_lazy.is_frozen = True` + a spy `_pip_runner`, calls every `ensure_*` across all eight modules, asserts each returns False AND that the spy was never called. `test_no_private_try_pip_install_leftover` flunks the suite if a future drive-by reintroduces the per-file helper.

#### Audit-cycle counter-fixes

- `_gap_before` / `_gap_after` in `segment_proposals.py` returned the gap at the *first* pair-crossing, not the gap straddling the target timestamp — the edge-bonus scoring was firing on unrelated silences. Rewrote both helpers to find the pair with `a.end <= t <= b.start` and return that gap (or zero).
- `_assemble_segments` replaced `best_score is math.inf` identity check with an explicit `found: bool` flag for readability.
- Caption-readiness gate tightened: now `any(c.text.strip() for c in caps)` instead of truthy-list, so a transcript of empty-text captions no longer lights up the button.
- `_on_segments_ready` / `_on_segments_failed` null out `segments_worker` to drop the QThread reference after the run completes.
- `pip_install` now logs a `crash.log` breadcrumb when every strategy raises an exception (typically pip itself missing) so frozen-build failures leave a trail.

#### Test suite

- **108 -> 128 passing** (+1 skipped when `auto-editor` is installed). 13 new segment-proposal cases, 7 new lazy-install regression tests.

## [0.11.1] - 2026-04-23

### Pycaps pass moves off the GUI thread

A point release focused on a single real-world defect surfaced by the post-0.11.0 audit: the animated-caption post-pass blocked the GUI for the entire composite.

- **`workers/pycaps_worker.py`** — new `QThread` that runs `animated_captions.render_composited` off the Qt event loop. The pycaps composite is a full FFmpeg re-encode and can take minutes on long clips; the previous `_apply_pycaps_pass` helper called it directly from the encode-done slot, freezing the entire window for the duration.
- **`MainController._on_export_done` refactor** — when an entry has an animated style + cached transcript, the slot kicks `PycapsWorker`, stashes the original out path / entry id in `_pending_pycaps`, and returns. File-swap + export finalisation run from `_on_pycaps_done` / `_on_pycaps_failed`. Shared finalisation lives in `_finish_export_done`. Missing-dep and missing-transcript paths still fall through to the reframed export with a log warning, unchanged.
- **Lifecycle** — `pycaps_worker` is wired into `has_running_worker`, `shutdown`, and `cancel_active`. User-cancel deletes the partial `.pycaps` sibling file so a half-encoded MP4 never lands next to the final export.
- **Tests: 101 → 108 passing.** `tests/test_pycaps_worker.py` adds 7 guards for the worker's cancel / failure contract and the controller's three-way finalisation branch (direct / pycaps-done / pycaps-failed).

## [0.11.0] - 2026-04-23

### Design-system polish + deep hardening + nine optional integrations

A marathon release across three themes: finish the premium-polish pass, harden the whole worker + encode pipeline, and expose a broad optional-integrations surface so power users can upgrade the product incrementally.

#### Design system (premium polish, continued)

- **Checkmark glyph inside QCheckBox** — baked per-theme PNGs rendered from an SVG with `currentColor` tinting; wired into QSS `image:` on `:checked` / `:checked:hover` / `:indeterminate` / `:checked:disabled`. Writable cache under `%LOCALAPPDATA%/Vertigo/glyphs/<theme>/`; cache key is theme id + palette hash. Replaces the bare accent-fill that previously showed no glyph.
- **Custom chevron for QComboBox::down-arrow** — same baking pipeline, three tints per theme (`subtext0` rest / `text` hover / `accent` focus/open). QSS selectors target `QComboBox::down-arrow`, `:hover::down-arrow`, `:focus::down-arrow`, `::down-arrow:on`.
- **FadingTabWidget** (`ui/widgets.py`) — QTabWidget subclass with a 180 ms OutCubic cross-fade on tab change. Persistent `QGraphicsOpacityEffect` + `QPropertyAnimation` cached per page so rapid tab flicks don't stack effects and teardown races can't fire `finished()` on a dead target. Honours `QT_ANIMATION_DURATION_FACTOR=0` as the reduced-motion opt-out.
- **`QTabWidget#sideTabs` CSS generalised** → plain `QTabWidget` + `QTabBar::tab`, so any `QTabWidget` (including `FadingTabWidget`) inherits the themed pane + rounded tab buttons. The old selectors had been dead since the side-tabs layout was removed.

#### Architecture (main_window split)

- **`ui/main_window.py` 1699 → ~1100 lines.** Worker lifecycle, batch driver, and every per-worker signal handler moved into a new **`ui/main_controller.py`**. Promoted to a real composed `QObject` (`self._ctl = MainController(self)`) with worker handles, analysis results, batch flags, and `last_output_path` extracted off the window. `closeEvent` collapsed from nine lines to `self._ctl.shutdown(1500)`. Signal wiring lives in `MainController.wire()`.
- **`ui/panels.py`** — two genuinely pure build helpers (`build_tool_section`, `add_overview_metric`) extracted; the rest stay on `MainWindow` because extracting them would add cross-imports.
- **`_clear_queue(confirm=True)`** kwarg so the smoke test exercises the real reset path.

#### Production hardening

Ten concrete defects fixed:

- **MediaPipe sentinel race** (`core/detect.py`): tri-state `None`/object/`False` only checked `is None` in the hot path, so after an init failure every frame silently burned CPU through its own try/except. Replaced with typed string sentinels + fast-path `_MP_DISABLED` check.
- **DetectWorker cancel contract**: no longer emits `finished_ok` with partial track after cancel.
- **FFmpeg encode kill escalation**: `terminate → wait(3s) → kill → wait(3s) → abandon`. A stuck FFmpeg no longer hangs the worker forever.
- **Subtitles-filter path escape**: single quotes escaped as `'\''` (FFmpeg idiom). Clip files with apostrophes no longer break the filter graph.
- **`_crop_dims` divide-by-zero guards** and **`_x_expression` bounded stride** (max 128 keyframes, first + last pinned) so long clips don't blow libavfilter's parser.
- **`clip_subs` cleanup on queue removal**.
- **`MainController.shutdown()`** logs worker-wait timeouts instead of silently exiting.
- **`FileDropZone`** filters on `Path.is_file()` as well as suffix.
- Minor: `hook_score` dead guard removed + sample_rate-0 early return; `batch_queue` ID counter → `itertools.count(1)`; pluralizations.

#### Optional integrations (nine core/ modules)

Every module follows the `core.subtitles` lazy-install pattern — `is_available()` probes cheaply, `ensure_installed()` tries a pip install, public API raises `RuntimeError` with a clear install hint when absent. Optional manifest at `requirements-optional.txt`.

- **`core.vad`** — Silero VAD (ONNX, <2 MB, no PyTorch).
- **`core.animated_captions`** — pycaps wrapper. `render_composited(source, out, captions, template)` drives `CapsPipelineBuilder` as a post-encode pass. Real pycaps template names: `default`, `hype`, `minimalist`, `word-focus`, `explosive`, `vibrant`.
- **`core.tracker_boxmot`** — BoxMOT (AGPL-3.0) speaker-ID tracking via `make_tracker()` factory. Drop-in swap inside `FaceTracker.track_with_cameraman`.
- **`core.auto_edit`** — auto-editor subprocess with `--export json`; parses both timeline shapes.
- **`core.highlights`** — Lighthouse moment retrieval + sliding-window `hook_score` fallback.
- **`core.cluster_track`** — RetargetVid cluster-then-temporal-filter port. Pure numpy.
- **`core.diarize`** — pyannote.audio with a clear HF-token check.
- **`core.broll`** — transcript → KeyBERT → Pexels → CLIP pipeline with a stdlib-only keyword fallback.
- **`core.keyframes`** — Katna-ranked thumbnails with cv2 fallback. Always usable on a bare install.

#### Seven integrations wired into the UI

- **Smart Track two-pass pipeline** now runs through `cluster_track` — short-lived noise detections filtered before speaker/cameraman smoothing.
- **Smart Track tracker** via `make_tracker()` — installing `boxmot` silently upgrades to BoT-SORT.
- **"Tighten to speech"** trim button (Silero VAD).
- **"Find highlights"** trim button (Lighthouse + fallback) → popup menu of ranked moments.
- **"Trim silences"** trim button (auto-editor) → popup menu of longest speech-contiguous sections.
- **"Export thumbnails"** hero-header button (Katna + cv2 fallback).
- **Animated captions** (pycaps) in the Subtitles panel style picker — selecting a template routes the export through a post-encode pycaps pass.

Not wired per user preference: `core.diarize` (HuggingFace token / signup) and `core.broll` (Pexels API key / signup). Both remain available as importable modules.

#### Test suite

- **58 → 101 passing** (+ 1 skipped when `auto-editor` is present locally, a correct branch).
- `tests/test_hardening.py` — 11 regression guards pinning every hardening-pass fix.
- `tests/test_integrations.py` — 33 smoke tests covering every optional module's contract (including `_captions_to_whisper_json` uses `word` key, not `text`).
- `tests/test_main_window_smoke.py` — MainWindow construction + core signal paths.
- `tests/test_fading_tab_widget.py` — cross-theme construction + reduced-motion opt-out.

---

## [0.10.0] - 2026-04-23

### Tier 4a · Face-aware caption positioning

**T4a · Face-aware caption positioning (`v0.10.0`).** New opt-in toggle on the Captions tab — "Lift captions off faces (face-aware placement)". When enabled, faces are sampled at 2 fps before transcription and the ASS writer emits per-chunk alignment overrides so captions never sit on top of a subject. The v0.8.0 face-tracker plumbing is reused: MediaPipe is preferred, Haar cascade is the fallback.

- `core/face_samples.py` — minimal face sampler (~130 LoC) that returns normalised bounding boxes per time-step. Decoupled from `core/detect.py::FaceTracker` so the caption pass can run without affecting Smart Track state.
- `core/caption_layout.py` — layout heuristic. Computes the caption zone in normalised y-coordinates from the preset's `margin_v_fraction` plus a conservative 12 % two-line caption height estimate, checks each chunk's time window against overlapping face samples, and returns ASS alignment codes (2 = bottom-center default, 8 = top-center when a face occludes). `min_face_area=0.015` gate filters spurious tiny detections.
- `core/subtitles.py::write_ass` — accepts optional `face_samples` + `letterbox` kwargs, runs `plan_alignments` before emitting Dialogue lines, and prefixes overridden chunks with `{\anN}` inline tag.
- `core/subtitles.py::transcribe_to_file` — new `face_aware`/`letterbox`/`face_sample_fps` params. When `face_aware=True`, samples faces before transcribing. Forces ASS output for non-karaoke presets (SRT can't carry per-line positioning).
- `workers/subtitle_worker.py` — two new kwargs (`face_aware`, `letterbox`) piped through to `transcribe_to_file`; status line shows "face-aware layout" when active.
- `ui/subtitles_panel.py` — new `QCheckBox` "Lift captions off faces", tooltip explains the 2 fps sample rate + letterbox exemption. `SubtitleChoice` carries the flag; `transcribe_requested` signal gained a fourth `bool` argument.
- `ui/main_window.py::_run_transcribe` — accepts the `face_aware` flag, passes `is_letterbox = self._mode is ReframeMode.BLUR_LETTERBOX` so letterbox mode short-circuits the face pass entirely.

**Blur Letterbox exemption.** In letterbox reframe the bottom of the output is the blurred bar, not the subject. The face pass is skipped there (both computationally and in the alignment decision) — captions stay at bottom-center regardless of where the subject is in the source.

**Why top-center instead of `\pos` coordinates?** The research-report suggestion was `\pos(x, y)` overrides per-word. Top-center (`{\an8}`) is equivalent for every realistic placement (two safe zones: top or bottom, never middle-of-frame), simpler to reason about, and keeps the `margin_v` tuning intact — the caption just mirrors vertically. No new layout math needed.

### Verified
- `chunk_alignment` unit cases pass: face in bottom zone → flips to 8; face in top → stays 2; tiny face (area < 0.015) → ignored; out-of-window sample → ignored; letterbox flag → always default.
- End-to-end `write_ass` with synthetic samples emits `{\an8}Hello there` on the chunk overlapping a face and plain `Nothing here` on the chunk that doesn't.
- `MainWindow` constructs cleanly (offscreen).

## [0.9.0] - 2026-04-23

### Tier 3 (partial) · Shot-boundary UX + hook-energy signal

**T3a · Shot-snap on trim timeline (`v0.9.0`).** Scope refined from the research report's `transnetv2-pytorch` suggestion to the `PySceneDetect` we already ship — the research agent called TransNetV2 "highest-ROI item in Tier 3", but the real value is the *interaction* (snap-to-cut trim handles + visible ticks), not the SOTA algorithm. A 500 MB PyTorch dependency for a +4 % F1 improvement over PySceneDetect is not a trade we'd make.

- `workers/scene_worker.py` — a `QThread` that runs scene detection off the UI thread on every clip load (previously only ran when Smart Track was invoked, so the trim timeline had no knowledge of cuts).
- `ui/range_slider.py` — new `set_shot_boundaries(list[float])` API. Paints a faint vertical tick at each cut, slightly above + below the slider track, under the accent fill so it sits behind the selection. Trim thumbs magnet-snap to the nearest boundary within a 200 ms window via a new `_apply_snap()` helper.
- `ui/video_player.py` — `set_shot_boundaries(...)` forwarder so `MainWindow` can address the slider without reaching through two layers.
- `ui/main_window.py::_kick_scene_detection` fires on every clip select; `_on_scenes_ready` stashes the result in `self._scenes` (reused by Smart Track) and pushes boundaries to the slider. Clear-clip cancels any in-flight worker and wipes ticks.
- Smart Track's `_run_detect()` now skips the inline `detect_scenes()` pass when the background worker has already produced a result.

**T3c · Hook-energy score (`v0.9.0`).** New `core/hook_score.py` produces a 0–100 engagement signal for the first 3 seconds of audio. Ignored the research report's `librosa + silero-vad` suggestion — no need for torch just to RMS a 3-second window.

- Audio grabbed via `ffmpeg -t 3 -ac 1 -ar 16000 -f s16le -` (FFmpeg is already required).
- Pure-Python per-frame RMS + zero-crossing-rate voice heuristic (speech: non-trivial RMS + ZCR in 0.02–0.35 range).
- Percentile-normalised energy so a single loud burst doesn't flatten the rest of the window.
- `HookScore` dataclass with `.score`, `.label` (`silent`/`weak`/`moderate`/`strong`), `.voice_fraction`, `.mean_voiced_energy`.
- Surfaced in the dry-run report (`core/dryrun.py`) as `Hook (first 3s): 72 · strong · voice 88% · energy 64%`.
- Ready to plug into the future T3b proposal panel.

**T3b is explicitly not landed yet** — the proposal UI needs design work (probably a new tab or a queue-panel mode) and T3c's scoring is useful without it for any single-clip analysis.

### Verified
- Shot ticks render correctly on the trim slider with three sample boundaries.
- `set_shot_boundaries` forwarder wired through `VideoPlayer` → `RangeSlider`.
- Hook score runs against a 3 s sine-wave test clip and returns `99 · strong` (expected: pure 440 Hz is continuous voice-band energy).
- `MainWindow` constructs cleanly with all 6 tabs intact.

## [0.8.0] - 2026-04-23

### Captions leap (Tier 1 from the competitive-research roadmap)
- **Caption preset system** (`core/caption_styles.py`) — `CaptionPreset` dataclass + six bundled looks (Clean, Pop, Karaoke, Bold Yellow, Neon Outline, Classic). Replaces the single hard-coded ASS block. Style picker surfaced as a dropdown in the Captions tab with a per-preset hint line.
- **Mobile-correct defaults** — font size now scales as `height / preset.font_scale` (20–24 range, ~87 pt at 1080 p instead of fixed 24 pt), bottom margin is `0.20 × height` not a hard-coded 60 px, wrap targets ≤ 18 chars × 2 lines. 2026 creator-tool consensus (CapCut / Opus / Submagic / Descript).
- **Word-level karaoke captions** — `faster-whisper` now called with `word_timestamps=True` for karaoke presets (zero new deps). New writer emits ASS with inline `\kf<cs>` fill-sweep tags per word. libass renders through the existing `subtitles=` filter. Soft limits: 3–4 words/chunk, ≤ 1.2 s/chunk. ASS writer patterned after `jianfch/stable-ts` `text_output.py` (MIT; re-implemented).
- `core/subtitles.py` refactored: new `Word` / `Caption` dataclasses, `transcribe_to_file(source, out_dir, preset, height_px, ...)` dispatches to SRT or styled ASS based on preset. Legacy `transcribe_to_srt(source, out_path)` kept as a thin alias.
- `EncodeJob` carries a `caption_preset_id`; `_subtitles_filter` builds `force_style=` from `force_style_string(preset, height)` so the same preset lands correctly at any output resolution.

### Smart-track quality (Tier 2)
- **`SmoothedCameraman` + `SpeakerTracker`** (`core/cameraman.py`) — ~320 LoC, MIT-compatible re-implementation of `mutonby/openshorts`'s tracking algorithms. Safe-zone hysteresis (no viewport motion while subject stays within ±25 % of crop width), speed-adaptive motion (3 px/f resting, 15 px/f on > 50 %-of-crop jumps, overshoot clamp), ID-sticky speaker tracking with exponential activity decay (0.85/f), +3 bonus on the active speaker, and a 30-frame switch cool-down.
- **Active-speaker bonus now gated on presence-this-frame** — bug caught during smoke-test: the previous port would keep an off-screen speaker indefinitely because the sticky bonus applied even when they weren't observed. Active bonus now only applies when the track was actually matched to an observation on the current frame, and switch candidates are restricted to tracks seen this frame.
- **Savitzky-Golay smoothing** on the x(t) trajectory (`core/reframe.py::_smooth_track`) — `scipy.signal.savgol_filter(window_length = odd(src_fps · 0.5), polyorder = 3)` applied before the piecewise-lerp FFmpeg expression is built. Kills detection jitter without perceptual latency. `scipy>=1.11` added to requirements.
- **VFR → CFR preflight** (`core/preflight.py`) — `VideoInfo` now carries `r_fps`, `avg_fps`, and `video_start_time`; `is_variable_frame_rate` detects > 1 % delta between r and avg frame rates; `plan_preflight(info, target_fps)` emits pre-input and output-side FFmpeg args. VFR sources now normalise to the closest safe-ladder rate (24 / 25 / 30 / 50 / 60) via `-vsync cfr -r <n>`. Non-zero video `start_time` now adds `-af adelay=<ms>|<ms>,apad` so audio realigns to t = 0 instead of silently drifting. Autocrop-vertical has no LICENSE, so this is a clean re-implementation of the public `ffprobe` technique.
- **Cameraman-driven detection pipeline** — `FaceTracker.track_with_cameraman(video, crop_width_frac)` feeds all per-frame detections through `SpeakerTracker` + `SmoothedCameraman`. `DetectWorker` picks this path automatically when the main window knows the clip's crop geometry. `_smart_track_crop_width_frac()` computes that fraction from the active preset + probed aspect.
- **Dry-run plan reporter** (`core/dryrun.py`, T2d) — builds a full synthesis of the active pipeline (probe → preflight → scene detection → reframe plan → encoder → per-scene strategy) and renders it to a monospace report. Surfaced as a new **"Show plan (dry run)"** button in the Track tab; output lands in the existing export log panel. No FFmpeg is invoked.

### Added
- `ui/tokens.py`-adjacent `core/preflight.py` and `core/cameraman.py` keep FFmpeg and Qt out of the hot-path logic so it stays testable.
- `ROADMAP.md` — tiered plan grounded in the 2026 competitive research pass (three parallel agents: reframing tools / captions / auto-highlight). Ticks T1a/T1b/T1c + T2a/T2b/T2c/T2d.

### Verified
- End-to-end encode with Smart Track + savgol smoothing + synthetic 40-point trajectory → clean MP4 (rc = 0).
- SpeakerTracker switches correctly on a simulated "subject teleports across frame" scenario — camera reverses direction within one frame (654 → 669), accelerates at 15 px/f (819 → 1044), decelerates into dead-zone hold (1104 → 1104 on return-to-centre below threshold).
- Caption preset style resolves correctly: `pop` at 1920 p height → font 96 pt, margin 384 px.
- Preflight no-ops cleanly on a CFR 30 fps test clip.
- All six sidebar tabs construct under every theme.

## [0.7.0] - 2026-04-23

### Premium polish pass

Deep UI/UX refinement across the whole surface — no feature additions, every change measured against the question "would this pass review from a world-class design team?"

### Added
- **`ui/tokens.py`** — single source of truth for design tokens. Five scales: `S` (spacing, 4 px rhythm), `R` (radius — chip/control/panel/hero), `T` (type size — 11/12/13/15/20/28), `W` (weight — 400/500/600/700), `M` (motion — 120/180/280/360 ms). Code should reference tokens by name instead of hard-coding numbers.

### Changed — design system
- **Typography ladder** — real scale replacing the previous three-size-everything. Display (20 px, -0.2 letter-spacing), Title (15), Subtitle (14), Body (13), Body-S (12), Caption (11). Weights standardised on 500 for secondary UI and 600 for emphasis; 700 reserved for section headers.
- **Radius system** — 6 (chip) / 10 (control) / 14 (panel) / 18 (hero) instead of uniform 8. Visual depth comes from the radius difference between hero / supporting panels / chips / buttons.
- **Spacing rhythm** — every margin and padding swept onto a 4 px grid. No more 7/9/11/14/18/28 arbitrariness.
- **Focus ring** — now a single 1 px coloured border instead of a `1 → 2 px` swap that caused layout shift. Buttons, inputs, sliders, tabs, and mode cards all pick up the same `focus` token.
- **Primary button** — dropped `text-transform: uppercase` (dated/shouty), switched to sentence case with tight tracking. Press state uses a 1 px vertical text offset instead of a colour change to communicate depth. Disabled state merges into the surface layer.
- **Progress bar** — removed the `accent → pink` linear gradient (read as Material-lite circa 2015). Now a solid accent fill at 6 px height. Idle state shows a muted "Ready" pill instead of the bar dominating the panel.
- **Sidebar tabs** — 10 × 14 px padding, 2 px `margin-right` between tabs, resting colour drops to `overlay2` so the active tab really feels selected.
- **Preset chips** — now true pills (999 px radius), transparent at rest with a 1 px border. Hover uses `accent_hover`; selected fills with `accent`. Feels like pills instead of pressed buttons.
- **Checkbox** — previously unstyled; now a 16 × 16 rounded square that fills with accent on check, with a hover ring and focus ring.
- **Splitter handle** — 10 px wide with subtle hover colour for discoverability (was a 2 px bar that was almost invisible).
- **Scrollbars** — narrower (8 px) with 4 px radius thumbs. Less visual weight, still clickable.
- **Tooltip** — repainted with crust background, surface1 border, 8 px radius. Reads as a separate surface instead of blending into the host.
- **Dialogs (`QMessageBox`, `QFileDialog`)** — now themed consistently; default buttons pick up the primary colour. The native Windows dialog opt-out stays, so they stay in-app.

### Changed — states and feedback
- **Empty queue** — headline "Your queue is empty", body "Drop several clips on the preview to batch-export them with one set of settings." Reads as a hint instead of an error.
- **Drop zone** — replaced the QLabel text composition with a painted empty state: inset rounded container, downward arrow entering a 9:16 phone frame glyph, headline, helper, and a muted format caption at the bottom. Hover state swaps the helper for accepted-format list and swaps the headline to "Release to add clips". Visual language now matches the preview canvas empty state.
- **Preview canvas empty state** — two-line instructional text replaced with a muted 9:16 frame glyph carrying a "9 : 16" aspect badge and a single-line "Preview ready once a clip is loaded" helper.
- **Progress panel at rest** — log textarea hides itself until an export starts; idle state is just "Export · Ready" with a flat bar. When encoding begins, the log slides in. When the export finishes, the destination row + "Reveal in folder" appears.
- **Track tab** — copy warmed: "Load a clip to find faces and scene cuts" / "Scanning for faces and scene cuts…" / "Tracking 42 keyframes across 3 scenes. Export will follow the subject." Button: "Find subjects" → "Finding subjects…" while running → "Run again" once complete. The clinical "Analyze subject" verb is gone.
- **Cancel button** — promoted from a generic ghost to a new `destructiveGhost` style that leans red on hover, so an in-flight cancel feels deliberate.
- **Preset detail** — previously a single dense line; now two lines: geometry + bitrate on line 1, duration policy on line 2.

### Changed — microcopy
- Hero meta pill: "No clip loaded" → "Waiting for a clip".
- Toast: "Could not read clip" → "Could not read that clip — {err}".
- Scene status: "3 scene(s) detected" → "3 scenes detected · panning will respect cuts".
- Titlebar separator glyph: ASCII pipe `|` → bullet `•`.

### Changed — chrome
- Titlebar height 42 → 48 px; brand label 14 → 15 px and `weight 800 → 700` for less shoutiness; icon 24 → 26 px. Theme picker is now a transparent combobox that lights up on hover instead of always drawing a border.
- Body margins 18/16 → 20/20 for consistent breathing room.
- Sidebar spacing 14 → 12 px; splitter handle now large enough to grab.

### Accessibility
- Every interactive control has an accessible focus state that does not shift layout.
- Queue items are now focusable and respond to Enter/Space/Delete/Backspace.
- Checkbox and combobox focus rings use the dedicated `focus` token, not the generic `accent`.
- Mode cards and preset chips are accessible buttons with tooltip + accessible description.

### Files touched
`ui/tokens.py` (new), `ui/theme.py`, `ui/main_window.py`, `ui/titlebar.py`, `ui/file_drop.py` (rewritten from `QLabel` to painted `QWidget`), `ui/video_player.py` (empty-state composition), `ui/batch_queue.py`, `vertigo.py`, `vertigo.spec`, `README.md`.

### Verified
- All three themes (Mocha / Graphite / Latte) construct cleanly; main window renders at 1400 × 900 with proper hierarchy visible in offscreen-grab sanity checks.
- Source-mode smoke-import (`python -c "from vertigo import __version__"`) reports 0.7.0.
- No references to retired objectNames or removed widgets.

## [0.6.1] - 2026-04-23

### Fixed
- **Critical — PyInstaller binary crashed on launch with `AttributeError: 'NoneType' object has no attribute 'write'`.** Two bugs stacked:
  1. Under a Windows GUI PyInstaller build (`console=False`), `sys.stderr` and `sys.stdout` are both `None`. The existing `sys.stderr.write(...)` call inside `_bootstrap()` therefore exploded *while reporting a different error* — swallowing the real message.
  2. The real message was `mediapipe: ModuleNotFoundError: No module named 'matplotlib'`. MediaPipe imports matplotlib internally; the spec had matplotlib in its `excludes` list to keep the binary small, which broke MediaPipe at bundle-import time.
- New `_fatal(title, body)` helper in `vertigo.py`:
  - Writes every fatal error to `%LOCALAPPDATA%\Vertigo\crash.log` (macOS: `~/Library/Logs/Vertigo`; Linux: `~/.local/state/Vertigo`).
  - Echoes to `sys.stderr` only when it is not `None`.
  - Pops a native Windows `MessageBoxW` so GUI-mode users actually see the failure.
  - Exits cleanly with a distinct code (2/3/4/10) per failure class.
- Replaced every raw `sys.stderr.write(...)` and `print(...)` in `_bootstrap()` / `_check_ffmpeg()` with the new helper.
- Wrapped `main()` in an `_entry()` guard so a late-import or Qt-init crash still surfaces a MessageBox instead of closing the GUI silently.
- `_REQUIRED` import loop now catches `Exception`, not just `ImportError`, so modules that fail at init time (not just missing ones) also report cleanly.

### Changed
- `matplotlib` and `scipy` removed from PyInstaller `excludes` — both are transitive MediaPipe dependencies. Binary size increases by ~40 MB on Windows; acceptable trade for correctness.
- `vertigo.spec` now runs `collect_submodules("scenedetect" | "cv2" | "PIL")` + `collect_data_files("scenedetect" | "cv2")` in addition to the existing MediaPipe collection, to preempt the next lazy-import miss.
- Explicit hiddenimports for every `scenedetect.detectors.*` submodule (content/threshold/adaptive/hash/histogram) — PySceneDetect loads detectors via string reference, which PyInstaller's static analyzer can't follow.

### Verified
- Rebuilt `Vertigo.exe` launches cleanly on Windows 11. Process monitoring shows exactly two PIDs (bootloader + runtime), runtime stabilizes at ~198 MB with the Qt main window visible, no crash log written, killed cleanly.
- No `'NoneType' object has no attribute 'write'` regression.

## [0.6.0] - 2026-04-22

### Changed
- **Renamed the project from Kiln to Vertigo.** Vertigo, from the Latin *vertere* ("to turn"), captures the tool's core verb: turning horizontal footage into vertical. It also lends the brand a cinematic identity — Hitchcock-era graphic design language (concentric circles, dolly-zoom perspective) translates cleanly into the mauve-to-pink accent system.
- Entry point is now `python vertigo.py` (was `python kiln.py`). PyInstaller output binaries are `Vertigo.exe` / `Vertigo.app` / `Vertigo`. macOS bundle identifier is `com.sysadmindoc.vertigo`.
- `QSettings` organization key is now `Vertigo`. Theme preference lookup walks a chained fallback: `Vertigo → Kiln → ReelForge → "system"`, so users who installed under any prior name keep their appearance.
- Qt app-property keys renamed (`kilnThemeId` → `vertigoThemeId`, same for `kilnThemePreference`).
- Cache / sidecar paths renamed (`.kiln/` → `.vertigo/`, `*.kiln.srt` → `*.vertigo.srt`).
- Titlebar brand label reads **Vertigo**; subtitle reads "Vertical video studio."
- Wordmark SVG redrawn for `VERTIGO`; `assets/logo_prompts.md` rewritten around the vertigo / rotation / dolly-zoom metaphor.
- README, architecture tree, install instructions, and CHANGELOG header updated.

### Verified
- App boots under every theme with the new brand mark, 6 sidebar tabs intact.
- End-to-end encode still produces a clean MP4 in all reframe modes.
- No stale `Kiln` / `kiln` references remain outside the deliberate legacy-fallback chain and historical changelog entries.

## [0.5.1] - 2026-04-22

### Fixed
- **Critical — PyInstaller fork-bomb on Windows.** The v0.5.0 binary relaunched itself recursively on startup because `multiprocessing.freeze_support()` was not called at the entry point. MediaPipe and cv2 both use Python's `multiprocessing` module internally; on Windows each worker spawns via `sys.executable`, which in a frozen build is `Kiln.exe` — so every worker booted a new GUI instead of a worker, spawning new workers, and so on. Two guards now prevent this:
  1. `multiprocessing.freeze_support()` is now the first executable statement in `kiln.py`.
  2. A PyInstaller runtime hook (`assets/runtime_hook_mp.py`) fires the same call *before* user code, wired into `kiln.spec` via `runtime_hooks=[...]`.
- **Bootstrap disabled in frozen builds.** `_bootstrap()` used to call `[sys.executable, "-m", "pip", "install", ...]` whenever a package import failed. In a frozen exe `sys.executable` is the GUI itself, so a missing bundled dep would have re-launched Kiln in a loop instead of running pip. `_bootstrap()` and `_pip_install()` now short-circuit when `sys.frozen` is set and print a clear "bundled import failed" error instead.
- **Version bumped to 0.5.1** everywhere (`__version__`, README badge, macOS `CFBundleShortVersionString` / `CFBundleVersion`).

### Rebuild required
Anyone who downloaded the v0.5.0 binary should kill any running `Kiln.exe` processes (Task Manager or `taskkill /F /IM Kiln.exe /T`) and replace the binary with the v0.5.1 release once CI finishes.

## [0.5.0] - 2026-04-22

### Changed
- **Renamed the project from ReelForge to Kiln.** The brand shifts from a generic "forge" metaphor to the sharper image of a kiln: a focused chamber where raw clay becomes a finished, premium object. One syllable, more distinctive in the creator-tools space, pairs naturally with the existing mauve-gradient vertical chamber icon.
- Entry point is now `python kiln.py` (was `python reelforge.py`). PyInstaller output binaries are `Kiln.exe` / `Kiln.app` / `Kiln`.
- `QSettings` organization key moved to `Kiln` with a one-time fallback read from the old `ReelForge` key so existing users keep their theme preference.
- Qt app property keys renamed (`reelforgeThemeId` → `kilnThemeId`, same for `reelforgeThemePreference`).
- README, CHANGELOG, architecture tree, logo prompts, wordmark SVG, and all user-visible strings updated to the new name. Titlebar brand label reads **Kiln**; subtitle reads "The kiln for vertical video."
- Cache / sidecar paths renamed (`.reelforge/` → `.kiln/`, `*.reelforge.srt` → `*.kiln.srt`).

### Verified
- App boots under every theme with the new brand mark, 6 sidebar tabs intact.
- End-to-end encode (NVENC + Center + adjustments + 2 overlays) still produces a clean MP4.
- No stale "ReelForge" / "reelforge" references remain in source or docs.

## [0.4.0] - 2026-04-22

### Added
- **Brand mark** — procedural logo rendered by `assets/build_icons.py` (Pillow). Ships as `icon.svg`, `icon.ico` (16/32/48/128/256 multi-res), `icon.png` (256), plus 512px and 16-48 PNG variants. Wordmark SVG included separately.
- **Window icon wiring** — `QApplication.setWindowIcon`, `MainWindow.setWindowIcon`, and the frameless titlebar all pick the icon up via a new bundle-aware `ui/assets.py` resolver that works under both source and PyInstaller.
- **Text overlays tab (Text)** — per-overlay editor with text, in/out range (clamped to clip duration), placement (title / top strap / lower-third / bottom caption), font size, color picker, and remove button. Preset menu adds intro title card, lower-third name, top hook, and bottom CTA with one click. Overlays compile to an FFmpeg `drawtext=` filter chain with `enable='between(t,start,end)'` gating.
- **PyInstaller spec** — `reelforge.spec` produces a single-file exe on every OS with the correct per-platform icon, bundles `assets/` and MediaPipe's TFLite data files, and trims ~350 MB of deadweight (tkinter, matplotlib, scipy, pandas, torch, tensorflow). faster-whisper stays excluded from the bundle and lazy-installs at runtime.
- **GitHub Actions CI** — `.github/workflows/build.yml` builds for Windows, macOS arm64, and Linux on every tag push or `workflow_dispatch`. Packages artifacts as `ReelForge-<os>-<arch>.{zip,tar.gz}` and uploads them via `gh release upload --clobber`, auto-creating a draft release if one doesn't exist.

### Changed
- `core/reframe.build_plan` now accepts `overlays=list[TextOverlay]` and chains a `drawtext=` filter pipeline after reframe/adjustments.
- README shows the logo, describes overlays + binary builds, updates architecture tree.
- Version bumped to 0.4.0; README badge + `__version__` updated.

### Verified
- Two-overlay encode (title card 0–1.5s + lower-third 1.5–3s) renders cleanly (`rc=0`).
- `icon.ico` loads 5 sizes (16/32/48/128/256) into `QIcon`.
- All 6 sidebar tabs (Queue / Adjust / Track / Output / Captions / Text) construct without error.

## [0.3.0] - 2026-04-22

### Added
- **Output tab** — pick encoder, quality (1–100 slider mapped into native codec units), and speed preset. Auto-detects every encoder FFmpeg exposes:
  - NVIDIA NVENC (H.264 + HEVC)
  - Intel QuickSync Video (H.264 + HEVC)
  - AMD AMF (H.264 + HEVC)
  - Apple VideoToolbox (H.264 + HEVC)
  - libx264 / libx265 (CPU fallback)
- **Captions tab** — AI subtitle generation via `faster-whisper`. Lazy-installed on first use (~200 MB one-time download) so the default bootstrap stays fast. Supports every Whisper model size (`tiny` through `large-v3`), 10+ language overrides or auto-detect, and mobile-safe burn-in styling (Segoe UI 24pt, bold, outlined, centered, 60 px bottom margin).
- Per-clip subtitle cache — generated SRTs persist across clip switches in the queue.
- Subtitle burn-in wired into the FFmpeg filter chain via `subtitles=` with cross-platform path escaping (Windows drive letter handling).

### Changed
- `EncodeJob` extended with `encoder`, `quality`, `speed_preset`, `subtitles_path`, `burn_subtitles` fields.
- `core/encode.py` no longer hardcodes libx264 — it consumes the chosen encoder via `core.encoders.encoder_args()`.
- Version bumped to 0.3.0; README badge + `__version__` in `reelforge.py` updated.

### Verified
- Smoke tested CPU (libx264) and NVENC hardware encodes with `-cq`/`-crf` quality mapping.
- Subtitle burn-in renders a 2s test clip with an SRT overlay cleanly (rc=0).
- All 5 sidebar tabs (Queue / Adjust / Track / Output / Captions) construct without error under the new theme system.

## [0.2.0] - 2026-04-22

### Added
- **Batch queue** — drop multiple clips at once, queue panel with per-item status (pending / active / done / failed), click any entry to preview, **Export All** runs them sequentially to a chosen folder.
- **Trim timeline** — dual-thumb range slider on the preview, drag in/out markers; playhead seeks by clicking the track. Exports respect the trim window.
- **Scene-aware Smart Track** — PySceneDetect (with histogram fallback) segments the timeline into scenes; per-scene median viewport locks the camera inside each cut so the pan never crosses a hard transition.
- **Adjustments panel** — brightness / contrast / saturation sliders with live value readouts; applied via FFmpeg `eq=` filter appended to the reframe chain.
- **Tabbed sidebar** — QUEUE · ADJUST · TRACK tabs in the right column.
- **Logo prompts** — five AI image generator prompts for minimal icon, app icon, wordmark, emblem, and abstract marketing art (`assets/logo_prompts.md`).

### Changed
- Version bumped to 0.2.0; README badge + `__version__` in `reelforge.py` updated.
- Removed `ffmpeg-python` dependency — we were calling FFmpeg via `subprocess` directly.

### Verified
- All four reframe modes still encode clean MP4s end-to-end.
- Smart Track now renders with scene-clamped keyframes when scenes are detected.
- Trim start/end respected by FFmpeg `-ss` / `-t` args.

## [0.1.0] - 2026-04-22

### Added
- Initial release.
- Premium PyQt6 GUI with Catppuccin Mocha theme, custom frameless titlebar, glassmorphism panels, shimmer headings, hover lifts.
- Drag-drop video import with animated drop zone.
- Built-in preview player with scrubber.
- Four reframe modes:
  - **Center Crop** — fast center-column crop, zero analysis.
  - **Smart Track** — MediaPipe face detection, pan viewport to follow subjects.
  - **Blur Letterbox** — keeps full frame, fills sides with blurred background.
  - **Manual** — drag viewport to lock crop column.
- Output presets for YouTube Shorts, TikTok, Instagram Reels, and Square (1:1).
- Async FFmpeg encoding with real-time progress bar and log overlay.
- Auto-install bootstrap for first-run dependency setup.
- Turnkey — drops into any FFmpeg-enabled system with a single `python reelforge.py`.
