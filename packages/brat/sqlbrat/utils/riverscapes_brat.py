import os
import sqlite3

from rscommons import Logger, ProgressBar, get_shp_or_gpkg, VectorBase
from rscommons.database import SQLiteCon
from rscommons.classes.vector_base import get_utm_zone_epsg


def riverscape_brat(gpkg_path: str, windows: dict):
    """
    Args:
        gpkg_path (str): _description_
        windows (dict): _description_
    """

    log = Logger('Riversapes BRAT')

    reaches = os.path.join(gpkg_path, 'vwReaches')
    dgo = os.path.join(gpkg_path, 'vwDgos')

    log.info('Calculating BRAT Outputs on DGOs')
    with get_shp_or_gpkg(dgo) as dgo_lyr, SQLiteCon(gpkg_path) as db:
        long = dgo_lyr.ogr_layer.GetExtent()[0]
        proj_epsg = get_utm_zone_epsg(long)
        sref, transform = VectorBase.get_transform_from_epsg(dgo_lyr.spatial_ref, proj_epsg)

        for dgo_feature, _counter, _progbar in dgo_lyr.iterate_features("Processing DGO features"):
            dgoid = dgo_feature.GetFID()
            dgo_geom = dgo_feature.GetGeometryRef()
            centerline_len = dgo_feature.GetField('centerline_length')

            ex_num_dams = 0
            hist_num_dams = 0
            lengths = []
            risk = []
            limitation = []
            opportunity = []
            with get_shp_or_gpkg(reaches) as reach_lyr:
                for reach_feature, _counter, _progbar in reach_lyr.iterate_features(clip_shape=dgo_geom):
                    reach_geom = reach_feature.GetGeometryRef()
                    intersect_geom = reach_geom.Intersection(dgo_geom)
                    if intersect_geom is not None:
                        reach_shapely = VectorBase.ogr2shapely(intersect_geom, transform)
                        reach_length = reach_shapely.length / 1000
                        ex_density = reach_feature.GetField('oCC_EX')
                        hist_density = reach_feature.GetField('oCC_HPE')
                        if ex_density is None or hist_density is None:
                            continue
                        ex_num_dams += ex_density * reach_length
                        hist_num_dams += hist_density * reach_length
                        lengths.append(reach_length)
                        risk.append(reach_feature.GetField('Risk'))
                        limitation.append(reach_feature.GetField('Limitation'))
                        opportunity.append(reach_feature.GetField('Opportunity'))

            if len(lengths) > 0:
                ix = lengths.index(max(lengths))
                risk_val = risk[ix]
                limitation_val = limitation[ix]
                opportunity_val = opportunity[ix]
                db.curs.execute(f"UPDATE DGOAttributes SET Risk = '{risk_val}', Limitation = '{limitation_val}', Opportunity = '{opportunity_val}' WHERE DGOID = {dgoid}")

            if centerline_len > 0:
                db.curs.execute(f"UPDATE DGOAttributes SET oCC_EX = {ex_num_dams / (centerline_len / 1000)}, oCC_HPE = {hist_num_dams /  (centerline_len / 1000)} WHERE DGOID = {dgoid}")

        db.conn.commit()

    conn = sqlite3.connect(gpkg_path)
    curs = conn.cursor()

    log.info('Calculating BRAT Outputs on IGOs (moving window)')
    progbar = ProgressBar(len(windows))
    counter = 0
    for igoid, dgoids in windows.items():
        counter += 1
        progbar.update(counter)
        ex_dams = 0
        hist_dams = 0
        cl_len = 0
        area = []
        risk = []
        limitation = []
        opportunity = []
        for dgoid in dgoids:
            curs.execute(f'SELECT centerline_length, oCC_EX, oCC_HPE, Risk, Limitation, Opportunity FROM DGOAttributes WHERE DGOID = {dgoid}')
            dgoattrs = curs.fetchone()
            if dgoattrs[1] is None:
                continue
            cl_len += dgoattrs[0]
            ex_dams += dgoattrs[0]/1000 * dgoattrs[1]
            hist_dams += dgoattrs[0]/1000 * dgoattrs[2]
            risk.append(dgoattrs[3])
            limitation.append(dgoattrs[4])
            opportunity.append(dgoattrs[5])
            curs.execute(f'SELECT segment_area FROM DGOAttributes WHERE DGOID = {dgoid}')
            area.append(curs.fetchone()[0])

        ix = area.index(max(area))
        risk_val = risk[ix]
        limitation_val = limitation[ix]
        opportunity_val = opportunity[ix]

        curs.execute(f"UPDATE IGOAttributes SET oCC_EX = {ex_dams / (cl_len / 1000)}, oCC_HPE = {hist_dams / (cl_len / 1000)} WHERE IGOID = {igoid}")
        curs.execute(f"UPDATE IGOAttributes SET Risk = '{risk_val}', Limitation = '{limitation_val}', Opportunity = '{opportunity_val}' WHERE IGOID = {igoid}")
        conn.commit()
    conn.close()
    log.info('BRAT DGO and IGO Outputs Calculated')
