#!/usr/bin/env python3
"""Sidecar NDJSON contract conformance check.

Scans every tools/*/sidecar.py and enforces the rules that bit us in v2.3:

  1. Frozen guard — any sidecar that calls `pip install` via subprocess must
     short-circuit when getattr(sys, 'frozen', False). When PyInstaller-frozen,
     sys.executable IS the sidecar exe; an unguarded pip-install call re-spawns
     the exe and fork-bombs the host. (Found in lipsight/demucs/whisper-stt
     during the 2026-04-30 audit.)

  2. Error-event code field — every emit of {"event": "error", ...} must include
     a "code" key. SidecarRunner.cs keys off `code`; omitting it routes every
     failure as "unknown" in the UI. (Found in lipsight during the same audit.)

  3. Known event names — `event` strings must be one of the documented set:
     progress, log, complete, error, segment, stem, device. New events should
     be added to KNOWN_EVENTS here when intentional, surfacing accidental typos.

Exit code 0 = pass, 1 = violations found. Designed for CI gating.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"

KNOWN_EVENTS = {
    # Standard lifecycle
    "progress", "log", "complete", "error",
    # Domain-specific result events (one per sidecar's output type)
    "segment",  # whisper-stt, lipsight — transcript segments
    "stem",     # demucs — separated audio stems
    "device",   # recordcast — DirectShow device enumeration
    "preset",   # gifstudio — known render presets
    "format",   # heicshift — supported input/output format inventory
    "voice",    # edge-tts — voice catalog enumeration
    "model",    # rnnoise — discoverable .rnnn model files
    "aspect",   # vertigo — target aspect-ratio presets
    "backend",  # whisper-cpp — compiled-in feature probe
    "chapter",  # chaptermark — discovered chapter markers
    "vmaf",          # clipforge.vmaf — per-frame VMAF scores
    "vmaf_summary",  # clipforge.vmaf — pooled mean / harmonic / min / pct<70
    "scene",         # scenedetect — detected scene cut (start/end timecodes)
    "thumb",         # clipforge.timeline — generated thumbnail in the strip
    "track",         # clipforge.track-list — enumerated container stream
    "doc",           # docconvert — produced document file (one per input)
    "archive_entry", # archive — file entry inside an archive
    "pdf_info",      # pdftools.info — page count + metadata for a PDF
    "pdf_part",      # pdftools.split — produced PDF part (range + path)
    "subtitle",      # subconvert — produced subtitle file (one per input)
    "font",          # fontconvert — produced font file
    "font_info",     # fontconvert.info — sfnt / flavor / family probe
    "ebook",         # ebookconvert — produced eBook file
    "ocr_result",    # ocr — produced text/hocr/pdf for each input image
    "ocr_language",  # ocr.languages — discovered Tesseract language pack
    "mesh",          # meshconvert — produced 3D model file
    "mesh_info",     # meshconvert.info — face / vertex / volume probe
    "pandoc_doc",    # pandoc-cli — produced markup file
    "raw_photo",     # rawphoto — developed RAW -> JPEG/TIFF/PNG
    "pdf_ocr",       # pdfocr — searchable PDF produced via ocrmypdf
    "gis_layer",     # gisconvert.vector — produced vector layer (ogr2ogr)
    "gis_raster",    # gisconvert.raster — produced raster (gdal_translate)
    # v2.7 wave
    "data_doc",        # datakit — produced JSON/YAML/TOML/XML/CSV
    "audio_tag",       # audiotag — read/wrote/stripped audio metadata
    "email_msg",       # mailbox — produced email message (eml/mbox/maildir)
    "calendar_event",  # calconvert — calendar event record
    "vcard_contact",   # calconvert — vCard contact record
    "web_record",      # webarchive — HAR/WARC record
    "color",           # iccprofile — applied/embedded/stripped ICC
    "color_info",      # iccprofile.info — image colorspace probe
    "tracker_song",    # trackermod — rendered MOD/IT/XM/S3M -> audio
    "lottie_render",   # lottiekit — rendered Lottie animation
    "texture",         # texturekit — converted GPU texture
    "midi_render",     # midisynth — rendered MIDI -> audio
    "dicom_image",     # dicomkit — DICOM -> image / anonymized
    "dicom_info",      # dicomkit.info — DICOM probe
    "cad_render",      # cadkit — rendered/saved CAD
    "cad_audit",       # cadkit.audit — DXF auditor findings
    "code_format",     # codeformat — formatted source file
    "formatter_status", # codeformat.check — formatter availability
    # v2.8 wave
    "sd_image",        # sdkit — Stable Diffusion produced image
    "sd_model",        # sdkit.models — discoverable SD model entry
    "speech_enhance",  # speechenhance — DeepFilterNet output
    "stem_track",      # stemkit — separated stem (vocals/drums/etc.)
    "stem_models",     # stemkit.models — supported separator models
    "pdf_md",          # pdfmarkdown — PDF -> Markdown output
    "vector_doc",      # vectorkit — converted AI/EPS/SVG/EMF/etc.
    "lut_cube",        # lutgen — generated 3D LUT (.cube/.3dl)
    "font_subset",     # fontsubset — subsetted webfont
    # v2.9 wave
    "rom_patch",       # gametools — patched/byteswapped/stripped ROM
    "rom_info",        # gametools.rom-info — header probe
    "disc_image",      # gametools.chd — packed/unpacked disc image
    "data_table",      # datasci — produced tabular/array data file
    "data_info",       # datasci.info — schema/shape probe
    "locale_doc",      # i18nkit — produced PO/MO/XLIFF/TMX/RESX/strings/JSON/YAML/CSV
    "point_cloud",     # pointcloud — produced PLY/LAS/LAZ/PCD/E57
    "point_cloud_info",# pointcloud.info — bounds + count probe
    "disk_image",      # diskimage — produced VM disk image
    "disk_image_info", # diskimage.info — qemu-img probe
    "email_index",     # mailimport.list — PST folder inventory
    # v2.10 wave (Latest & Greatest AI refresh)
    "matte_image",     # bgremove — produced RGBA cut-out
    "matte_model",     # bgremove.models — supported segmentation backend
    "upscale_image",   # superres — produced super-res image (spandrel path)
    "upscale_model",   # superres.models — downloadable checkpoint catalog
    "face_restore",    # facerestore — restored face image (CodeFormer / GFPGAN)
    "ocr_pro",         # ocrpro — Surya text/layout output
    "tts_audio",       # premiumtts — synthesized speech audio
    "tts_voice",       # premiumtts.voices — voice catalog entry
    "translation",     # translatekit — translated text/file/srt
    "translation_lang",# translatekit.langs — supported language code
    "inpaint_image",   # inpaint — produced inpainted PNG
    "master_audio",    # audiomastering — mastered / loudnorm audio
    # v2.11 wave (Raw Conversion Coverage)
    "layered_image",     # psdkit — flattened or per-layer image output
    "layered_info",      # psdkit.info — PSD/XCF probe
    "audio_codec",       # audiopro — niche codec output
    "audio_codec_info",  # audiopro.codecs — FFmpeg codec availability
    "subtitle_ocr",      # subocr — bitmap subtitle OCR'd to SRT
    "subtitle_text",     # subkit — interchanged text subtitle (SAMI/TTML/SCC/LRC/...)
    "dbtable",           # dbtools — produced DB table file
    "text_encode",       # textencode — recoded / line-end-normalized file
    "text_encode_info",  # textencode.detect — encoding probe
    "file_hash",         # hashkit — single file hash event
    "file_hash_manifest",# hashkit — consolidated SUMS manifest
    "file_hash_check",   # hashkit.verify — per-file pass/fail
    "encoded_blob",      # encodekit — Base-N / data-URL encoding
    "icon_blob",         # iconkit — produced .ico/.icns/.iconset
    "plist_doc",         # plistkit — plist conversion
    "hdr_image",         # hdrkit — HDR image converted / tonemapped
    "score_doc",         # music — produced notation file
    "hex_image",         # hexkit — produced flash image
    "hex_image_info",    # hexkit.info — segment probe
    # v2.12 wave (Domain-specific & exotic)
    "molecule",            # chemkit — converted molecular file
    "molecule_info",       # chemkit.info — formula / MW / SMILES probe
    "bio_seq",             # biokit — converted sequence / alignment / VCF
    "bio_stats",           # biokit.fastq-stats — QC stats
    "medical_volume",      # medkit — produced 3D medical volume
    "medical_volume_info", # medkit.info — dim / spacing / dtype
    "net_capture",         # netcap — converted PCAP/PCAPNG or CSV summary
    "log_record",          # logkit — produced JSONL/EVTX-JSONL log file
    "raster_image",        # rasterimg — niche raster image converted
    "archive_extra",       # morearchive — extracted niche archive
    "archive_extra_entry", # morearchive — file entry inside niche archive
    "archive_extra_info",  # morearchive.info — APK/IPA/MSIX probe
    "bookmark_doc",        # bookmark — converted browser bookmark file
    "eng_cad",             # engcad — STEP/IGES/BREP/STL converted
    "anim_scene",          # animkit — BVH/Alembic/USD/FBX produced
    # v2.13 wave (Office + Diagrams + Sysadmin)
    "legacy_doc",          # legacyoffice — WordPerfect/AmiPro/Works/Publisher converted
    "iwork_doc",           # applepro — Pages/Numbers/Keynote converted
    "hwp_doc",             # hwpkit — Korean Hangul converted
    "diagram_doc",         # diagram — Mermaid/PlantUML/Graphviz/Visio rendered
    "diagram_tool_status", # diagram.check — diagram CLI availability
    "playlist_doc",        # playlist — M3U/PLS/XSPF/WPL/B4S converted
    "comic_book",          # comic — CBZ/CBR/CBT/CB7/PDF/EPUB converted
    "notebook_doc",        # notebooks — ipynb/py/md/Rmd/qmd produced
    "help_doc",            # helpkit — CHM extracted / PDF
    "tls_cert",            # tlskit — X.509/PKCS conversion
    "ssh_key",             # sshkit — SSH key format conversion
    "time_value",          # timefmt — timestamp representation set
    "cron_explain",        # timefmt.cron-explain — cron description
    "coord",               # coordfmt — single coordinate representation set
    "coord_csv",           # coordfmt.csv — bulk CSV with appended cols
    "config_doc",          # config — HCL/HOCON/properties/INI converted
    "dns_record",          # dnskit — zone-file <-> JSON/YAML/CSV
    "dns_zone_check",      # dnskit.validate — sanity findings
    # v2.14 wave (Streaming + Crypto + Niche A/V)
    "video_specialty",     # videopro — VOB/MTS/DV/3GP/elementary streams
    "stream_manifest",     # streaming — DASH/HLS/CMAF manifest output
    "image_seq",           # imageseq — sequence <-> video conversion
    "chiptune_audio",      # chiptune — NSF/SPC/VGM/SID/AY rendered to audio
    "audio_long_tail",     # audiomore — AIFF/CAF/DTS/TrueHD/HE-AAC produced
    "pgp_blob",            # gpgkit — armored / dearmored output
    "pgp_key",             # gpgkit.key-info — OpenPGP key metadata
    "wallet_bip39",        # wallet.bip39-check — mnemonic validation
    "wallet_keystore",     # wallet.keystore-info — Ethereum keystore probe
    "wallet_descriptor",   # wallet.descriptor — Bitcoin output descriptor parse
    "wallet_psbt",         # wallet.psbt-decode — PSBT heuristic probe
    # v2.15 wave (Healthcare + Finance + Engineering + Wire formats)
    "hl7_message",         # hl7 — v2 message parse / emit
    "fhir_doc",            # hl7 — FHIR JSON <-> XML
    "finance_doc",         # finance — OFX/QFX/QIF/IIF/MT940/CSV
    "cad_more",            # cadmore — 3MF / AMF mesh produced
    "cad_more_info",       # cadmore.gcode-info — G-code probe
    "genome_doc",          # genome — BCF / BGZF / tabix / peak
    "gistile",             # gistiles — COG / KMZ / KML produced
    "gistile_info",        # gistiles.info — MBTiles / PMTiles probe
    "imgmore",             # imgmore — JBIG2 / FAX / PICT / IFF converted
    "wire_blob",           # wirefmt — CBOR / msgpack / BSON / Ion converted
    # v2.16 wave (Email + Messaging + Calendar + Subtitles + Specialty Enterprise)
    "email_extra",         # emailpro — Outlook .msg / Apple .emlx / thread mbox
    "chat_doc",            # messaging — Telegram/Discord/Slack/iMessage/WhatsApp
    "calmore_doc",         # calmore — .icbu / Google Takeout calendar / LDIF
    "subtitle_extra",      # subextra — CEA-608/708 / iTT / ASS karaoke -> LRC
    "edi_doc",             # edi — X12 / EDIFACT structured decode
    "swift_mt",            # swift — SWIFT MT banking message decode
    "asn1_doc",            # asn1 — BER/DER/PEM <-> JSON tree
    "mobile_doc",          # mobile — iTunes backup / adb .ab backup
    "sql_doc",             # dbsql — SQL dialect translation / format / AST
    "spreadsheet_legacy",  # spreadsheet — Lotus / Quattro / Gnumeric / etc.
    "color_doc",           # colorfmt — color list expansion / CSS / JSON
    "game_asset",          # gameasset — VPK / WAD / PAK / PCK / PK3 listing
    # v2.17 wave (Specialty Engineering + Wire / Network / Music / Sci)
    "well_log",            # wells — LAS / DLIS oil-well log conversion
    "datawire_blob",       # datawire — Protobuf / Avro binary blob conversion
    "datawire_schema",     # datawire — Thrift / FBS schema introspection
    "nmea_msg",            # wirelesskit — NMEA / AIS GPS message decode
    "iac_doc",             # iac — IaC translation document output
    "iac_plan",            # iac — Terraform plan summary
    "genome_interval",     # bed — BED / bigBed / GFF / GTF interval conversion
    "swift_mx",            # swiftmx — SWIFT MX (ISO 20022 XML) banking
    "score_extra",         # musicmore — LilyPond / MuseScore notation conversion
    "playlist_extra",      # playlistmore — iTunes Library / Spotify export
    "netflow_doc",         # netflowkit — NetFlow / IPFIX flow record conversion
    "massspec_doc",        # proteomics — mzML / mzXML / MGF mass spectra
    # v2.18 wave (Source xform + DICOM-RT + niche eBooks + automotive + airline + tax)
    "source_xform",        # srctranspile — Py2->3 / CoffeeScript / Vue / JS->TS
    "rt_struct",           # dicomrt — RTSTRUCT contours
    "rt_plan",             # dicomrt — RTPLAN beams + control points
    "rt_dose",             # dicomrt — RTDOSE 3D dose grid
    "ebook_extra",         # ebookmore — FB2 / PalmDoc / PDB / Calibre fallback
    "bus_doc",             # bus — DBC CAN / ARXML / candump / OBD-II
    "airline_doc",         # iata — NDC / PNR / airport+airline codes
    "photolib_doc",        # mobilephotos — Takeout / Photos library / MediaStore / iOS .ips
    "tax_doc",             # taxkit — SIE / DATEV / IFX / ELSTER
    "data_extra",          # datakitmore — EDN / KDL / JSON5 / HJSON / RON / NestedText
    "diagram_extra",       # diagrammore — GraphML / Freemind / Lucidchart .lcc
    "bgp_doc",             # bgpkit — MRT RIB / BIRD / RPKI ROA
    "sdr_iq",              # sdrkit — SDR IQ format conversion
    "comic_meta",          # comicmeta — ComicInfo.xml inject / scrub / read
}


class Violation:
    __slots__ = ("path", "line", "rule", "detail")

    def __init__(self, path: Path, line: int, rule: str, detail: str):
        self.path = path
        self.line = line
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        rel = self.path.relative_to(REPO).as_posix()
        return f"{rel}:{self.line}  [{self.rule}]  {self.detail}"


def find_sidecars() -> list[Path]:
    return sorted(p for p in TOOLS.glob("*/sidecar.py") if p.is_file())


def check_frozen_guard(path: Path, src: str, tree: ast.AST) -> list[Violation]:
    """If the file calls pip install via subprocess, it must check sys.frozen first."""
    has_pip_call = False
    pip_lines: list[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            args_text = ast.dump(node)
            if "'pip'" in args_text and "'install'" in args_text:
                has_pip_call = True
                pip_lines.append(getattr(node, "lineno", 0))

    if not has_pip_call:
        return []

    # If pip install is present, verify sys.frozen is checked SOMEWHERE in
    # the file. We don't try to prove control-flow dominance — the audit-fix
    # pattern just needs the early return to exist.
    if "getattr(sys, 'frozen'" in src or 'getattr(sys, "frozen"' in src:
        return []

    return [Violation(
        path, pip_lines[0] if pip_lines else 1, "frozen-guard",
        f"calls subprocess pip install (line {pip_lines[0]}) without "
        f"`if getattr(sys, 'frozen', False): return` short-circuit — "
        f"will fork-bomb when PyInstaller-frozen",
    )]


def check_error_code_field(path: Path, tree: ast.AST) -> list[Violation]:
    """Every literal emit({event: 'error', ...}) must include a 'code' key.

    Handles three common shapes:
      emit({"event": "error", "code": "...", "message": "..."})
      emit("error", code="...", message="...")
      emit_error(...)  → trust the helper to format correctly
    """
    violations: list[Violation] = []

    def keys_in_dict(d: ast.Dict) -> set[str]:
        out: set[str] = set()
        for k in d.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                out.add(k.value)
        return out

    def value_for_key(d: ast.Dict, key: str) -> str | None:
        for k, v in zip(d.keys, d.values):
            if isinstance(k, ast.Constant) and k.value == key and isinstance(v, ast.Constant):
                return v.value
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        # Shape A: emit({...})
        if (isinstance(node.func, ast.Name) and node.func.id == "emit"
                and len(node.args) == 1 and isinstance(node.args[0], ast.Dict)):
            d = node.args[0]
            ev = value_for_key(d, "event")
            if ev == "error" and "code" not in keys_in_dict(d):
                violations.append(Violation(
                    path, node.lineno, "error-code-field",
                    "emit({'event':'error', ...}) missing 'code' key — "
                    "SidecarRunner will route as errorCode='unknown'",
                ))

        # Shape B: emit("error", code=..., message=...)
        elif (isinstance(node.func, ast.Name) and node.func.id == "emit"
              and node.args and isinstance(node.args[0], ast.Constant)
              and node.args[0].value == "error"):
            kw_names = {kw.arg for kw in node.keywords if kw.arg}
            if "code" not in kw_names:
                violations.append(Violation(
                    path, node.lineno, "error-code-field",
                    "emit('error', ...) missing code= keyword arg",
                ))

    # emit_error helpers: enforce that the helper signature accepts a `code`
    # parameter. Avoids the lipsight-style mistake where every call site loses
    # the field because the helper drops it.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "emit_error":
            arg_names = {a.arg for a in node.args.args}
            if "code" not in arg_names and not node.args.kwonlyargs:
                violations.append(Violation(
                    path, node.lineno, "error-code-field",
                    "emit_error() helper has no 'code' parameter — "
                    "every error from this sidecar will reach the UI as 'unknown'",
                ))

    return violations


def check_known_events(path: Path, tree: ast.AST) -> list[Violation]:
    """Flag {event: '<typo>'} literals that aren't in KNOWN_EVENTS.

    Catches accidental typos like "completed" vs "complete" or "errors" vs "error".
    """
    violations: list[Violation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in {"emit", "emit_progress", "emit_log",
                                 "emit_complete", "emit_error"}:
            continue

        # Direct emit("<name>", ...) form
        if node.func.id == "emit" and node.args and isinstance(node.args[0], ast.Constant):
            ev = node.args[0].value
            if isinstance(ev, str) and ev not in KNOWN_EVENTS:
                violations.append(Violation(
                    path, node.lineno, "known-events",
                    f"unknown event name {ev!r} — add to KNOWN_EVENTS in "
                    f"check_contract.py if intentional",
                ))

        # emit({"event": "<name>", ...}) form
        if (node.func.id == "emit" and node.args
                and isinstance(node.args[0], ast.Dict)):
            for k, v in zip(node.args[0].keys, node.args[0].values):
                if (isinstance(k, ast.Constant) and k.value == "event"
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)
                        and v.value not in KNOWN_EVENTS):
                    violations.append(Violation(
                        path, node.lineno, "known-events",
                        f"unknown event name {v.value!r}",
                    ))

    return violations


def check_one(path: Path) -> list[Violation]:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        return [Violation(path, e.lineno or 0, "syntax", f"parse failed: {e.msg}")]

    return (
        check_frozen_guard(path, src, tree)
        + check_error_code_field(path, tree)
        + check_known_events(path, tree)
    )


def main(argv: list[str] | None = None) -> int:
    sidecars = find_sidecars()
    if not sidecars:
        print("no sidecars found under tools/*/sidecar.py", file=sys.stderr)
        return 2

    all_violations: list[Violation] = []
    for path in sidecars:
        all_violations.extend(check_one(path))

    if not all_violations:
        print(f"OK — {len(sidecars)} sidecar(s) conform to the NDJSON contract")
        return 0

    print(f"FAIL — {len(all_violations)} violation(s) across "
          f"{len({v.path for v in all_violations})} sidecar(s):", file=sys.stderr)
    print(file=sys.stderr)
    for v in all_violations:
        print(f"  {v}", file=sys.stderr)
    print(file=sys.stderr)
    print("Reference: see ROADMAP.md #49 for the contract.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
