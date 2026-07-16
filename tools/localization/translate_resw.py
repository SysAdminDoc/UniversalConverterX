"""Populate priority RESW locales with local Marian/OPUS-MT translations.

This is a maintainer tool, not a runtime dependency. It deduplicates English
values, protects format placeholders and product terminology, and keeps a
JSON cache outside the repository so interrupted generation can resume.
"""
from __future__ import annotations

import argparse
import gc
import json
import re
import sys
from pathlib import Path

import torch
from transformers import MarianMTModel, MarianTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_xaml_resources import STRINGS_ROOT, load_resw, write_resw


MODELS = {
    "de-DE": "Helsinki-NLP/opus-mt-en-de",
    "fr-FR": "Helsinki-NLP/opus-mt-en-fr",
    "es-ES": "Helsinki-NLP/opus-mt-en-es",
    "pl-PL": "Helsinki-NLP/opus-mt-en-zlw",
    "zh-Hans": "Helsinki-NLP/opus-mt-en-zh",
}
TARGET_PREFIXES = {"pl-PL": ">>pol<< "}
OVERRIDES = {
    "de-DE": {
        "Progress": "Fortschritt", "Output": "Ausgabe", "Cancel": "Abbrechen",
        "Finished": "Abgeschlossen", "Browse": "Durchsuchen", "Settings": "Einstellungen",
        "General": "Allgemein", "Queue": "Warteschlange", "Display language": "Anzeigesprache",
        "No GIFs rendered yet": "Noch keine GIFs gerendert",
        "Conversion was cancelled": "Konvertierung wurde abgebrochen",
        "Converter executable was not found: {0}": "Konverterprogramm wurde nicht gefunden: {0}",
        "Conversion timed out after {0}.": "Zeitlimit der Konvertierung nach {0} überschritten.",
        "The converter created an empty output file: {0}": "Der Konverter hat eine leere Ausgabedatei erstellt: {0}",
        "The converter completed but did not create the expected output file: {0}": "Der Konverter wurde beendet, hat aber die erwartete Ausgabedatei nicht erstellt: {0}",
        "Forced converter '{0}' cannot convert {1} → {2}.": "Der erzwungene Konverter '{0}' kann {1} nicht in {2} konvertieren.",
        "Forced converter '{0}' is not registered. Available: {1}": "Der erzwungene Konverter '{0}' ist nicht registriert. Verfügbar: {1}",
        "Input path is required.": "Ein Eingabepfad ist erforderlich.",
        "No converter is available for {0} → {1}.": "Für {0} → {1} ist kein Konverter verfügbar.",
        "Output already exists at '{0}' and the overwrite policy is Skip.": "Die Ausgabe unter '{0}' ist bereits vorhanden und die Überschreibungsrichtlinie lautet Überspringen.",
        "Output path is required.": "Ein Ausgabepfad ist erforderlich.",
        "Conversion succeeded, but the post-conversion source action failed: {0}": "Die Konvertierung war erfolgreich, aber die anschließende Quellaktion ist fehlgeschlagen: {0}",
        "Starting conversion...": "Konvertierung wird gestartet...", "Unknown error": "Unbekannter Fehler",
    },
    "fr-FR": {
        "Progress": "Progression", "Output": "Sortie", "Cancel": "Annuler",
        "Finished": "Terminé", "Browse": "Parcourir", "Settings": "Paramètres",
        "General": "Général", "Queue": "File d’attente", "Display language": "Langue d’affichage",
        "No GIFs rendered yet": "Aucun GIF rendu",
        "Conversion was cancelled": "La conversion a été annulée",
        "Converter executable was not found: {0}": "L’exécutable du convertisseur est introuvable : {0}",
        "Conversion timed out after {0}.": "La conversion a dépassé le délai de {0}.",
        "The converter created an empty output file: {0}": "Le convertisseur a créé un fichier de sortie vide : {0}",
        "The converter completed but did not create the expected output file: {0}": "Le convertisseur s’est terminé sans créer le fichier de sortie attendu : {0}",
        "Forced converter '{0}' cannot convert {1} → {2}.": "Le convertisseur imposé '{0}' ne peut pas convertir {1} en {2}.",
        "Forced converter '{0}' is not registered. Available: {1}": "Le convertisseur imposé '{0}' n’est pas enregistré. Disponibles : {1}",
        "Input path is required.": "Le chemin d’entrée est requis.",
        "No converter is available for {0} → {1}.": "Aucun convertisseur n’est disponible pour {0} → {1}.",
        "Output already exists at '{0}' and the overwrite policy is Skip.": "La sortie '{0}' existe déjà et la stratégie d’écrasement est Ignorer.",
        "Output path is required.": "Le chemin de sortie est requis.",
        "Conversion succeeded, but the post-conversion source action failed: {0}": "La conversion a réussi, mais l’action sur la source a échoué : {0}",
        "Starting conversion...": "Démarrage de la conversion...", "Unknown error": "Erreur inconnue",
    },
    "es-ES": {
        "Progress": "Progreso", "Output": "Salida", "Cancel": "Cancelar",
        "Finished": "Finalizado", "Browse": "Examinar", "Settings": "Configuración",
        "General": "General", "Queue": "Cola", "Display language": "Idioma de visualización",
        "No GIFs rendered yet": "Aún no se ha renderizado ningún GIF",
        "Conversion was cancelled": "La conversión se canceló",
        "Converter executable was not found: {0}": "No se encontró el ejecutable del conversor: {0}",
        "Conversion timed out after {0}.": "La conversión superó el tiempo límite de {0}.",
        "The converter created an empty output file: {0}": "El conversor creó un archivo de salida vacío: {0}",
        "The converter completed but did not create the expected output file: {0}": "El conversor terminó sin crear el archivo de salida esperado: {0}",
        "Forced converter '{0}' cannot convert {1} → {2}.": "El conversor forzado '{0}' no puede convertir {1} a {2}.",
        "Forced converter '{0}' is not registered. Available: {1}": "El conversor forzado '{0}' no está registrado. Disponibles: {1}",
        "Input path is required.": "Se requiere una ruta de entrada.",
        "No converter is available for {0} → {1}.": "No hay ningún conversor disponible para {0} → {1}.",
        "Output already exists at '{0}' and the overwrite policy is Skip.": "La salida '{0}' ya existe y la política de sobrescritura es Omitir.",
        "Output path is required.": "Se requiere una ruta de salida.",
        "Conversion succeeded, but the post-conversion source action failed: {0}": "La conversión finalizó correctamente, pero falló la acción posterior sobre el origen: {0}",
        "Starting conversion...": "Iniciando conversión...", "Unknown error": "Error desconocido",
    },
    "pl-PL": {
        "Progress": "Postęp", "Output": "Wyjście", "Cancel": "Anuluj",
        "Finished": "Zakończono", "Browse": "Przeglądaj", "Settings": "Ustawienia",
        "General": "Ogólne", "Queue": "Kolejka", "Display language": "Język wyświetlania",
        "No GIFs rendered yet": "Nie wyrenderowano jeszcze żadnych plików GIF",
        "Conversion was cancelled": "Konwersja została anulowana",
        "Converter executable was not found: {0}": "Nie znaleziono programu konwertującego: {0}",
        "Conversion timed out after {0}.": "Konwersja przekroczyła limit czasu {0}.",
        "The converter created an empty output file: {0}": "Konwerter utworzył pusty plik wyjściowy: {0}",
        "The converter completed but did not create the expected output file: {0}": "Konwerter zakończył pracę, ale nie utworzył oczekiwanego pliku wyjściowego: {0}",
        "Forced converter '{0}' cannot convert {1} → {2}.": "Wymuszony konwerter '{0}' nie może przekonwertować {1} na {2}.",
        "Forced converter '{0}' is not registered. Available: {1}": "Wymuszony konwerter '{0}' nie jest zarejestrowany. Dostępne: {1}",
        "Input path is required.": "Ścieżka wejściowa jest wymagana.",
        "No converter is available for {0} → {1}.": "Brak konwertera dla {0} → {1}.",
        "Output already exists at '{0}' and the overwrite policy is Skip.": "Plik wyjściowy '{0}' już istnieje, a zasada nadpisywania to Pomiń.",
        "Output path is required.": "Ścieżka wyjściowa jest wymagana.",
        "Conversion succeeded, but the post-conversion source action failed: {0}": "Konwersja powiodła się, ale działanie na pliku źródłowym zakończyło się błędem: {0}",
        "Starting conversion...": "Rozpoczynanie konwersji...", "Unknown error": "Nieznany błąd",
    },
    "zh-Hans": {
        "Progress": "进度", "Output": "输出", "Cancel": "取消",
        "Finished": "已完成", "Browse": "浏览", "Settings": "设置",
        "General": "常规", "Queue": "队列", "Display language": "显示语言",
        "No GIFs rendered yet": "尚未渲染 GIF",
        "Conversion was cancelled": "转换已取消",
        "Converter executable was not found: {0}": "找不到转换器可执行文件：{0}",
        "Conversion timed out after {0}.": "转换在 {0} 后超时。",
        "The converter created an empty output file: {0}": "转换器创建了空的输出文件：{0}",
        "The converter completed but did not create the expected output file: {0}": "转换器已完成，但未创建预期的输出文件：{0}",
        "Forced converter '{0}' cannot convert {1} → {2}.": "指定的转换器“{0}”无法将 {1} 转换为 {2}。",
        "Forced converter '{0}' is not registered. Available: {1}": "指定的转换器“{0}”未注册。可用转换器：{1}",
        "Input path is required.": "必须提供输入路径。",
        "No converter is available for {0} → {1}.": "没有可用于 {0} → {1} 的转换器。",
        "Output already exists at '{0}' and the overwrite policy is Skip.": "输出“{0}”已存在，覆盖策略为跳过。",
        "Output path is required.": "必须提供输出路径。",
        "Conversion succeeded, but the post-conversion source action failed: {0}": "转换成功，但转换后的源文件操作失败：{0}",
        "Starting conversion...": "正在开始转换...", "Unknown error": "未知错误",
    },
}
PROTECTED_TERMS = sorted({
    "UniversalConverter X", "UniversalConverterX", "FFmpeg", "FFprobe", "FFplay",
    "MKVToolNix", "PySceneDetect", "OpenTimelineIO", "CMX 3600", "SeedVR2",
    "Real-ESRGAN", "CodeFormer", "GFPGAN", "ClipForge", "VideoCrush", "StreamKeep",
    "AlphaCut", "ImageMagick", "LibreOffice", "Tesseract", "Whisper", "PyTorch",
    "ONNX Runtime", "ONNX", "CUDA", "Vulkan", "VMAF", "SSIMULACRA2", "DPAPI",
    "H.264", "H.265", "HEVC", "AV1", "VP9", "AAC", "Opus", "FLAC", "MP3",
    "MP4", "MKV", "MOV", "WebM", "JSON", "CSV", "XML", "EDL", "OTIO", "SRT",
    "VTT", "ASS", "SSA", "HDR", "HDR10+", "Dolby Vision", "PowerShell", "Windows",
    "WinUI", "GitHub", "YouTube", "Twitch", "Deno", "yt-dlp", "7-Zip", "Calibre",
}, key=len, reverse=True)
PLACEHOLDER_RE = re.compile(
    r"\{[^{}]+\}|%[A-Za-z0-9_]+%|(?i:--[a-z0-9][a-z0-9-]*|https?://\S+)|"
    r"(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9+.-]{1,}|[0-9]+D)s?\b")
ACRONYM_RE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9+.-]{1,}|[0-9]+D)s?\b")


def protect(text: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def replace(value: str) -> str:
        token = f"ZXQ{len(replacements)}QXZ"
        replacements[token] = value
        return token

    protected = PLACEHOLDER_RE.sub(lambda match: replace(match.group(0)), text)
    for term in PROTECTED_TERMS:
        protected = re.sub(re.escape(term), lambda match: replace(match.group(0)), protected)
    return protected, replacements


def restore(text: str, replacements: dict[str, str], fallback: str) -> str:
    restored = text
    for token, value in replacements.items():
        # Marian occasionally inserts spaces around an unknown all-caps token.
        pattern = r"\s*".join(re.escape(part) for part in re.findall(r"[A-Z]+|\d+", token))
        restored, count = re.subn(pattern, lambda _match, value=value: value, restored, flags=re.IGNORECASE)
        if count == 0:
            return fallback
    return restored.strip() or fallback


def should_translate(value: str) -> bool:
    if not re.search(r"[A-Za-z]", value):
        return False
    if re.fullmatch(r"[A-Z0-9+./_-]{1,16}", value):
        return False
    return True


def cache_is_valid(source: str, translated: str) -> bool:
    if not translated.strip() or "ZXQ" in translated or "QXZ" in translated:
        return False
    if len(translated) > max(180, len(source) * 5):
        return False
    compact = re.sub(r"[\s\W_]+", "", translated)
    for width in range(1, min(8, len(compact) // 3) + 1):
        if re.search(rf"(.{{{width}}})\1\1", compact):
            return False
    return all(token.rstrip("s") in translated for token in ACRONYM_RE.findall(source))


def translate_locale(locale: str, model_id: str, cache_dir: Path, batch_size: int) -> None:
    english = load_resw(STRINGS_ROOT / "en-US" / "Resources.resw")
    values = sorted(set(english.values()), key=lambda value: (len(value), value.casefold()))
    cache_path = cache_dir / f"{locale}.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    cache = {
        source: translated for source, translated in cache.items()
        if cache_is_valid(source, translated)
    }
    pending = [value for value in values if value not in cache and should_translate(value)]
    for value in values:
        if value not in cache and not should_translate(value):
            cache[value] = value

    if pending:
        print(f"{locale}: loading {model_id} for {len(pending)} unique string(s)", flush=True)
        tokenizer = MarianTokenizer.from_pretrained(model_id)
        model = MarianMTModel.from_pretrained(model_id).to("cuda" if torch.cuda.is_available() else "cpu")
        model.eval()
        device = next(model.parameters()).device
        for offset in range(0, len(pending), batch_size):
            source_batch = pending[offset:offset + batch_size]
            protected_batch = []
            replacement_maps = []
            for source in source_batch:
                protected, replacements = protect(source)
                protected_batch.append(TARGET_PREFIXES.get(locale, "") + protected)
                replacement_maps.append(replacements)
            encoded = tokenizer(
                protected_batch, return_tensors="pt", padding=True, truncation=True, max_length=256)
            encoded = {key: value.to(device) for key, value in encoded.items()}
            with torch.inference_mode():
                generated = model.generate(
                    **encoded, num_beams=4, max_new_tokens=256, early_stopping=True)
            translated = tokenizer.batch_decode(generated, skip_special_tokens=True)
            for source, output, replacements in zip(source_batch, translated, replacement_maps):
                candidate = restore(output, replacements, source)
                cache[source] = candidate if cache_is_valid(source, candidate) else source
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{locale}: {min(offset + batch_size, len(pending))}/{len(pending)}", flush=True)
        del model, tokenizer
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    overrides = OVERRIDES.get(locale, {})
    localized = {key: overrides.get(value, cache.get(value, value)) for key, value in english.items()}
    write_resw(STRINGS_ROOT / locale / "Resources.resw", localized)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--locale", choices=sorted(MODELS), action="append")
    parser.add_argument("--batch-size", type=int, default=24)
    args = parser.parse_args()
    selected = args.locale or list(MODELS)
    for locale in selected:
        translate_locale(locale, MODELS[locale], args.cache_dir, max(1, args.batch_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
