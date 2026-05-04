"""
PDF Filler v5 для декларации УСН (КНД 1152017).

Метод (зафиксирован НАМЕРТВО в правилах проекта): SUBSTITUTION + DRAW.
Заполнение ИСКЛЮЧИТЕЛЬНО ПОСИМВОЛЬНО — каждый символ value мапится к
конкретному cell в строке.

Алгоритм per cell:
  1. Substitute `<0010>` literal в content stream → `<0003>` (пробел).
     Это РЕАЛЬНО удаляет form's "-" из stream.
  2. Draw glyph через overlay stream поверх освобождённого места.

ЗАПРЕЩЕНО (rule #6 НАМЕРТВО): белые прямоугольники (mask). Mask нарушает
text-extraction и может перекрывать соседние символы.

Mapping format (explicit, v5):
  Каждый cell содержит span + stream_idx + tm_x + tm_y. Filler не делает
  runtime lookup — все позиции уже посчитаны при build_page_mapping.

Special: page 2 date row рендерится одним TJ литералом
`<0010001000110010001000110010001000100010>` (10 chars: "--.--.----").
Substitution всего литерала на width-0 CID (1) — литерал становится
невидимым, не сдвигая позиции. Затем draw полной "24.01.2026" поверх.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional

import pypdf
from pypdf.generic import ArrayObject, DecodedStreamObject, NameObject

# CTM constants
CTM_A = 0.7043478
CTM_E = 14.0
CTM_F = 827.91998
BASELINE_SHIFT = 1.79

# Page prolog
PROLOG_FULL = (
    "q\n"
    "0.24 0 0 -0.24 0 841.91998 cm\n"
    "2.9347825 0 0 2.9347825 58.333332 58.333332 cm\n"
)
PROLOG_INNER_ONLY = (
    "q\n"
    "2.9347825 0 0 2.9347825 58.333332 58.333332 cm\n"
)
EPILOG = "Q\n"

# Page 2 date literal substitution (CID 0001 width=0, не смещает positions)
DATE_LITERAL_OLD = b'<0010001000110010001000110010001000100010>'
DATE_LITERAL_NEW = b'<0001000100010001000100010001000100010001>'

# Kern compensation для substitution в TJ array
# CID 0010 (-) width = 333.0
# CID 0003 ( ) width = 277.832
# Difference = 55.168 — must be added как kern adjustment чтобы trailing chars не сдвинулись
# В TJ массиве: negative kern = move FORWARD (compensate width loss)
# Replacement bytes: <0003> (6) + ' -55.168 ' (9) = 15 bytes
SUBST_OLD_BYTES = b'<0010>'
SUBST_NEW_BYTES = b'<0003> -55.168 '  # width-preserving substitution для TJ array


@dataclass
class FontData:
    char_to_cid: dict[str, str]
    ttf_unicode_to_gid: dict[int, int]
    base_font: str
    font_name: str

    def char_to_cid_or_gid(self, char: str) -> Optional[str]:
        cid = self.char_to_cid.get(char)
        if cid is not None:
            return cid
        gid = self.ttf_unicode_to_gid.get(ord(char))
        if gid is None:
            return None
        return f'{gid:04X}'


def _parse_tounicode_cmap(cmap_data: str) -> dict[str, str]:
    import re
    out = {}
    for m in re.finditer(r'beginbfchar(.*?)endbfchar', cmap_data, re.DOTALL):
        for cm in re.finditer(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', m.group(1)):
            out[cm.group(1).upper().zfill(4)] = chr(int(cm.group(2), 16))
    for m in re.finditer(r'beginbfrange(.*?)endbfrange', cmap_data, re.DOTALL):
        body = m.group(1)
        for cm in re.finditer(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<([0-9A-Fa-f]+)>|\[([^\]]*)\])', body):
            s = int(cm.group(1), 16)
            e = int(cm.group(2), 16)
            if cm.group(4):
                u_start = int(cm.group(4), 16)
                for cid in range(s, e + 1):
                    out[f'{cid:04X}'] = chr(u_start + (cid - s))
            else:
                items = re.findall(r'<([0-9A-Fa-f]+)>', cm.group(5))
                for cid, u_hex in zip(range(s, e + 1), items):
                    out[f'{cid:04X}'] = chr(int(u_hex, 16))
    return out


def extract_font_data_obj(page, font_name: str) -> FontData:
    font_obj = page['/Resources']['/Font'][font_name].get_object()
    char_to_cid: dict[str, str] = {}
    tu = font_obj.get('/ToUnicode')
    if tu:
        cmap_data = tu.get_object().get_data().decode('latin-1', errors='replace')
        cid_to_char = _parse_tounicode_cmap(cmap_data)
        char_to_cid = {ch: cid for cid, ch in cid_to_char.items()}

    ttf_unicode_to_gid: dict[int, int] = {}
    df_arr = font_obj.get('/DescendantFonts')
    if df_arr:
        df = df_arr[0].get_object()
        desc = df.get('/FontDescriptor')
        if desc:
            ff = desc.get_object().get('/FontFile2')
            if ff:
                try:
                    from fontTools.ttLib import TTFont
                    ttf_bytes = ff.get_object().get_data()
                    ttf = TTFont(BytesIO(ttf_bytes))
                    cmap = ttf.getBestCmap()
                    glyph_order = ttf.getGlyphOrder()
                    gname_to_gid = {gn: gid for gid, gn in enumerate(glyph_order)}
                    ttf_unicode_to_gid = {
                        cp: gname_to_gid[gn]
                        for cp, gn in cmap.items() if gn in gname_to_gid
                    }
                except ImportError:
                    pass

    return FontData(
        char_to_cid=char_to_cid,
        ttf_unicode_to_gid=ttf_unicode_to_gid,
        base_font=str(font_obj.get('/BaseFont', '')),
        font_name=font_name,
    )


# ------------------------------------------------------------------------
# Mapping schema (v5 explicit format)
# ------------------------------------------------------------------------
@dataclass
class CellExplicit:
    x: float            # rl_x (для documentation)
    y: float            # rl_y
    tm_x: float         # ready для draw
    tm_y: float
    span: Optional[list]  # [start, end] in stream OR None (no <0010> at this position)
    stream_idx: Optional[int]

@dataclass
class FieldMapping:
    field: str
    cells: list[CellExplicit]
    alignment: str

@dataclass
class NarrowRow:
    field: str
    cells: list[CellExplicit]
    etalon_positions: list[dict]  # каждый имеет {text, x, y, tm_x, tm_y}
    format: str

@dataclass
class PageMapping:
    page: int
    font_name: str
    page_prolog_type: str
    narrow_rows: list[NarrowRow]
    fields: list[FieldMapping]


def _cell_from_dict(c: dict) -> CellExplicit:
    return CellExplicit(
        x=c['x'], y=c['y'],
        tm_x=c.get('tm_x', 0.0),
        tm_y=c.get('tm_y', 0.0),
        span=c.get('span'),
        stream_idx=c.get('stream_idx'),
    )


def load_mapping(path: Path) -> PageMapping:
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    fields = [
        FieldMapping(
            field=f['field'],
            cells=[_cell_from_dict(c) for c in f['cells']],
            alignment=f.get('alignment', 'left'),
        )
        for f in raw.get('fields', [])
    ]
    narrow_rows = [
        NarrowRow(
            field=nr['field'],
            cells=[_cell_from_dict(c) for c in nr['cells']],
            etalon_positions=nr['etalon_positions'],
            format=nr.get('format', ''),
        )
        for nr in raw.get('narrow_rows', [])
    ]
    return PageMapping(
        page=raw['page'],
        font_name=raw['font_name'],
        page_prolog_type=raw.get('page_prolog_type', 'full'),
        narrow_rows=narrow_rows,
        fields=fields,
    )


# ------------------------------------------------------------------------
# PDFFiller v5 — substitution + draw, explicit mapping
# ------------------------------------------------------------------------
class PDFFiller:
    """Заполнитель декларации УСН на blank24-25.pdf через substitution + draw."""

    FONT_SIZE = 12

    def __init__(self, blank_path: Path, mappings: dict[int, PageMapping]):
        self.blank_path = Path(blank_path)
        self.mappings = mappings

    def fill(self, data: dict[int, dict[str, str]], output_path: Path) -> dict:
        reader = pypdf.PdfReader(str(self.blank_path))
        writer = pypdf.PdfWriter(clone_from=reader)

        stats = {
            'pages_filled': [],
            'fields_filled': 0,
            'fields_skipped': [],
            'missing_chars': [],
        }

        for page_num in sorted(data.keys()):
            if page_num not in self.mappings:
                stats['fields_skipped'].extend((page_num, k) for k in data[page_num])
                continue

            page = writer.pages[page_num - 1]
            mapping = self.mappings[page_num]
            page_data = data[page_num]
            font = extract_font_data_obj(reader.pages[page_num - 1], mapping.font_name)

            page_stats = self._fill_page(page, mapping, page_data, font, writer)
            stats['pages_filled'].append(page_num)
            stats['fields_filled'] += page_stats['fields_filled']
            stats['missing_chars'].extend(page_stats['missing_chars'])

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'wb') as f:
            writer.write(f)

        stats['output_path'] = str(output_path)
        return stats

    def _substitute_with_kern_compensation(self, raw: bytes, s: int, e: int, new_bytes: bytes) -> bytes:
        """Substitute <0010> → <0003> с TJ kern compensation.

        Width(<0010>) = 333, Width(<0003>) = 277.832. Diff = 55.168 em-units.
        Внутри TJ-массива substitution сдвигает trailing chars влево на 55.168.
        Компенсируем: следующий kern → kern - 55.168 (более negative = больше advance).
        ВАЖНО: новый kern bytes должны иметь ТУ ЖЕ ДЛИНУ что и старый,
        иначе offsets других substitutions смещаются.
        Для standalone Tj — простая substitution без kern.
        """
        WIDTH_DIFF = 55.168  # 333 - 277.832
        # 1) Replace the literal first
        new_raw = raw[:s] + new_bytes + raw[e:]
        # 2) Detect TJ context — scan forward from e
        i = e
        while i < len(new_raw) and new_raw[i:i+1] in b' \t\r\n':
            i += 1
        if i >= len(new_raw):
            return new_raw

        nxt = new_raw[i:i+1]
        if nxt in b'-0123456789.':
            # Existing kern number — parse, adjust, write back с same length
            num_start = i
            while i < len(new_raw) and new_raw[i:i+1] in b'-0123456789.':
                i += 1
            num_end = i
            try:
                old_num = float(new_raw[num_start:num_end])
                new_num = old_num - WIDTH_DIFF
                target_len = num_end - num_start
                new_bytes_str = self._format_kern_padded(new_num, target_len)
                if len(new_bytes_str) == target_len:
                    new_raw = new_raw[:num_start] + new_bytes_str.encode('latin-1') + new_raw[num_end:]
            except ValueError:
                pass
        elif nxt == b']':
            # End of TJ array — no compensation possible without changing length
            # (compensation here would shift все subsequent substitution offsets)
            # Skip — last char's width difference accumulates только для этой row
            pass
        elif nxt == b'<':
            # Adjacent <...><...> в TJ array без explicit kern — skip (length change)
            pass
        # else: standalone Tj — no compensation needed
        return new_raw

    @staticmethod
    def _format_kern_padded(num: float, target_len: int) -> str:
        """Format float с длиной target_len. Уменьшаем precision если нужно, иначе pad с leading space."""
        for decimals in range(6, -1, -1):
            s = f'{num:.{decimals}f}'
            if len(s) <= target_len:
                if len(s) < target_len:
                    s = ' ' * (target_len - len(s)) + s
                return s
        # Fallback (very large number): use 0 decimals + truncate
        return f'{num:.0f}'[:target_len].rjust(target_len)

    def _fill_page(self, page, mapping: PageMapping, page_data: dict[str, str],
                   font: FontData, writer) -> dict:
        page_stats = {'fields_filled': 0, 'missing_chars': []}

        # Collect operations: substitutions + draws
        # Substitutions: list of (stream_idx, op_type, span, [new_bytes])
        substitutions: list = []
        # Draws: list of (tm_x, tm_y, char)
        draws: list = []

        fields_by_name = {f.field: f for f in mapping.fields}
        narrow_rows_by_name = {nr.field: nr for nr in mapping.narrow_rows}

        for field_name, value in page_data.items():
            if value is None or value == '':
                continue
            value = str(value)

            if field_name in narrow_rows_by_name:
                nr = narrow_rows_by_name[field_name]
                self._process_narrow_row(nr, value, font, page,
                                         substitutions, draws, page_stats, field_name)
                page_stats['fields_filled'] += 1
                continue

            if field_name not in fields_by_name:
                continue

            fm = fields_by_name[field_name]
            self._process_field(fm, value, font, substitutions, draws,
                                page_stats, field_name)
            page_stats['fields_filled'] += 1

        # Apply substitutions
        contents = page.get('/Contents')
        streams = list(contents) if isinstance(contents, ArrayObject) else [contents]
        new_refs: list = [None] * len(streams)

        from collections import defaultdict
        subs_by_stream = defaultdict(list)
        for op in substitutions:
            subs_by_stream[op['stream_idx']].append(op)

        for s_idx, stream_obj in enumerate(streams):
            if s_idx in subs_by_stream:
                target = stream_obj.get_object()
                raw = target.get_data()
                # Sort by start offset descending to keep offsets stable
                ops = sorted(subs_by_stream[s_idx], key=lambda op: -op['span'][0])
                for op in ops:
                    s, e = op['span']
                    expected = op.get('expected_bytes')
                    new_bytes = op['new_bytes']
                    if expected and raw[s:e] != expected:
                        # already modified — skip
                        continue
                    # ПОСИМВОЛЬНАЯ substitution (rule #17): каждая клетка независимо.
                    # Без kern compensation — каждый символ заполняется в свою клетку,
                    # никаких cross-cell adjustments.
                    raw = raw[:s] + new_bytes + raw[e:]
                new_stream = DecodedStreamObject()
                new_stream.set_data(raw)
                new_refs[s_idx] = writer._add_object(new_stream)
            else:
                if hasattr(stream_obj, 'indirect_reference') and stream_obj.indirect_reference is not None:
                    new_refs[s_idx] = stream_obj.indirect_reference
                else:
                    new_refs[s_idx] = writer._add_object(stream_obj)

        # Build draw overlay stream
        if draws:
            draw_commands = []
            for tm_x, tm_y, ch in draws:
                cid = font.char_to_cid_or_gid(ch)
                if cid is None:
                    continue
                draw_commands.append(
                    f"BT\n{font.font_name} {self.FONT_SIZE} Tf\n"
                    f"1 0 0 -1 {tm_x:.4f} {tm_y:.4f} Tm\n"
                    f"<{cid}> Tj\nET\n"
                )
            prolog = PROLOG_FULL if mapping.page_prolog_type == 'full' else PROLOG_INNER_ONLY
            content = prolog + ''.join(draw_commands) + EPILOG
            overlay = DecodedStreamObject()
            overlay.set_data(content.encode('latin-1'))
            new_refs.append(writer._add_object(overlay))

        page[NameObject('/Contents')] = ArrayObject(new_refs)
        return page_stats

    def _process_field(self, fm: FieldMapping, value: str, font: FontData,
                       substitutions: list, draws: list,
                       page_stats: dict, field_name: str):
        cells = fm.cells
        n_chars = len(value)
        n_cells = len(cells)

        if fm.alignment == 'right':
            offset = n_cells - n_chars
            pairs = []
            for i, ch in enumerate(value):
                cell_idx = offset + i
                if 0 <= cell_idx < n_cells:
                    pairs.append((cells[cell_idx], ch))
        else:
            pairs = []
            for i, ch in enumerate(value):
                if i >= n_cells:
                    break
                pairs.append((cells[i], ch))

        for cell, ch in pairs:
            if ch == '\x00':
                continue
            # Substitute <0010> → <0003> (space; same width 277.832/333 — small kerning shift but OK)
            if cell.span is not None and cell.stream_idx is not None:
                substitutions.append({
                    'stream_idx': cell.stream_idx,
                    'span': cell.span,
                    'expected_bytes': SUBST_OLD_BYTES,
                    'new_bytes': SUBST_NEW_BYTES,
                })
            if ch == ' ':
                continue  # space: substitution applied, no draw needed
            cid = font.char_to_cid_or_gid(ch)
            if cid is None:
                page_stats['missing_chars'].append((field_name, ch))
                continue
            draws.append((cell.tm_x, cell.tm_y, ch))

    def _process_narrow_row(self, nr: NarrowRow, value: str, font: FontData,
                            page, substitutions: list, draws: list,
                            page_stats: dict, field_name: str):
        """Special: date row — substitute multi-char literal + draw chars at etalon positions."""
        if not nr.etalon_positions:
            return

        # Find date literal в stream'е
        contents = page.get('/Contents')
        streams = list(contents) if isinstance(contents, ArrayObject) else [contents]
        for s_idx, stream_obj in enumerate(streams):
            raw = stream_obj.get_object().get_data()
            pos = raw.find(DATE_LITERAL_OLD)
            if pos != -1:
                substitutions.append({
                    'stream_idx': s_idx,
                    'span': [pos, pos + len(DATE_LITERAL_OLD)],
                    'expected_bytes': DATE_LITERAL_OLD,
                    'new_bytes': DATE_LITERAL_NEW,
                })
                break

        # Draw value chars at etalon tm positions
        for i, pos in enumerate(nr.etalon_positions):
            if i >= len(value):
                break
            ch = value[i]
            if ch in ('\x00', ' '):
                continue
            cid = font.char_to_cid_or_gid(ch)
            if cid is None:
                page_stats['missing_chars'].append((field_name, ch))
                continue
            draws.append((pos['tm_x'], pos['tm_y'], ch))


# ------------------------------------------------------------------------
# High-level + adapter
# ------------------------------------------------------------------------
def fill_declaration_pdf(blank_path: Path, mappings_paths: dict[int, Path],
                          data: dict[int, dict[str, str]], output_path: Path) -> dict:
    mappings = {p: load_mapping(path) for p, path in mappings_paths.items()}
    filler = PDFFiller(blank_path, mappings)
    return filler.fill(data, output_path)


def _format_int_or_empty(v) -> str:
    if v is None or v == '' or v == 0 or v == '0':
        return ''
    try:
        from decimal import Decimal
        return str(int(Decimal(str(v))))
    except Exception:
        return str(v)


def build_filler_data(
    project_data: dict,
    decl_data: dict,
    period_code: str = '34',
    signing_date: Optional[str] = None,
) -> dict[int, dict[str, str]]:
    """Преобразовать project_data + decl_data → формат для PDFFiller.fill().

    По правилам проекта (НАМЕРТВО):
    - correction_number НЕ заполняется (rule #19)
    - блок "Достоверность и полноту сведений подтверждаю" НЕ заполняется (rule #18):
      signer_type, signer_name_*, representative_*. Только дата подписания.
    - tax_object_code='1', at_location_code='120', pages_count='4--' (rule #14, #15)
    - ФИО передаётся с пробелами (rule #16)
    """
    from datetime import date as _date

    inn = str(project_data.get('inn', ''))
    fio = str(project_data.get('fio', '')).strip()
    oktmo = str(project_data.get('oktmo', ''))
    ifns = str(project_data.get('ifns_code', '0000'))
    year = str(project_data.get('tax_period_year', ''))
    phone = str(project_data.get('phone', '')).strip()

    if not signing_date:
        signing_date = _date.today().strftime('%d.%m.%Y')
    sd_parts = signing_date.split('.')
    sd_day = sd_parts[0] if len(sd_parts) >= 3 else ''
    sd_month = sd_parts[1] if len(sd_parts) >= 3 else ''
    sd_year = sd_parts[2] if len(sd_parts) >= 3 else ''

    sec_1_1 = decl_data.get('section_1_1', {})
    sec_2_1_1 = decl_data.get('section_2_1_1', {})

    # Page 1 — БЕЗ correction_number, БЕЗ signer/representative блока
    page1_data: dict[str, str] = {
        'inn': inn,
        'tax_period_code': period_code,
        'tax_period_year': year,
        'ifns_code': ifns,
        'at_location_code': '120',
        'taxpayer_fio_line1': fio,
        'tax_object_code': '1',
        'pages_count': '4--',
        'signing_date_day': sd_day,
        'signing_date_month': sd_month,
        'signing_date_year': sd_year,
    }

    if phone:
        # Посимвольно (rule #17): каждый символ value → отдельную клетку.
        # Phone field имеет 19 cells. Передаём raw digits "+79991112233" (12 chars)
        # → cells 0-11 substituted+drawn, cells 12-18 остаются как form's "-".
        digits_only = ''.join(c for c in phone if c.isdigit() or c == '+')
        if digits_only.startswith('+') and len(digits_only) == 12:
            page1_data['phone'] = digits_only
        elif len(digits_only) == 11 and digits_only.startswith(('7', '8')):
            page1_data['phone'] = '+7' + digits_only[1:]
        else:
            page1_data['phone'] = digits_only

    # Page 2 — Раздел 1.1
    has_q040 = sec_1_1.get('line_040') or sec_1_1.get('line_050')
    has_q070 = sec_1_1.get('line_070') or sec_1_1.get('line_080')
    has_q100 = sec_1_1.get('line_100') or sec_1_1.get('line_110')
    page2_data: dict[str, str] = {
        'inn': inn,
        'line_010_oktmo': oktmo,
        'line_020': _format_int_or_empty(sec_1_1.get('line_020')),
        'line_030_oktmo': oktmo if has_q040 else '',
        'line_040': _format_int_or_empty(sec_1_1.get('line_040')),
        'line_050': _format_int_or_empty(sec_1_1.get('line_050')),
        'line_060_oktmo': oktmo if has_q070 else '',
        'line_070': _format_int_or_empty(sec_1_1.get('line_070')),
        'line_080': _format_int_or_empty(sec_1_1.get('line_080')),
        'line_090_oktmo': oktmo if has_q100 else '',
        'line_100': _format_int_or_empty(sec_1_1.get('line_100')),
        'line_101_patent': _format_int_or_empty(sec_1_1.get('line_101')),
        'line_110': _format_int_or_empty(sec_1_1.get('line_110')),
        'signing_date': signing_date,
    }

    # Page 3 — Раздел 2.1.1
    rate = sec_2_1_1.get('line_120', 6)
    if isinstance(rate, (int, float)) and rate < 10:
        rate_str = str(int(rate * 10))
    else:
        rate_str = str(rate)

    page3_data: dict[str, str] = {
        'inn': inn,
        'line_101': str(sec_2_1_1.get('line_101', '1')),
        'line_102': '1' if project_data.get('has_employees') else '2',
        'line_110': _format_int_or_empty(sec_2_1_1.get('line_110')),
        'line_111': _format_int_or_empty(sec_2_1_1.get('line_111')),
        'line_112': _format_int_or_empty(sec_2_1_1.get('line_112')),
        'line_113': _format_int_or_empty(sec_2_1_1.get('line_113')),
        'line_120': rate_str,
        'line_121': rate_str,
        'line_122': rate_str,
        'line_123': rate_str,
        'line_130': _format_int_or_empty(sec_2_1_1.get('line_130')),
        'line_131': _format_int_or_empty(sec_2_1_1.get('line_131')),
        'line_132': _format_int_or_empty(sec_2_1_1.get('line_132')),
        'line_133': _format_int_or_empty(sec_2_1_1.get('line_133')),
    }

    page4_data: dict[str, str] = {
        'inn': inn,
        'insurance_q1': _format_int_or_empty(sec_2_1_1.get('line_140')),
        'insurance_h1': _format_int_or_empty(sec_2_1_1.get('line_141')),
        'insurance_9m': _format_int_or_empty(sec_2_1_1.get('line_142')),
        'insurance_y': _format_int_or_empty(sec_2_1_1.get('line_143')),
    }

    return {1: page1_data, 2: page2_data, 3: page3_data, 4: page4_data}


def get_default_mappings_paths() -> dict[int, Path]:
    base = Path(__file__).resolve().parents[3] / 'handoff' / 'pr31_filler' / 'artifacts'
    return {
        1: base / 'page1_field_mapping_blank24_25_v2.json',
        2: base / 'page2_field_mapping_blank24_25.json',
        3: base / 'page3_field_mapping_blank24_25.json',
        4: base / 'page4_field_mapping_blank24_25_v2.json',
    }


def get_default_blank_path() -> Path:
    """Стандартный путь к blank PDF.

    blank24-25_with_defaults.pdf — основной шаблон с уже заполненными defaults
    (correction='0', period='34', at_location='120', signer_type='1', pages_count='4--',
    tax_object_code='1'). Эти 6 значений в шаблоне готовые — не нужно substitute.
    """
    return Path(__file__).resolve().parents[3] / 'templates' / 'knd_1152017' / 'blank24-25_with_defaults.pdf'

