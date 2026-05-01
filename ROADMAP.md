# UniversalConverterX -- Format Conversion Roadmap

Living catalogue of every raw file-format conversion still missing from
UCX, organized by domain, prioritized for impact, and sized for sequencing.

**Current state (v2.12.0):** 88 sidecar engines, 121 shipped presets,
70+ Toolbox tiles, 4 desktop projects (Core, Console, UI, ShellExtension)
plus PowerShell module + REST `ucx serve`.

**Goal:** Cover every file format a working professional could plausibly
need. Beat each competitor on at least one axis: *coverage* (we ship the
formats they don't), *batch UX* (drop a folder, get every output),
*offline* (no cloud, no account), or *programmability* (CLI + REST + PS
module).

---

## Legend

* **P0** -- High demand, missing today. Ship next.
* **P1** -- Medium demand or specialist niche with active community.
* **P2** -- Long tail / archival / single-vendor formats. Nice-to-have.
* **Size** -- Rough sidecar build effort: **S** = a few hours, **M** = a day, **L** = multi-day (heavy native deps or proprietary protocols).
* **Backend** -- The OSS library / CLI we'll wrap.

---

## Already Covered (don't re-add)

For reference -- this is the existing surface so we don't accidentally re-scope:

| Domain | Sidecar | Formats |
| --- | --- | --- |
| Image (modern) | `heicshift` | HEIC / HEIF / AVIF / JPEG / PNG / WebP / TIFF / BMP / JXL |
| Image (HDR) | `hdrkit` | Radiance HDR / OpenEXR / PFM / 16-bit PNG-TIFF + tone-mapping |
| Image (vector) | `vectorkit` | AI / EPS / PS / EMF / WMF / SVG / SVGZ / CDR / VSD via Inkscape |
| Image (RAW) | `rawphoto` | CR2 / CR3 / NEF / ARW / DNG / ORF / RAF / RW2 (LibRaw) |
| Image (layered) | `psdkit` | PSD / PSB / XCF flatten + per-layer extract |
| Image (niche) | `rasterimg` | PCX / TGA / DPX / SGI / Sun / PCD / Netpbm / APNG / XPM / Palm |
| Image (textures) | `texturekit` | DDS / KTX / KTX2 / ASTC / EXR / TGA |
| Image (icons) | `iconkit` | PNG -> Windows .ico + Apple .icns / .iconset |
| Image (medical) | `dicomkit` | DICOM -> PNG / JPEG / TIFF + anonymize |
| Image (ICC) | `iccprofile` | Apply / embed / strip color profiles |
| Image (Lottie) | `lottiekit` | Lottie / TGS -> GIF / MP4 / WebP / APNG / SVG |
| Video | `videocrush` | MP4 / MKV / MOV / AVI / WebM (H.264 / H.265 / AV1 / VP9 / ProRes) |
| Video extras | `clipforge` | concat / speed / reverse / 3D-LUT / HDR->SDR |
| Video (GIF) | `gifstudio` | GIF authoring + optimization |
| Video (frames) | `framesnap` | Frame extraction (precise / batch) |
| Audio (codecs) | `audiopro` | DSD / APE / WV / TAK / TTA / AC3 / DTS / WMA / AMR / SPEEX / GSM / AU / VOC / RA / MusePack |
| Audio (tags) | `audiotag` | ID3 / FLAC / Ogg / M4A / APE metadata read/write/strip |
| Audio (tracker) | `trackermod` | MOD / IT / XM / S3M -> WAV / FLAC / MP3 |
| Audio (MIDI) | `midisynth` | MIDI + SoundFont -> WAV / FLAC / MP3 |
| Documents | `docconvert` | DOCX / PDF / ODT / RTF / XLSX / ODS / CSV / PPTX / EPUB / HTML (LibreOffice) |
| Documents (Pandoc) | `pandoc-cli` | Markdown / RST / DOCX / EPUB / HTML / LaTeX / DocBook / AsciiDoc / Org / MediaWiki / Textile |
| PDF | `pdftools` | merge / split / rotate / extract / encrypt / compress |
| PDF (OCR) | `pdfocr` | Searchable PDF via ocrmypdf |
| PDF -> MD | `pdfmarkdown` | pymupdf4llm / marker / Docling / MinerU |
| Subtitles | `subconvert` | SRT / VTT / ASS / SSA / SUB |
| Subtitles (interchange) | `subkit` | SAMI / TTML / DFXP / SCC / EBU STL / MicroDVD / LRC / SBV |
| Subtitles (OCR) | `subocr` | PGS / VobSub -> SRT |
| Fonts | `fontconvert` | TTF / OTF / WOFF / WOFF2 |
| Fonts (subset) | `fontsubset` | Webfont subsetter via fontTools |
| eBooks | `ebookconvert` | EPUB / MOBI / AZW3 / PDF / FB2 / DOCX (Calibre) |
| Archives | `archive` | 7z / ZIP / TAR / RAR / ISO / CAB / MSI |
| Archives (niche) | `morearchive` | SIT / LHA / ARJ / DEB / RPM / DMG / IPA / APK / MSIX / NUPKG |
| Email | `mailbox` | MBOX / EML / Maildir |
| Email (PST) | `mailimport` | Outlook PST / OST -> MBOX or per-message EML |
| Calendar | `calconvert` | ICS / VCF |
| Web archives | `webarchive` | HAR / WARC |
| Bookmarks | `bookmark` | Chrome / Firefox / Safari / Opera / Netscape / CSV |
| Data (text) | `datakit` | JSON / YAML / TOML / XML / CSV / TSV / NDJSON |
| Data (scientific) | `datasci` | Parquet / Feather / Avro / ORC / HDF5 / NPY / NPZ / MAT / NetCDF / FITS |
| Data (legacy DB) | `dbtools` | Access / DBF / SAS / SPSS / Stata / R Data |
| Localization | `i18nkit` | PO / MO / XLIFF / TMX / RESX / .strings / JSON-i18n / YAML |
| 3D (mesh) | `meshconvert` | STL / OBJ / PLY / GLB / GLTF / FBX / DAE / 3DS |
| 3D (point cloud) | `pointcloud` | PLY / PCD / XYZ / PTS / OBJ / LAS / LAZ / E57 |
| 3D (animation) | `animkit` | BVH / Alembic / USD / USDZ / FBX / glTF / VRM / Collada |
| Engineering CAD | `engcad` | STEP / IGES / BREP / STL (Open CASCADE) |
| 2D CAD | `cadkit` | DXF / DWG (ODA + ezdxf) |
| GIS | `gisconvert` | KML / GPX / GeoJSON / Shapefile / GeoPackage (GDAL) |
| Disk images | `diskimage` | RAW / QCOW2 / VMDK / VHD / VHDX / VDI / QED |
| Game ROMs | `gametools` | IPS / BPS / UPS / NES-SNES-N64 ROM ops / CHD <-> CUE/BIN |
| Networks | `netcap` | PCAP <-> PCAPNG + CSV summary |
| Logs | `logkit` | Apache / Nginx / syslog / Windows .evtx -> JSONL |
| Music notation | `music` | MusicXML / MIDI / ABC / MuseScore / GuitarPro |
| Color (LUT) | `lutgen` | .cube / .3dl 3D LUT generation |
| Chemistry | `chemkit` | SMILES / MOL / SDF / MOL2 / PDB / XYZ / CIF / InChI |
| Bioinformatics | `biokit` | FASTA / FASTQ / GenBank / EMBL / VCF / BAM / SAM / Newick |
| Medical (3D) | `medkit` | NIfTI / Analyze / MetaImage / NRRD / MINC / GIPL / VTK |
| Apple plist | `plistkit` | binary / XML / JSON plist |
| Microcontroller | `hexkit` | Intel HEX / Motorola SREC / TI-TXT / raw binary |
| Text | `textencode` | Charset / line-ending / BOM normalization |
| Text | `hashkit` | MD5 / SHA-1/2/3 / BLAKE2/3 / xxHash / CRC32 |
| Text | `encodekit` | Base64 / Base32 / Base85 / Hex / data: URL |
| Code | `codeformat` | prettier / black / gofmt / rustfmt / clang-format |

---

# Remaining Gaps -- The Roadmap

Each entry: *what we add* | *what's notable* | *backend* | *priority* | *size*.

## Wave A -- Office / Legacy Documents

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `legacyoffice` | WordPerfect (.wpd, .wpt, .wpg) | libwpd / libwpg via libreoffice | P0 | M |
| `legacyoffice` | WordStar (.ws, .wsd) | wordstar2text | P1 | M |
| `legacyoffice` | AmiPro (.sam) / KOffice / AbiWord (.abw) | libreoffice CLI | P1 | S |
| `legacyoffice` | Microsoft Works (.wps, .wpt) | libreoffice CLI | P1 | S |
| `legacyoffice` | Microsoft Publisher (.pub) | libmspub | P1 | M |
| `legacyoffice` | StarOffice 1.x (.sxw, .sxc, .sxi) | libreoffice CLI | P1 | S |
| `hwpkit` | HWP / HWPX (Korean Hangul) | pyhwp + libreoffice | P0 | M |
| `applepro` | Pages / Numbers / Keynote (.pages/.numbers/.key) | unzip + iWork XML | P0 | M |
| `helpkit` | CHM (compiled HTML help) | pychm + extract | P1 | M |
| `helpkit` | WinHelp (.hlp) | helpdeco extract | P2 | L |
| `mathnotebook` | Mathematica (.nb) | wolframclient (read-only) | P2 | M |

**Why P0 for `applepro` + `hwpkit`:** common formats with no good Windows-side OSS converter; user pain is real.

---

## Wave B -- Spreadsheet & Database Long Tail

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `spreadsheet` | Lotus 1-2-3 (.wk1, .wk3, .wks, .123) | libreoffice CLI | P1 | S |
| `spreadsheet` | Quattro Pro (.qpw, .wb1, .wb2) | libreoffice CLI | P1 | S |
| `spreadsheet` | Apple Numbers | unzip + iWork XML | P1 | M |
| `spreadsheet` | Gnumeric (.gnumeric) | gnumeric ssconvert | P1 | S |
| `spreadsheet` | DIF / SLK | pure Python | P2 | S |
| `dbsql` | SQL DDL dialect translation: MySQL <-> PostgreSQL <-> SQLite <-> Oracle <-> MSSQL | sqlglot | P0 | M |
| `dbsql` | MySQL `mysqldump` <-> PostgreSQL `pg_dump` | sqlglot + pgloader | P0 | M |
| `dbexport` | Oracle DMP / IBM DB2 export -> CSV | proprietary CLI shellouts | P2 | L |
| `dbexport` | FoxPro / Paradox (.db) | dbfread + pypdb | P2 | M |
| `dbexport` | MS SQL backup (.bak) -> bacpac | sqlpackage CLI | P2 | L |

**Why P0 for `dbsql`:** SQL dialect translation via `sqlglot` is the killer feature for the data-engineer crowd -- no good GUI for it exists.

---

## Wave C -- Niche Image Formats

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `imgmore` | JBIG2 (.jb2) | jbig2dec / jbig2enc | P1 | M |
| `imgmore` | FAX TIFF Group 3 / 4 | libtiff via Pillow | P1 | S |
| `imgmore` | Mac PICT (.pict, .pct) | imagemagick CLI | P2 | S |
| `imgmore` | Windows DIB (.dib) | Pillow native | P2 | S |
| `imgmore` | Amiga IFF / ILBM (.iff, .lbm) | imagemagick / pyiff | P2 | M |
| `imgmore` | Atari Degas (.pi1, .pi2, .pi3) | custom parser | P2 | M |
| `imgmore` | WPG (WordPerfect Graphics) | libwpg | P2 | M |
| `imgmore` | TIM (PSX texture), GIM (PSP) | custom parser | P2 | L |
| `imgmore` | Sega VDP texture formats | custom parser | P2 | L |
| `imgmore` | Adobe layered TIFF (.tif w/ layers) | tifffile | P1 | S |

**Bundle into one sidecar** (`imgmore`) since each is small + Pillow-friendly.

---

## Wave D -- Video Long Tail

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `videopro` | VOB / EVO (DVD-Video / EVO Blu-ray) | FFmpeg + libdvdread | P0 | S |
| `videopro` | MTS / M2TS (Blu-ray AVCHD) | FFmpeg | P0 | S |
| `videopro` | DV / DVCPRO (camcorder tape capture) | FFmpeg | P1 | S |
| `videopro` | 3GP / 3G2 (mobile container) | FFmpeg | P1 | S |
| `videopro` | F4V / SWF (Adobe Flash) | FFmpeg + swftools | P1 | M |
| `videopro` | HEVC / H.264 elementary streams (.h264, .h265, .hevc) | FFmpeg | P0 | S |
| `videopro` | Y4M raw uncompressed | FFmpeg | P1 | S |
| `videopro` | AVS / AVS2 (Chinese AVS) | FFmpeg + libavs | P2 | M |
| `videoraw` | Apple ProRes RAW | FFmpeg + Apple SDK | P2 | L |
| `videoraw` | Cinema DNG sequence | rawpy + ffmpeg muxer | P1 | M |
| `videoraw` | BRAW (Blackmagic RAW) | BRAW SDK | P2 | L |
| `videoraw` | RED .r3d | RED SDK | P2 | L |
| `videoraw` | ARRI ALEXA proprietary | (no OSS path) | P2 | -- |
| `streaming` | DASH .mpd <-> HLS .m3u8 manifest+segment conversion | shaka-packager | P0 | M |
| `streaming` | CMAF segments + Smooth Streaming .ism | shaka-packager | P1 | M |
| `imageseq` | DPX / Cineon / OpenEXR / TIFF image sequence <-> MP4 / MOV / MKV | FFmpeg sequence demuxer | P0 | S |

**Why P0 for `videopro` + `imageseq`:** these are *the* common gaps users hit when converting from broadcast or VFX workflows.

---

## Wave E -- Audio Long Tail

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `chiptune` | NSF (NES), SPC (SNES), VGM (multi-system), GBS (GameBoy), HES (PCEngine), KSS, GYM, S98, AY | game-music-emu (gme) | P0 | M |
| `chiptune` | C64 SID (.sid), AHX, HVL (Amiga) | sidplayfp + AHXplay | P1 | M |
| `chiptune` | MED / OctaMED / MTM / ULT / FAR (extra trackers beyond MOD/IT/XM/S3M) | libxmp | P1 | S |
| `audiomore` | AIFF / AIFC (.aif, .aifc) | FFmpeg + python-soundfile | P0 | S |
| `audiomore` | IFF-8SVX (Amiga sound) | FFmpeg | P2 | S |
| `audiomore` | ULAW / ALAW (telephony) | FFmpeg | P1 | S |
| `audiomore` | Apple CAF (Core Audio Format) | FFmpeg + caf-parser | P0 | S |
| `audiomore` | Sony ATRAC3 (.aa3, .oma, .at3) | FFmpeg + at3tool (read-only) | P1 | M |
| `audiomore` | DSD64/128/256 explicit rate handling | FFmpeg | P1 | S |
| `audiomore` | DTS Master Audio + TrueHD lossless | FFmpeg | P0 | S |
| `audiomore` | HE-AAC v2 + xHE-AAC | FFmpeg + libfdk-aac | P1 | S |
| `ringtone` | RTTTL / iMelody (.imy) / NRT | pure Python | P2 | S |
| `karaoke` | KFN / K05 / KAR (extends midisynth) | custom + midisynth | P2 | M |
| `audiocue` | EAC `.cue` sheet <-> FLAC + tags + EAC log validation | pycdio + custom | P1 | M |

**Why P0 for `chiptune` + AIFF / CAF / TrueHD / DTS-MA:** these are the formats that hit the long-tail audiophile / retro-gaming / pro broadcast crowd.

---

## Wave F -- Email & Messaging Long Tail

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `emailpro` | Outlook .msg (single message) -> .eml | extract-msg | P0 | S |
| `emailpro` | Lotus Notes .nsf | NotesSQL + open-nsf | P1 | L |
| `emailpro` | Windows Live Mail | EmlFile parsing | P1 | M |
| `emailpro` | EML thread -> Maildir / mbox archive | stdlib | P1 | S |
| `messaging` | WhatsApp .crypt12 / .crypt14 backup | wa-crypt-tools | P1 | M |
| `messaging` | Telegram Desktop chat export (.json/.html) | json + html parser | P1 | S |
| `messaging` | iMessage / SMS DB (`chat.db`) -> JSON | sqlite + pmsg | P1 | M |
| `messaging` | Discord export -> JSON | dispatcher | P2 | S |
| `messaging` | Slack export -> JSON | unzip + parse | P2 | S |

**Why P0 for `emailpro` (.msg):** Outlook saves single messages as .msg by default -- this is the missing companion to PST.

---

## Wave G -- Calendar / Contact Long Tail

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `calmore` | Apple .icbu (calendar backup bundle) | unzip + ics | P1 | S |
| `calmore` | Outlook .ost calendar items -> ICS | pypff + ics | P1 | M |
| `calmore` | Google Takeout calendar JSON -> ICS | json + ics | P1 | S |
| `calmore` | LDAP LDIF <-> vCard | python-ldap | P1 | S |

---

## Wave H -- Subtitle / Caption Edge Cases

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `subextra` | CEA-608 / CEA-708 closed captions <-> SRT | ccextractor + custom | P0 | M |
| `subextra` | SMIL (Synchronized Multimedia Integration Language) | ElementTree | P1 | S |
| `subextra` | iTT (iTunes Timed Text) | xml + DFXP path | P1 | S |
| `subextra` | STL (Spruce Subtitle Format) -- different from EBU STL | parser | P2 | M |
| `subextra` | Web-VTT cue formatting + `region` blocks | pysubs2 + extension | P1 | S |
| `subextra` | Karaoke ASS -> LRC time-aligned | pysubs2 | P1 | S |

---

## Wave I -- 3D / Game Asset Niche

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `gameasset` | Source engine (.smd, .qc, .vmt, .vtf) | srctools | P1 | M |
| `gameasset` | Quake (.mdl, .md2, .md3) | quake-mdl | P2 | M |
| `gameasset` | WoW M2 / WMO / BLP | pywowlib | P2 | L |
| `gameasset` | TIM (PSX texture) / BFRES (Switch) | byml + sarc | P2 | L |
| `gameasset` | Unity AssetBundle | UnityPy | P1 | M |
| `gameasset` | Godot scene formats (.tscn, .res) | godot-parser | P2 | M |
| `cadmore` | 3MF (3D Manufacturing Format) | lib3mf | P0 | M |
| `cadmore` | AMF (Additive Manufacturing Format) | xmlschema + amf-tools | P0 | S |
| `cadmore` | G-code (.gcode, .nc) -- format normalization + slicer settings | py-gcode | P1 | M |
| `cadmore` | X_T / Parasolid (.x_t, .x_b) | (closed format -- read-only via OCC) | P2 | L |
| `cadmore` | SAT / ACIS | (closed format) | P2 | L |
| `cadmore` | JT (Siemens) | (closed format) | P2 | L |
| `pcb` | Gerber RS-274X + Excellon drill | pcb-tools | P1 | M |
| `pcb` | KiCad PCB / Schematic <-> Eagle <-> Altium | kicad-python | P1 | L |

**Why P0 for `cadmore` (3MF + AMF):** the modern 3D-printing standards -- STL is the legacy, 3MF/AMF are what current slicers want.

---

## Wave J -- GIS & Geospatial Long Tail

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `gistiles` | MBTiles (Mapbox tile pyramid) | mbtiles + sqlite | P0 | S |
| `gistiles` | PMTiles (Protomaps single-file) | pmtiles | P0 | S |
| `gistiles` | MVT / PBF (Mapbox Vector Tiles) | mapbox-vector-tile | P1 | S |
| `gistiles` | COG (Cloud Optimized GeoTIFF) | rio-cogeo | P0 | S |
| `gistiles` | KMZ (zipped KML) | unzip + kml | P0 | S |
| `gispoi` | Garmin .gdb / .img (POI) | gpsbabel | P1 | M |
| `gispoi` | TomTom .ov2, Magellan .upt | gpsbabel | P2 | M |
| `wells` | LAS well-log (different from LiDAR LAS) | lasio | P1 | S |
| `seismic` | SEG-Y / SEG-D seismic data | obspy | P1 | M |

---

## Wave K -- Network / Security / DevOps

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `dnskit` | DNS zone files (.zone) <-> JSON | dnspython | P1 | S |
| `dnskit` | BIND9 named.conf parsing | dnspython | P1 | S |
| `netcap` (extend) | NetFlow v5/v9 / IPFIX -> PCAP / JSON | softflowd + pyfixbuf | P1 | M |
| `netcap` (extend) | BGP RIB MRT dumps | mrtparse | P2 | S |
| `tlskit` | X.509 certificates: PEM / DER / PKCS7 / PKCS12 metadata | cryptography | P0 | S |
| `tlskit` | OpenSSL key formats (PEM/DER) metadata + format conversion | cryptography | P0 | S |
| `sshkit` | OpenSSH <-> PKCS8 <-> PuTTY .ppk <-> OpenSSL key conversion | paramiko | P0 | S |
| `gpgkit` | GPG / OpenPGP key armoring (ASCII <-> binary) | python-gnupg | P1 | S |
| `nmapkit` | Nmap XML / GNMAP / JSON | python-libnmap | P2 | S |
| `wirelesskit` | NMEA GPS + AIS messages -> JSON / KML / GPX | pynmea2 | P1 | S |
| `wirelesskit` | SDR IQ files (.iq, .wav-iq, .cu8) format conversion | numpy + iq-tools | P2 | M |
| `bus` | DBC (CAN bus database) <-> ARXML / FIBEX | cantools | P2 | M |

**Why P0 for `tlskit` + `sshkit`:** every dev / sysadmin hits these. Key format conversion is annoying without a reliable GUI.

---

## Wave L -- Financial / Accounting

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `finance` | OFX / QFX (Quicken / financial) <-> CSV / JSON | ofxparse | P0 | S |
| `finance` | QIF (Quicken Interchange Format) | qifparse | P0 | S |
| `finance` | IIF (QuickBooks) | iif-parser | P1 | S |
| `finance` | IFX (Interactive Financial Exchange) | xml + xsd | P2 | M |
| `banking` | CAMT.052 / CAMT.053 / MT940 / MT942 | mt940-tools | P1 | M |
| `banking` | ISO 20022 messages | xmlschema + iso20022 lib | P1 | L |
| `banking` | SEPA pain.001 / pain.008 | sepa-utils | P2 | S |
| `tax` | German DATEV exports | datev-python | P2 | M |
| `accounting` | SIE (Swedish accounting) | sie-parser | P2 | S |
| `accounting` | ELSTER / FATCA / CRS XSD-driven generation | xmlschema | P2 | L |

**Why P0 for `finance` (OFX/QFX/QIF):** common export formats from banks; users want to convert to CSV for analysis.

---

## Wave M -- Medical / Healthcare Beyond DICOM

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `hl7` | HL7 v2 messages (pipe-delimited) <-> JSON | hl7apy | P0 | S |
| `hl7` | HL7 FHIR R4/R5 <-> JSON / XML | fhir.resources | P0 | M |
| `hl7` | HL7 v3 / CDA documents | hl7apy + xml | P1 | M |
| `medkit` (extend) | DICOM-RT (radiation therapy structure sets, plans, doses) | pydicom + dcmqi | P1 | M |
| `medkit` (extend) | MetaImage with TRE / tag preservation | SimpleITK | P1 | S |
| `medkit` (extend) | Bruker / GE / Siemens raw scanner data -> DICOM | dcmqi + vendor SDKs | P2 | L |
| `genome` | BCF binary VCF <-> VCF text | pysam + bcftools | P0 | S |
| `genome` | TSV <-> Variant Effect Predictor JSON | hgvs + custom | P2 | M |
| `genome` | PED / FAM (PLINK pedigree) | pyplink | P2 | S |
| `bed` | BED <-> narrowPeak / broadPeak / bigBed (genome intervals) | pybedtools | P1 | S |
| `proteomics` | mzML / mzXML / mzIdentML (mass spec) | pyteomics | P2 | M |

**Why P0 for `hl7` + BCF:** HL7 messaging is *the* missing healthcare piece; BCF is the binary VCF that bioinformatics pipelines actually use.

---

## Wave N -- Music Notation Beyond v2.11

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `music` (extend) | Sibelius (.sib) | (proprietary, requires Sibelius CLI) | P2 | L |
| `music` (extend) | Finale (.musx, .mus) | finale-python (read) | P2 | L |
| `music` (extend) | Capella (.cap, .capx) | capella-python | P2 | M |
| `music` (extend) | LilyPond (.ly) <-> MusicXML | lilypond CLI | P0 | M |
| `music` (extend) | NIFF (Notation Interchange File Format) | (legacy, niche) | P2 | M |
| `music` (extend) | DARMS / kern (humdrum) | music21 (already supports) | P1 | S |

---

## Wave O -- Drawing / Diagramming

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `diagram` | Visio (.vsd, .vsdx, .vsdm) -> PDF / SVG / PNG | libreoffice CLI / libvisio | P0 | M |
| `diagram` | draw.io (.drawio, .xml) <-> PNG / SVG | drawio-export CLI | P0 | M |
| `diagram` | Mermaid (.mmd) -> SVG / PNG / PDF | mermaid-cli | P0 | S |
| `diagram` | PlantUML (.puml) -> SVG / PNG | plantuml CLI | P0 | S |
| `diagram` | Graphviz (.dot, .gv) -> SVG / PNG / PDF | graphviz CLI | P0 | S |
| `diagram` | Lucidchart (.lcc) export -> SVG | unzip + parse | P1 | M |
| `diagram` | Excalidraw (.excalidraw) -> PNG / SVG | excalidraw CLI | P1 | S |
| `diagram` | OmniGraffle | osascript on macOS only | P2 | -- |
| `diagram` | yEd (.graphml) -> SVG / PNG | graphml + custom | P1 | M |

**Why P0 for the whole `diagram` sidecar:** developers and architects need this constantly. Mermaid / PlantUML / Graphviz CLI wrappers are tiny and high-impact.

---

## Wave P -- Configuration / Infrastructure-as-Code

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `config` | HCL (HashiCorp / Terraform) <-> JSON | python-hcl2 | P0 | S |
| `config` | HOCON (Typesafe Config) <-> JSON | pyhocon | P1 | S |
| `config` | Java .properties <-> JSON / YAML | jproperties | P1 | S |
| `config` | Apache HTTPD config + Nginx config -> JSON-ish | augeas / pyparsing | P1 | M |
| `config` | systemd unit files | configparser | P1 | S |
| `config` | INI <-> TOML <-> YAML <-> JSON (already in datakit; broaden) | datakit extension | P1 | S |
| `iac` | Terraform -> CloudFormation -> ARM -> Pulumi (cross-IaC translation) | tf2cfn / iac-convert | P2 | L |
| `iac` | Helm Chart -> Kustomize -> plain manifests | helm template | P1 | M |
| `iac` | Docker Compose v1 -> v2 -> v3 | yaml + transform | P1 | S |

**Why P0 for HCL:** Terraform's native format with no good GUI conversion path.

---

## Wave Q -- Programming / Source

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `srctranspile` | Python 2 -> Python 3 | 2to3 | P2 | S |
| `srctranspile` | JavaScript -> TypeScript bootstrapping | tsc / typewiz | P2 | M |
| `srctranspile` | CoffeeScript -> JavaScript | decaf | P2 | S |
| `srctranspile` | Vue 2 -> Vue 3 SFC | vue-codemod | P2 | M |
| `notebooks` | Jupyter .ipynb <-> Markdown <-> HTML <-> Python <-> R Markdown | nbconvert + jupytext | P0 | S |
| `notebooks` | Observable / Polyglot notebooks | custom | P2 | M |

**Why P0 for `notebooks`:** ipynb conversion is super common, currently goes through Pandoc but a dedicated path with jupytext is much cleaner.

---

## Wave R -- Streaming / Container / Manifest

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `playlist` | M3U / M3U8 / PLS / XSPF / WPL / ASX / B4S playlist conversion | pure Python | P0 | S |
| `playlist` | iTunes Library .xml <-> M3U / JSON | plistlib + parse | P1 | S |
| `playlist` | Spotify export JSON <-> M3U | json | P2 | S |
| `playlist` | Roon backup / RoonRadio | (proprietary) | P2 | -- |

**Why P0 for `playlist`:** every media player has its own format; this is a frequent ask.

---

## Wave S -- E-Books / Comics Long Tail

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `comic` | CBZ / CBR / CBT / CB7 -> PDF / EPUB | unrar/unzip + img2pdf | P0 | S |
| `comic` | Comic Rack metadata (.cbz with ComicInfo.xml) | xml + zip | P1 | S |
| `ebookmore` | LRF / LRX (Sony Reader) | calibre + pylrf | P2 | M |
| `ebookmore` | TPZ (Topaz Kindle, DRM-free old) | mobiunpack | P2 | M |
| `ebookmore` | Daisy DTBook (.daisy) | daisy-pipeline CLI | P2 | M |
| `ebookmore` | PalmDoc / iSilo | mobi + custom | P2 | S |

---

## Wave T -- Specialty Enterprise

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `edi` | EDI X12 (US healthcare / supply chain) -> JSON | bots-edi / pyx12 | P1 | M |
| `edi` | EDIFACT (international supply chain) -> JSON | pydifact | P1 | M |
| `swift` | SWIFT MT (banking messages) -> JSON | swift-mt-message | P1 | M |
| `swift` | SWIFT MX (modern XML banking) | iso20022 + xml | P1 | M |
| `iata` | IATA NDC (airline) | xmlschema | P2 | M |
| `iata` | TAP / SISCAB / BSP-link | various proprietary | P2 | L |
| `asn1` | ASN.1 BER / DER / PEM <-> JSON / XML | asn1crypto | P1 | M |

---

## Wave U -- Time / Coordinate Utilities

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `timefmt` | ISO 8601 <-> Unix epoch <-> Excel serial date <-> mainframe Julian | dateutil | P0 | S |
| `timefmt` | Cron expression <-> next-N-runs human readable | cron-descriptor + croniter | P1 | S |
| `coordfmt` | DD <-> DMS <-> UTM <-> MGRS <-> Geohash <-> Plus Codes | pyproj + mgrs | P0 | S |
| `colorfmt` | RGB <-> HSL <-> Lab <-> HEX <-> named CSS color batch conversion | colorspacious | P1 | S |

**Why P0 for `timefmt` + `coordfmt`:** small, high-utility, and "it just works" wins users instantly.

---

## Wave V -- Mobile Backups

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `mobile` | iOS iTunes backup -> file tree extraction | iphone-backup-decoder | P1 | M |
| `mobile` | Android adb backup (.ab) -> tar | android-backup-extractor | P1 | S |
| `mobile` | Android Photos library export -> file tree | unzip + json | P1 | S |
| `mobile` | iCloud `.icbu` calendar backup (covered in Wave G) | -- | -- | -- |

---

## Wave W -- Data Standards Beyond CSV

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `datakit` (extend) | EDN (Extensible Data Notation) | edn-format | P2 | S |
| `datakit` (extend) | KDL (Cuddly Data Language) | kdl-py | P2 | S |
| `datakit` (extend) | StrictYAML / YAML 1.1 vs 1.2 dialect | strictyaml | P2 | S |
| `datakit` (extend) | UBJSON / CBOR / MessagePack / BSON / Smile / Ion | cbor2 + msgpack + ion-python | P0 | S |
| `datakit` (extend) | Protocol Buffers (.proto) <-> JSON / binary | protobuf | P0 | M |
| `datakit` (extend) | Apache Thrift binary <-> JSON | thrift | P1 | M |
| `datakit` (extend) | Cap'n Proto <-> JSON | capnp | P1 | M |
| `datakit` (extend) | FlatBuffers <-> JSON | flatbuffers | P1 | M |

**Why P0 for binary data formats (CBOR / MessagePack / Protobuf):** these are the wire formats every modern API uses; a "convert this protobuf to JSON" tool is genuinely useful.

---

## Wave X -- Cryptocurrency / Wallet (Read-only)

| Sidecar | Formats | Backend | P | Size |
| --- | --- | --- | --- | --- |
| `wallet` | BIP39 mnemonic -> seed (read-only, NEVER write) | bip-utils | P2 | S |
| `wallet` | Wallet.dat / Bitcoin Core export metadata | python-bitcoinlib | P2 | M |
| `wallet` | Ethereum keystore JSON <-> raw key (research/migration only) | eth-keyfile | P2 | S |
| `wallet` | PSBT (Partially Signed Bitcoin Transaction) decode | python-bitcoinlib | P2 | S |

**Note:** All read-only / metadata. Never expose private-key-derivation paths in the UI without explicit warnings.

---

# Aggregate Tally

* **88 sidecars shipped** (v2.0 -> v2.12).
* **~ 30 P0 sidecars / sidecar-extensions** in the roadmap above. Sequencing them takes 4-6 more "waves" at the current pace (~10 sidecars per wave).
* **~ 50 P1 / P2 entries** for the long tail.

**Realistic milestone targets:**

* **v2.13 (Office + Diagrams + Dev)** -- `legacyoffice`, `applepro`, `hwpkit`, `diagram` (Mermaid / PlantUML / Graphviz / Visio / draw.io), `playlist`, `comic`, `notebooks`. ~7-8 P0 sidecars.
* **v2.14 (Sysadmin + Crypto + Config)** -- `tlskit`, `sshkit`, `gpgkit`, `dnskit`, `config` (HCL / HOCON), `wallet` (read-only). ~6 P0 sidecars.
* **v2.15 (Streaming + Video Niche + Manifests)** -- `videopro` (DVD / AVCHD / elementary), `streaming` (DASH / HLS / CMAF), `imageseq` (DPX / EXR sequence), `chiptune` (NSF / SPC / VGM), `audiomore` (AIFF / CAF / TrueHD / DTS-MA). ~5 P0 sidecars.
* **v2.16 (Healthcare + Finance + Engineering)** -- `hl7` (v2 / FHIR), `finance` (OFX / QFX / QIF), `cadmore` (3MF / AMF / G-code), `medkit` extend (DICOM-RT). ~5 P0 sidecars.
* **v2.17 (Geospatial + Genome + Time/Coord utils)** -- `gistiles` (MBTiles / PMTiles / COG / KMZ), `timefmt`, `coordfmt`, `genome` (BCF), `wells` (LAS log). ~5 P0 sidecars.
* **v2.18 (Data wire formats)** -- `datakit` extend (CBOR / MessagePack / Protobuf / Thrift / Cap'n Proto / FlatBuffers), `dbsql` (sqlglot dialect translation). ~3 P0 sidecars.
* **v2.19 (Email / Messaging long tail)** -- `emailpro` (.msg / Notes / Live Mail), `messaging` (WhatsApp / Telegram / iMessage / Discord / Slack). ~2-3 P0 sidecars.
* **v2.20 (Niche raster + game asset cleanup)** -- `imgmore`, `gameasset`, residual P1 / P2 items.

After v2.20 we will have shipped roughly **150 sidecars covering 1,500+ file extensions** -- the most extensive raw-conversion surface available in any single OSS desktop app.

---

# Universal Principles for Every New Sidecar

Every entry above must, before it is "done," satisfy:

1. NDJSON contract (`progress` / `log` / `complete` / `error` + at least one
   domain-specific event in `KNOWN_EVENTS`).
2. Frozen-PyInstaller guard for any sidecar that calls `pip install`.
3. Standard `--input` / `--output` / `--output-dir` argument shape.
4. At least one preset XML so it surfaces in the right-click menu and the
   unified PresetsPage browser.
5. A Toolbox tile via the `presets:engine` route convention.
6. A `build.ps1` from the standard PyInstaller template.
7. A `requirements.txt` (even if just a comment) so the build is reproducible.
8. Contract test (`tests/sidecar_contract/check_contract.py`) green.

---

# Out of Scope for the Roadmap (Different Initiatives)

These are *not* format conversions and live elsewhere:

* AI model upgrades (handled by separate "Latest & Greatest" passes).
* Watch-folder rule enrichment, REST API expansion, history dashboard
  features, accessibility passes, installer / MSI work.
* Cloud sync, account / login, telemetry. (UCX is offline-first by charter.)
* DRM-bound formats (KFX, AAX, FairPlay, etc.) -- legal grey area, intentionally skipped.
