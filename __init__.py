# -*- coding: utf-8 -*-


def classFactory(iface):  # pylint: disable=invalid-name
    """Load the koji DataQuery plugin."""
    from .koji_DataQuery import KojiDataQuery

    return KojiDataQuery(iface)
