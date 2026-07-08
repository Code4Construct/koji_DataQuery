import os

from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import (
    QgsProject,
    QgsWkbTypes,
    QgsVectorFileWriter,
    QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
    QgsMarkerSymbol,
    QgsSingleSymbolRenderer,
    QgsVectorLayer
)


def _find_point_layer_with_selected_features(iface_obj=None):
    """
    選択ポイントを持つポイントレイヤを探す。
    優先順位:
    1. アクティブレイヤ
    2. プロジェクト内の他のポイントレイヤ
    """
    if iface_obj is None:
        from qgis.utils import iface as iface_obj

    project = QgsProject.instance()

    active_layer = iface_obj.activeLayer()
    if (
        active_layer is not None
        and active_layer.type() == active_layer.VectorLayer
        and QgsWkbTypes.geometryType(active_layer.wkbType()) == QgsWkbTypes.PointGeometry
        and active_layer.selectedFeatureCount() > 0
    ):
        return active_layer

    for lyr in project.mapLayers().values():
        if (
            lyr.type() == lyr.VectorLayer
            and QgsWkbTypes.geometryType(lyr.wkbType()) == QgsWkbTypes.PointGeometry
            and lyr.selectedFeatureCount() > 0
        ):
            return lyr

    return None


def save_selected_points_as_red_star(
    output_layer_name="selected_points_red_star",
    target_epsg="EPSG:6674",
    source_layer=None,
    iface_obj=None,
    remove_source_if_memory=False,
    add_saved_layer_to_project=True,
    set_saved_layer_active=True
):
    if iface_obj is None:
        from qgis.utils import iface as iface_obj

    project = QgsProject.instance()

    # =========================
    # ① 対象レイヤ取得
    # =========================
    if source_layer is None:
        source_layer = _find_point_layer_with_selected_features(iface_obj)

    if source_layer is None:
        raise RuntimeError("選択ポイントを持つポイントレイヤが見つかりません。")

    if QgsWkbTypes.geometryType(source_layer.wkbType()) != QgsWkbTypes.PointGeometry:
        raise RuntimeError("指定されたレイヤがポイントレイヤではありません。")

    if source_layer.selectedFeatureCount() == 0:
        raise RuntimeError("ポイントが選択されていません。")

    # =========================
    # ② 選択地物だけを内部一時レイヤ化
    #    ※プロジェクトには追加しない
    # =========================
    selected_layer = source_layer.materialize(
        QgsFeatureRequest().setFilterFids(source_layer.selectedFeatureIds())
    )
    selected_layer.setName(output_layer_name)

    # =========================
    # ③ 赤い星型・5mm のシンボル設定
    # =========================
    symbol = QgsMarkerSymbol.createSimple({
        "name": "star",
        "color": "255,0,0,255",
        "size": "5",
        "size_unit": "MM",
        "outline_color": "255,0,0,255"
    })
    selected_layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    selected_layer.triggerRepaint()

    # =========================
    # ④ 保存先の初期パス
    # =========================
    project_folder = project.absolutePath()
    if project_folder and os.path.exists(project_folder):
        initial_path = os.path.join(project_folder, f"{output_layer_name}.gpkg")
    else:
        initial_path = os.path.expanduser(f"~/{output_layer_name}.gpkg")

    # =========================
    # ⑤ 保存先を聞く
    # =========================
    save_path, _ = QFileDialog.getSaveFileName(
        iface_obj.mainWindow(),
        "保存先を選択してください（EPSG:6674 で保存）",
        initial_path,
        "GeoPackage (*.gpkg)"
    )

    if not save_path:
        raise RuntimeError("保存がキャンセルされました。")

    if not save_path.lower().endswith(".gpkg"):
        save_path += ".gpkg"

    # =========================
    # ⑥ gpkgファイル名からレイヤ名を作る
    #    例: aaa.gpkg → aaa
    # =========================
    gpkg_layer_name = os.path.splitext(os.path.basename(save_path))[0]

    # =========================
    # ⑦ EPSG:6674 で保存
    # =========================
    target_crs = QgsCoordinateReferenceSystem(target_epsg)

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.fileEncoding = "UTF-8"
    options.layerName = gpkg_layer_name
    options.destCRS = target_crs

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        selected_layer,
        save_path,
        project.transformContext(),
        options
    )

    if result[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"保存に失敗しました: {result}")

    print(f"保存完了: {save_path}")
    print(f"保存レイヤ名: {gpkg_layer_name}")

    saved_file_layer = None

    # =========================
    # ⑧ 保存済みレイヤをプロジェクトに追加
    #    ※ scratch layer ではなくファイルレイヤ
    # =========================
    if add_saved_layer_to_project:
        uri = f"{save_path}|layername={gpkg_layer_name}"
        saved_file_layer = QgsVectorLayer(uri, gpkg_layer_name, "ogr")

        if not saved_file_layer.isValid():
            raise RuntimeError("保存後のレイヤ読み込みに失敗しました。")

        # 既存の同名レイヤがあれば削除
        existing_layers = project.mapLayersByName(gpkg_layer_name)
        for lyr in existing_layers:
            if project.mapLayer(lyr.id()):
                project.removeMapLayer(lyr.id())

        # 同じスタイルを設定
        saved_symbol = QgsMarkerSymbol.createSimple({
            "name": "star",
            "color": "255,0,0,255",
            "size": "5",
            "size_unit": "MM",
            "outline_color": "255,0,0,255"
        })
        saved_file_layer.setRenderer(QgsSingleSymbolRenderer(saved_symbol))

        project.addMapLayer(saved_file_layer)

        if set_saved_layer_active:
            iface_obj.setActiveLayer(saved_file_layer)

    # =========================
    # ⑨ 元レイヤが Temporary Scratch Layer なら削除
    # =========================
    if remove_source_if_memory:
        if source_layer.providerType() == "memory" and project.mapLayer(source_layer.id()):
            print(f"Temporary Scratch Layer を削除: {source_layer.name()}")
            project.removeMapLayer(source_layer.id())

    iface_obj.mapCanvas().refresh()

    print("Temporary Scratch Layer を残さず、保存済みレイヤをプロジェクトに追加しました。")
    return save_path, saved_file_layer


if __name__ == "__console__":
    from qgis.utils import iface
    save_selected_points_as_red_star(iface_obj=iface)