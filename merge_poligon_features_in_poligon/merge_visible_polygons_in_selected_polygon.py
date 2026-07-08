# -*- coding: utf-8 -*-

import os

from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
from qgis.core import (
    QgsProject,
    QgsWkbTypes,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsVectorFileWriter,
    QgsGeometry
)
from PyQt5.QtCore import QVariant


# =========================================================
# 設定
# =========================================================
EXCLUDE_FIELD_NAMES = {"fid"}   # GeoPackageの主キー衝突回避
ADD_SOURCE_FID = True           # 元feature idを保存したい場合
SOURCE_FID_FIELD_NAME = "src_fid"
ADD_SOURCE_LAYER_NAME = True    # 元レイヤ名も保存したい場合
SOURCE_LAYER_FIELD_NAME = "src_layer"

# True: 選択ポリゴンと少しでも重なれば抽出
# False: 完全に内包されるポリゴンのみ抽出
USE_INTERSECTS = True


def run(iface):
    """
    QGIS plugin の def run(self) から呼び出すための関数
    iface を受け取り、選択ポリゴン内または重なる表示中ポリゴンを結合して
    GeoPackage に保存し、保存後にレイヤを読み込みます。
    """
    parent = iface.mainWindow() if iface is not None else None

    try:
        # =========================================================
        # 1. プロジェクト取得
        # =========================================================
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        transform_context = project.transformContext()

        # =========================================================
        # 2. 選択 feature を持つポリゴンレイヤを探す
        # =========================================================
        candidate_polygon_layers = []

        for lyr in project.mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue
            if lyr.geometryType() != QgsWkbTypes.PolygonGeometry:
                continue
            if lyr.selectedFeatureCount() > 0:
                candidate_polygon_layers.append(lyr)

        if not candidate_polygon_layers:
            raise Exception("選択 feature を持つポリゴンレイヤがありません。ポリゴン feature を選択してください。")

        if len(candidate_polygon_layers) > 1:
            layer_names = [lyr.name() for lyr in candidate_polygon_layers]
            raise Exception(
                "選択 feature を持つポリゴンレイヤが複数あります。"
                f" 1つだけにしてください: {layer_names}"
            )

        polygon_layer = candidate_polygon_layers[0]
        selected_polygon_features = polygon_layer.selectedFeatures()

        # =========================================================
        # 3. 選択ポリゴンを1つのジオメトリに結合
        # =========================================================
        selected_geoms = []

        for f in selected_polygon_features:
            g = f.geometry()
            if g is not None and not g.isEmpty():
                selected_geoms.append(QgsGeometry(g))

        if not selected_geoms:
            raise Exception("選択されたポリゴンに有効なジオメトリがありません。")

        merged_polygon_geom = QgsGeometry(selected_geoms[0])
        for g in selected_geoms[1:]:
            merged_polygon_geom = merged_polygon_geom.combine(g)

        polygon_crs = polygon_layer.crs()

        # =========================================================
        # 4. 表示中のポリゴンレイヤ取得
        #    ※選択元ポリゴンレイヤ自身は除外
        # =========================================================
        visible_polygon_layers = []

        for lyr in project.mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue
            if lyr.geometryType() != QgsWkbTypes.PolygonGeometry:
                continue
            if lyr.id() == polygon_layer.id():
                continue

            node = root.findLayer(lyr.id())
            if node is None:
                continue
            if not node.isVisible():
                continue

            visible_polygon_layers.append(lyr)

        if not visible_polygon_layers:
            raise Exception("表示されているポリゴンレイヤが見つかりません。")

        # =========================================================
        # 5. 出力フィールド作成
        #    表示中ポリゴンレイヤの全属性を統合
        #    ただし fid は除外
        # =========================================================
        out_fields = QgsFields()
        field_name_set = set()

        if ADD_SOURCE_FID:
            out_fields.append(QgsField(SOURCE_FID_FIELD_NAME, QVariant.LongLong))
            field_name_set.add(SOURCE_FID_FIELD_NAME)

        if ADD_SOURCE_LAYER_NAME:
            out_fields.append(QgsField(SOURCE_LAYER_FIELD_NAME, QVariant.String))
            field_name_set.add(SOURCE_LAYER_FIELD_NAME)

        for lyr in visible_polygon_layers:
            for fld in lyr.fields():
                fld_name = fld.name()

                if fld_name.lower() in EXCLUDE_FIELD_NAMES:
                    continue

                if fld_name not in field_name_set:
                    out_fields.append(QgsField(fld))
                    field_name_set.add(fld_name)

        if len(out_fields) == 0:
            raise Exception("出力すべき属性フィールドがありません。")

        # =========================================================
        # 6. 保存ダイアログ
        # =========================================================
        project_path = project.fileName()

        if project_path:
            initial_dir = os.path.dirname(project_path)
        else:
            initial_dir = os.path.expanduser("~")

        default_file_name = "merged_polygons_in_selected_polygon.gpkg"

        save_path, _ = QFileDialog.getSaveFileName(
            parent,
            "GeoPackageとして保存",
            os.path.join(initial_dir, default_file_name),
            "GeoPackage (*.gpkg)"
        )

        if not save_path:
            return

        if not save_path.lower().endswith(".gpkg"):
            save_path += ".gpkg"

        output_layer_name = os.path.splitext(os.path.basename(save_path))[0]

        # =========================================================
        # 7. 出力メモリレイヤ作成
        #    MultiPolygon にしておくと Polygon / MultiPolygon 両対応しやすい
        # =========================================================
        out_layer = QgsVectorLayer(
            f"MultiPolygon?crs={polygon_crs.authid()}",
            output_layer_name,
            "memory"
        )

        out_dp = out_layer.dataProvider()
        out_dp.addAttributes(out_fields)
        out_layer.updateFields()

        # =========================================================
        # 8. 選択ポリゴン内（または重なる）のポリゴンを抽出して追加
        # =========================================================
        new_features = []

        for poly_layer in visible_polygon_layers:
            print("処理中:", poly_layer.name())

            poly_crs = poly_layer.crs()

            if poly_crs.isValid() and poly_crs != polygon_crs:
                to_polygon_crs = QgsCoordinateTransform(poly_crs, polygon_crs, transform_context)
                to_source_crs = QgsCoordinateTransform(polygon_crs, poly_crs, transform_context)
                bbox_for_request = to_source_crs.transformBoundingBox(merged_polygon_geom.boundingBox())
            else:
                to_polygon_crs = None
                bbox_for_request = merged_polygon_geom.boundingBox()

            request = QgsFeatureRequest().setFilterRect(bbox_for_request)

            for feat in poly_layer.getFeatures(request):
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue

                test_geom = QgsGeometry(geom)

                if to_polygon_crs is not None:
                    try:
                        test_geom.transform(to_polygon_crs)
                    except Exception:
                        continue

                if QgsWkbTypes.geometryType(test_geom.wkbType()) != QgsWkbTypes.PolygonGeometry:
                    continue

                if USE_INTERSECTS:
                    hit = merged_polygon_geom.intersects(test_geom)
                else:
                    hit = merged_polygon_geom.contains(test_geom)

                if not hit:
                    continue

                out_geom = QgsGeometry(test_geom)
                try:
                    if QgsWkbTypes.isSingleType(out_geom.wkbType()):
                        out_geom = QgsGeometry.fromWkt(
                            out_geom.asWkt().replace("Polygon", "MultiPolygon", 1)
                        )
                except Exception:
                    pass

                new_feat = QgsFeature(out_fields)
                new_feat.setGeometry(out_geom)

                attr_dict = {fld.name(): None for fld in out_fields}

                if ADD_SOURCE_FID:
                    attr_dict[SOURCE_FID_FIELD_NAME] = feat.id()

                if ADD_SOURCE_LAYER_NAME:
                    attr_dict[SOURCE_LAYER_FIELD_NAME] = poly_layer.name()

                for fld in poly_layer.fields():
                    fname = fld.name()

                    if fname.lower() in EXCLUDE_FIELD_NAMES:
                        continue

                    if fname in attr_dict:
                        try:
                            attr_dict[fname] = feat[fname]
                        except Exception:
                            attr_dict[fname] = None

                new_feat.setAttributes([attr_dict[fld.name()] for fld in out_fields])
                new_features.append(new_feat)

        if not new_features:
            raise Exception("選択ポリゴン内にある表示中ポリゴン feature は見つかりませんでした。")

        out_dp.addFeatures(new_features)
        out_layer.updateExtents()

        # =========================================================
        # 9. GPKG保存
        # =========================================================
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = output_layer_name
        options.fileEncoding = "UTF-8"

        write_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            out_layer,
            save_path,
            transform_context,
            options
        )

        result_code = write_result[0]

        if result_code != QgsVectorFileWriter.NoError:
            raise Exception(f"GPKG保存エラー: {write_result}")

        # =========================================================
        # 10. 保存したレイヤを読み込み
        # =========================================================
        saved_uri = f"{save_path}|layername={output_layer_name}"
        saved_layer = QgsVectorLayer(saved_uri, output_layer_name, "ogr")

        if saved_layer.isValid():
            QgsProject.instance().addMapLayer(saved_layer)

            msg = (
                f"保存完了:\n{save_path}\n\n"
                f"使用ポリゴンレイヤ: {polygon_layer.name()}\n"
                f"保存レイヤ名: {output_layer_name}\n"
                f"保存件数: {len(new_features)}"
            )

            if iface is not None:
                iface.messageBar().pushSuccess("完了", "ポリゴン結合レイヤを保存して追加しました。")

            QMessageBox.information(parent, "完了", msg)

        else:
            QMessageBox.warning(
                parent,
                "注意",
                f"保存は完了しましたが、レイヤの再読込に失敗しました。\n保存先: {save_path}"
            )

    except Exception as e:
        if iface is not None:
            iface.messageBar().pushCritical("エラー", str(e))
        QMessageBox.critical(parent, "エラー", str(e))
        raise