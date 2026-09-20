# Changelog

All notable changes to TTask are documented in this file.

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

