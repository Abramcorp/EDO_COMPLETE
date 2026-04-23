#!/usr/bin/env bash
# ============================================================
# sync_stamps.sh — копирует edo_core.py, edo_kontur.py, edo_tensor.py,
# edo_stamp.py (shim) и шрифты из Abramcorp/edo-stamps в modules/edo_stamps/.
#
# Использование:
#   ./scripts/sync_stamps.sh [/path/to/edo-stamps]
# или
#   EDO_STAMPS_REPO=/path/to/edo-stamps ./scripts/sync_stamps.sh
# ============================================================
set -euo pipefail

SRC="${1:-${EDO_STAMPS_REPO:-}}"
if [[ -z "$SRC" ]]; then
    SRC="$(pwd)/../edo-stamps"
fi

if [[ ! -f "$SRC/edo_core.py" ]]; then
    echo "❌ Не найден edo_core.py в $SRC" >&2
    exit 1
fi

DEST="$(dirname "$(realpath "$0")")/../modules/edo_stamps"
mkdir -p "$DEST/fonts"

echo "📂 Источник: $SRC"
echo "📂 Назначение: $DEST"

FILES=(
    "edo_core.py"
    "edo_kontur.py"
    "edo_tensor.py"
    "edo_stamp.py"
)

for f in "${FILES[@]}"; do
    if [[ -f "$SRC/$f" ]]; then
        cp "$SRC/$f" "$DEST/$f"
        echo "  ✓ $f"
    else
        echo "  ⚠ $f не найден" >&2
    fi
done

# Шрифты (обязательно — иначе штампы потеряют pixel-perfect)
if [[ -d "$SRC/edo_app/fonts" ]]; then
    cp "$SRC/edo_app/fonts/"*.ttf "$DEST/fonts/"
    echo "  ✓ fonts/ ($(ls "$DEST/fonts/" | wc -l) файлов)"
else
    echo "  ⚠ edo_app/fonts/ не найден — штампы будут рендериться без Tahoma/Segoe UI" >&2
fi

COMMIT=$(cd "$SRC" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo ""
echo "📌 Commit hash: $COMMIT"
echo "📌 Занеси в docs/SOURCES_INVENTORY.md"
echo "✅ Готово."
