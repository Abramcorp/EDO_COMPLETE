"""
POC pixel-perfect filler через /C2_0 (ArialMT, встроенный в blank).
Заполняет ИНН '330573397709' Романова на стр.1 нового blank_2024.pdf.

Проверяет: 0% диф-пикселей в зоне ИНН в 600 DPI vs эталон Романова Тензора.

Метод:
  1. Load page1_field_mapping.json и find ИНН field
  2. Substitute <0010> → <0003> в spans (в нужном streame, обратный порядок)
  3. Добавить параллельный content stream с BT-блоком для каждой клетки:
       q + CTM_2 (0.7043 ...) + BT /C2_0 12 Tf 1 0 0 -1 tm_x tm_y Tm <cid>Tj ET ... Q
  4. Pixel-сверка с эталоном.
"""
import json
import sys
from pathlib import Path

import pypdf
from pypdf.generic import DecodedStreamObject, NameObject, ArrayObject

REPO = Path(__file__).resolve().parents[3]
ART = REPO / 'handoff/pr31_filler/artifacts'
TEMPLATES = REPO / 'templates/knd_1152017'

# CTM_2 prologue (нейтральный к Tm `1 0 0 -1 tm_x tm_y`)
CTM_PROLOG = "q\n0.24 0 0 -0.24 0 841.91998 cm\n2.9347825 0 0 2.9347825 58.333332 58.333332 cm\n"
CTM_EPILOG = "Q\n"


def fill_field_inplace(page, mapping_field: dict, value: str, char_to_cid: dict, writer):
    """В page модифицирует:
      1. nth content stream: substitute <0010> → <0003> в spans для первых N=len(value) клеток
      2. Добавляет новый content stream после всех с draw-командами для каждой клетки
    """
    contents = page.get('/Contents')
    streams = list(contents) if isinstance(contents, ArrayObject) else [contents]
    
    spans = mapping_field['spans_in_stream']
    tm_cells = mapping_field['tm_for_drawing_cells']
    stream_idx = mapping_field['stream_idx']
    n_to_fill = min(len(value), len(spans))
    
    # 1. Substitution в правильном stream
    target = streams[stream_idx].get_object()
    raw = target.get_data().decode('latin-1')
    
    for span in sorted(spans[:n_to_fill], key=lambda s: -s[0]):
        s, e = span
        fragment = raw[s:e]
        assert fragment == '<0010>', f'Ожидал <0010> на span {span}, нашёл {fragment!r}'
        raw = raw[:s] + '<0003>' + raw[e:]
    
    new_main = DecodedStreamObject()
    new_main.set_data(raw.encode('latin-1'))
    new_main_ref = writer._add_object(new_main)
    
    # Заменяем target stream в массиве (на новый ref)
    new_refs = []
    for i, s in enumerate(streams):
        if i == stream_idx:
            new_refs.append(new_main_ref)
        elif hasattr(s, 'indirect_reference') and s.indirect_reference is not None:
            new_refs.append(s.indirect_reference)
        else:
            new_refs.append(writer._add_object(s))
    
    # 2. Добавляем draw-stream через /C2_0
    draw = CTM_PROLOG
    for i, ch in enumerate(value[:n_to_fill]):
        cid = char_to_cid.get(ch)
        if cid is None:
            print(f'  WARNING: char {ch!r} not in /C2_0 ToUnicode CMap')
            continue
        tm_x, tm_y = tm_cells[i]
        draw += f"BT\n/C2_0 12 Tf\n1 0 0 -1 {tm_x:.4f} {tm_y:.4f} Tm\n<{cid}> Tj\nET\n"
    draw += CTM_EPILOG
    
    draw_stream = DecodedStreamObject()
    draw_stream.set_data(draw.encode('latin-1'))
    new_refs.append(writer._add_object(draw_stream))
    
    page[NameObject('/Contents')] = ArrayObject(new_refs)


def main():
    blank_src = TEMPLATES / 'blank_2024.pdf'
    
    mapping = json.load((ART / 'page1_field_mapping.json').open())
    inn_field = next(f for f in mapping['fields'] if f['field'] == 'inn')
    print(f'ИНН: count={inn_field["count"]}, stream_idx={inn_field["stream_idx"]}')
    print(f'  rl_baseline_first: {inn_field["rl_baseline_cells"][0]}')
    print(f'  tm_for_drawing_first: {inn_field["tm_for_drawing_cells"][0]}')
    
    reader = pypdf.PdfReader(str(blank_src))
    writer = pypdf.PdfWriter(clone_from=reader)
    page1 = writer.pages[0]
    
    sys.path.insert(0, str(REPO / 'handoff/pr31_filler/scripts'))
    from build_page_mapping import extract_font_data
    font = extract_font_data(page1, '/C2_0')
    
    fill_field_inplace(page1, inn_field, '330573397709', font['char_to_cid'], writer)
    
    out_path = ART / 'poc_inn_pixel_perfect.pdf'
    with out_path.open('wb') as f:
        writer.write(f)
    print(f'\n✓ Written: {out_path} ({out_path.stat().st_size} bytes)')
    
    # Pixel-diff с эталоном Романова
    etalon_path = Path('/home/claude/etalons/etalon_1_romanov_with_marks/NO_USN_3300_3300_330517711336_20260124_12d6c8ca-4bf8-4df5-a370-ce44469d1650.pdf')
    if not etalon_path.exists():
        print(f'  (etalon не найден, скип pixel diff)')
        return
    
    import pypdfium2 as pdfium
    import numpy as np
    
    DPI = 600
    SCALE = DPI / 72
    my = pdfium.PdfDocument(str(out_path))[0].render(scale=SCALE).to_pil().convert('L')
    et = pdfium.PdfDocument(str(etalon_path))[0].render(scale=SCALE).to_pil().convert('L')
    print(f'\nrender sizes: my={my.size}, etalon={et.size}')
    if my.size != et.size:
        w = min(my.size[0], et.size[0]); h = min(my.size[1], et.size[1])
        my = my.crop((0, 0, w, h)); et = et.crop((0, 0, w, h))
    
    PAGE_H_PT = 841.92
    cx0 = int(190 * SCALE); cx1 = int(360 * SCALE)
    cy0 = int((PAGE_H_PT - 800) * SCALE); cy1 = int((PAGE_H_PT - 780) * SCALE)
    
    my_arr = np.array(my, dtype=np.int16)
    et_arr = np.array(et, dtype=np.int16)
    inn_my = my_arr[cy0:cy1, cx0:cx1]
    inn_et = et_arr[cy0:cy1, cx0:cx1]
    diff = np.abs(inn_my - inn_et)
    diff_px = (diff > 30).sum()
    total = diff.size
    pct = 100 * diff_px / total
    status = '✓ PIXEL-PERFECT' if diff_px == 0 else f'⚠ {pct:.3f}% diff'
    print(f'INN zone diff>30: {diff_px}/{total} ({status})')
    
    # Optional debug PNGs
    debug_dir = Path('/tmp/pr31_debug')
    if debug_dir.exists():
        from PIL import Image
        Image.fromarray(inn_my.astype('uint8')).save(debug_dir / 'inn_my.png')
        Image.fromarray(inn_et.astype('uint8')).save(debug_dir / 'inn_et.png')
        diff_vis = (diff > 30).astype('uint8') * 255
        Image.fromarray(diff_vis).save(debug_dir / 'inn_diff.png')


if __name__ == '__main__':
    main()
