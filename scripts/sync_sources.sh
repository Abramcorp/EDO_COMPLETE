#!/usr/bin/env bash
# ============================================================
# sync_sources.sh — копирует services/ из usn-declaration
# в modules/declaration_filler/
#
# Использование:
#   ./scripts/sync_sources.sh [/path/to/usn-declaration]
# или
#   USN_DECL_REPO=/path/to/usn-declaration ./scripts/sync_sources.sh
#
# После копирования ОБЯЗАТЕЛЬНО проверить:
#   1. Нет ли in-file импортов от app.database, app.models — их нужно
#      будет заменить / проработать (см. docs/ADR-001 и modules/declaration_filler/README.md)
#   2. Зафиксировать commit hash оригинала в docs/SOURCES_INVENTORY.md
# ============================================================
set -euo pipefail

SRC="${1:-${USN_DECL_REPO:-}}"
if [[ -z "$SRC" ]]; then
    SRC="$(pwd)/../usn-declaration"
fi

if [[ ! -d "$SRC/app/services" ]]; then
    echo "❌ Не найдена папка app/services в $SRC" >&2
    echo "Передай путь к клонированному репозиторию usn-declaration" >&2
    exit 1
fi

DEST="$(dirname "$(realpath "$0")")/../modules/declaration_filler"
mkdir -p "$DEST"

echo "📂 Источник: $SRC/app/services"
echo "📂 Назначение: $DEST"

# Список файлов для копирования (белый список — чтобы не тащить мусор)
FILES=(
    "parser.py"
    "ofd_parser.py"
    "classifier.py"
    "revenue_calculator.py"
    "contributions_calculator.py"
    "tax_engine.py"
    "declaration_generator.py"
    "utils.py"
)

for f in "${FILES[@]}"; do
    if [[ -f "$SRC/app/services/$f" ]]; then
        cp "$SRC/app/services/$f" "$DEST/$f"
        echo "  ✓ $f"
    else
        echo "  ⚠ $f не найден" >&2
    fi
done

# Копируем словари и эталоны
mkdir -p "$DEST/dictionaries"
if [[ -d "$SRC/dictionaries" ]]; then
    cp -r "$SRC/dictionaries/"* "$DEST/dictionaries/"
    echo "  ✓ dictionaries/"
fi

# Шаблоны декларации (в templates/, не в modules/)
TEMPLATES_DEST="$(dirname "$(realpath "$0")")/../templates/knd_1152017"
mkdir -p "$TEMPLATES_DEST"
for t in declaration_template.xlsx declaration_template_2024.xlsx declaration_template_2025.xlsx; do
    if [[ -f "$SRC/data/$t" ]]; then
        cp "$SRC/data/$t" "$TEMPLATES_DEST/$t"
        echo "  ✓ templates/knd_1152017/$t"
    fi
done

# Зафиксировать commit hash
COMMIT=$(cd "$SRC" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo ""
echo "📌 Commit hash: $COMMIT"
echo "📌 Занеси его в docs/SOURCES_INVENTORY.md"
echo ""
echo "🔧 СЛЕДУЮЩИЙ ШАГ: написать modules/declaration_filler/__init__.py"
echo "   который экспортирует функции под контракт из core/pipeline.py:"
echo "   - parse_1c_statement_bytes(bytes) -> Statement"
echo "   - ofd_parser.parse_ofd_bytes(bytes) -> list[OfdReceipt]"
echo "   - classifier.classify_operations(statement) -> ClassifiedOps"
echo "   - tax_engine.calculate(...) -> TaxResult"
echo "   - declaration_generator.render_declaration_pdf(...) -> bytes"
echo ""
echo "✅ Готово."
