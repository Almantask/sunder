# -*- mode: python ; coding: utf-8 -*-
"""Full onedir bundle. Needs ~15 GB free with CUDA PyTorch. Prefer the thin launcher."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

SPECDIR = Path(SPECPATH).resolve()
ROOT = SPECDIR.parent
ICON = SPECDIR / "sunder.ico"

datas = [
    (str(ROOT / "sunder" / "desktop" / "static"), "sunder/desktop/static"),
    (str(ROOT / "categories.yaml"), "."),
]
binaries = []
hiddenimports = [
    "sunder",
    "sunder.desktop",
    "sunder.desktop.server",
    "sunder.desktop.jobs",
    "sunder.desktop.frozen_main",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "mutagen.id3",
    "mutagen.mp3",
    "mutagen.flac",
    "mutagen.wave",
    "mutagen.oggvorbis",
    "miniaudio",
    "soundfile",
    "yaml",
    "tqdm",
    "transformers.models.clap",
]

for pkg in (
    "torch",
    "transformers",
    "tokenizers",
    "huggingface_hub",
    "safetensors",
    "webview",
    "pythonnet",
    "certifi",
    "soundfile",
    "miniaudio",
    "mutagen",
):
    try:
        pkg_datas, pkg_bins, pkg_hidden = collect_all(pkg)
    except Exception:
        continue
    datas += pkg_datas
    binaries += pkg_bins
    hiddenimports += pkg_hidden

for pkg in (
    "torch",
    "transformers",
    "huggingface_hub",
    "safetensors",
    "tokenizers",
    "numpy",
    "tqdm",
    "regex",
    "requests",
    "packaging",
    "filelock",
    "pyyaml",
    "certifi",
):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

excludes = [
    "tensorflow",
    "tensorboard",
    "flax",
    "jax",
    "jaxlib",
    "keras",
    "IPython",
    "notebook",
    "pytest",
    "matplotlib",
]

a = Analysis(
    [str(ROOT / "sunder" / "desktop" / "frozen_main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SPECDIR / "rthook.py")],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Sunder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON) if ICON.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Sunder",
)
