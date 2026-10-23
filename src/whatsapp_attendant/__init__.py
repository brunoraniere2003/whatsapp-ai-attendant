"""Pacote whatsapp-ai-attendant. Nome e descrição vêm do pyproject.toml (metadados)."""

from importlib.metadata import PackageNotFoundError, metadata

__version__ = "0.1.0"

try:
    _meta = metadata("whatsapp-ai-attendant")
    NOME = _meta["Name"]
    DESCRICAO = _meta.get("Summary", "")
except PackageNotFoundError:  # pragma: no cover
    NOME, DESCRICAO = "whatsapp-ai-attendant", ""
