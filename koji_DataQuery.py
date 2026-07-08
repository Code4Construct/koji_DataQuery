# -*- coding: utf-8 -*-

import os

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTranslator
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

from .kojiGIS4QGIS import DataPreprocessingTool


class KojiDataQuery:
    """QGIS plugin entry point for koji DataQuery."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.tool = None
        self.menu_title = self.tr('koji DataQuery')

        locale = QSettings().value('locale/userLocale', '')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'KojiDataQuery_{}.qm'.format(locale),
        )

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

    def tr(self, message):
        return QCoreApplication.translate('KojiDataQuery', message)

    def initGui(self):
        icon = QIcon(os.path.join(self.plugin_dir, 'icon.png'))
        self.main_action = QAction(
            icon,
            self.tr('\u30c7\u30fc\u30bf\u306e\u4e0b\u51e6\u7406'),
            self.iface.mainWindow(),
        )
        self.main_action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.main_action)
        self.iface.addPluginToMenu(self.menu_title, self.main_action)
        self.actions.append(self.main_action)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu_title, action)
            self.iface.removeToolBarIcon(action)

        if self.tool is not None:
            if getattr(self.tool, 'dlg', None) is not None:
                self.tool.dlg.close()
                self.tool.dlg = None

            for attr_name in (
                'organize_1_dialog',
                'organize_2_gpkg_dialog',
                'organize_2_query_tool',
                'organizing_data_tool',
                'organizing_data_gpkg_tool',
            ):
                tool_or_dialog = getattr(self.tool, attr_name, None)
                if tool_or_dialog is not None and hasattr(tool_or_dialog, 'dlg'):
                    if tool_or_dialog.dlg is not None:
                        tool_or_dialog.dlg.close()
                        tool_or_dialog.dlg = None
                elif tool_or_dialog is not None and hasattr(tool_or_dialog, 'dialog'):
                    if tool_or_dialog.dialog is not None:
                        tool_or_dialog.dialog.close()
                        tool_or_dialog.dialog = None
                elif tool_or_dialog is not None and hasattr(tool_or_dialog, 'close'):
                    tool_or_dialog.close()

    def run(self):
        try:
            if self.tool is None:
                self.tool = DataPreprocessingTool(self.iface)
            self.tool.run()
        except Exception as exc:  # pragma: no cover - shown inside QGIS
            QMessageBox.critical(
                self.iface.mainWindow(),
                self.tr('koji DataQuery'),
                self.tr('\u8d77\u52d5\u306b\u5931\u6557\u3057\u307e\u3057\u305f: {0}').format(exc),
            )
