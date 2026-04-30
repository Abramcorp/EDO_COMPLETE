#!/usr/bin/env bash
# restore_sandbox.sh — восстановление /home/claude/poc/ и /home/claude/etalons/ из handoff
# 
# Запускать из корня репо: bash handoff/pr31_filler/scripts/restore_sandbox.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
HANDOFF="$REPO_ROOT/handoff/pr31_filler"

echo "=== Восстановление sandbox из $HANDOFF ==="

# 1. POC директория
mkdir -p /home/claude/poc
cp "$HANDOFF/artifacts/blank_with_FX.pdf"          /home/claude/poc/
cp "$HANDOFF/artifacts/liberation_subset.ttf"      /home/claude/poc/
cp "$HANDOFF/artifacts/font_subset_data.json"      /home/claude/poc/
cp "$HANDOFF/artifacts/page1_text_sequences.json"  /home/claude/poc/
cp "$HANDOFF/artifacts/cid_map_F5.json"            /home/claude/poc/cid_map.json
cp "$HANDOFF/artifacts/cid_map_C2_0.json"          /home/claude/poc/cid_map_c20.json
cp "$HANDOFF/artifacts/poc_inn_replaced.pdf"       /home/claude/poc/blank_inn_replaced.pdf

echo "✓ /home/claude/poc/ восстановлен:"
ls -la /home/claude/poc/

# 2. Эталоны
mkdir -p /home/claude/etalons/etalon_1_romanov_with_marks
mkdir -p /home/claude/etalons/reference_blank
cp "$HANDOFF/etalons/etalon_romanov_5pages.pdf" \
   /home/claude/etalons/etalon_1_romanov_with_marks/NO_USN_3300_3300_330517711336_20260124_12d6c8ca-4bf8-4df5-a370-ce44469d1650.pdf
cp "$HANDOFF/etalons/reference_blank_titul.pdf" \
   /home/claude/etalons/reference_blank/blank_titul_REFERENCE.pdf

echo ""
echo "✓ /home/claude/etalons/ восстановлен:"
ls -la /home/claude/etalons/etalon_1_romanov_with_marks/
ls -la /home/claude/etalons/reference_blank/

# 3. Установка зависимостей (если нужно)
echo ""
echo "=== Проверка зависимостей ==="
python3 -c "import pypdf, pypdfium2, fontTools, PIL; print('✓ All deps installed')" 2>&1 || \
  pip install pypdf pypdfium2 fonttools Pillow --break-system-packages

echo ""
echo "=== Восстановление завершено ==="
echo "Главный документ: $HANDOFF/MASTER_PROMPT.md"
echo "Статус прогресса: $HANDOFF/STATUS.md"
