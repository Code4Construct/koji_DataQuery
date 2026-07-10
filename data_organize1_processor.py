# -*- coding: utf-8 -*-

import csv
import json
import os
import re
import unicodedata
from datetime import date


def normalize_headers(headers):
    result = []
    empty_count = 1
    seen = {}
    for header in headers:
        name = (header or '').strip()
        if not name:
            name = '空列{}'.format(empty_count)
            empty_count += 1
        if name in seen:
            seen[name] += 1
            name = '{}_{}'.format(name, seen[name])
        else:
            seen[name] = 1
        result.append(name)
    return result


def read_csv_rows(csv_path, encoding='UTF-8', delimiter=',', max_rows=None):
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


def write_csv_rows(csv_path, headers, rows, encoding='UTF-8', delimiter=','):
    folder = os.path.dirname(csv_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(csv_path, 'w', encoding=encoding, newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers, delimiter=delimiter, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def parse_string_concat_step(source_text, summary_text):
    source_fields = [field.strip() for field in source_text.replace('、', ',').split(',') if field.strip()]
    output_field = ''
    if '->' in summary_text:
        output_field = summary_text.split('->', 1)[1].strip()
    if not output_field and source_fields:
        output_field = ''.join(source_fields)
    return {
        'type': 'string_concat',
        'source_fields': source_fields,
        'output_field': output_field,
        'separator': '',
    }


def parse_column_rename_step(source_text, summary_text):
    source_fields = [field.strip() for field in source_text.replace('、', ',').split(',') if field.strip()]
    rename_targets = []
    if '->' in summary_text:
        rename_targets = [
            field.strip()
            for field in summary_text.split('->', 1)[1].replace('、', ',').split(',')
            if field.strip()
        ]
    return {
        'type': 'column_rename',
        'source_fields': source_fields,
        'target_fields': rename_targets,
    }


def parse_column_delete_step(source_text):
    return {
        'type': 'column_delete',
        'source_fields': [
            field.strip()
            for field in source_text.replace('、', ',').split(',')
            if field.strip()
        ],
    }


def parse_column_reorder_step(summary_text):
    order_map = {}
    for pair in summary_text.replace('、', ',').split(','):
        pair = pair.strip()
        if not pair or ':' not in pair:
            continue
        field, order = pair.rsplit(':', 1)
        field = field.strip()
        try:
            order_map[field] = int(order.strip())
        except ValueError:
            continue
    return {
        'type': 'column_reorder',
        'order_map': order_map,
    }


def parse_text_normalize_step(source_text, summary_text):
    operations = []
    normalized_summary = (summary_text or '').replace('、', ',')
    for label, operation in (
        ('半角化', 'to_halfwidth'),
        ('全角化', 'to_fullwidth'),
        ('空白削除', 'remove_spaces'),
    ):
        if label in normalized_summary:
            operations.append(operation)
    return {
        'type': 'text_normalize',
        'source_fields': [
            field.strip()
            for field in source_text.replace('、', ',').split(',')
            if field.strip()
        ],
        'operations': operations,
    }


def parse_date_normalize_step(source_text, summary_text):
    output_format = 'yyyy-mm-dd'
    for label, value in (
        ('YYYY-MM-DD', 'yyyy-mm-dd'),
        ('YYYY/MM/DD', 'yyyy/mm/dd'),
        ('YYYY年M月D日', 'yyyy年m月d日'),
        ('YYYYMMDD', 'yyyymmdd'),
    ):
        if label in (summary_text or ''):
            output_format = value
            break
    return {
        'type': 'date_normalize',
        'source_fields': [
            field.strip()
            for field in source_text.replace('、', ',').split(',')
            if field.strip()
        ],
        'output_format': output_format,
    }


def parse_chiban_organize_step(source_text, summary_text):
    source_fields = [
        field.strip()
        for field in source_text.replace('、', ',').split(',')
        if field.strip()
    ]
    return {
        'type': 'chiban_organize',
        'source_field': source_fields[0] if source_fields else '地番',
        'output_field': '地番整理',
        'description_field': '地番説明',
    }


def parse_chiban_prefix_step(source_text, summary_text):
    source_fields = [
        field.strip()
        for field in (source_text or '').replace('\u3001', ',').split(',')
        if field.strip()
    ]
    config = {}
    summary = summary_text or ''
    if summary.strip().startswith('{'):
        try:
            config = json.loads(summary)
        except Exception:
            config = {}
    return {
        'type': 'chiban_prefix',
        'source_fields': source_fields,
        'operation': config.get('operation') or 'remove',
        'prefix': config.get('prefix') or '大阪府大阪市',
        'output_field': config.get('output_field') or '',
    }


def parse_row_filter_step(source_text, summary_text):
    fields = [
        field.strip()
        for field in source_text.replace('、', ',').split(',')
        if field.strip()
    ]
    condition = 'empty'
    value = ''
    value2 = ''
    match_mode = 'any'
    filter_kind = 'text'
    action = 'exclude'
    summary = summary_text or ''
    if '残す' in summary:
        action = 'include'
    elif '除外' in summary:
        action = 'exclude'
    if 'すべての列' in summary:
        match_mode = 'all'
    if '数量制限' in summary:
        filter_kind = 'number'
    elif '日付期間' in summary:
        filter_kind = 'date'
    for label, parsed_condition in (
        ('期間内', 'between'),
        ('範囲内', 'between'),
        ('以上', 'gte'),
        ('以下', 'lte'),
        ('より大きい', 'gt'),
        ('より小さい', 'lt'),
        ('以前', 'lte'),
        ('以後', 'gte'),
        ('同じ日', 'equals'),
        ('含まない', 'not_contains'),
        ('空白でない', 'not_empty'),
        ('空白', 'empty'),
        ('含む', 'contains'),
        ('完全一致', 'equals'),
        ('一致', 'equals'),
        ('等しい', 'equals'),
        ('等しくない', 'not_equals'),
        ('正規表現', 'regex'),
    ):
        if label in summary:
            condition = parsed_condition
            break
    if ':' in summary:
        value = summary.rsplit(':', 1)[1].strip()
        if '～' in value:
            value, value2 = [part.strip() for part in value.split('～', 1)]
    rules = []
    if summary.strip().startswith('{'):
        try:
            data = json.loads(summary)
            rules = data.get('rules') or []
            action = data.get('action', action)
            match_mode = data.get('match_mode', match_mode)
            fields = [rule.get('field', '') for rule in rules if rule.get('field')]
        except Exception:
            rules = []
    return {
        'type': 'row_filter',
        'source_fields': fields,
        'filter_kind': filter_kind,
        'condition': condition,
        'value': value,
        'value2': value2,
        'match_mode': match_mode,
        'action': action,
        'rules': rules,
    }


def apply_processing_steps(headers, rows, steps):
    output_headers = list(headers)
    output_rows = [dict(row) for row in rows]

    for step in steps:
        if step.get('type') == 'string_concat':
            source_fields = step.get('source_fields') or []
            output_field = step.get('output_field') or ''.join(source_fields)
            separator = step.get('separator', '')
            if not source_fields or not output_field:
                continue
            if output_field not in output_headers:
                output_headers.append(output_field)
            for row in output_rows:
                row[output_field] = separator.join(
                    '' if row.get(field, '') is None else str(row.get(field, ''))
                    for field in source_fields
                )
            continue

        if step.get('type') == 'custom_python':
            output_headers, output_rows = _apply_custom_function_step(output_headers, output_rows, step)
            continue

        if step.get('type') == 'chiban_organize':
            source_field = step.get('source_field') or '地番'
            output_field = step.get('output_field') or '地番整理'
            description_field = step.get('description_field') or '地番説明'
            if not source_field:
                continue
            for field in (output_field, description_field):
                if field and field not in output_headers:
                    output_headers.append(field)
            for row in output_rows:
                organized, description = _organize_chiban_value(row.get(source_field, ''))
                row[output_field] = organized
                row[description_field] = description
            continue

        if step.get('type') == 'chiban_prefix':
            source_fields = step.get('source_fields') or []
            operation = step.get('operation') or 'remove'
            prefix = step.get('prefix') or ''
            output_field = step.get('output_field') or ''
            if not source_fields or not prefix:
                continue
            if output_field and output_field not in output_headers:
                output_headers.append(output_field)
            for row in output_rows:
                for field in source_fields:
                    if field not in row:
                        continue
                    target_field = output_field or field
                    row[target_field] = _apply_chiban_prefix(row.get(field, ''), operation, prefix)
            continue

        if step.get('type') == 'text_normalize':
            source_fields = step.get('source_fields') or []
            operations = step.get('operations') or []
            if not source_fields or not operations:
                continue
            for row in output_rows:
                for field in source_fields:
                    if field in row:
                        row[field] = _normalize_text_value(row.get(field, ''), operations)
            continue

        if step.get('type') == 'date_normalize':
            source_fields = step.get('source_fields') or []
            output_format = step.get('output_format') or 'yyyy-mm-dd'
            if not source_fields:
                continue
            for row in output_rows:
                for field in source_fields:
                    if field in row:
                        row[field] = _normalize_date_value(row.get(field, ''), output_format)
            continue

        if step.get('type') == 'row_filter':
            source_fields = step.get('source_fields') or []
            if not source_fields:
                continue
            if step.get('action') == 'include':
                output_rows = [
                    row for row in output_rows
                    if _row_matches_filter(row, step)
                ]
            else:
                output_rows = [
                    row for row in output_rows
                    if not _row_matches_filter(row, step)
                ]
            continue

        if step.get('type') != 'column_rename':
            if step.get('type') == 'column_delete':
                delete_fields = set(step.get('source_fields') or [])
                if not delete_fields:
                    continue
                output_headers = [header for header in output_headers if header not in delete_fields]
                for row in output_rows:
                    for field in delete_fields:
                        row.pop(field, None)
            elif step.get('type') == 'column_reorder':
                order_map = step.get('order_map') or {}
                output_headers = sorted(
                    output_headers,
                    key=lambda header: (
                        order_map.get(header, len(output_headers) + 1),
                        output_headers.index(header),
                    ),
                )
            continue

        source_fields = step.get('source_fields') or []
        target_fields = step.get('target_fields') or []
        rename_map = {
            source: target
            for source, target in zip(source_fields, target_fields)
            if source and target and source != target
        }
        if not rename_map:
            continue
        output_headers = [rename_map.get(header, header) for header in output_headers]
        for row in output_rows:
            for source, target in rename_map.items():
                if source in row:
                    row[target] = row.pop(source)

    return output_headers, output_rows


def _normalize_text_value(value, operations):
    text = '' if value is None else str(value)
    for operation in operations:
        if operation == 'to_halfwidth':
            text = unicodedata.normalize('NFKC', text)
        elif operation == 'to_fullwidth':
            text = _to_fullwidth(text)
        elif operation == 'remove_spaces':
            text = re.sub(r'[\s\u3000]+', '', text)
    return text


def _to_fullwidth(text):
    result = []
    for char in text:
        code = ord(char)
        if char == ' ':
            result.append('\u3000')
        elif 0x21 <= code <= 0x7E:
            result.append(chr(code + 0xFEE0))
        else:
            result.append(char)
    return ''.join(result)


def _organize_chiban_value(value):
    text = '' if value is None else str(value)
    text = _unwrap_spreadsheet_formula_text(text)
    normalized = _normalize_chiban_text(text)
    normalized = re.sub(r'\s*番地?\s*', '-', normalized)
    normalized = re.sub(r'\s*号\s*', '', normalized)
    normalized = re.sub(r'[‐‑‒–—―ー−ｰ]', '-', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    normalized = re.sub(r'\s*-\s*', '-', normalized)
    normalized = re.sub(r'の\s*(内|他|先|うち)$', r'\1', normalized)
    normalized = re.sub(r'うち$', '内', normalized)

    descriptions = []
    if re.search(r'(^|[\s,、/・()（）])内($|[\s,、/・()（）])', normalized) or normalized.endswith('内'):
        descriptions.append('内')
    if re.search(r'(^|[\s,、/・()（）])他($|[\s,、/・()（）])', normalized) or normalized.endswith('他'):
        descriptions.append('他')
    if re.search(r'(^|[\s,、/・()（）-])先($|[\s,、/・()（）])', normalized) or normalized.endswith('先'):
        descriptions.append('先')

    organized = re.sub(r'[()（）]?\s*[内他先]\s*[()（）]?', '', normalized)
    organized = re.sub(r'\s+', ' ', organized).strip()
    organized = re.sub(r'\s*-\s*', '-', organized)
    organized = re.sub(r'(?<=\d)-+$', '', organized)
    return organized, '、'.join(descriptions)


def _normalize_chiban_text(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def _apply_chiban_prefix(value, operation, prefix):
    text = unicodedata.normalize('NFKC', '' if value is None else str(value)).strip()
    prefix = unicodedata.normalize('NFKC', prefix or '').strip()
    if not text or not prefix:
        return text
    if operation == 'add':
        return text if text.startswith(prefix) else prefix + text
    if text.startswith(prefix):
        return text[len(prefix):].lstrip()
    return text


def _unwrap_spreadsheet_formula_text(text):
    text = (text or '').strip()
    if len(text) >= 3 and text[0] == '=' and text[1] in ('"', "'") and text[-1] == text[1]:
        return text[2:-1]
    return text


def _normalize_date_value(value, output_format):
    text = '' if value is None else str(value).strip()
    if not text:
        return ''
    parsed = _parse_date_value(text)
    if parsed is None:
        return text
    if output_format == 'yyyy/mm/dd':
        return '{:04d}/{:02d}/{:02d}'.format(parsed.year, parsed.month, parsed.day)
    if output_format == 'yyyy年m月d日':
        return '{}年{}月{}日'.format(parsed.year, parsed.month, parsed.day)
    if output_format == 'yyyymmdd':
        return '{:04d}{:02d}{:02d}'.format(parsed.year, parsed.month, parsed.day)
    return '{:04d}-{:02d}-{:02d}'.format(parsed.year, parsed.month, parsed.day)


def _parse_date_value(text):
    normalized = unicodedata.normalize('NFKC', text).strip()
    normalized = normalized.replace('年', '/').replace('月', '/').replace('日', '')
    normalized = normalized.replace('.', '/').replace('-', '/')
    normalized = re.sub(r'\s+', '', normalized)

    match = re.match(r'^(令和|平成|昭和|大正|明治|R|H|S|T|M)(元|\d{1,2})[/\.年](\d{1,2})[/\.月](\d{1,2})日?$', normalized, re.IGNORECASE)
    if match:
        era, year_text, month, day = match.groups()
        year = 1 if year_text == '元' else int(year_text)
        western_year = _era_to_year(era, year)
        return _safe_date(western_year, int(month), int(day))

    match = re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})$', normalized)
    if match:
        year, month, day = [int(part) for part in match.groups()]
        return _safe_date(year, month, day)

    match = re.match(r'^(\d{8})$', normalized)
    if match:
        value = match.group(1)
        return _safe_date(int(value[0:4]), int(value[4:6]), int(value[6:8]))

    return None


def _era_to_year(era, year):
    era = era.upper()
    starts = {
        '令和': 2018,
        'R': 2018,
        '平成': 1988,
        'H': 1988,
        '昭和': 1925,
        'S': 1925,
        '大正': 1911,
        'T': 1911,
        '明治': 1867,
        'M': 1867,
    }
    return starts.get(era, 0) + year


def _safe_date(year, month, day):
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _row_matches_filter(row, step):
    rules = step.get('rules') or []
    if rules:
        results = [
            _value_matches_filter(
                row.get(rule.get('field', ''), ''),
                rule.get('condition') or 'empty',
                rule.get('value') or '',
                rule.get('filter_kind') or 'text',
                rule.get('value2') or '',
            )
            for rule in rules
            if rule.get('field')
        ]
        if step.get('match_mode') == 'all':
            return all(results)
        return any(results)

    fields = step.get('source_fields') or []
    condition = step.get('condition') or 'empty'
    value = step.get('value') or ''
    value2 = step.get('value2') or ''
    filter_kind = step.get('filter_kind') or 'text'
    match_mode = step.get('match_mode') or 'any'
    results = [
        _value_matches_filter(row.get(field, ''), condition, value, filter_kind, value2)
        for field in fields
    ]
    if match_mode == 'all':
        return all(results)
    return any(results)


def _value_matches_filter(value, condition, expected, filter_kind='text', expected2=''):
    text = '' if value is None else str(value)
    if condition == 'not_empty':
        return text.strip() != ''
    if condition == 'empty':
        return text.strip() == ''

    if filter_kind == 'number':
        number = _parse_number(text)
        expected_number = _parse_number(expected)
        expected_number2 = _parse_number(expected2)
        if number is None or expected_number is None:
            return False
        if condition == 'gt':
            return number > expected_number
        if condition == 'gte':
            return number >= expected_number
        if condition == 'lt':
            return number < expected_number
        if condition == 'lte':
            return number <= expected_number
        if condition == 'not_equals':
            return number != expected_number
        if condition == 'between':
            if expected_number2 is None:
                return False
            low = min(expected_number, expected_number2)
            high = max(expected_number, expected_number2)
            return low <= number <= high
        return number == expected_number

    if filter_kind == 'date':
        parsed_date = _parse_date_value(text)
        expected_date = _parse_date_value(expected)
        expected_date2 = _parse_date_value(expected2)
        if parsed_date is None or expected_date is None:
            return False
        if condition == 'gte':
            return parsed_date >= expected_date
        if condition == 'lte':
            return parsed_date <= expected_date
        if condition == 'between':
            if expected_date2 is None:
                return False
            low = min(expected_date, expected_date2)
            high = max(expected_date, expected_date2)
            return low <= parsed_date <= high
        if condition == 'not_equals':
            return parsed_date != expected_date
        return parsed_date == expected_date

    normalized_text = _normalize_match_text(text)
    expected_values = _parse_expected_values(expected)
    normalized_expected_values = [_normalize_match_text(item) for item in expected_values]
    if condition == 'not_contains':
        return all(item not in normalized_text for item in normalized_expected_values)
    if condition == 'contains':
        return any(item in normalized_text for item in normalized_expected_values)
    if condition == 'not_equals':
        return all(normalized_text != item for item in normalized_expected_values)
    if condition == 'equals':
        return any(normalized_text == item for item in normalized_expected_values)
    if condition == 'regex':
        try:
            return re.search(expected, text) is not None
        except re.error:
            return False
    return False


def _normalize_match_text(text):
    return re.sub(r'[\s\u3000]+', '', unicodedata.normalize('NFKC', str(text)))


def _parse_expected_values(expected):
    values = [
        value.strip()
        for value in str(expected).replace('、', ',').split(',')
        if value.strip()
    ]
    return values or [str(expected)]


def _parse_number(text):
    normalized = unicodedata.normalize('NFKC', str(text)).strip()
    normalized = normalized.replace(',', '')
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _apply_custom_function_step(headers, rows, step):
    input_fields = step.get('input_fields') or []
    output_field = step.get('output_field') or ''
    function_id = _custom_function_id(step)
    if function_id not in ('chiban_organize', 'date_normalize'):
        raise ValueError('Unsupported custom function: {}'.format(function_id or 'unknown'))

    output_headers = list(headers)
    output_rows = [dict(row) for row in rows]
    if function_id == 'chiban_organize':
        for field in ('地番整理', '地番説明'):
            if field not in output_headers:
                output_headers.append(field)
    elif output_field and output_field not in output_headers:
        output_headers.append(output_field)

    for row in output_rows:
        values = {field: row.get(field, '') for field in input_fields}
        for index, field in enumerate(input_fields):
            values[chr(ord('A') + index)] = row.get(field, '')
        result = _run_custom_function(function_id, values)

        if isinstance(result, dict):
            for field, value in result.items():
                if field not in output_headers:
                    output_headers.append(field)
                row[field] = '' if value is None else value
        elif output_field:
            row[output_field] = '' if result is None else result

    return output_headers, output_rows


def _custom_function_id(step):
    function_id = step.get('function_id') or step.get('standard_function') or ''
    if function_id:
        return function_id
    path = (step.get('function_file_path') or '').replace('\\', '/').lower()
    if path.endswith('chiban_organize.json'):
        return 'chiban_organize'
    if path.endswith('date_normalize.json'):
        return 'date_normalize'
    code = step.get('code') or ''
    if '_organize_chiban_value' in code or "'地番整理'" in code:
        return 'chiban_organize'
    if 'base_years' in code and 'R' in code and 'H' in code:
        return 'date_normalize'
    return ''


def _run_custom_function(function_id, values):
    if function_id == 'chiban_organize':
        organized, description = _organize_chiban_value(values.get('A', ''))
        return {
            '地番整理': organized,
            '地番説明': description,
        }
    if function_id == 'date_normalize':
        return _normalize_date_value(values.get('A', ''), 'yyyy-mm-dd')
    raise ValueError('Unsupported custom function: {}'.format(function_id or 'unknown'))


def apply_string_concat_steps(headers, rows, steps):
    return apply_processing_steps(
        headers,
        rows,
        [step for step in steps if step.get('type') == 'string_concat'],
    )


def process_csv(input_csv, output_csv, steps, input_encoding='UTF-8', output_encoding='UTF-8', delimiter=','):
    headers, rows = read_csv_rows(input_csv, input_encoding, delimiter)
    output_headers, output_rows = apply_processing_steps(headers, rows, steps)
    write_csv_rows(output_csv, output_headers, output_rows, output_encoding, delimiter)
    return output_headers, len(output_rows)
