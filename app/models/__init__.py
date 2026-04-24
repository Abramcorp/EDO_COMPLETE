"""
Shim для `from app.models import ...` — legacy-импорты из usn-declaration.

В EDO_COMPLETE эти ORM-модели не нужны (мы работаем через SQLAlchemy-модели
в api/db.py), но старый код может импортировать их на уровне модуля и падать
при загрузке — эти минимальные stub-классы этого не допускают.

Любая РЕАЛЬНАЯ работа с этими классами (создание экземпляров, доступ к полям)
будет падать — это сознательный guard: новые кодовые пути не должны их
использовать.
"""


class _LegacyStub:
    """Базовый stub: при любой попытке создать экземпляр или обратиться
    к атрибуту — сообщает что класс недоступен."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            f"{self.__class__.__name__} — legacy stub из app.models. "
            f"В EDO_COMPLETE этот класс не используется. См. app/__init__.py"
        )


class BankOperation(_LegacyStub):
    """Stub: в EDO_COMPLETE используется modules.declaration_filler.BankOp."""


class OfdReceipt(_LegacyStub):
    """Stub: в EDO_COMPLETE чеки парсятся в dict через parse_ofd_bytes."""


class Project(_LegacyStub):
    """Stub: в EDO_COMPLETE нет понятия Project."""


class ClassificationRule(_LegacyStub):
    """Stub: в EDO_COMPLETE правила классификации зашиты в classifier.py."""


__all__ = ["BankOperation", "OfdReceipt", "Project", "ClassificationRule"]
