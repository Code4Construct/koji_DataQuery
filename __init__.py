# -*- coding: utf-8 -*-


def classFactory(iface):  # pylint: disable=invalid-name
    """Load kojiGIS4QGIS plugin."""
    from .kojiGIS4QGIS import KojiGIS4QGIS

    return KojiGIS4QGIS(iface)
