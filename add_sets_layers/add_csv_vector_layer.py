# -*- coding: utf-8 -*-
import os

from qgis.PyQt.QtWidgets import QInputDialog, QFileDialog
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QSizeF
from qgis.core import (
    QgsVectorLayer,
    QgsProject,
    QgsMarkerSymbol,
    QgsSingleSymbolRenderer,
    QgsPalLayerSettings,
    QgsTextFormat,
    QgsTextBackgroundSettings,
    QgsUnitTypes,
    QgsVectorLayerSimpleLabeling,
    QgsRuleBasedLabeling
)

# ==========================================
# ここを編集してください
# 「選んだ区の外」で除外したい施設名称キーワード
# この文字を含む施設は、選択した区の外では表示しません
# 選択した区の中では表示します
# ==========================================
EXCLUDED_OUTSIDE_WARD_NAME_KEYWORDS = [
    "消防署"
]

WARD_NAMES = [
    "都島区", "福島区", "此花区", "西区", "港区", "大正区", "天王寺区", "浪速区",
    "西淀川区", "東淀川区", "東成区", "生野区", "旭区", "城東区", "阿倍野区", "住吉区",
    "東住吉区", "西成区", "淀川区", "鶴見区", "住之江区", "平野区", "北区", "中央区"
]


def get_or_create_group(root, group_name):
    group = root.findGroup(group_name)
    if group is None:
        group = root.addGroup(group_name)
    return group


def rgba_string_to_qcolor(color_rgba, background_alpha=51):
    """
    '255,0,0,255' のような文字列を QColor に変換
    background_alpha=51 は約20%不透明
    """
    parts = [p.strip() for p in color_rgba.split(",")]
    r = int(parts[0]) if len(parts) > 0 else 0
    g = int(parts[1]) if len(parts) > 1 else 0
    b = int(parts[2]) if len(parts) > 2 else 0
    a = int(parts[3]) if len(parts) > 3 else 255

    if background_alpha is None:
        return QColor(r, g, b, a)
    return QColor(r, g, b, background_alpha)


def apply_symbol(layer, shape, color_rgba, size_mm):
    symbol = QgsMarkerSymbol.createSimple({
        'name': shape,
        'color': color_rgba,
        'outline_color': '0,0,0,255',
        'outline_width': '0.15',
        'outline_width_unit': 'MM',
        'size': str(size_mm),
        'size_unit': 'MM'
    })
    renderer = QgsSingleSymbolRenderer(symbol)
    layer.setRenderer(renderer)


def make_text_format_with_background(color_rgba):
    text_format = QgsTextFormat()
    text_format.setSize(3)
    text_format.setSizeUnit(QgsUnitTypes.RenderMillimeters)

    bg = QgsTextBackgroundSettings()
    bg.setEnabled(True)
    bg.setType(QgsTextBackgroundSettings.ShapeRectangle)
    bg.setFillColor(rgba_string_to_qcolor(color_rgba, background_alpha=51))
    bg.setStrokeColor(QColor(0, 0, 0, 0))

    bg.setSizeType(QgsTextBackgroundSettings.SizeBuffer)
    bg.setSize(QSizeF(0.8, 0.5))
    bg.setSizeUnit(QgsUnitTypes.RenderMillimeters)

    bg.setRadii(QSizeF(0.4, 0.4))
    bg.setRadiiUnit(QgsUnitTypes.RenderMillimeters)

    text_format.setBackground(bg)
    return text_format


def apply_simple_label(layer, label_expr, color_rgba):
    settings = QgsPalLayerSettings()
    settings.enabled = True
    settings.isExpression = True
    settings.fieldName = label_expr

    text_format = make_text_format_with_background(color_rgba)
    settings.setFormat(text_format)

    labeling = QgsVectorLayerSimpleLabeling(settings)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)


def apply_rule_based_label(layer, label_expr, color_rgba, description="rule label"):
    settings = QgsPalLayerSettings()
    settings.enabled = True
    settings.isExpression = True
    settings.fieldName = label_expr

    text_format = make_text_format_with_background(color_rgba)
    settings.setFormat(text_format)

    root_rule = QgsRuleBasedLabeling.Rule(QgsPalLayerSettings())
    rule = QgsRuleBasedLabeling.Rule(settings)
    rule.setDescription(description)
    root_rule.appendChild(rule)

    labeling = QgsRuleBasedLabeling(root_rule)
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(True)


def build_name_not_contains_all_expression(field_name, keywords):
    valid_keywords = [k for k in keywords if str(k).strip()]
    if not valid_keywords:
        return "TRUE"

    parts = []
    for keyword in valid_keywords:
        safe_kw = keyword.replace("'", "''")
        parts.append(f"\"{field_name}\" NOT LIKE '%{safe_kw}%'")
    return "(" + " AND ".join(parts) + ")"


def build_field_is_empty_expression(field_name):
    """
    指定フィールドが NULL または空文字または空白のみ
    のとき TRUE になる式を返す
    """
    return f'( "{field_name}" IS NULL OR trim("{field_name}") = \'\' )'


def build_total_floor_area_expression(area_filter):
    if not area_filter:
        return ""

    min_area = area_filter.get('min')
    max_area = area_filter.get('max')
    conditions = [
        '"延床面積_平方メートル" IS NOT NULL',
        'trim("延床面積_平方メートル") != \'\'',
    ]
    if min_area is not None:
        conditions.append(f'to_real("延床面積_平方メートル") >= {int(min_area)}')
    if max_area is not None:
        conditions.append(f'to_real("延床面積_平方メートル") < {int(max_area)}')

    if len(conditions) == 2:
        return ""
    return " AND ".join(f"({condition})" for condition in conditions)


def build_total_floor_area_group_suffix(area_filter):
    if not area_filter:
        return ""

    min_area = area_filter.get('min')
    max_area = area_filter.get('max')
    if min_area is not None and max_area is not None:
        return f"_{int(min_area)}㎡ｰ{int(max_area)}㎡"
    if min_area is not None:
        return f"_{int(min_area)}㎡以上"
    if max_area is not None:
        return f"_{int(max_area)}㎡未満"
    return ""


def combine_filter_parts(*filter_parts):
    parts = [part for part in filter_parts if part and part.strip()]
    if not parts:
        return ""
    return " AND ".join(f"({part})" for part in parts)


def create_five_layers_in_group(project, iface, uri, group, shape, size_mm, extra_filter=""):
    common_general = '"施設区分" = \'一般施設\''
    common_rent = '"施設区分" = \'賃借施設\''

    if extra_filter.strip():
        general_base = f"({common_general}) AND ({extra_filter})"
        rent_base = f"({common_rent}) AND ({extra_filter})"
    else:
        general_base = common_general
        rent_base = common_rent

    desired_display_order = [
        {
            "name": "賃借施設",
            "subset": rent_base,
            "color": "160,32,240,255",
            "label_expr": '\'賃:\' || "施設名称"',
            "rule_based_label": True
        },
        {
            "name": "一般施設_築45年以上",
            "subset": f"({general_base}) AND ((year(now()) - to_int(\"建築時期\")) >= 45)",
            "color": "255,0,0,255",
            "label_expr": '"施設名称" || \'：築\' || to_string(year(now()) - to_int("建築時期")) || \'年\'',
            "rule_based_label": False
        },
        {
            "name": "一般施設_築40年以上45年未満",
            "subset": f"({general_base}) AND ((year(now()) - to_int(\"建築時期\")) >= 40 AND (year(now()) - to_int(\"建築時期\")) < 45)",
            "color": "255,255,0,255",
            "label_expr": '"施設名称" || \'：築\' || to_string(year(now()) - to_int("建築時期")) || \'年\'',
            "rule_based_label": False
        },
        {
            "name": "一般施設_築35年以上40年未満",
            "subset": f"({general_base}) AND ((year(now()) - to_int(\"建築時期\")) >= 35 AND (year(now()) - to_int(\"建築時期\")) < 40)",
            "color": "0,0,255,255",
            "label_expr": '"施設名称" || \'：築\' || to_string(year(now()) - to_int("建築時期")) || \'年\'',
            "rule_based_label": False
        },
        {
            "name": "一般施設_築35年未満",
            "subset": f"({general_base}) AND ((year(now()) - to_int(\"建築時期\")) < 35)",
            "color": "0,0,0,255",
            "label_expr": '"施設名称" || \'：築\' || to_string(year(now()) - to_int("建築時期")) || \'年\'',
            "rule_based_label": False
        }
    ]

    insertion_order = list(reversed(desired_display_order))
    created_names = []

    for d in insertion_order:
        layer = QgsVectorLayer(uri, d["name"], "delimitedtext")

        if not layer.isValid():
            print(f"Layer failed to load: {d['name']}")
            continue

        project.addMapLayer(layer, False)
        group.insertLayer(0, layer)

        layer.setSubsetString(d["subset"])
        apply_symbol(layer, shape, d["color"], size_mm)

        if d["rule_based_label"]:
            apply_rule_based_label(layer, d["label_expr"], d["color"], "賃借施設ラベル")
        else:
            apply_simple_label(layer, d["label_expr"], d["color"])

        layer.triggerRepaint()
        layer.emitStyleChanged()
        iface.layerTreeView().refreshLayerSymbology(layer.id())

        created_names.append(d["name"])

    return desired_display_order, created_names


def select_csv_path(parent, start_dir):
    csv_path, _ = QFileDialog.getOpenFileName(
        parent,
        "CSVファイルを選択してください",
        start_dir,
        "CSV Files (*.csv);;All Files (*.*)"
    )
    return csv_path


def get_project_start_dir(project):
    project_path = project.fileName()
    if not project_path and hasattr(project, "absoluteFilePath"):
        project_path = project.absoluteFilePath()

    if project_path:
        project_path = os.path.abspath(project_path)
        if os.path.isfile(project_path):
            return os.path.dirname(project_path)
        if os.path.isdir(project_path):
            return project_path

    home_path = project.homePath() if hasattr(project, "homePath") else ""
    if home_path and os.path.isdir(home_path):
        return os.path.abspath(home_path)

    return os.path.expanduser("~")


def select_ward(parent):
    selected_ward, ok = QInputDialog.getItem(
        parent,
        "区の選択",
        "〇〇区を選んでください：",
        WARD_NAMES,
        0,
        False
    )
    if not ok:
        return None
    return selected_ward


def select_shape(parent):
    shapes = ["circle", "square", "triangle", "diamond", "cross"]
    shape, ok = QInputDialog.getItem(
        parent,
        "シンボル形状",
        "シンボルの形を選んでください：",
        shapes,
        0,
        False
    )
    if not ok:
        return None
    return shape


def select_size(parent):
    size_mm, ok = QInputDialog.getDouble(
        parent,
        "サイズ設定",
        "サイズ(mm)を入力してください：",
        2.0, 0.1, 50.0, 1
    )
    if not ok:
        return None
    return size_mm


def run_main(
    iface,
    parent=None,
    csv_path=None,
    selected_ward=None,
    shape=None,
    size_mm=None,
    group_selection='group1',
    area_filter=None,
):
    """
    Plugin からも Python Console からも呼べる共通入口
    """
    project = QgsProject.instance()
    if isinstance(group_selection, str):
        group_selections = [group_selection]
    else:
        group_selections = list(group_selection or ['group1'])
    unknown_selections = [
        selection
        for selection in group_selections
        if selection not in ('group1', 'group2', 'group3')
    ]
    if unknown_selections:
        print(f"不明なグループ選択です: {unknown_selections}")
        return None

    if parent is None and iface is not None:
        parent = iface.mainWindow()

    start_dir = get_project_start_dir(project)

    if not csv_path:
        csv_path = select_csv_path(parent, start_dir)
        if not csv_path:
            print("CSV選択をキャンセルしました。")
            return None

    if 'group3' in group_selections and not selected_ward:
        selected_ward = select_ward(parent)
        if not selected_ward:
            print("区選択をキャンセルしました。")
            return None

    if not shape:
        shape = select_shape(parent)
        if not shape:
            print("シンボル形状の選択をキャンセルしました。")
            return None

    if size_mm is None:
        size_mm = select_size(parent)
        if size_mm is None:
            print("サイズ入力をキャンセルしました。")
            return None

    area_filter_expression = build_total_floor_area_expression(area_filter)
    area_group_suffix = build_total_floor_area_group_suffix(area_filter)

    csv_path_uri = csv_path.replace("\\", "/")
    uri = (
        f"file:///{csv_path_uri}"
        "?delimiter=,"
        "&xField=世界_10進_X"
        "&yField=世界_10進_Y"
        "&crs=EPSG:4326"
    )

    root = project.layerTreeRoot()

    order1, created1 = [], []
    order2, created2 = [], []
    order3, created3 = [], []
    group1_name = "一般施設_賃借施設" + area_group_suffix
    group2_name = "複合化可能一般施設_賃借施設" + area_group_suffix
    group3_name = None

    if 'group1' in group_selections:
        group1 = get_or_create_group(root, group1_name)
        order1, created1 = create_five_layers_in_group(
            project=project,
            iface=iface,
            uri=uri,
            group=group1,
            shape=shape,
            size_mm=size_mm,
            extra_filter=area_filter_expression
        )

    if 'group2' in group_selections:
        group2 = get_or_create_group(root, group2_name)
        order2, created2 = create_five_layers_in_group(
            project=project,
            iface=iface,
            uri=uri,
            group=group2,
            shape=shape,
            size_mm=size_mm,
            extra_filter=combine_filter_parts(
                '"複合不可理由" = \'01複合化可能\'',
                area_filter_expression,
            )
        )

    if 'group3' in group_selections:
        # 選択区内は全部表示し、区外は指定キーワードと7用途施設を除外する
        ward_safe = selected_ward.replace("'", "''")
        inside_ward_filter = f'"所在地" LIKE \'%{ward_safe}%\''
        outside_ward_filter = f'NOT ("所在地" LIKE \'%{ward_safe}%\')'

        excluded_name_filter = build_name_not_contains_all_expression(
            "施設名称",
            EXCLUDED_OUTSIDE_WARD_NAME_KEYWORDS
        )

        seven_use_empty_filter = build_field_is_empty_expression("7用途施設")

        inside_or_outside_filtered = (
            f'(({inside_ward_filter}) OR '
            f'(({outside_ward_filter}) AND {excluded_name_filter} AND {seven_use_empty_filter}))'
        )

        group3_name = f"複合化可能一般施設_賃借施設_{selected_ward}以外で7用途施設または消防署を除外{area_group_suffix}"
        group3_extra_filter = (
            combine_filter_parts(
                '"複合不可理由" = \'01複合化可能\'',
                inside_or_outside_filtered,
                area_filter_expression,
            )
        )

        group3 = get_or_create_group(root, group3_name)
        order3, created3 = create_five_layers_in_group(
            project=project,
            iface=iface,
            uri=uri,
            group=group3,
            shape=shape,
            size_mm=size_mm,
            extra_filter=group3_extra_filter
        )

    iface.mapCanvas().refreshAllLayers()

    result_info = {
        "csv_path": csv_path,
        "selected_ward": selected_ward,
        "group_selection": group_selections,
        "area_filter": area_filter,
        "group1_name": group1_name,
        "group2_name": group2_name,
        "group3_name": group3_name,
        "created_count": len(created1) + len(created2) + len(created3),
        "order1": order1,
        "order2": order2,
        "order3": order3
    }

    print("作成完了")
    print(f"CSV: {csv_path}")
    if selected_ward:
        print(f"選択区: {selected_ward}")
        print("\n選択区の外で除外する施設名称キーワード:")
        for kw in EXCLUDED_OUTSIDE_WARD_NAME_KEYWORDS:
            print(f"  - {kw}")
        print("\n選択区の外で「7用途施設」に値がある施設も除外します。")

    for group_name, order in (
        (group1_name, order1),
        (group2_name, order2),
        (group3_name, order3),
    ):
        if group_name and order:
            print(f"\n{group_name} グループ内の表示順（上→下）:")
            for d in order:
                print(f"  - {d['name']}")

    print(f"\n作成レイヤ数: {result_info['created_count']}")

    return result_info
