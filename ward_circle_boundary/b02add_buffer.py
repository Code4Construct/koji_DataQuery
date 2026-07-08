# 選択したポイント地物からバッファを作成し、
# 作成したバッファ地物を選択状態にする
# 前提：QGIS Python コンソールで実行（iface が使える）

from qgis.utils import iface
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsMapLayer, QgsWkbTypes
)


def _find_selected_point_layers():
    """
    選択地物を持つポイントレイヤを一覧で返す
    """
    layers = []
    for layer in QgsProject.instance().mapLayers().values():
        if layer is None:
            continue
        if layer.type() != QgsMapLayer.VectorLayer:
            continue
        if not isinstance(layer, QgsVectorLayer):
            continue
        if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PointGeometry:
            continue
        if layer.selectedFeatureCount() > 0:
            layers.append(layer)
    return layers


def _choose_source_point_layer():
    """
    選択地物を持つポイントレイヤから1つ返す
    複数ある場合は最初の1つ
    """
    point_layers = _find_selected_point_layers()
    if not point_layers:
        return None
    return point_layers[0]


def create_selected_buffer(
    buffer_m=2000,
    output_layer_name="selected_point_buffer_2km",
    target_epsg="EPSG:6674",
    source_layer=None
):
    if source_layer is None:
        source_layer = _choose_source_point_layer()

    if source_layer is None:
        raise Exception("選択地物を持つポイントレイヤが見つかりません。ポイントを選択してから実行してください。")

    if source_layer.type() != QgsMapLayer.VectorLayer:
        raise Exception("入力レイヤがベクタレイヤではありません。")

    if QgsWkbTypes.geometryType(source_layer.wkbType()) != QgsWkbTypes.PointGeometry:
        raise Exception(f"レイヤ '{source_layer.name()}' はポイントレイヤではありません。")

    selected = source_layer.selectedFeatures()
    if not selected:
        raise Exception(f"ポイントレイヤ '{source_layer.name()}' で地物が選択されていません。")

    print(f"使用入力ポイントレイヤ: {source_layer.name()}")

    # バッファ計算用の投影 CRS
    target_crs = QgsCoordinateReferenceSystem(target_epsg)

    # 変換（レイヤCRS -> target_crs）
    src_crs = source_layer.crs()
    to_target = QgsCoordinateTransform(src_crs, target_crs, QgsProject.instance())
    to_src = QgsCoordinateTransform(target_crs, src_crs, QgsProject.instance())

    # 出力レイヤ（元レイヤと同じCRSで表示）
    out_crs = src_crs
    out = QgsVectorLayer(f"Polygon?crs={out_crs.authid()}", output_layer_name, "memory")
    pr = out.dataProvider()
    pr.addAttributes(source_layer.fields())
    out.updateFields()

    # 選択ポイントごとにバッファを作成
    feats_out = []
    for f in selected:
        geom = f.geometry()
        if geom is None or geom.isEmpty():
            continue

        g = QgsGeometry(geom)

        # 投影してメートル単位でバッファ作成
        result1 = g.transform(to_target)
        if result1 != 0:
            print(f"座標変換に失敗しました: feature id = {f.id()}")
            continue

        buf = g.buffer(buffer_m, 24)
        if buf is None or buf.isEmpty():
            print(f"バッファ作成に失敗しました: feature id = {f.id()}")
            continue

        # 元CRSに戻す
        result2 = buf.transform(to_src)
        if result2 != 0:
            print(f"逆座標変換に失敗しました: feature id = {f.id()}")
            continue

        nf = QgsFeature(out.fields())
        nf.setAttributes(f.attributes())
        nf.setGeometry(buf)
        feats_out.append(nf)

    if not feats_out:
        raise Exception("バッファ地物を作成できませんでした。")

    pr.addFeatures(feats_out)
    out.updateExtents()
    QgsProject.instance().addMapLayer(out)

    # 作成したバッファ地物を選択
    out.selectAll()

    iface.mapCanvas().refresh()

    print(f"選択ポイント {len(selected)} 件から {buffer_m} m バッファを作成し、作成したバッファを選択しました。")
    return out


if __name__ == "__console__":
    try:
        create_selected_buffer()
        QMessageBox.information(
            iface.mainWindow(),
            "完了",
            "選択したポイントから 2km バッファを作成し、作成したバッファを選択しました。"
        )
    except Exception as e:
        QMessageBox.warning(iface.mainWindow(), "エラー", str(e))