# -*- coding: utf-8 -*-

from importlib import reload

from qgis.PyQt.QtWidgets import QInputDialog
from qgis.core import QgsProject, QgsMapLayer, QgsWkbTypes

from . import b01select_poligon
from . import b02add_buffer
from . import b03merge_dissolve_from_defferent_layers
from . import b04frame_and_save
from . import b05save_selected_points_star


def run_selected_feature_ward_buffer_outline(iface):
    """
    選択した地物について、
    1) 地物を星印で保存
    2) 対応する区ポリゴンを選択
    3) 2kmバッファ作成
    4) 別レイヤ由来のポリゴンを統合・ディゾルブ
    5) 外枠を赤線で保存
    を実行する
    """

    reload(b01select_poligon)
    reload(b02add_buffer)
    reload(b03merge_dissolve_from_defferent_layers)
    reload(b04frame_and_save)
    reload(b05save_selected_points_star)

    b01 = b01select_poligon
    b02 = b02add_buffer
    b03 = b03merge_dissolve_from_defferent_layers
    b04 = b04frame_and_save
    b05 = b05save_selected_points_star

    project = QgsProject.instance()
    polygon_layers = []

    for lyr in project.mapLayers().values():
        if lyr.type() == QgsMapLayer.VectorLayer:
            geom_type = QgsWkbTypes.geometryType(lyr.wkbType())
            if geom_type == QgsWkbTypes.PolygonGeometry:
                polygon_layers.append(lyr)

    if not polygon_layers:
        raise Exception("プロジェクト内にポリゴンレイヤがありません。")

    polygon_layer_names = [lyr.name() for lyr in polygon_layers]

    default_index = 0
    if "区域EPSG_6674" in polygon_layer_names:
        default_index = polygon_layer_names.index("区域EPSG_6674")

    selected_polygon_layer_name, ok = QInputDialog.getItem(
        iface.mainWindow(),
        "ポリゴンレイヤ選択",
        "使用するポリゴンレイヤを選んでください：",
        polygon_layer_names,
        default_index,
        False
    )

    if not ok or not selected_polygon_layer_name:
        raise Exception("ポリゴンレイヤの選択をキャンセルしました。")

    print(f"選択したポリゴンレイヤ: {selected_polygon_layer_name}")

    b05.save_selected_points_as_red_star(iface_obj=iface)
    b01.select_polygons_from_selected_points(selected_polygon_layer_name)
    b02.create_selected_buffer()
    b03.dissolve_selected_polygons()
    b04.export_selected_polygons_with_red_outline()