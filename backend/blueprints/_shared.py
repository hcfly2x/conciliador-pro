from __future__ import annotations

from typing import Any, Callable


def allow_collab_write(view: Callable[..., Any]):
    view._allow_collab_write = True
    return view


def call_handler(name: str, **kwargs):
    from core import application

    return getattr(application, name)(**kwargs)
