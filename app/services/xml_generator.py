"""
Stub для legacy `from app.services import xml_generator`.

В EDO_COMPLETE XML-генерация не нужна — генерируется PDF.
"""
def __getattr__(name):
    raise AttributeError(
        f"app.services.xml_generator.{name} недоступен в EDO_COMPLETE."
    )
