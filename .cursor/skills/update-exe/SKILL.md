---
name: update-exe
description: Rebuilds the thin Sunder.exe launcher after repo changes so the double-click app stays current (icon, launcher, copy next to .venv). Use after finishing implementation work, when packaging or the desktop app changed, or when the user mentions exe, Sunder.exe, build_exe, or PyInstaller.
---

# Update exe

Rebuild the **thin launcher** after each completed change. It does not bundle PyTorch; it starts this repo's `.venv`. Keep `Sunder.exe` next to `.venv`.

## When

- After you finish writing or editing files for the user's request
- After icon, packaging, launcher, or desktop UI work
- When the user asks to update/rebuild the exe

Do not use `-Standalone` unless they asked for the portable CUDA bundle (~15 GB).

## Build

From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
```

That script installs `requirements-build.txt`, regenerates `packaging/sunder.ico`, runs PyInstaller with `packaging/sunder.spec`, and copies `dist/Sunder.exe` to `Sunder.exe` at the repo root.

## Verify

- Command exits 0
- `Sunder.exe` and `dist/Sunder.exe` exist and have a fresh timestamp
- If copy fails because the exe is running, tell the user to quit Sunder and rerun the same command

## Skip

Skip only if you made no file changes, or the user said not to build.
