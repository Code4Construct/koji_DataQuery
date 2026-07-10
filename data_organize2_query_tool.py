# -*- coding: utf-8 -*-

import csv
import json
import os

from qgis.PyQt.QtCore import Qt
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
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .data_organize1_processor import normalize_headers
from .config_paths import process_config_dir, process_config_path, project_dir as kdq_project_dir


DEFAULT_CONFIG_FILENAME = 'preset.json'
PROCESS_NAME = 'CSV集計クエリ'


AGGREGATE_OPERATIONS = [
    ('sum', '和'),
    ('count', 'カウント'),
    ('count_non_empty', '空白以外をカウント'),
    ('newline_list', '文字列の改行列挙'),
    ('unique_newline_list', '文字列の改行列挙（重複なし）'),
    ('first', '先頭値'),
    ('min', '最小'),
    ('max', '最大'),
]


class CsvColumnSelectionDialog(QDialog):
    """Select one or more CSV columns."""

    def __init__(self, columns, selected_columns=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('列を選択')
        self.resize(420, 520)
        selected_columns = selected_columns or []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('使用する列を選択してください。'))

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText('列名で絞り込み')
        self.filter_edit.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter_edit)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.check_layout = QVBoxLayout(content)
        self.check_layout.setContentsMargins(4, 4, 4, 4)
        self.rows = []
        self.checkboxes = []
        self.selected_order = [column for column in selected_columns if column in columns]

        for column in columns:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            checkbox = QCheckBox(column)
            checkbox.setChecked(column in selected_columns)
            order_label = QLabel('')
            order_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            order_label.setMinimumWidth(28)
            checkbox.stateChanged.connect(lambda _state, column=column: self.on_checked_changed(column))
            row_layout.addWidget(checkbox, 1)
            row_layout.addWidget(order_label)
            self.check_layout.addWidget(row_widget)
            self.rows.append((column, row_widget, checkbox, order_label))
            self.checkboxes.append(checkbox)

        self.check_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.update_order_labels()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def apply_filter(self, text):
        text = (text or '').strip().lower()
        for _column, row_widget, checkbox, _order_label in self.rows:
            row_widget.setVisible(text in checkbox.text().lower())

    def on_checked_changed(self, column):
        checkbox = self.checkbox_for_column(column)
        if checkbox and checkbox.isChecked():
            if column not in self.selected_order:
                self.selected_order.append(column)
        else:
            self.selected_order = [value for value in self.selected_order if value != column]
        self.update_order_labels()

    def checkbox_for_column(self, column):
        for row_column, _row_widget, checkbox, _order_label in self.rows:
            if row_column == column:
                return checkbox
        return None

    def update_order_labels(self):
        selected_set = {column for column, _row_widget, checkbox, _order_label in self.rows if checkbox.isChecked()}
        self.selected_order = [column for column in self.selected_order if column in selected_set]
        for column, _row_widget, checkbox, _order_label in self.rows:
            if checkbox.isChecked() and column not in self.selected_order:
                self.selected_order.append(column)
        order_by_column = {
            column: index + 1
            for index, column in enumerate(self.selected_order)
        }
        for column, _row_widget, checkbox, order_label in self.rows:
            order_label.setText(str(order_by_column[column]) if checkbox.isChecked() else '')

    def selected_columns(self):
        return list(self.selected_order)


class DataOrganize2QueryDialog(QDialog):
    """Create grouped aggregate CSV keys from a source CSV."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('データ整理３ ー CSVの集計クエリ')
        self.resize(1040, 720)
        self.current_headers = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel('データ整理３ ー CSVの集計クエリ')
        title.setStyleSheet('font-size: 17px; font-weight: 600;')
        layout.addWidget(title)

        io_group = QGroupBox('入出力')
        io_layout = QGridLayout(io_group)
        io_layout.setColumnStretch(1, 1)

        self.input_csv_edit = QLineEdit()
        self.input_csv_edit.setPlaceholderText('集計するCSVファイル')
        input_browse = QPushButton('参照')
        input_browse.clicked.connect(self.browse_input_csv)

        self.output_csv_edit = QLineEdit()
        self.output_csv_edit.setPlaceholderText('出力CSVファイル')
        output_browse = QPushButton('参照')
        output_browse.clicked.connect(self.browse_output_csv)

        self.delimiter_combo = QComboBox()
        self.delimiter_combo.addItems([',', '\\t', ';'])
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(['UTF-8', 'utf-8-sig', 'CP932', 'Shift_JIS'])
        self.output_encoding_combo = QComboBox()
        self.output_encoding_combo.addItems(['UTF-8', 'utf-8-sig', 'CP932', 'Shift_JIS'])

        self.status_label = QLabel('')
        io_layout.addWidget(QLabel('入力CSV'), 0, 0)
        io_layout.addWidget(self.input_csv_edit, 0, 1)
        io_layout.addWidget(input_browse, 0, 2)
        io_layout.addWidget(QLabel('入力文字コード'), 0, 3)
        io_layout.addWidget(self.encoding_combo, 0, 4)
        io_layout.addWidget(QLabel('出力CSV'), 1, 0)
        io_layout.addWidget(self.output_csv_edit, 1, 1)
        io_layout.addWidget(output_browse, 1, 2)
        io_layout.addWidget(QLabel('出力文字コード'), 1, 3)
        io_layout.addWidget(self.output_encoding_combo, 1, 4)
        io_layout.addWidget(self.status_label, 2, 1, 1, 4)
        layout.addWidget(io_group)

        key_group = QGroupBox('グループ化キー')
        key_layout = QHBoxLayout(key_group)
        self.key_columns_edit = QLineEdit()
        self.key_columns_edit.setPlaceholderText('例: 地番, 所有者')
        key_select = QPushButton('列を選択')
        key_select.clicked.connect(self.select_key_columns)
        key_layout.addWidget(QLabel('キー列'))
        key_layout.addWidget(self.key_columns_edit, 1)
        key_layout.addWidget(key_select)
        layout.addWidget(key_group)

        agg_group = QGroupBox('集計内容')
        agg_layout = QVBoxLayout(agg_group)
        toolbar = QHBoxLayout()
        add_button = QPushButton('集計行を追加')
        delete_button = QPushButton('削除')
        up_button = QPushButton('上へ')
        down_button = QPushButton('下へ')
        add_button.clicked.connect(self.add_aggregate_row)
        delete_button.clicked.connect(self.delete_selected_aggregate_row)
        up_button.clicked.connect(self.move_selected_aggregate_row_up)
        down_button.clicked.connect(self.move_selected_aggregate_row_down)
        toolbar.addWidget(add_button)
        toolbar.addWidget(delete_button)
        toolbar.addWidget(up_button)
        toolbar.addWidget(down_button)
        toolbar.addStretch(1)
        agg_layout.addLayout(toolbar)

        self.aggregation_table = QTableWidget(0, 4)
        self.aggregation_table.setHorizontalHeaderLabels(['対象列', '集計方法', '集計列名'])
        self.aggregation_table.setHorizontalHeaderLabels(['集計方法', '対象列', '集計列名'])
        self.aggregation_table.setHorizontalHeaderLabels(['対象列', '集計方法', '集計列名', ''])
        self.aggregation_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.aggregation_table.horizontalHeader().setStretchLastSection(False)
        self.aggregation_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.aggregation_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.aggregation_table.setColumnWidth(0, 320)
        self.aggregation_table.setColumnWidth(1, 220)
        self.aggregation_table.setColumnWidth(3, 90)
        agg_layout.addWidget(self.aggregation_table, 1)
        layout.addWidget(agg_group, 1)

        preview_group = QGroupBox('プレビュー')
        preview_layout = QVBoxLayout(preview_group)
        self.preview_table = QTableWidget(0, 0)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        preview_layout.addWidget(self.preview_table)
        layout.addWidget(preview_group, 1)

        footer = QHBoxLayout()
        load_button = QPushButton('プリセット呼出')
        save_button = QPushButton('プリセット更新')
        default_load_button = QPushButton('設定読込')
        default_save_button = QPushButton('設定保存')
        preview_button = QPushButton('プレビュー更新')
        run_button = QPushButton('実行')
        close_button = QPushButton('Close')
        load_button.clicked.connect(self.load_default_config)
        save_button.clicked.connect(self.save_default_config)
        default_load_button.clicked.connect(self.load_config_dialog)
        default_save_button.clicked.connect(self.save_config_dialog)
        preview_button.clicked.connect(self.update_preview)
        run_button.clicked.connect(self.run_processing)
        close_button.clicked.connect(self.reject)
        footer.addWidget(load_button)
        footer.addWidget(save_button)
        footer.addWidget(default_load_button)
        footer.addWidget(default_save_button)
        footer.addStretch(1)
        footer.addWidget(preview_button)
        footer.addWidget(run_button)
        footer.addWidget(close_button)
        layout.addLayout(footer)

        self.input_csv_edit.editingFinished.connect(self.load_headers)
        self.delimiter_combo.currentTextChanged.connect(lambda _text: self.load_headers())
        self.encoding_combo.currentTextChanged.connect(lambda _text: self.load_headers())
        self.add_aggregate_row('sum', '', '')
        self.add_aggregate_row('count', '', '')
        self.add_aggregate_row('unique_newline_list', '', '')

    def delimiter(self):
        delimiter = self.delimiter_combo.currentText()
        return '\t' if delimiter == '\\t' else delimiter

    def browse_input_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            '入力CSVを選択',
            '',
            'CSV (*.csv);;All files (*.*)',
        )
        if not path:
            return
        self.input_csv_edit.setText(path)
        if not self.output_csv_edit.text().strip():
            root, ext = os.path.splitext(path)
            self.output_csv_edit.setText('{}_集計キー{}'.format(root, ext or '.csv'))
        self.load_headers()

    def browse_output_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            '出力CSVを指定',
            '',
            'CSV (*.csv);;All files (*.*)',
        )
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        self.output_csv_edit.setText(path)

    def get_config(self):
        return {
            'input_csv': self.input_csv_edit.text().strip(),
            'output_csv': self.output_csv_edit.text().strip(),
            'delimiter': self.delimiter_combo.currentText(),
            'encoding': self.encoding_combo.currentText(),
            'output_encoding': self.output_encoding_combo.currentText(),
            'key_columns': self.key_columns_edit.text().strip(),
            'aggregates': self.aggregate_configs(include_empty=True),
        }

    def set_config(self, config):
        if not config:
            return
        self.input_csv_edit.setText(config.get('input_csv', ''))
        self.output_csv_edit.setText(config.get('output_csv', ''))
        if config.get('delimiter'):
            self.delimiter_combo.setCurrentText(config.get('delimiter'))
        if config.get('encoding'):
            self.encoding_combo.setCurrentText(config.get('encoding'))
        self.output_encoding_combo.setCurrentText(config.get('output_encoding', config.get('encoding', 'UTF-8')))
        self.key_columns_edit.setText(config.get('key_columns', ''))
        self.load_headers()
        aggregates = config.get('aggregates') or []
        if aggregates:
            self.rebuild_aggregate_rows(aggregates)
        else:
            self.aggregation_table.setRowCount(0)
            self.add_aggregate_row('sum', '', '')
            self.add_aggregate_row('count', '', '')
            self.add_aggregate_row('unique_newline_list', '', '')

    def load_config_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            '設定JSONを読込',
            self.config_initial_dir(),
            'JSON (*.json);;All files (*.*)',
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.set_config(json.load(f))
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理３', str(exc))

    def save_config_dialog(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            '設定JSONを保存',
            self.config_initial_dir(),
            'JSON (*.json);;All files (*.*)',
        )
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        try:
            self.write_config(path)
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理３', str(exc))
        else:
            QMessageBox.information(self, 'データ整理３', '設定を保存しました。\n\n{}'.format(path))

    def load_default_config(self):
        path = self.default_config_path()
        if not path:
            return
        if not os.path.exists(path):
            QMessageBox.warning(
                self,
                'データ整理３',
                'プリセットファイルが見つかりません。\n「プリセット更新」で現在の設定を保存してください。\n\n{}'.format(path),
            )
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.set_config(json.load(f))
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理３', str(exc))
        else:
            QMessageBox.information(self, 'データ整理３', 'プリセットを呼び出しました。\n\n{}'.format(path))

    def save_default_config(self):
        path = self.default_config_path()
        if not path:
            return
        try:
            self.write_config(path)
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理３', str(exc))
        else:
            QMessageBox.information(self, 'データ整理３', 'プリセットを更新しました。\n\n{}'.format(path))

    def ask_load_default_config_on_startup(self):
        path = self.default_config_path(silent=True)
        if not path or not os.path.exists(path):
            return
        reply = QMessageBox.question(
            self,
            'データ整理３',
            'プリセットを読み込みますか？\n\n{}'.format(path),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.set_config(json.load(f))
            except Exception as exc:
                QMessageBox.critical(self, 'データ整理３', str(exc))

    def write_config(self, path):
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.get_config(), f, ensure_ascii=False, indent=2)

    def config_initial_dir(self):
        config_dir = process_config_dir(PROCESS_NAME, create=True)
        if config_dir:
            return config_dir
        input_csv = self.input_csv_edit.text().strip()
        if input_csv:
            folder = os.path.dirname(input_csv)
            if folder:
                return folder
        return ''

    def default_config_path(self, silent=False):
        path = process_config_path(PROCESS_NAME, DEFAULT_CONFIG_FILENAME, create_dir=not silent)
        if not path:
            if not silent:
                QMessageBox.warning(
                    self,
                    'データ整理３',
                    'QGISプロジェクトが未保存です。\n先にプロジェクトを保存してください。',
                )
            return ''
        return path

    def project_dir(self):
        return kdq_project_dir()

    def load_headers(self):
        path = self.input_csv_edit.text().strip()
        if not path or not os.path.exists(path):
            return
        try:
            headers, _rows = read_csv_table(path, self.encoding_combo.currentText(), self.delimiter(), max_rows=0)
        except Exception as exc:
            self.status_label.setText('CSVを読み込めませんでした: {}'.format(exc))
            return
        self.current_headers = headers
        self.status_label.setText('列を読み込みました: {} 列'.format(len(headers)))
        self.refresh_aggregate_column_combos()

    def select_key_columns(self):
        if not self.current_headers:
            self.load_headers()
        selected = split_columns(self.key_columns_edit.text())
        dialog = CsvColumnSelectionDialog(self.current_headers, selected, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        self.key_columns_edit.setText(', '.join(dialog.selected_columns()))

    def add_aggregate_row(self, operation='sum', source_field='', output_field=''):
        row = self.aggregation_table.rowCount()
        self.aggregation_table.insertRow(row)

        operation_combo = QComboBox()
        for value, label in AGGREGATE_OPERATIONS:
            operation_combo.addItem(label, value)
        index = operation_combo.findData(operation)
        if index >= 0:
            operation_combo.setCurrentIndex(index)
        operation_combo.currentIndexChanged.connect(lambda _index, row=row: self.update_default_output_field(row))
        self.aggregation_table.setCellWidget(row, 1, operation_combo)

        field_combo = QComboBox()
        field_combo.setEditable(True)
        field_combo.addItem('')
        field_combo.addItems(self.current_headers)
        field_combo.setCurrentText(source_field or '')
        field_combo.currentTextChanged.connect(lambda _text, row=row: self.update_default_output_field(row))
        self.aggregation_table.setCellWidget(row, 0, field_combo)

        self.aggregation_table.setItem(row, 2, QTableWidgetItem(output_field or ''))

        auto_button = QPushButton('自動設定')
        auto_button.clicked.connect(self.auto_set_output_field_for_sender)
        self.aggregation_table.setCellWidget(row, 3, auto_button)

    def delete_selected_aggregate_row(self):
        row = self.aggregation_table.currentRow()
        if row >= 0:
            self.aggregation_table.removeRow(row)

    def move_selected_aggregate_row_up(self):
        self.move_selected_aggregate_row(-1)

    def move_selected_aggregate_row_down(self):
        self.move_selected_aggregate_row(1)

    def move_selected_aggregate_row(self, offset):
        row = self.aggregation_table.currentRow()
        target_row = row + offset
        if row < 0 or target_row < 0 or target_row >= self.aggregation_table.rowCount():
            return
        rows = self.aggregate_configs(include_empty=True)
        rows[row], rows[target_row] = rows[target_row], rows[row]
        self.rebuild_aggregate_rows(rows, target_row)

    def rebuild_aggregate_rows(self, rows, selected_row=0):
        self.aggregation_table.setRowCount(0)
        for aggregate in rows:
            self.add_aggregate_row(
                aggregate.get('operation') or 'sum',
                aggregate.get('source_field') or '',
                aggregate.get('output_field') or '',
            )
        if rows:
            selected_row = max(0, min(selected_row, len(rows) - 1))
            self.aggregation_table.selectRow(selected_row)
            self.aggregation_table.setCurrentCell(selected_row, 2)

    def auto_set_output_field(self, row):
        if row < 0 or row >= self.aggregation_table.rowCount():
            return
        operation = self.operation_at(row)
        source_field = self.source_field_at(row)
        output_field = self.default_output_field(operation, source_field)
        self.aggregation_table.setItem(row, 2, QTableWidgetItem(output_field))

    def auto_set_output_field_for_sender(self):
        sender = self.sender()
        for row in range(self.aggregation_table.rowCount()):
            if self.aggregation_table.cellWidget(row, 3) == sender:
                self.auto_set_output_field(row)
                return

    def refresh_aggregate_column_combos(self):
        for row in range(self.aggregation_table.rowCount()):
            combo = self.aggregation_table.cellWidget(row, 0)
            if not combo:
                continue
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem('')
            combo.addItems(self.current_headers)
            combo.setCurrentText(current)
            combo.blockSignals(False)

    def update_default_output_field(self, row):
        item = self.aggregation_table.item(row, 2)
        if item and item.text().strip():
            return
        operation = self.operation_at(row)
        source_field = self.source_field_at(row)
        output_field = self.default_output_field(operation, source_field)
        self.aggregation_table.setItem(row, 2, QTableWidgetItem(output_field))

    def default_output_field(self, operation, source_field):
        source_field = (source_field or '').strip()
        if operation in ('newline_list', 'unique_newline_list') and source_field:
            return source_field
        suffixes = {
            'sum': '和',
            'count': 'カウント',
            'count_non_empty': 'カウント',
            'first': '先頭',
            'min': '最小',
            'max': '最大',
        }
        suffix = suffixes.get(operation, dict(AGGREGATE_OPERATIONS).get(operation, operation))
        if source_field:
            return '{}_{}'.format(source_field, suffix)
        return suffix

    def operation_at(self, row):
        combo = self.aggregation_table.cellWidget(row, 1)
        return combo.currentData() if combo else 'sum'

    def source_field_at(self, row):
        combo = self.aggregation_table.cellWidget(row, 0)
        return combo.currentText().strip() if combo else ''

    def aggregate_configs(self, include_empty=False):
        configs = []
        for row in range(self.aggregation_table.rowCount()):
            operation = self.operation_at(row)
            source_field = self.source_field_at(row)
            item = self.aggregation_table.item(row, 2)
            output_field = item.text().strip() if item else ''
            if include_empty:
                configs.append({
                    'operation': operation,
                    'source_field': source_field,
                    'output_field': output_field,
                })
                continue
            if not output_field:
                self.update_default_output_field(row)
                item = self.aggregation_table.item(row, 2)
                output_field = item.text().strip() if item else ''
            if operation != 'count' and not source_field:
                continue
            if output_field:
                configs.append({
                    'operation': operation,
                    'source_field': source_field,
                    'output_field': output_field,
                })
        return configs

    def update_preview(self):
        try:
            headers, rows = self.process_current(max_rows=500)
            self.set_preview_data(headers, rows[:100])
            self.status_label.setText('プレビュー: {} グループ'.format(len(rows)))
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理３', str(exc))

    def run_processing(self):
        output_csv = self.output_csv_edit.text().strip()
        if not output_csv:
            QMessageBox.warning(self, 'データ整理３', '出力CSVを指定してください。')
            return
        try:
            headers, rows = self.process_current()
            write_csv_table(output_csv, headers, rows, self.output_encoding_combo.currentText(), self.delimiter())
        except Exception as exc:
            QMessageBox.critical(self, 'データ整理３', str(exc))
            return
        self.status_label.setText('出力しました: {} グループ'.format(len(rows)))
        QMessageBox.information(self, 'データ整理３', '集計キーCSVを作成しました。\n\n{}'.format(output_csv))

    def process_current(self, max_rows=None):
        input_csv = self.input_csv_edit.text().strip()
        if not input_csv or not os.path.exists(input_csv):
            raise ValueError('入力CSVを指定してください。')
        key_columns = split_columns(self.key_columns_edit.text())
        if not key_columns:
            raise ValueError('キー列を1つ以上指定してください。')
        aggregate_configs = self.aggregate_configs()
        if not aggregate_configs:
            raise ValueError('集計内容を1つ以上指定してください。')

        headers, rows = read_csv_table(input_csv, self.encoding_combo.currentText(), self.delimiter(), max_rows=max_rows)
        missing = [column for column in key_columns if column not in headers]
        for config in aggregate_configs:
            source_field = config.get('source_field')
            if source_field and source_field not in headers:
                missing.append(source_field)
        if missing:
            raise ValueError('CSVに列が見つかりません: {}'.format(', '.join(dict.fromkeys(missing))))

        output_headers, output_rows = aggregate_rows(headers, rows, key_columns, aggregate_configs)
        return output_headers, output_rows

    def set_preview_data(self, headers, rows):
        self.preview_table.clear()
        self.preview_table.setColumnCount(len(headers))
        self.preview_table.setHorizontalHeaderLabels(headers)
        self.preview_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, header in enumerate(headers):
                value = row.get(header, '')
                self.preview_table.setItem(row_index, column_index, QTableWidgetItem(str(value)))


class DataOrganize2QueryTool:
    """Tool wrapper for the CSV aggregate-key dialog."""

    def __init__(self, iface):
        self.iface = iface
        self.dialog = None

    def run(self):
        self.dialog = DataOrganize2QueryDialog(self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        self.dialog.ask_load_default_config_on_startup()


def split_columns(text):
    return [part.strip() for part in (text or '').replace('、', ',').split(',') if part.strip()]


def read_csv_table(csv_path, encoding='UTF-8', delimiter=',', max_rows=None):
    with open(csv_path, 'r', encoding=encoding, newline='') as f:
        reader = csv.reader(f, delimiter=delimiter)
        headers = normalize_headers(next(reader, []))
        rows = []
        for index, row in enumerate(reader):
            if max_rows is not None and index >= max_rows:
                break
            row = list(row[:len(headers)])
            if len(row) < len(headers):
                row.extend([''] * (len(headers) - len(row)))
            rows.append(dict(zip(headers, row)))
        return headers, rows


def write_csv_table(csv_path, headers, rows, encoding='UTF-8', delimiter=','):
    folder = os.path.dirname(csv_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(csv_path, 'w', encoding=encoding, newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def aggregate_rows(headers, rows, key_columns, aggregate_configs):
    groups = {}
    order = []
    for row in rows:
        key = tuple(row.get(column, '') for column in key_columns)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    output_headers = list(key_columns)
    for config in aggregate_configs:
        output_field = config['output_field']
        if output_field not in output_headers:
            output_headers.append(output_field)

    output_rows = []
    for key in order:
        group_rows = groups[key]
        output_row = {column: value for column, value in zip(key_columns, key)}
        for config in aggregate_configs:
            output_row[config['output_field']] = aggregate_value(group_rows, config)
        output_rows.append(output_row)

    return output_headers, output_rows


def aggregate_value(rows, config):
    operation = config.get('operation')
    source_field = config.get('source_field') or ''

    if operation == 'count':
        return len(rows)

    values = [row.get(source_field, '') for row in rows]
    texts = ['' if value is None else str(value) for value in values]
    non_empty_texts = [text for text in texts if text.strip()]

    if operation == 'count_non_empty':
        return len(non_empty_texts)
    if operation == 'sum':
        total = sum(parse_number(text) for text in texts)
        return format_number(total)
    if operation == 'newline_list':
        return '\n'.join(non_empty_texts)
    if operation == 'unique_newline_list':
        unique = []
        seen = set()
        for text in non_empty_texts:
            if text in seen:
                continue
            seen.add(text)
            unique.append(text)
        return '\n'.join(unique)
    if operation == 'first':
        return non_empty_texts[0] if non_empty_texts else ''
    if operation in ('min', 'max'):
        numbers = [parse_number(text) for text in non_empty_texts if is_number(text)]
        if numbers:
            value = min(numbers) if operation == 'min' else max(numbers)
            return format_number(value)
        if not non_empty_texts:
            return ''
        return min(non_empty_texts) if operation == 'min' else max(non_empty_texts)
    return ''


def is_number(value):
    try:
        parse_number(value)
        return True
    except ValueError:
        return False


def parse_number(value):
    text = str(value or '').strip().replace(',', '')
    if not text:
        return 0.0
    return float(text)


def format_number(value):
    if int(value) == value:
        return str(int(value))
    return str(value)
