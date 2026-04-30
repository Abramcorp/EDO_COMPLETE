#!/usr/bin/env bash
# commit_and_push.sh — финальный коммит handoff pack + новых шаблонов
#
# Запускать из корня репо: bash handoff/pr31_filler/scripts/commit_and_push.sh

set -e

cd "$(git rev-parse --show-toplevel)"

echo "=== Добавляем все новые файлы ==="
git add templates/knd_1152017/blank_2024.pdf
git add templates/knd_1152017/blank_2025.pdf
git add templates/knd_1152017/fields_2024.json
git add scripts/blank_builder/
git add handoff/

echo ""
echo "=== Статус перед коммитом ==="
git status

echo ""
echo "=== Коммит ==="
git commit -m "PR31 handoff: blank_2024.pdf + fields_2024.json + полный handoff pack для filler

- templates/knd_1152017/blank_2024.pdf (991 KB) — 4-стр шаблон, одобрен
  - Стр.1 = ручной reference + удалены прочерки Стр.№ + добавлены '001'
  - Стр.2-4 = v2-стирание + защита /F11 + восстановлены номера
- templates/knd_1152017/blank_2025.pdf — копия (форма 5.08 на оба года)
- templates/knd_1152017/fields_2024.json — 62 поля в reportlab pt
- scripts/blank_builder/cid_map_F5.json — CID-mapping ArialMT
- handoff/pr31_filler/ — полный pack для следующей сессии:
  - MASTER_PROMPT.md, STATUS.md, README.md
  - artifacts/: blank_with_FX.pdf (со встроенным /FX), liberation_subset.ttf,
    page1_text_sequences.json, cid_maps, poc_inn_replaced.pdf
  - etalons/: эталоны Тензора и reference
  - scripts/restore_sandbox.sh

POC одного поля (ИНН Романова) подтвердил pixel-perfect совпадение с эталоном.
Метод закреплён в памяти Claude и в MASTER_PROMPT.md."

echo ""
echo "=== Пуш ==="
git push origin feat/pr30-usn-declaration

echo ""
echo "✓ Готово. Handoff в репо."
