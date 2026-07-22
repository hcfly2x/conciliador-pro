"""Ponto de entrada compatível para Flask, gunicorn e ferramentas legadas."""

from __future__ import annotations

import sys

from core import application


# Preserva `import app` como alias do modulo real. Isso mantem monkeypatches e
# integracoes antigas funcionando enquanto o codigo e dividido por dominio.
sys.modules[__name__] = application

if __name__ == "__main__":
    import os

    application.app.run(
        host=os.environ.get("HOST") or "127.0.0.1",
        port=int(os.environ.get("PORT") or "5061"),
        debug=False,
        use_reloader=False,
    )
