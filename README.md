# koji_DataQuery

koji DataQuery is a QGIS 3 plugin for CSV and GeoPackage data preparation workflows.
It aims to become a Power Query-like toolset for QGIS.

- Website: https://www.arinobu.org/koji_DataQuery.html
- Repository: https://github.com/Code4Construct/koji_DataQuery

## Features

- CSV cleanup and preprocessing
- GeoPackage cleanup and preprocessing
- CSV aggregation queries
- CSV LEFT JOIN and UNION workflows
- GeoPackage LEFT JOIN and UNION workflows
- Project-based preset/config storage under `<project name>_KDQconfig`

## Installation

Place this folder under the QGIS profile plugin directory:

```text
QGIS3/profiles/default/python/plugins/koji_DataQuery
```

Then restart QGIS or reload the plugin from the QGIS Plugin Manager.

## Build Plugin ZIP

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_plugin_zip.ps1
powershell -ExecutionPolicy Bypass -File tools\validate_plugin_zip.ps1
```

The QGIS upload ZIP is created at `dist/koji_DataQuery.zip`.

For release steps, see `QGIS_PLUGIN_UPLOAD.md`.

## QGIS Plugin Entry Points

- Plugin metadata: `metadata.txt`
- Plugin factory: `__init__.py`
- Main plugin class: `koji_DataQuery.py`
- Main tool dialog launcher: `data_preprocessing_tool.py`

## Preset Storage

Preset and default configuration files are stored beside the current QGIS project:

```text
<project folder>/<project name>_KDQconfig/<tool name>/
```

The QGIS project must be saved before default presets can be stored.
