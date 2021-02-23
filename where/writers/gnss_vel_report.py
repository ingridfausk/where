"""Write report about a GNSS velocity analysis run

Description:
------------



"""
# Standard library imports
from enum import Enum
from collections import namedtuple
from datetime import datetime
from typing import List, Tuple, Union

# External library imports
import numpy as np
import pandas as pd

# Midgard imports
from midgard.collections import enums 
from midgard.dev import plugins
from midgard.gnss import gnss
from midgard.plot.matplotlib_extension import plot_scatter_subplots, plot
from midgard.math import rotation
from midgard.writers._writers import get_existing_fields_by_attrs, get_field_by_attrs

# Where imports
from where.data import dataset3 as dataset
from where.lib import config
from where.lib import log
from where.writers._report import Report


FIGURE_DPI = 200
FIGURE_FORMAT = "png"

PlotField = namedtuple("PlotField", ["name", "attrs", "unit", "ylabel", "caption"])
PlotField.__new__.__defaults__ = (None,) * len(PlotField._fields)
PlotField.__doc__ = """A convenience class for defining a output field for plotting

    Args:
        name  (str):             Unique name
        attrs (Tuple[str]):      Dataset field attributes
        unit (str):              Unit of field
        ylabel (str):            Y-axis label description
        caption (str):           Caption of plot
    """

FIELDS = (
    PlotField(
        "gnss_range_rate", ("delay", "gnss_range_rate"), "m/s", "Range rate", "Correction of range between satellite and receiver"
    ),
    PlotField(
        "gnss_satellite_clock_rate",
        ("delay", "gnss_satellite_clock_rate"),
        "m/s",
        "Satellite clock rate",
        "Correction of satellite clock rate",
    ),
    PlotField(
        "gnss_earth_rotation_drift",
        ("delay", "gnss_earth_rotation_drift"),
        "m/s",
        "Earth rotation drift",
        "Correction of Earth rotation drift",
    ),
    PlotField(
        "gnss_relativistic_clock_rate",
        ("delay", "gnss_relativistic_clock_rate"),
        "m/s",
        "Relativistic clock rate",
        "Correction of relativistic clock rate effect due to orbit eccentricity",
    ),
   # PlotField(
   #     "estimate_gnss_rcv_clock_rate",
   #     ("estimate_gnss_rcv_clock_rate",),
   #     "m",
   #     "Receiver clock rate estimate",
   #     "Estimate of receiver clock rate",
   # ),
)


@plugins.register
def gnss_vel_report(dset: "Dataset") -> None:
    """Write report about a GNSS velocity analysis run

    Args:
        dset:        A dataset containing the data.
    """
    file_vars = {**dset.vars, **dset.analysis}
    # TODO: Better solution?
    if "station" not in file_vars:  # necessary if called for example by ./where/tools/concatenate.py
        file_vars["station"] = ""
        file_vars["STATION"] = ""

    # Generate figure directory to save figures generated for GNSS report
    figure_dir = config.files.path("output_gnss_vel_report_figure", file_vars=file_vars)
    figure_dir.mkdir(parents=True, exist_ok=True)

    # Generate plots
    _plot_velocity(dset, figure_dir)
    _plot_residual(dset, figure_dir)
    _plot_number_of_satellites(dset, figure_dir)
    _plot_satellite_overview(dset, figure_dir)
    _plot_skyplot(dset, figure_dir)
    _plot_satellite_elevation(dset, figure_dir)
    _plot_model(dset, figure_dir)

    if "pdop" in dset.fields:
        _plot_dop(dset, figure_dir)

    # Generate GNSS velocity report
    path = config.files.path("output_gnss_vel_report", file_vars=file_vars)
    with config.files.open_path(path, create_dirs=True, mode="wt") as fid:
        rpt = Report(fid, rundate=dset.analysis["rundate"], path=path, description="GNSS analysis")
        rpt.title_page()
        rpt.write_config()
        _add_to_report(dset, rpt, figure_dir)
        rpt.markdown_to_pdf()


def _add_to_report(dset: "Dataset", rpt: "Report", figure_dir: "pathlib.PosixPath") -> None:
    """Add figures and tables to report

    Args:
        dset:        A dataset containing the data.
        rpt:         Report object.
        figure_dir:  Figure directory.
    """

    #
    # Position
    #
    rpt.add_text("\n# GNSS site velocity analysis\n\n")

    # Plot site velocity
    rpt.add_figure(
        f"{figure_dir}/plot_timeseries_enu.{FIGURE_FORMAT}",
        caption="Site velocity in topocentric coordinates (East, North, Up).",
        clearpage=True,
    )

    # Plot horizontal error
    rpt.add_figure(
        f"{figure_dir}/plot_horizontal_velocity.{FIGURE_FORMAT}",
        caption="Horizontal velocity",
        clearpage=True,
    )

    # Plot 3D timeseries
    rpt.add_figure(
        f"{figure_dir}/plot_timeseries_pdop_hv_3d.{FIGURE_FORMAT}",
        caption="Horizontal, vertical and 3D velocity of site position",
        clearpage=True,
    )

    #
    # Residual
    #
    rpt.add_text("\n# GNSS residual\n\n")

    # Add outlier table
    # MURKS: does not work at the moment. complement_with is not implemented in Dataset v3.
    # MURKS rpt.write_dataframe_to_markdown(_table_outlier_overview(dset))

    # Plot residuals
    rpt.add_figure(
        f"{figure_dir}/plot_residual.{FIGURE_FORMAT}",
        # MURKScaption="Post-fit residuals, whereby the red dots represents the rejected outliers. The histogram represent only number of residuals from kept observations.",
        caption="Post-fit residuals.",
        clearpage=True,
    )

    #
    # Dilution of precision (DOP)
    #
    if "pdop" in dset.fields:
        rpt.add_text("\n# Dilution of precision\n\n")

        # Plot DOP
        rpt.add_figure(f"{figure_dir}/plot_dop.{FIGURE_FORMAT}", caption="Dilution of precision.", clearpage=True)

    #
    # Satellite plots
    #
    rpt.add_text("\n# Satellite plots\n\n")

    rpt.add_figure(
        f"{figure_dir}/plot_number_of_satellites.{FIGURE_FORMAT}",
        caption="Number of satellites for each observation epoch",
        clearpage=False,
    )

    figure_path = figure_path = figure_dir / f"plot_satellite_overview.{FIGURE_FORMAT}"
    if figure_path.exists():  # Note: Does not exists for concatenated Datasets.
        rpt.add_figure(
            figure_path,
            caption="Overview over satellite observations. Red coloured: Observation rejected in orbit stage (e.g. unhealthy satellites, exceeding validity length, no orbit data available); Orange coloured: Observation rejected in edit stage; Green coloured: Kept observations after edit stage.",
            clearpage=False,
        )

    rpt.add_figure(f"{figure_dir}/plot_skyplot.{FIGURE_FORMAT}", caption="Skyplot", clearpage=False)

    rpt.add_figure(
        f"{figure_dir}/plot_satellite_elevation.{FIGURE_FORMAT}", caption="Satellite elevation", clearpage=True
    )

    #
    # Model parameter plots
    #
    rpt.add_text("\n# Plots of model parameters\n\n")

    for f in get_existing_fields_by_attrs(dset, FIELDS):
        rpt.add_figure(f"{figure_dir}/plot_{f.name}.{FIGURE_FORMAT}", caption=f.caption, clearpage=False)


#
# PLOT FUNCTIONS
#
def _plot_velocity(dset: "Dataset", figure_dir: "pathlib.PosixPath") -> None:
    """Plot site velocity plots

    Args:
       dset:        A dataset containing the data.
       figure_dir:  Figure directory
    """

    
    lat, lon, height = dset.site_pos.pos.llh.T
    vel_enu = np.squeeze(rotation.trs2enu(lat, lon) @  dset.site_vel[:,:,None]) 

    plot_scatter_subplots(
        x_array=dset.time.gps.datetime,
        y_arrays=[vel_enu[:, 0], vel_enu[:, 1], vel_enu[:, 2]],
        xlabel="Time [GPS]",
        ylabels=["East", "North", "Up"],
        colors=["steelblue", "darkorange", "limegreen"],
        y_units=["m/s", "m/s", "m/s"],
        figure_path=figure_dir / f"plot_timeseries_enu.{FIGURE_FORMAT}",
        opt_args={
            "figsize": (6, 6.8),
            "plot_to": "file",
            "sharey": True,
            "title": "Site velocity",
            "statistic": ["rms", "mean", "std", "min", "max", "percentile"],
        },
    )

    vel_h = np.sqrt(vel_enu[:,0] ** 2 + vel_enu[:,1] ** 2) 
    vel_v = np.absolute(vel_enu[:,2])
    #vel_3d = np.sqrt(vel_enu[:,0] ** 2 + vel_enu[:,1] ** 2 + vel_enu[:,2] ** 2)
    vel_3d = np.sqrt(dset.site_vel[:,0] ** 2 + dset.site_vel[:,1] ** 2 + dset.site_vel[:,2] ** 2)

    plot_scatter_subplots(
        x_array=dset.time.gps.datetime,
        y_arrays=[dset.pdop, vel_h, vel_v, vel_3d],
        xlabel="Time [GPS]",
        ylabels=["PDOP", "HV", "VV", "3D"],
        colors=["steelblue", "darkorange", "limegreen", "red"],
        y_units=[None, "m/s", "m/s", "m/s"],
        figure_path=figure_dir / f"plot_timeseries_pdop_hv_3d.{FIGURE_FORMAT}",
        opt_args={
            "figsize": (7, 7),
            "plot_to": "file",
            "sharey": False,
            # "title": "2D (horizontal) and 3D velocity",
            "statistic": ["rms", "mean", "std", "min", "max", "percentile"],
        },
    )

    plot_scatter_subplots(
        x_array=vel_enu[:, 0],
        y_arrays=[vel_enu[:, 1]],
        xlabel="East [m/s]",
        ylabels=["North"],
        y_units=["m/s"],
        figure_path=figure_dir / f"plot_horizontal_velocity.{FIGURE_FORMAT}",
        opt_args={
            "grid": True,
            "figsize": (6, 6),
            "histogram": "x, y",
            "histogram_binwidth": 0.002,
            "plot_to": "file",
            "title": "Horizontal velocity",
            "xlim": [-0.1, 0.1],
            "ylim": [-0.1, 0.1],
        },
    )


def _plot_residual(dset: "Dataset", figure_dir: "pathlib.PosixPath") -> None:
    """Plot residual plot

    Args:
       dset:        A dataset containing the data.
       figure_dir:  Figure directory
    """
    figure_path = figure_dir / f"plot_residual.{FIGURE_FORMAT}"
    dset_outlier = _get_outliers_dataset(dset)

    if dset_outlier == enums.ExitStatus.error:
        # NOTE: This is the case for concatencated Datasets, where "calculate" stage data are not available.
        log.warn(f"No data for calculate stage available. No outliers are plotted in {figure_path}.")
        x_arrays = [dset.time.gps.datetime]
        y_arrays = [dset.residual]
        colors = ["dodgerblue"]
    else:
        if dset_outlier.num_obs:
            x_arrays = [dset_outlier.time.gps.datetime, dset.time.gps.datetime]
            y_arrays = [dset_outlier.residual, dset.residual]
            colors = ["red", "dodgerblue"]
        else:
            log.debug("No outliers detected.")
            x_arrays = [dset.time.gps.datetime]
            y_arrays = [dset.residual]
            colors = ["dodgerblue"]

    plot(
        x_arrays=x_arrays,
        y_arrays=y_arrays,
        xlabel="Time [GPS]",
        ylabel="Post-fit residual",
        y_unit="m/s",
        colors=colors,
        figure_path=figure_path,
        opt_args={
            "figsize": (7, 4),
            "histogram": "y",
            "histogram_size": 0.8,
            "histogram_binwidth": 0.002,
            "plot_to": "file",
            "statistic": ["rms", "mean", "std", "min", "max", "percentile"],
        },
    )


def _plot_dop(dset: "Dataset", figure_dir: "pathlib.PosixPath") -> None:
    """Plot DOP

    Args:
       dset:        A dataset containing the data.
       figure_dir:  Figure directory
    """
    plot(
        x_arrays=[
            dset.time.gps.datetime,
            dset.time.gps.datetime,
            dset.time.gps.datetime,
            dset.time.gps.datetime,
            dset.time.gps.datetime,
        ],
        y_arrays=[dset.gdop, dset.pdop, dset.vdop, dset.hdop, dset.tdop],
        xlabel="Time [GPS]",
        ylabel="Dilution of precision",
        y_unit="",
        labels=["GDOP", "PDOP", "VDOP", "HDOP", "TDOP"],
        figure_path=figure_dir / f"plot_dop.{FIGURE_FORMAT}",
        opt_args={"figsize": (7, 4), "legend": True, "plot_to": "file"},
    )


def _plot_number_of_satellites(dset: "Dataset", figure_dir: "pathlib.PosixPath") -> None:
    """Plot number of satellites

    Args:
       dset:        A dataset containing the data.
       figure_dir:  Figure directory
    """

    if "num_satellite_used" not in dset.fields:
        dset.add_float(
            "num_satellite_used",
            val=gnss.get_number_of_satellites(dset.system, dset.satellite, dset.time.gps.datetime),
        )

    plot(
        x_arrays=[dset.time.gps.datetime, dset.time.gps.datetime],
        y_arrays=[dset.num_satellite_available, dset.num_satellite_used],
        xlabel="Time [GPS]",
        ylabel="Number of satellites",
        y_unit="",
        labels=["Available", "Used"],
        figure_path=figure_dir / f"plot_number_of_satellites.{FIGURE_FORMAT}",
        opt_args={"figsize": (7, 4), "legend": True, "marker": ",", "plot_to": "file", "plot_type": "plot"},
    )


def _plot_skyplot(dset: "Dataset", figure_dir: "pathlib.PosixPath") -> None:
    """Plot skyplot

    Args:
       dset:        A dataset containing the data.
       figure_dir:  Figure directory
    """

    # Convert azimuth to range 0-360 degree
    azimuth = dset.site_pos.azimuth
    idx = azimuth < 0
    azimuth[idx] = 2 * np.pi + azimuth[idx]

    # Convert zenith distance from radian to degree
    zenith_distance = np.rad2deg(dset.site_pos.zenith_distance)

    # Generate x- and y-axis data per satellite
    x_arrays = []
    y_arrays = []
    labels = []
    for sat in dset.unique("satellite"):
        idx = dset.filter(satellite=sat)
        x_arrays.append(azimuth[idx])
        y_arrays.append(zenith_distance[idx])
        labels.append(sat)

    # Plot with polar projection
    # TODO: y-axis labels are overwritten after second array plot. Why? What to do?
    plot(
        x_arrays=x_arrays,
        y_arrays=y_arrays,
        xlabel="",
        ylabel="",
        y_unit="",
        labels=labels,
        figure_path=figure_dir / f"plot_skyplot.{FIGURE_FORMAT}",
        opt_args={
            "colormap": "tab20",
            "figsize": (7, 7.5),
            "legend": True,
            "legend_ncol": 6,
            "legend_location": "bottom",
            "plot_to": "file",
            "plot_type": "scatter",
            "projection": "polar",
            "title": "Skyplot\n Azimuth [deg] / Elevation[deg]",
            "xlim": [0, 2 * np.pi],
            "ylim": [0, 90],
            "yticks": (range(0, 90, 30)),  # sets 3 concentric circles
            "yticklabels": (map(str, range(90, 0, -30))),  # reverse labels from zenith distance to elevation
        },
    )


def _plot_satellite_elevation(dset: "Dataset", figure_dir: "pathlib.PosixPath") -> None:
    """Plot satellite elevation

    Args:
       dset:        A dataset containing the data.
       figure_dir:  Figure directory
    """

    # Convert elevation from radian to degree
    elevation = np.rad2deg(dset.site_pos.elevation)

    # Limit x-axis range to rundate
    day_start, day_end = _get_day_limits(dset)

    # Generate x- and y-axis data per satellite
    x_arrays = []
    y_arrays = []
    labels = []

    for sat in dset.unique("satellite"):
        idx = dset.filter(satellite=sat)
        x_arrays.append(dset.time.gps.datetime[idx])
        y_arrays.append(elevation[idx])
        labels.append(sat)

    # Plot with scatter plot
    plot(
        x_arrays=x_arrays,
        y_arrays=y_arrays,
        xlabel="Time [GPS]",
        ylabel="Elevation [deg]",
        y_unit="",
        labels=labels,
        figure_path=figure_dir / f"plot_satellite_elevation.{FIGURE_FORMAT}",
        opt_args={
            "colormap": "tab20",
            "figsize": (7, 8),
            "legend": True,
            "legend_ncol": 6,
            "legend_location": "bottom",
            "plot_to": "file",
            "plot_type": "scatter",
            "title": "Satellite elevation",
            "xlim": [day_start, day_end],
        },
    )


def _plot_satellite_overview(dset: "Dataset", figure_dir: "pathlib.PosixPath") -> Union[None, Enum]:
    """Plot satellite observation overview

    Args:
       dset:        A dataset containing the data.
       figure_dir:  Figure directory
       
    Returns:
       Error exit status if necessary datasets could not be read
    """
    figure_path = figure_dir / f"plot_satellite_overview.{FIGURE_FORMAT}"

    # Limit x-axis range to rundate
    day_start, day_end = _get_day_limits(dset)

    # Get time and satellite data from read and orbit stage
    file_vars = {**dset.vars, **dset.analysis}
    file_vars["stage"] = "read"
    file_path = config.files.path("dataset", file_vars=file_vars)
    if file_path.exists(): 
        time_read, satellite_read = _sort_by_satellite(
            _get_dataset(dset, stage="read", systems=dset.meta["obstypes"].keys())
        )
        time_orbit, satellite_orbit = _sort_by_satellite(
            _get_dataset(dset, stage="orbit", systems=dset.meta["obstypes"].keys())
        )
        time_edit, satellite_edit = _sort_by_satellite(
            _get_dataset(dset, stage="edit", systems=dset.meta["obstypes"].keys())
        )
        
    else:
        # NOTE: This is the case for concatencated Datasets, where "read" and "edit" stage data are not available.
        log.warn(f"Read dataset does not exists: {file_path}. Plot {figure_path} can not be plotted.")
        return enums.ExitStatus.error

    # Generate plot
    plot(
        x_arrays=[time_read, time_orbit, time_edit],
        y_arrays=[satellite_read, satellite_orbit, satellite_edit],
        xlabel="Time [GPS]",
        ylabel="Satellite",
        y_unit="",
        # labels = ["Rejected in orbit stage", "Rejected in edit stage", "Kept observations"],
        colors=["red", "orange", "green"],
        figure_path=figure_path,
        opt_args={
            "colormap": "tab20",
            "figsize": (7, 6),
            "marker": "|",
            "plot_to": "file",
            "plot_type": "scatter",
            "title": "Overview over satellites",
            "xlim": [day_start, day_end],
        },
    )


def _plot_model(dset: "Dataset", figure_dir: "pathlib.PosixPath") -> None:
    """Plot model parameters

    Args:
       dset:        A dataset containing the data.
       figure_dir:  Figure directory
    """

    # Limit x-axis range to rundate
    day_start, day_end = _get_day_limits(dset)

    for f in get_existing_fields_by_attrs(dset, FIELDS):

        # Generate x- and y-axis data per satellite
        x_arrays = []
        y_arrays = []
        labels = []

        for sat in dset.unique("satellite"):
            idx = dset.filter(satellite=sat)
            x_arrays.append(dset.time.gps.datetime[idx])
            y_arrays.append(get_field_by_attrs(dset, f.attrs, f.unit)[idx])
            labels.append(sat)

        # Plot with scatter plot
        plot(
            x_arrays=x_arrays,
            y_arrays=y_arrays,
            xlabel="Time [GPS]",
            ylabel=f.ylabel,
            y_unit=f.unit,
            labels=labels,
            figure_path=figure_dir / f"plot_{f.name}.{FIGURE_FORMAT}",
            opt_args={
                "colormap": "tab20",
                "figsize": (7, 6),
                "legend": True,
                "legend_ncol": 6,
                "legend_location": "bottom",
                "plot_to": "file",
                "plot_type": "scatter",
                "statistic": ["rms", "mean", "std", "min", "max", "percentile"],
                "xlim": [day_start, day_end],
            },
        )


#
# TABLE GENERATION FUNCTIONS
#
def _table_outlier_overview(dset: "Dataset"):
    """Generate Dataframe table with overview over number of navigation messages

    Args:
        dset:      A dataset containing the data.

    Returns:
        Dataframe with satellites as indices and following columns:

        | Name        | Description                                                                                  |
        |-------------|----------------------------------------------------------------------------------------------|
        | outlier     | Number of outliers for each satellite                                                        |


        Example:

            |    |outlier | 
            |----|--------|
            | G01|      0 |
            | G02|     11 |
            | G03|      3 |
            | .. |    ... |
            | SUM|     42 |

    """
    columns = ["outlier"]
    df = pd.DataFrame(columns=columns)

    dset_outlier = _get_outliers_dataset(dset)
    if dset_outlier == enums.ExitStatus.error:
        # NOTE: This is the case for concatencated Datasets, where "calculate" stage data are not available.
        log.warn(f"No data for calculate stage available. Outliers can not be detected.")
        return df

    if dset_outlier.num_obs:
        log.debug("No outlier detected.")
        return df

    for satellite in sorted(dset.unique("satellite")):
        idx = dset_outlier.filter(satellite=satellite)
        row = [len(dset_outlier.satellite[idx])]
        df = df.append(pd.DataFrame([row], columns=columns, index=[satellite]))

    df = df.append(pd.DataFrame([[len(dset_outlier.satellite)]], columns=columns, index=["**SUM**"]))

    return df


#
# AUXILIARY FUNCTIONS
#
def _get_day_limits(dset: "Dataset") -> Tuple[datetime, datetime]:
    """Get start and end time for given run date

        Args:
            dset: A dataset containing the data.

        Returns:
            Start and end date. 
        """
    day_start = min(dset.time.datetime)
    day_end = max(dset.time.datetime)

    return day_start, day_end


def _get_outliers_dataset(dset: "Dataset") -> Union["Dataset", Enum]:
    """Get dataset with outliers

    Args:
       dset:        A dataset containing the data.

    Returns:
       Dataset with outliers or error exit status if no data for "calculate" stage are available
    """

    # Get Dataset where no outliers are rejected
    file_vars = {**dset.vars, **dset.analysis}
    file_vars["stage"] = "calculate"

    try:
        dset_complete = dataset.Dataset.read(**file_vars)
    except OSError:
        log.warn(f"Could not read dataset {config.files.path('dataset', file_vars=file_vars)}.")
        return enums.ExitStatus.error

    # Get relative complement, which corresponds to "outlier" dataset
    # dset_outliers = dset_complete.complement_with(dset, complement_by=["time", "satellite"])
    dset_outliers = dataset.Dataset(num_obs=0)  # MURKS: complement_with does not exists so far in Dataset v3.

    return dset_outliers


def _get_dataset(dset: "Dataset", stage: str, systems: Union[List[str], None] = None) -> Union["Dataset", Enum]:
    """Get dataset for given stage

    Args:
       dset:        A dataset containing the data.
       systems:     List with GNSS identifiers (e.g. E, G, ...)

    Returns:
       Dataset for given stage or error exit status if dataset could not be read
    """

    # Get Dataset
    # TODO: "label" should have a default value.
    file_vars = {**dset.vars, **dset.analysis}
    file_vars["stage"] = stage
    try:
        dset_out = dataset.Dataset.read(**file_vars)
    except OSError:
        log.warn("Could not read dataset {config.files.path('dataset', file_vars=file_vars)}.")
        return enums.ExitStatus.error

    # Reject not defined GNSS observations
    if systems:
        systems = [systems] if isinstance(systems, str) else systems
        keep_idx = np.zeros(dset_out.num_obs, dtype=bool)
        for sys in systems:
            idx = dset_out.filter(system=sys)
            keep_idx[idx] = True
        dset_out.subset(keep_idx)

    return dset_out


def _sort_by_satellite(dset: "Dataset") -> Tuple[List[datetime], List[str]]:
    """Sort time and satellite fields of dataset by satellite order

    Args: 
       dset:        A dataset containing the data.

    Returns:
        Tuple with ordered time array and satellite array
    """
    time = []
    satellite = []
    for sat in sorted(dset.unique("satellite"), reverse=True):
        idx = dset.filter(satellite=sat)
        time.extend(dset.time.gps.datetime[idx])
        satellite.extend(dset.satellite[idx])

    return time, satellite
