# -*- coding: utf-8 -*-

import os
import re
from pathlib import Path

from qgis.core import QgsProject


INVALID_PATH_CHARS = r'[<>:"/\\|?*\x00-\x1f]'
KDQ_CONFIG_SUFFIX = '_KDQconfig'


def project_file_path():
    return QgsProject.instance().fileName()


def project_dir():
    project_path = project_file_path()
    return os.path.dirname(project_path) if project_path else ''


def project_name():
    project_path = project_file_path()
    if not project_path:
        return ''
    return os.path.splitext(os.path.basename(project_path))[0]


def safe_folder_name(name):
    name = re.sub(INVALID_PATH_CHARS, '_', name or '').strip()
    name = name.rstrip('. ')
    return name or 'settings'


def kdq_config_root():
    folder = project_dir()
    name = project_name()
    if not folder or not name:
        return ''
    return os.path.join(folder, safe_folder_name(name + KDQ_CONFIG_SUFFIX))


def process_config_dir(process_name, create=False):
    root = kdq_config_root()
    if not root:
        return ''
    folder = os.path.join(root, safe_folder_name(process_name))
    if create:
        Path(folder).mkdir(parents=True, exist_ok=True)
    return folder


def process_config_path(process_name, filename, create_dir=False):
    folder = process_config_dir(process_name, create=create_dir)
    if not folder:
        return ''
    return os.path.join(folder, filename)
