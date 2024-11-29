import os
import argparse
import sqlite3
from rscommons import Logger

NEXT_REACH_QUERY = 'SELECT us.CATAREA, ds.HydroID FROM riverlines us LEFT JOIN riverlines ds on us.To_NODE = ds.FROM_NODE WHERE us.HydroID = ?'


def calc_tot_da(curs: sqlite3.Cursor, watershed_id: int, reset_first: bool) -> None:
    log = Logger('Calc TotDA')
    log.info(f'Calculating total drainage area for watershed {watershed_id}')

    curs.execute('SELECT Count(*) FROM riverlines WHERE WatershedHydroID = ?', [watershed_id])
    row = curs.fetchone()
    log.info(f'Found {row[0]} reaches in watershed {watershed_id}')

    curs.execute('SELECT Count(*) FROM riverlines WHERE WatershedHydroID = ? AND TotDASqKm IS NULL', [watershed_id])
    row = curs.fetchone()
    log.info(f'Found {row[0]} reaches without total drainage area in watershed {watershed_id}')

    if reset_first is True:
        log.info(f'Resetting total drainage areas for watershed {watershed_id}')
        curs.execute("UPDATE riverlines SET TotDASqKm = NULL WHERE WatershedHydroID = ?", [watershed_id])

    curs.execute("SELECT HydroID FROM riverlines WHERE Headwater <> 0 and WatershedHydroID = ? and TotDASqKm IS NULL", [watershed_id])
    tot_da_areas = {row[0]: 0.00 for row in curs.fetchall()}
    log.info(f'Found {len(tot_da_areas)} headwaters in watershed {watershed_id}')

    for hydro_id in tot_da_areas.keys():
        tot_da_areas[hydro_id] = calculate_tot_da(curs, hydro_id)

    num_processed = 0
    log.info('Assigning total drainage areas to reaches...')
    for hydro_id, _area in sorted(tot_da_areas.items(), key=lambda item: item[1], reverse=True):
        num_processed += 1
        new_tot_da = float(watershed_id * 10**9 + num_processed)
        num_reaches = assign_tot_da(curs, hydro_id, new_tot_da)

    log.info(f'Assigned total drainage areas to {num_processed} headwaters in watershed {watershed_id}')


def calculate_tot_da(curs: sqlite3.Cursor, hydro_id: int):
    """Calculate the cumulative catchment area from the headwater to the mouth."""

    cum_area = 0
    while hydro_id is not None:
        curs.execute(NEXT_REACH_QUERY, [hydro_id])
        row = curs.fetchall()
        if len(row) == 1:
            cum_area += row[0][0]
            hydro_id = row[0][1]
        elif row is None or len(row) == 0:
            return cum_area
        else:
            raise Exception(f"More than one downstream reach found for HydroID {hydro_id}")

    return cum_area


def assign_tot_da(curs: sqlite3.Cursor, headwater_hydro_id, tot_da: float) -> int:
    """Assign a total drainage area to each reach starting at the headwater down to the ocean."""

    num_reaches = 0
    hydro_id = headwater_hydro_id
    while hydro_id is not None:
        num_reaches += 1
        curs.execute('UPDATE riverlines SET TotDASqKm = ? WHERE HydroID = ? AND TotDASqKm IS NULL', [tot_da, hydro_id])
        curs.execute(NEXT_REACH_QUERY, [hydro_id])
        row = curs.fetchall()
        if len(row) == 1:
            hydro_id = row[0][1]
        elif row is None or len(row) == 0:
            return num_reaches
        else:
            raise Exception(f"More than one downstream reach found for HydroID {hydro_id}")

    return num_reaches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('hydro_gpkg', type=str)
    parser.add_argument('watershed_id', type=int)
    parser.add_argument('reset_first', type=str)
    args = parser.parse_args()

    log = Logger("RS Context")
    log.setup(logPath=os.path.join(os.path.dirname(args.hydro_gpkg), "nz_calc_tot_da.log"), verbose=args.verbose)
    log.title(f'Calculate total drainage area For NZ Watershed: {args.watershed_id}')

    log.info(f'HUC: {args.watershed_id}')
    log.info(f'Hydro GPKG: {args.hydro_gpkg}')
    log.info(f'Reset First: {args.reset_first}')

    with sqlite3.connect(args.hydro_gpkg) as conn:
        curs = conn.cursor()
        try:
            triggers = get_triggers(curs, 'riverlines')

            for trigger in triggers:
                curs.execute(f"DROP TRIGGER {trigger[1]}")

            calc_tot_da(curs, args.watershed_id, args.reset_first.lower() == 'true')
            conn.commit()
            log.info('Calculation complete')

            for trigger in triggers:
                curs.execute(trigger[4])

        except Exception as e:
            conn.rollback()
            raise e


if __name__ == '__main__':
    main()
