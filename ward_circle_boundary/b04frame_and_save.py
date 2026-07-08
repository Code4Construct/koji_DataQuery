import os
from qgis.utils import iface
from qgis.PyQt.QtWidgets import QFileDialog
from qgis.core import (
    QgsProject,
    QgsWkbTypes,
    QgsVectorFileWriter,
    QgsCoordinateReferenceSystem,
    QgsFillSymbol,
    QgsSingleSymbolRenderer,
    QgsFeatureRequest,
    QgsVectorLayer
)


def export_selected_polygons_with_red_outline(
    output_layer_name="selected_polygons_red_outline",
    outline_color="255,0,0,255",
    outline_width_mm="0.5",
    target_epsg="EPSG:6674",
    source_layer=None,
    remove_source_if_memory=True,
    add_saved_layer_to_project=True,
    set_saved_layer_active=True
):
    project = QgsProject.instance()

    if source_layer is None:
        source_layer = iface.activeLayer()

    # =========================
    # ① アクティブレイヤ確認
    # =========================
    if source_layer is None:
        raise RuntimeError("アクティブレイヤがありません。")

    if QgsWkbTypes.geometryType(source_layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
        raise RuntimeError("アクティブレイヤがポリゴンレイヤではありません。")

    if source_layer.selectedFeatureCount() == 0:
        raise RuntimeError("ポリゴンが選択されていません。")

    # =========================
    # ② 選択地物だけを内部一時レイヤ化
    #    ※プロジェクトには追加しない
    # =========================
    selected_layer = source_layer.materialize(
        QgsFeatureRequest().setFilterFids(source_layer.selectedFeatureIds())
    )
    selected_layer.setName(output_layer_name)

    # =========================
    # ③ 赤枠・塗りなしのシンボル設定
    # =========================
    symbol = QgsFillSymbol.createSimple({
        "color": "0,0,0,0",
        "outline_color": outline_color,
        "outline_width": outline_width_mm,
        "outline_width_unit": "MM"
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
        iface.mainWindow(),
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
    #    例: abc.gpkg -> abc
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
    # ⑧ 保存済みgpkgレイヤをプロジェクトに追加
    #    ※ scratch layer ではなくファイルレイヤ
    # =========================
    if add_saved_layer_to_project:
        uri = f"{save_path}|layername={gpkg_layer_name}"
        saved_file_layer = QgsVectorLayer(uri, gpkg_layer_name, "ogr")

        if not saved_file_layer.isValid():
            raise RuntimeError("保存後の gpkg レイヤ読み込みに失敗しました。")

        # 同名レイヤが既にあれば削除
        existing_layers = project.mapLayersByName(gpkg_layer_name)
        for lyr in existing_layers:
            if project.mapLayer(lyr.id()):
                project.removeMapLayer(lyr.id())

        # 保存済みレイヤにも同じスタイルを設定
        saved_symbol = QgsFillSymbol.createSimple({
            "color": "0,0,0,0",
            "outline_color": outline_color,
            "outline_width": outline_width_mm,
            "outline_width_unit": "MM"
        })
        saved_file_layer.setRenderer(QgsSingleSymbolRenderer(saved_symbol))

        project.addMapLayer(saved_file_layer)

        if set_saved_layer_active:
            iface.setActiveLayer(saved_file_layer)

    # =========================
    # ⑨ 選択解除
    # =========================
    source_layer.removeSelection()

    if saved_file_layer is not None:
        saved_file_layer.removeSelection()

    # =========================
    # ⑩ 元レイヤが Temporary Scratch Layer なら削除
    # =========================
    if remove_source_if_memory:
        if source_layer.providerType() == "memory" and project.mapLayer(source_layer.id()):
            print(f"Temporary Scratch Layer を削除: {source_layer.name()}")
            project.removeMapLayer(source_layer.id())

    # =========================
    # ⑪ scratch の内部一時 selected_layer は
    #    プロジェクトに追加していないので残らない
    # =========================
    iface.mapCanvas().refresh()

    print("Temporary Scratch Layer を残さず、保存済み gpkg レイヤだけをプロジェクトに追加しました。")
    return saved_file_layer, save_path


if __name__ == "__console__":
    export_selected_polygons_with_red_outline()