# QGIS Plugin Upload Guide

This repository is prepared so the QGIS plugin ZIP can be built locally or by GitHub Actions.

## Before Uploading

1. Update `version` in `metadata.txt`.
2. Update `CHANGELOG.md`.
3. Confirm `homepage` and `repository` in `metadata.txt`.
4. Build and validate the ZIP.

## Build Locally

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_plugin_zip.ps1
powershell -ExecutionPolicy Bypass -File tools\validate_plugin_zip.ps1
```

The upload ZIP is created at:

```text
dist/koji_DataQuery.zip
```

## Build With GitHub Actions

Use the `Build Plugin ZIP` workflow.

The workflow uploads `koji_DataQuery_plugin_zip` as an artifact. Download the artifact and upload the contained ZIP to the QGIS plugin site.

## Publish a GitHub Release

Use the `VirusTotal Check and Release` workflow.

Required repository secret:

```text
VIRUSTOTAL_API_KEY
```

The workflow builds `dist/koji_DataQuery.zip`, checks it with VirusTotal, and attaches it to a GitHub Release.

## ZIP Requirements Checked

- Top-level folder is `koji_DataQuery/`.
- Required files are present:
  - `metadata.txt`
  - `__init__.py`
  - `koji_DataQuery.py`
  - `icon.png`
- ZIP entries use `/`, not backslashes.
- Development files such as `.git`, `.github`, `tools`, `dist`, `__pycache__`, `.pyc`, and `.pyo` are not included.

