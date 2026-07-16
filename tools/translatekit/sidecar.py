"""Local-only neural translation sidecar.

Two SOTA OSS translation models, all offline:

  * NLLB-200          (Meta CC-BY-NC, 200 languages, 600 M / 1.3 B / 3.3 B)
  * MADLAD-400        (Google Apache-2.0, 419 languages, 3 B / 7 B / 10 B)
  * NLLB-200 distilled (faster, smaller, slightly lower quality)
  * Helsinki OPUS-MT  (lightweight per-language-pair models)

Default model = `facebook/nllb-200-distilled-600M` because it's small enough
to run on CPU, supports 200 languages, and is permissive enough for end-user
use.

Operations:
  text   Translate stdin or a string with --text
  file   Translate a UTF-8 text file (preserves blank lines)
  srt    Translate an SRT subtitle file (timecode-preserving)
  langs  List supported language tags
"""
from __future__ import annotations

import argparse
import json
import os
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import re
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Common NLLB-200 BCP-47 -> NLLB language code mapping (subset).
# Full list: https://github.com/facebookresearch/flores/blob/main/flores200/README.md
NLLB_LANGS = {
    "en": "eng_Latn", "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn",
    "it": "ita_Latn", "pt": "por_Latn", "nl": "nld_Latn", "ru": "rus_Cyrl",
    "uk": "ukr_Cyrl", "pl": "pol_Latn", "tr": "tur_Latn", "ar": "arb_Arab",
    "he": "heb_Hebr", "fa": "pes_Arab", "hi": "hin_Deva", "bn": "ben_Beng",
    "zh": "zho_Hans", "zh-tw": "zho_Hant", "ja": "jpn_Jpan", "ko": "kor_Hang",
    "th": "tha_Thai", "vi": "vie_Latn", "id": "ind_Latn", "ms": "zsm_Latn",
    "tl": "tgl_Latn", "sw": "swh_Latn", "cs": "ces_Latn", "sk": "slk_Latn",
    "ro": "ron_Latn", "hu": "hun_Latn", "el": "ell_Grek", "fi": "fin_Latn",
    "sv": "swe_Latn", "da": "dan_Latn", "no": "nob_Latn", "is": "isl_Latn",
    "et": "est_Latn", "lt": "lit_Latn", "lv": "lvs_Latn", "ca": "cat_Latn",
    "ga": "gle_Latn", "cy": "cym_Latn", "eu": "eus_Latn", "gl": "glg_Latn",
    "az": "azj_Latn", "ka": "kat_Geor", "hy": "hye_Armn",
    "sr": "srp_Cyrl", "hr": "hrv_Latn", "bs": "bos_Latn", "sl": "slv_Latn",
    "mk": "mkd_Cyrl", "bg": "bul_Cyrl",
    "kk": "kaz_Cyrl", "ky": "kir_Cyrl", "uz": "uzn_Latn",
    "ne": "npi_Deva", "ur": "urd_Arab", "pa": "pan_Guru", "ta": "tam_Taml",
    "te": "tel_Telu", "ml": "mal_Mlym", "kn": "kan_Knda", "gu": "guj_Gujr",
    "mr": "mar_Deva", "si": "sin_Sinh", "my": "mya_Mymr", "km": "khm_Khmr",
    "lo": "lao_Laoo", "am": "amh_Ethi",
}


def _resolve_nllb(code: str) -> str:
    code = code.lower()
    if code in NLLB_LANGS: return NLLB_LANGS[code]
    # If user already passed a flores code (like eng_Latn), accept verbatim.
    if "_" in code and len(code) <= 12: return code
    raise ValueError(f"Unknown language '{code}'. Try one of: {sorted(NLLB_LANGS.keys())[:24]} ...")


def _load_nllb(model_id: str, src: str, tgt: str, device: str):
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_id, src_lang=src)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_id).to(device)

    def translate(text: str) -> str:
        inputs = tokenizer(text, return_tensors="pt", truncation=True,
                           max_length=512).to(device)
        out = model.generate(**inputs,
                             forced_bos_token_id=tokenizer.convert_tokens_to_ids(tgt),
                             max_new_tokens=512, num_beams=4)
        return tokenizer.batch_decode(out, skip_special_tokens=True)[0]
    return translate


def _load_madlad(model_id: str, tgt: str, device: str):
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_id).to(device)

    def translate(text: str) -> str:
        # MADLAD takes a "<2xx> sentence" prefix.
        prompt = f"<2{tgt}> {text}"
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True,
                           max_length=512).to(device)
        out = model.generate(**inputs, max_new_tokens=512, num_beams=4)
        return tokenizer.batch_decode(out, skip_special_tokens=True)[0]
    return translate


def helsinki_model_id(source: str, target: str) -> str:
    """Return the deterministic OPUS-MT pair used by Subtitle Studio."""
    source = source.strip().lower()
    target = target.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", source):
        raise ValueError(f"Invalid OPUS-MT source language: {source!r}")
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", target):
        raise ValueError(f"Invalid OPUS-MT target language: {target!r}")
    if source == target:
        raise ValueError("Source and target languages must differ.")
    model_codes = {"ja": "jap"}
    return (
        "Helsinki-NLP/opus-mt-"
        f"{model_codes.get(source, source)}-{model_codes.get(target, target)}"
    )


def _load_helsinki_onnx(model_id: str, device: str):
    """Load a Marian OPUS-MT pair through ONNX Runtime, exporting once when
    the upstream model does not already publish ONNX weights. The exported
    graph is cached by Optimum in the normal Hugging Face model cache."""
    import onnxruntime as ort
    from optimum.onnxruntime import ORTModelForSeq2SeqLM
    from transformers import AutoTokenizer

    providers = ort.get_available_providers()
    wants_cuda = device.lower().startswith("cuda")
    provider = (
        "CUDAExecutionProvider"
        if wants_cuda and "CUDAExecutionProvider" in providers
        else "CPUExecutionProvider"
    )
    if wants_cuda and provider == "CPUExecutionProvider":
        emit("log", level="warn",
             message="ONNX Runtime CUDA provider is unavailable; OPUS-MT is using CPU.")

    cache_root = Path(os.environ.get("UCX_MODEL_DIR") or Path.home() / ".cache" / "ucx-models")
    cache_dir = cache_root / "translatekit" / model_id.replace("/", "--")
    cached = (cache_dir / "config.json").is_file() and any(cache_dir.glob("*.onnx"))
    tokenizer = AutoTokenizer.from_pretrained(cache_dir if cached else model_id)
    if cached:
        model = ORTModelForSeq2SeqLM.from_pretrained(cache_dir, provider=provider)
    else:
        emit("log", level="info",
             message=f"Exporting {model_id} to ONNX (one-time model cache setup).")
        model = ORTModelForSeq2SeqLM.from_pretrained(
            model_id, export=True, provider=provider)
        cache_dir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(cache_dir)
        tokenizer.save_pretrained(cache_dir)

    def translate(text: str) -> str:
        inputs = tokenizer(text, return_tensors="pt", truncation=True,
                           max_length=512)
        out = model.generate(**inputs, max_new_tokens=512, num_beams=4)
        return tokenizer.batch_decode(out, skip_special_tokens=True)[0]
    return translate


def _build_translator(args):
    model_id = args.model
    if model_id.lower() in {"helsinki", "opus-mt", "helsinki-opus-mt"}:
        model_id = helsinki_model_id(args.source, args.target)
    if model_id.lower().startswith("helsinki-nlp/opus-mt-"):
        return _load_helsinki_onnx(model_id, args.device)
    if "madlad" in model_id.lower():
        return _load_madlad(model_id, args.target, args.device)
    src = _resolve_nllb(args.source)
    tgt = _resolve_nllb(args.target)
    return _load_nllb(model_id, src, tgt, args.device)


def op_text(args: argparse.Namespace) -> int:
    try:
        import torch  # noqa: F401
    except ImportError as ex:
        return fail("missing_dep", f"torch / transformers missing: {ex}.")
    text = args.text or sys.stdin.read()
    if not text.strip(): return fail("empty_text", "Provide --text or stdin.")

    translate = _build_translator(args)
    out_dir = Path(args.output_dir).resolve() if args.output_dir else None
    if out_dir: out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    emit("progress", percent=0, stage="translate", eta_seconds=None)
    translated = translate(text)
    emit("progress", percent=100, stage="done",
         eta_seconds=int(time.monotonic() - started))

    if out_dir:
        out_path = out_dir / (args.name + ".txt")
        out_path.write_text(translated, encoding="utf-8")
        size = out_path.stat().st_size
        emit("translation",
             input=text[:80], output=str(out_path),
             size_bytes=size,
             source=args.source, target=args.target,
             model=args.model, char_count=len(translated))
        emit("complete", output=str(out_path), size_bytes=size, count=1)
    else:
        emit("translation",
             input=text[:80], output="(stdout)",
             text=translated,
             source=args.source, target=args.target,
             model=args.model, char_count=len(translated))
        emit("complete", output="(stdout)", size_bytes=0, count=1)
    return 0


def op_file(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Text file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    translate = _build_translator(args)
    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="translate", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8")
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")
        translated_lines: list[str] = []
        for line in text.splitlines():
            if line.strip():
                translated_lines.append(translate(line))
            else:
                translated_lines.append(line)
        out_path = out_dir / (src.stem + f".{args.target}{src.suffix}")
        out_path.write_text("\n".join(translated_lines), encoding="utf-8")
        emit("translation",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             source=args.source, target=args.target,
             model=args.model, char_count=len("\n".join(translated_lines)))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


_SRT_TC = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}.*$")


def op_srt(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"SRT file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    translate = _build_translator(args)
    total = len(inputs)

    for i, src in enumerate(inputs):
        text = src.read_text(encoding="utf-8")
        out_lines: list[str] = []
        cur_block: list[str] = []
        for line in text.splitlines():
            if line.strip().isdigit() or _SRT_TC.match(line) or line == "":
                if cur_block:
                    out_lines.append(translate(" ".join(cur_block)))
                    cur_block = []
                out_lines.append(line)
            else:
                cur_block.append(line)
        if cur_block: out_lines.append(translate(" ".join(cur_block)))
        out_path = out_dir / (src.stem + f".{args.target}.srt")
        out_path.write_text("\n".join(out_lines), encoding="utf-8")
        emit("translation",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             source=args.source, target=args.target,
             model=args.model, format="srt")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_langs(_args: argparse.Namespace) -> int:
    for code, flores in NLLB_LANGS.items():
        emit("translation_lang", code=code, flores=flores)
    emit("complete", output="", size_bytes=0, count=len(NLLB_LANGS))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="translatekit-sidecar",
                                description="Offline neural translation (OPUS-MT ONNX / NLLB-200 / MADLAD-400).")
    sub = p.add_subparsers(dest="op", required=True)

    def add_common(c):
        c.add_argument("--source", default="en")
        c.add_argument("--target", required=True,
                       help="Target language tag (en, es, fr, de, ja, zh, ar, ...)")
        c.add_argument("--model", default="facebook/nllb-200-distilled-600M",
                       help="Model id or 'opus-mt' for Helsinki OPUS-MT ONNX. "
                            "NLLB: facebook/nllb-200-distilled-600M | "
                            "facebook/nllb-200-distilled-1.3B | facebook/nllb-200-3.3B. "
                            "MADLAD: google/madlad400-3b-mt | google/madlad400-7b-mt-bt.")
        c.add_argument("--device", default="cuda")
        c.add_argument("--output-dir", default=None, dest="output_dir")
        c.add_argument("--name", default="translated")

    t = sub.add_parser("text", help="Translate stdin / --text.")
    t.add_argument("--text", default=None)
    add_common(t)

    f = sub.add_parser("file", help="Translate UTF-8 text files line-by-line.")
    f.add_argument("--input", nargs="+", required=True)
    f.add_argument("--output-dir", required=True, dest="output_dir")
    f.add_argument("--source", default="en")
    f.add_argument("--target", required=True)
    f.add_argument("--model", default="facebook/nllb-200-distilled-600M")
    f.add_argument("--device", default="cuda")

    s = sub.add_parser("srt", help="Translate SRT files (preserves timecodes).")
    s.add_argument("--input", nargs="+", required=True)
    s.add_argument("--output-dir", required=True, dest="output_dir")
    s.add_argument("--source", default="en")
    s.add_argument("--target", required=True)
    s.add_argument("--model", default="facebook/nllb-200-distilled-600M",
                   help="Model id or 'opus-mt' for Helsinki OPUS-MT ONNX.")
    s.add_argument("--device", default="cuda")

    sub.add_parser("langs", help="List supported language codes.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "text":  return op_text(args)
        if args.op == "file":  return op_file(args)
        if args.op == "srt":   return op_srt(args)
        if args.op == "langs": return op_langs(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
