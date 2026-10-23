"""Static assets (CSS and JS) of the report and the demo console."""

from functools import cache
from importlib import resources


@cache
def asset(name: str) -> str:
    return resources.files(__name__).joinpath(name).read_text(encoding="utf-8")
