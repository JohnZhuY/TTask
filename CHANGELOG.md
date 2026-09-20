# Changelog

All notable changes to TTask are documented in this file.

## [Unreleased]

### Added

- Appearance settings for system language, Simplified Chinese, and English.
- A persistent global font-size setting from 9 to 16 pixels, applied immediately.

### Changed

- Application styling is now generated from persisted appearance preferences at startup.

## [9.16.0] - 2026-09-20

### Added

- Fixed-time, random-window, one-time, and interval schedules.
- Multiple daily time points and random time windows.
- Weekday, official workday, holiday, and manual date rules.
- Command, notification, file, HTTP, copy, and move actions.
- Modern PySide6 interface, system tray support, execution history, and future
  schedule preview.
- Retry handling, automatic disabling after repeated failures, missed-schedule
  policies, and scheduler recovery.

### Changed

- Missed schedules now default to being skipped.
- SQLite now uses WAL mode and busy waiting for improved concurrency.
