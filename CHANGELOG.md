# Changelog

All notable changes to TTask are documented in this file.

## [9.16.1] - 2026-09-20

### Added

- Appearance settings for system language, Simplified Chinese, and English.
- A persistent global font-size setting from 9 to 16 points, applied immediately.
- Theme, interface scale, table density, alternating-row, and layout reset options.
- Startup, tray, close-confirmation, layout restoration, task-selection, and run-confirmation preferences.
- Defaults for date rules, missed schedules, future preview size, failure disabling, resume checks, and task concurrency.
- SQLite backup, validated restore, log retention, diagnostics export, and database integrity checks.
- Holiday auto-update, year range, offline status, reset, import, and export controls.
- About page with project links, update checks, changelog, license, feedback, and support links.

### Changed

- Application styling is now generated from persisted appearance preferences at startup.
- Windows startup commands respect the background/tray preference.
- SQLite restore validates backups and uses the SQLite backup API for safe replacement.
- The six settings tabs now share the available width without overflow buttons.

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
