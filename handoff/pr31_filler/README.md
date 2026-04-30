# PR31 Filler — Handoff Pack

Полный набор материалов для следующей сессии Claude по задаче **PR31: pixel-perfect генерация декларации УСН (КНД 1152017)**.

## Структура

```
handoff/pr31_filler/
├── README.md                ← ты здесь
├── MASTER_PROMPT.md         ← ГЛАВНЫЙ ДОКУМЕНТ — прочитать первым
├── STATUS.md                ← детальный прогресс DONE/IN PROGRESS/TODO
├── artifacts/               ← бинарные артефакты POC
│   ├── blank_with_FX.pdf            (~1 МБ) blank_2024.pdf + встроенный шрифт /FX
│   ├── liberation_subset.ttf         (22 КБ) subset Liberation Sans 87 символов
│   ├── font_subset_data.json         (1 КБ)  unicode→GID mapping для /FX
│   ├── page1_text_sequences.json    (125 КБ) карта <hex> spans в TJ-массивах стр.1
│   ├── cid_map_F5.json               (3 КБ)  CID-mapping ArialMT эталона стр.2-4
│   ├── cid_map_C2_0.json             (3 КБ)  CID-mapping reference стр.1
│   └── poc_inn_replaced.pdf         (1.3 МБ) рабочий POC одного поля (ИНН Романова)
├── etalons/                 ← эталонные образцы
│   ├── etalon_romanov_5pages.pdf    (200 КБ) Тензор-эталон Романова со штампом
│   └── reference_blank_titul.pdf   (1.2 МБ) твой ручной reference стр.1
└── scripts/
    └── restore_sandbox.sh    ← восстановление /home/claude/poc/ и /home/claude/etalons/
```

## Старт следующей сессии

```bash
# 1. Восстановить песочницу из артефактов
bash handoff/pr31_filler/scripts/restore_sandbox.sh

# 2. Прочитать главный документ
cat handoff/pr31_filler/MASTER_PROMPT.md

# 3. Посмотреть текущий статус и TODO
cat handoff/pr31_filler/STATUS.md

# 4. Продолжить работу с пункта "TODO #1: Достроить mapping FIELD_TO_DASH_GROUP"
```

## Что входит в pack

### MASTER_PROMPT.md
Главный документ. Содержит:
- Контекст проекта
- Что уже сделано
- Что осталось сделать
- Тестовые данные Романова
- Зафиксированные правила (CRITICAL)
- Зафиксированный технический метод (THE METHOD)
- Якоря последовательностей стр.1 (cheat sheet)

### STATUS.md
Детальный прогресс с разбивкой:
- DONE: всё что готово
- IN PROGRESS: 9 из 17 полей стр.1 размечены
- TODO: пошаговый план до завершения PR31

### artifacts/
Бинарные файлы POC, которые НЕ восстанавливаются из кода (нужно их брать отсюда):
- **blank_with_FX.pdf** — критичный артефакт, в нём встроенный шрифт `/FX` со всей кириллицей
- **liberation_subset.ttf** — TTF файл шрифта (можно пересоздать через fontTools, но проще взять)
- **font_subset_data.json** — mapping unicode→GID для шрифта
- **page1_text_sequences.json** — карта всех `<hex>` spans для удаления прочерков на стр.1
- **cid_map_F5.json**, **cid_map_C2_0.json** — CID-маппинги шрифтов
- **poc_inn_replaced.pdf** — рабочий POC одного поля (ИНН), показывает что метод работает

### etalons/
Эталонные образцы для проверки и сравнения:
- **etalon_romanov_5pages.pdf** — Тензор-эталон Романова (5 страниц, последняя = штамп)
- **reference_blank_titul.pdf** — твой вручную исправленный reference титульного листа

## Метод (краткая выжимка)

Технология подтверждена POC'ом ИНН Романова — pixel-perfect совпадение с эталоном.

```python
# 1. Координатное преобразование (КАЛИБРОВАНО на 10 полях)
def rl_to_tm(x_rl, y_rl):
    tm_x = (x_rl - 14) / 0.7043
    tm_y = (827.92 - y_rl) / 0.7043 - 2.555
    return tm_x, tm_y

# 2. На стр.1 (TJ-массивы): удаление прочерка через literal substring 
#    в основном content stream — заменить <0010> на <0003>

# 3. Параллельно в новом content stream рисовать данные через шрифт /FX
#    (Liberation Sans, Identity-H, GID == Unicode)
```

См. полное описание в MASTER_PROMPT.md → раздел "Зафиксированный технический метод (THE METHOD)".

## Манера работы

- Q&A режим с вариантами A/B/C при развилках (ask_user_input_v0)
- Один пакетный git-патч при множественных правках  
- Рендер только в 600 DPI, попиксельное сравнение
- НЕ выдавать "готово" без сверки с эталоном
