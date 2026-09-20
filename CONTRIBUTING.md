# Contributing to TTask

Thank you for contributing.

## Development setup

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run locally

```powershell
.\venv\Scripts\python.exe -m ttask
```

## Run tests

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Before submitting a pull request, add or update tests for behavior changes and
ensure the complete test suite passes. Keep pull requests focused and describe
the user-visible impact clearly.

## User-interface settings

Keep application-wide appearance preferences in the `app_settings` table through
`Database.get_setting()` and `Database.set_settings()`. Font-size values must pass
through `normalized_font_size()` before being applied. New user-facing text should
be written so it can be moved into the shared language resources rather than being
assembled from unrelated UI fragments.
