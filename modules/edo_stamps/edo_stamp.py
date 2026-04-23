"""
edo_stamp.py — обратносовместимый shim.

Реэкспортирует всё необходимое из новых модулей:
    edo_core   — ядро
    edo_tensor — штамп Тензора
    edo_kontur — штамп Контура

app.py и CLI продолжают работать без изменений:
    from edo_stamp import StampConfig, Party, apply_stamps
    python edo_stamp.py input.pdf output.pdf --operator kontur
"""

# ── Ядро ─────────────────────────────────────────────────────────────────────
from edo_core import (
    Party,
    StampConfig,
    apply_stamps,
    _fonts,
    _trunc,
    _build_metadata,
    _parse_pdf_date,
    PAGE_W, PAGE_H,
    C_K, C_GL, C_GT, C_BL, C_FBG, C_DK, C_GR, C_DV,
)

# ── Тензор ───────────────────────────────────────────────────────────────────
from edo_tensor import (
    gen_cert_send_tensor,
    gen_cert_ifns_tensor,
    render_tensor_page as _tensor,
)

# ── Контур ───────────────────────────────────────────────────────────────────
from edo_kontur import (
    gen_cert_kontur,
    render_kontur_page as _kontur,
    _kontur_icon,
    K_RX, K_BW,
    K_P1X, K_P1W, K_P1CX, K_P1HX, K_P1KO,
    K_B1_TOP, K_B1_BOT,
    K_B2_TOP, K_B2_BOT,
    K_P_TOP, K_P_BOT,
    LW,
)

# ── CLI (из оригинального edo_stamp.py) ──────────────────────────────────────
import argparse, json, secrets


def _example(op: str) -> StampConfig:
    if op == "tensor":
        return StampConfig(
            operator="tensor",
            identifier="5c2bced0-5fcc-4e2a-8a2f-238962faeaae",
            sender=Party(
                name='ООО "РЕМСЕРВИС", ИВАНОВ МИХАИЛ АНАТОЛЬЕВИЧ',
                role="ДИРЕКТОР",
                datetime_msk="22.05.2025 20:51",
                certificate=gen_cert_send_tensor(),
            ),
            receiver=Party(
                name="МЕЖРАЙОННАЯ ИНСПЕКЦИЯ ФНС № 2 ПО САРАТОВСКОЙ ОБЛАСТИ",
                role="Баймурзин Данияр Исимкулович, Начальник",
                datetime_msk="22.05.2025 21:08",
                certificate=gen_cert_ifns_tensor(),
            ),
        )
    return StampConfig(
        operator="kontur",
        tax_office_code="7734",
        inn="312772472951",
        send_date="20250127",
        doc_uuid="850a12df-3aee-3405-4d6a-67a3e7257dec",
        sender=Party(
            name="БРЕЕВ ДМИТРИЙ ОЛЕГОВИЧ",
            datetime_msk="27.01.2025 в 13:17",
            certificate=gen_cert_kontur(),
            cert_valid_from="09.12.2024",
            cert_valid_to="09.03.2026",
        ),
        receiver=Party(
            name="ИФНС РОССИИ № 34 ПО Г. МОСКВЕ",
            role="Шевлякова Анастасия Сергеевна, начальник инспекции",
            datetime_msk="27.01.2025 в 16:12",
            certificate=gen_cert_kontur(),
            cert_valid_from="15.11.2024",
            cert_valid_to="15.02.2026",
        ),
    )


def main():
    p = argparse.ArgumentParser(description="Наложение отметок ЭДО на PDF-декларацию")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--operator", choices=["kontur", "tensor"], required=True)
    p.add_argument("--config", default=None)
    p.add_argument("--example-config", action="store_true")
    args = p.parse_args()

    if args.example_config:
        import dataclasses
        print(json.dumps(
            dataclasses.asdict(_example(args.operator)),
            ensure_ascii=False,
            indent=2,
        ))
        return

    cfg = StampConfig.from_json(args.config) if args.config else _example(args.operator)
    cfg.operator = args.operator
    apply_stamps(args.input, args.output, cfg)


if __name__ == "__main__":
    main()
