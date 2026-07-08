# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime

from qgis.core import (
    QgsMapLayer,
    QgsPrintLayout,
    QgsProject,
    QgsRasterLayer,
    QgsReadWriteContext,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication, Qt, QSettings, QTranslator
from qgis.PyQt.QtGui import QGuiApplication, QIcon
from qgis.PyQt.QtXml import QDomDocument
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .add_sets_layers.add_sets_layers import Add_Sets_Layers
from .data_organize1_processor import (
    apply_processing_steps,
    parse_column_delete_step,
    parse_column_rename_step,
    parse_column_reorder_step,
    parse_date_normalize_step,
    parse_chiban_organize_step,
    parse_chiban_prefix_step,
    parse_row_filter_step,
    parse_string_concat_step,
    parse_text_normalize_step,
    process_csv,
    read_csv_rows,
)
from .data_organize2_gpkg_processor import list_gpkg_layer_infos, process_gpkg, read_gpkg_rows
from .data_organize2_query_tool import DataOrganize2QueryTool
from .organizing_data.organizing_data_tool import OrganizingDataGpkgTool, OrganizingDataTool
from .merge_point_features_in_poligon.merge_point_features_in_poligon import (
    MergePointFeaturesInPoligon,
)
from .merge_poligon_features_in_poligon.merge_poligon_features_in_poligon import (
    MergePoligonFeaturesInPoligon,
)
from .ward_circle_boundary.ward_circle_boundary import WardCircleBoundary


DEFAULT_DATA_ORGANIZE1_CSV = (
    r'D:\01HIROTAKAのデータ\仕事\20260313施設\csv_data'
    r'\大阪府公有財産（固定資産）台帳一覧【土地】R7.3.31現在.csv'
)


DATA_ORGANIZE1_DEFAULT_CONFIG_FILENAME = 'kojiGIS_tools_data_organize1_csv_cleanup_default.json'
DATA_ORGANIZE2_DEFAULT_CONFIG_FILENAME = 'kojiGIS_tools_data_organize2_gpkg_cleanup_default.json'


def display_metrics_text():
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 'DPI: - / 表示倍率: -'
    dpi = screen.logicalDotsPerInch()
    scale = dpi / 96.0 * 100.0
    return 'DPI: {0:.0f} / 表示倍率: {1:.0f}%'.format(dpi, scale)


def dpi_scale_factor():
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 1.0
    return max(0.75, screen.logicalDotsPerInch() / 96.0)


def dpi_px(value):
    return max(1, int(round(value * dpi_scale_factor())))


class StringConcatSelectionDialog(QDialog):
    """Select fields for string concatenation and keep their checked order."""

    def __init__(self, fields, selected_fields=None, output_field='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('文字列結合の列を選択')
        self.resize(430, 560)
        self.selected_order = []
        self.rows = []
        selected_fields = selected_fields or []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('結合する列を順番にチェックしてください。'))

        layout.itemAt(0).widget().setText('結合する列を順番にチェックしてください。')
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        toolbar = QHBoxLayout()
        self.reorder_up_button = QPushButton('上へ')
        self.reorder_down_button = QPushButton('下へ')
        self.reorder_up_button.clicked.connect(self.move_reorder_row_up)
        self.reorder_down_button.clicked.connect(self.move_reorder_row_down)
        toolbar.addStretch(1)
        toolbar.addWidget(self.reorder_up_button)
        toolbar.addWidget(self.reorder_down_button)
        layout.addLayout(toolbar)

        self.reorder_table = QTableWidget(0, 2)
        self.reorder_table.setHorizontalHeaderLabels(['列名', '順序'])
        self.reorder_table.horizontalHeader().setStretchLastSection(False)
        self.reorder_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.reorder_table.setColumnWidth(1, 80)
        self.reorder_table.verticalHeader().setVisible(True)
        layout.addWidget(self.reorder_table, 1)
        if hasattr(self, '_refresh_reorder_table'):
            self._refresh_reorder_table()
        self.reorder_up_button.hide()
        self.reorder_down_button.hide()
        self.reorder_table.hide()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        grid.addWidget(QLabel('列名'), 0, 0)
        grid.addWidget(QLabel('順番'), 0, 1)
        grid.addWidget(QLabel('変更後'), 0, 2)

        target_by_source = {}
        for index, field in enumerate(fields, start=1):
            checkbox = QCheckBox(field)
            order_label = QLabel('')
            order_label.setAlignment(Qt.AlignCenter)
            order_label.setMinimumWidth(34)
            target_edit = QLineEdit(target_by_source.get(field, ''))
            target_edit.setPlaceholderText('新しいコラム名')
            target_edit.setEnabled(False)
            checkbox.toggled.connect(lambda checked=False, field=field: self._toggle_field(field, checked))
            grid.addWidget(checkbox, index, 0)
            grid.addWidget(order_label, index, 1)
            self.rows.append((field, checkbox, order_label))

        grid.setRowStretch(len(fields) + 1, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        output_layout = QFormLayout()
        self.output_field_edit = QLineEdit(output_field)
        self.output_field_edit.setPlaceholderText('例: 所在地番')
        output_layout.addRow('結合後の新しい列名', self.output_field_edit)
        layout.addLayout(output_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for field in selected_fields:
            for row_field, checkbox, _ in self.rows:
                if row_field == field:
                    checkbox.setChecked(True)
                    break

    def _toggle_field(self, field, checked):
        if checked and field not in self.selected_order:
            self.selected_order.append(field)
        elif not checked and field in self.selected_order:
            self.selected_order.remove(field)
        self._refresh_order_labels()

    def _refresh_order_labels(self):
        for field, _, order_label in self.rows:
            if field in self.selected_order:
                order_label.setText(str(self.selected_order.index(field) + 1))
            else:
                order_label.setText('')

    def apply_filter(self, text):
        text = text.strip().lower()
        for field, checkbox, order_label in self.rows:
            visible = text in field.lower()
            checkbox.setVisible(visible)
            order_label.setVisible(visible)

    def accept(self):
        if len(self.selected_order) < 2:
            QMessageBox.warning(self, 'データ整理１', '結合する列を2つ以上選択してください。')
            return
        if not self.output_field_edit.text().strip():
            QMessageBox.warning(self, 'データ整理１', '結合後の新しい列名を入力してください。')
            return
        super().accept()

    def selected_fields(self):
        return list(self.selected_order)

    def output_field(self):
        return self.output_field_edit.text().strip()

    def move_reorder_row_up(self):
        return

    def move_reorder_row_down(self):
        return


class ChibanPrefixSelectionDialog(QDialog):
    """Configure address prefix add/remove for chiban strings."""

    def __init__(self, fields, selected_field='', output_field='', operation='remove', prefix='大阪府大阪市', parent=None):
        super().__init__(parent)
        self.setWindowTitle('地番住所プレフィックス')
        self.resize(520, 260)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('地番や結合地番の先頭にある住所文字列を除去、または追加します。'))

        form = QFormLayout()
        self.field_combo = QComboBox()
        self.field_combo.setEditable(True)
        self.field_combo.addItems(fields)
        if selected_field:
            self.field_combo.setCurrentText(selected_field)

        self.operation_combo = QComboBox()
        self.operation_combo.addItem('先頭から除く', 'remove')
        self.operation_combo.addItem('先頭に追加', 'add')
        index = self.operation_combo.findData(operation)
        if index >= 0:
            self.operation_combo.setCurrentIndex(index)

        self.prefix_edit = QLineEdit(prefix or '大阪府大阪市')
        self.output_field_edit = QLineEdit(output_field or '')
        self.output_field_edit.setPlaceholderText('空欄なら対象列を上書き')

        form.addRow('対象列', self.field_combo)
        form.addRow('処理', self.operation_combo)
        form.addRow('文字列', self.prefix_edit)
        form.addRow('出力列', self.output_field_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        if not self.source_field():
            QMessageBox.warning(self, 'データ整理１', '対象列を指定してください。')
            return
        if not self.prefix():
            QMessageBox.warning(self, 'データ整理１', '除去または追加する文字列を入力してください。')
            return
        super().accept()

    def source_field(self):
        return self.field_combo.currentText().strip()

    def operation(self):
        return self.operation_combo.currentData()

    def prefix(self):
        return self.prefix_edit.text().strip()

    def output_field(self):
        return self.output_field_edit.text().strip()


class ColumnRenameSelectionDialog(QDialog):
    """Select columns and enter replacement column names next to each checkbox."""

    def __init__(self, fields, selected_fields=None, target_fields=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('コラム名の変更')
        self.resize(620, 580)
        self.rows = []
        selected_fields = selected_fields or []
        target_fields = target_fields or []
        target_by_source = {
            source: target
            for source, target in zip(selected_fields, target_fields)
        }

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('名前を変更する列をチェックし、右側に変更後のコラム名を入力してください。'))

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.addWidget(QLabel('列名'), 0, 0)
        grid.addWidget(QLabel('変更後'), 0, 1)

        for index, field in enumerate(fields, start=1):
            checkbox = QCheckBox(field)
            target_edit = QLineEdit(target_by_source.get(field, ''))
            target_edit.setPlaceholderText('新しいコラム名')
            target_edit.setEnabled(False)
            checkbox.toggled.connect(target_edit.setEnabled)
            grid.addWidget(checkbox, index, 0)
            grid.addWidget(target_edit, index, 1)
            self.rows.append((field, checkbox, target_edit))

        grid.setRowStretch(len(fields) + 1, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for field in selected_fields:
            for row_field, checkbox, _ in self.rows:
                if row_field == field:
                    checkbox.setChecked(True)
                    break

    def apply_filter(self, text):
        text = text.strip().lower()
        for field, checkbox, target_edit in self.rows:
            visible = text in field.lower()
            checkbox.setVisible(visible)
            target_edit.setVisible(visible)

    def accept(self):
        if not self.selected_fields():
            QMessageBox.warning(self, 'データ整理１', '名前を変更する列を選択してください。')
            return
        for field, checkbox, target_edit in self.rows:
            if checkbox.isChecked() and not target_edit.text().strip():
                QMessageBox.warning(self, 'データ整理１', '「{}」の変更後のコラム名を入力してください。'.format(field))
                return
        super().accept()

    def selected_fields(self):
        return [field for field, checkbox, _ in self.rows if checkbox.isChecked()]

    def target_fields(self):
        return [
            target_edit.text().strip()
            for _, checkbox, target_edit in self.rows
            if checkbox.isChecked()
        ]


class ColumnDeleteSelectionDialog(QDialog):
    """Select columns to delete."""

    def __init__(self, fields, selected_fields=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('列の削除')
        self.resize(430, 560)
        self.rows = []
        selected_fields = selected_fields or []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('削除する列を選択してください。'))

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        list_layout = QVBoxLayout(content)
        list_layout.setContentsMargins(4, 4, 4, 4)

        for field in fields:
            checkbox = QCheckBox(field)
            checkbox.setChecked(field in selected_fields)
            list_layout.addWidget(checkbox)
            self.rows.append((field, checkbox))

        list_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_filter(self, text):
        text = text.strip().lower()
        for field, checkbox in self.rows:
            checkbox.setVisible(text in field.lower())

    def accept(self):
        if not self.selected_fields():
            QMessageBox.warning(self, 'データ整理１', '削除する列を1つ以上選択してください。')
            return
        super().accept()

    def selected_fields(self):
        return [field for field, checkbox in self.rows if checkbox.isChecked()]


class TextNormalizeSelectionDialog(QDialog):
    """Select columns and text normalization operations."""

    def __init__(self, fields, selected_fields=None, operations=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('空白・全角半角の整理')
        self.resize(520, 620)
        self.rows = []
        selected_fields = selected_fields or []
        operations = operations or []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('整理する列を選択し、実行する処理を選んでください。'))

        operations_group = QGroupBox('処理')
        operations_layout = QVBoxLayout(operations_group)
        self.halfwidth_checkbox = QCheckBox('半角化')
        self.fullwidth_checkbox = QCheckBox('全角化')
        self.remove_spaces_checkbox = QCheckBox('空白削除')
        self.halfwidth_checkbox.setChecked('to_halfwidth' in operations)
        self.fullwidth_checkbox.setChecked('to_fullwidth' in operations)
        self.remove_spaces_checkbox.setChecked('remove_spaces' in operations)
        operations_layout.addWidget(self.halfwidth_checkbox)
        operations_layout.addWidget(self.fullwidth_checkbox)
        operations_layout.addWidget(self.remove_spaces_checkbox)
        layout.addWidget(operations_group)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        list_layout = QVBoxLayout(content)
        list_layout.setContentsMargins(4, 4, 4, 4)

        for field in fields:
            checkbox = QCheckBox(field)
            checkbox.setChecked(field in selected_fields)
            list_layout.addWidget(checkbox)
            self.rows.append((field, checkbox))

        list_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_filter(self, text):
        text = text.strip().lower()
        for field, checkbox in self.rows:
            checkbox.setVisible(text in field.lower())

    def accept(self):
        if not self.selected_fields():
            QMessageBox.warning(self, 'データ整理１', '整理する列を1つ以上選択してください。')
            return
        operations = self.operations()
        if not operations:
            QMessageBox.warning(self, 'データ整理１', '実行する処理を1つ以上選択してください。')
            return
        if 'to_halfwidth' in operations and 'to_fullwidth' in operations:
            QMessageBox.warning(self, 'データ整理１', '半角化と全角化はどちらか一方を選択してください。')
            return
        super().accept()

    def selected_fields(self):
        return [field for field, checkbox in self.rows if checkbox.isChecked()]

    def operations(self):
        operations = []
        if self.halfwidth_checkbox.isChecked():
            operations.append('to_halfwidth')
        if self.fullwidth_checkbox.isChecked():
            operations.append('to_fullwidth')
        if self.remove_spaces_checkbox.isChecked():
            operations.append('remove_spaces')
        return operations


class DateNormalizeSelectionDialog(QDialog):
    """Select date columns and output date format."""

    FORMAT_OPTIONS = [
        ('YYYY-MM-DD', 'yyyy-mm-dd'),
        ('YYYY/MM/DD', 'yyyy/mm/dd'),
        ('YYYY年M月D日', 'yyyy年m月d日'),
        ('YYYYMMDD', 'yyyymmdd'),
    ]

    def __init__(self, fields, selected_fields=None, output_format='yyyy-mm-dd', parent=None):
        super().__init__(parent)
        self.setWindowTitle('日付の統一')
        self.resize(520, 620)
        self.rows = []
        selected_fields = selected_fields or []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('日付を統一する列を選択し、出力形式を選んでください。'))

        format_group = QGroupBox('出力形式')
        format_layout = QVBoxLayout(format_group)
        self.format_combo = QComboBox()
        for label, value in self.FORMAT_OPTIONS:
            self.format_combo.addItem(label, value)
        index = self.format_combo.findData(output_format)
        self.format_combo.setCurrentIndex(index if index >= 0 else 0)
        format_layout.addWidget(self.format_combo)
        layout.addWidget(format_group)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        list_layout = QVBoxLayout(content)
        list_layout.setContentsMargins(4, 4, 4, 4)

        for field in fields:
            checkbox = QCheckBox(field)
            checkbox.setChecked(field in selected_fields)
            list_layout.addWidget(checkbox)
            self.rows.append((field, checkbox))

        list_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_filter(self, text):
        text = text.strip().lower()
        for field, checkbox in self.rows:
            checkbox.setVisible(text in field.lower())

    def accept(self):
        if not self.selected_fields():
            QMessageBox.warning(self, 'データ整理１', '日付を統一する列を1つ以上選択してください。')
            return
        super().accept()

    def selected_fields(self):
        return [field for field, checkbox in self.rows if checkbox.isChecked()]

    def output_format(self):
        return self.format_combo.currentData()

    def output_format_label(self):
        return self.format_combo.currentText()


class RowFilterSelectionDialog(QDialog):
    """Select columns and a condition for excluding matching rows."""

    FILTER_KINDS = [
        ('文字列一致', 'text'),
        ('数量制限', 'number'),
        ('日付期間', 'date'),
    ]
    CONDITIONS_BY_KIND = {
        'text': [
            ('空白', 'empty'),
            ('空白でない', 'not_empty'),
            ('指定文字を含む', 'contains'),
            ('指定文字を含まない', 'not_contains'),
            ('完全一致', 'equals'),
            ('一致しない', 'not_equals'),
            ('正規表現に一致', 'regex'),
        ],
        'number': [
            ('空白', 'empty'),
            ('空白でない', 'not_empty'),
            ('等しい', 'equals'),
            ('等しくない', 'not_equals'),
            ('以上', 'gte'),
            ('以下', 'lte'),
            ('より大きい', 'gt'),
            ('より小さい', 'lt'),
            ('範囲内', 'between'),
        ],
        'date': [
            ('空白', 'empty'),
            ('空白でない', 'not_empty'),
            ('同じ日', 'equals'),
            ('以後', 'gte'),
            ('以前', 'lte'),
            ('期間内', 'between'),
        ],
    }

    def __init__(self, fields, selected_fields=None, condition='empty', value='', match_mode='any', filter_kind='text', value2='', action='exclude', parent=None, rules=None):
        super().__init__(parent)
        self.setWindowTitle('行の抽出・除外')
        self.resize(1120, 620)
        self.rows = []
        rules = rules or []
        selected_fields = selected_fields or [rule.get('field') for rule in rules if rule.get('field')]
        if not rules and selected_fields:
            rules = [
                {
                    'field': field,
                    'filter_kind': filter_kind,
                    'condition': condition,
                    'value': value,
                    'value2': value2,
                }
                for field in selected_fields
            ]
        self.initial_rules_by_field = {
            rule.get('field'): dict(rule)
            for rule in rules
            if rule.get('field')
        }

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('条件に合う行を除外します。対象列と条件を選んでください。'))

        content_layout = QHBoxLayout()
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        left_layout.addWidget(self.filter_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        list_layout = QVBoxLayout(content)
        list_layout.setContentsMargins(4, 4, 4, 4)

        for field in fields:
            checkbox = QCheckBox(field)
            checkbox.setChecked(field in selected_fields)
            checkbox.toggled.connect(self._refresh_selected_fields_preview)
            list_layout.addWidget(checkbox)
            self.rows.append((field, checkbox))

        list_layout.addStretch(1)
        scroll.setWidget(content)
        left_layout.addWidget(scroll, 1)
        content_layout.addWidget(left_panel, 3)

        condition_group = QGroupBox('抽出・除外条件')
        condition_layout = QVBoxLayout(condition_group)
        common_form = QFormLayout()
        self.action_combo = QComboBox()
        self.action_combo.addItem('条件に合う行を除外する', 'exclude')
        self.action_combo.addItem('条件に合う行だけを残す', 'include')
        action_index = self.action_combo.findData(action)
        self.action_combo.setCurrentIndex(action_index if action_index >= 0 else 0)

        self.match_mode_combo = QComboBox()
        self.match_mode_combo.addItem('いずれかの列が条件に合う', 'any')
        self.match_mode_combo.addItem('すべての列が条件に合う', 'all')
        mode_index = self.match_mode_combo.findData(match_mode)
        self.match_mode_combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)

        common_form.addRow('動作', self.action_combo)
        common_form.addRow('判定', self.match_mode_combo)
        condition_layout.addLayout(common_form)

        self.rules_table = QTableWidget(0, 5)
        self.rules_table.setHorizontalHeaderLabels(['列名', '種類', '条件', '値1', '値2'])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        self.rules_table.setColumnWidth(0, 210)
        self.rules_table.setColumnWidth(1, 120)
        self.rules_table.setColumnWidth(2, 150)
        self.rules_table.setColumnWidth(3, 160)
        self.rules_table.setColumnWidth(4, 160)
        condition_layout.addWidget(self.rules_table, 1)
        condition_group.setMinimumWidth(620)
        content_layout.addWidget(condition_group, 5)
        layout.addLayout(content_layout, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_rules_table()

    def apply_filter(self, text):
        text = text.strip().lower()
        for field, checkbox in self.rows:
            checkbox.setVisible(text in field.lower())

    def _refresh_selected_fields_preview(self):
        if not hasattr(self, 'rules_table'):
            return
        self._refresh_rules_table()

    def _refresh_rules_table(self):
        existing_rules = {
            rule.get('field'): rule
            for rule in self.rules()
            if rule.get('field')
        }
        for field, rule in self.initial_rules_by_field.items():
            existing_rules.setdefault(field, rule)

        self.rules_table.setRowCount(0)
        for field in self.selected_fields():
            rule = existing_rules.get(field, {'field': field})
            self._add_rule_row(rule)

    def _add_rule_row(self, rule):
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        field = rule.get('field', '')
        field_item = QTableWidgetItem(field)
        field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
        self.rules_table.setItem(row, 0, field_item)

        kind_combo = QComboBox()
        for label, data in self.FILTER_KINDS:
            kind_combo.addItem(label, data)
        kind_index = kind_combo.findData(rule.get('filter_kind') or 'text')
        kind_combo.setCurrentIndex(kind_index if kind_index >= 0 else 0)

        condition_combo = QComboBox()
        value_edit = QLineEdit(rule.get('value') or '')
        value2_edit = QLineEdit(rule.get('value2') or '')
        self.rules_table.setCellWidget(row, 1, kind_combo)
        self.rules_table.setCellWidget(row, 2, condition_combo)
        self.rules_table.setCellWidget(row, 3, value_edit)
        self.rules_table.setCellWidget(row, 4, value2_edit)

        def refresh_condition_options(selected_condition=None):
            current = selected_condition if isinstance(selected_condition, str) else condition_combo.currentData()
            condition_combo.blockSignals(True)
            try:
                condition_combo.clear()
                for label, data in self.CONDITIONS_BY_KIND.get(kind_combo.currentData(), []):
                    condition_combo.addItem(label, data)
                index = condition_combo.findData(current)
                condition_combo.setCurrentIndex(index if index >= 0 else 0)
            finally:
                condition_combo.blockSignals(False)
            refresh_value_enabled()

        def refresh_value_enabled():
            condition = condition_combo.currentData()
            needs_value = condition not in ('empty', 'not_empty')
            value_edit.setEnabled(needs_value)
            value2_edit.setEnabled(condition == 'between')
            if kind_combo.currentData() == 'date':
                value_edit.setPlaceholderText('例: 2024/1/1, R6.1.1')
                value2_edit.setPlaceholderText('例: 2024/12/31')
            elif kind_combo.currentData() == 'number':
                value_edit.setPlaceholderText('例: 18, 1000.5')
                value2_edit.setPlaceholderText('範囲の上限')
            else:
                value_edit.setPlaceholderText('文字列・正規表現（複数はカンマ区切り）')
                value2_edit.setPlaceholderText('使用しません')

        kind_combo.currentIndexChanged.connect(refresh_condition_options)
        condition_combo.currentIndexChanged.connect(refresh_value_enabled)
        refresh_condition_options(rule.get('condition') or 'empty')

    def accept(self):
        rules = self.rules()
        if not rules:
            QMessageBox.warning(self, 'データ整理１', '判定する列を1つ以上選択してください。')
            return
        for rule in rules:
            if rule.get('condition') not in ('empty', 'not_empty') and not rule.get('value'):
                QMessageBox.warning(self, 'データ整理１', '{} の条件の値を入力してください。'.format(rule.get('field')))
                return
            if rule.get('condition') == 'between' and not rule.get('value2'):
                QMessageBox.warning(self, 'データ整理１', '{} の範囲条件の値2を入力してください。'.format(rule.get('field')))
                return
        super().accept()

    def selected_fields(self):
        return [field for field, checkbox in self.rows if checkbox.isChecked()]

    def rules(self):
        rules = []
        if not hasattr(self, 'rules_table'):
            return rules
        for row in range(self.rules_table.rowCount()):
            item = self.rules_table.item(row, 0)
            field = item.text().strip() if item else ''
            kind_combo = self.rules_table.cellWidget(row, 1)
            condition_combo = self.rules_table.cellWidget(row, 2)
            value_edit = self.rules_table.cellWidget(row, 3)
            value2_edit = self.rules_table.cellWidget(row, 4)
            if not field:
                continue
            rules.append({
                'field': field,
                'filter_kind': kind_combo.currentData() if kind_combo else 'text',
                'condition': condition_combo.currentData() if condition_combo else 'empty',
                'value': value_edit.text().strip() if value_edit else '',
                'value2': value2_edit.text().strip() if value2_edit else '',
            })
        return rules

    def filter_kind(self):
        rules = self.rules()
        return rules[0].get('filter_kind') if rules else 'text'

    def filter_kind_label(self):
        return self._kind_label(self.filter_kind())

    def condition(self):
        rules = self.rules()
        return rules[0].get('condition') if rules else 'empty'

    def condition_label(self):
        return self._condition_label(self.filter_kind(), self.condition())

    def value(self):
        rules = self.rules()
        return rules[0].get('value') if rules else ''

    def value2(self):
        rules = self.rules()
        return rules[0].get('value2') if rules else ''

    def action(self):
        return self.action_combo.currentData()

    def action_label(self):
        return self.action_combo.currentText()

    def match_mode(self):
        return self.match_mode_combo.currentData()

    def match_mode_label(self):
        return self.match_mode_combo.currentText()

    def _kind_label(self, kind):
        return next((label for label, data in self.FILTER_KINDS if data == kind), kind)

    def _condition_label(self, kind, condition):
        return next((label for label, data in self.CONDITIONS_BY_KIND.get(kind, []) if data == condition), condition)


class ColumnReorderDialog(QDialog):
    """Assign order numbers to all columns."""

    def __init__(self, fields, order_map=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('列の順序の変更')
        self.resize(520, 620)
        self.rows = []
        fields = list(fields)
        order_map = order_map or {}
        self.reorder_fields = sorted(
            fields,
            key=lambda field: (order_map.get(field, len(fields) + 1), fields.index(field)),
        )

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('各列の右側に並び順の番号を入力してください。未入力の列は元の順番で末尾に残ります。'))

        layout.itemAt(0).widget().setText('列を選択して「上へ」「下へ」で並び替えてください。')
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        toolbar = QHBoxLayout()
        self.reorder_up_button = QPushButton('上へ')
        self.reorder_down_button = QPushButton('下へ')
        self.reorder_up_button.clicked.connect(self.move_reorder_row_up)
        self.reorder_down_button.clicked.connect(self.move_reorder_row_down)
        toolbar.addStretch(1)
        toolbar.addWidget(self.reorder_up_button)
        toolbar.addWidget(self.reorder_down_button)
        layout.addLayout(toolbar)

        self.reorder_table = QTableWidget(0, 2)
        self.reorder_table.setHorizontalHeaderLabels(['列名', '順序'])
        self.reorder_table.horizontalHeader().setStretchLastSection(False)
        self.reorder_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.reorder_table.setColumnWidth(1, 80)
        self.reorder_table.verticalHeader().setVisible(True)
        layout.addWidget(self.reorder_table, 1)
        self._refresh_reorder_table()
        self.filter_edit.hide()
        self.reorder_table.setColumnCount(1)
        self.reorder_table.setHorizontalHeaderLabels(['列名'])
        self.reorder_table.horizontalHeader().setStretchLastSection(True)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setColumnStretch(0, 1)
        grid.addWidget(QLabel('列名'), 0, 0)
        grid.addWidget(QLabel('順序'), 0, 1)

        for index, field in enumerate(fields, start=1):
            label = QLabel(field)
            order_edit = QLineEdit(str(order_map.get(field, index)))
            order_edit.setMaximumWidth(80)
            order_edit.setAlignment(Qt.AlignRight)
            grid.addWidget(label, index, 0)
            grid.addWidget(order_edit, index, 1)
            self.rows.append((field, label, order_edit))

        grid.setRowStretch(len(fields) + 1, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        scroll.hide()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_filter(self, text):
        text = text.strip().lower()
        for field, label, order_edit in self.rows:
            visible = text in field.lower()
            label.setVisible(visible)
            order_edit.setVisible(visible)

    def accept(self):
        super().accept()

    def order_map(self):
        result = {}
        for field, _, order_edit in self.rows:
            value = order_edit.text().strip()
            if value:
                result[field] = int(value)
        return result


    def _refresh_reorder_table(self, selected_row=None):
        self.reorder_table.setRowCount(len(self.reorder_fields))
        for row, field in enumerate(self.reorder_fields):
            self.reorder_table.setItem(row, 0, QTableWidgetItem(field))
            order_item = QTableWidgetItem(str(row + 1))
            order_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.reorder_table.setItem(row, 1, order_item)
        if self.reorder_fields:
            if selected_row is None:
                selected_row = min(self.reorder_table.currentRow(), len(self.reorder_fields) - 1)
            selected_row = max(0, min(selected_row, len(self.reorder_fields) - 1))
            self.reorder_table.selectRow(selected_row)
            self.reorder_table.setCurrentCell(selected_row, 0)
        self.apply_filter(self.filter_edit.text())

    def _refresh_reorder_table(self, selected_row=None):
        self.reorder_table.setColumnCount(1)
        self.reorder_table.setHorizontalHeaderLabels(['列名'])
        self.reorder_table.horizontalHeader().setStretchLastSection(True)
        self.reorder_table.setRowCount(len(self.reorder_fields))
        for row, field in enumerate(self.reorder_fields):
            self.reorder_table.setItem(row, 0, QTableWidgetItem(field))
        if self.reorder_fields:
            if selected_row is None:
                selected_row = min(self.reorder_table.currentRow(), len(self.reorder_fields) - 1)
            selected_row = max(0, min(selected_row, len(self.reorder_fields) - 1))
            self.reorder_table.selectRow(selected_row)
            self.reorder_table.setCurrentCell(selected_row, 0)

    def _current_reorder_row(self):
        row = self.reorder_table.currentRow()
        if row < 0 and self.reorder_table.selectedIndexes():
            row = self.reorder_table.selectedIndexes()[0].row()
        return row

    def move_reorder_row_up(self):
        row = self._current_reorder_row()
        if row <= 0:
            return
        self.reorder_fields[row - 1], self.reorder_fields[row] = self.reorder_fields[row], self.reorder_fields[row - 1]
        self._refresh_reorder_table(row - 1)

    def move_reorder_row_down(self):
        row = self._current_reorder_row()
        if row < 0 or row >= len(self.reorder_fields) - 1:
            return
        self.reorder_fields[row + 1], self.reorder_fields[row] = self.reorder_fields[row], self.reorder_fields[row + 1]
        self._refresh_reorder_table(row + 1)

    def apply_filter(self, text):
        text = text.strip().lower()
        if not hasattr(self, 'reorder_table'):
            return
        for row, field in enumerate(self.reorder_fields):
            self.reorder_table.setRowHidden(row, text not in field.lower())

    def order_map(self):
        return {
            field: index + 1
            for index, field in enumerate(self.reorder_fields)
        }


class CustomPythonFunctionDialog(QDialog):
    """Configure a row-wise Python transform."""

    def __init__(self, fields, config=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('カスタム関数')
        self.resize(720, 680)
        self.rows = []
        self.selected_order = []
        config = config or {}
        selected_fields = config.get('input_fields') or []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('入力に使う列を選び、戻り値を書き込む出力先を指定してください。'))

        splitter = QSplitter(Qt.Horizontal)

        fields_panel = QWidget()
        fields_layout = QVBoxLayout(fields_panel)
        fields_layout.setContentsMargins(0, 0, 8, 0)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        fields_layout.addWidget(self.filter_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setColumnStretch(0, 1)
        grid.addWidget(QLabel('列名'), 0, 0)
        grid.addWidget(QLabel('変数'), 0, 1)
        for index, field in enumerate(fields, start=1):
            checkbox = QCheckBox(field)
            variable_label = QLabel('')
            variable_label.setAlignment(Qt.AlignCenter)
            variable_label.setMinimumWidth(34)
            checkbox.toggled.connect(lambda checked=False, field=field: self._toggle_input_field(field, checked))
            grid.addWidget(checkbox, index, 0)
            grid.addWidget(variable_label, index, 1)
            self.rows.append((field, checkbox, variable_label))
        grid.setRowStretch(len(fields) + 1, 1)
        scroll.setWidget(content)
        fields_layout.addWidget(scroll, 1)

        settings_panel = QWidget()
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(8, 0, 0, 0)

        output_group = QGroupBox('列の作成 / 書き込み先')
        output_layout = QFormLayout(output_group)
        self.output_mode_combo = QComboBox()
        self.output_mode_combo.addItem('新規列を作成する', 'new')
        self.output_mode_combo.addItem('既存列へ書き込む', 'existing')
        mode = config.get('output_mode', 'new')
        self.output_mode_combo.setCurrentIndex(1 if mode == 'existing' else 0)
        self.auto_existing_output_field = config.get('existing_output_field') == '__FIRST_INPUT__'

        self.new_output_edit = QLineEdit(config.get('new_output_field', ''))
        self.new_output_edit.setPlaceholderText('新しい列名')
        self.existing_output_combo = QComboBox()
        self.existing_output_combo.setEditable(True)
        self.existing_output_combo.addItem('')
        self.existing_output_combo.addItems(fields)
        existing_field = config.get('existing_output_field', '')
        if existing_field and existing_field != '__FIRST_INPUT__':
            if self.existing_output_combo.findText(existing_field) < 0:
                self.existing_output_combo.addItem(existing_field)
            self.existing_output_combo.setCurrentText(existing_field)
        self.existing_output_combo.activated.connect(self._disable_existing_output_auto)
        self.output_mode_combo.currentIndexChanged.connect(self._sync_output_mode)
        output_layout.addRow('列の扱い', self.output_mode_combo)
        output_layout.addRow('作成する新規列', self.new_output_edit)
        output_layout.addRow('書き込む既存列', self.existing_output_combo)
        settings_layout.addWidget(output_group)

        standard_group = QGroupBox('標準カスタム関数')
        standard_layout = QVBoxLayout(standard_group)
        self.standard_functions_layout = QVBoxLayout()
        standard_layout.addLayout(self.standard_functions_layout)
        settings_layout.addWidget(standard_group)

        code_group = QGroupBox('Python関数')
        code_layout = QVBoxLayout(code_group)
        self.code_edit = QPlainTextEdit()
        self.code_edit.setPlainText(config.get('code') or self._default_code())
        code_layout.addWidget(self.code_edit)
        code_buttons = QHBoxLayout()
        load_button = QPushButton('ローカル関数を読込')
        save_standard_button = QPushButton('標準へ保存')
        save_local_button = QPushButton('ローカルへ保存')
        save_as_button = QPushButton('名前を付けて保存')
        load_button.clicked.connect(lambda: self.load_function_file(scope='local'))
        save_standard_button.clicked.connect(lambda: self.save_function_file(scope='standard', save_as=True))
        save_local_button.clicked.connect(lambda: self.save_function_file(scope='local', save_as=True))
        save_as_button.clicked.connect(lambda: self.save_function_file(save_as=True))
        code_buttons.addWidget(load_button)
        code_buttons.addWidget(save_standard_button)
        code_buttons.addWidget(save_local_button)
        code_buttons.addWidget(save_as_button)
        code_buttons.addStretch(1)
        code_layout.addLayout(code_buttons)
        self.function_file_path = config.get('function_file_path', '')
        settings_layout.addWidget(code_group, 1)

        splitter.addWidget(fields_panel)
        splitter.addWidget(settings_panel)
        splitter.setSizes([260, 460])
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._sync_output_mode()
        self.refresh_standard_functions()

        for field in selected_fields:
            for row_field, checkbox, _ in self.rows:
                if row_field == field:
                    checkbox.setChecked(True)
                    break
        self._sync_existing_output_to_first_input()

    def _default_code(self):
        return (
            'def transform(row, values):\n'
            '    # valuesにはチェックした順に A, B, C... の変数名で値が入ります。\n'
            '    # 例: A = values.get("A", "")\n'
            '    # 新規列を作る場合も、既存列へ書き込む場合も、この戻り値が使われます。\n'
            '    # 例: return A\n'
            '    return ""\n'
        )

    def _standard_functions_dir(self):
        folder = os.path.join(os.path.dirname(__file__), 'custom_functions', 'standard')
        os.makedirs(folder, exist_ok=True)
        return folder

    def _local_functions_dir(self):
        project_path = QgsProject.instance().fileName()
        if not project_path:
            return ''
        folder = os.path.join(os.path.dirname(project_path), 'kojiGIS_tools_custom_functions')
        os.makedirs(folder, exist_ok=True)
        return folder

    def _functions_dir(self):
        return self._local_functions_dir() or self._standard_functions_dir()

    def _function_dir_for_scope(self, scope):
        if scope == 'standard':
            return self._standard_functions_dir()
        if scope == 'local':
            folder = self._local_functions_dir()
            if not folder:
                QMessageBox.warning(self, 'データ整理１', 'QGISプロジェクトを保存してからローカル関数を使ってください。')
            return folder
        return self._functions_dir()

    def refresh_standard_functions(self):
        while self.standard_functions_layout.count():
            item = self.standard_functions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        folder = self._standard_functions_dir()
        paths = [
            os.path.join(folder, name)
            for name in sorted(os.listdir(folder))
            if name.lower().endswith(('.py', '.json'))
        ]
        if not paths:
            self.standard_functions_layout.addWidget(QLabel('標準カスタム関数はまだありません。'))
            return

        for path in paths:
            radio = QRadioButton(self._function_display_name(path))
            radio.toggled.connect(lambda checked=False, path=path: self.load_standard_function(path, checked))
            self.standard_functions_layout.addWidget(radio)

    def load_standard_function(self, path, checked):
        if not checked:
            return
        self._load_function_path(path)

    def _function_display_name(self, path):
        if path.lower().endswith('.json'):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get('name') or os.path.splitext(os.path.basename(path))[0]
            except Exception:
                return os.path.splitext(os.path.basename(path))[0]
        return os.path.splitext(os.path.basename(path))[0]

    def _load_function_path(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                if path.lower().endswith('.json'):
                    data = json.load(f)
                    self.code_edit.setPlainText(data.get('code', ''))
                    if data.get('output_mode') in ('new', 'existing'):
                        self.output_mode_combo.setCurrentIndex(1 if data.get('output_mode') == 'existing' else 0)
                    if data.get('new_output_field'):
                        self.new_output_edit.setText(data.get('new_output_field'))
                    if data.get('existing_output_field') == '__FIRST_INPUT__':
                        self.auto_existing_output_field = True
                        self._sync_existing_output_to_first_input()
                    elif data.get('existing_output_field'):
                        self.auto_existing_output_field = False
                        self.existing_output_combo.setCurrentText(data.get('existing_output_field'))
                    self._sync_output_mode()
                else:
                    self.code_edit.setPlainText(f.read())
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理１', str(exc))
            return
        self.function_file_path = path

    def load_function_file(self, scope=None):
        initial_dir = self._function_dir_for_scope(scope)
        if not initial_dir:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            'Python関数を読込',
            initial_dir,
            'Python (*.py);;All files (*.*)',
        )
        if not path:
            return
        self._load_function_path(path)

    def save_function_file(self, scope=None, save_as=False):
        path = '' if save_as else self.function_file_path
        if not path:
            initial_dir = self._function_dir_for_scope(scope)
            if not initial_dir:
                return
            path, _ = QFileDialog.getSaveFileName(
                self,
                'Python関数を保存',
                initial_dir,
                'Python (*.py);;All files (*.*)',
            )
        if not path:
            return
        if not path.lower().endswith('.py'):
            path += '.py'
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.code())
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理１', str(exc))
            return
        self.function_file_path = path
        if os.path.dirname(path) == self._standard_functions_dir():
            self.refresh_standard_functions()
        QMessageBox.information(self, 'データ整理１', 'Python関数を保存しました。\n\n{}'.format(path))

    def _sync_output_mode(self):
        is_new = self.output_mode_combo.currentData() == 'new'
        self.new_output_edit.setEnabled(is_new)
        self.existing_output_combo.setEnabled(not is_new)
        if not is_new:
            self._sync_existing_output_to_first_input()

    def _disable_existing_output_auto(self, *args):
        self.auto_existing_output_field = False

    def _sync_existing_output_to_first_input(self):
        if self.output_mode_combo.currentData() != 'existing':
            return
        if not self.auto_existing_output_field:
            return
        if not self.selected_order:
            return
        self.existing_output_combo.blockSignals(True)
        self.existing_output_combo.setCurrentText(self.selected_order[0])
        self.existing_output_combo.blockSignals(False)

    def _toggle_input_field(self, field, checked):
        if checked and field not in self.selected_order:
            self.selected_order.append(field)
        elif not checked and field in self.selected_order:
            self.selected_order.remove(field)
        self._refresh_variable_labels()
        self._sync_existing_output_to_first_input()

    def _refresh_variable_labels(self):
        for field, _, variable_label in self.rows:
            if field in self.selected_order:
                variable_label.setText(chr(ord('A') + self.selected_order.index(field)))
            else:
                variable_label.setText('')

    def apply_filter(self, text):
        text = text.strip().lower()
        for field, checkbox, variable_label in self.rows:
            checkbox.setVisible(text in field.lower())
            variable_label.setVisible(text in field.lower())

    def accept(self):
        if not self.input_fields():
            QMessageBox.warning(self, 'データ整理１', '入力に使う列を1つ以上選択してください。')
            return
        if not self.output_field():
            QMessageBox.warning(self, 'データ整理１', '出力先の列を指定してください。')
            return
        if 'def transform' not in self.code():
            QMessageBox.warning(self, 'データ整理１', 'Python関数 def transform(row, values): を入力してください。')
            return
        super().accept()

    def input_fields(self):
        return list(self.selected_order)

    def output_mode(self):
        return self.output_mode_combo.currentData()

    def output_field(self):
        if self.output_mode() == 'new':
            return self.new_output_edit.text().strip()
        return self.existing_output_combo.currentText().strip()

    def code(self):
        return self.code_edit.toPlainText()

    def config(self):
        return {
            'input_fields': self.input_fields(),
            'output_mode': self.output_mode(),
            'new_output_field': self.new_output_edit.text().strip(),
            'existing_output_field': (
                '__FIRST_INPUT__'
                if self.auto_existing_output_field
                else self.existing_output_combo.currentText().strip()
            ),
            'output_field': self.output_field(),
            'code': self.code(),
            'function_file_path': self.function_file_path,
        }


class DataOrganize1Dialog(QDialog):
    """Prototype UI for CSV cleanup and transformation recipes."""

    STEP_TYPES = [
        '地番住所プレフィックス',
        '文字列結合',
        '地番整理',
        '日付の統一',
        '空白・全角半角の整理',
        '不要行の除外',
        '列の削除',
        'コラム名の変更',
        '列の順序の変更',
        '列の分割',
        'カスタム関数',
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('データ整理１ ー CSV下処理')
        self.resize(dpi_px(1120), dpi_px(820))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(dpi_px(14), dpi_px(14), dpi_px(14), dpi_px(14))
        main_layout.setSpacing(dpi_px(10))

        title = QLabel('データ整理１ ー CSV下処理')
        title.setStyleSheet('font-size: 17px; font-weight: 600;')
        main_layout.addWidget(title)

        io_group = QGroupBox('入出力')
        io_layout = QGridLayout(io_group)
        io_layout.setColumnStretch(1, 1)
        io_layout.setHorizontalSpacing(dpi_px(8))
        io_layout.setVerticalSpacing(dpi_px(6))

        self.input_csv_edit = QLineEdit()
        self.input_csv_edit.setPlaceholderText('下処理するCSVファイル')
        self.input_csv_edit.setText('')
        input_browse = QPushButton('参照')
        input_browse.clicked.connect(lambda: self._browse_file(self.input_csv_edit, save=False))

        self.output_csv_edit = QLineEdit()
        self.output_csv_edit.setPlaceholderText('出力CSVファイル')
        self.output_csv_edit.setText('')
        output_browse = QPushButton('参照')
        output_browse.clicked.connect(lambda: self._browse_file(self.output_csv_edit, save=True))

        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItems([',', '\\t', ';'])
        self.input_encoding_combo = QComboBox()
        self.input_encoding_combo.addItems(['UTF-8', 'CP932', 'Shift_JIS'])
        self.output_encoding_combo = QComboBox()
        self.output_encoding_combo.addItems(['UTF-8', 'CP932', 'Shift_JIS'])
        self.preview_status_label = QLabel('')

        io_layout.addWidget(QLabel('入力CSV'), 0, 0)
        io_layout.addWidget(self.input_csv_edit, 0, 1)
        io_layout.addWidget(input_browse, 0, 2)
        io_layout.addWidget(QLabel('出力CSV'), 1, 0)
        io_layout.addWidget(self.output_csv_edit, 1, 1)
        io_layout.addWidget(output_browse, 1, 2)
        io_layout.addWidget(QLabel('区切り'), 2, 0)
        io_layout.addWidget(self.delimiter_combo, 2, 1)
        io_layout.addWidget(QLabel('入力文字コード'), 2, 2)
        io_layout.addWidget(self.input_encoding_combo, 2, 3)
        io_layout.addWidget(QLabel('出力文字コード'), 2, 4)
        io_layout.addWidget(self.output_encoding_combo, 2, 5)
        io_layout.addWidget(self.preview_status_label, 3, 1, 1, 5)
        main_layout.addWidget(io_group)

        splitter = QSplitter(Qt.Horizontal)

        steps_panel = QWidget()
        steps_panel.setMinimumHeight(dpi_px(300))
        steps_layout = QVBoxLayout(steps_panel)
        steps_layout.setContentsMargins(0, 0, 0, 0)
        steps_layout.setSpacing(dpi_px(8))

        step_toolbar = QHBoxLayout()
        self.add_step_button = QPushButton('ステップ追加')
        self.delete_step_button = QPushButton('削除')
        self.up_step_button = QPushButton('上へ')
        self.down_step_button = QPushButton('下へ')
        self.add_step_button.clicked.connect(self.add_step)
        self.delete_step_button.clicked.connect(self.delete_step)
        self.up_step_button.clicked.connect(self.move_step_up)
        self.down_step_button.clicked.connect(self.move_step_down)
        step_toolbar.addWidget(self.add_step_button)
        step_toolbar.addWidget(self.delete_step_button)
        step_toolbar.addWidget(self.up_step_button)
        step_toolbar.addWidget(self.down_step_button)
        step_toolbar.addStretch(1)
        steps_layout.addLayout(step_toolbar)

        self.steps_table = QTableWidget(7, 4)
        self.steps_table.setHorizontalHeaderLabels(['有効', '処理', '対象列', '設定概要'])
        self.steps_table.verticalHeader().setVisible(True)
        self.steps_table.setMinimumHeight(dpi_px(260))
        self.steps_table.verticalHeader().setDefaultSectionSize(dpi_px(32))
        self.steps_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.steps_table.horizontalHeader().setStretchLastSection(True)
        self.steps_table.setColumnWidth(0, dpi_px(54))
        self.steps_table.setColumnWidth(1, dpi_px(150))
        self.steps_table.setColumnWidth(2, dpi_px(320))
        self.steps_table.itemChanged.connect(self._on_steps_table_item_changed)
        self.step_type_combos = []
        self.target_column_widgets_by_row = []
        self.current_headers = []
        self.custom_function_configs = {}
        self.row_filter_configs = {}
        self._populate_blank_steps()
        steps_layout.addWidget(self.steps_table, 1)

        self.target_column_combo = None
        main_layout.addWidget(steps_panel, 2)

        preview_group = QGroupBox('プレビュー')
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(dpi_px(10), dpi_px(8), dpi_px(10), dpi_px(10))
        preview_layout.setSpacing(dpi_px(6))
        preview_layout.addWidget(QLabel('現状のプレビュー'))
        self.preview_table = QTableWidget(0, 0)
        self.preview_table.setMinimumHeight(dpi_px(150))
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        preview_layout.addWidget(self.preview_table)
        preview_layout.addWidget(QLabel('変更後のプレビュー（実装済み処理のみ反映）'))
        self.changed_preview_table = QTableWidget(0, 0)
        self.changed_preview_table.setMinimumHeight(dpi_px(150))
        self.changed_preview_table.horizontalHeader().setStretchLastSection(True)
        preview_layout.addWidget(self.changed_preview_table)
        main_layout.addWidget(preview_group, 3)

        buttons = QDialogButtonBox()
        buttons.addButton('設定を読込', QDialogButtonBox.ActionRole)
        buttons.addButton('設定を保存', QDialogButtonBox.ActionRole)
        preview_button = buttons.addButton('プレビュー更新', QDialogButtonBox.ActionRole)
        load_button = buttons.addButton('設定を読込', QDialogButtonBox.ActionRole)
        save_button = buttons.addButton('設定を保存', QDialogButtonBox.ActionRole)
        default_load_button = buttons.addButton('初期設定読込', QDialogButtonBox.ActionRole)
        default_save_button = buttons.addButton('初期設定上書', QDialogButtonBox.ActionRole)
        for obsolete_button in buttons.buttons()[:2]:
            obsolete_button.hide()
        load_button.clicked.connect(self.load_config_dialog)
        save_button.clicked.connect(self.save_config_dialog)
        default_load_button.clicked.connect(self.load_default_config)
        default_save_button.clicked.connect(self.save_default_config)
        preview_button.clicked.connect(self.load_preview_from_input)
        run_button = buttons.addButton('実行（実装済み処理）', QDialogButtonBox.AcceptRole)
        run_button.clicked.connect(self.run_processing)
        close_button = buttons.addButton(QDialogButtonBox.Close)
        close_button.clicked.connect(self.reject)
        main_layout.addWidget(buttons)
        buttons.hide()

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(dpi_px(8))
        footer_load_button = QPushButton('設定を読込')
        footer_save_button = QPushButton('設定を保存')
        footer_default_load_button = QPushButton('初期設定読込')
        footer_default_save_button = QPushButton('初期設定上書')
        footer_run_button = QPushButton('実行（実装済み処理）')
        footer_preview_button = QPushButton('プレビュー更新')
        footer_close_button = QPushButton('Close')
        footer_load_button.clicked.connect(self.load_config_dialog)
        footer_save_button.clicked.connect(self.save_config_dialog)
        footer_default_load_button.clicked.connect(self.load_default_config)
        footer_default_save_button.clicked.connect(self.save_default_config)
        footer_run_button.clicked.connect(self.run_processing)
        footer_preview_button.clicked.connect(self.load_preview_from_input)
        footer_close_button.clicked.connect(self.reject)
        footer_layout.addWidget(footer_load_button)
        footer_layout.addWidget(footer_save_button)
        footer_layout.addWidget(footer_default_load_button)
        footer_layout.addWidget(footer_default_save_button)
        footer_layout.addStretch(1)
        footer_layout.addWidget(footer_run_button)
        footer_layout.addWidget(footer_preview_button)
        footer_layout.addWidget(footer_close_button)
        main_layout.addWidget(footer)

        self.load_preview_from_input()

    def _populate_sample_steps(self):
        samples = [
            ['ON', '文字列結合', '所在地, 地番', '所在地 + 地番 -> 所在地番'],
            ['ON', '日付の統一', '取得年月日（登記年月日）', 'H08.03.15 などを西暦へ統一'],
            ['ON', '列の削除', '空列1, 空列2', '空列1, 空列2 を削除'],
            ['ON', 'コラム名の変更', '公簿面積（又は実測面積）（㎡）', '面積_㎡へ変更'],
            ['ON', '地番整理', '地番', '地番整理, 地番説明 を追加'],
            ['ON', '列の順序の変更', '全列', ''],
            ['', 'カスタム関数', '', ''],
        ]
        for row, values in enumerate(samples):
            self._set_enabled_cell(row, values[0])
            self._set_step_type_combo(row, values[1])
            self._set_target_columns_widget(row, values[2])
            self.steps_table.setItem(row, 3, QTableWidgetItem(values[3]))

    def _populate_blank_steps(self):
        self._updating_steps = True
        try:
            for row in range(self.steps_table.rowCount()):
                self._set_enabled_cell(row, '')
                self._set_step_type_combo(row, self.STEP_TYPES[0])
                self._set_enabled_cell(row, '')
                self._set_target_columns_widget(row, '')
                self.steps_table.setItem(row, 3, QTableWidgetItem(''))
        finally:
            self._updating_steps = False

    def ask_load_default_config_on_startup(self):
        path = self._default_config_path_silent()
        if not path or not os.path.exists(path):
            return
        reply = QMessageBox.question(
            self,
            'データ整理１',
            '初期設定を読み込みますか？\n\n{}'.format(path),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.set_config(json.load(f))
            except Exception as exc:
                QMessageBox.critical(self, 'データ整理１', str(exc))

    def _current_step_row(self):
        row = self.steps_table.currentRow()
        if row < 0 and self.steps_table.selectedIndexes():
            row = self.steps_table.selectedIndexes()[0].row()
        if row < 0 and self.steps_table.rowCount() > 0:
            row = 0
        return row

    def _step_row_data(self, row):
        return {
            'enabled': self._table_text(row, 0),
            'type': self._table_text(row, 1),
            'target': self._table_text(row, 2),
            'summary': self._table_text(row, 3),
            'custom_config': self.custom_function_configs.get(row),
            'row_filter_config': self.row_filter_configs.get(row),
        }

    def _set_step_row_data(self, row, data):
        self._set_step_type_combo(row, data.get('type') or self.STEP_TYPES[0])
        self._set_enabled_cell(row, data.get('enabled') or '')
        self._set_target_columns_widget(row, data.get('target') or '')
        self.steps_table.setItem(row, 3, QTableWidgetItem(data.get('summary') or ''))

    def _all_step_rows_data(self):
        return [self._step_row_data(row) for row in range(self.steps_table.rowCount())]

    def _rebuild_step_rows(self, rows, selected_row):
        self._updating_steps = True
        try:
            self.steps_table.setRowCount(0)
            self.steps_table.setRowCount(len(rows))
            self.step_type_combos = []
            self.target_column_widgets_by_row = []
            self.custom_function_configs = {}
            self.row_filter_configs = {}
            for row, data in enumerate(rows):
                self._set_step_row_data(row, data)
                if data.get('custom_config'):
                    self.custom_function_configs[row] = data['custom_config']
                if data.get('row_filter_config'):
                    self.row_filter_configs[row] = data['row_filter_config']
            if rows:
                selected_row = max(0, min(selected_row, len(rows) - 1))
                self.steps_table.selectRow(selected_row)
                self.steps_table.setCurrentCell(selected_row, 0)
        finally:
            self._updating_steps = False
        self.load_preview_from_input()

    def add_step(self):
        rows = self._all_step_rows_data()
        current = self._current_step_row()
        insert_at = current + 1 if current >= 0 else len(rows)
        rows.insert(insert_at, {
            'enabled': 'ON',
            'type': self.STEP_TYPES[0],
            'target': '',
            'summary': '',
            'custom_config': None,
            'row_filter_config': None,
        })
        self._rebuild_step_rows(rows, insert_at)

    def delete_step(self):
        if self.steps_table.rowCount() <= 0:
            return
        rows = self._all_step_rows_data()
        current = self._current_step_row()
        if current < 0:
            return
        if len(rows) == 1:
            rows = [{
                'enabled': '',
                'type': self.STEP_TYPES[0],
                'target': '',
                'summary': '',
                'custom_config': None,
                'row_filter_config': None,
            }]
            self._rebuild_step_rows(rows, 0)
            return
        rows.pop(current)
        self._rebuild_step_rows(rows, min(current, len(rows) - 1))

    def move_step_up(self):
        current = self._current_step_row()
        if current <= 0:
            return
        rows = self._all_step_rows_data()
        rows[current - 1], rows[current] = rows[current], rows[current - 1]
        self._rebuild_step_rows(rows, current - 1)

    def move_step_down(self):
        current = self._current_step_row()
        if current < 0 or current >= self.steps_table.rowCount() - 1:
            return
        rows = self._all_step_rows_data()
        rows[current + 1], rows[current] = rows[current], rows[current + 1]
        self._rebuild_step_rows(rows, current + 1)

    def _set_step_type_combo(self, row, value):
        combo = QComboBox()
        combo.addItems(self.STEP_TYPES)
        if combo.findText(value) >= 0:
            combo.setCurrentText(value)
        combo.currentTextChanged.connect(lambda text, row=row: self._on_step_type_changed(row, text))
        self.steps_table.setCellWidget(row, 1, combo)
        self.step_type_combos.append(combo)
        self._on_step_type_changed(row, combo.currentText())

    def _set_target_columns_widget(self, row, value):
        selected = [part.strip() for part in value.replace('、', ',').split(',') if part.strip()]
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(dpi_px(2), dpi_px(2), dpi_px(2), dpi_px(2))
        layout.setSpacing(dpi_px(4))

        edit = QLineEdit(', '.join(selected))
        select_button = QPushButton('選択')
        select_button.setMaximumWidth(54)
        edit.editingFinished.connect(self.load_preview_from_input)
        select_button.clicked.connect(lambda checked=False, row=row: self.open_step_selection(row))
        layout.addWidget(edit, 1)
        layout.addWidget(select_button)
        self.steps_table.setCellWidget(row, 2, widget)
        self.target_column_widgets_by_row.append((edit, select_button))

    def _set_combo_text(self, combo, value):
        value = value or ''
        if value and combo.findText(value) < 0:
            combo.addItem(value)
        combo.setCurrentText(value)

    def _on_step_type_changed(self, row, step_type):
        current = self._table_text(row, 0)
        if step_type == '地番住所プレフィックス':
            if current == '':
                self._set_enabled_cell(row, 'ON')
            self.load_preview_from_input()
            return
        if step_type in ('文字列結合', '地番整理', '日付の統一', '空白・全角半角の整理', '不要行の除外', '列の削除', 'コラム名の変更', '列の順序の変更', 'カスタム関数'):
            if current in ('', '（未）'):
                self._set_enabled_cell(row, 'ON')
        else:
            self._set_enabled_cell(row, '（未）')
        self.load_preview_from_input()

    def open_step_selection(self, row):
        step_type = self._table_text(row, 1)
        if step_type == '地番住所プレフィックス':
            self.open_chiban_prefix_selection(row)
            return
        if step_type == '文字列結合':
            self.open_string_concat_selection(row)
            return
        if step_type == '地番整理':
            self.open_chiban_organize_selection(row)
            return
        if step_type == '日付の統一':
            self.open_date_normalize_selection(row)
            return
        if step_type == 'コラム名の変更':
            self.open_column_rename_selection(row)
            return
        if step_type == '空白・全角半角の整理':
            self.open_text_normalize_selection(row)
            return
        if step_type == '不要行の除外':
            self.open_row_filter_selection(row)
            return
        if step_type == '列の削除':
            self.open_column_delete_selection(row)
            return
        if step_type == '列の順序の変更':
            self.open_column_reorder_selection(row)
            return
        if step_type == 'カスタム関数':
            self.open_custom_function_selection(row)
            return
        QMessageBox.information(self, 'データ整理１', 'この処理はまだ設定UIがありません。')

    def apply_template(self, label):
        if label.startswith('地番:'):
            row = self._template_target_row()
            source_field = '地番' if '地番' in self.current_headers else self.target_column_combo.currentText().strip() or '地番'
            self._set_enabled_cell(row, 'ON')
            self._set_step_type_combo(row, '地番整理')
            self._target_columns_edit(row).setText(source_field)
            self.steps_table.setItem(row, 3, QTableWidgetItem('地番整理, 地番説明 を追加'))
            self.steps_table.selectRow(row)
            self.load_preview_from_input()
            return
        if label.startswith('日付:'):
            row = self._template_target_row()
            source_field = '取得年月日（登記年月日）' if '取得年月日（登記年月日）' in self.current_headers else self.target_column_combo.currentText().strip()
            self._set_enabled_cell(row, 'ON')
            self._set_step_type_combo(row, '日付の統一')
            self._target_columns_edit(row).setText(source_field)
            self.steps_table.setItem(row, 3, QTableWidgetItem('出力形式: YYYY-MM-DD'))
            self.steps_table.selectRow(row)
            self.load_preview_from_input()
            return
        if label.startswith('空白'):
            row = self._template_target_row()
            self._set_enabled_cell(row, 'ON')
            self._set_step_type_combo(row, '空白・全角半角の整理')
            self._target_columns_edit(row).setText(self.target_column_combo.currentText().strip())
            self.steps_table.setItem(row, 3, QTableWidgetItem('半角化, 空白削除'))
            self.steps_table.selectRow(row)
            self.load_preview_from_input()
            return
        if label.startswith('不要行'):
            row = self._template_target_row()
            self._set_enabled_cell(row, 'ON')
            self._set_step_type_combo(row, '不要行の除外')
            self.steps_table.selectRow(row)
            self.open_row_filter_selection(row)
            return
        if label.startswith('列名'):
            row = self._template_target_row()
            self._set_enabled_cell(row, 'ON')
            self._set_step_type_combo(row, 'コラム名の変更')
            self.steps_table.selectRow(row)
            self.open_column_rename_selection(row)

    def _template_target_row(self):
        current = self._current_step_row()
        if current >= 0 and self._table_text(current, 0).upper() != 'ON':
            return current
        rows = self._all_step_rows_data()
        insert_at = current + 1 if current >= 0 else len(rows)
        rows.insert(insert_at, {
            'enabled': '',
            'type': self.STEP_TYPES[0],
            'target': '',
            'summary': '',
            'custom_config': None,
            'row_filter_config': None,
        })
        self._rebuild_step_rows(rows, insert_at)
        return insert_at

    def open_chiban_prefix_selection(self, row):
        headers = self._headers_for_selection(row)
        if not headers:
            self.load_preview_from_input()
            headers = self._headers_for_selection(row)
        if not headers:
            QMessageBox.warning(self, 'データ整理１', '先に入力CSVを読み込んでください。')
            return

        config = self._chiban_prefix_config(row)
        selected_fields = [part.strip() for part in self._table_text(row, 2).split(',') if part.strip()]
        selected_field = selected_fields[0] if selected_fields else config.get('source_field', '')
        dialog = ChibanPrefixSelectionDialog(
            headers,
            selected_field,
            config.get('output_field', ''),
            config.get('operation', 'remove'),
            config.get('prefix', '大阪府大阪市'),
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        self._target_columns_edit(row).setText(dialog.source_field())
        summary = json.dumps({
            'operation': dialog.operation(),
            'prefix': dialog.prefix(),
            'output_field': dialog.output_field(),
        }, ensure_ascii=False)
        self.steps_table.setItem(row, 3, QTableWidgetItem(summary))
        self.load_preview_from_input()

    def open_chiban_organize_selection(self, row):
        headers = self._headers_for_selection(row)
        if not headers:
            self.load_preview_from_input()
            headers = self._headers_for_selection(row)
        if not headers:
            QMessageBox.warning(self, 'データ整理１', '先に入力CSVを読み込んでください。')
            return

        selected_field = self._table_text(row, 2) or ('地番' if '地番' in headers else '')
        field, accepted = QInputDialog.getItem(
            self,
            '地番整理',
            '整理する地番列',
            headers,
            headers.index(selected_field) if selected_field in headers else 0,
            False,
        )
        if not accepted or not field:
            return

        self._target_columns_edit(row).setText(field)
        self.steps_table.setItem(row, 3, QTableWidgetItem('地番整理, 地番説明 を追加'))
        self.load_preview_from_input()

    def open_string_concat_selection(self, row):
        if self._table_text(row, 1) != '文字列結合':
            QMessageBox.information(self, 'データ整理１', 'この選択UIは文字列結合用です。')
            return
        headers = self._headers_for_selection(row)
        if not headers:
            self.load_preview_from_input()
            headers = self._headers_for_selection(row)
        if not headers:
            QMessageBox.warning(self, 'データ整理１', '先に入力CSVを読み込んでください。')
            return

        selected_fields = [part.strip() for part in self._table_text(row, 2).split(',') if part.strip()]
        dialog = StringConcatSelectionDialog(
            headers,
            selected_fields,
            self._string_concat_output_field(row),
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        selected_fields = dialog.selected_fields()
        output_field = dialog.output_field()
        self._target_columns_edit(row).setText(', '.join(selected_fields))
        self.steps_table.setItem(
            row,
            3,
            QTableWidgetItem('{} -> {}'.format(' + '.join(selected_fields), output_field)),
        )
        self.load_preview_from_input()

    def open_column_rename_selection(self, row):
        headers = self._headers_for_selection(row)
        if not headers:
            self.load_preview_from_input()
            headers = self._headers_for_selection(row)
        if not headers:
            QMessageBox.warning(self, 'データ整理１', '先に入力CSVを読み込んでください。')
            return

        selected_fields = [part.strip() for part in self._table_text(row, 2).split(',') if part.strip()]
        target_fields = self._column_rename_target_fields(row)
        dialog = ColumnRenameSelectionDialog(
            headers,
            selected_fields,
            target_fields,
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        selected_fields = dialog.selected_fields()
        target_fields = dialog.target_fields()
        self._target_columns_edit(row).setText(', '.join(selected_fields))
        self.steps_table.setItem(
            row,
            3,
            QTableWidgetItem('{} -> {}'.format(', '.join(selected_fields), ', '.join(target_fields))),
        )
        self.load_preview_from_input()

    def open_column_delete_selection(self, row):
        headers = self._headers_for_selection(row)
        if not headers:
            self.load_preview_from_input()
            headers = self._headers_for_selection(row)
        if not headers:
            QMessageBox.warning(self, 'データ整理１', '先に入力CSVを読み込んでください。')
            return

        selected_fields = [part.strip() for part in self._table_text(row, 2).split(',') if part.strip()]
        dialog = ColumnDeleteSelectionDialog(
            headers,
            selected_fields,
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        selected_fields = dialog.selected_fields()
        self._target_columns_edit(row).setText(', '.join(selected_fields))
        self.steps_table.setItem(
            row,
            3,
            QTableWidgetItem('{} を削除'.format(', '.join(selected_fields))),
        )
        self.load_preview_from_input()

    def open_text_normalize_selection(self, row):
        headers = self._headers_for_selection(row)
        if not headers:
            self.load_preview_from_input()
            headers = self._headers_for_selection(row)
        if not headers:
            QMessageBox.warning(self, 'データ整理１', '先に入力CSVを読み込んでください。')
            return

        selected_fields = [part.strip() for part in self._table_text(row, 2).split(',') if part.strip()]
        dialog = TextNormalizeSelectionDialog(
            headers,
            selected_fields,
            self._text_normalize_operations(row),
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        selected_fields = dialog.selected_fields()
        operations = dialog.operations()
        self._target_columns_edit(row).setText(', '.join(selected_fields))
        self.steps_table.setItem(
            row,
            3,
            QTableWidgetItem(', '.join(self._text_normalize_operation_labels(operations))),
        )
        self.load_preview_from_input()

    def open_date_normalize_selection(self, row):
        headers = self._headers_for_selection(row)
        if not headers:
            self.load_preview_from_input()
            headers = self._headers_for_selection(row)
        if not headers:
            QMessageBox.warning(self, 'データ整理１', '先に入力CSVを読み込んでください。')
            return

        selected_fields = [part.strip() for part in self._table_text(row, 2).split(',') if part.strip()]
        dialog = DateNormalizeSelectionDialog(
            headers,
            selected_fields,
            self._date_normalize_output_format(row),
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        selected_fields = dialog.selected_fields()
        self._target_columns_edit(row).setText(', '.join(selected_fields))
        self.steps_table.setItem(
            row,
            3,
            QTableWidgetItem('出力形式: {}'.format(dialog.output_format_label())),
        )
        self.load_preview_from_input()

    def open_row_filter_selection(self, row):
        headers = self._headers_for_selection(row)
        if not headers:
            self.load_preview_from_input()
            headers = self._headers_for_selection(row)
        if not headers:
            QMessageBox.warning(self, 'データ整理１', '先に入力CSVを読み込んでください。')
            return

        current_step = self.row_filter_configs.get(row)
        if not current_step:
            current_step = parse_row_filter_step(self._table_text(row, 2), self._table_text(row, 3))
        selected_fields = [
            rule.get('field')
            for rule in current_step.get('rules', [])
            if rule.get('field')
        ] or [part.strip() for part in self._table_text(row, 2).split(',') if part.strip()]
        dialog = RowFilterSelectionDialog(
            headers,
            selected_fields,
            current_step.get('condition', 'empty'),
            current_step.get('value', ''),
            current_step.get('match_mode', 'any'),
            current_step.get('filter_kind', 'text'),
            current_step.get('value2', ''),
            current_step.get('action', 'exclude'),
            self,
            current_step.get('rules') or None,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        rules = dialog.rules()
        config = {
            'type': 'row_filter',
            'action': dialog.action(),
            'match_mode': dialog.match_mode(),
            'rules': rules,
        }
        self.row_filter_configs[row] = config
        selected_fields = [rule.get('field') for rule in rules if rule.get('field')]
        self._target_columns_edit(row).setText(', '.join(selected_fields))
        summary = self._row_filter_summary(config)
        self.steps_table.setItem(row, 3, QTableWidgetItem(summary))
        self.load_preview_from_input()

    def _row_filter_summary(self, config):
        action_label = '条件に合う行だけを残す' if config.get('action') == 'include' else '条件に合う行を除外する'
        match_label = 'すべて' if config.get('match_mode') == 'all' else 'いずれか'
        parts = []
        for rule in config.get('rules') or []:
            field = rule.get('field', '')
            kind = self._row_filter_kind_label(rule.get('filter_kind') or 'text')
            condition = self._row_filter_condition_label(rule.get('filter_kind') or 'text', rule.get('condition') or 'empty')
            value = rule.get('value') or ''
            value2 = rule.get('value2') or ''
            text = '{}: {} {}'.format(field, kind, condition)
            if value:
                text = '{}={}'.format(text, value)
            if value2:
                text = '{}～{}'.format(text, value2)
            parts.append(text)
        detail = '; '.join(parts)
        return '{} / {} / {}'.format(action_label, match_label, detail)

    def _row_filter_kind_label(self, kind):
        return next((label for label, data in RowFilterSelectionDialog.FILTER_KINDS if data == kind), kind)

    def _row_filter_condition_label(self, kind, condition):
        return next(
            (
                label
                for label, data in RowFilterSelectionDialog.CONDITIONS_BY_KIND.get(kind, [])
                if data == condition
            ),
            condition,
        )

    def open_column_reorder_selection(self, row):
        headers = self._headers_for_selection(row)
        if not headers:
            self.load_preview_from_input()
            headers = self._headers_for_selection(row)
        if not headers:
            QMessageBox.warning(self, 'データ整理１', '先に入力CSVを読み込んでください。')
            return

        dialog = ColumnReorderDialog(
            headers,
            self._column_reorder_order_map(row),
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        order_map = dialog.order_map()
        ordered_fields = [
            field
            for field, _ in sorted(order_map.items(), key=lambda item: item[1])
        ]
        summary = ', '.join(['{}:{}'.format(field, order_map[field]) for field in ordered_fields])
        self._target_columns_edit(row).setText('全列')
        self.steps_table.setItem(row, 3, QTableWidgetItem(summary))
        self.load_preview_from_input()

    def open_custom_function_selection(self, row):
        headers = self._headers_for_selection(row)
        if not headers:
            self.load_preview_from_input()
            headers = self._headers_for_selection(row)
        if not headers:
            QMessageBox.warning(self, 'データ整理１', '先に入力CSVを読み込んでください。')
            return

        dialog = CustomPythonFunctionDialog(
            headers,
            self.custom_function_configs.get(row),
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        config = dialog.config()
        self.custom_function_configs[row] = config
        output_label = '新規列' if config['output_mode'] == 'new' else '既存列'
        self._target_columns_edit(row).setText(', '.join(config['input_fields']))
        self.steps_table.setItem(
            row,
            3,
            QTableWidgetItem('{} -> {}: {}'.format(
                ', '.join(config['input_fields']),
                output_label,
                config['output_field'],
            )),
        )
        self.load_preview_from_input()

    def _target_columns_edit(self, row):
        return self.steps_table.cellWidget(row, 2).layout().itemAt(0).widget()

    def _string_concat_output_field(self, row):
        summary = self._table_text(row, 3)
        if '->' in summary:
            return summary.split('->', 1)[1].strip()
        return ''

    def _chiban_prefix_config(self, row):
        step = parse_chiban_prefix_step(
            self._table_text(row, 2),
            self._table_text(row, 3),
        )
        return {
            'source_field': (step.get('source_fields') or [''])[0],
            'operation': step.get('operation') or 'remove',
            'prefix': step.get('prefix') or '大阪府大阪市',
            'output_field': step.get('output_field') or '',
        }

    def _column_rename_target_fields(self, row):
        summary = self._table_text(row, 3)
        if '->' not in summary:
            return []
        return [
            field.strip()
            for field in summary.split('->', 1)[1].replace('、', ',').split(',')
            if field.strip()
        ]

    def _column_reorder_order_map(self, row):
        return parse_column_reorder_step(self._table_text(row, 3)).get('order_map', {})

    def _text_normalize_operations(self, row):
        return parse_text_normalize_step(
            self._table_text(row, 2),
            self._table_text(row, 3),
        ).get('operations', [])

    def _text_normalize_operation_labels(self, operations):
        labels = []
        if 'to_halfwidth' in operations:
            labels.append('半角化')
        if 'to_fullwidth' in operations:
            labels.append('全角化')
        if 'remove_spaces' in operations:
            labels.append('空白削除')
        return labels

    def _date_normalize_output_format(self, row):
        return parse_date_normalize_step(
            self._table_text(row, 2),
            self._table_text(row, 3),
        ).get('output_format', 'yyyy-mm-dd')

    def _headers_for_selection(self, row):
        headers = self._headers_before_step(row)
        return headers or list(self.current_headers)

    def _headers_before_step(self, target_row):
        headers = list(self.current_headers)
        if not headers:
            return headers

        steps = []
        for row in range(min(target_row, self.steps_table.rowCount())):
            if self._table_text(row, 0).upper() != 'ON':
                continue
            step_type = self._table_text(row, 1)
            if step_type == '地番住所プレフィックス':
                step = parse_chiban_prefix_step(
                    self._table_text(row, 2),
                    self._table_text(row, 3),
                )
                if step.get('source_fields') and step.get('prefix'):
                    steps.append(step)
                continue

            if step_type == '文字列結合':
                step = parse_string_concat_step(
                    self._table_text(row, 2),
                    self._table_text(row, 3),
                )
                if step.get('source_fields') and step.get('output_field'):
                    steps.append(step)
            elif step_type == '地番整理':
                step = parse_chiban_organize_step(
                    self._table_text(row, 2),
                    self._table_text(row, 3),
                )
                if step.get('source_field'):
                    steps.append(step)
            elif step_type == '列の削除':
                step = parse_column_delete_step(self._table_text(row, 2))
                if step.get('source_fields'):
                    steps.append(step)
            elif step_type == 'コラム名の変更':
                step = parse_column_rename_step(
                    self._table_text(row, 2),
                    self._table_text(row, 3),
                )
                if step.get('source_fields') and step.get('target_fields'):
                    steps.append(step)
            elif step_type == '列の順序の変更':
                step = parse_column_reorder_step(self._table_text(row, 3))
                if step.get('order_map'):
                    steps.append(step)
            elif step_type == 'カスタム関数':
                config = self.custom_function_configs.get(row)
                if config:
                    steps.append({
                        'type': 'custom_python',
                        'input_fields': config.get('input_fields') or [],
                        'output_mode': config.get('output_mode') or 'new',
                        'output_field': config.get('output_field') or '',
                        'code': config.get('code') or '',
                    })

        if not steps:
            return headers
        processed_headers, _ = apply_processing_steps(headers, [], steps)
        return processed_headers

    def load_preview_from_input(self):
        if getattr(self, '_updating_steps', False):
            return
        if not (
            hasattr(self, 'preview_table')
            and hasattr(self, 'changed_preview_table')
        ):
            return

        csv_path = self.input_csv_edit.text().strip()
        if not csv_path:
            self.preview_status_label.setText('入力CSVを指定してください。')
            return
        if not os.path.exists(csv_path):
            self.preview_status_label.setText('入力CSVが見つかりません: {}'.format(csv_path))
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            self.changed_preview_table.setRowCount(0)
            self.changed_preview_table.setColumnCount(0)
            return

        encodings = [
            self.input_encoding_combo.currentText(),
            'UTF-8',
            'utf-8-sig',
            'CP932',
            'Shift_JIS',
        ]
        last_error = None
        for encoding in dict.fromkeys(encodings):
            try:
                preview_limit = 8
                processing_preview_limit = 500 if self._has_row_filter_step() else preview_limit
                headers, rows = read_csv_rows(
                    csv_path,
                    encoding,
                    self._delimiter(),
                    max_rows=processing_preview_limit,
                )
                self._set_preview_data(self.preview_table, headers, rows[:preview_limit])
                changed_headers, changed_rows = apply_processing_steps(
                    headers,
                    rows,
                    self._processing_steps(),
                )
                changed_count = max(0, len(rows) - len(changed_rows))
                self._set_preview_data(self.changed_preview_table, changed_headers, changed_rows[:preview_limit])
                self._refresh_target_column_options(headers)
                self.input_encoding_combo.setCurrentText(encoding)
                self.preview_status_label.setText(
                    '実データを表示中: {} 行プレビュー / 変更後 {} 行表示 / 減少 {} 行 / 文字コード {}'.format(
                        min(len(rows), preview_limit),
                        min(len(changed_rows), preview_limit),
                        changed_count,
                        encoding,
                    )
                )
                return
            except Exception as exc:
                last_error = exc

        self.preview_status_label.setText('CSVを読み込めませんでした: {}'.format(last_error))

    def _delimiter(self):
        delimiter = self.delimiter_combo.currentText()
        return '\t' if delimiter == '\\t' else delimiter

    def _processing_steps(self):
        steps = []
        for row in range(self.steps_table.rowCount()):
            enabled = self._table_text(row, 0).upper() == 'ON'
            step_type = self._table_text(row, 1)
            if not enabled:
                continue
            if step_type == '地番住所プレフィックス':
                step = parse_chiban_prefix_step(
                    self._table_text(row, 2),
                    self._table_text(row, 3),
                )
                if step.get('source_fields') and step.get('prefix'):
                    steps.append(step)
                continue
            if step_type == '文字列結合':
                step = parse_string_concat_step(
                    self._table_text(row, 2),
                    self._table_text(row, 3),
                )
                if step.get('source_fields') and step.get('output_field'):
                    steps.append(step)
            elif step_type == '地番整理':
                step = parse_chiban_organize_step(
                    self._table_text(row, 2),
                    self._table_text(row, 3),
                )
                if step.get('source_field'):
                    steps.append(step)
            elif step_type == '日付の統一':
                step = parse_date_normalize_step(
                    self._table_text(row, 2),
                    self._table_text(row, 3),
                )
                if step.get('source_fields') and step.get('output_format'):
                    steps.append(step)
            elif step_type == '空白・全角半角の整理':
                step = parse_text_normalize_step(
                    self._table_text(row, 2),
                    self._table_text(row, 3),
                )
                if step.get('source_fields') and step.get('operations'):
                    steps.append(step)
            elif step_type == '不要行の除外':
                step = self._row_filter_step_for_row(row)
                if (step.get('rules') or step.get('source_fields')) and (step.get('condition') or step.get('rules')):
                    steps.append(step)
            elif step_type == 'コラム名の変更':
                step = parse_column_rename_step(
                    self._table_text(row, 2),
                    self._table_text(row, 3),
                )
                if step.get('source_fields') and step.get('target_fields'):
                    steps.append(step)
            elif step_type == '列の削除':
                step = parse_column_delete_step(self._table_text(row, 2))
                if step.get('source_fields'):
                    steps.append(step)
            elif step_type == '列の順序の変更':
                step = parse_column_reorder_step(self._table_text(row, 3))
                if step.get('order_map'):
                    steps.append(step)
            elif step_type == 'カスタム関数':
                config = self.custom_function_configs.get(row)
                if config:
                    steps.append({
                        'type': 'custom_python',
                        'input_fields': config.get('input_fields') or [],
                        'output_mode': config.get('output_mode') or 'new',
                        'output_field': config.get('output_field') or '',
                        'code': config.get('code') or '',
                    })
        return steps

    def _row_filter_step_for_row(self, row):
        config = self.row_filter_configs.get(row)
        if config:
            rules = config.get('rules') or []
            return {
                'type': 'row_filter',
                'source_fields': [rule.get('field') for rule in rules if rule.get('field')],
                'action': config.get('action') or 'exclude',
                'match_mode': config.get('match_mode') or 'any',
                'rules': rules,
            }
        return parse_row_filter_step(
            self._table_text(row, 2),
            self._table_text(row, 3),
        )

    def _has_row_filter_step(self):
        for row in range(self.steps_table.rowCount()):
            if self._table_text(row, 0).upper() == 'ON' and self._table_text(row, 1) == '不要行の除外':
                return True
        return False

    def _set_enabled_cell(self, row, value):
        text = (value or '').strip()
        enabled = text.upper() == 'ON'
        item = QTableWidgetItem('ON' if enabled else text)
        if text == '（未）':
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        else:
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
        item.setTextAlignment(Qt.AlignCenter)
        self.steps_table.setItem(row, 0, item)

    def _on_steps_table_item_changed(self, item):
        if getattr(self, '_updating_steps', False):
            return
        if not item or item.column() != 0:
            return
        checked = item.checkState() == Qt.Checked
        expected_text = 'ON' if checked else ''
        if item.text() != expected_text:
            self.steps_table.blockSignals(True)
            try:
                item.setText(expected_text)
            finally:
                self.steps_table.blockSignals(False)
        self.load_preview_from_input()

    def _table_text(self, row, col):
        if col == 0:
            item = self.steps_table.item(row, col)
            if not item:
                return ''
            if item.flags() & Qt.ItemIsUserCheckable:
                return 'ON' if item.checkState() == Qt.Checked else ''
            return item.text().strip()
        if col == 1:
            combo = self.steps_table.cellWidget(row, col)
            return combo.currentText().strip() if combo else ''
        if col == 2:
            widget = self.steps_table.cellWidget(row, col)
            if widget:
                edit = widget.layout().itemAt(0).widget()
                return edit.text().strip() if edit else ''
        item = self.steps_table.item(row, col)
        return item.text().strip() if item else ''

    def _set_preview_data(self, table, headers, rows):
        table.clear()
        table.setColumnCount(len(headers))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(headers)
        table.setVerticalHeaderLabels([str(index + 1) for index in range(len(rows))])
        for row_index, row in enumerate(rows):
            for col_index, header in enumerate(headers):
                value = row.get(header, '')
                table.setItem(row_index, col_index, QTableWidgetItem('' if value is None else str(value)))
        table.resizeColumnsToContents()

    def _refresh_target_column_options(self, headers):
        self.current_headers = list(headers)
        if not getattr(self, 'target_column_combo', None):
            return
        current = self.target_column_combo.currentText()
        self.target_column_combo.blockSignals(True)
        self.target_column_combo.clear()
        self.target_column_combo.addItems(headers)
        if current and self.target_column_combo.findText(current) >= 0:
            self.target_column_combo.setCurrentText(current)
        elif '地番' in headers:
            self.target_column_combo.setCurrentText('地番')
        self.target_column_combo.blockSignals(False)

    def get_config(self):
        return {
            'input_csv': self.input_csv_edit.text().strip(),
            'output_csv': self.output_csv_edit.text().strip(),
            'delimiter': self.delimiter_combo.currentText(),
            'input_encoding': self.input_encoding_combo.currentText(),
            'output_encoding': self.output_encoding_combo.currentText(),
            'steps': self._all_step_rows_data(),
        }

    def set_config(self, config):
        if not config:
            return
        self.input_csv_edit.setText(config.get('input_csv', ''))
        self.output_csv_edit.setText(config.get('output_csv', ''))
        self._set_combo_text(self.delimiter_combo, config.get('delimiter', ','))
        self._set_combo_text(self.input_encoding_combo, config.get('input_encoding', 'UTF-8'))
        self._set_combo_text(self.output_encoding_combo, config.get('output_encoding', 'UTF-8'))

        rows = config.get('steps') or []
        if rows:
            self._rebuild_step_rows(rows, 0)
        else:
            self.load_preview_from_input()

    def load_config_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            '設定JSONを読込',
            self._config_initial_dir(),
            'JSON (*.json);;All files (*.*)',
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.set_config(json.load(f))
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理１', str(exc))

    def save_config_dialog(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            '設定JSONを保存',
            self._config_initial_dir(),
            'JSON (*.json);;All files (*.*)',
        )
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        try:
            self._write_config(path, self.get_config())
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理１', str(exc))
        else:
            QMessageBox.information(self, 'データ整理１', '設定を保存しました。\n\n{}'.format(path))

    def load_default_config(self):
        path = self._default_config_path()
        if not path:
            return
        try:
            if not os.path.exists(path):
                QMessageBox.warning(
                    self,
                    'データ整理１',
                    '初期設定ファイルが見つかりません。\n「初期設定上書」で現在の設定を保存してください。\n\n{}'.format(path),
                )
                return
            with open(path, 'r', encoding='utf-8') as f:
                self.set_config(json.load(f))
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理１', str(exc))
        else:
            QMessageBox.information(self, 'データ整理１', '初期設定を読み込みました。\n\n{}'.format(path))

    def save_default_config(self):
        path = self._default_config_path()
        if not path:
            return
        try:
            self._write_config(path, self.get_config())
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理１', str(exc))
        else:
            QMessageBox.information(self, 'データ整理１', '初期設定を上書き保存しました。\n\n{}'.format(path))

    def _write_config(self, path, config):
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def _project_dir(self):
        project_path = QgsProject.instance().fileName()
        if project_path:
            project_dir = os.path.dirname(project_path)
            if project_dir:
                return project_dir
        return ''

    def _config_initial_dir(self):
        project_dir = self._project_dir()
        if project_dir:
            return project_dir
        input_csv = self.input_csv_edit.text().strip()
        if input_csv:
            folder = os.path.dirname(input_csv)
            if folder:
                return folder
        return ''

    def _default_config_path(self):
        project_dir = self._project_dir()
        if not project_dir:
            QMessageBox.warning(
                self,
                'データ整理１',
                'QGISプロジェクトが未保存です。\n先にプロジェクトを保存してください。',
            )
            return ''
        return os.path.join(project_dir, DATA_ORGANIZE1_DEFAULT_CONFIG_FILENAME)

    def _default_config_path_silent(self):
        project_dir = self._project_dir()
        if not project_dir:
            return ''
        return os.path.join(project_dir, DATA_ORGANIZE1_DEFAULT_CONFIG_FILENAME)

    def run_processing(self):
        input_csv = self.input_csv_edit.text().strip()
        output_csv = self.output_csv_edit.text().strip()
        if not input_csv or not os.path.exists(input_csv):
            QMessageBox.warning(self, 'データ整理１', '入力CSVを指定してください。')
            return
        if not output_csv:
            QMessageBox.warning(self, 'データ整理１', '出力CSVを指定してください。')
            return

        steps = self._processing_steps()
        if not steps:
            QMessageBox.warning(self, 'データ整理１', 'ONになっている実装済みステップがありません。')
            return

        try:
            headers, row_count = process_csv(
                input_csv,
                output_csv,
                steps,
                self.input_encoding_combo.currentText(),
                self.output_encoding_combo.currentText(),
                self._delimiter(),
            )
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理１', str(exc))
            return

        self.preview_status_label.setText(
            '実装済み処理を実行しました: {} 行'.format(row_count)
        )
        QMessageBox.information(self, 'データ整理１', '実装済み処理を実行しました。\n\n{}'.format(output_csv))

    def _default_output_csv(self, input_csv):
        root, ext = os.path.splitext(input_csv)
        return '{}_整理１_文字列結合{}'.format(root, ext or '.csv')

    def _browse_file(self, line_edit, save=False):
        if save:
            path, _ = QFileDialog.getSaveFileName(self, '出力CSVを指定', '', 'CSV (*.csv);;All files (*.*)')
        else:
            path, _ = QFileDialog.getOpenFileName(self, '入力CSVを選択', '', 'CSV (*.csv);;All files (*.*)')
        if path:
            line_edit.setText(path)
            if not save:
                self.output_csv_edit.setText(self._default_output_csv(path))
                self.load_preview_from_input()


class DataOrganize2GpkgDialog(DataOrganize1Dialog):
    """GeoPackage cleanup dialog using the same recipe UI as DataOrganize1Dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('データ整理２ ー GeoPackage下処理')
        self._retitle_ui()

    def _retitle_ui(self):
        labels = self.findChildren(QLabel)
        for label in labels:
            text = label.text()
            if text == 'データ整理１ ー CSV下処理':
                label.setText('データ整理２ ー GeoPackage下処理')
            elif text == '入力CSV':
                label.setText('入力GeoPackage')
            elif text == '出力CSV':
                label.setText('出力GeoPackage')
            elif text == '区切り':
                label.hide()
            elif text in ('入力文字コード', '出力文字コード'):
                label.hide()
            elif text == '現状のプレビュー':
                label.setText('入力レイヤのプレビュー')
            elif text == '変更後のプレビュー（実装済み処理のみ反映）':
                label.setText('変更後のプレビュー（実装済み処理のみ反映）')

        self.input_csv_edit.setPlaceholderText('下処理するGeoPackageファイル')
        self.output_csv_edit.setPlaceholderText('出力GeoPackageファイル')
        self.delimiter_combo.hide()
        self.input_encoding_combo.hide()
        self.output_encoding_combo.hide()

        self.layer_name_combo = QComboBox()
        self.layer_name_combo.setEditable(True)
        self.layer_name_combo.setInsertPolicy(QComboBox.NoInsert)
        self.layer_name_combo.currentTextChanged.connect(lambda _text: self.load_preview_from_input())
        self.output_layer_name_edit = QLineEdit()
        self.output_layer_name_edit.setPlaceholderText('空欄の場合は入力レイヤ名')

        io_groups = [group for group in self.findChildren(QGroupBox) if group.title() == '入出力']
        if io_groups:
            io_layout = io_groups[0].layout()
            io_layout.addWidget(QLabel('入力レイヤ名'), 4, 0)
            io_layout.addWidget(self.layer_name_combo, 4, 1)
            io_layout.addWidget(QLabel('出力レイヤ名'), 5, 0)
            io_layout.addWidget(self.output_layer_name_edit, 5, 1)

    def _selected_layer_name(self):
        data = self.layer_name_combo.currentData()
        if data:
            return str(data).strip()
        return self._layer_name_from_display(self.layer_name_combo.currentText())

    def _layer_name_from_display(self, text):
        text = (text or '').strip()
        if text.endswith('）') and '（' in text:
            return text.rsplit('（', 1)[0].strip()
        return text

    def _refresh_layer_name_options(self, selected_name=None):
        if not hasattr(self, 'layer_name_combo'):
            return

        gpkg_path = self.input_csv_edit.text().strip()
        current = self._selected_layer_name() if selected_name is None else selected_name
        self.layer_name_combo.blockSignals(True)
        try:
            self.layer_name_combo.clear()
            if gpkg_path and os.path.exists(gpkg_path):
                try:
                    layer_infos = list_gpkg_layer_infos(gpkg_path)
                except Exception as exc:
                    layer_infos = []
                    if hasattr(self, 'preview_status_label'):
                        self.preview_status_label.setText('レイヤ一覧を取得できませんでした: {}'.format(exc))
                for info in layer_infos:
                    name = info.get('name', '')
                    geometry_type = info.get('geometry_type') or 'Unknown'
                    if name:
                        self.layer_name_combo.addItem('{}（{}）'.format(name, geometry_type), name)
            if current:
                index = self._find_layer_name_index(current)
                if index < 0:
                    self.layer_name_combo.addItem(current, current)
                    index = self.layer_name_combo.count() - 1
                self.layer_name_combo.setCurrentIndex(index)
        finally:
            self.layer_name_combo.blockSignals(False)

    def _find_layer_name_index(self, layer_name):
        layer_name = (layer_name or '').strip()
        for index in range(self.layer_name_combo.count()):
            if self.layer_name_combo.itemData(index) == layer_name:
                return index
        return -1

    def ask_load_default_config_on_startup(self):
        path = self._default_config_path_silent()
        if not path or not os.path.exists(path):
            return
        reply = QMessageBox.question(
            self,
            'データ整理２',
            '初期設定を読み込みますか？\n\n{}'.format(path),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.set_config(json.load(f))
            except Exception as exc:
                QMessageBox.critical(self, 'データ整理２', str(exc))

    def load_preview_from_input(self):
        if getattr(self, '_updating_steps', False):
            return
        if not (
            hasattr(self, 'preview_table')
            and hasattr(self, 'changed_preview_table')
            and hasattr(self, 'layer_name_combo')
        ):
            return

        gpkg_path = self.input_csv_edit.text().strip()
        if not gpkg_path:
            self.preview_status_label.setText('入力GeoPackageを指定してください。')
            return
        if not os.path.exists(gpkg_path):
            self.preview_status_label.setText('入力GeoPackageが見つかりません: {}'.format(gpkg_path))
            self.preview_table.setRowCount(0)
            self.preview_table.setColumnCount(0)
            self.changed_preview_table.setRowCount(0)
            self.changed_preview_table.setColumnCount(0)
            return

        try:
            preview_limit = 8
            processing_preview_limit = 500 if self._has_row_filter_step() else preview_limit
            self._refresh_layer_name_options()
            headers, rows = read_gpkg_rows(
                gpkg_path,
                self._selected_layer_name(),
                max_rows=processing_preview_limit,
            )
            self._set_preview_data(self.preview_table, headers, rows[:preview_limit])
            changed_headers, changed_rows = apply_processing_steps(
                headers,
                rows,
                self._processing_steps(),
            )
            changed_count = max(0, len(rows) - len(changed_rows))
            self._set_preview_data(self.changed_preview_table, changed_headers, changed_rows[:preview_limit])
            self._refresh_target_column_options(headers)
            self.preview_status_label.setText(
                '実データを表示中: {} 行プレビュー / 変更後 {} 行表示 / 減少 {} 行'.format(
                    min(len(rows), preview_limit),
                    min(len(changed_rows), preview_limit),
                    changed_count,
                )
            )
        except Exception as exc:
            self.preview_status_label.setText('GeoPackageを読み込めませんでした: {}'.format(exc))

    def get_config(self):
        return {
            'input_gpkg': self.input_csv_edit.text().strip(),
            'output_gpkg': self.output_csv_edit.text().strip(),
            'layer_name': self._selected_layer_name(),
            'output_layer_name': self.output_layer_name_edit.text().strip(),
            'steps': self._all_step_rows_data(),
        }

    def set_config(self, config):
        if not config:
            return
        self.input_csv_edit.setText(config.get('input_gpkg', config.get('input_csv', '')))
        self.output_csv_edit.setText(config.get('output_gpkg', config.get('output_csv', '')))
        self._refresh_layer_name_options(config.get('layer_name', ''))
        self.output_layer_name_edit.setText(config.get('output_layer_name', ''))

        rows = config.get('steps') or []
        if rows:
            self._rebuild_step_rows(rows, 0)
        else:
            self.load_preview_from_input()

    def load_config_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            '設定JSONを読込',
            self._config_initial_dir(),
            'JSON (*.json);;All files (*.*)',
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.set_config(json.load(f))
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理２', str(exc))

    def save_config_dialog(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            '設定JSONを保存',
            self._config_initial_dir(),
            'JSON (*.json);;All files (*.*)',
        )
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        try:
            self._write_config(path, self.get_config())
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理２', str(exc))
        else:
            QMessageBox.information(self, 'データ整理２', '設定を保存しました。\n\n{}'.format(path))

    def load_default_config(self):
        path = self._default_config_path()
        if not path:
            return
        try:
            if not os.path.exists(path):
                QMessageBox.warning(
                    self,
                    'データ整理２',
                    '初期設定ファイルが見つかりません。\n「初期設定上書」で現在の設定を保存してください。\n\n{}'.format(path),
                )
                return
            with open(path, 'r', encoding='utf-8') as f:
                self.set_config(json.load(f))
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理２', str(exc))
        else:
            QMessageBox.information(self, 'データ整理２', '初期設定を読み込みました。\n\n{}'.format(path))

    def save_default_config(self):
        path = self._default_config_path()
        if not path:
            return
        try:
            self._write_config(path, self.get_config())
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理２', str(exc))
        else:
            QMessageBox.information(self, 'データ整理２', '初期設定を上書き保存しました。\n\n{}'.format(path))

    def _config_initial_dir(self):
        project_dir = self._project_dir()
        if project_dir:
            return project_dir
        input_gpkg = self.input_csv_edit.text().strip()
        if input_gpkg:
            folder = os.path.dirname(input_gpkg)
            if folder:
                return folder
        return ''

    def _default_config_path(self):
        project_dir = self._project_dir()
        if not project_dir:
            QMessageBox.warning(
                self,
                'データ整理２',
                'QGISプロジェクトが未保存です。\n先にプロジェクトを保存してください。',
            )
            return ''
        return os.path.join(project_dir, DATA_ORGANIZE2_DEFAULT_CONFIG_FILENAME)

    def _default_config_path_silent(self):
        project_dir = self._project_dir()
        if not project_dir:
            return ''
        return os.path.join(project_dir, DATA_ORGANIZE2_DEFAULT_CONFIG_FILENAME)

    def run_processing(self):
        input_gpkg = self.input_csv_edit.text().strip()
        output_gpkg = self.output_csv_edit.text().strip()
        if not input_gpkg or not os.path.exists(input_gpkg):
            QMessageBox.warning(self, 'データ整理２', '入力GeoPackageを指定してください。')
            return
        if not output_gpkg:
            QMessageBox.warning(self, 'データ整理２', '出力GeoPackageを指定してください。')
            return
        if os.path.abspath(input_gpkg) == os.path.abspath(output_gpkg):
            QMessageBox.warning(self, 'データ整理２', '入力GeoPackageとは別の出力先を指定してください。')
            return

        steps = self._processing_steps()
        if not steps:
            QMessageBox.warning(self, 'データ整理２', 'ONになっている実装済みステップがありません。')
            return

        try:
            headers, row_count = process_gpkg(
                input_gpkg,
                output_gpkg,
                steps,
                self._selected_layer_name(),
                self.output_layer_name_edit.text().strip(),
            )
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理２', str(exc))
            return

        self.preview_status_label.setText(
            '実装済み処理を実行しました: {} 行'.format(row_count)
        )
        QMessageBox.information(self, 'データ整理２', '実装済み処理を実行しました。\n\n{}'.format(output_gpkg))

    def _default_output_csv(self, input_gpkg):
        root, ext = os.path.splitext(input_gpkg)
        return '{}_整理２_下処理{}'.format(root, ext or '.gpkg')

    def _browse_file(self, line_edit, save=False):
        if save:
            path, _ = QFileDialog.getSaveFileName(
                self,
                '出力GeoPackageを指定',
                '',
                'GeoPackage (*.gpkg);;All files (*.*)',
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                '入力GeoPackageを選択',
                '',
                'GeoPackage (*.gpkg);;All files (*.*)',
            )
        if path:
            line_edit.setText(path)
            if not save:
                self.output_csv_edit.setText(self._default_output_csv(path))
                self._refresh_layer_name_options('')
                self.load_preview_from_input()


class DataPreprocessingDialog(QDialog):
    """Launcher dialog for data preprocessing tools."""

    def __init__(self, tools, run_callback, parent=None):
        super().__init__(parent)
        self.tools = tools
        self.run_callback = run_callback

        self.setWindowTitle('データの下処理')
        self.setMinimumWidth(dpi_px(640))
        self.resize(dpi_px(760), dpi_px(600))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(dpi_px(18), dpi_px(18), dpi_px(18), dpi_px(18))
        main_layout.setSpacing(dpi_px(12))

        title_row = QHBoxLayout()
        title = QLabel('データの下処理')
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        metrics_label = QLabel(display_metrics_text())
        metrics_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        metrics_label.setStyleSheet('color: #555;')
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(metrics_label)
        main_layout.addLayout(title_row)

        lead = QLabel('使用したい処理をクリックしてください。')
        lead.setWordWrap(True)
        main_layout.addWidget(lead)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        tools_layout = QGridLayout(scroll_content)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(dpi_px(10))

        for index, tool in enumerate(self.tools):
            tools_layout.addWidget(self._create_tool_row(tool), index // 2, index % 2)

        tools_layout.setColumnStretch(0, 1)
        tools_layout.setColumnStretch(1, 1)
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def _create_tool_row(self, tool):
        row = QPushButton()
        row.setMinimumHeight(dpi_px(128))
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        row.setCursor(Qt.PointingHandCursor)
        row.clicked.connect(lambda checked=False, key=tool['key']: self._run_tool(key))
        row.setStyleSheet(
            'QPushButton {{ text-align: left; border: {0}px solid #c8c8c8; border-radius: {1}px; background: #f7f7f7; }}'
            'QPushButton:hover {{ background: #eef5ff; border-color: #7aa7d9; }}'
            'QPushButton:pressed {{ background: #e0edf9; }}'
            'QLabel {{ border: none; background: transparent; }}'
            .format(dpi_px(1), dpi_px(4))
        )

        layout = QHBoxLayout(row)
        layout.setContentsMargins(dpi_px(12), dpi_px(10), dpi_px(12), dpi_px(10))
        layout.setSpacing(dpi_px(12))

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        name_label = QLabel(tool['text'])
        name_label.setStyleSheet('font-weight: 600;')
        description_label = QLabel(tool['description'])
        description_label.setWordWrap(True)
        description_label.setMinimumHeight(description_label.fontMetrics().lineSpacing() * 3 + 6)
        description_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        text_layout.addWidget(name_label)
        text_layout.addWidget(description_label)
        layout.addLayout(text_layout, 1)

        return row

    def _run_tool(self, key):
        self.run_callback(key)


class DataPreprocessingTool:
    """Open data preprocessing submenu and dispatch implemented tools."""

    def __init__(self, iface):
        self.iface = iface
        self.dlg = None
        self.organize_1_dialog = None
        self.organize_2_gpkg_dialog = None
        self.organize_2_query_tool = None
        self.organizing_data_tool = None
        self.organizing_data_gpkg_tool = None
        self.tools = [
            {
                'key': 'organize_1',
                'text': 'データ整理１ ー CSV下処理',
                'description': (
                    'CSVファイルへの、文字列結合・日付の統一・列の削除・'
                    'コラム名の変更等・カスタム関数による変更。例: 地番の内、他などを独立したコラムへ。'
                ),
            },
            {
                'key': 'organize_2_gpkg',
                'text': 'データ整理２ ー GeoPackage下処理',
                'description': (
                    'GeoPackageファイルへの、文字列結合・日付の統一・列の削除・'
                    'コラム名の変更等・カスタム関数による変更。例: 地番の内、他などを独立したコラムへ。'
                ),
            },
            {
                'key': 'organize_2_query',
                'text': 'データ整理３ ー CSVの集計クエリ',
                'description': '例: 地番毎集積（面積和・所有者改行列記・カウント）など。',
            },
            {
                'key': 'organize_3_csv_left_join',
                'text': 'データ整理４ ー CSVへのLeft JoinとUnion',
                'description': 'CSVのLEFT JOIN手順を最大10ステップまで設定し、保存・読込して連続実行します。',
            },
            {
                'key': 'organize_4_gpkg_left_join',
                'text': 'データ整理５ ー GeoPackageへのLeft JoinとUnion',
                'description': 'GeoPackageファイルへのLEFT JOINとUNION。',
            },
        ]
        for tool in self.tools:
            if tool.get('key') == 'organize_3_csv_left_join':
                tool['text'] = 'CSVの結合（LEFT JOIN 及び UNION）'
                tool['description'] = 'CSVのLEFT JOINと、同じ列名CSVのUNION結合を実行します。'

        for tool in self.tools:
            if tool.get('key') == 'organize_3_csv_left_join':
                tool['text'] = 'データ整理４ ー CSVへのLeft JoinとUnion'
                tool['description'] = 'CSVのLEFT JOINと、同じ列名CSVのUNION結合を実行します。'

    def run(self):
        if self.dlg is None:
            self.dlg = DataPreprocessingDialog(
                self.tools,
                self.run_tool,
                self.iface.mainWindow(),
            )

        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def run_tool(self, key):
        if key == 'organize_1':
            self.organize_1_dialog = DataOrganize1Dialog(self.iface.mainWindow())
            self.organize_1_dialog.show()
            self.organize_1_dialog.raise_()
            self.organize_1_dialog.activateWindow()
            self.organize_1_dialog.ask_load_default_config_on_startup()
            return

        if key == 'organize_2_gpkg':
            self.organize_2_gpkg_dialog = DataOrganize2GpkgDialog(self.iface.mainWindow())
            self.organize_2_gpkg_dialog.show()
            self.organize_2_gpkg_dialog.raise_()
            self.organize_2_gpkg_dialog.activateWindow()
            self.organize_2_gpkg_dialog.ask_load_default_config_on_startup()
            return

        if key == 'organize_2_query':
            if self.organize_2_query_tool is None:
                self.organize_2_query_tool = DataOrganize2QueryTool(self.iface)
            self.organize_2_query_tool.run()
            return

        if key == 'organize_3_csv_left_join':
            if self.organizing_data_tool is None:
                self.organizing_data_tool = OrganizingDataTool(self.iface)
                if hasattr(self.organizing_data_tool, 'first_start'):
                    self.organizing_data_tool.first_start = True
            self.organizing_data_tool.run()
            return

        if key == 'organize_4_gpkg_left_join':
            if self.organizing_data_gpkg_tool is None:
                self.organizing_data_gpkg_tool = OrganizingDataGpkgTool(self.iface)
                if hasattr(self.organizing_data_gpkg_tool, 'first_start'):
                    self.organizing_data_gpkg_tool.first_start = True
            self.organizing_data_gpkg_tool.run()
            return

        QMessageBox.information(
            self.iface.mainWindow(),
            'データの下処理',
            'このメニューはまだ中身がありません。',
        )


class MapSharingDummyTool:
    """Placeholder for the future map sharing workflow."""

    def __init__(self, iface):
        self.iface = iface

    def run(self):
        QMessageBox.information(
            self.iface.mainWindow(),
            '地図のおすそ分けパック',
            'この機能は現在準備中です。',
        )


class MapSharingLayerSelectionDialog(QDialog):
    """Select layers to include in a map sharing package."""

    def __init__(self, layers, layouts=None, checked_layer_ids=None, parent=None):
        super().__init__(parent)
        self.layers = layers
        self.layouts = layouts or []
        self.layer_by_id = {layer.id(): layer for layer in layers}
        self.checked_layer_ids = set(checked_layer_ids or [])
        self._changing_checks = False

        self.setWindowTitle('おすそ分けパックに入れるレイヤを選択')
        self.resize(780, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        lead = QLabel('地図のおすそ分けパックに入れるレイヤだけチェックしてください。')
        lead.setWordWrap(True)
        layout.addWidget(lead)

        toolbar = QHBoxLayout()
        select_all_button = QPushButton('すべて選択')
        clear_button = QPushButton('選択解除')
        select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        clear_button.clicked.connect(lambda: self._set_all_checked(False))
        toolbar.addWidget(select_all_button)
        toolbar.addWidget(clear_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(['レイヤ構成', 'データソース'])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.itemChanged.connect(self._handle_item_changed)
        layout.addWidget(self.tree, 1)

        self._build_layer_tree()
        self.tree.expandAll()

        layout_label = QLabel('おすそ分けパックに入れるレイアウトを選択してください。')
        layout_label.setWordWrap(True)
        layout.addWidget(layout_label)

        self.layout_tree = QTreeWidget()
        self.layout_tree.setColumnCount(2)
        self.layout_tree.setHeaderLabels(['レイアウト', '種類'])
        self.layout_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.layout_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._build_layout_tree()
        layout.addWidget(self.layout_tree)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def selected_layers(self):
        selected_ids = set()
        self._collect_checked_layer_ids(self.tree.invisibleRootItem(), selected_ids)
        return [layer for layer in self.layers if layer.id() in selected_ids]

    def selected_layouts(self):
        selected_names = set()
        root_item = self.layout_tree.invisibleRootItem()
        for index in range(root_item.childCount()):
            item = root_item.child(index)
            if item.checkState(0) == Qt.Checked:
                selected_names.add(item.data(0, Qt.UserRole))
        return [layout for layout in self.layouts if layout.name() in selected_names]

    def _set_all_checked(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        self._changing_checks = True
        root_item = self.tree.invisibleRootItem()
        for index in range(root_item.childCount()):
            self._set_item_checked_recursive(root_item.child(index), state)
        layout_root_item = self.layout_tree.invisibleRootItem()
        for index in range(layout_root_item.childCount()):
            layout_root_item.child(index).setCheckState(0, state)
        self._changing_checks = False

    def _build_layer_tree(self):
        added_ids = set()
        root_node = QgsProject.instance().layerTreeRoot()
        for child in root_node.children():
            self._add_layer_tree_node(self.tree.invisibleRootItem(), child, added_ids)

        for layer in self.layers:
            if layer.id() not in added_ids:
                self._add_layer_item(self.tree.invisibleRootItem(), layer)
                added_ids.add(layer.id())

        self._refresh_group_check_states(self.tree.invisibleRootItem())

    def _build_layout_tree(self):
        for layout in self.layouts:
            item = QTreeWidgetItem(self.layout_tree.invisibleRootItem(), [layout.name(), 'レイアウト'])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, layout.name())

    def _add_layer_tree_node(self, parent_item, node, added_ids):
        if hasattr(node, 'layerId'):
            layer = self.layer_by_id.get(node.layerId())
            if layer is None:
                return False
            self._add_layer_item(parent_item, layer)
            added_ids.add(layer.id())
            return True

        if not hasattr(node, 'children'):
            return False

        group_item = QTreeWidgetItem(parent_item, [node.name(), ''])
        group_item.setFlags(group_item.flags() | Qt.ItemIsUserCheckable)
        group_item.setCheckState(0, Qt.Unchecked)
        group_item.setData(0, Qt.UserRole, '')

        has_layers = False
        for child in node.children():
            has_layers = self._add_layer_tree_node(group_item, child, added_ids) or has_layers

        if not has_layers:
            parent_item.removeChild(group_item)
        return has_layers

    def _add_layer_item(self, parent_item, layer):
        layer_item = QTreeWidgetItem(parent_item, [layer.name(), layer.source()])
        layer_item.setFlags(layer_item.flags() | Qt.ItemIsUserCheckable)
        checked = layer.id() in self.checked_layer_ids
        layer_item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        layer_item.setData(0, Qt.UserRole, layer.id())

    def _handle_item_changed(self, item, column):
        if self._changing_checks or column != 0:
            return

        self._changing_checks = True
        if item.childCount() > 0:
            state = item.checkState(0)
            if state in (Qt.Checked, Qt.Unchecked):
                for index in range(item.childCount()):
                    self._set_item_checked_recursive(item.child(index), state)
        self._refresh_parent_check_state(item.parent())
        self._changing_checks = False

    def _set_item_checked_recursive(self, item, state):
        item.setCheckState(0, state)
        for index in range(item.childCount()):
            self._set_item_checked_recursive(item.child(index), state)

    def _refresh_group_check_states(self, item):
        for index in range(item.childCount()):
            child = item.child(index)
            self._refresh_group_check_states(child)
        if item.childCount() > 0 and item is not self.tree.invisibleRootItem():
            self._apply_group_check_state(item)

    def _refresh_parent_check_state(self, item):
        while item is not None:
            self._apply_group_check_state(item)
            item = item.parent()

    def _apply_group_check_state(self, item):
        checked_count = 0
        partial_count = 0
        for index in range(item.childCount()):
            state = item.child(index).checkState(0)
            if state == Qt.Checked:
                checked_count += 1
            elif state == Qt.PartiallyChecked:
                partial_count += 1

        if checked_count == item.childCount():
            item.setCheckState(0, Qt.Checked)
        elif checked_count == 0 and partial_count == 0:
            item.setCheckState(0, Qt.Unchecked)
        else:
            item.setCheckState(0, Qt.PartiallyChecked)

    def _collect_checked_layer_ids(self, item, selected_ids):
        layer_id = item.data(0, Qt.UserRole)
        if layer_id and item.checkState(0) == Qt.Checked:
            selected_ids.add(layer_id)
        for index in range(item.childCount()):
            self._collect_checked_layer_ids(item.child(index), selected_ids)


class MapSharingDialog(QDialog):
    """Choose package export or import."""

    def __init__(self, export_callback, import_callback, parent=None):
        super().__init__(parent)
        self.export_callback = export_callback
        self.import_callback = import_callback

        self.setWindowTitle('地図のおすそ分けパック')
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel('地図のおすそ分けパック')
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        layout.addWidget(title)

        lead = QLabel('選択したレイヤをZIPパックに書き出すか、受け取ったおすそ分けパックを読み込みます。')
        lead.setWordWrap(True)
        layout.addWidget(lead)

        export_button = QPushButton('おすそ分けパックを書き出し')
        export_button.clicked.connect(self.export_callback)
        layout.addWidget(export_button)

        import_button = QPushButton('おすそ分けパックを読み込み')
        import_button.clicked.connect(self.import_callback)
        layout.addWidget(import_button)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


class MapSharingPackagePreviewDialog(QDialog):
    """Show map sharing package contents before import."""

    def __init__(self, manifest, parent=None):
        super().__init__(parent)
        self.manifest = manifest

        self.setWindowTitle('おすそ分けパックから読み込むものを選択')
        self.resize(820, 560)
        self._changing_checks = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        package_name = manifest.get('package_name') or '名称未設定'
        layers = manifest.get('layers', [])
        layouts = manifest.get('layouts', [])
        title = QLabel('おすそ分けパックから読み込むものを選択')
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        layout.addWidget(title)

        summary = QLabel(
            'パック名: {0} / レイヤ数: {1} / レイアウト数: {2}'.format(
                package_name,
                len(layers),
                len(layouts),
            )
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        guide = QLabel('読み込むレイヤとレイアウトにチェックを入れてください。チェックを外したものは読み込みません。')
        guide.setWordWrap(True)
        layout.addWidget(guide)

        toolbar = QHBoxLayout()
        select_all_button = QPushButton('すべて選択')
        clear_button = QPushButton('選択解除')
        select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        clear_button.clicked.connect(lambda: self._set_all_checked(False))
        toolbar.addWidget(select_all_button)
        toolbar.addWidget(clear_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(['読み込む項目', '種類', 'データ', 'スタイル'])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self._handle_item_changed)
        self.tree.setRootIsDecorated(True)
        layout.addWidget(self.tree, 1)

        self._populate_tree(layers)
        self._populate_layouts(layouts)
        self.tree.expandAll()

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText('チェックしたものを読み込む')
        button_box.button(QDialogButtonBox.Cancel).setText('キャンセル')
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _populate_tree(self, layers):
        group_items = {}
        for index, layer_info in enumerate(layers):
            parent_item = self.tree.invisibleRootItem()
            group_path = layer_info.get('group_path')
            if not isinstance(group_path, list):
                group_name = layer_info.get('group')
                group_path = [group_name] if group_name else []

            path_key = []
            for group_name in group_path:
                if not group_name:
                    continue
                path_key.append(group_name)
                key = tuple(path_key)
                if key not in group_items:
                    group_items[key] = QTreeWidgetItem(parent_item, [group_name, 'フォルダ', '', ''])
                    self._make_checkable_group_item(group_items[key])
                parent_item = group_items[key]

            layer_type = layer_info.get('type') or ('ベクタ' if layer_info.get('path') else 'ラスタ')
            if layer_type == 'vector':
                display_type = 'ベクタ'
                data_value = layer_info.get('path', '')
            elif layer_type == 'raster':
                display_type = 'ラスタ/XYZ'
                data_value = layer_info.get('source', '')
            else:
                display_type = layer_type
                data_value = layer_info.get('path') or layer_info.get('source') or ''

            style_value = 'あり' if layer_info.get('style') else 'なし'
            item = QTreeWidgetItem(parent_item, [
                layer_info.get('name') or layer_info.get('layername') or '名称未設定',
                display_type,
                data_value,
                style_value,
            ])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked)
            item.setData(0, Qt.UserRole, 'layer')
            item.setData(0, Qt.UserRole + 1, index)

    def _populate_layouts(self, layouts):
        if not layouts:
            return

        layouts_item = QTreeWidgetItem(self.tree.invisibleRootItem(), ['レイアウト', 'フォルダ', '', ''])
        self._make_checkable_group_item(layouts_item)
        for index, layout_info in enumerate(layouts):
            item = QTreeWidgetItem(layouts_item, [
                layout_info.get('name') or '名称未設定',
                'レイアウト',
                layout_info.get('path') or '',
                '',
            ])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked)
            item.setData(0, Qt.UserRole, 'layout')
            item.setData(0, Qt.UserRole + 1, index)
        self._refresh_group_check_states(self.tree.invisibleRootItem())

    def selected_layer_indexes(self):
        selected = []
        self._collect_selected_indexes(self.tree.invisibleRootItem(), 'layer', selected)
        return selected

    def selected_layout_indexes(self):
        selected = []
        self._collect_selected_indexes(self.tree.invisibleRootItem(), 'layout', selected)
        return selected

    def _set_all_checked(self, checked):
        self._changing_checks = True
        state = Qt.Checked if checked else Qt.Unchecked
        root_item = self.tree.invisibleRootItem()
        for index in range(root_item.childCount()):
            self._set_item_checked_recursive(root_item.child(index), state)
        self._changing_checks = False

    def _make_checkable_group_item(self, item):
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked)

    def _handle_item_changed(self, item, column):
        if self._changing_checks or column != 0:
            return

        self._changing_checks = True
        if item.childCount() > 0:
            state = item.checkState(0)
            if state in (Qt.Checked, Qt.Unchecked):
                for index in range(item.childCount()):
                    self._set_item_checked_recursive(item.child(index), state)
        self._refresh_parent_check_state(item.parent())
        self._changing_checks = False

    def _set_item_checked_recursive(self, item, state):
        item.setCheckState(0, state)
        for index in range(item.childCount()):
            self._set_item_checked_recursive(item.child(index), state)

    def _refresh_parent_check_state(self, item):
        while item is not None:
            self._apply_group_check_state(item)
            item = item.parent()

    def _refresh_group_check_states(self, item):
        for index in range(item.childCount()):
            child = item.child(index)
            self._refresh_group_check_states(child)
        if item.childCount() > 0 and item is not self.tree.invisibleRootItem():
            self._apply_group_check_state(item)

    def _apply_group_check_state(self, item):
        checked_count = 0
        partial_count = 0
        for index in range(item.childCount()):
            state = item.child(index).checkState(0)
            if state == Qt.Checked:
                checked_count += 1
            elif state == Qt.PartiallyChecked:
                partial_count += 1

        if checked_count == item.childCount():
            item.setCheckState(0, Qt.Checked)
        elif checked_count == 0 and partial_count == 0:
            item.setCheckState(0, Qt.Unchecked)
        else:
            item.setCheckState(0, Qt.PartiallyChecked)

    def _collect_selected_indexes(self, item, item_type, selected):
        if item.data(0, Qt.UserRole) == item_type and item.checkState(0) == Qt.Checked:
            selected.append(item.data(0, Qt.UserRole + 1))
        for index in range(item.childCount()):
            self._collect_selected_indexes(item.child(index), item_type, selected)


class MapSharingLayoutImportDialog(QDialog):
    """Edit layout names before importing package layouts."""

    def __init__(self, layouts, parent=None):
        super().__init__(parent)
        self.layouts = layouts
        self.setWindowTitle('レイアウトの取り込み設定')
        self.resize(720, 420)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(10)

        title = QLabel('取り込むレイアウトを選択し、必要に応じて名前を変更してください。')
        title.setWordWrap(True)
        main_layout.addWidget(title)

        existing_names = [layout.name() for layout in QgsProject.instance().layoutManager().layouts()]
        existing_label = QLabel(
            '既存レイアウト: {0}'.format(', '.join(existing_names) if existing_names else 'なし')
        )
        existing_label.setWordWrap(True)
        main_layout.addWidget(existing_label)

        self.table = QTableWidget(len(layouts), 3)
        self.table.setHorizontalHeaderLabels(['取り込む', '元の名前', '取り込み後の名前'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        main_layout.addWidget(self.table, 1)

        for row, layout_info in enumerate(layouts):
            original_name = layout_info.get('name') or 'おすそ分けレイアウト'
            import_item = QTableWidgetItem('')
            import_item.setFlags(import_item.flags() | Qt.ItemIsUserCheckable)
            import_item.setCheckState(Qt.Checked)
            self.table.setItem(row, 0, import_item)

            original_item = QTableWidgetItem(original_name)
            original_item.setFlags(original_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, original_item)

            name_item = QTableWidgetItem(self._default_import_name(original_name, existing_names))
            self.table.setItem(row, 2, name_item)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Ok).setText('取り込む')
        button_box.button(QDialogButtonBox.Cancel).setText('キャンセル')
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def selected_layouts(self):
        selected = []
        for row, layout_info in enumerate(self.layouts):
            import_item = self.table.item(row, 0)
            name_item = self.table.item(row, 2)
            if import_item is None or import_item.checkState() != Qt.Checked:
                continue
            new_name = name_item.text().strip() if name_item is not None else ''
            if not new_name:
                continue
            updated_info = dict(layout_info)
            updated_info['import_name'] = new_name
            selected.append(updated_info)
        return selected

    def _default_import_name(self, original_name, existing_names):
        if original_name not in existing_names:
            return original_name
        return original_name + '_取り込み'


class MapSharingTool:
    """Export and import kojiGIS map sharing ZIP packages."""

    def __init__(self, iface):
        self.iface = iface
        self.dlg = None
        self.plugin_dir = os.path.dirname(__file__)

    def run(self):
        if self.dlg is None:
            self.dlg = MapSharingDialog(
                self.export_package,
                self.import_package,
                self.iface.mainWindow(),
            )

        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def export_package(self):
        project = QgsProject.instance()
        available_layers = [
            layer
            for layer in project.mapLayers().values()
            if layer.type() in (QgsMapLayer.VectorLayer, QgsMapLayer.RasterLayer) and layer.isValid()
        ]
        available_layouts = project.layoutManager().layouts()
        if not available_layers and not available_layouts:
            QMessageBox.warning(
                self.iface.mainWindow(),
                '地図のおすそ分けパック',
                '書き出せるレイヤまたはレイアウトがありません。',
            )
            return

        selection_dialog = MapSharingLayerSelectionDialog(
            available_layers,
            available_layouts,
            self._selected_layer_ids(),
            self.iface.mainWindow(),
        )
        if selection_dialog.exec_() != QDialog.Accepted:
            return

        layers = selection_dialog.selected_layers()
        layouts = selection_dialog.selected_layouts()
        if not layers and not layouts:
            QMessageBox.warning(
                self.iface.mainWindow(),
                '地図のおすそ分けパック',
                'おすそ分けパックに入れるレイヤまたはレイアウトを1つ以上選択してください。',
            )
            return

        default_name = '地図のおすそ分けパック.zip'
        zip_path, _ = QFileDialog.getSaveFileName(
            self.iface.mainWindow(),
            '地図のおすそ分けパックを書き出し',
            default_name,
            'おすそ分けパック (*.zip);;All files (*.*)',
        )
        if not zip_path:
            return
        if not zip_path.lower().endswith('.zip'):
            zip_path += '.zip'

        try:
            with tempfile.TemporaryDirectory(prefix='kojigis_package_') as temp_dir:
                self._build_package(temp_dir, zip_path, layers, layouts)
            QMessageBox.information(
                self.iface.mainWindow(),
                '地図のおすそ分けパック',
                'おすそ分けパックを書き出しました。\n{0}'.format(zip_path),
            )
        except Exception as exc:  # pragma: no cover - shown inside QGIS
            QMessageBox.critical(
                self.iface.mainWindow(),
                '地図のおすそ分けパック',
                'おすそ分けパックの書き出しに失敗しました。\n{0}'.format(exc),
            )

    def import_package(self):
        zip_path, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            '地図のおすそ分けパックを読み込み',
            '',
            'おすそ分けパック (*.zip);;All files (*.*)',
        )
        if not zip_path:
            return

        try:
            package_dir = self._extract_package(zip_path)
            self._load_package_directory(package_dir)
        except Exception as exc:  # pragma: no cover - shown inside QGIS
            QMessageBox.critical(
                self.iface.mainWindow(),
                '地図のおすそ分けパック',
                'おすそ分けパックの読み込みに失敗しました。\n{0}'.format(exc),
            )

    def _build_package(self, temp_dir, zip_path, layers, layouts=None):
        data_dir = os.path.join(temp_dir, 'data')
        styles_dir = os.path.join(temp_dir, 'styles')
        symbols_dir = os.path.join(temp_dir, 'symbols')
        layouts_dir = os.path.join(temp_dir, 'layouts')
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(styles_dir, exist_ok=True)
        os.makedirs(symbols_dir, exist_ok=True)
        os.makedirs(layouts_dir, exist_ok=True)

        project = QgsProject.instance()
        manifest = {
            'package_name': self._safe_name(project.baseName() or 'kojiGIS_package'),
            'package_type': 'layer_package',
            'created_at': datetime.now().isoformat(timespec='seconds'),
            'layers': [],
            'layouts': [],
        }

        package_gpkg_name = 'kojiGIS_layers.gpkg'
        package_gpkg_path = os.path.join(data_dir, package_gpkg_name)
        used_names = set()
        vector_written = False
        for index, layer in enumerate(layers, start=1):
            layer_key = self._unique_name(
                self._safe_name(layer.name()) or 'layer_{0}'.format(index),
                used_names,
            )
            qml_path = os.path.join(styles_dir, layer_key + '.qml')

            layer_entry = {
                'name': layer.name(),
                'layername': layer_key,
                'style': 'styles/{0}.qml'.format(layer_key),
                'visible': self._layer_is_visible(layer),
                'group': self._layer_group_name(layer),
                'group_path': self._layer_group_path(layer),
            }
            if layer.type() == QgsMapLayer.VectorLayer:
                self._write_vector_layer(layer, package_gpkg_path, layer_key, not vector_written)
                vector_written = True
                layer_entry.update({
                    'type': 'vector',
                    'path': 'data/{0}'.format(package_gpkg_name),
                })
            elif layer.type() == QgsMapLayer.RasterLayer:
                layer_entry.update({
                    'type': 'raster',
                    'provider': layer.providerType(),
                    'source': layer.source(),
                })
            else:
                continue

            layer.saveNamedStyle(qml_path)
            self._copy_svg_assets(qml_path, symbols_dir)

            manifest['layers'].append(layer_entry)

        self._write_layout_templates(layouts_dir, layouts or [], manifest)

        manifest_path = os.path.join(temp_dir, 'manifest.json')
        with open(manifest_path, 'w', encoding='utf-8') as manifest_file:
            json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as package_zip:
            for root, _, files in os.walk(temp_dir):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    arcname = os.path.relpath(file_path, temp_dir).replace(os.sep, '/')
                    package_zip.write(file_path, arcname)

    def _extract_package(self, zip_path):
        imports_dir = os.path.join(self.plugin_dir, 'imported_packages')
        os.makedirs(imports_dir, exist_ok=True)
        base_name = self._safe_name(os.path.splitext(os.path.basename(zip_path))[0]) or 'package'
        package_dir = os.path.join(
            imports_dir,
            '{0}_{1}'.format(base_name, datetime.now().strftime('%Y%m%d_%H%M%S')),
        )
        os.makedirs(package_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as package_zip:
            self._safe_extract_zip(package_zip, package_dir)
        return package_dir

    def _load_package_directory(self, package_dir):
        manifest_path = os.path.join(package_dir, 'manifest.json')
        if not os.path.exists(manifest_path):
            raise ValueError('選択したフォルダに manifest.json がありません。')

        with open(manifest_path, 'r', encoding='utf-8') as manifest_file:
            manifest = json.load(manifest_file)

        preview_dialog = MapSharingPackagePreviewDialog(manifest, self.iface.mainWindow())
        if preview_dialog.exec_() != QDialog.Accepted:
            return
        manifest = self._filter_manifest_by_preview_selection(manifest, preview_dialog)
        if not manifest.get('layers') and not manifest.get('layouts'):
            QMessageBox.warning(
                self.iface.mainWindow(),
                '地図のおすそ分けパック',
                '読み込むレイヤまたはレイアウトを1つ以上選択してください。',
            )
            return

        if manifest.get('layouts'):
            layout_dialog = MapSharingLayoutImportDialog(
                manifest.get('layouts', []),
                self.iface.mainWindow(),
            )
            if layout_dialog.exec_() != QDialog.Accepted:
                return
            manifest['layouts'] = layout_dialog.selected_layouts()
            if not manifest.get('layers') and not manifest.get('layouts'):
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    '地図のおすそ分けパック',
                    '読み込むレイヤまたはレイアウトを1つ以上選択してください。',
                )
                return

        gpkg_path_overrides = self._copy_package_gpkgs_to_user_locations(package_dir, manifest)
        if gpkg_path_overrides is None:
            return

        destination_group = self._ask_import_group(manifest)
        if destination_group is None:
            return

        loaded_count = self._load_manifest_layers(
            package_dir,
            manifest,
            destination_group,
            gpkg_path_overrides,
        )
        loaded_layout_count = self._load_layout_templates(package_dir, manifest)
        QMessageBox.information(
            self.iface.mainWindow(),
            '地図のおすそ分けパック',
            '{0} レイヤ、{1} レイアウトを読み込みました。'.format(
                loaded_count,
                loaded_layout_count,
            ),
        )

    def _filter_manifest_by_preview_selection(self, manifest, preview_dialog):
        filtered_manifest = dict(manifest)
        layers = manifest.get('layers', [])
        layouts = manifest.get('layouts', [])
        selected_layer_indexes = set(preview_dialog.selected_layer_indexes())
        selected_layout_indexes = set(preview_dialog.selected_layout_indexes())

        filtered_manifest['layers'] = [
            layer
            for index, layer in enumerate(layers)
            if index in selected_layer_indexes
        ]
        filtered_manifest['layouts'] = [
            layout
            for index, layout in enumerate(layouts)
            if index in selected_layout_indexes
        ]
        return filtered_manifest

    def _copy_package_gpkgs_to_user_locations(self, package_dir, manifest):
        gpkg_rel_paths = []
        for layer_info in manifest.get('layers', []):
            rel_path = layer_info.get('path')
            if rel_path and rel_path.lower().endswith('.gpkg') and rel_path not in gpkg_rel_paths:
                gpkg_rel_paths.append(rel_path)

        data_dir = os.path.join(package_dir, 'data')
        if not gpkg_rel_paths and os.path.isdir(data_dir):
            for file_name in os.listdir(data_dir):
                if file_name.lower().endswith('.gpkg'):
                    gpkg_rel_paths.append('data/{0}'.format(file_name))

        if not gpkg_rel_paths:
            return {}

        path_overrides = {}
        for rel_path in gpkg_rel_paths:
            source_path = os.path.normpath(os.path.join(package_dir, rel_path))
            self._assert_inside_directory(package_dir, source_path)
            if not os.path.exists(source_path):
                raise ValueError('GeoPackageが見つかりません: {0}'.format(rel_path))

            default_name = os.path.basename(source_path)
            save_path, _ = QFileDialog.getSaveFileName(
                self.iface.mainWindow(),
                'GeoPackageの保存先',
                default_name,
                'GeoPackage (*.gpkg);;All files (*.*)',
            )
            if not save_path:
                return None
            if not save_path.lower().endswith('.gpkg'):
                save_path += '.gpkg'

            shutil.copy2(source_path, save_path)
            path_overrides[rel_path] = save_path

        return path_overrides

    def _load_layout_templates(self, package_dir, manifest):
        layouts = manifest.get('layouts', [])
        if not isinstance(layouts, list):
            return 0

        manager = QgsProject.instance().layoutManager()
        loaded_count = 0
        for layout_info in layouts:
            rel_path = layout_info.get('path')
            if not rel_path:
                continue

            template_path = os.path.normpath(os.path.join(package_dir, rel_path))
            self._assert_inside_directory(package_dir, template_path)
            if not os.path.exists(template_path):
                raise ValueError('レイアウトテンプレートが見つかりません: {0}'.format(rel_path))

            with open(template_path, 'r', encoding='utf-8') as template_file:
                template_text = template_file.read()

            document = QDomDocument()
            set_content_result = document.setContent(template_text)
            if isinstance(set_content_result, tuple):
                set_content_ok = bool(set_content_result[0])
            else:
                set_content_ok = bool(set_content_result)
            if not set_content_ok:
                raise ValueError('レイアウトテンプレートを読み込めません: {0}'.format(rel_path))

            layout = QgsPrintLayout(QgsProject.instance())
            layout.initializeDefaults()
            layout.loadFromTemplate(document, QgsReadWriteContext())
            layout.setName(self._unique_layout_name(
                layout_info.get('import_name') or layout_info.get('name') or 'おすそ分けレイアウト'
            ))
            manager.addLayout(layout)
            loaded_count += 1

        return loaded_count

    def _write_layout_templates(self, layouts_dir, layouts, manifest):
        used_names = set()
        context = QgsReadWriteContext()
        for index, layout in enumerate(layouts, start=1):
            layout_key = self._unique_name(
                self._safe_name(layout.name()) or 'layout_{0}'.format(index),
                used_names,
            )
            qpt_path = os.path.join(layouts_dir, layout_key + '.qpt')
            layout.saveAsTemplate(qpt_path, context)
            manifest['layouts'].append({
                'name': layout.name(),
                'path': 'layouts/{0}.qpt'.format(layout_key),
            })

    def _load_manifest_layers(self, package_dir, manifest, destination_group=None, path_overrides=None):
        layers = manifest.get('layers', [])
        if not isinstance(layers, list):
            raise ValueError('manifest.json の layers が配列ではありません。')

        root = QgsProject.instance().layerTreeRoot()
        loaded_count = 0
        for layer_info in layers:
            rel_path = layer_info.get('path')
            layer_type = layer_info.get('type') or ('vector' if rel_path else 'raster')
            layer_name = layer_info.get('name') or layer_info.get('layername') or 'layer'

            if layer_type == 'vector':
                if not rel_path:
                    continue
                source_path = path_overrides.get(rel_path) if path_overrides else None
                if source_path is None:
                    source_path = os.path.normpath(os.path.join(package_dir, rel_path))
                    self._assert_inside_directory(package_dir, source_path)
                layer_name = layer_info.get('name') or layer_info.get('layername') or os.path.basename(source_path)
                gpkg_layer_name = layer_info.get('layername')
                source = source_path
                if gpkg_layer_name:
                    source = '{0}|layername={1}'.format(source_path, gpkg_layer_name)
                layer = QgsVectorLayer(source, layer_name, 'ogr')
            elif layer_type == 'raster':
                source = layer_info.get('source')
                provider = layer_info.get('provider') or 'gdal'
                if not source:
                    continue
                layer = QgsRasterLayer(source, layer_name, provider)
            else:
                continue

            if not layer.isValid():
                raise ValueError('レイヤを読み込めません: {0}'.format(layer_name))

            style_rel_path = layer_info.get('style')
            if style_rel_path:
                style_path = os.path.normpath(os.path.join(package_dir, style_rel_path))
                self._assert_inside_directory(package_dir, style_path)
                if os.path.exists(style_path):
                    style_result = layer.loadNamedStyle(style_path)
                    if isinstance(style_result, tuple) and len(style_result) > 1 and not style_result[1]:
                        raise ValueError('スタイルを読み込めません: {0}'.format(style_rel_path))
                    layer.triggerRepaint()

            QgsProject.instance().addMapLayer(layer, False)
            parent_group = destination_group or root
            group_path = layer_info.get('group_path')
            if not isinstance(group_path, list):
                group_name = layer_info.get('group')
                group_path = [group_name] if group_name else []
            target_group = self._find_or_create_group_path(parent_group, group_path)
            target_group.addLayer(layer)

            node = root.findLayer(layer.id())
            if node is not None:
                node.setItemVisibilityChecked(bool(layer_info.get('visible', True)))
            loaded_count += 1

        return loaded_count

    def _write_vector_layer(self, layer, gpkg_path, layer_name, create_file):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = layer_name
        options.fileEncoding = 'UTF-8'
        if create_file:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
        else:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            gpkg_path,
            QgsProject.instance().transformContext(),
            options,
        )
        error_code = result[0] if isinstance(result, tuple) else result
        if error_code != QgsVectorFileWriter.NoError:
            message = result[1] if isinstance(result, tuple) and len(result) > 1 else 'unknown error'
            raise RuntimeError('レイヤを書き出せません: {0} ({1})'.format(layer.name(), message))

    def _copy_svg_assets(self, qml_path, symbols_dir):
        if not os.path.exists(qml_path):
            return
        with open(qml_path, 'r', encoding='utf-8', errors='ignore') as qml_file:
            qml_text = qml_file.read()

        replacements = {}
        for match in re.findall(r'["\']([^"\']+\.svg)["\']', qml_text, flags=re.IGNORECASE):
            svg_path = match
            if not os.path.isabs(svg_path):
                svg_path = os.path.normpath(os.path.join(os.path.dirname(qml_path), svg_path))
            if os.path.exists(svg_path):
                asset_name = os.path.basename(svg_path)
                shutil.copy2(svg_path, os.path.join(symbols_dir, asset_name))
                replacements[match] = '../symbols/{0}'.format(asset_name)

        if replacements:
            for old_path, new_path in replacements.items():
                qml_text = qml_text.replace(old_path, new_path)
            with open(qml_path, 'w', encoding='utf-8') as qml_file:
                qml_file.write(qml_text)

    def _safe_extract_zip(self, package_zip, target_dir):
        for member in package_zip.infolist():
            target_path = os.path.normpath(os.path.join(target_dir, member.filename))
            self._assert_inside_directory(target_dir, target_path)
            package_zip.extract(member, target_dir)

    def _assert_inside_directory(self, base_dir, path):
        base_dir = os.path.abspath(base_dir)
        path = os.path.abspath(path)
        if os.path.commonpath([base_dir, path]) != base_dir:
            raise ValueError('おすそ分けパック外のパスは使用できません。')

    def _layer_is_visible(self, layer):
        node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        return True if node is None else node.isVisible()

    def _selected_layer_ids(self):
        selected_ids = set()
        try:
            layer_tree_view = self.iface.layerTreeView()
            selected_layers = layer_tree_view.selectedLayers()
        except Exception:
            selected_layers = []
            layer_tree_view = None

        selected_ids.update(layer.id() for layer in selected_layers if layer is not None)
        if layer_tree_view is not None and hasattr(layer_tree_view, 'selectedNodes'):
            for node in layer_tree_view.selectedNodes():
                self._collect_layer_ids_from_node(node, selected_ids)
        return list(selected_ids)

    def _selected_group_node(self):
        try:
            layer_tree_view = self.iface.layerTreeView()
        except Exception:
            return None

        if not hasattr(layer_tree_view, 'selectedNodes'):
            return None

        for node in layer_tree_view.selectedNodes():
            if self._is_group_node(node):
                return node
        return None

    def _collect_layer_ids_from_node(self, node, selected_ids):
        if hasattr(node, 'layerId'):
            layer_id = node.layerId()
            if layer_id:
                selected_ids.add(layer_id)

        if hasattr(node, 'children'):
            for child in node.children():
                self._collect_layer_ids_from_node(child, selected_ids)

    def _is_group_node(self, node):
        return hasattr(node, 'children') and not hasattr(node, 'layerId')

    def _ask_import_group(self, manifest):
        default_name = 'もらい物'
        group_name, accepted = QInputDialog.getText(
            self.iface.mainWindow(),
            'インポート先フォルダ名',
            'レイヤパネルに作成するフォルダ名:',
            QLineEdit.Normal,
            default_name,
        )
        if not accepted:
            return None

        group_name = group_name.strip()
        if not group_name:
            QMessageBox.warning(
                self.iface.mainWindow(),
                '地図のおすそ分けパック',
                'フォルダ名を入力してください。',
            )
            return None

        return QgsProject.instance().layerTreeRoot().addGroup(group_name)

    def _find_or_create_group(self, parent_group, group_name):
        if not group_name:
            return parent_group

        if hasattr(parent_group, 'findGroup'):
            group = parent_group.findGroup(group_name)
            if group is not None:
                return group

        for child in parent_group.children():
            if self._is_group_node(child) and child.name() == group_name:
                return child

        return parent_group.addGroup(group_name)

    def _find_or_create_group_path(self, parent_group, group_path):
        group = parent_group
        for group_name in group_path:
            if group_name:
                group = self._find_or_create_group(group, group_name)
        return group

    def _layer_group_name(self, layer):
        node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        parent = node.parent() if node is not None else None
        if parent is not None and hasattr(parent, 'name'):
            name = parent.name()
            return name or None
        return None

    def _layer_group_path(self, layer):
        node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        parent = node.parent() if node is not None else None
        root = QgsProject.instance().layerTreeRoot()
        path = []
        while parent is not None and parent is not root and hasattr(parent, 'name'):
            name = parent.name()
            if name:
                path.insert(0, name)
            parent = parent.parent() if hasattr(parent, 'parent') else None
        return path

    def _safe_name(self, value):
        value = re.sub(r'[^\w\-]+', '_', value, flags=re.UNICODE).strip('_')
        return value[:80]

    def _unique_name(self, value, used_names):
        candidate = value
        suffix = 2
        while candidate in used_names:
            candidate = '{0}_{1}'.format(value, suffix)
            suffix += 1
        used_names.add(candidate)
        return candidate

    def _unique_layout_name(self, value):
        manager = QgsProject.instance().layoutManager()
        existing_names = {layout.name() for layout in manager.layouts()}
        candidate = value
        suffix = 2
        while candidate in existing_names:
            candidate = '{0}_{1}'.format(value, suffix)
            suffix += 1
        return candidate


class KojiGIS4QGISDialog(QDialog):
    """Launcher dialog for bundled kojiGIS4QGIS tools."""

    def __init__(self, tools, run_callback, parent=None):
        super().__init__(parent)
        self.tools = tools
        self.run_callback = run_callback

        self.setWindowTitle('kojiGIS4QGIS')
        self.setMinimumWidth(dpi_px(560))
        self.resize(dpi_px(760), dpi_px(600))

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(dpi_px(18), dpi_px(18), dpi_px(18), dpi_px(18))
        main_layout.setSpacing(dpi_px(12))

        title_row = QHBoxLayout()
        title = QLabel('kojiGIS4QGIS')
        title.setObjectName('KojiGIS4QGISTitle')
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        metrics_label = QLabel(display_metrics_text())
        metrics_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        metrics_label.setStyleSheet('color: #555;')
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(metrics_label)
        main_layout.addLayout(title_row)

        lead = QLabel('使用したい機能をクリックしてください。')
        lead.setWordWrap(True)
        main_layout.addWidget(lead)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        scroll_content = QWidget()
        self.tools_layout = QGridLayout(scroll_content)
        self.tools_layout.setContentsMargins(0, 0, 0, 0)
        self.tools_layout.setSpacing(dpi_px(10))

        for index, tool in enumerate(self.tools):
            self.tools_layout.addWidget(self._create_tool_row(tool), index // 2, index % 2)

        self.tools_layout.setColumnStretch(0, 1)
        self.tools_layout.setColumnStretch(1, 1)
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    def _create_tool_row(self, tool):
        row = QPushButton()
        row.setMinimumHeight(dpi_px(128))
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        row.setCursor(Qt.PointingHandCursor)
        row.clicked.connect(lambda checked=False, key=tool['key']: self._run_tool(key))
        row.setStyleSheet(
            'QPushButton {{ text-align: left; border: {0}px solid #c8c8c8; border-radius: {1}px; background: #f7f7f7; }}'
            'QPushButton:hover {{ background: #eef5ff; border-color: #7aa7d9; }}'
            'QPushButton:pressed {{ background: #e0edf9; }}'
            'QLabel {{ border: none; background: transparent; }}'
            .format(dpi_px(1), dpi_px(4))
        )

        layout = QHBoxLayout(row)
        layout.setContentsMargins(dpi_px(12), dpi_px(10), dpi_px(12), dpi_px(10))
        layout.setSpacing(dpi_px(12))

        icon_label = QLabel()
        icon = QIcon(tool['icon_path'])
        icon_size = dpi_px(64)
        icon_box = dpi_px(72)
        icon_label.setPixmap(icon.pixmap(icon_size, icon_size))
        icon_label.setFixedSize(icon_box, icon_box)
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(4)

        name_label = QLabel(tool['text'])
        name_label.setStyleSheet('font-weight: 600;')
        description_label = QLabel(tool['description'])
        description_label.setWordWrap(True)
        description_label.setMinimumHeight(description_label.fontMetrics().lineSpacing() * 3 + 6)
        description_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        text_layout.addWidget(name_label)
        text_layout.addWidget(description_label)
        layout.addLayout(text_layout, 1)

        return row

    def _run_tool(self, key):
        self.run_callback(key)


class KojiGIS4QGIS:
    """Single-entry wrapper plugin for kojiGIS4QGIS tools."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.child_plugins = {}
        self.tool_definitions = []
        self.dlg = None
        self.menu_title = self.tr(u'&kojiGIS4QGIS')

        locale = QSettings().value('locale/userLocale', '')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'KojiGIS4QGIS_{}.qm'.format(locale),
        )

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

    def tr(self, message):
        return QCoreApplication.translate('KojiGIS4QGIS', message)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path)

        self._add_tool(
            key='data_preprocessing',
            text=self.tr(u'データの下処理'),
            description=self.tr(u'CSVやGeoPackageの整理、集計キー作成、LEFT JOINなどの下処理メニューを開きます。'),
            plugin_class=DataPreprocessingTool,
            icon_path=os.path.join(self.plugin_dir, 'data_preprocessing_icon.svg'),
        )
        self._add_tool(
            key='map_sharing',
            text=self.tr(u'地図のおすそ分けパック'),
            description=self.tr(u'選択したレイヤ、スタイル、シンボルをZIPパックにして共有・読み込みします。'),
            plugin_class=MapSharingTool,
            icon_path=os.path.join(self.plugin_dir, 'map_sharing_icon.svg'),
        )
        self._add_tool(
            key='add_sets_layers',
            text=self.tr(u'レイヤセットを追加'),
            description=self.tr(u'施設統合ポテンシャルマップ用のレイヤセットをまとめて追加します。'),
            plugin_class=Add_Sets_Layers,
            icon_path=os.path.join(self.plugin_dir, 'add_sets_layers', 'icon.png'),
        )
        self._add_tool(
            key='ward_circle_boundary',
            text=self.tr(u'区境界・2km円を作成'),
            description=self.tr(u'選択した地物から区境界と2km円を作成し、結果をレイヤとして保存します。'),
            plugin_class=WardCircleBoundary,
            icon_path=os.path.join(self.plugin_dir, 'ward_circle_boundary', 'icon.png'),
        )
        self._add_tool(
            key='merge_point_features_in_poligon',
            text=self.tr(u'ポリゴン内のポイントを統合'),
            description=self.tr(u'選択したポリゴン内にある表示中のポイント地物を抽出して統合します。'),
            plugin_class=MergePointFeaturesInPoligon,
            icon_path=os.path.join(
                self.plugin_dir,
                'merge_point_features_in_poligon',
                'icon.png',
            ),
        )
        self._add_tool(
            key='merge_poligon_features_in_poligon',
            text=self.tr(u'ポリゴン内のポリゴンを統合'),
            description=self.tr(u'選択したポリゴン内にある表示中のポリゴン地物を抽出して統合します。'),
            plugin_class=MergePoligonFeaturesInPoligon,
            icon_path=os.path.join(
                self.plugin_dir,
                'merge_poligon_features_in_poligon',
                'icon.png',
            ),
        )

        self.main_action = QAction(icon, self.tr(u'kojiGIS4QGIS'), self.iface.mainWindow())
        self.main_action.triggered.connect(self.show_dialog)
        self.iface.addToolBarIcon(self.main_action)
        self.iface.addPluginToMenu(self.menu_title, self.main_action)
        self.actions.append(self.main_action)

    def _add_tool(self, key, text, description, plugin_class, icon_path):
        self.tool_definitions.append({
            'key': key,
            'text': text,
            'description': description,
            'icon_path': icon_path,
        })
        self.child_plugins[key] = {
            'class': plugin_class,
            'instance': None,
            'text': text,
        }

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu_title, action)
            self.iface.removeToolBarIcon(action)

        if self.dlg is not None:
            self.dlg.close()
            self.dlg = None

    def show_dialog(self):
        if self.dlg is None:
            self.dlg = KojiGIS4QGISDialog(
                self.tool_definitions,
                self.run_tool,
                self.iface.mainWindow(),
            )

        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def run_tool(self, key):
        tool = self.child_plugins.get(key)
        if tool is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                self.tr(u'kojiGIS4QGIS'),
                self.tr(u'The selected tool was not found.'),
            )
            return

        try:
            if tool['instance'] is None:
                tool['instance'] = tool['class'](self.iface)
                if hasattr(tool['instance'], 'first_start'):
                    tool['instance'].first_start = True

            tool['instance'].run()
        except Exception as exc:  # pragma: no cover - shown inside QGIS
            QMessageBox.critical(
                self.iface.mainWindow(),
                self.tr(u'kojiGIS4QGIS'),
                self.tr(u'Failed to start tool: {0}').format(exc),
            )
