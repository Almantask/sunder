from __future__ import annotations

import json
import math
import os
import struct
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sunder.desktop.media import is_allowed_media, parse_range
from sunder.desktop.server import make_server
from sunder.desktop.settings import load_settings, save_settings
from sunder.progress import Cancelled, check_cancel


def write_sine_wav(path: Path, freq: float = 440.0, seconds: float = 1.2, sr: int = 16000) -> None:
    n_frames = int(sr * seconds)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        frames = bytearray()
        for index in range(n_frames):
            sample = int(8000 * math.sin(2 * math.pi * freq * index / sr))
            frames.extend(struct.pack("<h", sample))
        handle.writeframes(bytes(frames))


class ProgressTests(unittest.TestCase):
    def test_check_cancel(self) -> None:
        check_cancel(None)
        check_cancel(lambda: False)
        with self.assertRaises(Cancelled):
            check_cancel(lambda: True)


class RangeTests(unittest.TestCase):
    def test_parse_range(self) -> None:
        self.assertIsNone(parse_range(None, 100))
        self.assertEqual(parse_range("bytes=0-9", 100), (0, 9))
        self.assertEqual(parse_range("bytes=50-", 100), (50, 99))
        self.assertEqual(parse_range("bytes=-10", 100), (90, 99))
        self.assertIsNone(parse_range("bytes=100-110", 100))
        self.assertIsNone(parse_range("bytes=20-10", 100))


class SettingsTests(unittest.TestCase):
    def test_roundtrip_and_clean(self) -> None:
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                saved = save_settings(
                    {
                        "library": r"D:\tracks",
                        "device": "CUDA",
                        "limit": "",
                        "threshold": 0.4,
                        "save_file": False,
                    }
                )
                self.assertEqual(saved["library"], r"D:\tracks")
                self.assertEqual(saved["device"], "cuda")
                self.assertIsNone(saved["limit"])
                self.assertEqual(saved["threshold"], 0.4)
                self.assertFalse(saved["save_file"])
                loaded = load_settings()
                self.assertEqual(loaded["library"], r"D:\tracks")
            finally:
                os.chdir(old)


class MediaAllowTests(unittest.TestCase):
    def test_only_audio_under_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav = root / "ok.wav"
            write_sine_wav(wav)
            outside = Path(tmp).parent / "no.wav"
            self.assertTrue(is_allowed_media(wav, [root]))
            self.assertFalse(is_allowed_media(root / "notes.txt", [root]))
            extra = {wav}
            nested = root / "deep"
            nested.mkdir()
            other = nested / "b.wav"
            write_sine_wav(other)
            self.assertTrue(is_allowed_media(other, [root]))
            self.assertTrue(is_allowed_media(wav, [], extra_files=extra))
            self.assertFalse(is_allowed_media(outside, [root], extra_files=extra))


class DesktopHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.httpd = make_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        os.chdir(self._old)
        self._tmp.cleanup()

    def _json(self, path: str, method: str = "GET", body=None, headers=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urlopen(req, timeout=5) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw.decode("utf-8")) if raw else {}, dict(resp.headers)
        except HTTPError as exc:
            raw = exc.read()
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            return exc.code, payload, dict(exc.headers)

    def test_index_and_bootstrap(self) -> None:
        req = Request(self.base + "/")
        with urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8")
            self.assertIn("Sunder", html)
            self.assertIn("Embed library", html)
        status, payload, _ = self._json("/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertIn("settings", payload)
        self.assertIn("version", payload)

    def test_move_requires_confirm(self) -> None:
        status, payload, _ = self._json(
            "/api/organize",
            "POST",
            {"mode": "move", "confirm_move": False, "organize_dest": "organized"},
        )
        self.assertEqual(status, 400)
        self.assertIn("Move", payload.get("error", ""))

    def test_media_range_inside_library(self) -> None:
        wav = Path("tone.wav")
        write_sine_wav(wav)
        save_settings({"library": str(Path.cwd())})
        url = self.base + "/media?p=" + quote(str(wav.resolve()), safe="")
        req = Request(url, headers={"Range": "bytes=0-15"})
        with urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 206)
            self.assertEqual(resp.headers.get("Content-Type"), "audio/wav")
            data = resp.read()
            self.assertEqual(len(data), 16)

    def test_media_rejects_outside(self) -> None:
        status, payload, _ = self._json("/media?p=" + quote(str(Path.cwd() / "missing.wav"), safe=""))
        self.assertIn(status, {400, 403})
        self.assertIn("error", payload)

    def test_invalid_categories_not_written(self) -> None:
        Path("categories.yaml").write_text("forest:\n  - trees\n", encoding="utf-8")
        status, payload, _ = self._json("/api/categories", "PUT", {"yaml": "this: [unterminated"})
        self.assertEqual(status, 400)
        self.assertTrue(Path("categories.yaml").read_text(encoding="utf-8").startswith("forest:"))
        self.assertIn("error", payload)


class RuntimeAndLauncherTests(unittest.TestCase):
    def test_static_dir(self) -> None:
        from sunder.desktop.runtime import is_frozen, static_dir

        self.assertFalse(is_frozen())
        self.assertTrue((static_dir() / "index.html").is_file())

    def test_seed_defaults(self) -> None:
        from sunder.desktop.runtime import seed_defaults

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            seed_defaults(home)
            self.assertTrue((home / "categories.yaml").is_file())
            self.assertIn("forest:", (home / "categories.yaml").read_text(encoding="utf-8"))

    def test_print_tee_none_stream(self) -> None:
        from sunder.desktop.jobs import _PrintTee

        lines: list[str] = []
        tee = _PrintTee(lines.append, None)
        tee.write("hello\nworld\n")
        tee.flush()
        self.assertEqual(lines, ["hello", "world"])

    def test_find_project_root(self) -> None:
        import importlib.util

        launcher_path = Path(__file__).resolve().parents[1] / "packaging" / "launcher.py"
        spec = importlib.util.spec_from_file_location("sunder_launcher", launcher_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sunder").mkdir()
            (root / "sunder" / "__init__.py").write_text("", encoding="utf-8")
            scripts = root / ".venv" / "Scripts"
            scripts.mkdir(parents=True)
            (scripts / "python.exe").write_bytes(b"")
            nested = root / "dist"
            nested.mkdir()
            self.assertEqual(module.find_project_root(nested), root)
            self.assertIsNone(module.find_project_root(Path(tmp).parent))


if __name__ == "__main__":
    unittest.main()
