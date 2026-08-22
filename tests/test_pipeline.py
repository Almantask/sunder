from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from sunder.classify import (
    Classification,
    apply_human_overrides,
    classify_embeddings,
    read_results_csv,
    score_track,
    write_results_csv,
)
from sunder.config import load_categories, normalize_categories
from sunder.embeddings import (
    EmbeddingCache,
    load_windows,
    resample_mono,
    scan_audio,
    window_starts,
)
from sunder.organize import organize_rows, safe_folder_name
from sunder.report import render_report, write_report
from sunder.cli import main as cli_main


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


class ConfigTests(unittest.TestCase):
    def test_normalize_mapping_and_wrapper(self) -> None:
        mapping = normalize_categories(
            {"rain": ["rain ambience", "thunder"], "drone": "dark drone"}
        )
        self.assertEqual(mapping["rain"], ["rain ambience", "thunder"])
        self.assertEqual(mapping["drone"], ["dark drone"])

        wrapped = normalize_categories({"categories": ["ocean", "night"]})
        self.assertEqual(wrapped["ocean"], ["ocean"])

    def test_load_categories_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "categories.yaml"
            path.write_text("forest:\n  - birds in trees\n", encoding="utf-8")
            loaded = load_categories(path)
            self.assertEqual(loaded["forest"], ["birds in trees"])


class ScanAndAudioTests(unittest.TestCase):
    def test_scan_nested_playlists_and_skips_tooling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "keep.wav").write_bytes(b"x")
            (root / "skip.txt").write_text("nope", encoding="utf-8")
            nested = root / "Playlists" / "Forest I"
            nested.mkdir(parents=True)
            (nested / "deep.wav").write_bytes(b"x")
            deeper = root / "Playlists" / "Boss" / "III"
            deeper.mkdir(parents=True)
            (deeper / "boss.mp3").write_bytes(b"x")
            venv_dir = root / ".venv" / "lib"
            venv_dir.mkdir(parents=True)
            (venv_dir / "hidden.wav").write_bytes(b"x")
            found = scan_audio(root)
            names = {path.name for path in found}
            self.assertIn("keep.wav", names)
            self.assertIn("deep.wav", names)
            self.assertIn("boss.mp3", names)
            self.assertNotIn("hidden.wav", names)
            self.assertNotIn("skip.txt", names)
            top_only = scan_audio(root, recursive=False)
            top_names = {path.name for path in top_only}
            self.assertEqual(top_names, {"keep.wav"})

    def test_window_starts_short_and_long(self) -> None:
        self.assertEqual(window_starts(100, 200), [0])
        starts = window_starts(1000, 100)
        self.assertEqual(starts[0], 0)
        self.assertEqual(starts[-1], 900)
        self.assertEqual(len(starts), 3)

    def test_resample_and_load_windows(self) -> None:
        stretched = resample_mono(np.ones(10, dtype=np.float32), 10, 20)
        self.assertEqual(stretched.size, 20)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tone.wav"
            write_sine_wav(path, seconds=1.5, sr=8000)
            windows = load_windows(path, window_seconds=0.4, n_windows=3, target_sr=16000)
            self.assertGreaterEqual(len(windows), 1)
            self.assertTrue(all(window.dtype == np.float32 for window in windows))


class CacheAndClassifyTests(unittest.TestCase):
    def test_cache_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav = root / "a.wav"
            write_sine_wav(wav)
            cache = EmbeddingCache(root / "cache")
            vector = np.array([0.0, 1.0, 0.0], dtype=np.float32)
            cache.put(wav, vector)
            cache.save()
            again = EmbeddingCache(root / "cache")
            loaded = again.get(wav)
            self.assertIsNotNone(loaded)
            np.testing.assert_array_almost_equal(loaded, vector)

    def test_score_and_csv(self) -> None:
        categories = {"rain": ["rain"], "drone": ["drone"]}
        prompt_embs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        audio = np.array([0.9, 0.1], dtype=np.float32)
        category, confidence, score, runner, runner_score, prompt = score_track(
            audio,
            prompt_embs,
            ["rain", "drone"],
            ["rain", "drone"],
            ["rain", "drone"],
            logit_scale=14.0,
        )
        self.assertEqual(category, "rain")
        self.assertGreater(confidence, 0.5)
        self.assertGreater(score, runner_score)
        self.assertEqual(prompt, "rain")

        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "x.wav"
            write_sine_wav(wav)
            items = [(wav, audio)]
            rows = classify_embeddings(items, categories, prompt_embs, logit_scale=14.0)
            csv_path = Path(tmp) / "results.csv"
            write_results_csv(csv_path, rows)
            loaded = read_results_csv(csv_path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].category, "rain")
            self.assertEqual(loaded[0].review, "pending")
            self.assertEqual(loaded[0].suggested_category, "rain")

    def test_review_overrides_and_legacy_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "x.wav"
            write_sine_wav(wav)
            previous = Path(tmp) / "results.csv"
            write_results_csv(
                previous,
                [
                    Classification(
                        path=wav,
                        category="swamp",
                        confidence=0.4,
                        score=0.2,
                        runner_up="rain",
                        runner_up_score=0.1,
                        margin=0.1,
                        low_confidence=False,
                        matched_prompt="rain",
                        suggested_category="rain",
                        review="accepted",
                        comment="more bog than rain",
                    )
                ],
            )
            fresh = [
                Classification(
                    path=wav,
                    category="rain",
                    confidence=0.9,
                    score=0.4,
                    runner_up="drone",
                    runner_up_score=0.1,
                    margin=0.3,
                    low_confidence=False,
                    matched_prompt="rain",
                    suggested_category="rain",
                )
            ]
            apply_human_overrides(fresh, previous)
            self.assertEqual(fresh[0].category, "swamp")
            self.assertEqual(fresh[0].review, "accepted")
            self.assertEqual(fresh[0].comment, "more bog than rain")
            self.assertEqual(fresh[0].suggested_category, "rain")

            legacy = Path(tmp) / "old.csv"
            legacy.write_text(
                "path,filename,category,confidence,score,runner_up,runner_up_score,margin,low_confidence,matched_prompt\n"
                f"{wav},x.wav,rain,0.500000,0.200000,drone,0.100000,0.100000,false,rain\n",
                encoding="utf-8",
            )
            loaded = read_results_csv(legacy)
            self.assertEqual(loaded[0].review, "pending")
            self.assertEqual(loaded[0].suggested_category, "rain")


class OrganizeAndReportTests(unittest.TestCase):
    def test_safe_folder_and_copy(self) -> None:
        self.assertEqual(safe_folder_name('rain/forest'), "rain_forest")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "track.wav"
            write_sine_wav(src)
            dest = root / "out"
            rows = [
                Classification(
                    path=src,
                    category="rain",
                    confidence=0.9,
                    score=0.4,
                    runner_up="ocean",
                    runner_up_score=0.1,
                    margin=0.3,
                    low_confidence=False,
                    matched_prompt="rain",
                )
            ]
            copied, skipped, missing = organize_rows(rows, dest, mode="copy")
            self.assertEqual((copied, skipped, missing), (1, 0, 0))
            self.assertTrue((dest / "rain" / "track.wav").is_file())
            self.assertTrue(src.is_file())

    def test_organize_skips_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "track.wav"
            write_sine_wav(src)
            dest = root / "out"
            rows = [
                Classification(
                    path=src,
                    category="rain",
                    confidence=0.9,
                    score=0.4,
                    runner_up="ocean",
                    runner_up_score=0.1,
                    margin=0.3,
                    low_confidence=False,
                    matched_prompt="rain",
                    review="rejected",
                    comment="not this folder",
                )
            ]
            copied, skipped, missing = organize_rows(rows, dest, mode="copy")
            self.assertEqual((copied, skipped, missing), (0, 1, 0))
            self.assertFalse((dest / "rain" / "track.wav").exists())

    def test_copy_stops_when_cancelled(self) -> None:
        from sunder.progress import Cancelled

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "track.wav"
            write_sine_wav(src)
            dest = root / "out"
            rows = [
                Classification(
                    path=src,
                    category="rain",
                    confidence=0.9,
                    score=0.4,
                    runner_up="ocean",
                    runner_up_score=0.1,
                    margin=0.3,
                    low_confidence=False,
                    matched_prompt="rain",
                )
            ]
            with self.assertRaises(Cancelled):
                organize_rows(rows, dest, mode="copy", should_cancel=lambda: True)
            self.assertFalse((dest / "rain" / "track.wav").exists())

    def test_report_contains_players_and_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "storm.wav"
            write_sine_wav(wav)
            rows = [
                Classification(
                    path=wav,
                    category="rain",
                    confidence=0.2,
                    score=0.11,
                    runner_up="ocean",
                    runner_up_score=0.10,
                    margin=0.01,
                    low_confidence=True,
                    matched_prompt="rain ambience",
                )
            ]
            html_doc = render_report(rows, Path(tmp) / "report.html")
            self.assertIn("Needs review", html_doc)
            self.assertIn("<audio", html_doc)
            self.assertIn("storm.wav", html_doc)
            csv_path = Path(tmp) / "results.csv"
            write_results_csv(csv_path, rows)
            out = Path(tmp) / "report.html"
            self.assertEqual(cli_main(["report", "--results", str(csv_path), "--out", str(out)]), 0)
            self.assertTrue(out.is_file())
            write_report(csv_path, out)


class TagTests(unittest.TestCase):
    def test_wav_genre_and_sunder_frames(self) -> None:
        from sunder.tags import read_category_tags, write_category_tags

        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "cue.wav"
            write_sine_wav(wav)
            write_category_tags(
                wav,
                "boss",
                confidence=0.61,
                matched_prompt="dark orchestral boss fight music",
            )
            tags = read_category_tags(wav)
            self.assertEqual(tags.get("genre"), "boss")
            self.assertEqual(tags.get("sunder_category"), "boss")
            self.assertEqual(tags.get("sunder_confidence"), "0.610000")
            self.assertEqual(tags.get("sunder_prompt"), "dark orchestral boss fight music")

    def test_tag_cli_and_cache_refresh(self) -> None:
        from sunder.tags import read_category_tags, tag_rows

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav = root / "cue.wav"
            write_sine_wav(wav)
            cache = EmbeddingCache(root / "cache")
            cache.put(wav, np.array([1.0, 0.0], dtype=np.float32))
            cache.save()
            self.assertTrue(cache.is_current(wav))
            rows = [
                Classification(
                    path=wav,
                    category="forest",
                    confidence=0.8,
                    score=0.4,
                    runner_up="night",
                    runner_up_score=0.1,
                    margin=0.3,
                    low_confidence=False,
                    matched_prompt="green woodland forest ambience",
                )
            ]
            csv_path = root / "results.csv"
            write_results_csv(csv_path, rows)
            self.assertEqual(
                cli_main(["tag", "--results", str(csv_path), "--cache", str(root / "cache")]),
                0,
            )
            tags = read_category_tags(wav)
            self.assertEqual(tags.get("sunder_category"), "forest")
            refreshed = EmbeddingCache(root / "cache")
            self.assertTrue(refreshed.is_current(wav))
            written, errors = tag_rows(rows, cache=refreshed)
            self.assertEqual((written, errors), (1, 0))


class ClassifyDestinationTests(unittest.TestCase):
    def _parse(self, *flags: str):
        from sunder.cli import build_parser, classify_destinations

        args = build_parser().parse_args(["classify", *flags])
        return classify_destinations(args)

    def test_save_file_and_embed_track(self) -> None:
        self.assertEqual(self._parse("--save-file"), (True, False))
        self.assertEqual(self._parse("--embed-track"), (False, True))
        self.assertEqual(self._parse("--save-file", "--embed-track"), (True, True))

    def test_requires_at_least_one_flag(self) -> None:
        with self.assertRaises(ValueError):
            self._parse()


class CliHelpTests(unittest.TestCase):
    def test_help_exits_zero(self) -> None:
        from io import StringIO
        from unittest.mock import patch

        with patch("sys.stdout", new=StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli_main(["--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_app_help_exits_zero(self) -> None:
        from io import StringIO
        from unittest.mock import patch

        with patch("sys.stdout", new=StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli_main(["app", "--help"])
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
