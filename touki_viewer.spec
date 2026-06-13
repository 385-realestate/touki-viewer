# -*- mode: python ; coding: utf-8 -*-
"""
登記簿ビューアー PyInstaller spec
tk_data / tcl_data を明示的にバンドル
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

PYTHON_DIR = Path(sys.executable).parent
TCL_DIR    = PYTHON_DIR / 'tcl'
TK_PATH    = TCL_DIR / 'tk8.6'
TCL_PATH   = TCL_DIR / 'tcl8.6'

datas = [
    # tkinter データ（これが欠けているとエラーになる）
    (str(TK_PATH),  'tk_data'),
    (str(TCL_PATH), 'tcl_data'),
    # サードパーティ GUI ライブラリ
    *collect_data_files('customtkinter'),
    *collect_data_files('tkinterdnd2'),
    # アプリ独自モジュール
    ('scripts', 'scripts'),
    ('ui',      'ui'),
]

binaries = [
    *collect_dynamic_libs('tkinterdnd2'),
]

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=['.', 'scripts'],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'customtkinter',
        'tkinterdnd2',
        'pdfplumber',
        'pdfminer',
        'pdfminer.high_level',
        'pdfminer.layout',
        'sqlite3',
        'agents.tochi_agent',
        'agents.tatemono_agent',
        'agents.base_agent',
        'touki_parser',
        'db_writer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='touki_viewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUIアプリのためコンソール非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='touki_viewer',
)
