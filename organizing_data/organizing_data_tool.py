# -*- coding: utf-8 -*-

import json
import os
import csv
import unicodedata
from pathlib import Path

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

MAX_STEPS = 10
MODE_SELECT_FIELDS = 'select_fields'
MODE_OVERWRITE_FIELDS = 'overwrite_fields'
DEFAULT_CONFIG_FILENAME = 'kojiGIS_tools_data_organize3_csv_join_default.json'
GPKG_DEFAULT_CONFIG_FILENAME = 'kojiGIS_tools_data_organize4_gpkg_join_default.json'
CSV_JOIN_PROCESS_NAME = 'CSVの結合'
GPKG_JOIN_PROCESS_NAME = 'GeoPackageの結合'

COL_CSV_B = 0
COL_MODE = 1
COL_KEY_A = 2
COL_KEY_B = 3
COL_FIELDS = 4
COL_PREFIX = 5
COL_UNMATCHED_B = 6

ENCODING_OPTIONS = ['UTF-8', 'utf-8-sig', 'CP932', 'Shift_JIS']


try:
    from ..data_organize2_gpkg_processor import list_gpkg_layer_infos, open_gpkg_layer
    from ..config_paths import process_config_dir, process_config_path, project_dir as kdq_project_dir
except Exception:
    list_gpkg_layer_infos = None
    open_gpkg_layer = None
    from config_paths import process_config_dir, process_config_path, project_dir as kdq_project_dir


class FieldSelectionDialog(QDialog):
    """Select one or more CSV fields."""

    def __init__(self, fields, selected_fields=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('追加列を選択')
        self.resize(420, 520)
        selected_fields = selected_fields or []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('参照CSVから追加する列を選択してください。'))

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.check_layout = QVBoxLayout(content)
        self.check_layout.setContentsMargins(4, 4, 4, 4)
        self.checkboxes = []

        for field in fields:
            checkbox = QCheckBox(field)
            checkbox.setChecked(field in selected_fields)
            self.check_layout.addWidget(checkbox)
            self.checkboxes.append(checkbox)

        self.check_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_filter(self, text):
        text = text.strip().lower()
        for checkbox in self.checkboxes:
            checkbox.setVisible(text in checkbox.text().lower())

    def selected_fields(self):
        return [checkbox.text() for checkbox in self.checkboxes if checkbox.isChecked()]


class OverwriteFieldMappingDialog(QDialog):
    """Map selected CSV fields to target fields with combo boxes."""

    def __init__(self, source_fields, target_fields, field_map=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('上書き対応を選択')
        self.resize(620, 520)
        self.rows = []
        field_map = field_map or {}
        source_to_target = {source: target for target, source in field_map.items()}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('参照CSVの列を選択し、右側で上書き先の列を選択してください。'))

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.grid = QGridLayout(content)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setColumnStretch(1, 1)

        self.grid.addWidget(QLabel('参照CSV(B)'), 0, 0)
        self.grid.addWidget(QLabel('上書き先(A)'), 0, 1)

        for index, source_field in enumerate(source_fields, start=1):
            checkbox = QCheckBox(source_field)
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems(target_fields)

            target_field = source_to_target.get(source_field, '')
            if target_field:
                checkbox.setChecked(True)
                if combo.findText(target_field) < 0:
                    combo.addItem(target_field)
                combo.setCurrentText(target_field)

            checkbox.toggled.connect(combo.setEnabled)
            combo.setEnabled(checkbox.isChecked())

            self.grid.addWidget(checkbox, index, 0)
            self.grid.addWidget(combo, index, 1)
            self.rows.append((source_field, checkbox, combo))

        self.grid.setRowStretch(len(source_fields) + 1, 1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_filter(self, text):
        text = text.strip().lower()
        for source_field, checkbox, combo in self.rows:
            visible = text in source_field.lower()
            checkbox.setVisible(visible)
            combo.setVisible(visible)

    def accept(self):
        checked_targets = []
        for _, checkbox, combo in self.rows:
            if checkbox.isChecked():
                target_field = combo.currentText().strip()
                if not target_field:
                    QMessageBox.warning(self, 'Organizing Data', '上書き先(A)が空の行があります。')
                    return
                checked_targets.append(target_field)
        if not checked_targets:
            QMessageBox.warning(self, 'Organizing Data', '上書き対応を1つ以上選択してください。')
            return
        if len(checked_targets) != len(set(checked_targets)):
            QMessageBox.warning(self, 'Organizing Data', '同じ上書き先(A)が複数指定されています。')
            return
        super().accept()

    def selected_field_map(self):
        result = {}
        for source_field, checkbox, combo in self.rows:
            if not checkbox.isChecked():
                continue
            target_field = combo.currentText().strip()
            if target_field:
                result[target_field] = source_field
        return result


class OrganizingDataDialog(QDialog):
    """Generic sequential CSV LEFT JOIN tool."""

    def __init__(self, parent=None, default_config=None):
        super().__init__(parent)
        self.setWindowTitle('データ整理４ ー CSVへのLeft JoinとUnion')
        self.resize(1180, 720)
        self.default_config = default_config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel('データ整理４ ー CSVへのLeft JoinとUnion')
        title.setText('データ整理４ ー CSVへのLeft JoinとUnion')
        title.setStyleSheet('font-size: 17px; font-weight: 600;')
        layout.addWidget(title)

        description = QLabel(
            '基準CSVに対して最大10個のLEFT JOINを順番に実行します。'
            '各ステップの出力CSVが次ステップの入力CSVになります。'
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        description.hide()

        form = QGridLayout()
        form.setColumnStretch(1, 1)
        form.setColumnStretch(7, 1)

        left_join_title = QLabel('ＣＳＶ LEFT JOIN')
        left_join_title.setStyleSheet('font-size: 14px; font-weight: 600;')
        form.addWidget(left_join_title, 0, 0, 1, 3)

        self.base_csv_edit = QLineEdit()
        self.base_csv_edit.setPlaceholderText('最初の基準CSV')
        self.base_csv_edit.editingFinished.connect(self.refresh_key_a_options)
        base_browse = QPushButton('参照')
        base_browse.clicked.connect(self.browse_base_csv)
        form.addWidget(QLabel('基準CSV'), 0, 0)
        form.addWidget(self.base_csv_edit, 1, 1)
        form.addWidget(base_browse, 1, 2)

        self.final_output_csv_edit = QLineEdit()
        self.final_output_csv_edit.setPlaceholderText('最終出力CSV')
        final_output_browse = QPushButton('参照')
        final_output_browse.clicked.connect(self.browse_final_output_csv)
        form.addWidget(QLabel('最終出力CSV'), 1, 0)
        form.addWidget(self.final_output_csv_edit, 2, 1)
        form.addWidget(final_output_browse, 2, 2)

        self.delimiter_edit = QLineEdit(',')
        self.delimiter_edit.setMaximumWidth(80)
        self.encoding_edit = QComboBox()
        self.encoding_edit.addItems(ENCODING_OPTIONS)
        self.encoding_edit.setMaximumWidth(120)
        self.output_encoding_edit = QComboBox()
        self.output_encoding_edit.addItems(ENCODING_OPTIONS)
        self.output_encoding_edit.setMaximumWidth(120)

        form.addWidget(QLabel('区切り'), 2, 0)
        form.addWidget(self.delimiter_edit, 3, 1)
        form.addWidget(QLabel('入力文字コード'), 2, 2)
        form.addWidget(self.encoding_edit, 3, 3)
        form.addWidget(QLabel('出力文字コード'), 2, 4)
        form.addWidget(self.output_encoding_edit, 3, 5)
        form.addWidget(QLabel('ＣＳＶ LEFT JOIN'), 0, 0, 1, 3)
        form.addWidget(QLabel('基準CSV'), 1, 0)
        form.addWidget(QLabel('最終出力CSV'), 2, 0)
        form.addWidget(QLabel('区切り'), 3, 0)
        form.addWidget(QLabel('入力文字コード'), 3, 2)
        form.addWidget(QLabel('出力文字コード'), 3, 4)
        union_title = QLabel('CSV UNION（同じ列名のCSVを縦結合）')
        union_title.setStyleSheet('font-weight: 600;')
        form.addWidget(union_title, 0, 6, 1, 3)

        self.union_folder_edit = QLineEdit()
        self.union_folder_edit.setPlaceholderText('フォルダ内の全CSVをUNION')
        union_folder_browse = QPushButton('参照')
        union_folder_browse.setMaximumWidth(60)
        union_folder_browse.clicked.connect(self.browse_union_folder)
        form.addWidget(QLabel('フォルダ'), 1, 6)
        form.addWidget(self.union_folder_edit, 1, 7)
        form.addWidget(union_folder_browse, 1, 8)

        self.union_csv_a_edit = QLineEdit()
        self.union_csv_a_edit.setPlaceholderText('1つ目のCSV')
        union_a_browse = QPushButton('参照')
        union_a_browse.setMaximumWidth(60)
        union_a_browse.clicked.connect(lambda: self.browse_union_csv(self.union_csv_a_edit))
        form.addWidget(QLabel('CSV 1'), 2, 6)
        form.addWidget(self.union_csv_a_edit, 2, 7)
        form.addWidget(union_a_browse, 2, 8)

        self.union_csv_b_edit = QLineEdit()
        self.union_csv_b_edit.setPlaceholderText('2つ目のCSV')
        union_b_browse = QPushButton('参照')
        union_b_browse.setMaximumWidth(60)
        union_b_browse.clicked.connect(lambda: self.browse_union_csv(self.union_csv_b_edit))
        form.addWidget(QLabel('CSV 2'), 3, 6)
        form.addWidget(self.union_csv_b_edit, 3, 7)
        form.addWidget(union_b_browse, 3, 8)

        self.union_output_csv_edit = QLineEdit()
        self.union_output_csv_edit.setPlaceholderText('UNION結果の出力CSV')
        union_output_browse = QPushButton('参照')
        union_output_browse.setMaximumWidth(60)
        union_output_browse.clicked.connect(self.browse_union_output_csv)
        self.union_input_encoding_combo = QComboBox()
        self.union_input_encoding_combo.addItems(ENCODING_OPTIONS)
        self.union_output_encoding_combo = QComboBox()
        self.union_output_encoding_combo.addItems(ENCODING_OPTIONS)
        union_run_button = QPushButton('UNION実行')
        union_run_button.clicked.connect(self.run_union_csv)
        action_button_style = (
            'QPushButton {'
            'background-color: #2f6f73; color: white; font-weight: 600;'
            'border: 1px solid #255b5f; border-radius: 3px; padding: 5px 12px;'
            '}'
            'QPushButton:hover { background-color: #367f84; }'
            'QPushButton:pressed { background-color: #285f63; }'
        )
        union_run_button.setMinimumHeight(28)
        union_run_button.setStyleSheet(action_button_style)
        form.addWidget(QLabel('出力'), 3, 6)
        form.addWidget(QLabel('CSV 2'), 3, 6)
        form.addWidget(QLabel('出力'), 4, 6)
        form.addWidget(self.union_output_csv_edit, 4, 7)
        form.addWidget(union_output_browse, 4, 8)
        form.addWidget(union_run_button, 5, 7, 1, 2)

        union_group = QGroupBox('ＣＳＶ UNION（同じ列名のCSVを縦結合）')
        union_layout = QGridLayout(union_group)
        union_layout.setColumnStretch(1, 1)
        union_layout.setColumnStretch(4, 1)
        union_layout.addWidget(QLabel('フォルダ'), 0, 0)
        union_layout.addWidget(self.union_folder_edit, 0, 1, 1, 4)
        union_layout.addWidget(union_folder_browse, 0, 5)
        union_layout.addWidget(QLabel('CSV 1'), 1, 0)
        union_layout.addWidget(self.union_csv_a_edit, 1, 1)
        union_layout.addWidget(union_a_browse, 1, 2)
        union_layout.addWidget(QLabel('CSV 2'), 1, 3)
        union_layout.addWidget(self.union_csv_b_edit, 1, 4)
        union_layout.addWidget(union_b_browse, 1, 5)
        union_layout.addWidget(QLabel('出力'), 2, 0)
        union_layout.addWidget(self.union_output_csv_edit, 2, 1, 1, 4)
        union_layout.addWidget(union_output_browse, 2, 5)
        union_encoding_widget = QWidget()
        union_encoding_layout = QHBoxLayout(union_encoding_widget)
        union_encoding_layout.setContentsMargins(0, 0, 0, 0)
        union_encoding_layout.setSpacing(8)
        union_encoding_layout.addWidget(QLabel('入力文字コード'))
        union_encoding_layout.addWidget(self.union_input_encoding_combo)
        union_encoding_layout.addWidget(QLabel('出力文字コード'))
        union_encoding_layout.addWidget(self.union_output_encoding_combo)
        union_encoding_layout.addStretch(1)
        union_layout.addWidget(union_encoding_widget, 3, 0, 1, 6)
        union_layout.addWidget(union_run_button, 4, 1, 1, 5)
        form.addWidget(union_group, 0, 6, 6, 3)
        union_title.hide()

        left_join_group = QGroupBox('ＣＳＶ LEFT JOIN')
        left_join_group.setTitle('ＣＳＶ LEFT JOIN（基準CSVに対して最大10個のLEFT JOINを順番に実行します）')
        left_join_layout = QGridLayout(left_join_group)
        left_join_layout.setColumnStretch(1, 1)
        left_join_layout.setColumnMinimumWidth(2, 110)
        left_join_layout.setColumnStretch(3, 0)
        self.run_button = QPushButton('LEFT JOIN実行')
        self.run_button.clicked.connect(self.run_workflow)
        self.run_button.setMinimumHeight(28)
        self.run_button.setStyleSheet(action_button_style)
        left_join_layout.addWidget(QLabel('基準CSV'), 0, 0)
        left_join_layout.addWidget(self.base_csv_edit, 0, 1)
        left_join_layout.addWidget(base_browse, 0, 2)
        left_join_layout.addWidget(QLabel('最終出力CSV'), 1, 0)
        left_join_layout.addWidget(self.final_output_csv_edit, 1, 1)
        left_join_layout.addWidget(final_output_browse, 1, 2)
        self.delimiter_edit.hide()
        encoding_widget = QWidget()
        encoding_layout = QHBoxLayout(encoding_widget)
        encoding_layout.setContentsMargins(0, 0, 0, 0)
        encoding_layout.setSpacing(8)
        encoding_layout.addWidget(QLabel('入力文字コード'))
        encoding_layout.addWidget(self.encoding_edit)
        encoding_layout.addWidget(QLabel('出力文字コード'))
        encoding_layout.addWidget(self.output_encoding_edit)
        encoding_layout.addStretch(1)
        left_join_layout.addWidget(encoding_widget, 2, 0, 1, 4)

        left_join_layout.addWidget(self.run_button, 3, 1, 1, 3)

        top_layout = QHBoxLayout()
        top_layout.addWidget(left_join_group, 1)
        top_layout.addWidget(union_group, 1)
        layout.addLayout(top_layout)

        toolbar = QHBoxLayout()
        self.load_button = QPushButton('プリセット呼出')
        self.save_button = QPushButton('プリセット更新')
        self.default_load_button = QPushButton('初期設定読込')
        self.default_save_button = QPushButton('初期設定上書')

        self.load_button.clicked.connect(self.load_config_dialog)
        self.save_button.clicked.connect(self.save_config_dialog)
        self.default_load_button.clicked.connect(self.load_default_config)
        self.default_save_button.clicked.connect(self.save_default_config)

        toolbar.addWidget(self.load_button)
        toolbar.addWidget(self.save_button)
        toolbar.addWidget(self.default_load_button)
        toolbar.addWidget(self.default_save_button)
        toolbar.addStretch(1)

        self.table = QTableWidget(MAX_STEPS, 7)
        self.table.setHorizontalHeaderLabels([
            '参照CSV(B)',
            '処理',
            'キーA',
            'キーB',
            '追加列 / 上書き対応',
            '接頭辞',
        ])
        self.table.setHorizontalHeaderItem(COL_UNMATCHED_B, QTableWidgetItem('未結合B 保存先'))
        self.table.verticalHeader().setVisible(True)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(COL_CSV_B, 350)
        self.table.setColumnWidth(COL_MODE, 120)
        self.table.setColumnWidth(COL_KEY_A, 110)
        self.table.setColumnWidth(COL_KEY_B, 110)
        self.table.setColumnWidth(COL_FIELDS, 170)
        self.table.setColumnWidth(COL_PREFIX, 55)
        self.table.setColumnWidth(COL_UNMATCHED_B, 180)

        for row in range(MAX_STEPS):
            self._init_row(row)

        self.table.itemChanged.connect(self.on_table_item_changed)
        layout.addWidget(self.table, 1)

        hint = QLabel(
            '追加列: col1, col2 のように指定。'
            '上書き対応: A列<-B列, A列2<-B列2 のように指定。'
            '中間CSVは作成せず、すべてのJOINをメモリ上で連続処理して最終出力CSVだけ保存します。'
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        self.log.setPlaceholderText('実行結果がここに表示されます。')
        layout.addWidget(self.log)

        buttons = QDialogButtonBox()
        self.run_button = buttons.addButton('LEFT JOIN実行', QDialogButtonBox.AcceptRole)
        close_button = buttons.addButton(QDialogButtonBox.Close)
        self.run_button.clicked.connect(self.run_workflow)
        close_button.clicked.connect(self.reject)
        layout.addWidget(buttons)
        buttons.hide()

        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.addLayout(toolbar, 1)

        close_footer = QDialogButtonBox()
        footer_close_button = close_footer.addButton(QDialogButtonBox.Close)
        footer_close_button.clicked.connect(self.reject)
        footer_layout.addWidget(close_footer)
        layout.addLayout(footer_layout)

        if default_config:
            self.set_config(default_config)

    def tr(self, message):
        return QCoreApplication.translate('OrganizingDataDialog', message)

    def _init_row(self, row):
        csv_widget = QWidget()
        csv_layout = QHBoxLayout(csv_widget)
        csv_layout.setContentsMargins(2, 2, 2, 2)
        csv_layout.setSpacing(4)
        csv_edit = QLineEdit()
        csv_edit.editingFinished.connect(lambda row=row: self.on_reference_csv_changed(row))
        csv_encoding_combo = self._new_encoding_combo()
        csv_encoding_combo.currentTextChanged.connect(lambda _text, row=row: self.refresh_key_b_options(row))
        csv_button = QPushButton('参照')
        csv_button.setMaximumWidth(54)
        csv_button.clicked.connect(lambda checked=False, row=row: self.browse_reference_csv_for_row(row))
        csv_layout.addWidget(csv_edit, 1)
        csv_layout.addWidget(csv_encoding_combo)
        csv_layout.addWidget(csv_button)
        self.table.setCellWidget(row, COL_CSV_B, csv_widget)

        mode_combo = QComboBox()
        mode_combo.addItem('列を追加', MODE_SELECT_FIELDS)
        mode_combo.addItem('列を上書き', MODE_OVERWRITE_FIELDS)
        self.table.setCellWidget(row, COL_MODE, mode_combo)

        key_a_combo = QComboBox()
        key_a_combo.setEditable(True)
        self.table.setCellWidget(row, COL_KEY_A, key_a_combo)

        key_b_combo = QComboBox()
        key_b_combo.setEditable(True)
        self.table.setCellWidget(row, COL_KEY_B, key_b_combo)

        fields_widget = QWidget()
        fields_layout = QHBoxLayout(fields_widget)
        fields_layout.setContentsMargins(2, 2, 2, 2)
        fields_layout.setSpacing(4)
        fields_edit = QLineEdit()
        fields_edit.editingFinished.connect(self.refresh_key_a_options)
        fields_button = QPushButton('選択')
        fields_button.setMaximumWidth(54)
        fields_button.clicked.connect(lambda checked=False, row=row: self.open_fields_dialog(row))
        fields_layout.addWidget(fields_edit, 1)
        fields_layout.addWidget(fields_button)
        self.table.setCellWidget(row, COL_FIELDS, fields_widget)

        self.table.setItem(row, COL_PREFIX, QTableWidgetItem(''))

        unmatched_widget = QWidget()
        unmatched_layout = QHBoxLayout(unmatched_widget)
        unmatched_layout.setContentsMargins(2, 2, 2, 2)
        unmatched_layout.setSpacing(4)
        unmatched_edit = QLineEdit()
        unmatched_button = QPushButton('参照')
        unmatched_button.setMaximumWidth(54)
        unmatched_button.clicked.connect(lambda checked=False, row=row: self.browse_unmatched_b_csv_for_row(row))
        unmatched_layout.addWidget(unmatched_edit, 1)
        unmatched_layout.addWidget(unmatched_button)
        self.table.setCellWidget(row, COL_UNMATCHED_B, unmatched_widget)

    def _mode_combo(self, row):
        return self.table.cellWidget(row, COL_MODE)

    def _key_a_combo(self, row):
        return self.table.cellWidget(row, COL_KEY_A)

    def _key_b_combo(self, row):
        return self.table.cellWidget(row, COL_KEY_B)

    def _combo_text(self, combo):
        return combo.currentText().strip() if combo else ''

    def _set_combo_text(self, combo, value):
        value = value or ''
        if combo.findText(value) < 0 and value:
            combo.addItem(value)
        combo.setCurrentText(value)

    def _new_encoding_combo(self, value='UTF-8'):
        combo = QComboBox()
        combo.addItems(ENCODING_OPTIONS)
        combo.setMaximumWidth(92)
        combo.setToolTip('参照CSV(B)の文字コード')
        combo.setCurrentText(value or 'UTF-8')
        return combo

    def _csv_b_encoding_combo(self, row):
        return self.table.cellWidget(row, COL_CSV_B).layout().itemAt(1).widget()

    def _csv_b_encoding(self, row):
        combo = self._csv_b_encoding_combo(row)
        return combo.currentText().strip() if combo else (self.encoding_edit.currentText().strip() or 'UTF-8')

    def _set_csv_b_encoding(self, row, value):
        self._set_combo_text(self._csv_b_encoding_combo(row), value or self.encoding_edit.currentText().strip() or 'UTF-8')

    def refresh_key_a_options(self):
        fields = []
        delimiter = self.delimiter_edit.text() or ','
        encoding = self.encoding_edit.currentText().strip() or 'UTF-8'
        base_csv = self.base_csv_edit.text().strip()
        if base_csv and Path(base_csv).exists():
            try:
                fields, _ = self._read_csv_rows(base_csv, encoding, delimiter)
            except Exception:
                fields = []

        for row in range(MAX_STEPS):
            step_fields = self._item_text(row, COL_FIELDS)
            if self._mode_combo(row).currentData() == MODE_SELECT_FIELDS:
                prefix = self._item_text(row, COL_PREFIX)
                fields.extend([prefix + field for field in self._parse_list(step_fields)])
            elif step_fields:
                try:
                    fields.extend(list(self._parse_field_map(step_fields).keys()))
                except ValueError:
                    pass

            combo = self._key_a_combo(row)
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self._unique(fields))
            self._set_combo_text(combo, current)
            combo.blockSignals(False)

    def refresh_key_b_options(self, row):
        csv_b = self._item_text(row, COL_CSV_B)
        combo = self._key_b_combo(row)
        current = combo.currentText()
        fields = []
        if csv_b and Path(csv_b).exists():
            try:
                fields, _ = self._read_csv_rows(csv_b, self._csv_b_encoding(row), self.delimiter_edit.text() or ',')
            except Exception as exc:
                QMessageBox.warning(self, 'Organizing Data', '参照CSVのヘッダを読めませんでした:\n{}'.format(exc))
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(fields)
        self._set_combo_text(combo, current)
        combo.blockSignals(False)

    def _unique(self, values):
        result = []
        seen = set()
        for value in values:
            if value and value not in seen:
                result.append(value)
                seen.add(value)
        return result

    def _item_text(self, row, col):
        if col == COL_CSV_B:
            return self._csv_b_edit(row).text().strip()
        if col == COL_FIELDS:
            return self._fields_edit(row).text().strip()
        if col == COL_UNMATCHED_B:
            return self._unmatched_b_edit(row).text().strip()
        item = self.table.item(row, col)
        return item.text().strip() if item else ''

    def _set_item_text(self, row, col, value):
        if col == COL_CSV_B:
            self._csv_b_edit(row).setText(value or '')
            return
        if col == COL_FIELDS:
            self._fields_edit(row).setText(value or '')
            return
        if col == COL_UNMATCHED_B:
            self._unmatched_b_edit(row).setText(value or '')
            return
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem('')
            self.table.setItem(row, col, item)
        item.setText(value or '')

    def _csv_b_edit(self, row):
        return self.table.cellWidget(row, COL_CSV_B).layout().itemAt(0).widget()

    def _fields_edit(self, row):
        return self.table.cellWidget(row, COL_FIELDS).layout().itemAt(0).widget()

    def _unmatched_b_edit(self, row):
        return self.table.cellWidget(row, COL_UNMATCHED_B).layout().itemAt(0).widget()

    def on_table_item_changed(self, item):
        if item.column() in (COL_FIELDS, COL_PREFIX):
            self.refresh_key_a_options()

    def browse_base_csv(self):
        initial_dir = self._initial_dir_from_paths(
            self.base_csv_edit.text(),
            self.final_output_csv_edit.text(),
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            '基準CSVを選択',
            initial_dir,
            'CSV (*.csv);;All files (*.*)',
        )
        if path:
            self.base_csv_edit.setText(path)
            self.refresh_key_a_options()

    def browse_reference_csv_for_row(self, row):
        initial_dir = self._initial_dir_from_paths(
            self._item_text(row, COL_CSV_B),
            self.base_csv_edit.text(),
            self.final_output_csv_edit.text(),
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            '参照CSVを選択',
            initial_dir,
            'CSV (*.csv);;All files (*.*)',
        )
        if path:
            self._set_item_text(row, COL_CSV_B, path)
            self.refresh_key_b_options(row)
            self.refresh_key_a_options()

    def on_reference_csv_changed(self, row):
        self.refresh_key_b_options(row)
        self.refresh_key_a_options()

    def browse_unmatched_b_csv_for_row(self, row):
        initial_dir = self._initial_dir_from_paths(
            self._item_text(row, COL_UNMATCHED_B),
            self._item_text(row, COL_CSV_B),
            self.final_output_csv_edit.text(),
            self.base_csv_edit.text(),
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            '未結合B行の保存先CSVを指定',
            initial_dir,
            'CSV (*.csv);;All files (*.*)',
        )
        if path:
            if not path.lower().endswith('.csv'):
                path += '.csv'
            self._set_item_text(row, COL_UNMATCHED_B, path)

    def _target_fields_for_row(self, row):
        fields = []
        delimiter = self.delimiter_edit.text() or ','
        encoding = self.encoding_edit.currentText().strip() or 'UTF-8'
        base_csv = self.base_csv_edit.text().strip()
        if base_csv and Path(base_csv).exists():
            try:
                fields, _ = self._read_csv_rows(base_csv, encoding, delimiter)
            except Exception:
                fields = []

        for step_row in range(row):
            step_fields = self._item_text(step_row, COL_FIELDS)
            if not step_fields:
                continue
            if self._mode_combo(step_row).currentData() == MODE_SELECT_FIELDS:
                prefix = self._item_text(step_row, COL_PREFIX)
                fields.extend([prefix + field for field in self._parse_list(step_fields)])
            else:
                try:
                    fields.extend(list(self._parse_field_map(step_fields).keys()))
                except ValueError:
                    pass

        try:
            current_targets = list(self._parse_field_map(self._item_text(row, COL_FIELDS)).keys())
        except ValueError:
            current_targets = []
        fields.extend(current_targets)

        return self._unique(fields)

    def open_fields_dialog(self, row):
        csv_b = self._item_text(row, COL_CSV_B)
        if not csv_b:
            QMessageBox.warning(self, 'Organizing Data', '先に参照CSVを選択してください。')
            return
        if not Path(csv_b).exists():
            QMessageBox.warning(self, 'Organizing Data', '参照CSVが見つかりません:\n{}'.format(csv_b))
            return

        try:
            fields, _ = self._read_csv_rows(
                csv_b,
                self._csv_b_encoding(row),
                self.delimiter_edit.text() or ',',
            )
        except Exception as exc:
            QMessageBox.critical(self, 'Organizing Data', str(exc))
            return

        if self._mode_combo(row).currentData() == MODE_OVERWRITE_FIELDS:
            target_fields = self._target_fields_for_row(row)
            if not target_fields:
                QMessageBox.warning(self, 'Organizing Data', '上書き先(A)の列を取得できませんでした。基準CSVを選択してください。')
                return
            try:
                current_map = self._parse_field_map(self._item_text(row, COL_FIELDS))
            except ValueError:
                current_map = {}
            dialog = OverwriteFieldMappingDialog(fields, target_fields, current_map, self)
            if dialog.exec_() == QDialog.Accepted:
                selected_map = dialog.selected_field_map()
                self._set_item_text(
                    row,
                    COL_FIELDS,
                    ', '.join(['{}<-{}'.format(target, source) for target, source in selected_map.items()]),
                )
                self.refresh_key_a_options()
            return

        dialog = FieldSelectionDialog(fields, self._parse_list(self._item_text(row, COL_FIELDS)), self)
        if dialog.exec_() == QDialog.Accepted:
            self._set_item_text(row, COL_FIELDS, ', '.join(dialog.selected_fields()))
            self.refresh_key_a_options()

    def browse_final_output_csv(self):
        initial_dir = self._initial_dir_from_paths(
            self.final_output_csv_edit.text(),
            self.base_csv_edit.text(),
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            '最終出力CSVを指定',
            initial_dir,
            'CSV (*.csv);;All files (*.*)',
        )
        if path:
            self.final_output_csv_edit.setText(path)

    def browse_union_csv(self, line_edit):
        initial_dir = self._initial_dir_from_paths(line_edit.text(), self.union_csv_a_edit.text(), self.union_csv_b_edit.text())
        path, _ = QFileDialog.getOpenFileName(
            self,
            'UNIONするCSVを選択',
            initial_dir,
            'CSV (*.csv);;All files (*.*)',
        )
        if path:
            line_edit.setText(path)

    def browse_union_folder(self):
        initial_dir = self._initial_dir_from_paths(
            self.union_folder_edit.text(),
            self.union_csv_a_edit.text(),
            self.union_csv_b_edit.text(),
        )
        path = QFileDialog.getExistingDirectory(
            self,
            'UNIONするCSVフォルダを選択',
            initial_dir,
        )
        if path:
            self.union_folder_edit.setText(path)

    def browse_union_output_csv(self):
        initial_dir = self._initial_dir_from_paths(
            self.union_output_csv_edit.text(),
            self.union_folder_edit.text(),
            self.union_csv_a_edit.text(),
            self.union_csv_b_edit.text(),
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            'UNION結果の出力CSVを指定',
            initial_dir,
            'CSV (*.csv);;All files (*.*)',
        )
        if path:
            if not path.lower().endswith('.csv'):
                path += '.csv'
            self.union_output_csv_edit.setText(path)

    def run_union_csv(self):
        folder = self.union_folder_edit.text().strip()
        csv_a = self.union_csv_a_edit.text().strip()
        csv_b = self.union_csv_b_edit.text().strip()
        output_csv = self.union_output_csv_edit.text().strip()
        delimiter = self.delimiter_edit.text() or ','
        encoding = self.union_input_encoding_combo.currentText().strip() or 'UTF-8'
        output_encoding = self.union_output_encoding_combo.currentText().strip() or 'UTF-8'

        try:
            if folder:
                row_count, file_count = self._union_folder_same_columns_csv(
                    folder,
                    output_csv,
                    encoding,
                    output_encoding,
                    delimiter,
                )
            else:
                row_count = self._union_same_columns_csv(
                    csv_a,
                    csv_b,
                    output_csv,
                    encoding,
                    output_encoding,
                    delimiter,
                )
                file_count = 2
        except Exception as exc:
            QMessageBox.critical(self, 'Organizing Data', str(exc))
            self._log('UNION ERROR: {}'.format(exc))
            return

        self._log('UNION completed: {} files, {} rows -> {}'.format(file_count, row_count, output_csv))
        QMessageBox.information(
            self,
            'Organizing Data',
            'UNION処理が完了しました。\n\n出力:\n{}\n\n行数: {}'.format(output_csv, row_count),
        )

    def load_default_config(self):
        path = self._default_config_path()
        if not path:
            return
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    self.set_config(json.load(f))
                QMessageBox.information(
                    self,
                    'Organizing Data',
                    '初期設定を読み込みました。\n\n{}'.format(path),
                )
                return

            QMessageBox.warning(
                self,
                'Organizing Data',
                '初期設定ファイルが見つかりません。\n「初期設定上書」で現在の設定を保存してください。\n\n{}'.format(path),
            )
        except Exception as exc:
            QMessageBox.critical(self, 'Organizing Data', str(exc))

    def save_default_config(self):
        path = self._default_config_path()
        if not path:
            return
        try:
            self._write_config(path, self.get_config())
        except Exception as exc:
            QMessageBox.critical(self, 'Organizing Data', str(exc))
        else:
            QMessageBox.information(
                self,
                'Organizing Data',
                '初期設定を上書き保存しました。\n\n{}'.format(path),
            )

    def load_config_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            '設定JSONを読込',
            self._config_dir(),
            'JSON (*.json)',
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.set_config(json.load(f))
        except Exception as exc:
            QMessageBox.critical(self, 'Organizing Data', str(exc))

    def save_config_dialog(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            '設定JSONを保存',
            self._config_dir(),
            'JSON (*.json)',
        )
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.get_config(), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, 'Organizing Data', str(exc))
        else:
            QMessageBox.information(self, 'Organizing Data', '設定を保存しました。')

    def _config_dir(self):
        folder = process_config_dir(self._process_name(), create=True)
        if folder:
            return folder
        fallback = Path(__file__).resolve().parent / 'configs'
        fallback.mkdir(exist_ok=True)
        return str(fallback)

    def _process_name(self):
        return CSV_JOIN_PROCESS_NAME

    def _project_dir(self):
        return kdq_project_dir()

    def _default_config_path(self):
        path = process_config_path(self._process_name(), DEFAULT_CONFIG_FILENAME, create_dir=True)
        if path:
            return path
        return os.path.join(self._config_dir(), DEFAULT_CONFIG_FILENAME)

    def _write_config(self, path, config):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def _initial_dir(self, fallback=''):
        project_dir = self._project_dir()
        if project_dir:
            return project_dir
        return fallback

    def _initial_dir_from_paths(self, *paths):
        project_dir = self._project_dir()
        if project_dir:
            return project_dir
        for path in paths:
            if not path:
                continue
            if os.path.isdir(path):
                return path
            folder = os.path.dirname(path)
            if folder:
                return folder
        return ''

    def _require_project_dir(self):
        project_dir = self._project_dir()
        if project_dir:
            return project_dir
        QMessageBox.warning(
            self,
            'Organizing Data',
            'QGISプロジェクトが未保存です。\n先にプロジェクトを保存してください。',
        )
        return ''

    def get_config(self):
        steps = []
        for row in range(MAX_STEPS):
            steps.append({
                'mode': self._mode_combo(row).currentData(),
                'csv_b': self._item_text(row, COL_CSV_B),
                'csv_b_encoding': self._csv_b_encoding(row),
                'key_a': self._combo_text(self._key_a_combo(row)),
                'key_b': self._combo_text(self._key_b_combo(row)),
                'fields': self._item_text(row, COL_FIELDS),
                'prefix': self._item_text(row, COL_PREFIX),
                'unmatched_b_csv': self._item_text(row, COL_UNMATCHED_B),
            })
        return {
            'base_csv': self.base_csv_edit.text().strip(),
            'final_output_csv': self.final_output_csv_edit.text().strip(),
            'delimiter': self.delimiter_edit.text() or ',',
            'encoding': self.encoding_edit.currentText().strip() or 'UTF-8',
            'output_encoding': self.output_encoding_edit.currentText().strip() or 'UTF-8',
            'union_folder': self.union_folder_edit.text().strip(),
            'union_csv_a': self.union_csv_a_edit.text().strip(),
            'union_csv_b': self.union_csv_b_edit.text().strip(),
            'union_output_csv': self.union_output_csv_edit.text().strip(),
            'union_encoding': self.union_input_encoding_combo.currentText().strip() or 'UTF-8',
            'union_output_encoding': self.union_output_encoding_combo.currentText().strip() or 'UTF-8',
            'steps': steps,
        }

    def set_config(self, config):
        if not config:
            return
        self.base_csv_edit.setText(config.get('base_csv', ''))
        self.final_output_csv_edit.setText(config.get('final_output_csv', self._last_step_output(config)))
        self.delimiter_edit.setText(config.get('delimiter', ','))
        self.encoding_edit.setCurrentText(config.get('encoding', 'UTF-8'))
        self.output_encoding_edit.setCurrentText(config.get('output_encoding', 'UTF-8'))
        self.union_folder_edit.setText(config.get('union_folder', ''))
        self.union_csv_a_edit.setText(config.get('union_csv_a', ''))
        self.union_csv_b_edit.setText(config.get('union_csv_b', ''))
        self.union_output_csv_edit.setText(config.get('union_output_csv', ''))
        self.union_input_encoding_combo.setCurrentText(config.get('union_encoding', config.get('encoding', 'UTF-8')))
        self.union_output_encoding_combo.setCurrentText(config.get('union_output_encoding', config.get('output_encoding', 'UTF-8')))
        self.refresh_key_a_options()

        steps = config.get('steps', [])
        for row in range(MAX_STEPS):
            step = steps[row] if row < len(steps) else {}
            mode = step.get('mode', MODE_SELECT_FIELDS)
            combo = self._mode_combo(row)
            index = combo.findData(mode)
            combo.setCurrentIndex(index if index >= 0 else 0)
            self._set_item_text(row, COL_CSV_B, step.get('csv_b', ''))
            self._set_csv_b_encoding(row, step.get('csv_b_encoding', config.get('encoding', 'UTF-8')))
            self.refresh_key_b_options(row)
            self._set_combo_text(self._key_a_combo(row), step.get('key_a', ''))
            self._set_combo_text(self._key_b_combo(row), step.get('key_b', ''))
            self._set_item_text(row, COL_FIELDS, step.get('fields', ''))
            self._set_item_text(row, COL_PREFIX, step.get('prefix', ''))
            self._set_item_text(row, COL_UNMATCHED_B, step.get('unmatched_b_csv', ''))
            self.refresh_key_a_options()

    def _last_step_output(self, config):
        steps = [step for step in config.get('steps', []) if step.get('csv_b') and step.get('output_csv')]
        if not steps:
            steps = [step for step in config.get('steps', []) if step.get('enabled') and step.get('output_csv')]
        if steps:
            return steps[-1].get('output_csv', '')
        return ''

    def run_workflow(self):
        config = self.get_config()
        try:
            self._validate_config(config)
        except ValueError as exc:
            QMessageBox.warning(self, 'Organizing Data', str(exc))
            return

        summary = self._execution_summary(config)
        reply = QMessageBox.question(
            self,
            'Organizing Data',
            summary,
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Ok:
            return

        self.log.clear()
        delimiter = config['delimiter']
        encoding = config['encoding']
        output_encoding = config['output_encoding']

        try:
            fieldnames, rows = self._read_csv_rows(config['base_csv'], encoding, delimiter)
            self._log('Base CSV: {}'.format(config['base_csv']))
            self._log('Rows: {}'.format(len(rows)))

            for index, step in enumerate(self._active_steps(config), start=1):
                self._log('Step {}: {}'.format(index, '列を追加' if step['mode'] == MODE_SELECT_FIELDS else '列を上書き'))
                self._log('  B: {}'.format(step['csv_b']))
                self._log('  B Encoding: {}'.format(step.get('csv_b_encoding', encoding)))
                matched_a_keys = self._matched_a_keys(rows, step['key_a'])

                if step['mode'] == MODE_SELECT_FIELDS:
                    fieldnames, rows = self._apply_select_fields_join(
                        fieldnames,
                        rows,
                        step,
                        step.get('csv_b_encoding', encoding),
                        delimiter,
                    )
                else:
                    fieldnames, rows = self._apply_overwrite_fields_join(
                        fieldnames,
                        rows,
                        step,
                        step.get('csv_b_encoding', encoding),
                        delimiter,
                    )
                self._write_unmatched_b_rows_if_requested(
                    rows,
                    step,
                    step.get('csv_b_encoding', encoding),
                    output_encoding,
                    delimiter,
                    matched_a_keys,
                )

            self._write_csv_rows(config['final_output_csv'], fieldnames, rows, output_encoding, delimiter)

        except Exception as exc:
            QMessageBox.critical(self, 'Organizing Data', str(exc))
            self._log('ERROR: {}'.format(exc))
        else:
            self._log('Completed.')
            QMessageBox.information(self, 'Organizing Data', '処理が完了しました。\n\n最終出力:\n{}'.format(config['final_output_csv']))

    def _validate_config(self, config):
        if not config['base_csv']:
            raise ValueError('基準CSVを指定してください。')
        if not Path(config['base_csv']).exists():
            raise ValueError('基準CSVが見つかりません:\n{}'.format(config['base_csv']))
        if not config.get('final_output_csv'):
            raise ValueError('最終出力CSVを指定してください。')
        enabled_steps = self._active_steps(config)
        if not enabled_steps:
            raise ValueError('少なくとも1つのステップを使用してください。')

        for index, step in enumerate(enabled_steps, start=1):
            if not step.get('csv_b'):
                raise ValueError('Step {} の参照CSV(B)を指定してください。'.format(index))
            if not Path(step['csv_b']).exists():
                raise ValueError('Step {} の参照CSV(B)が見つかりません:\n{}'.format(index, step['csv_b']))
            if not step.get('key_a') or not step.get('key_b'):
                raise ValueError('Step {} のキーA・キーBを指定してください。'.format(index))
            if not step.get('fields'):
                raise ValueError('Step {} の追加列 / 上書き対応を指定してください。'.format(index))
            if step['mode'] == MODE_OVERWRITE_FIELDS:
                self._parse_field_map(step['fields'])
            if step.get('unmatched_b_csv') and os.path.abspath(step['unmatched_b_csv']) == os.path.abspath(step['csv_b']):
                raise ValueError('Step {} の未結合B 保存先は参照CSV(B)とは別のCSVを指定してください。'.format(index))

    def _execution_summary(self, config):
        lines = ['以下のLEFT JOIN処理を一括実行します。', '']
        current = config['base_csv']
        for index, step in enumerate(self._active_steps(config), start=1):
            mode = '列を追加' if step['mode'] == MODE_SELECT_FIELDS else '列を上書き'
            lines.extend([
                'Step {}: {}'.format(index, mode),
                'A: {}'.format(current),
                'B: {}'.format(step['csv_b']),
                'B Encoding: {}'.format(step.get('csv_b_encoding') or config.get('encoding') or 'UTF-8'),
                'Key: {} = {}'.format(step['key_a'], step['key_b']),
                'Fields: {}'.format(step['fields']),
                'Unmatched B Output: {}'.format(step.get('unmatched_b_csv') or '(none)'),
                '',
            ])
        lines.append('Final Output: {}'.format(config['final_output_csv']))
        lines.append('')
        lines.append('中間CSVは作成しません。同名の最終出力CSVは上書きされます。実行しますか？')
        return '\n'.join(lines)

    def _read_csv_rows(self, csv_path, encoding, delimiter):
        path = Path(csv_path)
        if not path.exists():
            raise ValueError('CSV file not found: {}'.format(csv_path))
        with open(path, 'r', encoding=encoding, newline='') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            fieldnames = reader.fieldnames
            if not fieldnames:
                raise ValueError('CSV has no header: {}'.format(csv_path))
            return list(fieldnames), list(reader)

    def _read_reference_rows(self, reference_path, _layer_name='', encoding='UTF-8', delimiter=','):
        return self._read_csv_rows(reference_path, encoding, delimiter)

    def _write_csv_rows(self, output_csv, fieldnames, rows, output_encoding, delimiter):
        out_path = Path(output_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding=output_encoding, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=delimiter, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        self._log('Final Output: {}'.format(output_csv))

    def _matched_a_keys(self, rows, key_a):
        return {
            self._join_key(row.get(key_a, ''))
            for row in rows
            if self._join_key(row.get(key_a, ''))
        }
    def _write_unmatched_b_rows_if_requested(self, rows, step, encoding, output_encoding, delimiter, matched_a_keys=None):
        output_csv = step.get('unmatched_b_csv', '').strip()
        if not output_csv:
            return

        reference_b = step.get('csv_b') or step.get('gpkg_b') or step.get('reference_b')
        layer_name = step.get('layer_b', '')
        fields_b, rows_b = self._read_reference_rows(reference_b, layer_name, encoding, delimiter)
        self._validate_fields_exist(fields_b, [step['key_b']], '参照ファイル(B)')

        if matched_a_keys is None:
            matched_a_keys = self._matched_a_keys(rows, step['key_a'])
        unmatched_rows = [
            row for row in rows_b
            if self._join_key(row.get(step['key_b'], '')) not in matched_a_keys
        ]

        out_path = Path(output_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, 'w', encoding=output_encoding, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields_b, delimiter=delimiter, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(unmatched_rows)
        self._log('  Unmatched B rows: {} / {} -> {}'.format(len(unmatched_rows), len(rows_b), output_csv))

    def _union_same_columns_csv(self, csv_a, csv_b, output_csv, encoding, output_encoding, delimiter):
        if not csv_a:
            raise ValueError('CSV 1を指定してください。')
        if not csv_b:
            raise ValueError('CSV 2を指定してください。')
        if not output_csv:
            raise ValueError('UNION結果の出力CSVを指定してください。')
        if not Path(csv_a).exists():
            raise ValueError('CSV 1が見つかりません:\n{}'.format(csv_a))
        if not Path(csv_b).exists():
            raise ValueError('CSV 2が見つかりません:\n{}'.format(csv_b))

        fields_a, rows_a = self._read_csv_rows(csv_a, encoding, delimiter)
        fields_b, rows_b = self._read_csv_rows(csv_b, encoding, delimiter)

        duplicate_a = self._duplicate_fields(fields_a)
        duplicate_b = self._duplicate_fields(fields_b)
        if duplicate_a:
            raise ValueError('CSV 1に重複した列名があります: {}'.format(', '.join(duplicate_a)))
        if duplicate_b:
            raise ValueError('CSV 2に重複した列名があります: {}'.format(', '.join(duplicate_b)))

        missing_in_b = [field for field in fields_a if field not in fields_b]
        extra_in_b = [field for field in fields_b if field not in fields_a]
        if missing_in_b or extra_in_b:
            lines = ['2つのCSVの列名が一致していません。']
            if missing_in_b:
                lines.append('CSV 2にない列: {}'.format(', '.join(missing_in_b)))
            if extra_in_b:
                lines.append('CSV 2にだけある列: {}'.format(', '.join(extra_in_b)))
            raise ValueError('\n'.join(lines))

        output_rows = []
        for row in rows_a:
            output_rows.append({field: row.get(field, '') for field in fields_a})
        for row in rows_b:
            output_rows.append({field: row.get(field, '') for field in fields_a})

        self._write_csv_rows(output_csv, fields_a, output_rows, output_encoding, delimiter)
        return len(output_rows)

    def _union_folder_same_columns_csv(self, folder, output_csv, encoding, output_encoding, delimiter):
        if not folder:
            raise ValueError('UNIONするフォルダを指定してください。')
        if not output_csv:
            raise ValueError('UNION結果の出力CSVを指定してください。')

        folder_path = Path(folder)
        if not folder_path.exists() or not folder_path.is_dir():
            raise ValueError('UNIONするフォルダが見つかりません:\n{}'.format(folder))

        output_path = Path(output_csv)
        output_resolved = output_path.resolve()
        csv_paths = [
            path
            for path in sorted(folder_path.glob('*.csv'), key=lambda item: item.name.lower())
            if path.resolve() != output_resolved
        ]
        if not csv_paths:
            raise ValueError('指定フォルダにCSVファイルが見つかりません:\n{}'.format(folder))

        base_fields = None
        output_rows = []
        for csv_path in csv_paths:
            fieldnames, rows = self._read_csv_rows(str(csv_path), encoding, delimiter)
            duplicates = self._duplicate_fields(fieldnames)
            if duplicates:
                raise ValueError('{} に重複した列名があります: {}'.format(csv_path.name, ', '.join(duplicates)))

            if base_fields is None:
                base_fields = fieldnames
            else:
                missing = [field for field in base_fields if field not in fieldnames]
                extra = [field for field in fieldnames if field not in base_fields]
                if missing or extra:
                    lines = ['{} の列名が1つ目のCSVと一致していません。'.format(csv_path.name)]
                    if missing:
                        lines.append('不足している列: {}'.format(', '.join(missing)))
                    if extra:
                        lines.append('余分な列: {}'.format(', '.join(extra)))
                    raise ValueError('\n'.join(lines))

            for row in rows:
                output_rows.append({field: row.get(field, '') for field in base_fields})

        self._write_csv_rows(output_csv, base_fields, output_rows, output_encoding, delimiter)
        return len(output_rows), len(csv_paths)

    def _duplicate_fields(self, fieldnames):
        seen = set()
        duplicates = []
        for field in fieldnames:
            if field in seen and field not in duplicates:
                duplicates.append(field)
            seen.add(field)
        return duplicates

    def _validate_fields_exist(self, fieldnames, required_fields, label):
        missing = [field for field in required_fields if field not in fieldnames]
        if missing:
            raise ValueError('{} に列が見つかりません: {}'.format(label, ', '.join(missing)))

    def _build_lookup(self, csv_b, key_b, encoding, delimiter):
        fields_b, rows_b = self._read_csv_rows(csv_b, encoding, delimiter)
        self._validate_fields_exist(fields_b, [key_b], '参照CSV(B)')
        lookup = {}
        for row in rows_b:
            key = self._join_key(row.get(key_b, ''))
            if key and key not in lookup:
                lookup[key] = row
        return fields_b, lookup

    def _apply_select_fields_join(self, fieldnames, rows, step, encoding, delimiter):
        selected_fields = self._parse_list(step['fields'])
        prefix = step.get('prefix', '')
        self._validate_fields_exist(fieldnames, [step['key_a']], '基準CSV/前ステップ結果')
        fields_b, lookup = self._build_lookup(step['csv_b'], step['key_b'], encoding, delimiter)
        self._validate_fields_exist(fields_b, selected_fields, '参照CSV(B)')

        output_fields = list(fieldnames)
        joined_field_names = [prefix + field for field in selected_fields]
        for field in joined_field_names:
            if field not in output_fields:
                output_fields.append(field)

        match_count = 0
        for row in rows:
            match = lookup.get(self._join_key(row.get(step['key_a'], '')))
            if match:
                match_count += 1
            for source_field, output_field in zip(selected_fields, joined_field_names):
                row[output_field] = match.get(source_field, '') if match else ''

        self._log('  Added fields: {}'.format(', '.join(joined_field_names)))
        self._log('  Matched rows: {} / {}'.format(match_count, len(rows)))
        return output_fields, rows

    def _apply_overwrite_fields_join(self, fieldnames, rows, step, encoding, delimiter):
        field_map = self._parse_field_map(step['fields'])
        self._validate_fields_exist(fieldnames, [step['key_a']], '基準CSV/前ステップ結果')
        fields_b, lookup = self._build_lookup(step['csv_b'], step['key_b'], encoding, delimiter)
        self._validate_fields_exist(fields_b, list(field_map.values()), '参照CSV(B)')

        output_fields = list(fieldnames)
        for target_field in field_map:
            if target_field not in output_fields:
                output_fields.append(target_field)

        match_count = 0
        overwrite_count = 0
        for row in rows:
            match = lookup.get(self._join_key(row.get(step['key_a'], '')))
            if not match:
                continue
            match_count += 1
            for target_field, source_field in field_map.items():
                value = match.get(source_field, '')
                if value != '':
                    row[target_field] = value
                    overwrite_count += 1

        self._log('  Overwrite mapping: {}'.format(step['fields']))
        self._log('  Matched rows: {} / {}'.format(match_count, len(rows)))
        self._log('  Overwritten cells: {}'.format(overwrite_count))
        return output_fields, rows

    def _parse_list(self, value):
        return [v.strip() for v in value.replace('\n', ',').replace(';', ',').split(',') if v.strip()]

    def _join_key(self, value):
        if value is None:
            return ''
        return str(value).strip()

    def _active_steps(self, config):
        return [step for step in config.get('steps', []) if step.get('csv_b')]

    def _parse_field_map(self, value):
        result = {}
        pairs = self._parse_list(value)
        for pair in pairs:
            if '<-' in pair:
                left, right = pair.split('<-', 1)
            elif '=' in pair:
                left, right = pair.split('=', 1)
            elif ':' in pair:
                left, right = pair.split(':', 1)
            else:
                raise ValueError('上書き対応は A列<-B列 の形式で指定してください:\n{}'.format(pair))
            left = left.strip()
            right = right.strip()
            if not left or not right:
                raise ValueError('上書き対応に空の列名があります:\n{}'.format(pair))
            result[left] = right
        if not result:
            raise ValueError('上書き対応を指定してください。')
        return result

    def _log(self, message):
        self.log.appendPlainText(message)


class OrganizingDataGpkgDialog(OrganizingDataDialog):
    """Sequential GeoPackage LEFT JOIN tool based on the CSV organizing dialog."""

    def __init__(self, parent=None, default_config=None):
        super().__init__(parent, default_config=None)
        self.setWindowTitle('データ整理５ ー GeoPackageへのLeft JoinとUnion')
        self._retitle_ui()
        if default_config:
            self.set_config(default_config)

    def _retitle_ui(self):
        for label in self.findChildren(QLabel):
            text = label.text()
            if text == 'データ整理４ ー CSVへのLeft JoinとUnion':
                label.setText('データ整理５ ー GeoPackageへのLeft JoinとUnion')
            elif text == '基準CSV':
                label.setText('基準GeoPackage')
            elif text == '最終出力CSV':
                label.setText('最終出力GeoPackage')
            elif text in ('区切り', '入力文字コード', '出力文字コード'):
                label.hide()

        for group in self.findChildren(QGroupBox):
            title = group.title()
            if title.startswith('ＣＳＶ LEFT JOIN'):
                group.setTitle('GeoPackage LEFT JOIN（基準レイヤに対して最大10個のLEFT JOINを順番に実行します）')
            elif 'UNION' in title:
                self.gpkg_union_group = group
                group.setTitle('GeoPackage UNION（同じ列名・同じジオメトリ種別の2つのGeoPackageを縦結合）')

        self.base_csv_edit.setPlaceholderText('最初の基準GeoPackage')
        self.final_output_csv_edit.setPlaceholderText('最終出力GeoPackage')
        self.delimiter_edit.hide()
        self.encoding_edit.hide()
        self.output_encoding_edit.hide()
        self.table.setHorizontalHeaderLabels([
            '参照ファイル(B)',
            '処理',
            'キーA',
            'キーB',
            '追加列 / 上書き対応',
            '接頭辞',
        ])

        self.table.setHorizontalHeaderItem(COL_UNMATCHED_B, QTableWidgetItem('未結合B 保存先'))

        self.base_layer_combo = QComboBox()
        self.base_layer_combo.setEditable(True)
        self.base_layer_combo.setInsertPolicy(QComboBox.NoInsert)
        self.base_layer_combo.currentTextChanged.connect(lambda _text: self.refresh_key_a_options())
        self.base_csv_edit.editingFinished.connect(self.on_base_gpkg_changed)
        self.output_layer_name_edit = QLineEdit()
        self.output_layer_name_edit.setPlaceholderText('空欄の場合は基準レイヤ名')
        self.union_layer_a_combo = QComboBox()
        self.union_layer_a_combo.setEditable(True)
        self.union_layer_a_combo.setInsertPolicy(QComboBox.NoInsert)
        self.union_layer_b_combo = QComboBox()
        self.union_layer_b_combo.setEditable(True)
        self.union_layer_b_combo.setInsertPolicy(QComboBox.NoInsert)
        self.union_output_layer_name_edit = QLineEdit()
        self.union_output_layer_name_edit.setPlaceholderText('空欄の場合はGeoPackage 1のレイヤ名')
        self.union_csv_a_edit.setPlaceholderText('1つ目のGeoPackage')
        self.union_csv_b_edit.setPlaceholderText('2つ目のGeoPackage')
        self.union_output_csv_edit.setPlaceholderText('UNION結果の出力GeoPackage')
        self.union_csv_a_edit.editingFinished.connect(lambda: self._refresh_layer_options(
            self.union_csv_a_edit.text().strip(),
            self.union_layer_a_combo,
        ))
        self.union_csv_b_edit.editingFinished.connect(lambda: self._refresh_layer_options(
            self.union_csv_b_edit.text().strip(),
            self.union_layer_b_combo,
        ))

        self._retitle_union_ui()

        left_join_groups = [
            group for group in self.findChildren(QGroupBox)
            if group.title().startswith('GeoPackage LEFT JOIN')
        ]
        if left_join_groups:
            layout = left_join_groups[0].layout()
            layout.addWidget(QLabel('基準レイヤ名'), 0, 3)
            layout.addWidget(self.base_layer_combo, 0, 4, 1, 2)
            layout.addWidget(QLabel('出力レイヤ名'), 1, 3)
            layout.addWidget(self.output_layer_name_edit, 1, 4, 1, 2)

            self.csv_reference_encoding_combo = QComboBox()
            self.csv_reference_encoding_combo.addItems(ENCODING_OPTIONS)
            self.csv_reference_encoding_combo.setMaximumWidth(120)
            self.csv_reference_encoding_combo.currentTextChanged.connect(self._refresh_csv_reference_options)
            self.unmatched_b_output_encoding_combo = QComboBox()
            self.unmatched_b_output_encoding_combo.addItems(ENCODING_OPTIONS)
            self.unmatched_b_output_encoding_combo.setMaximumWidth(120)
            layout.addWidget(QLabel('参照CSV文字コード'), 4, 0)
            layout.addWidget(self.csv_reference_encoding_combo, 4, 1)
            layout.addWidget(QLabel('未結合B CSV文字コード'), 4, 4)
            layout.addWidget(self.unmatched_b_output_encoding_combo, 4, 5)

        hint_labels = [
            label for label in self.findChildren(QLabel)
            if '中間CSVは作成せず' in label.text()
        ]
        for label in hint_labels:
            label.setText(
                '追加列: col1, col2 のように指定。'
                '上書き対応: A列<-B列, A列2<-B列2 のように指定。'
                'ジオメトリは基準GeoPackage(A)のものを維持して、属性だけをLEFT JOINします。'
            )

    def _retitle_union_ui(self):
        group = getattr(self, 'gpkg_union_group', None)
        if not group:
            return
        layout = group.layout()
        if not layout:
            return

        for index in range(layout.count()):
            item = layout.itemAt(index)
            widget = item.widget()
            if widget:
                widget.hide()

        self.union_gpkg_a_browse_button = QPushButton('参照')
        self.union_gpkg_b_browse_button = QPushButton('参照')
        self.union_gpkg_output_browse_button = QPushButton('参照')
        self.union_gpkg_run_button = QPushButton('UNION実行')
        self.union_gpkg_a_browse_button.setMaximumWidth(60)
        self.union_gpkg_b_browse_button.setMaximumWidth(60)
        self.union_gpkg_output_browse_button.setMaximumWidth(60)
        self.union_gpkg_a_browse_button.clicked.connect(
            lambda checked=False: self.browse_union_gpkg(self.union_csv_a_edit, self.union_layer_a_combo)
        )
        self.union_gpkg_b_browse_button.clicked.connect(
            lambda checked=False: self.browse_union_gpkg(self.union_csv_b_edit, self.union_layer_b_combo)
        )
        self.union_gpkg_output_browse_button.clicked.connect(self.browse_union_output_gpkg)
        self.union_gpkg_run_button.clicked.connect(self.run_union_gpkg)
        self.union_gpkg_run_button.setMinimumHeight(28)
        self.union_gpkg_run_button.setStyleSheet(
            'QPushButton {'
            'background-color: #2f6f73; color: white; font-weight: 600;'
            'border: 1px solid #255b5f; border-radius: 3px; padding: 5px 12px;'
            '}'
            'QPushButton:hover { background-color: #367f84; }'
            'QPushButton:pressed { background-color: #285f63; }'
        )

        layout.addWidget(QLabel('GeoPackage 1'), 0, 0)
        layout.addWidget(self.union_csv_a_edit, 0, 1)
        layout.addWidget(self.union_gpkg_a_browse_button, 0, 2)
        layout.addWidget(QLabel('レイヤ'), 0, 3)
        layout.addWidget(self.union_layer_a_combo, 0, 4)
        layout.addWidget(QLabel('GeoPackage 2'), 1, 0)
        layout.addWidget(self.union_csv_b_edit, 1, 1)
        layout.addWidget(self.union_gpkg_b_browse_button, 1, 2)
        layout.addWidget(QLabel('レイヤ'), 1, 3)
        layout.addWidget(self.union_layer_b_combo, 1, 4)
        layout.addWidget(QLabel('出力'), 2, 0)
        layout.addWidget(self.union_output_csv_edit, 2, 1, 1, 3)
        layout.addWidget(self.union_gpkg_output_browse_button, 2, 4)
        layout.addWidget(QLabel('出力レイヤ名'), 3, 0)
        layout.addWidget(self.union_output_layer_name_edit, 3, 1, 1, 4)
        layout.addWidget(self.union_gpkg_run_button, 4, 1, 1, 4)

        for widget in (
            self.union_csv_a_edit,
            self.union_csv_b_edit,
            self.union_output_csv_edit,
            self.union_layer_a_combo,
            self.union_layer_b_combo,
            self.union_output_layer_name_edit,
        ):
            widget.show()

    def _init_row(self, row):
        gpkg_widget = QWidget()
        gpkg_layout = QHBoxLayout(gpkg_widget)
        gpkg_layout.setContentsMargins(2, 2, 2, 2)
        gpkg_layout.setSpacing(4)

        gpkg_edit = QLineEdit()
        gpkg_edit.editingFinished.connect(lambda row=row: self.on_reference_csv_changed(row))
        gpkg_button = QPushButton('参照')
        gpkg_button.setMaximumWidth(54)
        gpkg_button.clicked.connect(lambda checked=False, row=row: self.browse_reference_csv_for_row(row))
        layer_combo = QComboBox()
        layer_combo.setEditable(True)
        layer_combo.setInsertPolicy(QComboBox.NoInsert)
        layer_combo.setMinimumWidth(150)
        layer_combo.currentTextChanged.connect(lambda _text, row=row: self.refresh_key_b_options(row))

        gpkg_layout.addWidget(gpkg_edit, 2)
        gpkg_layout.addWidget(gpkg_button)
        gpkg_layout.addWidget(layer_combo, 1)
        self.table.setCellWidget(row, COL_CSV_B, gpkg_widget)

        mode_combo = QComboBox()
        mode_combo.addItem('列を追加', MODE_SELECT_FIELDS)
        mode_combo.addItem('列を上書き', MODE_OVERWRITE_FIELDS)
        self.table.setCellWidget(row, COL_MODE, mode_combo)

        key_a_combo = QComboBox()
        key_a_combo.setEditable(True)
        self.table.setCellWidget(row, COL_KEY_A, key_a_combo)

        key_b_combo = QComboBox()
        key_b_combo.setEditable(True)
        self.table.setCellWidget(row, COL_KEY_B, key_b_combo)

        fields_widget = QWidget()
        fields_layout = QHBoxLayout(fields_widget)
        fields_layout.setContentsMargins(2, 2, 2, 2)
        fields_layout.setSpacing(4)
        fields_edit = QLineEdit()
        fields_edit.editingFinished.connect(self.refresh_key_a_options)
        fields_button = QPushButton('選択')
        fields_button.setMaximumWidth(54)
        fields_button.clicked.connect(lambda checked=False, row=row: self.open_fields_dialog(row))
        fields_layout.addWidget(fields_edit, 1)
        fields_layout.addWidget(fields_button)
        self.table.setCellWidget(row, COL_FIELDS, fields_widget)

        for col in (COL_PREFIX,):
            item = QTableWidgetItem('')
            self.table.setItem(row, col, item)

        unmatched_widget = QWidget()
        unmatched_layout = QHBoxLayout(unmatched_widget)
        unmatched_layout.setContentsMargins(2, 2, 2, 2)
        unmatched_layout.setSpacing(4)
        unmatched_edit = QLineEdit()
        unmatched_button = QPushButton('参照')
        unmatched_button.setMaximumWidth(54)
        unmatched_button.clicked.connect(lambda checked=False, row=row: self.browse_unmatched_b_csv_for_row(row))
        unmatched_layout.addWidget(unmatched_edit, 1)
        unmatched_layout.addWidget(unmatched_button)
        self.table.setCellWidget(row, COL_UNMATCHED_B, unmatched_widget)

    def _gpkg_layer_combo(self, row):
        return self.table.cellWidget(row, COL_CSV_B).layout().itemAt(2).widget()

    def _selected_base_layer_name(self):
        return self._selected_layer_name_from_combo(self.base_layer_combo)

    def _selected_reference_layer_name(self, row):
        return self._selected_layer_name_from_combo(self._gpkg_layer_combo(row))

    def _is_csv_reference(self, path):
        return (path or '').lower().endswith('.csv')

    def _csv_reference_encoding(self):
        combo = getattr(self, 'csv_reference_encoding_combo', None)
        if combo:
            return combo.currentText().strip() or 'UTF-8'
        return 'UTF-8'

    def _unmatched_b_output_encoding(self):
        combo = getattr(self, 'unmatched_b_output_encoding_combo', None)
        if combo:
            return combo.currentText().strip() or 'UTF-8'
        return 'UTF-8'

    def _refresh_csv_reference_options(self):
        for row in range(MAX_STEPS):
            if self._is_csv_reference(self._item_text(row, COL_CSV_B)):
                self.refresh_key_b_options(row)

    def _selected_layer_name_from_combo(self, combo):
        data = combo.currentData()
        if data:
            return str(data).strip()
        return self._layer_name_from_display(combo.currentText())

    def _layer_name_from_display(self, text):
        text = (text or '').strip()
        if text.endswith('）') and '（' in text:
            return text.rsplit('（', 1)[0].strip()
        return text

    def _refresh_layer_options(self, gpkg_path, combo, selected_name=None):
        current = self._selected_layer_name_from_combo(combo) if selected_name is None else selected_name
        combo.blockSignals(True)
        try:
            combo.clear()
            if gpkg_path and Path(gpkg_path).exists() and list_gpkg_layer_infos:
                for info in list_gpkg_layer_infos(gpkg_path):
                    name = info.get('name', '')
                    geometry_type = info.get('geometry_type') or 'Unknown'
                    if name:
                        combo.addItem('{}（{}）'.format(name, geometry_type), name)
            if current:
                index = self._find_layer_index(combo, current)
                if index < 0:
                    combo.addItem(current, current)
                    index = combo.count() - 1
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(False)

    def _find_layer_index(self, combo, layer_name):
        layer_name = (layer_name or '').strip()
        for index in range(combo.count()):
            if combo.itemData(index) == layer_name:
                return index
        return -1

    def on_base_gpkg_changed(self):
        self._refresh_layer_options(self.base_csv_edit.text().strip(), self.base_layer_combo)
        self.refresh_key_a_options()

    def browse_base_csv(self):
        initial_dir = self._initial_dir_from_paths(
            self.base_csv_edit.text(),
            self.final_output_csv_edit.text(),
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            '基準GeoPackageを選択',
            initial_dir,
            'GeoPackage (*.gpkg);;All files (*.*)',
        )
        if path:
            self.base_csv_edit.setText(path)
            self.final_output_csv_edit.setText(self._default_output_gpkg(path))
            self._refresh_layer_options(path, self.base_layer_combo, '')
            self.refresh_key_a_options()

    def browse_reference_csv_for_row(self, row):
        initial_dir = self._initial_dir_from_paths(
            self._item_text(row, COL_CSV_B),
            self.base_csv_edit.text(),
            self.final_output_csv_edit.text(),
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            '参照ファイルを選択',
            initial_dir,
            'GeoPackage / CSV (*.gpkg *.csv);;GeoPackage (*.gpkg);;CSV (*.csv);;All files (*.*)',
        )
        if path:
            self._set_item_text(row, COL_CSV_B, path)
            self._refresh_reference_layer_options(row, '')
            self.refresh_key_b_options(row)
            self.refresh_key_a_options()

    def on_reference_csv_changed(self, row):
        self._refresh_reference_layer_options(row)
        self.refresh_key_b_options(row)
        self.refresh_key_a_options()

    def _refresh_reference_layer_options(self, row, selected_name=None):
        path = self._item_text(row, COL_CSV_B)
        combo = self._gpkg_layer_combo(row)
        if self._is_csv_reference(path):
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.setEnabled(False)
            finally:
                combo.blockSignals(False)
            return
        combo.setEnabled(True)
        self._refresh_layer_options(path, combo, selected_name)

    def browse_final_output_csv(self):
        initial_dir = self._initial_dir_from_paths(
            self.final_output_csv_edit.text(),
            self.base_csv_edit.text(),
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            '最終出力GeoPackageを指定',
            initial_dir,
            'GeoPackage (*.gpkg);;All files (*.*)',
        )
        if path:
            if not path.lower().endswith('.gpkg'):
                path += '.gpkg'
            self.final_output_csv_edit.setText(path)

    def browse_union_gpkg(self, edit, layer_combo):
        initial_dir = self._initial_dir_from_paths(
            edit.text(),
            self.union_csv_a_edit.text(),
            self.union_csv_b_edit.text(),
            self.union_output_csv_edit.text(),
        )
        path, _ = QFileDialog.getOpenFileName(
            self,
            'UNIONするGeoPackageを選択',
            initial_dir,
            'GeoPackage (*.gpkg);;All files (*.*)',
        )
        if path:
            edit.setText(path)
            self._refresh_layer_options(path, layer_combo, '')

    def browse_union_output_gpkg(self):
        initial_dir = self._initial_dir_from_paths(
            self.union_output_csv_edit.text(),
            self.union_csv_a_edit.text(),
            self.union_csv_b_edit.text(),
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            'UNION結果の出力GeoPackageを指定',
            initial_dir,
            'GeoPackage (*.gpkg);;All files (*.*)',
        )
        if path:
            if not path.lower().endswith('.gpkg'):
                path += '.gpkg'
            self.union_output_csv_edit.setText(path)

    def run_union_gpkg(self):
        gpkg_a = self.union_csv_a_edit.text().strip()
        gpkg_b = self.union_csv_b_edit.text().strip()
        output_gpkg = self.union_output_csv_edit.text().strip()
        layer_a = self._selected_layer_name_from_combo(self.union_layer_a_combo)
        layer_b = self._selected_layer_name_from_combo(self.union_layer_b_combo)
        output_layer = self.union_output_layer_name_edit.text().strip()
        self.log.clear()
        try:
            count = self._union_same_columns_gpkg(gpkg_a, layer_a, gpkg_b, layer_b, output_gpkg, output_layer)
        except Exception as exc:
            QMessageBox.critical(self, 'Organizing Data', str(exc))
            self._log('ERROR: {}'.format(exc))
        else:
            self._log('UNION rows: {}'.format(count))
            QMessageBox.information(self, 'Organizing Data', 'UNIONが完了しました。\n\n出力:\n{}'.format(output_gpkg))

    def _default_output_gpkg(self, input_gpkg):
        root, ext = os.path.splitext(input_gpkg)
        return '{}_整理５_LEFT_JOIN{}'.format(root, ext or '.gpkg')

    def refresh_key_a_options(self):
        fields = []
        base_gpkg = self.base_csv_edit.text().strip()
        if base_gpkg and Path(base_gpkg).exists():
            try:
                fields, _, _, _ = self._read_gpkg_rows(base_gpkg, self._selected_base_layer_name())
            except Exception:
                fields = []

        for row in range(MAX_STEPS):
            step_fields = self._item_text(row, COL_FIELDS)
            if self._mode_combo(row).currentData() == MODE_SELECT_FIELDS:
                prefix = self._item_text(row, COL_PREFIX)
                fields.extend([prefix + field for field in self._parse_list(step_fields)])
            elif step_fields:
                try:
                    fields.extend(list(self._parse_field_map(step_fields).keys()))
                except ValueError:
                    pass

            combo = self._key_a_combo(row)
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self._unique(fields))
            self._set_combo_text(combo, current)
            combo.blockSignals(False)

    def refresh_key_b_options(self, row):
        reference_b = self._item_text(row, COL_CSV_B)
        combo = self._key_b_combo(row)
        current = combo.currentText()
        fields = []
        if reference_b and Path(reference_b).exists():
            try:
                fields, _ = self._read_reference_rows(
                    reference_b,
                    self._selected_reference_layer_name(row),
                    self._csv_reference_encoding(),
                )
            except Exception as exc:
                QMessageBox.warning(self, 'Organizing Data', '参照ファイルの属性を読めませんでした:\n{}'.format(exc))
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(fields)
        self._set_combo_text(combo, current)
        combo.blockSignals(False)

    def _target_fields_for_row(self, row):
        fields = []
        base_gpkg = self.base_csv_edit.text().strip()
        if base_gpkg and Path(base_gpkg).exists():
            try:
                fields, _, _, _ = self._read_gpkg_rows(base_gpkg, self._selected_base_layer_name())
            except Exception:
                fields = []

        for step_row in range(row):
            step_fields = self._item_text(step_row, COL_FIELDS)
            if not step_fields:
                continue
            if self._mode_combo(step_row).currentData() == MODE_SELECT_FIELDS:
                prefix = self._item_text(step_row, COL_PREFIX)
                fields.extend([prefix + field for field in self._parse_list(step_fields)])
            else:
                try:
                    fields.extend(list(self._parse_field_map(step_fields).keys()))
                except ValueError:
                    pass

        try:
            fields.extend(list(self._parse_field_map(self._item_text(row, COL_FIELDS)).keys()))
        except ValueError:
            pass
        return self._unique(fields)

    def open_fields_dialog(self, row):
        reference_b = self._item_text(row, COL_CSV_B)
        if not reference_b:
            QMessageBox.warning(self, 'Organizing Data', '先に参照ファイルを選択してください。')
            return
        if not Path(reference_b).exists():
            QMessageBox.warning(self, 'Organizing Data', '参照ファイルが見つかりません:\n{}'.format(reference_b))
            return

        try:
            fields, _ = self._read_reference_rows(
                reference_b,
                self._selected_reference_layer_name(row),
                self._csv_reference_encoding(),
            )
        except Exception as exc:
            QMessageBox.critical(self, 'Organizing Data', str(exc))
            return

        if self._mode_combo(row).currentData() == MODE_OVERWRITE_FIELDS:
            target_fields = self._target_fields_for_row(row)
            if not target_fields:
                QMessageBox.warning(self, 'Organizing Data', '上書き先(A)の列を取得できませんでした。基準GeoPackageを選択してください。')
                return
            try:
                current_map = self._parse_field_map(self._item_text(row, COL_FIELDS))
            except ValueError:
                current_map = {}
            dialog = OverwriteFieldMappingDialog(fields, target_fields, current_map, self)
            if dialog.exec_() == QDialog.Accepted:
                selected_map = dialog.selected_field_map()
                self._set_item_text(
                    row,
                    COL_FIELDS,
                    ', '.join(['{}<-{}'.format(target, source) for target, source in selected_map.items()]),
                )
                self.refresh_key_a_options()
            return

        dialog = FieldSelectionDialog(fields, self._parse_list(self._item_text(row, COL_FIELDS)), self)
        if dialog.exec_() == QDialog.Accepted:
            self._set_item_text(row, COL_FIELDS, ', '.join(dialog.selected_fields()))
            self.refresh_key_a_options()

    def get_config(self):
        steps = []
        for row in range(MAX_STEPS):
            steps.append({
                'mode': self._mode_combo(row).currentData(),
                'gpkg_b': self._item_text(row, COL_CSV_B),
                'csv_b': self._item_text(row, COL_CSV_B),
                'reference_b': self._item_text(row, COL_CSV_B),
                'layer_b': self._selected_reference_layer_name(row),
                'key_a': self._combo_text(self._key_a_combo(row)),
                'key_b': self._combo_text(self._key_b_combo(row)),
                'fields': self._item_text(row, COL_FIELDS),
                'prefix': self._item_text(row, COL_PREFIX),
                'unmatched_b_csv': self._item_text(row, COL_UNMATCHED_B),
                'csv_b_encoding': self._csv_reference_encoding(),
            })
        return {
            'base_gpkg': self.base_csv_edit.text().strip(),
            'base_layer': self._selected_base_layer_name(),
            'final_output_gpkg': self.final_output_csv_edit.text().strip(),
            'output_layer_name': self.output_layer_name_edit.text().strip(),
            'csv_reference_encoding': self._csv_reference_encoding(),
            'unmatched_b_output_encoding': self._unmatched_b_output_encoding(),
            'union_gpkg_a': self.union_csv_a_edit.text().strip(),
            'union_layer_a': self._selected_layer_name_from_combo(self.union_layer_a_combo),
            'union_gpkg_b': self.union_csv_b_edit.text().strip(),
            'union_layer_b': self._selected_layer_name_from_combo(self.union_layer_b_combo),
            'union_output_gpkg': self.union_output_csv_edit.text().strip(),
            'union_output_layer_name': self.union_output_layer_name_edit.text().strip(),
            'steps': steps,
        }

    def set_config(self, config):
        if not config:
            return
        self.base_csv_edit.setText(config.get('base_gpkg', config.get('base_csv', '')))
        self.final_output_csv_edit.setText(config.get('final_output_gpkg', config.get('final_output_csv', '')))
        self._refresh_layer_options(self.base_csv_edit.text().strip(), self.base_layer_combo, config.get('base_layer', ''))
        self.output_layer_name_edit.setText(config.get('output_layer_name', ''))
        self.union_csv_a_edit.setText(config.get('union_gpkg_a', config.get('union_csv_a', '')))
        self.union_csv_b_edit.setText(config.get('union_gpkg_b', config.get('union_csv_b', '')))
        self.union_output_csv_edit.setText(config.get('union_output_gpkg', config.get('union_output_csv', '')))
        self.union_output_layer_name_edit.setText(config.get('union_output_layer_name', ''))
        self._refresh_layer_options(self.union_csv_a_edit.text().strip(), self.union_layer_a_combo, config.get('union_layer_a', ''))
        self._refresh_layer_options(self.union_csv_b_edit.text().strip(), self.union_layer_b_combo, config.get('union_layer_b', ''))
        self._set_combo_text(
            self.csv_reference_encoding_combo,
            config.get('csv_reference_encoding', config.get('encoding', 'UTF-8')),
        )
        self._set_combo_text(
            self.unmatched_b_output_encoding_combo,
            config.get('unmatched_b_output_encoding', config.get('output_encoding', 'UTF-8')),
        )
        self.refresh_key_a_options()

        steps = config.get('steps', [])
        for row in range(MAX_STEPS):
            step = steps[row] if row < len(steps) else {}
            mode = step.get('mode', MODE_SELECT_FIELDS)
            combo = self._mode_combo(row)
            index = combo.findData(mode)
            combo.setCurrentIndex(index if index >= 0 else 0)
            self._set_item_text(row, COL_CSV_B, step.get('reference_b', step.get('gpkg_b', step.get('csv_b', ''))))
            self._refresh_reference_layer_options(row, step.get('layer_b', ''))
            self.refresh_key_b_options(row)
            self._set_combo_text(self._key_a_combo(row), step.get('key_a', ''))
            self._set_combo_text(self._key_b_combo(row), step.get('key_b', ''))
            self._set_item_text(row, COL_FIELDS, step.get('fields', ''))
            self._set_item_text(row, COL_PREFIX, step.get('prefix', ''))
            self._set_item_text(row, COL_UNMATCHED_B, step.get('unmatched_b_csv', ''))
            self.refresh_key_a_options()

    def _default_config_path(self):
        path = process_config_path(self._process_name(), GPKG_DEFAULT_CONFIG_FILENAME, create_dir=True)
        if path:
            return path
        return os.path.join(self._config_dir(), GPKG_DEFAULT_CONFIG_FILENAME)

    def _process_name(self):
        return GPKG_JOIN_PROCESS_NAME

    def run_workflow(self):
        config = self.get_config()
        try:
            self._validate_config(config)
        except ValueError as exc:
            QMessageBox.warning(self, 'Organizing Data', str(exc))
            return

        summary = self._execution_summary(config)
        reply = QMessageBox.question(
            self,
            'Organizing Data',
            summary,
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Ok:
            return

        self.log.clear()
        try:
            fieldnames, rows, geometries, source_layer = self._read_gpkg_rows(
                config['base_gpkg'],
                config.get('base_layer', ''),
            )
            self._log('Base GeoPackage: {}'.format(config['base_gpkg']))
            self._log('Base layer: {}'.format(source_layer.name()))
            self._log('Rows: {}'.format(len(rows)))

            for index, step in enumerate(self._active_steps(config), start=1):
                self._log('Step {}: {}'.format(index, '列を追加' if step['mode'] == MODE_SELECT_FIELDS else '列を上書き'))
                self._log('  B: {}{}'.format(
                    step['gpkg_b'],
                    '' if self._is_csv_reference(step['gpkg_b']) else ' / {}'.format(step.get('layer_b', '')),
                ))
                matched_a_keys = self._matched_a_keys(rows, step['key_a'])

                if step['mode'] == MODE_SELECT_FIELDS:
                    fieldnames, rows = self._apply_select_fields_join(fieldnames, rows, step, '', '')
                else:
                    fieldnames, rows = self._apply_overwrite_fields_join(fieldnames, rows, step, '', '')
                self._write_unmatched_b_rows_if_requested(
                    rows,
                    step,
                    config.get('csv_reference_encoding', 'UTF-8'),
                    config.get('unmatched_b_output_encoding', 'UTF-8'),
                    ',',
                    matched_a_keys,
                )

            self._write_gpkg_rows(
                config['final_output_gpkg'],
                config.get('output_layer_name') or source_layer.name(),
                source_layer,
                fieldnames,
                rows,
                geometries,
            )
        except Exception as exc:
            QMessageBox.critical(self, 'Organizing Data', str(exc))
            self._log('ERROR: {}'.format(exc))
        else:
            self._log('Completed.')
            QMessageBox.information(self, 'Organizing Data', '処理が完了しました。\n\n最終出力:\n{}'.format(config['final_output_gpkg']))

    def _validate_config(self, config):
        if not config['base_gpkg']:
            raise ValueError('基準GeoPackageを指定してください。')
        if not Path(config['base_gpkg']).exists():
            raise ValueError('基準GeoPackageが見つかりません:\n{}'.format(config['base_gpkg']))
        if not config.get('final_output_gpkg'):
            raise ValueError('最終出力GeoPackageを指定してください。')
        if os.path.abspath(config['base_gpkg']) == os.path.abspath(config['final_output_gpkg']):
            raise ValueError('基準GeoPackageとは別の出力先を指定してください。')
        enabled_steps = self._active_steps(config)
        if not enabled_steps:
            raise ValueError('少なくとも1つのステップを使用してください。')

        for index, step in enumerate(enabled_steps, start=1):
            if not step.get('gpkg_b'):
                raise ValueError('Step {} の参照ファイル(B)を指定してください。'.format(index))
            if not Path(step['gpkg_b']).exists():
                raise ValueError('Step {} の参照ファイル(B)が見つかりません:\n{}'.format(index, step['gpkg_b']))
            if os.path.abspath(step['gpkg_b']) == os.path.abspath(config['final_output_gpkg']):
                raise ValueError('Step {} の参照ファイル(B)とは別の出力先を指定してください。'.format(index))
            if not step.get('key_a') or not step.get('key_b'):
                raise ValueError('Step {} のキーA・キーBを指定してください。'.format(index))
            if not step.get('fields'):
                raise ValueError('Step {} の追加列 / 上書き対応を指定してください。'.format(index))
            if step['mode'] == MODE_OVERWRITE_FIELDS:
                self._parse_field_map(step['fields'])
            if step.get('unmatched_b_csv') and os.path.abspath(step['unmatched_b_csv']) == os.path.abspath(step['csv_b']):
                raise ValueError('Step {} の未結合B 保存先は参照CSV(B)とは別のCSVを指定してください。'.format(index))

    def _execution_summary(self, config):
        lines = ['以下のGeoPackage LEFT JOIN処理を一括実行します。', '']
        for index, step in enumerate(self._active_steps(config), start=1):
            mode = '列を追加' if step['mode'] == MODE_SELECT_FIELDS else '列を上書き'
            lines.extend([
                'Step {}: {}'.format(index, mode),
                'A: {} / {}'.format(config['base_gpkg'], config.get('base_layer', '')),
                'B: {}{}'.format(
                    step['gpkg_b'],
                    '' if self._is_csv_reference(step['gpkg_b']) else ' / {}'.format(step.get('layer_b', '')),
                ),
                'Key: {} = {}'.format(step['key_a'], step['key_b']),
                'Fields: {}'.format(step['fields']),
                'Unmatched B Output: {}'.format(step.get('unmatched_b_csv') or '(none)'),
                '',
            ])
        lines.append('Final Output: {}'.format(config['final_output_gpkg']))
        lines.append('')
        lines.append('同名の最終出力GeoPackageは上書きされます。実行しますか？')
        return '\n'.join(lines)

    def _active_steps(self, config):
        return [step for step in config.get('steps', []) if step.get('gpkg_b') or step.get('csv_b')]

    def _build_lookup(self, gpkg_b, key_b, _encoding, _delimiter):
        step = getattr(self, '_current_lookup_step', None)
        layer_name = step.get('layer_b', '') if step else ''
        encoding = step.get('csv_b_encoding', self._csv_reference_encoding()) if step else self._csv_reference_encoding()
        fields_b, rows_b = self._read_reference_rows(gpkg_b, layer_name, encoding)
        self._validate_fields_exist(fields_b, [key_b], '参照ファイル(B)')
        lookup = {}
        for row in rows_b:
            key = self._join_key(row.get(key_b, ''))
            if key and key not in lookup:
                lookup[key] = row
        return fields_b, lookup

    def _apply_select_fields_join(self, fieldnames, rows, step, encoding, delimiter):
        self._current_lookup_step = step
        try:
            return super()._apply_select_fields_join(fieldnames, rows, step, encoding, delimiter)
        finally:
            self._current_lookup_step = None

    def _apply_overwrite_fields_join(self, fieldnames, rows, step, encoding, delimiter):
        self._current_lookup_step = step
        try:
            return super()._apply_overwrite_fields_join(fieldnames, rows, step, encoding, delimiter)
        finally:
            self._current_lookup_step = None

    def _read_gpkg_rows(self, gpkg_path, layer_name=''):
        if open_gpkg_layer is None:
            raise ValueError('GeoPackage読み込み機能を初期化できませんでした。')
        layer = open_gpkg_layer(gpkg_path, layer_name)
        fields = [field.name() for field in layer.fields()]
        rows = []
        geometries = []
        for feature in layer.getFeatures():
            rows.append({
                field: feature[field]
                for field in fields
            })
            geometry = feature.geometry()
            geometries.append(QgsGeometry(geometry) if geometry and not geometry.isEmpty() else QgsGeometry())
        return fields, rows, geometries, layer

    def _union_same_columns_gpkg(self, gpkg_a, layer_a, gpkg_b, layer_b, output_gpkg, output_layer_name=''):
        if not gpkg_a:
            raise ValueError('GeoPackage 1を指定してください。')
        if not gpkg_b:
            raise ValueError('GeoPackage 2を指定してください。')
        if not output_gpkg:
            raise ValueError('UNION結果の出力GeoPackageを指定してください。')
        if not Path(gpkg_a).exists():
            raise ValueError('GeoPackage 1が見つかりません:\n{}'.format(gpkg_a))
        if not Path(gpkg_b).exists():
            raise ValueError('GeoPackage 2が見つかりません:\n{}'.format(gpkg_b))
        if os.path.abspath(gpkg_a) == os.path.abspath(output_gpkg):
            raise ValueError('GeoPackage 1とは別の出力先を指定してください。')
        if os.path.abspath(gpkg_b) == os.path.abspath(output_gpkg):
            raise ValueError('GeoPackage 2とは別の出力先を指定してください。')

        fields_a, rows_a, geometries_a, source_layer = self._read_gpkg_rows(gpkg_a, layer_a)
        fields_b, rows_b, geometries_b, layer_b_obj = self._read_gpkg_rows(gpkg_b, layer_b)

        duplicate_a = self._duplicate_fields(fields_a)
        duplicate_b = self._duplicate_fields(fields_b)
        if duplicate_a:
            raise ValueError('GeoPackage 1に重複した列名があります: {}'.format(', '.join(duplicate_a)))
        if duplicate_b:
            raise ValueError('GeoPackage 2に重複した列名があります: {}'.format(', '.join(duplicate_b)))

        missing_in_b = [field for field in fields_a if field not in fields_b]
        extra_in_b = [field for field in fields_b if field not in fields_a]
        if missing_in_b or extra_in_b:
            lines = ['2つのGeoPackageレイヤの列名が一致していません。']
            if missing_in_b:
                lines.append('GeoPackage 2にない列: {}'.format(', '.join(missing_in_b)))
            if extra_in_b:
                lines.append('GeoPackage 2にだけある列: {}'.format(', '.join(extra_in_b)))
            raise ValueError('\n'.join(lines))

        geometry_a = QgsWkbTypes.geometryType(source_layer.wkbType())
        geometry_b = QgsWkbTypes.geometryType(layer_b_obj.wkbType())
        if geometry_a != geometry_b:
            raise ValueError(
                'ジオメトリ種別が一致していません。\nGeoPackage 1: {}\nGeoPackage 2: {}'.format(
                    QgsWkbTypes.displayString(source_layer.wkbType()),
                    QgsWkbTypes.displayString(layer_b_obj.wkbType()),
                )
            )
        crs_a = source_layer.crs().authid()
        crs_b = layer_b_obj.crs().authid()
        if crs_a != crs_b:
            raise ValueError('CRSが一致していません。\nGeoPackage 1: {}\nGeoPackage 2: {}'.format(crs_a, crs_b))

        output_rows = []
        for row in rows_a:
            output_rows.append({field: row.get(field, '') for field in fields_a})
        for row in rows_b:
            output_rows.append({field: row.get(field, '') for field in fields_a})

        output_geometries = geometries_a + geometries_b
        layer_name = output_layer_name or source_layer.name()
        self._write_gpkg_rows(output_gpkg, layer_name, source_layer, fields_a, output_rows, output_geometries)
        return len(output_rows)

    def _read_reference_rows(self, reference_path, layer_name='', encoding='UTF-8', delimiter=','):
        if self._is_csv_reference(reference_path):
            delimiter = delimiter or self.delimiter_edit.text() or ','
            encoding = encoding or self.encoding_edit.currentText().strip() or 'UTF-8'
            return self._read_csv_rows(reference_path, encoding, delimiter)
        fields, rows, _, _ = self._read_gpkg_rows(reference_path, layer_name)
        return fields, rows

    def _display_value(self, value):
        if value is None:
            return ''
        return str(value)

    def _join_key(self, value):
        text = unicodedata.normalize('NFKC', self._display_value(value)).strip()
        return ''.join(text.split())

    def _write_gpkg_rows(self, output_gpkg, layer_name, source_layer, fieldnames, rows, geometries):
        folder = os.path.dirname(output_gpkg)
        if folder:
            os.makedirs(folder, exist_ok=True)

        geometry_name = QgsWkbTypes.displayString(source_layer.wkbType())
        if source_layer.wkbType() == QgsWkbTypes.NoGeometry:
            geometry_name = 'None'
        crs_authid = source_layer.crs().authid()
        uri = '{}?crs={}'.format(geometry_name, crs_authid) if crs_authid else geometry_name
        output_layer = QgsVectorLayer(uri, layer_name, 'memory')
        provider = output_layer.dataProvider()
        provider.addAttributes(self._output_fields(source_layer, fieldnames, rows))
        output_layer.updateFields()

        output_fields = output_layer.fields()
        features = []
        for index, row in enumerate(rows):
            geometry = geometries[index] if index < len(geometries) else QgsGeometry()
            feature = QgsFeature(output_fields)
            if geometry and not geometry.isEmpty():
                feature.setGeometry(geometry)
            feature.setAttributes([row.get(field, '') for field in fieldnames])
            features.append(feature)

        ok, added_features = provider.addFeatures(features)
        if not ok or len(added_features) != len(features):
            raise RuntimeError(
                'GeoPackage出力レイヤへの行追加に失敗しました。入力: {} 行 / 追加: {} 行'.format(
                    len(features),
                    len(added_features) if added_features is not None else 0,
                )
            )
        output_layer.updateExtents()

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = layer_name
        options.fileEncoding = 'UTF-8'
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            output_layer,
            output_gpkg,
            QgsProject.instance().transformContext(),
            options,
        )
        if result[0] != QgsVectorFileWriter.NoError:
            message = result[1] if len(result) > 1 else 'GeoPackageの保存に失敗しました。'
            raise RuntimeError(message)
        self._log('Final Output: {}'.format(output_gpkg))

    def _output_fields(self, source_layer, fieldnames, rows=None):
        source_fields = {field.name(): field for field in source_layer.fields()}
        result = []
        used = set()
        for fieldname in fieldnames:
            source_field = source_fields.get(fieldname)
            if source_field and not self._field_has_joined_string_values(fieldname, rows):
                field = QgsField(source_field)
            else:
                field = QgsField(fieldname, QVariant.String)
            if field.name() in used:
                base = field.name()
                suffix = 2
                while '{}_{}'.format(base, suffix) in used:
                    suffix += 1
                field.setName('{}_{}'.format(base, suffix))
            used.add(field.name())
            result.append(field)
        return result

    def _field_has_joined_string_values(self, fieldname, rows):
        if not rows:
            return False
        for row in rows:
            value = row.get(fieldname)
            if isinstance(value, str) and value != '':
                return True
        return False


class OrganizingDataTool:
    """Open the generic CSV organizing dialog."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dlg = None

    def run(self):
        if self.dlg is None:
            default_config = self._startup_config()
            if default_config is None:
                return
            self.dlg = OrganizingDataDialog(
                parent=self.iface.mainWindow(),
                default_config=default_config,
            )
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def _startup_config(self):
        config_path = process_config_path(CSV_JOIN_PROCESS_NAME, DEFAULT_CONFIG_FILENAME)
        if not config_path:
            config_path = os.path.join(self.plugin_dir, 'configs', DEFAULT_CONFIG_FILENAME)

        if os.path.exists(config_path):
            reply = QMessageBox.question(
                self.iface.mainWindow(),
                'データ整理４',
                '初期設定を読み込みますか？\n\n{}'.format(config_path),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return self._empty_config()
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        return self._empty_config()

    def _empty_config(self):
        return {
            'base_csv': '',
            'final_output_csv': '',
            'delimiter': ',',
            'encoding': 'UTF-8',
            'output_encoding': 'UTF-8',
            'steps': [],
        }


class OrganizingDataGpkgTool(OrganizingDataTool):
    """Open the GeoPackage LEFT JOIN organizing dialog."""

    def run(self):
        if self.dlg is None:
            default_config = self._startup_config()
            if default_config is None:
                return
            self.dlg = OrganizingDataGpkgDialog(
                parent=self.iface.mainWindow(),
                default_config=default_config,
            )
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def _startup_config(self):
        config_path = process_config_path(GPKG_JOIN_PROCESS_NAME, GPKG_DEFAULT_CONFIG_FILENAME)
        if not config_path:
            config_path = os.path.join(self.plugin_dir, 'configs', GPKG_DEFAULT_CONFIG_FILENAME)

        if os.path.exists(config_path):
            reply = QMessageBox.question(
                self.iface.mainWindow(),
                'データ整理５',
                '初期設定を読み込みますか？\n\n{}'.format(config_path),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return self._empty_config()
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)

        return self._empty_config()

    def _empty_config(self):
        return {
            'base_gpkg': '',
            'base_layer': '',
            'final_output_gpkg': '',
            'output_layer_name': '',
            'steps': [],
        }

