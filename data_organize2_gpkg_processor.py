# -*- coding: utf-8 -*-

import os

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsProject,
)

from .data_organize1_processor import apply_processing_steps


_GEOMETRY_ROW_ID = '__kojiGIS_geometry_row_id__'


def _layer_uri(gpkg_path, layer_name=''):
    layer_name = (layer_name or '').strip()
    if layer_name:
        return '{}|layername={}'.format(gpkg_path, layer_name)
    return gpkg_path


def open_gpkg_layer(gpkg_path, layer_name=''):
    layer = QgsVectorLayer(_layer_uri(gpkg_path, layer_name), layer_name or os.path.basename(gpkg_path), 'ogr')
    if not layer.isValid():
        raise ValueError('GeoPackageを読み込めませんでした: {}'.format(gpkg_path))
    return layer


def list_gpkg_layer_names(gpkg_path):
    return [info['name'] for info in list_gpkg_layer_infos(gpkg_path)]


def list_gpkg_layer_infos(gpkg_path):
    layer = QgsVectorLayer(gpkg_path, os.path.basename(gpkg_path), 'ogr')
    if not layer.isValid():
        raise ValueError('GeoPackageを読み込めませんでした: {}'.format(gpkg_path))

    names = []
    for sublayer in layer.dataProvider().subLayers():
        parts = sublayer.split('!!::!!')
        name = ''
        if len(parts) >= 2:
            name = parts[1].strip()
        elif sublayer:
            name = sublayer.strip()
        if name.startswith('layername='):
            name = name.split('=', 1)[1].strip()
        if name and name not in names:
            names.append(name)

    if not names:
        names.append(layer.name())

    infos = []
    for name in names:
        try:
            sublayer = open_gpkg_layer(gpkg_path, name)
            geometry_type = QgsWkbTypes.displayString(sublayer.wkbType()) or 'Unknown'
        except Exception:
            geometry_type = 'Unknown'
        infos.append({
            'name': name,
            'geometry_type': geometry_type,
        })
    return infos


def read_gpkg_rows(gpkg_path, layer_name='', max_rows=None):
    layer = open_gpkg_layer(gpkg_path, layer_name)
    headers = [field.name() for field in layer.fields()]
    rows = []
    for index, feature in enumerate(layer.getFeatures()):
        if max_rows is not None and index >= max_rows:
            break
        rows.append({
            header: _display_value(feature[header])
            for header in headers
        })
    return headers, rows


def process_gpkg(input_gpkg, output_gpkg, steps, layer_name='', output_layer_name=''):
    source_layer = open_gpkg_layer(input_gpkg, layer_name)
    headers = [field.name() for field in source_layer.fields()]
    rows = []
    geometries_by_row_id = {}

    for row_id, feature in enumerate(source_layer.getFeatures()):
        row = {
            header: feature[header]
            for header in headers
        }
        row[_GEOMETRY_ROW_ID] = row_id
        rows.append(row)
        geometry = feature.geometry()
        geometries_by_row_id[row_id] = QgsGeometry(geometry) if geometry and not geometry.isEmpty() else QgsGeometry()

    output_headers, output_rows = apply_processing_steps(headers, rows, steps)
    output_layer = _build_output_layer(source_layer, output_headers, output_rows, geometries_by_row_id, steps)
    _write_gpkg(output_layer, output_gpkg, output_layer_name or source_layer.name())
    return output_headers, len(output_rows)


def _display_value(value):
    if value is None:
        return ''
    return str(value)


def _build_output_layer(source_layer, output_headers, output_rows, geometries_by_row_id, steps):
    geometry_name = QgsWkbTypes.displayString(source_layer.wkbType())
    if source_layer.wkbType() == QgsWkbTypes.NoGeometry:
        geometry_name = 'None'

    crs_authid = source_layer.crs().authid()
    uri = geometry_name
    if crs_authid:
        uri = '{}?crs={}'.format(uri, crs_authid)

    output_layer = QgsVectorLayer(uri, source_layer.name(), 'memory')
    provider = output_layer.dataProvider()

    fields = _output_fields(source_layer, output_headers, steps)
    provider.addAttributes(fields)
    output_layer.updateFields()

    output_fields = output_layer.fields()
    features = []
    for index, row in enumerate(output_rows):
        row_id = row.get(_GEOMETRY_ROW_ID)
        geometry = geometries_by_row_id.get(row_id, QgsGeometry())
        feature = QgsFeature(output_fields)
        if geometry and not geometry.isEmpty():
            feature.setGeometry(geometry)
        feature.setAttributes([row.get(header, '') for header in output_headers])
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
    return output_layer


def _output_fields(source_layer, output_headers, steps):
    source_fields = {field.name(): field for field in source_layer.fields()}
    renamed_from = _renamed_target_sources(steps)
    string_fields = _string_output_fields([field.name() for field in source_layer.fields()], steps)
    result = []
    used = set()

    for header in output_headers:
        source_name = renamed_from.get(header, header)
        source_field = source_fields.get(source_name)
        if source_field and header not in string_fields:
            field = QgsField(source_field)
            field.setName(header)
        else:
            field = QgsField(header, QVariant.String)

        name = field.name()
        if name in used:
            suffix = 2
            while '{}_{}'.format(name, suffix) in used:
                suffix += 1
            field.setName('{}_{}'.format(name, suffix))
        used.add(field.name())
        result.append(field)

    return result


def _renamed_target_sources(steps):
    renamed = {}
    for step in steps:
        if step.get('type') != 'column_rename':
            continue
        for source, target in zip(step.get('source_fields') or [], step.get('target_fields') or []):
            if source and target:
                renamed[target] = source
    return renamed


def _string_output_fields(headers, steps):
    current_headers = list(headers)
    string_fields = set()

    for step in steps:
        step_type = step.get('type')

        if step_type == 'string_concat':
            output_field = step.get('output_field') or ''.join(step.get('source_fields') or [])
            if output_field:
                if output_field not in current_headers:
                    current_headers.append(output_field)
                string_fields.add(output_field)
            continue

        if step_type == 'custom_python':
            output_field = step.get('output_field') or ''
            if output_field:
                if step.get('output_mode') == 'new' and output_field not in current_headers:
                    current_headers.append(output_field)
                string_fields.add(output_field)
            continue

        if step_type == 'chiban_organize':
            for field in (
                step.get('output_field') or '地番整理',
                step.get('description_field') or '地番説明',
            ):
                if field:
                    if field not in current_headers:
                        current_headers.append(field)
                    string_fields.add(field)
            continue

        if step_type in ('text_normalize', 'date_normalize'):
            for field in step.get('source_fields') or []:
                if field:
                    string_fields.add(field)
            continue

        if step_type == 'column_delete':
            delete_fields = set(step.get('source_fields') or [])
            if delete_fields:
                current_headers = [header for header in current_headers if header not in delete_fields]
                string_fields.difference_update(delete_fields)
            continue

        if step_type == 'column_rename':
            rename_map = {
                source: target
                for source, target in zip(step.get('source_fields') or [], step.get('target_fields') or [])
                if source and target and source != target
            }
            if rename_map:
                current_headers = [rename_map.get(header, header) for header in current_headers]
                string_fields = {rename_map.get(field, field) for field in string_fields}

    return string_fields


def _write_gpkg(layer, output_gpkg, layer_name):
    folder = os.path.dirname(output_gpkg)
    if folder:
        os.makedirs(folder, exist_ok=True)

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = 'GPKG'
    options.layerName = layer_name
    options.fileEncoding = 'UTF-8'
    options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer,
        output_gpkg,
        QgsProject.instance().transformContext(),
        options,
    )
    error_code = result[0]
    if error_code != QgsVectorFileWriter.NoError:
        message = result[1] if len(result) > 1 else 'GeoPackageの保存に失敗しました。'
        raise RuntimeError(message)
