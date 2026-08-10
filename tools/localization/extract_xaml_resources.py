"""Deterministically add x:Uid values and maintain WinUI RESW string catalogs.

Run from the repository root. The transformer preserves XAML formatting and
only inserts x:Uid attributes; literal user-facing properties remain as the
English fallback visible in source control.
"""
from __future__ import annotations

import html
import hashlib
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
UI_ROOT = REPO / "src" / "UniversalConverterX.UI"
STRINGS_ROOT = UI_ROOT / "Strings"
LOCALES = ("en-US", "de-DE", "fr-FR", "es-ES", "pl-PL", "zh-Hans")
CODE_RESOURCES = {
    "ConverterPage_QueueSortEstimateButton.Content": "Est. output",
    "Core_ConversionCancelled": "Conversion was cancelled",
    "Core_ConverterExecutableNotFound": "Converter executable was not found: {0}",
    "Core_ConversionTimedOut": "Conversion timed out after {0}.",
    "Core_EmptyOutputFile": "The converter created an empty output file: {0}",
    "Core_ExpectedOutputMissing": "The converter completed but did not create the expected output file: {0}",
    "Core_ForcedConverterCannotConvert": "Forced converter '{0}' cannot convert {1} → {2}.",
    "Core_ForcedConverterNotRegistered": "Forced converter '{0}' is not registered. Available: {1}",
    "Core_InputPathRequired": "Input path is required.",
    "Core_NoConverterAvailable": "No converter is available for {0} → {1}.",
    "Core_OutputExistsSkip": "Output already exists at '{0}' and the overwrite policy is Skip.",
    "Core_OutputPathRequired": "Output path is required.",
    "Core_PostActionFailed": "Conversion succeeded, but the post-conversion source action failed: {0}",
    "Core_StartingConversion": "Starting conversion...",
    "Core_UnknownError": "Unknown error",
    "MainWindow_Item_001.Title": "UniversalConverter X",
    "SettingsWindow_Item_001.Title": "Settings - UniversalConverter X",
}
LOCALIZABLE_PROPERTIES = {
    "Text": "Text",
    "Content": "Content",
    "Header": "Header",
    "PlaceholderText": "PlaceholderText",
    "OffContent": "OffContent",
    "OnContent": "OnContent",
    "Title": "Title",
    "AutomationProperties.Name": "[using:Microsoft.UI.Xaml.Automation]AutomationProperties.Name",
    "AutomationProperties.HelpText": "[using:Microsoft.UI.Xaml.Automation]AutomationProperties.HelpText",
    "ToolTipService.ToolTip": "[using:Microsoft.UI.Xaml.Controls]ToolTipService.ToolTip",
}
ATTRIBUTE_RE = re.compile(r'([A-Za-z_][\w:.-]*)\s*=\s*"([^"]*)"', re.DOTALL)
RESW_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def iter_start_tags(text: str):
    """Yield (start, end, tag text) while respecting > inside quoted values."""
    index = 0
    while True:
        start = text.find("<", index)
        if start < 0:
            return
        if start + 1 >= len(text) or text[start + 1] in "/!?":
            index = start + 1
            continue
        quote = None
        cursor = start + 1
        while cursor < len(text):
            character = text[cursor]
            if quote:
                if character == quote:
                    quote = None
            elif character in "\"'":
                quote = character
            elif character == ">":
                yield start, cursor + 1, text[start:cursor + 1]
                index = cursor + 1
                break
            cursor += 1
        else:
            return


def attributes(tag: str) -> dict[str, str]:
    return {match.group(1): match.group(2) for match in ATTRIBUTE_RE.finditer(tag)}


def is_localizable(raw_value: str) -> bool:
    value = raw_value.strip()
    if not value or value.startswith("{"):
        return False
    if re.fullmatch(r"&#x[0-9A-Fa-f]+;?", value):
        return False
    return True


def sanitize(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = "Item_" + cleaned
    return cleaned


def file_prefix(path: Path) -> str:
    relative = path.relative_to(UI_ROOT).with_suffix("")
    parts = [part for part in relative.parts if part not in {"Views", "Pages"}]
    return sanitize("_".join(parts))


def load_resw(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    root = ET.parse(path).getroot()
    return {
        node.attrib["name"]: node.findtext("value") or ""
        for node in root.findall("data")
        if node.get("name")
    }


def csharp_files() -> list[Path]:
    return sorted(
        path for path in (UI_ROOT / "").rglob("*.cs")
        if not any(part in {"bin", "obj"} for part in path.parts)
    )


def parse_csharp_string(text: str, index: int):
    """Return (end, token, interpolated) for a C# string at index."""
    start = index
    if text.startswith('$@"', index) or text.startswith('@$"', index):
        quote = index + 2
        interpolated = True
        verbatim = True
    elif text.startswith('$"', index):
        quote = index + 1
        interpolated = True
        verbatim = False
    elif text.startswith('@"', index):
        quote = index + 1
        interpolated = False
        verbatim = True
    elif text.startswith('"', index):
        quote = index
        interpolated = False
        verbatim = False
    else:
        return None

    cursor = quote + 1
    brace_depth = 0
    while cursor < len(text):
        character = text[cursor]
        if verbatim:
            if character == '"':
                if cursor + 1 < len(text) and text[cursor + 1] == '"':
                    cursor += 2
                    continue
                if brace_depth == 0:
                    return cursor + 1, text[start:cursor + 1], interpolated
        else:
            if character == '\\':
                cursor += 2
                continue
            if interpolated and character == '{' and not text.startswith('{{', cursor):
                brace_depth += 1
            elif interpolated and character == '}' and brace_depth > 0 and not text.startswith('}}', cursor):
                brace_depth -= 1
            elif character == '"' and brace_depth == 0:
                return cursor + 1, text[start:cursor + 1], interpolated
        cursor += 1
    return None


def decode_csharp_string(token: str) -> str:
    if token.startswith('$@') or token.startswith('@'):
        body = token[token.index('"') + 1:-1]
        return body.replace('""', '"')
    body = token[token.index('"') + 1:-1]
    escapes = {
        '\\n': '\n', '\\r': '\r', '\\t': '\t', '\\b': '\b',
        '\\f': '\f', '\\v': '\v', '\\\\': '\\', '\\"': '"',
    }
    for source, value in escapes.items():
        body = body.replace(source, value)
    body = re.sub(
        r"\\u([0-9A-Fa-f]{4})",
        lambda match: chr(int(match.group(1), 16)),
        body,
    )
    return body


def interpolation_format(body: str) -> str:
    """Replace C# interpolation holes with positional format placeholders."""
    output: list[str] = []
    cursor = 0
    argument = 0
    while cursor < len(body):
        if body.startswith('{{', cursor) or body.startswith('}}', cursor):
            output.append(body[cursor:cursor + 2])
            cursor += 2
            continue
        if body[cursor] != '{':
            output.append(body[cursor])
            cursor += 1
            continue

        end = cursor + 1
        depth = 1
        while end < len(body) and depth:
            if body[end] == '{':
                depth += 1
            elif body[end] == '}':
                depth -= 1
            end += 1
        if depth:
            return body

        expression = body[cursor + 1:end - 1].strip()
        suffix = ""
        for marker in (',', ':'):
            position = expression.find(marker)
            if position >= 0:
                suffix = expression[position:]
                break
        output.append(f"{{{argument}{suffix}}}")
        argument += 1
        cursor = end
    return "".join(output)


def code_resource_key(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest().upper()
    return f"Code_{digest[:20]}"


def discover_code_resources() -> dict[str, str]:
    discovered: dict[str, str] = {}
    call_pattern = re.compile(r"\bAppLocalizer\.(Get|Format)\s*\(")
    for path in csharp_files():
        text = path.read_text(encoding="utf-8-sig")
        for match in call_pattern.finditer(text):
            cursor = match.end()
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            parsed = parse_csharp_string(text, cursor)
            if not parsed:
                continue
            end, token, interpolated = parsed
            value = decode_csharp_string(token)
            if match.group(1) == "Format" and interpolated:
                value = interpolation_format(value)
            elif match.group(1) == "Get" and interpolated:
                # Interpolated Get is not a supported resource call; it is
                # still safer to omit it than to create a value with embedded
                # runtime data.
                continue
            if not value:
                continue

            # Two-argument calls retain their semantic key. The code-resource
            # hash is used only by the concise one-argument overloads.
            after = text[end:]
            if match.group(1) == "Get" and re.match(r"\s*,", after):
                continue
            key = code_resource_key(value)
            previous = discovered.get(key)
            if previous is not None and previous != value:
                raise ValueError(f"Resource {key} has conflicting values")
            discovered[key] = value
    return discovered


def write_resw(path: Path, values: dict[str, str]) -> None:
    root = ET.Element("root")
    headers = (
        ("resmimetype", "text/microsoft-resx"),
        ("version", "2.0"),
        ("reader", "System.Resources.ResXResourceReader, System.Windows.Forms"),
        ("writer", "System.Resources.ResXResourceWriter, System.Windows.Forms"),
    )
    for name, value in headers:
        header = ET.SubElement(root, "resheader", {"name": name})
        ET.SubElement(header, "value").text = value
    for name in sorted(values, key=str.casefold):
        data = ET.SubElement(root, "data", {"name": name, RESW_XML_SPACE: "preserve"})
        ET.SubElement(data, "value").text = values[name]
    ET.indent(root, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write through a binary stream so Windows does not translate ElementTree's
    # LF separators into CRLF and turn every resource line into a noisy diff.
    with path.open("wb") as stream:
        ET.ElementTree(root).write(stream, encoding="utf-8", xml_declaration=True)
        stream.write(b"\n")


def xaml_files() -> list[Path]:
    return sorted(
        path for path in UI_ROOT.rglob("*.xaml")
        if not any(part in {"bin", "obj"} for part in path.parts)
    )


def transform() -> tuple[int, int]:
    english_path = STRINGS_ROOT / "en-US" / "Resources.resw"
    english = load_resw(english_path)
    discovered: dict[str, str] = {}
    seen_uids: set[str] = set()
    modified_files = 0

    # Existing UIDs are globally addressed from one Resources map.
    for path in xaml_files():
        text = path.read_text(encoding="utf-8-sig")
        for _, _, tag in iter_start_tags(text):
            uid = attributes(tag).get("x:Uid")
            if not uid:
                continue
            if uid in seen_uids:
                raise ValueError(f"Duplicate x:Uid {uid!r} (seen again in {path})")
            seen_uids.add(uid)

    for path in xaml_files():
        text = path.read_text(encoding="utf-8-sig")
        replacements: list[tuple[int, int, str]] = []
        prefix = file_prefix(path)
        sequence = 0
        for start, end, tag in iter_start_tags(text):
            attrs = attributes(tag)
            localizable = [
                (prop, value)
                for prop, value in attrs.items()
                if prop in LOCALIZABLE_PROPERTIES and is_localizable(value)
            ]
            if not localizable:
                continue

            uid = attrs.get("x:Uid")
            replacement = tag
            if not uid:
                sequence += 1
                identity = attrs.get("x:Name") or attrs.get("AutomationProperties.AutomationId")
                base = f"{prefix}_{sanitize(identity)}" if identity else f"{prefix}_Item_{sequence:03d}"
                uid = base
                suffix = 2
                while uid in seen_uids:
                    uid = f"{base}_{suffix}"
                    suffix += 1
                seen_uids.add(uid)
                name_match = re.match(r"<([A-Za-z_][\w:.-]*)", tag)
                if not name_match:
                    raise ValueError(f"Could not parse XAML tag in {path}: {tag[:80]}")
                insertion = name_match.end()
                replacement = tag[:insertion] + f' x:Uid="{uid}"' + tag[insertion:]
                replacements.append((start, end, replacement))

            for prop, raw_value in localizable:
                resource_prop = LOCALIZABLE_PROPERTIES[prop]
                key = f"{uid}.{resource_prop}"
                value = html.unescape(raw_value)
                previous = discovered.get(key)
                if previous is not None and previous != value:
                    raise ValueError(f"Resource {key} has conflicting values: {previous!r} / {value!r}")
                discovered[key] = value

        if replacements:
            for start, end, replacement in reversed(replacements):
                text = text[:start] + replacement + text[end:]
            path.write_text(text, encoding="utf-8", newline="\n")
            modified_files += 1

    # Keep explicitly maintained code-behind/Core keys while refreshing XAML keys.
    xaml_prefixes = tuple(f"{file_prefix(path)}_" for path in xaml_files())
    english = {
        key: value for key, value in english.items()
        if not key.startswith(xaml_prefixes)
    }
    english.update(discovered)
    english.update(CODE_RESOURCES)
    english.update(discover_code_resources())
    write_resw(english_path, english)

    for locale in LOCALES[1:]:
        locale_path = STRINGS_ROOT / locale / "Resources.resw"
        localized = load_resw(locale_path)
        localized = {key: localized.get(key, value) for key, value in english.items()}
        write_resw(locale_path, localized)

    return modified_files, len(discovered)


def main() -> int:
    modified, resources = transform()
    print(f"Localized {resources} XAML properties across {modified} modified file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
