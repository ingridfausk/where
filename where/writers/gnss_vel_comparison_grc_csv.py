"""Compare different GNSS_VEL Where datasets and write a text file in GRC CSV format

Description:
------------

A dictionary with datasets is used as input for this writer. The keys of the dictionary are station names. 

Example:
--------


"""
# Standard library imports
import csv
from typing import Dict, List

# External library imports
import numpy as np
import pandas as pd

# Midgard imports
from midgard.data import position
from midgard.dev import plugins

# Where imports
import where
from where.lib import config
from where.lib import log
from where.lib import util
from where.writers._gnss import get_grc_csv_header, get_grc_csv_row


@plugins.register
def gnss_vel_comparison_grc_csv(dset: "Dataset") -> None:
    """Compare different GNSS_VEL Where datasets and write a text file in GRC CSV format

    Args:
        dset:  Dictionary with station name as keys and the belonging Dataset as value
    """
    output_defs = dict()
    dset_first = dset[list(dset.keys())[0]]
    _,nav_msg,mode = dset_first.vars["profile"].split("_")[0:3]

    # Get file path
    file_vars = {**dset_first.vars, **dset_first.analysis}
    file_vars["solution"] = config.tech.gnss_comparison_report.solution.str.lower()
    file_path = config.files.path("output_gnss_vel_comparison_grc_csv", file_vars=file_vars)
    file_path.parent.mkdir(parents=True, exist_ok=True)

     # Get dataframes for writing
    df_month = _generate_dataframe(dset)


    # Write file
    # 
    # Example:
    #
    #   Service Line,Service Category,Business Service,Batch,Satellite,PRN,Slot,GSS Site,Service,Type,Mode,Target,Unit,Month/Year,Result
    #   Open Service,Position Domain,FOM-OS-0021 3D Velocity Service Accuracy per Station over Month,,,,,Ny Alesund (Norway),nabd,OS,Single,E1,,m/s,July-2021,0.04901977073863475
    #   Open Service,Position Domain,FOM-OS-0021 3D Velocity Service Accuracy per Station over Month,,,,,Honningsvåg (Norway),hons,OS,Single,E1,,m/s,July-2021,0.04110985838629842
    #
    with open(file_path, "w") as csvfile:
        writer = csv.writer(csvfile, delimiter=";")

        log.info(f"Write file {file_path}.")

        # Write header 
        writer.writerow(get_grc_csv_header())

        # Write results to GRC CSV file
        for index, row in df_month.iterrows():

            row = get_grc_csv_row(
                    kpi="site_vel_3d", 
                    mode=mode, 
                    date=row.date, 
                    result=row.site_vel_3d,
                    station=row.station, 
            )

            writer.writerow(row)


def _generate_dataframe(dset: Dict[str, "Dataset"]) -> Dict[str, pd.core.frame.DataFrame]:
    """Generate dataframe based on station datasets

    Example for "df_month" dictionary:

               date           hpe           vpe station
        0  Jul-2021  1.936327e-09  5.567021e-09    nabd
        1  Jul-2021  3.034691e-09  5.419228e-09    hons
        2  Jul-2021  3.865243e-09  5.229739e-09    vegs

    Args:
        dset: Dictionary with station name as keys and the belonging Dataset as value

    Returns:
        Dataframe with monthly entries with columns like date, stationm hpe, vpe, ...

    """
    dsets = dset
    df_month = pd.DataFrame()
    dfs_month_field = {
        "site_vel_3d": pd.DataFrame(), 
    }

    for station, dset in dsets.items():

        if dset.num_obs == 0:
            log.warn(f"Dataset '{station}' is empty.")
            continue


        # Determine dataframe 
        df = dset.as_dataframe(fields=["time.gps", "site_vel_3d"])
        df = df.rename(columns={"time_gps": "date"})

        if df.empty:
            continue
        else:

            df_month_tmp = df.set_index("date").resample("M").apply(lambda x: np.nanpercentile(x, q=95))
            df_month_tmp.index = df_month_tmp.index.strftime("%y-%b")
            df_month_tmp["station"] = np.repeat(station, df_month_tmp.shape[0])
            df_month = pd.concat([df_month, df_month_tmp], axis=0)

    # Prepare dataframes for writing
    df_month.index.name = "date"
    df_month = df_month.reset_index()

    return df_month


