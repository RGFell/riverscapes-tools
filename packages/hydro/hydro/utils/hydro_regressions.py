import argparse
import sqlite3
import numpy as np
from sklearn.linear_model import LinearRegression
import csv
import json
import datetime
import traceback
import sys

from rscommons import Logger, dotenv


def generate_linear_regressions(data_dict, x_key, y_key):
    """
    Generate linear regression models using values from a dictionary and compare
    a regular linear regression model to a log-transformed model, returning the better fit.

    Parameters:
    data_dict (dict): Dictionary containing the data.
    x_key (str): Key to be used as the independent variable.
    y_key (str): Key to be used as the dependent variable.

    Returns:
    dict: Dictionary containing the better model's coefficients, intercept, and R^2 score.
    """
    # Extract data from the dictionary
    X = np.array(data_dict[x_key]).reshape(-1, 1)
    y = np.array(data_dict[y_key])

    # Create and train the regular linear regression model
    model_regular = LinearRegression(fit_intercept=False)
    model_regular.fit(X, y)
    r2_regular = model_regular.score(X, y)

    # Create and train the log-transformed linear regression model
    X_log = np.log(X)
    model_log = LinearRegression()
    model_log.fit(X_log, y)
    r2_log = model_log.score(X_log, y)

    # Compare R^2 scores and return the better model
    if r2_regular >= r2_log:
        return {
            'model_type': 'regular',
            'coefficients': model_regular.coef_,
            'intercept': model_regular.intercept_,
            'r2_score': r2_regular
        }
    else:
        return {
            'model_type': 'log-transformed',
            'coefficients': model_log.coef_,
            'intercept': model_log.intercept_,
            'r2_score': r2_log
        }


def update_csv_rows(file_path, target_column, target_value, update_column, update_value):
    """
    Update rows in a CSV file where the target column matches the target value.

    Parameters:
    file_path (str): Path to the CSV file.
    target_column (str): Name of the column to be checked for the target value.
    target_value (str): The value to be matched in the target column.
    new_value (str): The new value to be set in the target column.

    Returns:
    None
    """
    # Read the CSV file
    with open(file_path, mode='r', newline='') as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        fieldnames = reader.fieldnames

    # Update the rows
    for row in rows:
        if row[target_column] == target_value:
            row[update_column] = update_value

    # Write the updated rows back to the CSV file
    with open(file_path, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_gage_data(db_path, huc, minimum_gages):

    conn = sqlite3.connect(db_path)
    curs = conn.cursor()

    out_data = {'DA': [], 'Qlow': [], 'Q2': []}

    ct = 0
    # select hucs whose hucs = huc
    curs.execute(f"SELECT * FROM gages WHERE HUC8 = '{huc}'")
    selection = curs.fetchall()
    for gage in selection:
        out_data['DA'].append(gage['DA'])
        out_data['Qlow'].append(gage['Qlow'])
        out_data['Q2'].append(gage['Q2'])
        ct += 1

    if ct >= minimum_gages:
        level = 8
        return out_data, ct, level
    else:
        # step up to huc6 and add to select huc[0:6] = huc[0:6]
        curs.execute(f"SELECT * FROM gages WHERE SUBSTR(HUC6, 0, 6) = '{huc[0:6]}'")
        selection = curs.fetchall()
        for gage in selection:
            ct += 1

    if ct >= minimum_gages:
        level = 6
        return out_data, ct, level
    else:
        # step up to huc4 and add to selection huc[0:4] = huc[0:4]
        curs.execute(f"SELECT * FROM gages WHERE SUBSTR(HUC4, 0, 4) = '{huc[0:4]}'")
        selection = curs.fetchall()
        for gage in selection:
            ct += 1

    if ct >= minimum_gages:
        level = 4
        return out_data, ct, level
    else:
        raise ValueError(f"Insufficient gages for HUC {huc}")


def update_watersheds_table(csv_path, db_path, operator):

    log = Logger('Flow Equations')

    metadata = {}

    # get list of huc8s from watersheds table
    with open(csv_path, mode='r', newline='') as file:
        reader = csv.DictReader(file)
        huc8s_qlow = [row['WatershedID'] for row in reader if row['Qlow'] == '']
        log.info(f"Updating {len(huc8s_qlow)} watersheds with missing Qlow values.")
        huc8s_q2 = [row['WatershedID'] for row in reader if row['Q2'] == '']
        log.info(f"Updating {len(huc8s_q2)} watersheds with missing Q2 values.")

    for huc in huc8s_qlow:
        try:
            data, gage_ct, huc_level = generate_gage_data(db_path, huc, 5)
            qlow = generate_linear_regressions(data, 'DA', 'Qlow')
            if qlow['model_type'] == 'regular':
                qlow_eqn = f"{qlow['intercept']} + {qlow['coefficients'][0]} * DRNAREA"
                qlow_r2 = qlow['r2_score']
            else:
                qlow_eqn = f"{10 ** qlow['intercept']} * DRNAREA ** {qlow['coefficients'][0]}"
                qlow_r2 = qlow['r2_score']

            metadata[huc] = {'Operator': operator, 'DateCreated': datetime.datetime.now().isoformat(), 'NumGages': gage_ct, 'HucLevel': huc_level, 'QLowR2': qlow_r2}

            update_csv_rows(csv_path, 'WatershedID', huc, 'Qlow', qlow_eqn)  # is it going to be slow doing this one by one?

        except ValueError as e:
            log.error(e)

    for huc in huc8s_q2:
        try:
            data, gage_ct, huc_level = generate_gage_data(db_path, huc, 5)
            q2 = generate_linear_regressions(data, 'DA', 'Q2')
            if q2['model_type'] == 'regular':
                q2_eqn = f"{q2['intercept']} + {q2['coefficients'][0]} * DRNAREA"
                q2_r2 = q2['r2_score']
            else:
                q2_eqn = f"{10 ** q2['intercept']} * DRNAREA ** {q2['coefficients'][0]}"
                q2_r2 = q2['r2_score']

            update_csv_rows(csv_path, 'WatershedID', huc, 'Q2', q2_eqn)
            if huc in metadata.keys():
                metadata[huc].update({'Q2R2': q2_r2})
            else:
                metadata[huc] = {'Operator': operator, 'DateCreated': datetime.datetime.now().isoformat(), 'NumGages': gage_ct, 'HucLevel': huc_level, 'Q2R2': q2_r2}

        except ValueError as e:
            log.error(e)

    for huc, meta in metadata.items():
        update_csv_rows(csv_path, 'WatershedID', huc, 'Metadata', json.dumps(meta))


def main():

    parser = argparse.ArgumentParser(description='Update the flow equations in the watersheds table.')
    parser.add_argument('csv_path', type=str, help='Path to the CSV file containing the watersheds table.')
    parser.add_argument('db_path', type=str, help='Path to the SQLite database containing the gages table.')
    parser.add_argument('operator', type=str, help='The person updating the flow equations.')
    parser.add_argument('--verbose', action='store_true', help='Print log messages to the console.', default=False)

    args = dotenv.parse_args_env(parser)

    log = Logger('Flow Equations')
    log.setup(logPath='', verbose=args.verbose)
    log.title('Update Flow Equations using USGS Gage Data')

    try:
        update_watersheds_table(args.csv_path, args.db_path, args.operator)
    except Exception as e:
        log.error(e)
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)

    sys.exit(0)
