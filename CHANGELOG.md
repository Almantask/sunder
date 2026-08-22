# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-08-23

Review is now a decision queue, not only a filter. The job console stays
docked on the right so Settings and other tabs can scroll without covering it.

### Added

- Accept, reject, or type a custom category on each Review track, with an
  optional comment. `A` accepts and `R` rejects.
- Queue chips: **To review**, **Reviewed**, and **All**.
- Decisions, comments, and custom categories survive re-classify. The model
  suggestion is kept as `suggested_category`.
- HTML report shows accepted/rejected flags and comments.
- Organize skips rejected tracks and uses the category you accepted.

### Changed

- Settings is options-only. Classify and tag from CSV run from Library
  (**Full analysis**) and the stamp-tags checkbox, not extra Settings buttons.
- `results.csv` gains `suggested_category`, `review`, and `comment` columns.
  Older CSVs still load (those tracks start as pending).

### Fixed

- Play/pause in the player (and the Review row button) now follows actual
  playback instead of sticking on the play icon.
- The job console no longer slides off-screen when a tab is wide or tall.
  Tab content scrolls in the main pane; the console width stays fixed.

## [0.2.0] - 2026-08-22

Desktop app with a thin `Sunder.exe` launcher, Library / Categories / Review /
Settings tabs, in-app playback, and background jobs for embed, classify,
report, and organize.

## [0.1.0] - 2026-08-22

CLI categorizer (`embed`, `classify`, `report`, `organize`, `tag`) plus the
Suno downloader and D&D prompt library.

[0.3.0]: https://github.com/Almantask/sunder/releases/tag/v0.3.0
