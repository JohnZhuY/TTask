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

