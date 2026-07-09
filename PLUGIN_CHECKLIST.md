# QGIS Plugin Checklist

## Required Elements

- `metadata.txt`: present.
- `__init__.py` with `classFactory(iface)`: present.
- Main plugin class with `initGui`, `unload`, and `run`: present in `koji_DataQuery.py`.
- Plugin icon referenced by metadata: present as `icon.png`.
- Python modules imported by the plugin: present.

## Added Elements

- `README.md`: added for installation and usage notes.
- `CHANGELOG.md`: added for version history.
- `PLUGIN_CHECKLIST.md`: added for maintenance checks.

## Notes

- The placeholder metadata URLs were removed because they were not real project links.
- `resources.py` is not required because the plugin loads `icon.png` directly.
- An `i18n` folder is optional. The plugin already checks for translation files if they are added later.
