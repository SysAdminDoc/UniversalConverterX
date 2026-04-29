# StreamKeep — Feature Candidates

## 1. Download Queue with Concurrent Downloads
**Scope:** Large
**What:** Let users queue multiple downloads and run 2-3 concurrently, instead of the current one-at-a-time foreground model.
**Why:** Single biggest friction point. Every user who watches multiple channels or browses VOD lists has to wait for each download to finish before starting the next. The auto-record pool already proves the architecture can handle parallel downloads — but foreground users don't get that. A queue turns StreamKeep from "a downloader" into "a download manager."
**Touches:** `main_window.py` (download tab UI, worker lifecycle), `workers/download.py` (pool management), `workers/finalize.py` (multi-job finalization), config persistence (queue state across restarts). Needs queue UI (table with reorder, pause/resume/cancel per item, progress per item).
**Risks:** Main_window god-object complexity. Disk I/O contention with parallel writes. Bandwidth sharing across concurrent downloads.

---

## 2. Batch VOD Selection from Channel Browse
**Scope:** Medium
**What:** When a user pastes a channel URL, show the full VOD list with multi-select checkboxes, metadata preview (duration, date, views), and a "Download Selected" button that feeds into the download flow.
**Why:** The VOD listing infrastructure exists in every extractor (`list_vods()`), and the monitor's subscribe feature already discovers new VODs — but the UI for manually browsing and cherry-picking VODs from a channel is minimal. Users who want to archive a creator's content currently have to paste URLs one at a time.
**Touches:** Download tab VOD list viewer, extractor `list_vods()` pagination, quality auto-selection logic. Feeds selected items into fetch->quality->download flow.
**Risks:** VOD listing APIs return limited results (Kick: 20, Twitch: 20). Pagination needed for full archives. Quality auto-selection needed for batch (can't prompt per-VOD).

---

## 3. Keyword / Title Filters for Auto-Record
**Scope:** Small
**What:** Add per-channel keyword filters to the monitor so auto-record only triggers when the stream title matches specified terms (e.g., "speedrun", "tournament", "collab").
**Why:** Users who monitor prolific streamers currently get every single live session recorded. Title filtering turns auto-record from "record everything" to "record what I actually want," saving disk space and post-processing time.
**Touches:** `MonitorEntry` model, `monitor_entry_dialog.py`, `_PollTask.run()` in `monitor.py`, auto-record trigger in `main_window.py`, config save/load.
**Risks:** Minimal. Stream titles can change mid-broadcast. Regex vs. simple keyword matching. Edge case: empty title from API.

---

## 4. Persistent Notification History with Log Viewer
**Scope:** Medium
**What:** Persist the notification center to disk and add a searchable log viewer — a dedicated panel or dialog showing all events with timestamps, filtering by severity, and export.
**Why:** Current notification center is in-memory only (50-item ring buffer, lost on restart). Users who run StreamKeep overnight for auto-recording wake up with no idea what happened. A persistent log viewer turns StreamKeep into something you can trust to run unattended.
**Touches:** `notifications.py` (file-backed persistence), new log viewer dialog, `main_window.py` notify call sites, existing `write_log_line` infrastructure.
**Risks:** Log file size management. Parsing structured data back from text logs vs. separate JSON log. UI performance with large log files.

---

## 5. One-Click Re-Download from History
**Scope:** Small
**What:** Add a "Re-download" action to history entries that pre-fills the download tab with the original URL, quality preference, and output location.
**Why:** History entries already store the source URL, quality, and path. If a download was partial, corrupted, or deleted, users currently have to manually copy the URL, re-select quality, pick the folder. Especially painful for auto-recorded content.
**Touches:** History tab context menu in `main_window.py`, reads `HistoryEntry` fields, calls existing fetch->download pipeline with pre-filled values. ~50-80 lines.
**Risks:** Minimal. Original URL may have expired. Quality tier may no longer exist. Need graceful handling when re-fetch fails.

---

## 6. Drag-and-Drop URL & File Import
**Scope:** Small
**What:** Accept dragged URLs from a browser (text/uri-list, text/plain) directly onto the StreamKeep window to auto-fetch, and accept dropped local video files to open them in the Trim/Convert dialog.
**Why:** The clipboard monitor polls every 800ms for copied URLs, which works — but drag-and-drop is the more natural interaction for users who keep StreamKeep open alongside their browser. Every major download manager supports it. For local files, it creates a direct on-ramp to the post-processing pipeline (trim, convert, transcribe) without navigating menus. Two capabilities, one gesture.
**Touches:** `main_window.py` — override `dragEnterEvent` / `dropEvent` on the QMainWindow. URL drops route to the existing `_on_fetch()` path. File drops route to `_open_clip_dialog()` or a new "process local file" entry point. ~60-80 lines of new code. No new modules needed.
**Risks:** Minimal. Platform differences in MIME types (Windows vs. Linux drag payloads). Need to distinguish URL drops from file drops cleanly. Should reject non-media file drops gracefully.

---

## 7. Post-Processing Presets (Saved Profiles)
**Scope:** Medium
**What:** Let users save named post-processing configurations ("Archive Quality", "Quick Share 720p", "Audio Podcast", "Raw — No Processing") and apply them per-download or per-monitored-channel with one click, instead of toggling 10+ individual settings each time.
**Why:** The post-processing pipeline is StreamKeep's most complex settings surface: extract audio, normalize loudness, H.265 re-encode, contact sheet, chapter split, video format/codec/resolution/FPS, audio format/codec/bitrate/sample-rate, source deletion toggle. Power users who process different content differently (e.g., stream archives get H.265 + loudness norm, podcast rips get audio-only + MP3) are re-toggling these settings constantly. Presets turn a 30-second settings dance into a single combo-box pick.
**Touches:** `postprocess/processor.py` (snapshot/restore already exists — presets formalize it), `config.py` (persist named preset dicts), `ui/tabs/settings.py` (preset combo + save/delete/rename buttons), `monitor_entry_dialog.py` (per-channel preset selector), `main_window.py` (apply preset at download start). The `PostProcessor` already takes a snapshot at download time — presets are just named snapshots.
**Risks:** Schema versioning if new post-processing options are added later (presets missing new keys need defaults). UI for managing presets (add/edit/delete/rename) is the bulk of the work. Should ship with 2-3 built-in defaults that users can customize.

---

## 8. Chat-Spike Clip Markers
**Scope:** Medium
**What:** Analyze captured chat logs (`.chat.jsonl`) to detect message-density spikes and surface them as suggested clip timestamps — shown as colored markers on the Trim dialog's filmstrip scrubber and as a "Suggested Clips" list in the History context menu.
**Why:** The app already captures Twitch and Kick chat with full timestamps, and the Trim dialog already has a visual filmstrip. Chat activity spikes are the strongest signal for "something interesting happened here" — a clutch play, a raid, a funny moment. Connecting these two existing features creates an editing assistant that no other VOD ripper offers. Content creators who archive streams would use this constantly.
**Touches:** New analysis function (read `.chat.jsonl`, bucket by time window, find spikes above N standard deviations). `ui/clip_dialog.py` (render spike markers as colored ticks on the filmstrip). History context menu (new "Show chat highlights" action). ~150-200 lines of analysis + ~50 lines of UI integration.
**Risks:** Chat density varies wildly by channel size. Need adaptive thresholds (% above rolling average, not absolute count). Channels with no chat capture get no markers (graceful empty state). Large JSONL files (500k+ messages) need streaming analysis, not full load.

---

## 9. Multi-Range Highlight Reel Export
**Scope:** Medium
**What:** Extend the Trim dialog to support marking multiple time ranges within a single video, then concatenate them into one highlight reel file with crossfade or hard-cut transitions.
**Why:** The current Trim dialog does one contiguous start-end cut. But the core use case for stream archives is extracting 3-5 best moments into a shareable highlight clip. Users currently have to trim each segment separately, then manually concatenate with external tools. This is the natural next step for the existing clip workflow — and it pairs perfectly with chat-spike markers (Feature 8) to auto-suggest ranges.
**Touches:** `ui/clip_dialog.py` (multi-handle filmstrip, range list panel with add/remove/reorder), `postprocess/clip_worker.py` (ffmpeg concat demuxer for multi-range export), existing filmstrip thumbnail infrastructure. The ClipWorker already handles single-range — multi-range adds a concat phase using ffmpeg's `concat` protocol or filter.
**Risks:** UI complexity — multiple draggable ranges on one filmstrip needs careful interaction design (handle overlap, reorder, minimum gap). Transition effects (crossfade) require re-encode even in "stream copy" mode. Should start with hard-cut only (stream-copy compatible) and add transitions as a toggle.

---

## 10. Import/Export Monitor Channel Lists
**Scope:** Small
**What:** Add "Export channels" and "Import channels" actions to the Monitor tab that save/load the monitored channel list as a portable JSON file, including per-channel profiles (quality, schedule, retention, output dir, keywords).
**Why:** Users who run StreamKeep on multiple machines (desktop + always-on server), or communities that share creator watchlists, need a way to transfer their monitor setup without manually re-adding every channel. The config already serializes `monitor_channels` — this just exposes it as a user-facing action with a file picker. Also serves as a backup mechanism for the most tedious-to-recreate part of the config.
**Touches:** `main_window.py` — two new actions in Monitor tab toolbar or context menu. Export: `json.dumps(cfg["monitor_channels"])` to user-chosen `.json` file. Import: read file, validate entries, merge with existing (skip duplicates by `channel_id`). ~80-100 lines.
**Risks:** Minimal. Need to handle import conflicts (channel already monitored). Per-channel output dir paths may not exist on the target machine (warn, fall back to global). Schema forward-compatibility if monitor entry fields change between versions.

---

## 11. Keyboard Shortcuts
**Scope:** Small-Medium
**What:** Add keyboard shortcuts for every common action: Ctrl+V to paste-and-fetch a URL, Enter to start download, Escape to stop, Ctrl+1/2/3/4/5 to switch tabs, Delete to remove queue/history/monitor items, Ctrl+A to select all in tables, Ctrl+E to export, Ctrl+F to focus the search box on History.
**Why:** There are currently zero `QShortcut` bindings in the entire application. For a power-user tool that people leave running all day, keyboard-driven operation is essential. Users who queue multiple downloads, trim clips, and manage monitors shouldn't have to reach for the mouse for every action. This is the kind of polish that separates a tool from a product.
**Touches:** `main_window.py` — add `QShortcut` bindings in the constructor, wired to existing slot methods. No new logic needed, just wiring. Tab-switching shortcuts target the existing `QStackedWidget`. Action shortcuts call existing `_on_fetch()`, `_on_download()`, `_on_stop()`, etc. ~60-80 lines of shortcut registration.
**Risks:** Minimal. Need to avoid conflicts with OS-level shortcuts (Ctrl+C is copy, not cancel). Should show shortcut hints in tooltips and context menus. Some shortcuts should be tab-context-aware (Delete means different things on History vs. Monitor vs. Queue).

---

## 12. Filename Template Live Preview
**Scope:** Small
**What:** Add a live preview line below the folder and file template inputs in Settings that renders the current template with sample data, updating as the user types. Example: typing `{channel}/{date} - {title}` shows `xQc/2026-04-12 - Just Chatting Marathon`.
**Why:** Template misconfiguration is a "discover at download time" problem today. Users type a template, download, and only then see if their output path makes sense. A live preview eliminates trial-and-error and makes the template variables self-documenting — users can see what `{platform}`, `{quality}`, `{date}` expand to without reading docs.
**Touches:** `ui/tabs/settings.py` (add QLabel below each template input), `utils.py` (the `render_template()` function already exists — call it with sample context). Wire `textChanged` signal on the template inputs to a debounced preview update. ~40-50 lines.
**Risks:** Minimal. The sample data should be representative (not empty strings). If `render_template()` throws on malformed templates, catch and show "Invalid template" in red instead of a preview.

---

## 13. Storage Tab Filtering & Analytics
**Scope:** Medium
**What:** Add filter dropdowns (Platform, Channel) and a date-range picker above the Storage table, plus a "Total Archive Size" trend sparkline showing growth over time. Let users quickly answer "how much Twitch content do I have?" or "what did I record last week?"
**Why:** The Storage tab currently shows a flat list of every recording folder with no filtering. Users with large archives (100+ recordings across multiple platforms/channels) can't quickly find or analyze their content. The data is already there — `scan_storage()` returns platform, channel, size, and date for every group — but the UI doesn't expose any way to slice it.
**Touches:** Storage tab builder (`ui/tabs/storage.py`) — add filter combo boxes populated from scan results, wire `currentIndexChanged` to table filtering. Trend sparkline: persist daily total-size snapshots in config (one int per day, rolling 90 days), render as a simple QPainter line in a small widget. ~150-200 lines.
**Risks:** Filter state should persist across tab switches but reset on rescan. Sparkline data accumulation needs the app to actually run regularly (no data = no trend). Large archives may have slow scans — the existing scan is already synchronous, so filtering should be client-side on cached results.

---

## 14. History-to-Disk Sync (Orphan Detection)
**Scope:** Small
**What:** On History tab load, check whether each entry's file path still exists on disk. Mark orphaned entries (file deleted/moved) with a warning icon and "(File missing)" badge. Add a "Clean up orphans" action that removes all entries whose files no longer exist.
**Why:** History entries are permanent records — they persist even after the user deletes the downloaded files from disk (via Storage tab, file explorer, or retention policies). Over time, History accumulates stale entries that point to nothing. Users double-click an entry expecting to open the folder, and nothing happens. This creates distrust in the History tab's accuracy.
**Touches:** `main_window.py` — in `_refresh_history_table()`, add a `Path(entry.path).exists()` check per row. If missing, set a warning icon in the first column and dim the row. Add a "Remove missing" button or context menu action that filters `self._history` to entries with valid paths. ~40-60 lines.
**Risks:** Minimal. The `exists()` check is fast for local paths but could be slow for network drives — should run async or with a timeout. Entries with empty paths (legacy data) should be treated as "unknown" not "missing."

---

## 15. Webhook Expansion (Slack, Telegram, Ntfy)
**Scope:** Medium
**What:** Extend the webhook system beyond Discord to support Slack (incoming webhooks), Telegram (Bot API), and ntfy.sh (push notifications to phone). Auto-detect the target from the URL and format the payload accordingly.
**Why:** Discord webhooks work great for Discord users, but StreamKeep's user base includes people who live in Slack workspaces, use Telegram for notifications, or prefer lightweight push via ntfy. The webhook infrastructure already exists (`_send_webhook()` with fire-and-forget curl) — extending it to detect the target URL and format appropriately is a natural evolution. Especially valuable for users running StreamKeep unattended (auto-record overnight) who want mobile push notifications when a channel goes live or a download completes.
**Touches:** `main_window.py` `_send_webhook()` — add URL pattern detection for Slack (`hooks.slack.com`), Telegram (`api.telegram.org/bot`), ntfy (`ntfy.sh` or custom ntfy server). Each target gets its own payload formatter. Slack: blocks-based message. Telegram: `sendMessage` with markdown. Ntfy: plain POST with title/priority headers. ~100-120 lines in `_send_webhook()`, plus a "Webhook type" indicator in Settings.
**Risks:** Telegram requires a bot token + chat ID (two fields instead of one URL). Ntfy requires a topic. Settings UI needs to accommodate different target types gracefully. Testing is manual (no mock server). Rate limits vary by service.

---

## 16. Download Speed & ETA Dashboard
**Scope:** Small-Medium
**What:** Add a live speed readout (e.g., "12.4 MB/s") and ETA countdown ("~8 min remaining") to the Download tab's hero metrics row during active downloads. Show a mini speed history sparkline (last 60 seconds) so users can see if their connection is stable or fluctuating.
**Why:** During downloads, the only progress indicator is the per-segment progress bar. Users have no visibility into throughput, can't tell if a download is stalling, and can't estimate when it'll finish. The download worker already emits progress signals with byte counts and timestamps — the data exists, it just isn't surfaced. For large VODs (multi-GB, multi-hour), speed and ETA visibility is the difference between "is this working?" anxiety and confidence.
**Touches:** `main_window.py` — add speed/ETA labels to the existing hero metrics card row. Calculate speed from `_on_dl_progress()` signal data (bytes delta / time delta, smoothed over 5-second window). ETA from remaining bytes / smoothed speed. Sparkline: rolling deque of 60 speed samples, rendered as a QPainter polyline in a 120x30 widget. ~80-100 lines.
**Risks:** Speed calculation needs smoothing to avoid jitter. ETA is unreliable for live streams (unknown total). Sparkline rendering should be lightweight (no full repaint per sample — incremental scroll). HLS downloads report segment-level progress, not byte-level, so speed calculation may be coarser than direct HTTP downloads.

---

## 17. Deep Archive: VOD Listing Pagination
**Scope:** Medium
**What:** Extend the VOD list viewer to support pagination — "Load more" button that fetches the next page of VODs from the platform API. Currently Kick returns 20 and Twitch returns 20. For full channel archives, users need access to hundreds of VODs.
**Why:** The batch VOD selection (Feature 2) is limited by the extractors' single-page returns. A creator with 500 VODs can only see the most recent 20. Users who want to archive an entire channel — a common use case for preservation — currently have to find and paste individual VOD URLs manually. Pagination in the extractors + a "Load More" UX in the VOD viewer unlocks true bulk archival.
**Touches:** `extractors/kick.py` (add `offset` param to `list_vods()`), `extractors/twitch.py` (add cursor-based pagination to GraphQL VOD query), `extractors/ytdlp.py` (increase `--playlist-items` range), `workers/fetch.py` (thread pagination params), `main_window.py` VOD table (add "Load More" button below the table that triggers the next page fetch). ~100-150 lines across extractor + UI.
**Risks:** API rate limits on Kick/Twitch for rapid pagination. Large VOD lists consume memory (1000 VODInfo objects is fine, 10,000 could be a concern). Need a sensible upper bound or lazy-load. Some old VODs may have expired/deleted source URLs — handle gracefully in batch download.

---

## 18. Per-Download Settings Override
**Scope:** Medium
**What:** Add a collapsible "Advanced" panel in the Download tab (below the output folder picker) that lets users override global settings for this specific download: quality preference, post-processing preset (ties into Feature 7), output template, rate limit, and parallel connections. Overrides apply only to the current download, not saved globally.
**Why:** The current workflow forces users to change global Settings every time they want a different configuration for one download. Example: user normally records at 1080p but wants one specific VOD at source quality. Or they want to extract audio from a podcast download but not from a gaming stream. Per-download overrides let users make one-off decisions without polluting their defaults. The PostProcessor snapshot mechanism already captures settings at download time — overrides just modify the snapshot.
**Touches:** `main_window.py` Download tab — add collapsible QFrame with override widgets (quality combo, post-process toggles, rate limit input, template input). On `_on_download()`, merge overrides into the worker context / PostProcessor snapshot. Clear overrides after download starts. ~120-150 lines of UI + plumbing.
**Risks:** UI clutter — the collapsible panel must default to hidden and only expand on click. Override state should clear after each download to avoid "sticky" surprises. Need clear visual indicator when overrides are active ("Custom settings applied" badge).

---

## 19. Browser Extension: Right-Click Context Menu & Multi-Tab Send
**Scope:** Small
**What:** Add a browser context menu item ("Send link to StreamKeep") that appears when right-clicking any link on a webpage, plus a "Send all tabs to StreamKeep" action in the extension popup that batches every open tab's URL into a single queue submission.
**Why:** The current browser extension requires: open popup, click "Send to Fetch/Queue." For users browsing a forum thread with 10 VOD links, that's 10 popup interactions. A right-click context menu on links is the standard UX for "send this to my external tool" — every download manager extension works this way. Multi-tab send covers the "I have 15 tabs open with VODs I want to grab" scenario.
**Touches:** `browser-extension/manifest.json` (add `contextMenus` permission), `browser-extension/background.js` (register context menu item, handle click → POST to `/send_url`), `browser-extension/popup.js` (add "Send all tabs" button that queries `chrome.tabs` and POSTs each URL). Server-side: `local_server.py` already handles `/send_url` — no changes needed. ~60-80 lines in extension code.
**Risks:** Minimal. Context menu permission is low-risk. Multi-tab send could overwhelm the queue if user has 50 tabs — should confirm "Send 50 URLs to queue?" before firing. Need to filter out non-http tabs (chrome://, about:, extensions). Rate-limit POSTs to avoid flooding the local server.

---

## 20. Dark / Light Theme Toggle
**Scope:** Medium
**What:** Add a theme switcher in Settings (Dark / Light / System) with a full Catppuccin Latte (light) stylesheet alongside the existing Mocha (dark). Apply the theme change instantly without restart.
**Why:** StreamKeep currently ships dark-only (Catppuccin Mocha). Users who work in bright environments, have visual accessibility needs, or simply prefer light themes have no option. The Catppuccin palette system has a ready-made light variant (Latte) with the same semantic color slots — the stylesheet structure can be reused with swapped color values. A "System" option that follows the OS dark/light preference makes the app feel native.
**Touches:** `theme.py` — add a second `CAT_LATTE` dict with Catppuccin Latte colors, a `build_stylesheet(palette)` function that takes either palette and returns QSS. `main_window.py` — add theme combo in Settings, wire `currentIndexChanged` to `app.setStyleSheet(build_stylesheet(new_palette))`. Persist choice in config. ~80-100 lines in `theme.py`, ~20 lines in Settings UI.
**Risks:** Some widgets may have hardcoded colors outside the stylesheet (inline `setStyleSheet()` calls in `main_window.py`). These need to be audited and converted to palette references. Thumbnails and icons that assume dark background may look wrong on light. Gradient backgrounds on banners need light-mode variants. Testing surface is large (every widget in every tab).

---

## 21. Pre-Download Time-Range Crop
**Scope:** Small-Medium
**Inspired by:** Twitch Leecher DX
**What:** Let users specify a start and end timestamp *before* downloading, so only that portion of the VOD is fetched. Instead of downloading a 6-hour stream and trimming to the 20 minutes you want, you download only those 20 minutes.
**Why:** This is the single most-requested feature in VOD ripper communities. StreamKeep has post-download trimming (ClipDialog), but users still download the full VOD first — burning bandwidth, disk space, and time. For HLS streams, the segment list is already known after fetch; filtering to a time range before handing segments to the download worker is the natural optimization. yt-dlp's `--download-sections` flag proves the demand. Twitch Leecher DX's time-range cropping is cited as its killer feature over competing tools.
**Touches:** Download tab UI — add optional start/end time inputs (HH:MM:SS) next to the segment controls, visible after fetch populates stream metadata. `workers/download.py` — filter `segments` list to only those within the time range before starting. For yt-dlp direct downloads, pass `--download-sections *start-end`. ~80-100 lines.
**Risks:** HLS segments have fixed boundaries (usually 2-10 seconds), so the crop is keyframe-aligned, not frame-exact — users should see "approximate" indicator. Live streams can't be pre-cropped (no duration known). Need clear UX distinction between "pre-crop" (download less) and "trim" (cut after download).

---

## 22. Chat-to-Video Render Engine
**Scope:** Large
**Inspired by:** TwitchDownloader (lay295)
**What:** Render captured chat logs (`.chat.jsonl`) into an animated video overlay — scrolling messages with username colors, badges, and emotes (including BTTV/FFZ/7TV third-party emotes) — that can be played side-by-side with the stream recording or composited as an overlay.
**Why:** TwitchDownloader's chat render is its most-loved feature and the gold standard for chat archival. StreamKeep already captures chat as JSONL and generates `.ass` subtitles, but `.ass` renderers in video players are crude — no emotes, no badges, no animated GIFs, no Twitch-like scrolling feel. A proper video render produces a standalone `.mp4` that looks like actual Twitch chat. Content creators use this for YouTube uploads, compilations, and highlight reels. No other Python-based VOD tool offers this.
**Touches:** New `postprocess/chat_render_worker.py`. Reads `.chat.jsonl`, fetches emote images from CDN (BTTV/FFZ/7TV APIs) with local cache, renders frames using Pillow or cairo (text + images composited per-frame), pipes to ffmpeg for video encoding. Expose as right-click action on History/Storage entries that have `.chat.jsonl` files. Settings: render width, font size, message display duration, background opacity.
**Risks:** Largest scope item on this list. Emote fetching requires network (first run per emote set). Rendering is CPU-intensive for long streams (could take 10-30 min for a 4-hour VOD). Animated emotes (GIFs) add complexity. Should offer a "preview first 60 seconds" mode before committing to full render. Consider using ffmpeg drawtext filter chain as a lighter alternative to per-frame Pillow rendering.

---

## 23. Deleted VOD Recovery Wizard
**Scope:** Medium
**Inspired by:** TwitchRecover, VodRecovery
**What:** A recovery wizard that attempts to reconstruct CDN URLs for deleted or expired Twitch VODs using stream metadata from tracker sites (TwitchTracker, SullyGnome, Streamscharts). User enters a streamer name + approximate date, the wizard fetches known stream IDs from tracker sites, brute-forces the CDN URL pattern, and tests if the VOD segments are still cached on Twitch's CDN.
**Why:** Twitch VODs expire after 14-60 days depending on the streamer's plan. Deleted VODs and sub-only content are the most painful losses for archivists. The CDN often retains segments for weeks after the VOD is "deleted" from the platform. TwitchRecover and VodRecovery have proven this approach works and have large user communities. No GUI tool integrates this natively — users currently run separate CLI tools. Integrating it into StreamKeep's extractor system would make it seamless.
**Touches:** New `extractors/twitch_recover.py` — scrape TwitchTracker for stream IDs given a channel + date range, construct CDN URL candidates (`https://d1m7jfoe9zdc1j.cloudfront.net/{hash}_{streamername}_{streamid}_{timestamp}/chunked/index-dvr.m3u8`), test with HEAD requests, return valid URLs as `StreamInfo`. UI: new "Recover VOD" action in Download tab (separate from Fetch), opens a small dialog for channel name + date range. ~200-250 lines.
**Risks:** Twitch actively rotates CDN patterns — the URL construction may break. Tracker sites may rate-limit or change their page structure. Recovery is not guaranteed (CDN purges eventually). Ethical consideration: sub-only VODs were access-gated for a reason — should warn the user. This feature has a maintenance burden as Twitch changes infrastructure.

---

## 24. Event Hook System (Pre/Post Scripts)
**Scope:** Small-Medium
**Inspired by:** JDownloader Event Scripter, Stacher pre/post scripts, Sonarr custom scripts
**What:** Let users configure shell scripts or commands that fire on lifecycle events: `on_download_start`, `on_download_complete`, `on_download_error`, `on_channel_live`, `on_auto_record_start`, `on_auto_record_end`, `on_transcode_complete`. Pass event context as environment variables (`$SK_TITLE`, `$SK_CHANNEL`, `$SK_PLATFORM`, `$SK_PATH`, `$SK_QUALITY`, `$SK_URL`).
**Why:** Power users want StreamKeep to be a node in their automation pipeline: download completes -> upload to NAS -> notify Plex -> send Discord message -> run custom transcription -> generate thumbnail for social media. The webhook system handles one notification target, but hooks enable arbitrary automation without StreamKeep needing to support every integration natively. JDownloader's Event Scripter and Sonarr's custom scripts are the most-cited features for power users in those communities.
**Touches:** New `hooks.py` module — load hook config from `config["hooks"]` (dict of event_name -> command string), `fire_hook(event, context_dict)` runs the command as a subprocess with env vars set. Wire into existing signal handlers in `main_window.py` (the completion/error/live-detection slots). Settings UI: a simple table (Event | Command) with add/edit/remove. ~100-120 lines.
**Risks:** Security — arbitrary command execution is powerful but dangerous. Should warn on first configure ("Scripts run with your user permissions"). Commands must be non-blocking (fire-and-forget subprocess) to avoid stalling the UI. Failed hooks should log but never block downloads. Need timeout (30s default) to prevent runaway scripts.

---

## 25. Quality Auto-Upgrade
**Scope:** Medium
**Inspired by:** Sonarr/Radarr automatic quality upgrades
**What:** When a monitored channel's VOD becomes available at a higher quality than what was auto-recorded live, automatically re-download the VOD portion and replace the live capture. Live recordings are often 720p or have encoding artifacts; the processed VOD published hours later is typically higher quality.
**Why:** This is the #1 complaint in stream archival communities: "I auto-recorded the live stream at 720p, but the VOD is now available at 1080p source quality." Sonarr/Radarr's auto-upgrade pattern proves this workflow: grab what's available now, upgrade when better becomes available. StreamKeep already has the channel monitor checking for new VODs (`subscribe_vods`) — extending it to check quality against existing recordings is a natural evolution.
**Touches:** `monitor.py` — after detecting a new VOD, compare its quality to the existing recording in that channel's output dir (read `metadata.json` for recorded quality). If the new VOD's best quality exceeds the recorded quality by a configurable threshold, queue a re-download. `MonitorEntry` gets `auto_upgrade: bool` and `min_upgrade_quality: str` fields. `monitor_entry_dialog.py` — add toggle and quality floor. ~120-150 lines.
**Risks:** Disk space — keeping both old and new until upgrade completes. Need atomic swap (download new, verify, delete old). False positives if quality detection is unreliable (platform reports 1080p but actual bitrate is lower). Should compare bitrate, not just resolution label. User must opt-in per channel.

---

## 26. Silence / Dead Air Removal
**Scope:** Small
**Inspired by:** CapCut AutoCut, Descript, jumpcutter
**What:** Add a post-processing option that detects and removes silence/dead-air segments from recordings using FFmpeg's built-in `silencedetect` filter. Configurable noise floor threshold (dB) and minimum silence duration. Outputs a trimmed version with dead air cut out, or a "jump cut" version with silences replaced by speed-up (2x-4x).
**Why:** Stream VODs are full of dead air: "be right back" screens, AFK segments, pre-stream silence, post-stream wind-down. A 4-hour stream might have 30-60 minutes of dead air. Auto-removing it saves storage and makes the archive more watchable. FFmpeg's `silencedetect` is fast (processes at 50-100x realtime), requires no ML, and is already a dependency. CapCut's AutoCut and Descript's silence removal are among their most-used features.
**Touches:** `postprocess/processor.py` — add `remove_silence` preset. Implementation: (1) run `ffmpeg -af silencedetect=noise=-30dB:d=3` to get silence timestamps, (2) build a concat filter or segment list that skips silent ranges, (3) re-mux with stream copy (fast) or re-encode if user wants speed-up mode. Expose as checkbox in Settings post-processing section + right-click action on History entries. ~80-100 lines.
**Risks:** Threshold tuning — what counts as "silence" varies by content (music streams have different floor than talk streams). Should expose noise floor as a slider (-20dB to -50dB). Stream-copy mode can only cut at keyframes (some residual silence). Re-encode mode is frame-exact but slower. Background music during "BRB" screens may not register as silence.

---

## 27. Full-Text Transcript Search Across Archive
**Scope:** Medium
**Inspired by:** Tube Archivist, ReChat, Descript
**What:** Index all generated transcripts (`.srt`, `.vtt`, `.transcript.json`) into a searchable database. Add a search bar to the History tab that searches transcript text, returning results with timestamps and VOD titles. Click a result to jump to that moment in the Trim dialog or open the recording at that timestamp.
**Why:** "What stream did they talk about X?" is the question every archivist asks. With transcription already generating SRT/VTT/JSON for every processed recording, the text data exists — it's just not searchable. Tube Archivist's full-text subtitle search is its most differentiating feature over plain media servers. ReChat's chat-search-to-timestamp is the most-cited feature by Twitch archivists. This turns StreamKeep's archive from "a folder of videos" into "a searchable knowledge base."
**Touches:** New `search.py` module — on transcript generation, parse segments into a lightweight SQLite FTS5 table (columns: recording_id, text, start_sec, end_sec). History tab gets a "Search transcripts" toggle on the search bar that queries FTS5 instead of title/path matching. Results show matching text snippet + timestamp + recording title. Double-click opens ClipDialog at that timestamp. ~150-180 lines (SQLite FTS5 is built into Python's sqlite3 module).
**Risks:** Requires transcripts to exist (only works for recordings that have been transcribed). Should surface "N recordings not yet transcribed" and offer batch transcription. FTS5 index grows with archive size but SQLite handles millions of rows efficiently. Need to handle re-transcription (update index, don't duplicate). Initial index build for large archives takes time — run async on first enable.

---

## 28. System Tray Badge with Live Count
**Scope:** Small
**Inspired by:** Streamlink Twitch GUI
**What:** Show a badge overlay on the system tray icon indicating the number of currently-live monitored channels and active downloads. Example: red badge "3" means 3 channels are live. Clicking the tray icon shows a compact dropdown: live channels with "Record" buttons, active downloads with progress, and recent notifications.
**Why:** Streamlink Twitch GUI's tray badge is its most-loved UX pattern — users glance at the taskbar and instantly know if anyone is live without opening the app. StreamKeep users who run the app minimized for auto-recording currently have zero visibility into what's happening without opening the window. A tray badge + compact dropdown turns StreamKeep into a passive monitoring dashboard.
**Touches:** `main_window.py` — create `QSystemTrayIcon` with dynamic icon overlay (QPainter to draw badge circle + count on base icon). Wire to `ChannelMonitor.status_changed` signal to update count. Tray context menu: list live channels (click to record), active downloads (with % progress), last 5 notifications, Quit. ~80-100 lines.
**Risks:** Minimal. QSystemTrayIcon is well-supported on Windows. Badge overlay rendering needs to work at multiple DPI scales. On macOS, tray icon badges work differently (monochrome). The compact dropdown must not duplicate the full Monitor tab — keep it lightweight (channel name + status only, not full controls).

---

## 29. WhisperX Upgrade (Word-Level Timestamps + Speaker Diarization)
**Scope:** Medium
**Inspired by:** WhisperX, Buzz, Descript
**What:** Replace or augment the current faster-whisper/whisper.cpp transcription backend with WhisperX, which adds: (1) word-level timestamps via wav2vec2 forced alignment, (2) speaker diarization via pyannote-audio (labels "Speaker 1", "Speaker 2"), and (3) VAD pre-filtering to reduce hallucination on silence. Output enriched transcripts with per-word timing and speaker labels.
**Why:** StreamKeep's current transcription produces sentence-level SRT/VTT — useful for subtitles but too coarse for editing or search. Word-level timestamps enable transcript-based editing (Feature 9's multi-range highlight reel becomes "select text ranges to export"), clickable-word-to-timestamp navigation, and karaoke-style subtitle rendering. Speaker diarization is critical for streams with co-hosts, guests, or interviews — without it, the transcript is an undifferentiated wall of text. WhisperX is the most popular enhancement to faster-whisper with 13K+ GitHub stars.
**Touches:** `postprocess/transcribe_worker.py` — add WhisperX as a preferred backend (fall back to faster-whisper if not installed). Output new `.transcript.json` schema with word-level entries (`{word, start, end, speaker}`). Existing SRT/VTT generation adapts to use word timestamps for tighter subtitle timing. Settings: "Enable speaker diarization" toggle (requires HuggingFace token for pyannote models). ~120-150 lines of backend changes.
**Risks:** WhisperX requires `torch` + `torchaudio` (heavy dependencies, ~2GB). Speaker diarization needs a free HuggingFace token and ~1GB model download. GPU strongly recommended for reasonable speed. Should be opt-in with clear dependency instructions. Falls back gracefully to current faster-whisper if WhisperX isn't installed.

---

## 30. Scene Detection + Storyboard View
**Scope:** Medium
**Inspired by:** PySceneDetect, Plex/Jellyfin trickplay thumbnails
**What:** Run scene change detection on downloaded recordings and generate a storyboard — a grid of thumbnails at each scene boundary with timestamps. Display this as a browsable panel in the History tab or Trim dialog. Users can click any scene thumbnail to jump to that timestamp. Optionally use scene boundaries as auto-generated chapter markers.
**Why:** Long VODs (4-8 hours) are opaque — the existing 20-frame filmstrip in the Trim dialog is too sparse to navigate a full stream. Scene detection identifies every visual transition (camera angle changes, screen switches, game loads, "BRB" screens, raid overlays) and produces a dense, navigable storyboard. Plex and Jellyfin generate similar "trickplay" thumbnails for timeline scrubbing — it's an expected feature in media management tools. PySceneDetect processes video at 100+ fps on CPU, is pip-installable, and has a clean Python API.
**Touches:** New `postprocess/scene_worker.py` — runs PySceneDetect `ContentDetector` on the recording, extracts a thumbnail at each scene boundary, saves as a cached sprite sheet (`.storyboard.jpg`). `ui/clip_dialog.py` — add a scrollable storyboard panel below the filmstrip (click to jump). History right-click: "Generate storyboard" action. Config: scene detection threshold (sensitivity), max scenes cap. ~150-180 lines.
**Risks:** PySceneDetect is an optional dependency (~pip install scenedetect). Processing time scales with video length (~1 min per hour of footage on CPU). Should run async with progress. Very long streams could produce hundreds of scenes — need scrollable/paginated UI with a sensible max (cap at 200 scenes, user can lower threshold). Scene detection on streams with static cameras (just-chatting, podcasts) may produce very few results — warn if <5 scenes detected.

---

## 31. Social Clip Export (Vertical / Platform Presets)
**Scope:** Medium
**Inspired by:** Medal.tv, CapCut, Clipchamp
**What:** Add platform-specific export presets to the Trim/Clip dialog: TikTok (9:16, 1080x1920, max 10 min), YouTube Shorts (9:16, max 60s), Instagram Reels (9:16, max 90s), Twitter/X (16:9 or 1:1, max 2:20). Each preset auto-crops the 16:9 source to vertical with a draggable crop region preview, re-encodes at the target resolution, and optionally burns in captions from the Whisper transcript.
**Why:** Stream archivists and content creators are the same audience. The #1 thing creators do with saved VODs is clip highlights for social platforms. Today that requires exporting from StreamKeep, importing into CapCut/Premiere, reformatting, and re-exporting. A built-in vertical export with caption burn-in eliminates the round-trip. The core FFmpeg command is simple (`-vf "crop=ih*9/16:ih,scale=1080:1920"`), and StreamKeep already has Whisper for captions and ClipDialog for trimming. Medal.tv's one-click-to-platform-ready export is its most-cited feature.
**Touches:** `ui/clip_dialog.py` — add a "Platform" dropdown (Original / TikTok / Shorts / Reels / Twitter) that adjusts canvas preview and sets output resolution. Add a draggable crop rectangle on the preview frame for vertical crop positioning. `postprocess/clip_worker.py` — add crop/scale filter chain + optional subtitle burn-in via FFmpeg `drawtext` or `subtitles` filter. ~200-250 lines.
**Risks:** Caption generation requires Whisper (optional dep). Crop region preview needs QGraphicsView overlay work — moderate UI effort. Vertical crop from a "just chatting" facecam is easy, but from a fullscreen game it may cut important HUD elements — users need the draggable crop to adjust. Re-encode is mandatory for format change (no stream-copy shortcut).

---

## 32. Auto-Cleanup Lifecycle Policies
**Scope:** Medium
**Inspired by:** Pocket Casts, AntennaPod, Overcast
**What:** Extend retention from count-only (current "keep last N" per channel) to a full lifecycle policy engine with time-based rules ("delete after 30 days"), watch-status rules ("delete after viewed"), size-based rules ("when storage exceeds X GB, delete oldest watched first"), and a favorites exemption ("never auto-delete favorited recordings"). Per-channel overrides and a global default. Always show a cleanup preview before executing.
**Why:** The current `retention_keep_last` field on `MonitorEntry` is count-based only — it has no concept of time, viewing status, or priority. Users running auto-record on 10+ channels accumulate terabytes fast. Podcast apps solved this years ago with tiered cleanup: played episodes go first, then old unplayed, never favorites. The "cleanup preview" pattern (Pocket Casts shows exactly what will be deleted before you confirm) is critical for trust. Without lifecycle policies, users either hoard everything until their disk fills or manually delete, which defeats the purpose of auto-record.
**Touches:** New `lifecycle.py` module — evaluate retention rules against recordings (read from `metadata.json` + file timestamps). `MonitorEntry` gets `retention_max_days: int`, `retention_delete_watched: bool` fields. `models.py` gets a `favorite: bool` field on `HistoryEntry`. `main_window.py` — add "Manage storage policies" in Settings, cleanup preview dialog (table of recordings that would be deleted with size totals), manual "Run cleanup now" button. Wire lifecycle evaluation to the existing post-auto-record retention path. ~150-200 lines.
**Risks:** "Auto-delete" is destructive — must always use `send2trash` (recycle bin), never permanent delete. Cleanup preview is mandatory UX (never silently delete). "Watched" status requires a way to mark recordings as viewed (see Feature 38). Without watch tracking, only time-based and count-based rules work initially.

---

## 33. Media Server Auto-Import (Plex / Jellyfin / Emby)
**Scope:** Small-Medium
**Inspired by:** Sonarr→Plex, Radarr→Jellyfin integration pattern
**What:** After a download completes, automatically copy or hardlink the recording into a media server library folder with the correct naming convention, write an NFO sidecar with metadata, and trigger a library scan via the server's API. Configure per media server: type (Plex/Jellyfin/Emby), library root path, API URL + token. Optionally map channels to "series" with auto-assigned season/episode numbers (Season = year, Episode = sequence).
**Why:** Many StreamKeep users also run Plex or Jellyfin as their viewing platform. Today, downloads land in StreamKeep's output folder and the user manually moves them into the media library structure. StreamKeep already writes `metadata.json` and NFO files — the data exists, it just doesn't flow to the media server automatically. Sonarr and Radarr proved that auto-import with library scan trigger is the #1 most-valued integration for media server users. The implementation is lightweight: file copy + one HTTP GET (Plex) or POST (Jellyfin) to trigger the scan.
**Touches:** New `integrations/media_server.py` — functions for Plex (`GET /library/sections/{id}/refresh?X-Plex-Token={token}`), Jellyfin (`POST /Library/Refresh` with API key), Emby (same as Jellyfin). File copy/hardlink with naming template (`{Channel}/Season {Year}/{Channel} - S{Year}E{Seq} - {Title}.mp4`). NFO writer already exists in `metadata.py` — reuse it. Settings UI: server config form (type, URL, token, library path). Wire to `_on_all_done()` in `main_window.py`. ~120-150 lines.
**Risks:** Hardlinks only work on the same filesystem (fall back to copy). Library scan can be slow for large libraries — trigger a targeted scan on the specific folder if the API supports it. API tokens are sensitive — store encrypted or warn the user. Plex authentication is complex (requires plex.tv OAuth); Jellyfin/Emby are simpler (static API key).

---

## 34. Audio Waveform in Trim Dialog
**Scope:** Small
**Inspired by:** DaVinci Resolve, Audacity, Descript
**What:** Show an audio waveform visualization strip below the filmstrip in the Trim/Clip dialog. Extract audio peaks via FFmpeg, render as a filled amplitude envelope using QPainter. Clicking/dragging on the waveform seeks the video. Overlay silence detection markers (tinted regions where audio drops below a threshold) to help users find dead air, intermissions, and speech boundaries.
**Why:** The current Trim dialog has a 20-frame visual filmstrip — useful for finding scene changes but useless for finding audio events (someone starts talking, music stops, crowd reacts). Waveform visualization is the standard editing tool for audio-aware trimming. Every professional editor (Premiere, DaVinci, Descript) shows waveforms in the timeline. For podcast-style content and "just chatting" streams where the video is static but the audio varies, the waveform IS the timeline. The implementation is lightweight: FFmpeg extracts raw PCM, NumPy computes min/max peaks per pixel, QPainter draws vertical lines.
**Touches:** `ui/clip_dialog.py` — add a `WaveformWidget(QWidget)` below the filmstrip. On dialog open, extract audio peaks in a background worker (`ffmpeg -i input.mp4 -ac 1 -f s16le -ar 8000 pipe:1` → NumPy reshape → min/max per pixel column). Cache peaks as `.waveform.bin` alongside the video. Render with QPainter in `paintEvent`. Sync cursor position with the filmstrip scrubber. ~200 lines for the widget + worker.
**Risks:** Peak extraction takes a few seconds for long videos (8000 Hz mono = ~1 MB/min of audio — manageable). NumPy is an optional dependency (fall back to pure-Python peak computation if unavailable, just slower). The waveform must resize cleanly when the dialog resizes. Stereo→mono downmix in FFmpeg is trivial (`-ac 1`).

---

## 35. Tags & Smart Collections
**Scope:** Medium
**Inspired by:** Apple Photos smart albums, Lightroom keywords, Eagle, Raindrop.io
**What:** Add a tagging system to recordings: user-defined tags (click to add, autocomplete from existing tags) plus auto-generated tags at download time (channel, platform, game/category from stream metadata, duration bucket, resolution). Add smart collections — saved filter rules that auto-populate (e.g., "All Valorant streams from 2026", "Unwatched from favorite channels", "Long VODs > 4 hours"). Display as a filterable sidebar on the History/Storage tabs.
**Why:** StreamKeep's library is currently a flat list searchable by title/platform/path. Once a user has 100+ recordings, they need structured navigation. Tags are the universal solution — they're more flexible than folders (a recording can have multiple tags), cheaper than AI classification, and familiar from every photo/bookmark/note app. Smart collections make the tags useful without manual curation — the auto-tag pipeline does the work, and smart collections surface the interesting views. No existing VOD download tool offers this.
**Touches:** New `tags.py` — SQLite FTS5 table for tags, many-to-many junction table. Auto-tag hook in download completion path (extract channel, platform, game category from stream metadata). `main_window.py` — tag chips on History/Storage rows, tag filter sidebar, smart collection editor dialog (AND/OR rule builder with field/operator/value rows). Persist collections as JSON in config. ~300-400 lines total (tag CRUD ~100, auto-tag ~80, filter sidebar ~120, collection editor ~100).
**Risks:** SQLite dependency for tags (separate from config.json — but Python has sqlite3 built in). Auto-tagging is only as good as the metadata available at download time (yt-dlp sources have less metadata than native extractors). Smart collection editor UI is the most complex widget — start with quick-filter chips (simpler) and add the full rule builder later. Tag namespace pollution (hundreds of auto-tags) — need a "system tags" vs. "user tags" distinction.

---

## 36. Batch Rename Studio
**Scope:** Small-Medium
**Inspired by:** Bulk Rename Utility, Advanced Renamer, Hazel
**What:** A rename dialog that lets users select multiple recordings from History/Storage and apply a naming template with live preview. Shows a two-column table: "Current Name" | "New Name" for every selected file, updating in real-time as the user edits the template. Template tokens: `{channel}`, `{date}`, `{title}`, `{quality}`, `{duration}`, `{platform}`, `{seq:001}`. Conflict detection highlights duplicate names in red. Undo log written so the batch can be reverted.
**Why:** Early downloads with default naming or inconsistent conventions leave users with a messy archive. Post-hoc cleanup is painful with OS file rename tools because they don't understand stream metadata. StreamKeep already stores metadata alongside recordings (`metadata.json`) — it can resolve `{channel}`, `{game}`, `{date}` from sidecar files. The live preview table (showing before/after for every file) is the gold-standard UX from Bulk Rename Utility that eliminates rename anxiety. The undo log makes it risk-free.
**Touches:** New dialog class `ui/rename_dialog.py` — file list populated from selected History/Storage entries, template input with token autocomplete, live preview table updated on `textChanged`, rename execution with undo log. Read metadata from `metadata.json` sidecars for token resolution. ~200-250 lines.
**Risks:** Renaming files that are referenced by History entries requires updating `HistoryEntry.path` in the config. OS path length limits (260 chars on Windows) — validate before committing. Files currently being downloaded or processed must be locked from rename. Undo log should persist to disk (not just in-memory) so it survives app restart.

---

## 37. REST API + Web Remote UI
**Scope:** Medium
**Inspired by:** qBittorrent web UI, Transmission RPC, MyJDownloader
**What:** Embed a lightweight HTTP server (extending the existing `local_server.py`) that exposes a full REST API and serves a single-page responsive web UI. Users access `http://192.168.x.x:port/` from their phone browser to: see active downloads with progress, add new URLs to the queue, browse the library, pause/resume/cancel downloads, and see which channels are live. Authenticated via the existing bearer token system.
**Why:** StreamKeep users who auto-record overnight or run the app on a headless/always-on machine currently have zero remote visibility. The browser companion extension only sends URLs to the app — it can't show status or control downloads. A web UI turns StreamKeep from a desktop-only tool into a remotely manageable server. qBittorrent's web UI is the #1 reason power users choose it over other torrent clients. The existing `local_server.py` already has the HTTP server, CORS, and token auth — extending it to a full API + static HTML is a natural evolution.
**Touches:** `local_server.py` — add API endpoints: `GET /api/status` (active downloads, live channels, queue), `POST /api/queue` (add URL), `PATCH /api/downloads/{id}` (pause/resume/cancel), `GET /api/library` (search recordings), `GET /api/monitor` (channel statuses). Serve a single bundled HTML file at `/` (vanilla JS + CSS, no framework, ~400-500 lines). Wire API handlers to existing main_window methods via Qt signals. ~300-400 lines of server code + HTML.
**Risks:** Security — the API must be token-gated on all endpoints. LAN-only by default (bind to 0.0.0.0 only when explicitly enabled in Settings, with warning). The web UI must not duplicate full desktop functionality — keep it to status + queue + basic control. Thread safety: API handlers run on the server thread but need to signal the Qt main thread for state changes (use existing `pyqtSignal` pattern).

---

## 38. Watch Queue + Playback Progress Tracking
**Scope:** Small-Medium
**Inspired by:** Plex Watchlist, Jellyfin "Continue Watching", VLC bookmarks
**What:** Add three features: (1) a "Watch Later" queue — manually add recordings you intend to watch, exempt from auto-cleanup; (2) playback progress tracking — mark recordings as "unwatched" / "in progress" / "watched" with an optional timestamp for resume; (3) moment bookmarks — save named timestamps within a recording ("funny moment at 1:23:45"). Show progress bars on History thumbnails and a "Continue Watching" section at the top of the History tab.
**Why:** StreamKeep downloads content but provides no way to track consumption. Users download 50 VODs, watch 3, and lose track of which they've seen. The watch queue solves "what should I watch next." Progress tracking solves "where was I." Moment bookmarks solve "I want to find that thing again." Together they turn the History tab from a download log into a media library. This also enables Feature 32's watch-status cleanup rules ("delete after viewed"). Plex's Continue Watching bar is the #1 engagement feature in their entire product.
**Touches:** `models.py` — add `watched: str` ("unwatched"/"in_progress"/"watched"), `watch_position_secs: float`, `bookmarks: list` fields to `HistoryEntry`. `main_window.py` History tab — progress bar overlay on thumbnails, "Continue Watching" filtered section at top, right-click "Mark as watched/unwatched", "Add bookmark at timestamp" dialog. Config persistence for watch state. ~150-200 lines.
**Risks:** Without a built-in video player, playback position tracking is manual (user sets it themselves). Could detect via file access time heuristics or offer a "played in external player" button that marks as watched. Bookmarks need a timestamp input — reuse the HH:MM:SS fields from ClipDialog. Watch state must survive across config export/import.

---

## 39. Stream Schedule Calendar
**Scope:** Medium
**Inspired by:** Sonarr calendar view, Twitch Schedule API
**What:** Fetch upcoming stream schedules from Twitch (Schedule API) and YouTube (search API for upcoming livestreams) for monitored channels. Display in a week-view calendar widget with colored blocks per channel. Users can click an upcoming stream to pre-configure auto-record settings. When the scheduled time arrives and the channel goes live, auto-record starts automatically.
**Why:** StreamKeep's channel monitor polls for live status reactively — it discovers a stream is live after it starts, potentially missing the first minutes. Twitch's Schedule API provides forward-looking data: what streams are planned, when they start, what game/category. A calendar view turns StreamKeep into a DVR — users see what's coming, choose what to record in advance, and never miss the start. Sonarr's calendar view (showing upcoming episodes across all tracked shows) is consistently rated as its best UX feature. The Twitch Schedule API is free, authenticated, and well-documented.
**Touches:** New `schedule.py` module — fetch schedules from Twitch API (`GET /helix/schedule?broadcaster_id={id}`), cache in config. New `ui/calendar_widget.py` — custom week-view grid (QTableWidget with day columns, hour rows, colored blocks for scheduled streams). Wire to Monitor tab as a toggle view (List | Calendar). On calendar block click: show stream details + "Auto-record this" button. Auto-record trigger: timer checks if current time matches a scheduled start ± 5 min window. ~300-400 lines.
**Risks:** Twitch Schedule API requires OAuth (app access token, not user token — simpler). YouTube search API has quota limits (10,000 units/day). Kick has no public schedule API. Calendar widget is custom UI work (no good Qt calendar component exists for week-view with time blocks). Schedule data can be stale — poll every 30-60 minutes. Streamers may go live off-schedule or cancel without updating — the existing live-detection monitor is still needed as a fallback.

---

## 40. Pre-Download Duplicate Detection
**Scope:** Small
**Inspired by:** dupeGuru, Sonarr duplicate detection, JDownloader link check
**What:** Before starting a download, check if a recording with matching metadata (same channel + similar title + similar duration) already exists in the library. Show a warning: "You may already have this: [title, downloaded 2026-01-15, 1080p, 4.2 GB]. Download anyway?" with options to skip, replace, or download alongside. For exact URL matches, warn immediately on paste. For fuzzy matches (re-uploads, re-encoded versions), check after fetch resolves metadata.
**Why:** Users who auto-record live streams and also manually download VODs from the same channel frequently end up with duplicates — the live capture and the processed VOD are the same content at different quality. Users who re-download accidentally (paste a URL they've already grabbed) waste bandwidth and disk. StreamKeep already does URL deduplication for the download queue, but not metadata-based matching against the full library. This is the cheapest possible storage optimization — prevent duplicates before they happen rather than scanning for them after.
**Touches:** `main_window.py` `_on_download()` — after fetch resolves stream metadata, compare `(channel, title, duration)` against `self._history` entries. Fuzzy title match via token overlap (split titles into words, check if >70% overlap). Duration match within ±5% tolerance. Show `QMessageBox` if match found. ~50-60 lines.
**Risks:** Minimal. False positives on fuzzy matching ("Stream title part 1" vs. "Stream title part 2" share many tokens) — the warning is advisory, not blocking. Duration tolerance must account for live captures (which may be shorter than the full VOD). Should not block batch/queue downloads — just log the warning and continue if user has "skip duplicates" preference set.

---

# Wave 2 — Features F41-F80

> Wave 1 (F1-F40) shipped in v4.18.0-v4.24.5. Wave 2 expands StreamKeep
> into a full media management platform with CLI/headless operation,
> authenticated downloads, built-in playback, AI-powered editing,
> analytics, distribution pipelines, and deep UX polish.

---

## 41. SQLite Library Database Migration
**Scope:** Large
**What:** Migrate the library index from the flat JSON `config.json` (history entries, monitor channels, queue state, notifications, tag associations, search indices, watch status) into a proper SQLite database at `%APPDATA%\StreamKeep\library.db`. The JSON config retains only user preferences and UI state. All list-of-dicts data moves to normalized tables with proper indices.
**Why:** `config.json` is the single biggest scaling bottleneck. Users with 500+ recordings have a 2-5 MB config that loads, parses, and re-serializes on every save. Atomic writes (the `.tmp` + `os.replace` pattern) block the UI thread for 100-200ms per save. History search is O(n) scan. Tag queries require joining in-memory. Notifications and lifecycle evaluations each re-parse the same blob. SQLite gives indexed queries, WAL-mode concurrent reads, and eliminates the "one writer blocks everything" problem. The `tags.db` already proves the architecture works — this extends it to the rest of the data model.
**Touches:** New `streamkeep/db.py` module — schema definition, migration logic (read existing config.json, insert into tables, rename config.json to config.json.migrated). Update `config.py` to delegate list queries to `db.py`. `models.py` — add `to_row()`/`from_row()` classmethod pairs. All call sites that do `cfg["history"]` list operations become SQL queries. Migration must be **one-way with backup** — on first launch after upgrade, the old config is preserved.
**Risks:** Large migration surface — every module that reads/writes history, monitor, queue, or notifications needs updating. Must handle interrupted migration (half-migrated state). Need a version stamp in the DB so future schema changes are orderly. Thread safety: SQLite WAL + `check_same_thread=False` with a connection pool, or per-thread connections. The JSON config path must remain as a read-only fallback for at least one version cycle.

---

## 42. CLI / Headless Mode
**Scope:** Large
**Inspired by:** yt-dlp, streamlink, gallery-dl
**What:** Add a full command-line interface that runs StreamKeep without any GUI. `StreamKeep.py --url URL --quality best --output ./` downloads a single URL. `StreamKeep.py --monitor` runs the channel monitor headlessly with console-logged events. `StreamKeep.py --server` starts only the REST API/web UI for remote control. All CLI operations share the same extractors, workers, and config as the GUI.
**Why:** StreamKeep can't run on headless servers (Linux VPS, NAS, Docker containers) because it requires PyQt6 and a display server. Users who want always-on auto-recording on a remote box are forced to use streamlink or yt-dlp scripts. A headless mode unlocks: Docker deployment, SSH-managed recording, cron-scheduled downloads, CI/CD pipelines for content archival, and scripted batch operations. The REST API (F37) already provides remote control — headless mode just removes the Qt dependency from the server path.
**Touches:** New `streamkeep/cli.py` — argparse-based CLI (`--url`, `--quality`, `--output`, `--monitor`, `--server`, `--format`, `--cookies`, `--proxy`). Refactor worker instantiation out of `main_window.py` into a shared `streamkeep/engine.py` that both GUI and CLI can drive. Console progress via `\r`-overwrite lines (speed, ETA, segment count). `--monitor` runs `ChannelMonitor` with a plain event loop (no Qt). `--server` starts `LocalCompanionServer` standalone. ~300-400 lines for CLI + ~200 lines for engine extraction.
**Risks:** The biggest risk is the Qt entanglement — `ChannelMonitor` uses `QTimer`, workers use `QThread`, signals use `pyqtSignal`. Headless mode needs non-Qt equivalents (stdlib `threading.Timer`, `threading.Thread`, callback functions). The refactor is the real work; the CLI itself is straightforward. Should not break the GUI path — both CLI and GUI import from `engine.py`.

---

## 43. Portable Mode
**Scope:** Small
**What:** Detect a `portable.txt` marker file next to `StreamKeep.exe` (or `StreamKeep.py`). When present, store all config, database, logs, and cache in a `data/` subfolder alongside the executable instead of `%APPDATA%\StreamKeep\`. This makes the entire installation USB-stick-friendly — carry your settings, history, and monitor list between machines.
**Why:** Power users who run StreamKeep on multiple machines (work desktop, home desktop, HTPC) want to carry their config on a USB drive. Enterprise users may not have write access to `%APPDATA%`. Convention: many Windows tools (Notepad++, 7-Zip, Firefox) support a `portable.txt` or `portable.ini` marker for this purpose. Implementation is trivial — redirect `CONFIG_DIR` in `paths.py` before any other module reads it.
**Touches:** `streamkeep/paths.py` — at module load, check `Path(sys.argv[0]).parent / "portable.txt"`. If found, set `CONFIG_DIR = exe_parent / "data"` instead of `%APPDATA%\StreamKeep`. All downstream code already uses `CONFIG_DIR` / `CONFIG_FILE` / `DB_PATH` from `paths.py`. ~15-20 lines in `paths.py`. Add `portable.txt.example` to the repo with a comment explaining the feature.
**Risks:** Minimal. USB drives are slow — SQLite WAL mode handles this fine. Path length limits if the USB is mounted at a long path. The marker file must be checked before `config.py` or `tags.py` or `db.py` import, which they already are (lazy init). Need to document: "Drop `portable.txt` next to the exe to enable portable mode."

---

## 44. Batch URL Import from File
**Scope:** Small
**What:** Accept a text file (or clipboard paste) containing one URL per line and queue all of them for download. Support comment lines (`#`) and blank-line separators. Show a preview dialog with the parsed URL count and any lines that failed validation, then queue valid URLs in one action.
**Why:** Users migrating from yt-dlp scripts often have curated URL lists in text files. Reddit/forum threads with "here are 50 VOD links" are common in archival communities. Currently, each URL must be pasted individually. Batch import from a `.txt` file is the simplest possible bulk-add feature — no custom format, just URLs.
**Touches:** New action in Download tab toolbar: "Import URLs..." opens a file picker (`.txt` filter) or accepts clipboard paste into a `QPlainTextEdit` dialog. Parse: split lines, strip whitespace, skip `#` comments and blanks, validate as `http(s)://`. Preview dialog shows valid count + invalid lines. On confirm, feed each URL to `_queue_add()`. ~80-100 lines.
**Risks:** Minimal. Large files (1000+ URLs) should stream-parse, not load all at once. Need rate limiting on queue additions to avoid flooding the extractor resolver. Should deduplicate against existing queue entries. Encoding: assume UTF-8, fall back to system locale.

---

## 45. Global Unified Search Bar
**Scope:** Small-Medium
**What:** Add a persistent search bar at the top of the main window (above the tab bar) that searches across all tabs simultaneously: History titles/channels, Storage paths, Monitor channel names, Queue URLs, transcript text (via FTS5), and tag names. Results grouped by source tab with "jump to" navigation.
**Why:** Each tab currently has its own isolated search/filter. Users who remember "something about a Valorant stream" don't know whether to search History, Storage, or Transcripts. A unified search bar is the Google-for-your-archive UX — type anything, see everything that matches. Every modern app (Spotlight, VS Code, Notion) has converged on this pattern.
**Touches:** New `streamkeep/ui/search_bar.py` — `GlobalSearchBar(QWidget)` with a `QLineEdit` + results dropdown (`QListWidget` or custom popup). Query dispatches to: History (title/channel substring), Storage (path/title), Monitor (channel name), tags.db (tag name + FTS5 transcript), queue (URL/title). Results are `(tab, entry, display_text)` tuples. Click navigates to the source tab and highlights/selects the row. ~150-180 lines.
**Risks:** Performance — must debounce (300ms) and cap results (50 per source). FTS5 queries can be slow on first hit (cold cache). The search bar must not steal focus from the URL input on the Download tab. Visual integration: needs to feel like part of the header, not a bolt-on. Should support `tab:history` prefix filters for power users.

---

## 46. Recording Hover Preview
**Scope:** Small
**What:** When hovering over a recording thumbnail in History or Storage, show an animated preview — a 3-5 frame loop extracted from the video at evenly-spaced timestamps. Uses the existing `ThumbWorker` to generate frames, cached as a `.preview.gif` or sprite strip alongside the recording.
**Why:** Thumbnails show one moment from a multi-hour recording — useless for identifying content at a glance. Animated previews (the Netflix/YouTube hover-to-preview pattern) let users visually browse their archive without opening files. The `ThumbWorker` already generates multi-frame filmstrips for the Trim dialog — reusing it for hover previews is a small incremental.
**Touches:** `ui/thumb_loader.py` — extend `ThumbLoader` to generate 5-frame preview strips on demand (triggered by `QTableWidget.entered` signal with a debounce timer). `ui/tabs/history.py` / `ui/tabs/storage.py` — on hover, cycle through frames in the thumbnail cell using a `QTimer` (200ms per frame). Cache as `<dir>/.streamkeep_preview.jpg` (sprite strip, 5 frames side-by-side, split on display). ~100-120 lines.
**Risks:** Frame extraction is slow for the first hover (ffmpeg probe + 5 seeks). The `ThumbWorker` pool is 2-concurrent — hover requests must be low-priority and cancelable (user moves mouse away = cancel). Sprite strip file size: 5 frames at 160x90 JPEG = ~50-80 KB, acceptable. Must not flicker or cause table layout jumps.

---

## 47. Browser Cookie Import
**Scope:** Medium
**Inspired by:** yt-dlp `--cookies-from-browser`, gallery-dl
**What:** Import authentication cookies from installed browsers (Chrome, Firefox, Edge, Brave) to access subscriber-only VODs, age-gated content, and authenticated API endpoints. Auto-detect installed browsers, extract cookies for supported platforms (Twitch, YouTube, Kick), and inject them into curl/yt-dlp requests. Optionally accept a Netscape-format cookies.txt file for manual import.
**Why:** Twitch subscriber-only VODs, YouTube members-only content, and age-restricted videos all require authentication. yt-dlp's `--cookies-from-browser` is its most-used auth feature. StreamKeep currently passes no cookies, so any authenticated content fails silently or returns a "login required" error. Cookie import unlocks the entire authenticated content tier without building a full OAuth login flow per platform.
**Touches:** New `streamkeep/cookies.py` — browser detection (check default install paths), cookie extraction using `browser_cookie3` or `rookiepy` library (reads Chrome/Firefox/Edge encrypted cookie stores), filter to platform domains, export as Netscape cookies.txt. `http.py` — add `--cookie` flag to `_build_curl_cmd()` when cookies file exists. `workers/download.py` — pass `--cookies` to yt-dlp. Settings UI: "Import cookies from browser" button + browser dropdown, "Import cookies.txt" file picker, per-platform cookie status indicators. ~150-200 lines.
**Risks:** Browser cookie stores are encrypted (Chrome uses DPAPI on Windows, Keychain on macOS). Libraries like `browser_cookie3` handle decryption but may break on browser updates. Cookie extraction requires the browser to be closed on some platforms. Privacy concern: cookies grant full account access — store the extracted cookies.txt with restricted permissions. Cookies expire — need a "Refresh cookies" action. Some browsers (Firefox) use profile directories that need user selection.

---

## 48. Platform Account Manager
**Scope:** Medium
**What:** A settings panel for managing platform authentication credentials: Twitch OAuth token (for subscriber VODs + Schedule API), YouTube API key (for quota-efficient requests), Kick session token, and generic "Custom header" entries per platform. Stored encrypted in config. Status indicators show auth state per platform (authenticated / expired / none).
**Why:** Several features need platform auth beyond cookies: Twitch Schedule API (F39) needs an OAuth app token, YouTube Data API has quota limits that an API key helps manage, Kick's authenticated API returns higher-quality metadata. Currently all auth is implicit (cookie-based or anonymous). An account manager centralizes credentials, shows expiry, and enables per-platform auth flows. This also enables future features like Twitch clip creation, YouTube upload, and channel-specific chat badges.
**Touches:** New `streamkeep/accounts.py` — credential store with optional encryption (Windows DPAPI via `ctypes`, fallback to base64 obfuscation). Settings UI: per-platform auth cards (Twitch: "Connect" button → OAuth device flow; YouTube: API key text input; Kick: session cookie import; Generic: key-value header pairs). `http.py` — inject auth headers from account manager into platform-specific requests. ~150-200 lines.
**Risks:** OAuth flows are platform-specific and complex (Twitch requires registered app, YouTube requires Google Cloud project). Start with manual token paste (user gets token from developer console) and add OAuth device flow later. Token storage encryption is best-effort — determined attackers with local access can still extract tokens. Tokens expire — need refresh logic for Twitch (refresh_token grant) and clear "Expired" indicators for manual-token platforms.

---

## 49. Proxy Pool with Per-Platform Routing
**Scope:** Medium
**Inspired by:** JDownloader proxy rotation, aria2c multi-source
**What:** Configure multiple proxy servers and assign them to specific platforms. Example: Twitch through a US proxy, YouTube through a DE proxy, everything else direct. Support HTTP, SOCKS5, and SOCKS5h protocols. Health check on each proxy (latency + connectivity test to the target platform). Auto-failover: if the assigned proxy fails, try the next in the pool before falling back to direct.
**Why:** StreamKeep's current proxy support is global (one proxy for everything via `NATIVE_PROXY` in config). Users in geo-restricted regions need different proxies for different platforms — a US proxy for Twitch, a JP proxy for Japanese streams. Content creators doing competitive research may want to rotate IPs to avoid rate limits. The architecture already routes all HTTP through `_build_curl_cmd()` — extending it to select a proxy per-platform is clean.
**Touches:** `streamkeep/http.py` — replace `NATIVE_PROXY` singleton with `ProxyPool` class. Pool entries: `{url, protocol, assigned_platforms[], enabled, last_health}`. `_build_curl_cmd()` resolves the proxy for the target URL's platform. New `streamkeep/proxy.py` — health check worker (curl to platform homepage through each proxy, measure latency). Settings UI: proxy table (add/edit/remove), per-proxy platform assignment checkboxes, "Test all" button with latency results. ~150-200 lines.
**Risks:** SOCKS5 support requires curl compiled with SOCKS support (most distributions include it). Health checks add startup latency — run async on app launch, cache results. Proxy authentication (user:pass) needs secure storage. Some CDNs (Cloudflare) detect and block datacenter proxies — residential proxies work but are user-provided. Auto-failover must not retry infinitely (3 attempts then fail).

---

## 50. DASH/MPD Manifest Support
**Scope:** Medium
**What:** Add native parsing of DASH (Dynamic Adaptive Streaming over HTTP) manifests (`.mpd` files) alongside the existing HLS (`.m3u8`) support. Detect DASH manifests from `Content-Type: application/dash+xml` or `.mpd` extension, parse `<AdaptationSet>` and `<Representation>` elements into `QualityInfo` entries, and download via ffmpeg's DASH demuxer or direct segment fetching.
**Why:** While HLS dominates live streaming, DASH is used by YouTube (for non-yt-dlp paths), Twitch (some VOD formats), Facebook, and many European broadcasters. Direct URL detection (`scrape.py`) currently misses DASH manifests because they're XML, not video. The yt-dlp fallback handles DASH implicitly, but native support means faster resolution, better quality selection, and the ability to use StreamKeep's parallel downloader on DASH segments.
**Touches:** New `streamkeep/dash.py` — parse MPD XML (stdlib `xml.etree.ElementTree`), extract `<Period>`, `<AdaptationSet>`, `<Representation>` into `QualityInfo` entries. Handle SegmentTemplate (pattern-based) and SegmentList (explicit URLs) addressing. `scrape.py` — add MPD Content-Type detection. `workers/download.py` — for DASH sources, either delegate to ffmpeg (`-i manifest.mpd`) or fetch segments directly using the parallel downloader. ~200-250 lines.
**Risks:** DASH manifests are more complex than HLS (multiple periods, content protection, dynamic MPD updates for live). Start with static VOD manifests only, skip DRM-protected content (log warning). Live DASH (dynamic MPD) is a Phase 2 extension. Some DASH streams use CENC encryption — detect and warn rather than failing silently.

---

## 51. Download Speed Scheduling
**Scope:** Small
**Inspired by:** qBittorrent scheduler, JDownloader speed limiter
**What:** Define time-based bandwidth rules: "Full speed from 00:00-08:00, limit to 5 MB/s from 08:00-18:00, 10 MB/s from 18:00-00:00." A weekly schedule grid (7 days x 24 hours) where each cell is a speed tier (unlimited / custom limit). The active limit updates automatically as time passes. Overrides the global rate limit during scheduled windows.
**Why:** Users who auto-record overnight don't want daytime downloads consuming their work bandwidth. qBittorrent's scheduler is the #1 cited reason power users choose it over simpler clients. StreamKeep already has a global rate limit (`rate_limit` config key passed to ffmpeg as `-maxrate`) — scheduling just swaps the active value based on the clock.
**Touches:** New `streamkeep/scheduler.py` — `SpeedScheduler` class with a 7x24 grid of speed values. `QTimer` checks every 60 seconds, updates the active speed limit. `workers/download.py` — reads the active limit from the scheduler instead of the static config value. Settings UI: visual week grid (clickable cells that cycle through speed tiers), or simpler: "Day hours" / "Night hours" / "Weekend" speed inputs. ~100-120 lines.
**Risks:** Minimal. Changing the speed mid-download: ffmpeg's `-maxrate` is set at launch, so mid-stream speed changes require restarting ffmpeg (unacceptable for live captures) or using a throttling proxy. Alternative: use `trickle` or OS-level bandwidth shaping. Simpler approach: only apply schedule limits to *new* downloads/queue items, not running ones.

---

## 52. Embedded Media Player (mpv Backend)
**Scope:** Large
**Inspired by:** Stremio, Plex desktop, VLC
**What:** Embed an mpv-based media player directly into StreamKeep. Double-click a History/Storage entry to play it in-app instead of launching an external player. Player features: play/pause, seek bar with thumbnail preview, volume, playback speed (0.5x-3x), subtitle track selection (loads `.ass`/`.srt` sidecars automatically), chapter markers on the seek bar, and fullscreen toggle. Player state (position, volume) persists for resume.
**Why:** Every interaction that sends users to an external player is a context switch that breaks the archive management workflow. Users watch a clip, want to trim it, switch back to StreamKeep, lose their timestamp. An embedded player with StreamKeep integration means: watch → right-click → "Trim from here" → clip exported. Watch progress tracking (F38) becomes automatic instead of manual. The transcript search (F27) can play results in-place. Stremio and Plex desktop prove that an embedded player is the centerpiece feature that turns a download manager into a media center.
**Touches:** New `streamkeep/player/` package. `mpv_widget.py` — `MpvWidget(QWidget)` wrapping `python-mpv` (libmpv Python bindings). `player_controls.py` — transport bar (play/pause, seek slider, volume, speed, subtitle, chapter). `player_panel.py` — the composite panel with player + controls + metadata display. Wire double-click on History/Storage to `_open_player(entry)`. Persist playback position to `HistoryEntry.watch_position_secs`. ~400-500 lines.
**Risks:** libmpv is a native C library — needs to be distributed alongside the exe (Windows: `mpv-2.dll` + `libmpv.dll.a`, ~30 MB). `python-mpv` handles the bindings. Embedding mpv in a Qt window uses the `wid` (window ID) approach which is well-documented. Video decoding is mpv's job (hardware acceleration via D3D11/DXVA2 on Windows). Risk: mpv version compatibility, DLL distribution in PyInstaller builds. Start with external mpv.exe detection (like ffmpeg), add bundled mpv later.

---

## 53. Picture-in-Picture Mini Player
**Scope:** Small-Medium
**Depends on:** F52 (Embedded Player)
**What:** A floating always-on-top mini player window (320x180 default, resizable) that detaches from the main window. Users can browse other tabs, trim clips, or manage downloads while a recording plays in the corner. Drag to reposition. Click to expand back to the main player. Minimal controls: play/pause, close.
**Why:** The embedded player (F52) takes over the main window's focus. Users who want to review a recording while setting up the next download need PiP. This is a standard feature in VLC, Firefox, Chrome, and every streaming platform. The implementation is a `QWidget` with `WindowStaysOnTopHint` + the mpv widget re-parented.
**Touches:** `player/pip_window.py` — `PiPWindow(QWidget)` with `Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool`. Re-parent the `MpvWidget` from the main player panel. Custom title bar with close/expand buttons. Drag-to-move via `mousePressEvent`/`mouseMoveEvent`. Resize handle at bottom-right corner. ~120-150 lines.
**Risks:** Re-parenting an mpv widget mid-playback may cause a brief flicker (mpv reattaches to a new window handle). On multi-monitor setups, PiP should remember its last position. `WindowStaysOnTopHint` behavior varies by OS — works reliably on Windows. Frameless window needs custom drop shadow for visual clarity.

---

## 54. Multi-Stream Sync Viewer
**Scope:** Large
**Depends on:** F52 (Embedded Player)
**Inspired by:** MultiTwitch, ViewSync, Kadgar
**What:** Play 2-4 recordings side by side with synchronized playback. Users select recordings from History, the viewer arranges them in a grid (2x1, 2x2), and all players share a single transport (play/pause/seek moves all players together). Audio source selector: hear one stream at a time or mix. Sync offset adjustment per stream (±30 seconds) for recordings that started at different times.
**Why:** Multi-POV content is huge in streaming — tournament participants, collaborative streams, group raids. Archivists who capture the same event from multiple channels want to review them together. MultiTwitch and ViewSync are dedicated web tools for this; no desktop VOD tool offers it. With multiple mpv instances sharing a seek position, the implementation is straightforward — mpv supports multiple instances per process.
**Touches:** New `streamkeep/player/sync_viewer.py` — `SyncViewer(QWidget)` with a grid layout of `MpvWidget` instances. Shared transport bar: seek/play/pause commands dispatched to all players. Per-stream offset slider (±30s). Audio toggle buttons (one per stream). Grid layout adapts to count (2=side-by-side, 3=2+1, 4=2x2). Entry: History multi-select → right-click → "Watch together (synced)". ~250-300 lines.
**Risks:** 4 simultaneous mpv decode instances need significant CPU/GPU (hardware decode essential). Memory: 4 streams at 1080p ≈ 1-2 GB. Seek synchronization must account for differing durations (one stream may be shorter). Audio mixing is mpv's job (`--audio-device` or `--volume 0` per instance). Performance testing needed on mid-range hardware.

---

## 55. Chapter & Bookmark Navigation Panel
**Scope:** Small
**Depends on:** F52 (Embedded Player)
**What:** A sidebar panel in the player that lists all chapters (from `metadata.json`, `.chapters.auto.txt`, or embedded MP4 chapters) and user bookmarks (from `HistoryEntry.bookmarks`). Click any entry to seek the player to that timestamp. Current chapter is highlighted. "Add bookmark here" button saves the current playback position with a user-provided label.
**Why:** Long VODs (4-8 hours) are impossible to navigate by seek bar alone. Chapters and bookmarks provide named jump points. StreamKeep already generates auto-chapters from Whisper transcription and stores user bookmarks in `HistoryEntry` — this panel just surfaces them in the player context. Every podcast app and audiobook player has this feature. It also creates a feedback loop: the more a user watches, the more bookmarks they create, the more useful the player becomes.
**Touches:** `player/chapter_panel.py` — `ChapterPanel(QWidget)` with a `QListWidget` of chapter/bookmark entries (icon + timestamp + label). Load from `metadata.json` chapters + `.chapters.auto.txt` + `HistoryEntry.bookmarks`. Wire click to `mpv.seek(timestamp)`. "Add bookmark" button captures `mpv.time_pos`, prompts for label, saves to `HistoryEntry.bookmarks`. ~100-120 lines.
**Risks:** Minimal. Multiple chapter sources may overlap — merge and sort by timestamp, deduplicate within 5 seconds. Bookmark persistence requires config save on each add (acceptable frequency). Chapter panel should be collapsible to not consume horizontal space when not needed.

---

## 56. Playback Speed & Audio EQ Controls
**Scope:** Small
**Depends on:** F52 (Embedded Player)
**What:** Extended playback controls: speed selector (0.25x, 0.5x, 0.75x, 1x, 1.25x, 1.5x, 2x, 3x), audio equalizer (5-band: bass, low-mid, mid, high-mid, treble), volume normalization toggle (mpv's `--af=dynaudnorm`), and mono/stereo toggle. Settings persist per-recording or globally.
**Why:** Podcast and talk-stream archivists routinely watch at 1.5-2x speed. Gaming VOD reviewers slow down to 0.5x for analysis. Audio EQ compensates for poor stream audio (boost speech, cut hiss). These are standard mpv capabilities exposed through properties — no custom audio processing needed. mpv's `speed`, `af`, and `audio-channels` properties handle everything.
**Touches:** `player/player_controls.py` — extend transport bar with speed combo, EQ sliders (5 `QSlider` widgets mapped to mpv's `equalizer` audio filter bands), normalization checkbox (toggles `dynaudnorm` AF), mono toggle. Persist as `playback_speed`, `eq_bands`, `normalize_audio` in config. ~80-100 lines.
**Risks:** Minimal. mpv handles all audio processing natively. EQ filter chain: `--af=equalizer=f=100:width_type=o:w=2:g={bass},...` per band. Speed changes are instant (`mpv.speed = 1.5`). Audio normalization may add latency on first enable (mpv needs to buffer ahead). 5-band EQ is a simplification — audiophiles want 10-band, but 5 covers the use cases without UI clutter.

---

## 57. AI Auto-Highlight Generator
**Scope:** Large
**Depends on:** F8 (Chat Spikes), F34 (Waveform), F30 (Scene Detection)
**Inspired by:** Eklipse, Opus Clip, Medal.tv auto-clip
**What:** Combine chat spike detection, audio peak analysis, and scene change frequency into a composite "interestingness" score per time window. Automatically identify the top N highlight moments in a recording and export them as a highlight reel (leveraging the multi-range export from F9). User reviews suggested highlights in a preview panel before export.
**Why:** This is the feature that turns StreamKeep from an archival tool into a content creation assistant. Manual clip selection from a 6-hour VOD takes 30-60 minutes. AI-assisted highlight detection reduces it to a 2-minute review. Eklipse and Opus Clip charge $15-50/month for this capability. StreamKeep can offer it offline using the signals it already captures (chat, audio, scenes). No cloud API needed — all analysis is local.
**Touches:** New `streamkeep/intelligence/highlight.py` — `HighlightDetector` class. Inputs: `.chat.jsonl` (chat spike scores from `spike_detect.py`), `.waveform.bin` (audio peak data), scene change timestamps (from `scene_worker.py`). Composite scoring: weighted sum of normalized signals per 30-second window. Top-N selection with minimum gap (avoid overlapping highlights). Output: list of `(start, end, score, reason)` tuples. UI: "Generate highlights" action on History → preview panel showing top-10 clips with filmstrip thumbnails → "Export highlight reel" button. ~200-250 lines.
**Risks:** Quality of highlights depends heavily on the content type. Gaming streams have strong chat/audio correlation with exciting moments. "Just chatting" streams have weaker signals. The composite scoring weights need tuning — start with equal weights and expose sliders in Settings for user adjustment. Must gracefully handle missing signals (no chat log = chat weight is 0, not an error).

---

## 58. SponsorBlock Integration
**Scope:** Small
**Inspired by:** SponsorBlock, yt-dlp `--sponsorblock-remove`
**What:** For YouTube downloads, query the SponsorBlock API for community-submitted segment data (sponsors, intros, outros, self-promotion, interaction reminders, music non-music). Display segments as colored markers on the quality selection / pre-download view. Options: skip segments during download (filter HLS segments), mark as chapters (non-destructive), or remove in post-processing (re-mux without those segments).
**Why:** SponsorBlock has 800K+ active users and segment data for millions of YouTube videos. yt-dlp already supports `--sponsorblock-remove` — but StreamKeep's native download path (for direct HLS/DASH) doesn't use yt-dlp. Integrating SponsorBlock natively means the segment data is available for visualization (colored markers), pre-download planning ("this 30-min video has 4 min of sponsors"), and post-processing (remove or chapter-mark). It's a lightweight API call that dramatically improves the YouTube download experience.
**Touches:** New `streamkeep/integrations/sponsorblock.py` — query `https://sponsor.sponorblock.party/api/skipSegments?videoID={id}` (SHA256 prefix lookup for privacy). Return segment list `[{start, end, category, action}]`. `ui/tabs/download.py` — render segments as colored bars on the quality selection panel. `workers/download.py` — for yt-dlp path, pass `--sponsorblock-remove` categories. For native HLS path, filter segment list to exclude sponsor time ranges (reuse the pre-download crop logic from F21). Settings: category toggles (sponsor, intro, outro, etc.), action per category (skip/chapter/none). ~100-120 lines.
**Risks:** SponsorBlock API is rate-limited (respect headers). Not all videos have segments. The native HLS segment skip is keyframe-aligned (same limitation as F21 pre-crop). Privacy: the SHA256 prefix lookup prevents the API from knowing which exact video you're downloading. Should be opt-in (some users philosophically oppose SponsorBlock).

---

## 59. Platform Subtitle Download
**Scope:** Small
**What:** Download platform-provided subtitles/closed captions alongside the video. Twitch VODs have auto-generated captions (via their caption API), YouTube has both auto-generated and creator-uploaded subtitle tracks in multiple languages. Save as `.srt` or `.vtt` sidecar files alongside the recording, with language codes in the filename (e.g., `recording.en.srt`, `recording.es.srt`).
**Why:** Whisper transcription (F29) generates subtitles from audio, but platform-provided captions are: (1) available instantly (no processing time), (2) often human-reviewed or creator-corrected, (3) available in multiple languages. For YouTube content with official subtitles, downloading them is strictly better than re-generating from Whisper. The two sources complement each other: platform subs when available, Whisper when not.
**Touches:** `extractors/twitch.py` — query caption availability from VOD metadata. `extractors/ytdlp.py` — pass `--write-subs --sub-langs all` to yt-dlp (already supported, just not wired). New `streamkeep/subtitles.py` — normalize subtitle formats (convert TTML/SBV to SRT/VTT), save alongside recording. Settings: "Download platform subtitles" toggle, language preference list. Download tab: subtitle track selector (when multiple languages available). ~100-120 lines.
**Risks:** Twitch caption API is undocumented and may change. YouTube subtitle download is well-supported via yt-dlp. Some platforms (Kick, Rumble) have no subtitle infrastructure. Subtitle format conversion (TTML → SRT) is straightforward but needs testing with edge cases (overlapping cues, styling tags). Multiple language downloads increase disk usage slightly (~50 KB per track).

---

## 60. Content Summary via LLM
**Scope:** Medium
**Inspired by:** Descript, YouTube AI summary, Recall.ai
**What:** Generate a concise text summary of a recording by feeding its transcript to a local LLM (via ollama) or cloud API (Anthropic Claude, OpenAI). Summary includes: key topics discussed, notable moments with timestamps, participant list (from speaker diarization), and a one-paragraph overview. Saved as `.summary.md` alongside the recording.
**Why:** A 4-hour stream transcript is 50-100 pages of text. Nobody reads that. A 500-word summary with timestamped key moments makes the archive genuinely useful for reference. YouTube's AI summary feature (now on every video) proves the demand. With WhisperX transcripts (F29) providing the text and ollama enabling free local inference, this feature costs nothing to run. The summary also powers better search — searching summaries is more semantic than searching raw transcript text.
**Touches:** New `streamkeep/intelligence/summarize.py` — `SummarizeWorker(QThread)`. Input: `.transcript.json` (from F29). Chunked processing: split transcript into 8K-token chunks, summarize each, then summarize the summaries. LLM backends: (1) ollama local (`POST http://localhost:11434/api/generate`), (2) Anthropic API (`anthropic` SDK), (3) OpenAI-compatible endpoint. Output: `.summary.md` with sections (Overview, Key Topics, Notable Moments with timestamps, Participants). Settings: LLM provider dropdown, model name, API key (for cloud), max summary length. History right-click: "Generate summary". ~200-250 lines.
**Risks:** LLM quality varies by model. Local ollama models (llama3, mistral) produce decent summaries but may hallucinate timestamps. Cloud APIs (Claude) produce better results but cost money and require internet. Transcript chunking must preserve speaker context across chunk boundaries. Long summaries are useless — enforce a 500-word cap with "expand" sections for key moments. Must handle transcripts with no speech (music streams, AFK) gracefully.

---

## 61. Smart Thumbnail Generator
**Scope:** Small-Medium
**Inspired by:** YouTube thumbnail generator, Canva, Eklipse
**What:** Auto-generate an eye-catching thumbnail for each recording by analyzing video frames for visual interest (face detection, high contrast, action). Extract the best candidate frame, apply optional text overlay (stream title, channel name, date), and save as `thumbnail.jpg`. Gallery view in History/Storage uses the generated thumbnail. Export option for social media (1280x720 JPEG).
**Why:** StreamKeep's current thumbnails are arbitrary single frames (first non-black frame). For users who re-upload or share content, a good thumbnail matters. YouTube's thumbnail selection algorithm (pick the frame with the most faces/contrast/color) is well-studied and implementable with basic CV. Even without ML, selecting the highest-contrast frame from scene-change boundaries (F30) produces better thumbnails than random sampling.
**Touches:** New `streamkeep/intelligence/thumbnail.py` — `ThumbnailGenerator`. Uses scene detection timestamps (from F30) as candidate frames. Score each by: luminance variance (contrast), edge density (detail), face presence (optional, via `mediapipe` or skip). Select top-scored frame. Optional text overlay via Pillow (`ImageDraw.text` with outline/shadow). Save as `thumbnail.jpg` (1280x720) alongside recording. History right-click: "Generate thumbnail" with preview. ~150-180 lines.
**Risks:** Face detection requires `mediapipe` (optional dep, ~50 MB). Without it, fall back to contrast/edge scoring (still better than random). Text overlay font must be bundled or use system fonts. Thumbnail quality depends on content — streams with static cameras (talking head) produce similar-scoring frames across the entire recording. Should offer "Pick from top 5 candidates" instead of fully automatic.

---

## 62. Audio Normalization Profiles
**Scope:** Small
**Inspired by:** FFmpeg loudnorm, Auphonic, Descript
**What:** Add LUFS-based loudness normalization as a post-processing option with named profiles: "Broadcast Standard" (-24 LUFS, EBU R128), "Podcast" (-16 LUFS, typical podcast loudness), "YouTube" (-14 LUFS), "Streaming" (-18 LUFS), and "Custom" (user-specified target + true peak). Two-pass normalization: first pass measures, second pass applies. Integrates with the existing post-processing preset system (F7).
**Why:** Stream recordings have wildly inconsistent loudness — quiet talk segments, loud game audio, sudden alert/donation sounds. Playing back recordings at consistent loudness is the #1 audio complaint in archival communities. FFmpeg's `loudnorm` filter implements EBU R128 loudness normalization and is already a dependency. Auphonic (the gold-standard audio processor) charges $11/month for this capability. StreamKeep can offer it for free.
**Touches:** `postprocess/processor.py` — new `_normalize_audio()` method. Two-pass: (1) `ffmpeg -i input -af loudnorm=print_format=json -f null -` → parse measured values, (2) `ffmpeg -i input -af loudnorm=I={target}:measured_I={measured}:measured_LRA={measured_lra}:... output`. Named profiles stored in config as `normalization_profiles`. Settings UI: profile selector + custom target/true-peak inputs. Expose as a PostProcessor preset option. ~100-120 lines.
**Risks:** Two-pass processing doubles the audio processing time (still fast — 10-50x realtime for audio-only analysis). True peak limiting may introduce subtle clipping on already-loud content. The `loudnorm` filter requires ffmpeg built with the `libebur128` library (most distributions include it). Stream-copy output is not possible with normalization — requires re-encode of at least the audio track.

---

## 63. Download Analytics Dashboard
**Scope:** Medium
**What:** A new **Analytics** tab (or overlay panel) showing historical download statistics with interactive charts: downloads per day/week/month (bar chart), total data downloaded over time (cumulative line), platform breakdown (pie/donut chart), top channels by download count and size (ranked bar), average download speed over time (line), peak download hours (heatmap). Data sourced from History entries with date parsing.
**Why:** Users who run StreamKeep for months accumulate hundreds of downloads but have zero visibility into patterns. "How much data did I download last month?" "Which platform uses the most storage?" "Is my download speed degrading?" Analytics answer these questions and help users make informed decisions about storage, bandwidth, and monitoring priorities. qBittorrent's stats and Sonarr's calendar/history views are the most-cited features for operational awareness.
**Touches:** New `streamkeep/ui/tabs/analytics.py` — `AnalyticsTab(QWidget)`. Charts rendered via QPainter (no external charting library needed — bar charts and line graphs are simple geometry). Data: query History entries grouped by date/platform/channel, aggregate size/count. Sparkline widgets reused from Storage tab (F13). Metric cards at top: total downloads, total size, avg speed, most active channel. Date range selector for filtering. ~250-300 lines.
**Risks:** QPainter charts are lower fidelity than matplotlib/plotly, but avoid heavy dependencies and render instantly. History entries must have parseable dates (existing format is ISO-like). Users with <20 downloads get sparse charts — show "Download more to see trends" placeholder. Chart rendering must be fast even with 1000+ entries — aggregate in Python, not per-entry painting.

---

## 64. Bandwidth Usage Tracker
**Scope:** Small
**What:** Track cumulative network bytes transferred per download session and persist daily totals in the database. Show a running total in the status bar ("Today: 12.4 GB / This month: 89.2 GB"). Optional bandwidth cap with warning: "Daily limit of 50 GB reached — pause queue?" Integrates with the Analytics dashboard (F63) for historical bandwidth charts.
**Why:** ISPs with data caps (Comcast 1.2 TB, many mobile ISPs) are common. Users auto-recording multiple channels overnight can unknowingly consume 50-100 GB per day. A bandwidth tracker with optional caps prevents overage charges. Even without caps, visibility into data usage helps users decide whether to reduce quality, limit parallel downloads, or add channels to the monitor.
**Touches:** `streamkeep/bandwidth.py` — `BandwidthTracker` singleton. Incremented by `DownloadWorker` progress callbacks (byte deltas). Persists daily totals to DB. `ui/main_window.py` — status bar label showing running total. Settings: daily/monthly cap (0 = unlimited), action on cap (warn / pause queue / stop all). ~80-100 lines.
**Risks:** Byte tracking in HLS mode counts segment sizes (accurate). In yt-dlp mode, progress bytes come from yt-dlp's output parsing (less precise). ffmpeg mode tracks via stderr progress output (approximate). Parallel downloads: sum all active workers' byte deltas. Cap enforcement must not abort running downloads — finish the current segment/file, then pause the queue.

---

## 65. Download Integrity Verification
**Scope:** Small
**What:** After a download completes, run integrity checks: (1) ffprobe the output file to verify it's a valid media container with expected duration, (2) compare actual duration to expected duration (within 2% tolerance), (3) check for truncation (file size vs. expected based on bitrate). Report results in History tab: green check (verified), yellow warning (minor discrepancy), red X (failed/corrupt). Offer "Re-download" action on failed verifications.
**Why:** Downloads can silently corrupt: CDN errors, network drops during the last segment, ffmpeg muxing failures that exit 0 but produce truncated output, disk-full mid-write. Users discover corruption only when they try to play the recording — sometimes weeks later. Post-download verification catches corruption immediately while the source is still available for re-download. This is especially important for auto-recorded content that nobody watches immediately.
**Touches:** New `streamkeep/verify.py` — `VerifyWorker(QThread)`. Runs `ffprobe -v error -show_entries format=duration,size -of json` on the output file. Compares against expected duration from stream metadata. Checks for common corruption signatures (duration=0, size<expected*0.5). Emits `verified(path, status, details)` signal. Wire to `FinalizeWorker` as an optional post-step. History tab: verification badge column. ~80-100 lines.
**Risks:** ffprobe adds ~1-3 seconds per file (acceptable as a post-step). Expected duration is approximate for live captures (stream duration grows during recording). HLS downloads with missing segments produce short files — this is corruption, not a verification bug. Must not mark yt-dlp's "--download-sections" partial downloads as corrupt (they're intentionally shorter).

---

## 66. Channel Statistics & Growth Trends
**Scope:** Medium
**What:** Track historical metadata for monitored channels: stream frequency (broadcasts per week), average stream duration, typical viewer count (from Twitch/Kick API), quality tier history, VOD count over time. Show per-channel trend cards in the Monitor tab: "xQc: 28 streams this month, avg 6.2h, usually 1080p60." Growth sparklines for frequency and duration. "Channel insights" panel below the monitor table.
**Why:** Users who monitor 10+ channels want to understand patterns: "This channel streams daily but always short sessions" vs. "This channel does 2 marathon streams per week." The monitor already polls channel status every 2 minutes — logging each poll result (live/offline, viewer count, title, game) builds a historical dataset for free. Trend visibility helps users tune their monitoring: adjust schedules, set quality expectations, decide which channels are worth the disk space.
**Touches:** New `streamkeep/channel_stats.py` — on each monitor poll, log `{channel_id, timestamp, status, viewers, title, game}` to a `channel_polls` DB table. Aggregate queries: streams_per_week, avg_duration, quality_distribution. `ui/tabs/monitor.py` — "Channel Insights" collapsible panel below the channel table. Per-channel: stat cards (frequency, avg duration, top game) + sparkline (streams/week over last 8 weeks). ~200-250 lines.
**Risks:** Poll logging grows the DB — log one row per status *change* (live→offline, not every poll). At 120s polling with 10 channels = 7,200 polls/day — logging only transitions reduces to ~20-40 rows/day. Historical viewer counts are approximate (sampled at poll time, not peak). Channel that hasn't been monitored long shows "Not enough data" placeholder.

---

## 67. Storage Health Monitor & Disk Alerts
**Scope:** Small
**What:** Continuously monitor free disk space on the output drive. Show a persistent indicator in the status bar ("1.2 TB free" with color: green >100GB, yellow 20-100GB, red <20GB). Alert when space drops below configurable thresholds. Auto-pause queue when critically low (prevent partial downloads). Extend to monitor multiple drives if output dirs span different volumes.
**Why:** The disk-space preflight (F15-era feature in v4.15.0) checks once before download start, but long auto-record sessions can fill a drive over hours. A continuous monitor catches the slow burn. Users who record to a dedicated drive (common for archivists) need persistent visibility. Auto-pausing the queue on low space prevents the worst outcome: partial/corrupt downloads that waste bandwidth AND disk.
**Touches:** `streamkeep/disk_monitor.py` — `DiskMonitor(QObject)` with a 30-second `QTimer`. Queries `shutil.disk_usage()` on each output root. Emits `space_changed(path, free_bytes)` and `space_critical(path)` signals. `ui/main_window.py` — status bar label + color, auto-pause queue on critical. Settings: warning threshold (GB), critical threshold (GB), auto-pause toggle. ~60-80 lines.
**Risks:** Minimal. `shutil.disk_usage()` is fast and cross-platform. Network drives may report inaccurate free space — accept this limitation. The 30-second poll is a good balance between responsiveness and overhead. Should not spam notifications — one alert per threshold crossing, not per poll.

---

## 68. Upload Destinations (YouTube / S3 / FTP / WebDAV)
**Scope:** Large
**Inspired by:** Sonarr remote path mapping, rclone, Cyberduck
**What:** After a download (or post-process) completes, automatically upload the recording to a configured destination: YouTube (via Data API v3 with OAuth), AWS S3 / Backblaze B2 / MinIO (via boto3 or rclone), FTP/SFTP server, or WebDAV (Nextcloud, OwnCloud). Multiple destinations can be configured (e.g., "archive to S3 + upload highlights to YouTube"). Each destination has its own naming template, folder structure, and upload condition (all downloads / specific channels / manual trigger only).
**Why:** "Download locally then manually upload" is a tedious workflow for users who archive to cloud storage or re-upload content. Sonarr users expect the "download → process → distribute" pipeline to be fully automated. S3/B2 is the cheapest long-term archive storage (~$5/TB/month). YouTube upload enables clip-to-publish in one step. FTP/WebDAV covers NAS and self-hosted storage. The implementation is per-destination adapter pattern — each uploads via its native protocol.
**Touches:** New `streamkeep/upload/` package. `base.py` — `UploadDestination` base class with `upload(path, metadata)` and `test_connection()` methods. `youtube.py` — YouTube Data API v3 upload (OAuth device flow, resumable upload). `s3.py` — boto3 upload with multipart. `ftp.py` — ftplib/paramiko upload. `webdav.py` — HTTP PUT with auth. `upload_worker.py` — `UploadWorker(QThread)` with progress signals. Settings: destination table with per-destination config forms. Wire to `FinalizeWorker` completion path. ~400-500 lines across adapters.
**Risks:** YouTube upload requires Google Cloud project + OAuth consent screen (complex setup for users). S3 requires AWS credentials (security-sensitive). FTP is unencrypted by default (warn, recommend SFTP). Large file uploads need resumable upload support (YouTube API and S3 multipart both support this). Upload failures should retry 3x with backoff then log failure (never block the download pipeline). Each adapter is independent — ship one at a time starting with S3/B2 (simplest API).

---

## 69. Clip Share via Local Web Gallery
**Scope:** Small-Medium
**Depends on:** F37 (REST API)
**What:** Extend the local web server (F37) with a shareable clip gallery: users mark recordings or clips as "shared," and the web UI serves them as a browsable gallery with embedded HTML5 video player. Generate short shareable URLs (e.g., `http://192.168.1.100:8080/share/abc123`) that can be sent to friends on the same network. Gallery view shows thumbnails, titles, durations. Video streams via HTTP Range requests for seek support.
**Why:** "Hey, watch this clip" currently means: find the file, upload to a file sharing service, send the link. A local share gallery turns StreamKeep into a mini media server for LAN sharing. Especially useful in households, offices, or LAN parties where multiple people want to watch clips. The web server infrastructure (F37) and token auth already exist — this extends it with media serving and a gallery UI.
**Touches:** `local_server.py` — add `GET /share/{id}` (HTML page with video player), `GET /media/{id}` (video file streaming with Range support), `GET /gallery` (shared items grid). `models.py` — add `shared: bool`, `share_id: str` to `HistoryEntry`. `ui/tabs/history.py` — right-click "Share on network" toggles shared flag, copies URL to clipboard. Gallery HTML: responsive grid with thumbnails, click-to-play. ~150-200 lines.
**Risks:** Video file serving must support HTTP Range requests for seek (straightforward in Python's `http.server`). Large files (multi-GB) served over HTTP may be slow — this is inherently LAN-only. Security: shared URLs should be unguessable (UUID-based IDs), and the gallery itself should still require the bearer token (or a separate read-only token). Must not expose the full filesystem — only explicitly shared recordings are accessible.

---

## 70. RSS Feed Generator
**Scope:** Small
**Inspired by:** Podcast apps, Jellyfin RSS, Sonarr RSS sync
**What:** Generate an RSS 2.0 / Atom feed of downloaded recordings, served via the local web server (F37). Each recording becomes a feed item with title, description, date, duration, and a media enclosure pointing to the local file. Per-channel feeds and a combined "all downloads" feed. Compatible with podcast apps (Pocket Casts, AntennaPod) for playback on mobile devices.
**Why:** Users who archive stream VODs often want to consume them like podcasts — queue them in a podcast app, listen on the go, track what they've listened to. An RSS feed with media enclosures is the universal format that every podcast app understands. Jellyfin generates podcast-compatible feeds from its library; StreamKeep can do the same. This turns downloaded VODs into a personal podcast feed accessible from any device on the network.
**Touches:** `local_server.py` — add `GET /feed/all.xml` and `GET /feed/{channel}.xml` endpoints. `streamkeep/feed.py` — `generate_rss(entries, base_url)` builds RSS 2.0 XML with `<enclosure>` tags pointing to `/media/{id}` URLs. Channel grouping from History entries. Proper MIME types, duration tags, and podcast-namespace extensions. ~100-120 lines.
**Risks:** Podcast apps expect consistent feed URLs (bookmarked once, polled forever) — the random port on each launch breaks this. Solution: persist the port in config and reuse it across launches. Large feeds (500+ items) may cause slow parsing in some apps — paginate or limit to last 100 items. Audio-only podcast apps may choke on video enclosures — offer an "audio feed" variant that serves the audio-extracted version.

---

## 71. Recording Notes & Annotations
**Scope:** Small
**What:** Attach Markdown notes to any recording in History. A notes panel (collapsible sidebar or dialog) with a `QPlainTextEdit` for free-form text. Notes are saved alongside the recording as `.notes.md` and persisted in the database. Auto-populated template on first open: title, channel, date, duration, tags. Searchable via the global search bar (F45).
**Why:** Archivists annotate their collections — "great discussion at 1:23:00 about X," "save the segment from 2:00:00 for the compilation," "audio quality drops at 45:00." Currently there's no place to store these observations. `.notes.md` files alongside recordings are simple, portable, and human-readable. The template auto-fill removes the friction of starting from scratch. Integration with search means notes become part of the archive's knowledge base alongside transcripts and tags.
**Touches:** `ui/tabs/history.py` — "Notes" button on selection or right-click → "Edit Notes". `streamkeep/notes.py` — load/save `.notes.md` files, template generation, DB index for search. Notes panel: `QPlainTextEdit` with basic Markdown preview toggle (or just monospace editing). Global search (F45) includes notes content. ~100-120 lines.
**Risks:** Minimal. Markdown rendering is optional — plain text editing is sufficient for v1. File path for `.notes.md` follows the recording location. If the recording moves, notes may be orphaned — the DB index provides a fallback. Auto-populate template must not overwrite existing notes on re-open.

---

## 72. Backup & Restore Wizard
**Scope:** Small-Medium
**What:** Export the complete StreamKeep configuration (settings, monitor channels, history, tags, smart collections, presets, hooks, account credentials, notification log) as a single encrypted `.skbackup` file. Import restores everything. Backup includes the SQLite database, config.json, and optionally metadata/notes sidecars (not video files). Scheduled auto-backup option (daily/weekly to a configured path).
**Why:** Users who invest significant time configuring monitors, presets, tags, and lifecycle policies risk losing it all to a disk failure, OS reinstall, or accidental config corruption. The config is now split across JSON + SQLite + sidecar files — a manual backup requires knowing where everything lives. A one-click backup wizard makes the investment in configuration feel safe. Auto-backup prevents "I forgot to back up before the reinstall" scenarios.
**Touches:** New `streamkeep/backup.py` — `create_backup(path, include_metadata=False)`: zip `config.json` + `library.db` + `tags.db` + `notifications.jsonl` + optional metadata sidecars into a `.skbackup` (renamed `.zip`). `restore_backup(path)`: extract, validate schema versions, merge or replace. Scheduled backup: `QTimer` daily/weekly, write to configured path. Settings UI: "Backup now" / "Restore from backup" buttons + schedule config. ~150-180 lines.
**Risks:** Restore must handle version mismatches (backup from v4.25, restoring into v4.28 — run schema migrations). Encrypted backup needs a user-provided passphrase (don't store it). Restore is destructive to current config — confirm before proceeding. Auto-backup rotation (keep last 5) prevents disk fill. Credentials in the backup are the biggest security concern — encrypt the entire zip with AES-256 via `pyzipper` or warn that credentials are included in plaintext.

---

## 73. Custom Accent Color Picker
**Scope:** Small
**What:** Add a color picker in Settings that lets users choose a custom accent color (replacing the default Catppuccin Mauve/Blue). The accent color tints: primary buttons, active tab indicators, progress bars, links, selected rows, and focus rings. Preset accent swatches (Mauve, Blue, Green, Peach, Pink, Red, Teal, Yellow) plus a custom hex input with live preview.
**Why:** Catppuccin Mocha with mauve accent is the default — and it's great — but personalization is a strong user desire. Users who run StreamKeep alongside other Catppuccin-themed apps may want a consistent accent across tools. The implementation is simple: `build_stylesheet(palette)` already interpolates colors from a dict — adding an `accent` override that the user picks is a one-line change to the palette plus a color picker widget.
**Touches:** `theme.py` — add `apply_accent(hex_color)` that patches `CAT["accent"]`, `CAT["blue"]`, and `CAT["lavender"]` with the user's choice, then rebuilds the stylesheet. Settings UI: row of 8 preset color swatches (clickable `QPushButton` with `border-radius:12; background:{color}`) + "Custom" button that opens `QColorDialog`. Persist as `accent_color` in config. ~60-80 lines.
**Risks:** Minimal. Some accent colors have poor contrast against the dark background (yellow on dark is tricky — use it for text/borders, not backgrounds). The color picker should show a live preview before applying. "Reset to default" button restores the theme's built-in accent. Light theme accent colors need different choices than dark theme accents — validate contrast ratio.

---

## 74. Multi-Language (i18n)
**Scope:** Large
**What:** Internationalize all user-facing strings using Qt's built-in translation system (`QCoreApplication.translate()` + `.ts` files). Ship with English (default) + community-contributed translations for: Spanish, Portuguese, German, French, Japanese, Korean, Chinese (Simplified), Russian. Settings: language dropdown with instant apply (no restart required).
**Why:** StreamKeep's user base is global — streaming is worldwide. Non-English users currently navigate an English-only interface. Qt's i18n system is battle-tested: wrap strings in `self.tr()`, generate `.ts` XML files with `pylupdate6`, translate via Qt Linguist or Crowdin, compile to `.qm` binary. The system is designed to be incrementally adopted — untranslated strings fall through to English.
**Touches:** Every `.py` file with user-facing strings — wrap in `self.tr()` or `QCoreApplication.translate("Context", "string")`. New `streamkeep/i18n/` directory with `.ts` and `.qm` files per language. `main_window.py` — install `QTranslator` at startup from config language preference. Settings: language combo populated from available `.qm` files. ~50-80 lines of infrastructure + per-file string wrapping (large surface area but mechanical).
**Risks:** The biggest effort is touching every file to wrap strings — this is a codebase-wide change. Dynamic strings (f-strings with variables) need `arg()` substitution. Right-to-left languages (Arabic, Hebrew) need layout mirroring — defer to a later phase. Translation quality depends on contributors — start with machine translation (DeepL) and accept community PRs. Plural forms vary by language — use Qt's plural-aware translation.

---

## 75. Layout Density Modes
**Scope:** Small
**What:** Three layout density presets: **Compact** (smaller fonts, tighter spacing, more rows visible — optimized for monitors ≤15"), **Cozy** (current default), and **Spacious** (larger fonts, more padding, bigger thumbnails — optimized for 4K/TV viewing). Affects: font sizes, row heights, padding, thumbnail dimensions, button sizes, spacing between elements.
**Why:** StreamKeep currently has one layout that works well at 1080p/125% DPI. Users on 4K monitors at 100% scaling see tiny UI elements. Users on laptops see wasted space. A density toggle is the simplest way to support diverse displays without building a fully responsive layout system. Every Google product (Gmail, Drive, Calendar) ships with this exact compact/cozy/spacious pattern.
**Touches:** `theme.py` — add density multiplier to `build_stylesheet()`. Define `DENSITY_COMPACT = {"font_size": 11, "row_height": 48, "padding": 4, "thumb_w": 80}`, `DENSITY_COZY = {"font_size": 13, "row_height": 72, "padding": 8, "thumb_w": 112}`, `DENSITY_SPACIOUS = {"font_size": 16, "row_height": 96, "padding": 12, "thumb_w": 160}`. QSS template interpolates these values. Settings: density radio buttons with instant apply. ~60-80 lines.
**Risks:** Some widgets may not scale cleanly (fixed-width layouts, hardcoded pixel values in `main_window.py`). Need to audit all `setFixedWidth`/`setFixedHeight` calls and convert to density-relative values. Table column widths need proportional adjustment. The Trim dialog's filmstrip has hardcoded dimensions — these need parameterization.

---

## 76. First-Run Onboarding Wizard
**Scope:** Small-Medium
**What:** A multi-step wizard dialog on first launch (or when no config exists): (1) Welcome + ffmpeg detection (auto-download if missing), (2) Output directory selection, (3) Theme preference (dark/light), (4) Optional: import cookies from browser, (5) Optional: add first monitored channel, (6) Quick tour highlighting key UI areas. Skippable at any step. Sets a `first_run_complete` flag in config.
**Why:** StreamKeep's first-launch experience is: paste a URL and hope ffmpeg is in PATH. New users who don't have ffmpeg installed get a cryptic error. Users don't know about the Monitor tab, post-processing, or keyboard shortcuts until they explore. An onboarding wizard reduces time-to-first-download from "figure it out" to "follow 3 steps." Every mature desktop app (OBS, Discord, VS Code) has first-run onboarding.
**Touches:** New `streamkeep/ui/onboarding.py` — `OnboardingWizard(QDialog)` with `QStackedWidget` pages. Page 1: ffmpeg check + auto-download (existing `_check_ffmpeg()` logic). Page 2: output dir picker. Page 3: theme/accent preview. Page 4: cookie import (if F47 is present). Page 5: "Add your first channel" with URL input. Page 6: animated tour overlay highlighting tab bar, URL input, queue. Shown on first launch or when `config.get("first_run_complete")` is False. ~200-250 lines.
**Risks:** Wizard must not be annoying — "Skip all" button on every page. FFmpeg auto-download needs platform detection (Windows: download from gyan.dev, extract, add to PATH or app dir). Tour overlay is the most complex page — use `QGraphicsOpacityEffect` to dim the main window and spotlight UI areas. Must work with both dark and light themes.

---

## 77. Plugin / Extension SDK
**Scope:** Large
**Inspired by:** OBS plugins, JDownloader extensions, yt-dlp extractors
**What:** A plugin system that loads Python modules from `%APPDATA%\StreamKeep\plugins\` (or `plugins/` in portable mode). Plugin types: (1) Custom extractors (subclass `Extractor`, auto-registered), (2) Post-processing filters (hook into the `PostProcessor` pipeline), (3) Upload destinations (subclass `UploadDestination`), (4) UI panels (add custom tabs or sidebar widgets). Plugins declare metadata in a `plugin.json` manifest. Settings tab lists installed plugins with enable/disable toggles.
**Why:** StreamKeep can't natively support every streaming platform, post-processing filter, or upload destination. A plugin system lets the community extend it. The extractor system already uses `__init_subclass__` auto-registration — any Python file that defines an `Extractor` subclass automatically appears in the extractor registry. Formalizing this as a plugin system means: (1) users can add extractors for niche platforms without forking, (2) post-processing pipelines become extensible, (3) the core app stays lean while the ecosystem grows.
**Touches:** New `streamkeep/plugins.py` — `PluginManager` scans the plugins directory, validates `plugin.json` manifests, and `importlib.import_module()` each enabled plugin. Plugin API: expose `streamkeep.extractors.base.Extractor`, `streamkeep.postprocess.processor.PostProcessor` hook points, `streamkeep.upload.base.UploadDestination`. Sandboxing: plugins run in the same process (no sandbox — trust-based, like yt-dlp extractors). Settings UI: plugin list table (name, version, author, enabled toggle), "Open plugins folder" button. ~200-250 lines for the manager + API surface.
**Risks:** No sandboxing — malicious plugins can do anything. This is acceptable for a power-user tool (same model as yt-dlp, OBS, JDownloader). Plugin API stability — need to version the API and document breaking changes. Plugin dependencies (pip packages) need a loading mechanism. Name collisions between plugins — namespace by plugin ID. Plugin errors must not crash the main app — wrap `importlib` calls in try/except with error logging.

---

## 78. Accessibility (Screen Reader + High Contrast)
**Scope:** Medium
**What:** Full accessibility pass: (1) Set `accessibleName` and `accessibleDescription` on all interactive widgets for screen readers (NVDA, JAWS, Windows Narrator), (2) High-contrast theme option (WCAG AAA, 7:1 contrast ratio on all text), (3) Focus indicators (visible focus rings on all interactive elements), (4) Tab order audit (logical keyboard navigation through all controls), (5) Alt text on all images/icons (thumbnails, platform badges, status icons).
**Why:** Accessibility is both an ethical responsibility and a practical consideration — visually impaired users, users with motor disabilities who rely on keyboard navigation, and users in high-glare environments all benefit. Qt has built-in accessibility support via `QAccessible`, but it requires explicit `setAccessibleName()` calls on widgets — which StreamKeep currently has zero of. A high-contrast theme also benefits users on poor displays or in bright environments.
**Touches:** Every UI file — add `setAccessibleName()` / `setAccessibleDescription()` to buttons, inputs, tables, labels. `theme.py` — new `CAT_HIGH_CONTRAST` palette (black background, white text, bright accents, no subtle grays). Tab order: `setTabOrder()` calls in tab builders. Focus rings: QSS `:focus` pseudo-class with visible border. `main_window.py` — keyboard navigation audit (ensure all actions reachable via Tab/Enter/Escape). ~200-300 lines across all UI files.
**Risks:** Large surface area — every widget in every tab needs attention. Screen reader testing requires NVDA or Narrator running alongside (can't automate easily). High-contrast theme is a new palette that needs full testing. Some custom widgets (filmstrip, waveform, sparkline) need custom accessibility implementations. This is a codebase-wide change best done as a focused sweep.

---

## 79. Encrypted Config Storage
**Scope:** Small
**What:** Encrypt sensitive fields in the config database: API tokens, webhook URLs, proxy credentials, account passwords, cookie data. Use Windows DPAPI (via `ctypes` or `win32crypt`) for machine-bound encryption on Windows, Keychain on macOS, and libsecret on Linux. Non-sensitive fields (UI preferences, history, tags) remain in plaintext for debuggability. A master-password option for users who want additional protection beyond OS-level encryption.
**Why:** StreamKeep's config currently stores Twitch OAuth tokens, webhook URLs (which include Discord bot tokens), proxy credentials, and API keys in plaintext JSON. Any process on the machine can read them. OS-level encryption (DPAPI) binds secrets to the user account at zero UX cost — no password prompt, just transparent encrypt/decrypt. This is the standard for desktop credential storage (Chrome, Firefox, VS Code all use DPAPI on Windows).
**Touches:** New `streamkeep/secrets.py` — `encrypt(plaintext) -> blob`, `decrypt(blob) -> plaintext` using DPAPI on Windows (`ctypes.windll.crypt32.CryptProtectData`). `config.py` / `db.py` — wrap reads/writes of sensitive fields through `secrets.encrypt/decrypt`. Sensitive field list: `webhook_url`, `twitch_token`, `youtube_api_key`, `proxy_auth`, `companion_token`, `media_server_token`, `upload_credentials`. Migration: on first run after upgrade, encrypt existing plaintext values in-place. ~80-100 lines.
**Risks:** DPAPI is Windows-only (need platform-specific backends). `ctypes` DPAPI usage is well-documented and stable. If the user's Windows password changes, DPAPI may fail to decrypt — need a "re-enter credentials" fallback. Encrypted values are base64-encoded blobs (not human-readable in the JSON — intentional). Debugging encrypted config is harder — provide a "Show decrypted value" toggle in Settings (behind a confirm dialog).

---

## 80. Native OS Notifications
**Scope:** Small
**Inspired by:** Windows Toast, macOS Notification Center
**What:** Replace `QSystemTrayIcon.showMessage()` with native OS notification APIs for richer notifications: Windows Toast notifications (with action buttons, progress bars, and app icon), macOS Notification Center (with custom actions), Linux libnotify. Action buttons in notifications: "Open folder" on download complete, "Record now" on channel live, "View" on clip export complete.
**Why:** Qt's `showMessage()` produces basic balloon tips on Windows — no buttons, no progress, no rich content. Windows Toast notifications support interactive buttons, progress bars, hero images, and grouping. When a channel goes live, the notification should have a "Start recording" button that triggers auto-record without opening the app window. This is the difference between "informational" and "actionable" notifications. Every modern Windows app (Slack, Discord, Teams) uses Toast.
**Touches:** New `streamkeep/native_notify.py` — Windows: use `win10toast_click` or `windows-toasts` library for Toast notifications with callbacks. Register app ID for notification grouping. Action callbacks: "Open folder" → `os.startfile()`, "Record" → signal to main window. macOS: `pyobjc` NSUserNotification (or defer to Qt). Linux: `dbus` + `org.freedesktop.Notifications`. Fallback to `QSystemTrayIcon.showMessage()` if native backend unavailable. Settings: native notifications toggle (on by default). ~120-150 lines.
**Risks:** `windows-toasts` library handles the COM interop but adds a dependency. Toast notifications require an AUMID (Application User Model ID) registered in the Start Menu — PyInstaller builds may need a shortcut. Action button callbacks are async (the app may not be in the foreground when clicked). Linux notification support varies by desktop environment. Keep Qt fallback as a reliable default.
