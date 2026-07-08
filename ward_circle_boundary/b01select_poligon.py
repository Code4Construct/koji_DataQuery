from qgis.utils import iface
from qgis.core import (
    QgsProject,
    QgsFeatureRequest,
    QgsWkbTypes,
    QgsCoordinateTransform,
    QgsMapLayer,
    QgsVectorLayer,
    QgsGeometry
)


def _find_point_layer_with_selection():
    """
    プロジェクト内のポイントレイヤから、
    選択フィーチャを持つレイヤを探して返す。
    複数ある場合は最初の1つを返す。
    """
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
            return layer

    return None


def select_polygons_from_selected_points(polygon_layer_name, point_layer=None):
    if point_layer is None:
        point_layer = _find_point_layer_with_selection()

    if point_layer is None:
        raise Exception("選択フィーチャを持つポイントレイヤが見つかりません。ポイントを選択してから実行してください。")

    if point_layer.type() != QgsMapLayer.VectorLayer:
        raise Exception("指定されたレイヤはベクタレイヤではありません。")

    if QgsWkbTypes.geometryType(point_layer.wkbType()) != QgsWkbTypes.PointGeometry:
        raise Exception("指定されたレイヤはポイントレイヤではありません。")

    if point_layer.selectedFeatureCount() == 0:
        raise Exception(f"ポイントレイヤ '{point_layer.name()}' でフィーチャが選択されていません。")

    polygon_layers = QgsProject.instance().mapLayersByName(polygon_layer_name)
    if not polygon_layers:
        raise Exception(f"ポリゴンレイヤ '{polygon_layer_name}' が見つかりません。")

    polygon_layer = polygon_layers[0]

    if polygon_layer.type() != QgsMapLayer.VectorLayer:
        raise Exception(f"レイヤ '{polygon_layer_name}' はベクタレイヤではありません。")

    if QgsWkbTypes.geometryType(polygon_layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
        raise Exception(f"レイヤ '{polygon_layer_name}' はポリゴンレイヤではありません。")

    point_crs = point_layer.crs()
    polygon_crs = polygon_layer.crs()

    print("使用ポイントレイヤ:", point_layer.name())
    print("point CRS  :", point_crs.authid(), point_crs.description())
    print("polygon CRS:", polygon_crs.authid(), polygon_crs.description())

    coord_transform = None
    if point_crs != polygon_crs:
        coord_transform = QgsCoordinateTransform(
            point_crs,
            polygon_crs,
            QgsProject.instance()
        )

    polygon_layer.removeSelection()

    selected_points = point_layer.selectedFeatures()
    if not selected_points:
        raise Exception(f"ポイントレイヤ '{point_layer.name()}' でフィーチャが選択されていません。")

    polygon_ids_to_select = set()

    for point_feat in selected_points:
        point_geom = point_feat.geometry()
        if point_geom is None or point_geom.isEmpty():
            continue

        # clone() の代わりにコピーを作る
        test_point_geom = QgsGeometry(point_geom)

        if coord_transform is not None:
            result = test_point_geom.transform(coord_transform)
            if result != 0:
                print(f"座標変換に失敗: point feature id = {point_feat.id()}")
                continue

        request = QgsFeatureRequest().setFilterRect(test_point_geom.boundingBox())

        for poly_feat in polygon_layer.getFeatures(request):
            poly_geom = poly_feat.geometry()
            if poly_geom is None or poly_geom.isEmpty():
                continue

            if poly_geom.intersects(test_point_geom):
                polygon_ids_to_select.add(poly_feat.id())

    polygon_layer.selectByIds(list(polygon_ids_to_select))

    print(f"選択したポイントに重なるポリゴンを {len(polygon_ids_to_select)} 件選択しました。")
    return polygon_layer, list(polygon_ids_to_select)


if __name__ == "__console__":
    select_polygons_from_selected_points("区域EPSG_6674")