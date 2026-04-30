"""
build_page_mapping.py — self-contained sборщик field-mapping для стр.1 и стр.4
нового blank_2024.pdf / blank_2025.pdf (приказ ЕД-7-3/813@, версия с 8 content
streams на стр.1 и расширенной стр.4 со строками 150/160/161/162).

Не требует никаких внешних artifacts — всё извлекается напрямую из PDF:
  - widths /C2_0 из W-array
  - ToUnicode CMap из /ToUnicode для расшифровки текста
  - встроенный TTF (FontFile2) для unicode→GID при рисовании любого символа

Запуск:
  python3 handoff/pr31_filler/scripts/build_page_mapping.py [--page 1|4] [--verify]

Выход:
  handoff/pr31_filler/artifacts/page{N}_field_mapping.json
"""
import json
import re
import sys
from pathlib import Path

import pypdf
from pypdf.generic import ArrayObject

REPO = Path(__file__).resolve().parents[3]
ART = REPO / 'handoff/pr31_filler/artifacts'
TEMPLATES = REPO / 'templates/knd_1152017'

# CTM_2 которая применяется к BT/TJ-блокам с /C2_0:
#   q + 0.24 0 0 -0.24 0 841.91998 cm + 2.9347825 0 0 2.9347825 58.333332 58.333332 cm
#   = [0.7043478, 0, 0, -0.7043478, 14.0, 827.91998]
CTM_A = 0.7043478
CTM_E = 14.0
CTM_F = 827.91998


def to_tm_for_drawing(rl_x: float, rl_y: float) -> tuple[float, float]:
    """rl-baseline (device) → tm для рисования через /C2_0 12 Tf, 1 0 0 -1 tm_x tm_y Tm."""
    return round((rl_x - CTM_E) / CTM_A, 4), round((CTM_F - rl_y) / CTM_A, 4)


# =======================================================================
# 1. Извлечение font data из PDF
# =======================================================================
def parse_W_array(W) -> dict[str, float]:
    """PDF /W array → {cid_hex: width_em_1000}.

    Form 1: a [w1 w2 ... wN] — widths for cids a, a+1, ..., a+N-1
    Form 2: a b w — same width w for cids a..b inclusive
    """
    widths = {}
    i = 0
    items = list(W)
    while i < len(items):
        a = int(items[i])
        if i + 1 < len(items) and isinstance(items[i+1], (list, ArrayObject)):
            arr = items[i+1]
            for j, w in enumerate(arr):
                widths[f'{a+j:04X}'] = float(w)
            i += 2
        else:
            b = int(items[i+1])
            w = float(items[i+2])
            for cid in range(a, b+1):
                widths[f'{cid:04X}'] = w
            i += 3
    return widths


def parse_tounicode_cmap(cmap_data: str) -> dict[str, str]:
    """ToUnicode CMap → {cid_hex: unicode_char}.

    Парсит beginbfchar и beginbfrange блоки.
    """
    out = {}
    
    # bfchar: <CID> <UNICODE>
    for m in re.finditer(r'beginbfchar(.*?)endbfchar', cmap_data, re.DOTALL):
        for cm in re.finditer(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', m.group(1)):
            cid = cm.group(1).upper().zfill(4)
            uchar = chr(int(cm.group(2), 16))
            out[cid] = uchar
    
    # bfrange: <CID_START> <CID_END> <UNICODE_START>  →  CID_START..CID_END mapped sequentially
    for m in re.finditer(r'beginbfrange(.*?)endbfrange', cmap_data, re.DOTALL):
        body = m.group(1)
        # Forms:
        #   <s> <e> <u_start>     — sequential
        #   <s> <e> [<u1> <u2> ...]  — explicit list
        for cm in re.finditer(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<([0-9A-Fa-f]+)>|\[([^\]]*)\])', body):
            s = int(cm.group(1), 16)
            e = int(cm.group(2), 16)
            if cm.group(4):  # sequential form
                u_start = int(cm.group(4), 16)
                for cid in range(s, e+1):
                    out[f'{cid:04X}'] = chr(u_start + (cid - s))
            else:  # list form
                items = re.findall(r'<([0-9A-Fa-f]+)>', cm.group(5))
                for cid, u_hex in zip(range(s, e+1), items):
                    out[f'{cid:04X}'] = chr(int(u_hex, 16))
    
    return out


def extract_font_data(page, font_name: str = '/C2_0') -> dict:
    """Извлечь widths, cid_to_char, char_to_cid и TTF bytes из шрифта на странице."""
    font_obj = page['/Resources']['/Font'][font_name].get_object()
    df = font_obj['/DescendantFonts'][0].get_object()
    
    # Widths
    W = df.get('/W')
    widths = parse_W_array(W) if W else {}
    dw = float(df.get('/DW', 750))
    
    # ToUnicode CMap
    tu = font_obj.get('/ToUnicode')
    cid_to_char = {}
    if tu:
        cid_to_char = parse_tounicode_cmap(tu.get_object().get_data().decode('latin-1', errors='replace'))
    
    char_to_cid = {ch: cid for cid, ch in cid_to_char.items()}
    
    # FontFile2 TTF bytes (для филлера: unicode→GID при рисовании любых символов)
    ttf_bytes = None
    desc = df.get('/FontDescriptor')
    if desc:
        ff = desc.get_object().get('/FontFile2')
        if ff:
            ttf_bytes = ff.get_object().get_data()
    
    return {
        'widths': widths,
        'dw': dw,
        'cid_to_char': cid_to_char,
        'char_to_cid': char_to_cid,
        'ttf_bytes': ttf_bytes,
        'base_font': str(font_obj.get('/BaseFont')),
    }


# =======================================================================
# 2. Парсер content stream (TJ + Tm + Td)
# =======================================================================
def parse_content_stream(raw: str, widths: dict, cid_to_char: dict) -> list[dict]:
    """Полный TJ-парсер с tracking text matrix И graphics state CTM.
    Возвращает список элементов: {idx, hex, text, abs_span, rl_x, rl_y, fs}.
    rl_x/rl_y — реальные device-space координаты baseline (с учётом q/Q/cm).
    """
    n = len(raw)
    fs = None
    Tm_a = Tm_b = Tm_c = Tm_d = Tm_e = Tm_f = None
    Tlm_a = Tlm_b = Tlm_c = Tlm_d = Tlm_e = Tlm_f = None
    th = 1.0
    
    # CTM (current transformation matrix) — отслеживаем стек q/Q + cm.
    # CTM = [a, b, c, d, e, f] действует как row-vector × matrix:
    #   device = (text_x * a + text_y * c + e,  text_x * b + text_y * d + f)
    # cm op concatenates: new_CTM = old_CTM_pre × cm_matrix (но в PDF — это cm_matrix × CTM).
    # PDF spec: "x' y' = x y * CTM_new where CTM_new = m_cm × CTM_old"
    ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]  # identity at start
    ctm_stack = []

    def hex_chunks(hx):
        return [hx[i:i+4].upper() for i in range(0, len(hx), 4)]

    def w_em(c):
        return widths.get(c, 0.0)

    def text_of(hx):
        return ''.join(cid_to_char.get(c, '?') for c in hex_chunks(hx))
    
    def matrix_concat(m_new, m_old):
        """m_new × m_old (PDF cm semantics: new CTM = m_new × old CTM)."""
        a1, b1, c1, d1, e1, f1 = m_new
        a2, b2, c2, d2, e2, f2 = m_old
        return [
            a1*a2 + b1*c2,
            a1*b2 + b1*d2,
            c1*a2 + d1*c2,
            c1*b2 + d1*d2,
            e1*a2 + f1*c2 + e2,
            e1*b2 + f1*d2 + f2,
        ]
    
    def tm_to_device(tm_e, tm_f):
        """Tm.e/Tm.f текст-позиция (0,0) → device coord через Tm и CTM."""
        # Сначала через Tm (но baseline всегда text(0,0), значит вклад от Tm = (Tm.e, Tm.f)).
        # Затем через CTM:
        return (
            tm_e * ctm[0] + tm_f * ctm[2] + ctm[4],
            tm_e * ctm[1] + tm_f * ctm[3] + ctm[5],
        )

    out = []
    pos = 0
    stack = []

    def to_num(s):
        try:
            return int(s)
        except ValueError:
            return float(s)

    while pos < n:
        while pos < n and raw[pos] in ' \t\n\r':
            pos += 1
        if pos >= n:
            break
        ch = raw[pos]

        if ch == '<' and (pos + 1 >= n or raw[pos+1] != '<'):
            end = raw.index('>', pos)
            stack.append({'type': 'hex', 'value': raw[pos+1:end], 'abs_span': [pos, end+1]})
            pos = end + 1
            continue
        if ch == '(':
            depth = 1; j = pos + 1
            while j < n and depth > 0:
                if raw[j] == '\\':
                    j += 2; continue
                if raw[j] == '(': depth += 1
                elif raw[j] == ')': depth -= 1
                j += 1
            stack.append({'type': 'str'}); pos = j; continue
        if ch == '[':
            depth = 1; j = pos + 1; items = []
            while j < n and depth > 0:
                while j < n and raw[j] in ' \t\n\r': j += 1
                if j >= n: break
                if raw[j] == ']':
                    depth -= 1; j += 1; break
                if raw[j] == '<':
                    e = raw.index('>', j)
                    items.append({'type':'hex','value':raw[j+1:e],'abs_span':[j, e+1]})
                    j = e + 1
                elif raw[j] == '(':
                    d2 = 1; k = j + 1
                    while k < n and d2 > 0:
                        if raw[k] == '\\': k += 2; continue
                        if raw[k] == '(': d2 += 1
                        elif raw[k] == ')': d2 -= 1
                        k += 1
                    items.append({'type':'str'}); j = k
                else:
                    m = re.match(r'-?[\d.]+', raw[j:])
                    if m:
                        items.append({'type':'num','value':to_num(m.group())}); j += len(m.group())
                    else:
                        j += 1
            stack.append({'type':'arr','items':items}); pos = j; continue
        if ch == '/':
            m = re.match(r'/[^\s\[\]<>()/]+', raw[pos:])
            stack.append({'type':'name','value':m.group()}); pos += len(m.group()); continue
        m = re.match(r'-?\d+\.?\d*|-?\.\d+', raw[pos:])
        if m and m.group():
            stack.append({'type':'num','value':to_num(m.group())}); pos += len(m.group()); continue
        m = re.match(r'[A-Za-z\*\'\"]+', raw[pos:])
        if not m:
            pos += 1; continue
        op = m.group(); pos += len(op)

        if op == 'q':
            ctm_stack.append(list(ctm))
        elif op == 'Q':
            if ctm_stack:
                ctm = ctm_stack.pop()
        elif op == 'cm':
            # a b c d e f cm
            m_new = [s['value'] for s in stack[-6:]]
            ctm = matrix_concat(m_new, ctm)
        elif op == 'BT':
            pass
        elif op == 'ET':
            pass
        elif op == 'Tf':
            fs = stack[-1]['value']
        elif op == 'Tm':
            a, b, c, d, e, f = [s['value'] for s in stack[-6:]]
            Tm_a, Tm_b, Tm_c, Tm_d, Tm_e, Tm_f = a, b, c, d, e, f
            Tlm_a, Tlm_b, Tlm_c, Tlm_d, Tlm_e, Tlm_f = a, b, c, d, e, f
        elif op in ('Td', 'TD'):
            tx, ty = stack[-2]['value'], stack[-1]['value']
            new_e = Tlm_a * tx + Tlm_c * ty + Tlm_e
            new_f = Tlm_b * tx + Tlm_d * ty + Tlm_f
            Tlm_e, Tlm_f = new_e, new_f
            Tm_e, Tm_f = Tlm_e, Tlm_f
        elif op == "T*":
            pass
        elif op == 'Tz':
            th = stack[-1]['value'] / 100.0
        elif op == 'Tj':
            elem = stack[-1]
            hx = elem['value']
            dx, dy = tm_to_device(Tm_e, Tm_f)
            out.append({
                'idx': len(out),
                'hex': hx,
                'text': text_of(hx),
                'abs_span': elem['abs_span'],
                'rl_x': round(dx, 4),
                'rl_y': round(dy, 4),
                'fs': fs,
            })
            adv = sum(w_em(c) for c in hex_chunks(hx)) / 1000.0 * fs * Tm_a * th
            Tm_e += adv
        elif op == 'TJ':
            arr = stack[-1]['items']
            for elem in arr:
                if elem['type'] == 'hex':
                    hx = elem['value']
                    dx, dy = tm_to_device(Tm_e, Tm_f)
                    out.append({
                        'idx': len(out),
                        'hex': hx,
                        'text': text_of(hx),
                        'abs_span': elem['abs_span'],
                        'rl_x': round(dx, 4),
                        'rl_y': round(dy, 4),
                        'fs': fs,
                    })
                    adv = sum(w_em(c) for c in hex_chunks(hx)) / 1000.0 * fs * Tm_a * th
                    Tm_e += adv
                elif elem['type'] == 'num':
                    Tm_e -= elem['value'] / 1000.0 * fs * Tm_a * th

        if op not in ('q', 'Q'):
            stack.clear()

    return out


def find_dashes_stream(page) -> tuple[bytes, int]:
    """Найти content stream содержащий <0010>-прочерки. Возвращает (raw_bytes, stream_index)."""
    contents = page.get('/Contents')
    if isinstance(contents, ArrayObject):
        for i, ref in enumerate(contents):
            data = ref.get_object().get_data()
            if b'<0010>' in data:
                return data, i
        raise ValueError('no <0010> found in any content stream')
    else:
        data = contents.get_object().get_data()
        if b'<0010>' not in data:
            raise ValueError('no <0010> in main content stream')
        return data, 0


def parse_page_streams(page, widths: dict, cid_to_char: dict) -> tuple[list[dict], int]:
    """
    Парсит ВСЕ content streams страницы последовательно (CTM накапливается через все).
    Это критично: stream[7] может зависеть от CTM, накопленной в [0..6].

    Возвращает:
      elements — список TJ/Tj-элементов с device-space rl_x/rl_y и
                 abs_span_in_dashes_stream (если элемент в dashes stream),
                 или abs_span_global (для других)
      dashes_stream_idx — индекс stream'а с <0010> (для substitution)
    """
    contents = page.get('/Contents')
    streams = list(contents) if isinstance(contents, ArrayObject) else [contents]
    
    raw_blobs = [s.get_object().get_data() for s in streams]
    
    # Найдём dashes stream
    dashes_idx = None
    for i, b in enumerate(raw_blobs):
        if b'<0010>' in b:
            dashes_idx = i
            break
    if dashes_idx is None:
        raise ValueError('no <0010> in any content stream')
    
    # Конкатенируем все streams через '\n' разделитель и помним границы
    # PDF semantics: /Contents [s1 s2] эквивалентно s1 + b' ' + s2 при чтении
    sep = b'\n'
    boundaries = []  # [(stream_idx, start_pos_in_concat, end_pos_in_concat)]
    concat = b''
    for i, b in enumerate(raw_blobs):
        start = len(concat)
        concat += b
        end = len(concat)
        boundaries.append((i, start, end))
        concat += sep
    
    raw = concat.decode('latin-1')
    
    # Парсим всё одним проходом
    elems_global = parse_content_stream(raw, widths, cid_to_char)
    
    # Для каждого элемента: переводим abs_span в (stream_idx, span_in_stream).
    # Также фильтруем — оставляем все, но добавляем мета.
    for e in elems_global:
        s_start_global, s_end_global = e['abs_span']
        # Находим в каком stream
        for s_idx, s_start, s_end in boundaries:
            if s_start <= s_start_global < s_end:
                e['stream_idx'] = s_idx
                e['span_in_stream'] = [s_start_global - s_start, s_end_global - s_start]
                break
        else:
            # элемент в разделителе (sep) — игнорируем
            e['stream_idx'] = -1
            e['span_in_stream'] = e['abs_span']
    
    return elems_global, dashes_idx


# =======================================================================
# 3. Описание полей стр.1 (33 +1 kpp = 34 поля для нового blank где KPP-dashes есть)
# =======================================================================
FIELDS_PAGE1 = [
    # ------- BLOCK_TOP --------
    {'field': 'inn',                'anchor': 'ИНН',          'occurrence': 1, 'count': 12},
    # kpp на стр.1 для ИП — отсутствует в reference (Валентин стирает; новый blank тоже без KPP-dashes).
    # Для ЮЛ-клиентов потребуется альтернативный reference; пока пропускаем.
    # page_number ('001') уже встроен в новый blank в отдельном q-блоке (рисуется поверх ' '×3),
    # так что filler его не трогает. Не включаем в FIELDS_PAGE1.
    {'field': 'correction_number',  'anchor': 'тировки',      'occurrence': 1, 'count': 3},
    {'field': 'tax_period_code',    'anchor': 'д)',           'occurrence': 1, 'count': 2},
    {'field': 'tax_period_year',    'anchor': 'тный год',     'occurrence': 1, 'count': 4},
    {'field': 'ifns_code',          'anchor': 'д)',           'occurrence': 2, 'count': 4},
    {'field': 'at_location_code',   'anchor': 'д)',           'occurrence': 3, 'count': 3},
    {'field': 'taxpayer_fio_line1', 'prev_field': 'at_location_code', 'count': 38},
    {'field': 'taxpayer_fio_line2', 'prev_field': 'taxpayer_fio_line1', 'count': 40},
    {'field': 'taxpayer_fio_line3', 'prev_field': 'taxpayer_fio_line2', 'count': 40},
    {'field': 'taxpayer_fio_line4', 'prev_field': 'taxpayer_fio_line3', 'count': 40},
    {'field': 'reorg_form',         'anchor': 'ликвидации) (код)', 'occurrence': 1, 'count': 1},
    {'field': 'reorg_inn',          'prev_field': 'reorg_form', 'count': 10},
    {'field': 'reorg_kpp',          'prev_field': 'reorg_inn',  'count': 9},
    # phone: anchor 'телефона' резолвит idx=311. Между ним и реальными phone-dashes (idx=316..326,
    # rl_y=556.75) встречается outlier dash idx=313 на rl_y=556.75 но x=227.71 (вне phone-row).
    # expected_rl_y фильтрует по баseline (выводит только dashes с rl_y ≈ 556.75).
    {'field': 'phone',                          'anchor': 'телефона', 'occurrence': 1, 'count': 11, 'expected_rl_y': 556.75, 'expected_rl_x_min': 290.0},
    {'field': 'tax_object_code',                'anchor': 'жения:',   'occurrence': 1, 'count': 1},
    {'field': 'pages_count',                    'anchor': 'расходов', 'occurrence': 1, 'count': 3},
    {'field': 'appendix_pages_count',           'prev_field': 'pages_count', 'count': 3},
    {'field': 'signer_type',                    'anchor': 'ерждаю:',  'occurrence': 1, 'count': 1},
    {'field': 'signer_name_line1',              'prev_field': 'signer_type', 'count': 10},
    {'field': 'signer_name_line2',              'prev_field': 'signer_name_line1', 'count': 5},
    {'field': 'signer_name_line3',              'prev_field': 'signer_name_line2', 'count': 10},
    {'field': 'repr_org_line1',                 'prev_field': 'signer_name_line3', 'count': 20},
    {'field': 'repr_org_line2',                 'prev_field': 'repr_org_line1', 'count': 40},
    {'field': 'repr_org_line3',                 'prev_field': 'repr_org_line2', 'count': 20},
    {'field': 'repr_org_line4',                 'prev_field': 'repr_org_line3', 'count': 20},
    {'field': 'repr_org_line5',                 'prev_field': 'repr_org_line4', 'count': 20},
    {'field': 'repr_org_line6',                 'prev_field': 'repr_org_line5', 'count': 40},
    {'field': 'signing_date_day',               'anchor': 'Дата',     'occurrence': 1, 'count': 2},
    {'field': 'signing_date_month',             'prev_field': 'signing_date_day', 'count': 2},
    {'field': 'signing_date_year',              'prev_field': 'signing_date_month', 'count': 4},
    {'field': 'representative_document_line1',  'anchor': 'плательщика', 'occurrence': 'last', 'count': 14},
    {'field': 'representative_document_line2',  'prev_field': 'representative_document_line1', 'count': 2},
]

# Поля стр.4 (новые в этом blank: 150, 160, 161, 162; плюс ИНН/КПП/Стр./140-143)
FIELDS_PAGE4 = [
    {'field': 'inn',                'anchor': 'ИНН', 'occurrence': 1, 'count': 12},
    # kpp и page_number ('004') в новом blank: KPP-dashes отсутствуют для ИП,
    # page_number уже встроен в blank — не включаем.
    {'field': 'insurance_q1',       'anchor': '140', 'occurrence': 1, 'count': 12, 'expected_rl_y': 650.4},
    {'field': 'insurance_h1',       'anchor': '141', 'occurrence': 1, 'count': 12, 'expected_rl_y': 614.5},
    {'field': 'insurance_9m',       'anchor': '142', 'occurrence': 1, 'count': 12, 'expected_rl_y': 578.6},
    {'field': 'insurance_y',        'anchor': '143', 'occurrence': 1, 'count': 12, 'expected_rl_y': 542.7},
    # Строки 150-162 с column-major порядком dashes в content stream:
    # 150 имеет 12 dashes на y≈480 (две строки 479.97 и 480.15, в пределах tolerance 1pt).
    {'field': 'insurance_fixed',    'anchor': '150', 'occurrence': 1, 'count': 12, 'expected_rl_y': 480.0, 'rl_y_tolerance': 1.5},
    {'field': 'insurance_1pct',     'anchor': '160', 'occurrence': 1, 'count': 6,  'expected_rl_y': 462.15},
    {'field': 'insurance_1pct_curr','anchor': '161', 'occurrence': 1, 'count': 6,  'expected_rl_y': 445.15},
    {'field': 'insurance_1pct_prev','anchor': '162', 'occurrence': 1, 'count': 6,  'expected_rl_y': 427.15},
]


# =======================================================================
# 4. Anchor resolver
# =======================================================================
def find_anchor_idx(seq: list, anchor: str, occurrence) -> int | None:
    if occurrence == 'last':
        last = None
        for i, it in enumerate(seq):
            if it['text'] == anchor:
                last = i
        if last is not None:
            return last
        return _find_substring_idx(seq, anchor, 'last')
    
    matches = [i for i, it in enumerate(seq) if it['text'] == anchor]
    if len(matches) >= occurrence:
        return matches[occurrence - 1]
    
    return _find_substring_idx(seq, anchor, occurrence)


def _find_substring_idx(seq: list, anchor: str, occurrence) -> int | None:
    text = ''
    boundaries = []
    for i, it in enumerate(seq):
        text += it['text']
        boundaries.append((i, len(text)))
    
    starts = []
    p = 0
    while True:
        f = text.find(anchor, p)
        if f < 0:
            break
        starts.append(f)
        p = f + 1
    
    if occurrence == 'last':
        if not starts:
            return None
        idx_match = starts[-1]
    elif len(starts) >= occurrence:
        idx_match = starts[occurrence - 1]
    else:
        return None
    
    end_char = idx_match + len(anchor)
    for i, end in boundaries:
        if end >= end_char:
            return i
    return None


def resolve_field(spec: dict, seq: list, prev_results: dict) -> dict:
    count = spec['count']
    expected_y = spec.get('expected_rl_y')
    expected_x_min = spec.get('expected_rl_x_min')
    expected_x_max = spec.get('expected_rl_x_max')
    y_tol = spec.get('rl_y_tolerance', 1.0)
    
    def dash_passes_filter(d):
        if d['hex'] != '0010':
            return False
        if expected_y is not None and abs(d['rl_y'] - expected_y) > y_tol:
            return False
        if expected_x_min is not None and d['rl_x'] < expected_x_min:
            return False
        if expected_x_max is not None and d['rl_x'] > expected_x_max:
            return False
        return True
    
    if 'prev_field' in spec:
        prev = prev_results.get(spec['prev_field'])
        if not prev or 'error' in prev:
            return {'error': f"{spec['field']}: prev_field '{spec['prev_field']}' missing"}
        prev_last_idx = prev['dash_indices'][-1]
        start_search = prev_last_idx + 1
    else:
        anchor = spec['anchor']
        occ = spec['occurrence']
        anchor_idx = find_anchor_idx(seq, anchor, occ)
        if anchor_idx is None:
            return {'error': f"{spec['field']}: anchor {anchor!r} (occ={occ}) not found"}
        start_search = anchor_idx + 1
    
    # Собираем dashes последовательно, пропуская не подходящие под фильтр
    # (но останавливаясь при первом несоответствии после того как уже начали собирать).
    dashes = []
    started = False
    for i in range(start_search, len(seq)):
        d = seq[i]
        if dash_passes_filter(d):
            dashes.append(d)
            started = True
            if len(dashes) >= count:
                break
        else:
            # Если уже начали собирать и встретили НЕ-dash на той же rl_y что target —
            # это конец группы (выход из field).
            if started and expected_y is not None:
                # Outlier с другим y/x пропускаем; элемент с правильной y но non-dash — конец
                if abs(d['rl_y'] - expected_y) <= y_tol and d['hex'] != '0010':
                    break
                # иначе скип (другой block, q/Q artifacts)
                continue
            if started and expected_y is None:
                # без expected_y — простая логика: следующий не-dash сразу конец
                if d['hex'] != '0010':
                    break
                continue
            # ещё не начали → продолжаем поиск первого
    
    if len(dashes) < count:
        return {'error': f"{spec['field']}: only {len(dashes)} dashes available, need {count}"}
    
    # Sort dashes по rl_x по возрастанию (left-to-right) — иначе на стр.4 строки 150-162
    # идут в content stream в column-major порядке (правые столбцы сверху вниз).
    # Filler рисует значения слева направо.
    dashes_sorted = sorted(dashes, key=lambda d: d['rl_x'])
    
    return {
        'field': spec['field'],
        'anchor': spec.get('anchor'),
        'occurrence': spec.get('occurrence'),
        'prev_field': spec.get('prev_field'),
        'count': count,
        'dash_indices': [d['idx'] for d in dashes_sorted],
        'stream_idx': dashes_sorted[0].get('stream_idx', 0),
        'spans_in_stream': [d.get('span_in_stream', d['abs_span']) for d in dashes_sorted],
        'rl_baseline_cells': [[d['rl_x'], d['rl_y']] for d in dashes_sorted],
        'tm_for_drawing_cells': [list(to_tm_for_drawing(d['rl_x'], d['rl_y'])) for d in dashes_sorted],
    }


# =======================================================================
# 5. Main
# =======================================================================
def build_for_page(blank_path: Path, page_number: int, fields_spec: list) -> dict:
    print(f'\n=== build mapping for page {page_number} of {blank_path.name} ===')
    reader = pypdf.PdfReader(str(blank_path))
    page = reader.pages[page_number - 1]
    
    # 1. Extract font /C2_0 data
    font = extract_font_data(page, '/C2_0')
    print(f'  Font /C2_0: {font["base_font"]},  widths: {len(font["widths"])} entries,  cmap: {len(font["cid_to_char"])} entries')
    
    # 2. Parse all content streams (cumulative CTM)
    elems, dashes_stream_idx = parse_page_streams(page, font['widths'], font['cid_to_char'])
    print(f'  Parsed {len(elems)} elements,  dashes stream index: {dashes_stream_idx}')
    
    # 3. Resolve fields
    prev = {}
    fields_out = []
    errors = []
    for spec in fields_spec:
        res = resolve_field(spec, elems, prev)
        if 'error' in res:
            errors.append(res['error'])
            print(f'    ❌ {spec["field"]}: {res["error"]}')
            prev[spec['field']] = res
        else:
            fields_out.append(res)
            prev[spec['field']] = res
            xy = res['rl_baseline_cells'][0]
            print(f'    ✓ {spec["field"]:<35} count={res["count"]:>3}  rl_first=({xy[0]:7.2f},{xy[1]:7.2f})  idx_first={res["dash_indices"][0]}  stream={res["stream_idx"]}')
    
    return {
        '_meta': {
            'description': f'PR31 page {page_number} field mapping (method v2: anchor + Tm + CTM tracking)',
            'source_pdf': str(blank_path.relative_to(REPO)),
            'page_number': page_number,
            'dashes_content_stream_index': dashes_stream_idx,
            'font_used': font['base_font'],
            'rl_baseline_to_tm': 'tm_x = (rl_x - 14) / 0.7043478;  tm_y = (827.91998 - rl_y) / 0.7043478',
            'tm_text_matrix_for_drawing': '1 0 0 -1 tm_x tm_y Tm  (in /C2_0 12 Tf BT block, prologued by q + 0.24 0 0 -0.24 0 841.91998 cm + 2.9347825 0 0 2.9347825 58.333332 58.333332 cm)',
            'fields_count': len(fields_out),
            'errors_count': len(errors),
        },
        'fields': fields_out,
        '_errors': errors,
    }


def main():
    page_arg = '1'
    if '--page' in sys.argv:
        page_arg = sys.argv[sys.argv.index('--page') + 1]
    
    blank_path = TEMPLATES / 'blank_2024.pdf'
    
    pages = []
    if page_arg == 'all':
        pages = [1, 4]
    else:
        pages = [int(page_arg)]
    
    for p in pages:
        spec = FIELDS_PAGE1 if p == 1 else FIELDS_PAGE4
        out = build_for_page(blank_path, p, spec)
        out_path = ART / f'page{p}_field_mapping.json'
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        print(f'\n✓ Written: {out_path}  ({out_path.stat().st_size} bytes)')
        print(f'  fields: {out["_meta"]["fields_count"]},  errors: {out["_meta"]["errors_count"]}')


if __name__ == '__main__':
    main()
