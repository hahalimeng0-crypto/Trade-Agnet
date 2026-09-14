"""Build deterministic, de-identified PDF fixtures in temporary test directories."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

PAGE_WIDTH = 612
PAGE_HEIGHT = 792


def _ascii_font() -> DictionaryObject:
    return DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })


def _unicode_font() -> DictionaryObject:
    descriptor = DictionaryObject({
        NameObject("/Type"): NameObject("/FontDescriptor"),
        NameObject("/FontName"): NameObject("/STSong-Light"),
        NameObject("/Flags"): NumberObject(4),
        NameObject("/FontBBox"): ArrayObject([
            NumberObject(0), NumberObject(-250), NumberObject(1000), NumberObject(880)
        ]),
        NameObject("/ItalicAngle"): NumberObject(0),
        NameObject("/Ascent"): NumberObject(752),
        NameObject("/Descent"): NumberObject(-271),
        NameObject("/CapHeight"): NumberObject(737),
        NameObject("/StemV"): NumberObject(58),
    })
    descendant = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/CIDFontType0"),
        NameObject("/BaseFont"): NameObject("/STSong-Light"),
        NameObject("/CIDSystemInfo"): DictionaryObject({
            NameObject("/Registry"): TextStringObject("Adobe"),
            NameObject("/Ordering"): TextStringObject("GB1"),
            NameObject("/Supplement"): NumberObject(4),
        }),
        NameObject("/FontDescriptor"): descriptor,
    })
    return DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type0"),
        NameObject("/BaseFont"): NameObject("/STSong-Light"),
        NameObject("/Encoding"): NameObject("/UniGB-UCS2-H"),
        NameObject("/DescendantFonts"): ArrayObject([descendant]),
    })


def _pdf_text(value: str, unicode_font: bool) -> str:
    if unicode_font:
        return f"<{value.encode('utf-16-be').hex().upper()}>"
    escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"({escaped})"


def _add_text_page(writer: PdfWriter, lines: list[str], *, columns: tuple[list[str], list[str]] | None = None) -> None:
    page = writer.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    all_lines = list(lines)
    if columns:
        all_lines.extend(columns[0]); all_lines.extend(columns[1])
    use_unicode = any(not line.isascii() for line in all_lines)
    font = _unicode_font() if use_unicode else _ascii_font()
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
    })
    operations: list[str] = []

    def place(values: list[str], x: int, y: int) -> None:
        for offset, value in enumerate(values):
            operations.append(
                f"BT /F1 12 Tf {x} {y - offset * 20} Td {_pdf_text(value, use_unicode)} Tj ET"
            )

    if columns:
        place(columns[0], 54, 720)
        place(columns[1], 324, 720)
    else:
        place(lines, 72, 720)
    stream = DecodedStreamObject()
    stream.set_data("\n".join(operations).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)


def _add_scanned_page(writer: PdfWriter) -> None:
    page = writer.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    stream = DecodedStreamObject()
    stream.set_data(b"q 0.88 g 60 180 492 430 re f Q")
    page[NameObject("/Contents")] = writer._add_object(stream)


def _serialize(writer: PdfWriter) -> bytes:
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def build_fixture(case: dict) -> bytes:
    build = case["build"]
    kind = build["kind"]
    if kind == "malformed":
        return b"%PDF-1.7\n1 0 obj\n<<truncated"

    writer = PdfWriter()
    if kind == "text":
        for lines in build["pages"]:
            _add_text_page(writer, list(lines))
    elif kind == "two_column":
        _add_text_page(writer, [], columns=(list(build["left"]), list(build["right"])))
    elif kind == "repeated":
        for page_number in range(1, int(build["page_count"]) + 1):
            _add_text_page(writer, [build["header"], f"{build['body_prefix']} {page_number}", build["footer"]])
    elif kind == "scanned":
        for _ in range(int(build["page_count"])):
            _add_scanned_page(writer)
    elif kind == "mixed":
        for page_number in range(1, int(build["page_count"]) + 1):
            if page_number % 2:
                _add_text_page(writer, [f"Extractable page {page_number}", "Controlled mixed PDF fixture with sufficient searchable trade guidance text."])
            else:
                _add_scanned_page(writer)
    elif kind == "encrypted":
        for _ in range(int(build["page_count"])):
            _add_text_page(writer, ["Encrypted synthetic fixture"])
        writer.encrypt(str(build["password"]))
    elif kind == "blank":
        for _ in range(int(build["page_count"])):
            writer.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    elif kind == "oversized":
        _add_text_page(writer, ["Oversized synthetic fixture"])
        payload = _serialize(writer)
        return payload + (b"\x00" * (int(build["size_bytes"]) - len(payload)))
    else:
        raise ValueError(f"unsupported fixture kind: {kind}")
    return _serialize(writer)
