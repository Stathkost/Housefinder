# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Housefinder desktop app.
Build:  pyinstaller app.spec
Output: dist/Housefinder/   (one-dir, fastest startup)
"""

import sys, os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ── Hidden imports ────────────────────────────────────────────────────────────
hidden = [
    # pywebview platform backends
    "webview.platforms.gtk",
    "webview.platforms.winforms",
    "webview.platforms.cocoa",
    "webview.platforms.edgechromium",
    # Flask internals
    "flask", "flask.json.provider", "jinja2", "werkzeug",
    # dotenv
    "dotenv",
    # other
    "pkg_resources", "psutil", "colorama", "requests",
    "playwright", "playwright.sync_api",
]

datas = [
    ("assets",      "assets"),
    ("example.env", "."),
]

# Collect pywebview data files (JS bridges etc.)
try:
    datas += collect_data_files("webview")
except Exception:
    pass

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Housefinder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,              # no terminal window on Windows/Mac
    icon="assets/logo.png",    # Windows uses .ico; PNG accepted on Linux/Mac
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="Housefinder",
)
