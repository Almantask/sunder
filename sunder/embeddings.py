"""Audio scanning, windowed CLAP embeddings, and on-disk cache."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from tqdm import tqdm

AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".ogg", ".oga"}
SKIP_DIR_NAMES = {
    ".git",
    ".sunder_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
MODEL_ID = "laion/larger_clap_music"
WINDOW_SECONDS = 10.0
N_WINDOWS = 3
TARGET_SR = 48_000
CACHE_VERSION = 1


class AudioLoadError(RuntimeError):
    """A track could not be decoded."""


def scan_audio(
    root: str | Path,
    *,
    recursive: bool = True,
    skip_dirs: set[str] | None = None,
) -> list[Path]:
    """Find supported audio files under *root*.

    Recursive by default: every nested folder is visited (playlists, liked
    songs, category folders, arbitrary depth). Only well-known tooling
    directories relative to the walk (``.git``, ``.venv``, ``.sunder_cache``,
    …) are skipped — a parent folder named ``organized`` will not hide the
    library.
    """
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Audio folder not found: {root}")
    skip = skip_dirs if skip_dirs is not None else SKIP_DIR_NAMES

    files: list[Path] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            dirnames[:] = [name for name in dirnames if name not in skip and not name.startswith(".")]
            folder = Path(dirpath)
            for name in filenames:
                path = folder / name
                if path.suffix.lower() in AUDIO_SUFFIXES:
                    files.append(path)
    else:
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES:
                files.append(path)

    files.sort()
    return files


def window_starts(n_frames: int, window_frames: int, n_windows: int = N_WINDOWS) -> list[int]:
    """Start/middle/end offsets; de-duplicated for short clips."""
    if n_frames <= 0:
        return [0]
    if n_frames <= window_frames or n_windows <= 1:
        return [0]
    last = n_frames - window_frames
    mid = last // 2
    starts = [0, mid, last]
    if n_windows != 3:
        starts = [int(round(i * last / (n_windows - 1))) for i in range(n_windows)]
    unique: list[int] = []
    for start in starts:
        start = max(0, min(start, last))
        if start not in unique:
            unique.append(start)
    return unique


def resample_mono(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    if orig_sr == target_sr or audio.size == 0:
        return audio
    n_out = max(1, int(round(audio.size * target_sr / orig_sr)))
    x_old = np.linspace(0.0, 1.0, audio.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def _to_mono(data: np.ndarray) -> np.ndarray:
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 1:
        return arr
    return arr.mean(axis=1 if arr.shape[-1] <= 8 else 0).astype(np.float32)


def load_windows(
    path: str | Path,
    window_seconds: float = WINDOW_SECONDS,
    n_windows: int = N_WINDOWS,
    target_sr: int = TARGET_SR,
) -> list[np.ndarray]:
    """Return 1–3 mono windows at *target_sr*, each ~window_seconds long."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".wav", ".flac", ".ogg", ".oga"}:
        try:
            return _load_windows_soundfile(path, window_seconds, n_windows, target_sr)
        except Exception:
            pass
    return _load_windows_full(path, window_seconds, n_windows, target_sr)


def _load_windows_soundfile(
    path: Path,
    window_seconds: float,
    n_windows: int,
    target_sr: int,
) -> list[np.ndarray]:
    import soundfile as sf

    info = sf.info(str(path))
    sr = int(info.samplerate)
    n_frames = int(info.frames)
    if sr <= 0 or n_frames <= 0:
        raise AudioLoadError(f"Empty or invalid audio: {path}")
    window_frames = max(1, int(round(window_seconds * sr)))
    starts = window_starts(n_frames, window_frames, n_windows)
    windows: list[np.ndarray] = []
    with sf.SoundFile(str(path)) as handle:
        for start in starts:
            handle.seek(min(start, max(0, n_frames - 1)))
            frames = handle.read(window_frames, dtype="float32", always_2d=True)
            if frames.size == 0:
                continue
            mono = _to_mono(frames)
            windows.append(resample_mono(mono, sr, target_sr))
    if not windows:
        raise AudioLoadError(f"No samples decoded: {path}")
    return windows


def _decode_full(path: Path) -> tuple[np.ndarray, int]:
    suffix = path.suffix.lower()
    if suffix in {".wav", ".flac", ".ogg", ".oga"}:
        try:
            import soundfile as sf

            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
            return _to_mono(data), int(sr)
        except Exception:
            pass
    if suffix == ".wav":
        try:
            return _decode_wave(path)
        except Exception:
            pass
    try:
        import miniaudio

        decoded = miniaudio.decode_file(str(path))
        samples = np.asarray(decoded.samples, dtype=np.float32)
        channels = int(decoded.nchannels)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        return samples.astype(np.float32), int(decoded.sample_rate)
    except Exception as exc:
        raise AudioLoadError(f"Could not decode {path}: {exc}") from exc


def _decode_wave(path: Path) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as handle:
        n_channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sr = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    if sample_width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sample_width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise AudioLoadError(f"Unsupported WAV sample width {sample_width}: {path}")
    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)
    return data.astype(np.float32), int(sr)


def _load_windows_full(
    path: Path,
    window_seconds: float,
    n_windows: int,
    target_sr: int,
) -> list[np.ndarray]:
    audio, sr = _decode_full(path)
    if audio.size == 0 or sr <= 0:
        raise AudioLoadError(f"Empty or invalid audio: {path}")
    window_frames = max(1, int(round(window_seconds * sr)))
    starts = window_starts(int(audio.size), window_frames, n_windows)
    windows: list[np.ndarray] = []
    for start in starts:
        chunk = audio[start : start + window_frames]
        if chunk.size == 0:
            continue
        windows.append(resample_mono(chunk, sr, target_sr))
    if not windows:
        raise AudioLoadError(f"No samples decoded: {path}")
    return windows


def file_cache_key(path: Path, size: int, mtime_ns: int) -> str:
    payload = f"{path.resolve()}|{size}|{mtime_ns}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class EmbeddingCache:
    """JSON index + one .npy embedding per track, keyed by path/size/mtime."""

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)
        self.emb_dir = self.cache_dir / "embeddings"
        self.index_path = self.cache_dir / "index.json"
        self._index: dict[str, Any] = {
            "version": CACHE_VERSION,
            "model": MODEL_ID,
            "window_seconds": WINDOW_SECONDS,
            "n_windows": N_WINDOWS,
            "target_sr": TARGET_SR,
            "audio_root": None,
            "entries": {},
        }
        self._load()

    def _load(self) -> None:
        if not self.index_path.is_file():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if isinstance(data, dict):
            self._index.update(data)
            self._index.setdefault("entries", {})

    def save(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.emb_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._index, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    @property
    def model_id(self) -> str:
        return str(self._index.get("model") or MODEL_ID)

    @property
    def audio_root(self) -> Path | None:
        raw = self._index.get("audio_root")
        return Path(raw) if raw else None

    def set_audio_root(self, root: str | Path) -> None:
        self._index["audio_root"] = str(Path(root).resolve())

    def entry_for(self, path: Path) -> dict[str, Any] | None:
        return self._index["entries"].get(str(path.resolve()))

    def is_current(self, path: Path) -> bool:
        path = path.resolve()
        try:
            stat = path.stat()
        except OSError:
            return False
        entry = self.entry_for(path)
        if not entry:
            return False
        if int(entry.get("size", -1)) != stat.st_size:
            return False
        if int(entry.get("mtime_ns", -1)) != stat.st_mtime_ns:
            return False
        npy = self.emb_dir / f"{entry['key']}.npy"
        return npy.is_file()

    def get(self, path: Path) -> np.ndarray | None:
        if not self.is_current(path):
            return None
        entry = self.entry_for(path.resolve())
        if not entry:
            return None
        npy = self.emb_dir / f"{entry['key']}.npy"
        return np.load(npy)

    def put(self, path: Path, embedding: np.ndarray) -> None:
        path = path.resolve()
        stat = path.stat()
        key = file_cache_key(path, stat.st_size, stat.st_mtime_ns)
        self.emb_dir.mkdir(parents=True, exist_ok=True)
        np.save(self.emb_dir / f"{key}.npy", np.asarray(embedding, dtype=np.float32))
        self._index["entries"][str(path)] = {
            "key": key,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    def refresh_stat(self, path: Path) -> None:
        """Keep the cached embedding after metadata-only file changes (ID3 tags)."""
        path = path.resolve()
        entry = self.entry_for(path)
        if not entry:
            return
        try:
            stat = path.stat()
        except OSError:
            return
        old_key = entry.get("key")
        new_key = file_cache_key(path, stat.st_size, stat.st_mtime_ns)
        old_npy = self.emb_dir / f"{old_key}.npy"
        new_npy = self.emb_dir / f"{new_key}.npy"
        if old_key != new_key and old_npy.is_file():
            if new_npy.is_file() and new_npy.resolve() != old_npy.resolve():
                new_npy.unlink()
            old_npy.replace(new_npy)
        self._index["entries"][str(path)] = {
            "key": new_key,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    def items(self) -> list[tuple[Path, np.ndarray]]:
        out: list[tuple[Path, np.ndarray]] = []
        missing: list[str] = []
        for raw_path, entry in self._index["entries"].items():
            path = Path(raw_path)
            if not path.is_file():
                missing.append(raw_path)
                continue
            npy = self.emb_dir / f"{entry['key']}.npy"
            if not npy.is_file():
                missing.append(raw_path)
                continue
            out.append((path, np.load(npy)))
        for key in missing:
            self._index["entries"].pop(key, None)
        return out

    def __len__(self) -> int:
        return len(self._index.get("entries", {}))


def pick_device(requested: str | None = None) -> str:
    if requested:
        return requested
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


class ClapEmbedder:
    """Lazy Hugging Face CLAP wrapper for audio and text."""

    def __init__(self, model_id: str = MODEL_ID, device: str | None = None):
        self.model_id = model_id
        self.device = pick_device(device)
        self.model = None
        self.processor = None
        self.logit_scale = 14.0

    def load(self) -> None:
        if self.model is not None:
            return
        import torch
        from transformers import ClapModel, ClapProcessor

        print(f"Loading {self.model_id} on {self.device}...", flush=True)
        t0 = time.perf_counter()
        self.processor = ClapProcessor.from_pretrained(self.model_id)
        self.model = ClapModel.from_pretrained(self.model_id)
        self.model.to(self.device)
        self.model.eval()
        scale = getattr(self.model, "logit_scale", None)
        if scale is not None:
            self.logit_scale = float(scale.exp().detach().cpu().item())
        print(f"Model ready in {time.perf_counter() - t0:.1f}s", flush=True)

    def _move_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        import torch

        moved = {}
        for key, value in inputs.items():
            if torch.is_tensor(value):
                moved[key] = value.to(self.device)
            else:
                moved[key] = value
        return moved

    def encode_audio_windows(self, windows: Sequence[np.ndarray]) -> np.ndarray:
        self.load()
        import torch
        import torch.nn.functional as F

        arrays = [np.asarray(window, dtype=np.float32) for window in windows]
        try:
            inputs = self.processor(
                audios=arrays,
                sampling_rate=TARGET_SR,
                return_tensors="pt",
                padding=True,
            )
        except TypeError:
            inputs = self.processor(
                audio=arrays,
                sampling_rate=TARGET_SR,
                return_tensors="pt",
                padding=True,
            )
        with torch.inference_mode():
            features = self.model.get_audio_features(**self._move_inputs(inputs))
            features = F.normalize(features, dim=-1)
            pooled = F.normalize(features.mean(dim=0), dim=0)
        return pooled.detach().cpu().numpy().astype(np.float32)

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        self.load()
        import torch
        import torch.nn.functional as F

        inputs = self.processor(
            text=list(texts),
            return_tensors="pt",
            padding=True,
        )
        with torch.inference_mode():
            features = self.model.get_text_features(**self._move_inputs(inputs))
            features = F.normalize(features, dim=-1)
        return features.detach().cpu().numpy().astype(np.float32)


def embed_library(
    audio_root: str | Path,
    cache_dir: str | Path,
    *,
    limit: int | None = None,
    force: bool = False,
    device: str | None = None,
    model_id: str = MODEL_ID,
    recursive: bool = True,
) -> EmbeddingCache:
    files = scan_audio(audio_root, recursive=recursive)
    if limit is not None:
        files = files[: max(0, limit)]
    cache = EmbeddingCache(cache_dir)
    cache.set_audio_root(audio_root)
    cache._index["model"] = model_id
    cache._index["recursive"] = recursive

    pending = [path for path in files if force or not cache.is_current(path)]
    skipped = len(files) - len(pending)
    scope = "recursively" if recursive else "in the top folder only"
    print(
        f"Found {len(files)} tracks {scope} ({skipped} cached, {len(pending)} to embed)",
        flush=True,
    )

    if pending:
        embedder = ClapEmbedder(model_id=model_id, device=device)
        embedder.load()
        errors = 0
        for path in tqdm(pending, desc="Embedding", unit="track"):
            try:
                windows = load_windows(path)
                vector = embedder.encode_audio_windows(windows)
                cache.put(path, vector)
            except Exception as exc:
                errors += 1
                tqdm.write(f"SKIP {path.name}: {exc}")
        cache.save()
        print(f"Cache saved ({errors} failed)", flush=True)
    else:
        cache.save()
        print("Nothing new to embed.", flush=True)
    return cache
