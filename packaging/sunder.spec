# -*- mode: python ; coding: utf-8 -*-
"""Thin double-click launcher (does not bundle PyTorch)."""

from pathlib import Path

SPECDIR = Path(SPECPATH).resolve()
ICON = SPECDIR / "sunder.ico"

a = Analysis(
    [str(SPECDIR / "launcher.py")],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "sunder",
        "torch",
        "torchvision",
        "torchaudio",
        "transformers",
        "numpy",
        "PIL",
        "cv2",
        "pandas",
        "scipy",
        "sklearn",
        "tensorflow",
        "webview",
        "pythonnet",
        "mutagen",
        "soundfile",
        "miniaudio",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Sunder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.is_file() else None,
)
