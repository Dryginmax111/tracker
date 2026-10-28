#!/usr/bin/env python3
"""make_patches.py — DEPRECATED stub.

Оригинал был повреждён при применении audit-fix-02-make-patches-keys
(или v1.0.3-big-bundle): регулярка `\\{'op': '` задела triple-quote
внутри v1.1.8-блока _page_html.

ВАЖНО: make_patches.py — dev-tool для ГЕНЕРАЦИИ патчей.
В рантайме не участвует. Всё, что он генерировал, уже применено.

Восстановить оригинал:
    скопируйте make_patches.py.broken_<timestamp>.py
    -> переименуйте в make_patches.py
"""
import sys

print('make_patches.py: DEPRECATED (dev-tool, все патчи уже применены)', file=sys.stderr)
sys.exit(0)
