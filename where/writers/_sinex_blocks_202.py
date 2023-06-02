"""Contruct data blocks for SINEX files from a dataset

Description:
------------

Construct blocks for the the SINEX format version 2.02 described in [1]_.

@todo: print content in blocks for Site Code other than stations
@todo: Point code. What is it? Hardcoded to A
@todo: file comment block
@todo: content in non-VLBI blocks


References:
-----------

.. [1] SINEX Format https://www.iers.org/IERS/EN/Organization/AnalysisCoordinator/SinexFormat/sinex.html


"""
# Standard library imports
from datetime import datetime
from functools import lru_cache

# Third party imports
import numpy as np

# Midgard imports
from midgard.math.unit import Unit
from midgard.data.time import Time

# Where imports
import where
from where import apriori
from where.lib import config
from where.lib import log
from where.data import time
from where.lib import util

_PARAMS = dict(
    site_pos={"x": "STAX", "y": "STAY", "z": "STAZ"},
    src_dir={"ra": "RS_RA", "dec": "RS_DE"},
    eop_nut={"x": "NUT_X", "y": "NUT_Y"},
    eop_pm={"xp": "XPO", "yp": "YPO"},
    eop_pm_rate={"dxp": "XPOR", "dyp": "YPOR"},
    eop_dut1={"dut1": "UT"},
    eop_lod={"lod": "LOD"},
    trop_wet={},
)

_TECH = {"comb": "C", "doris": "D", "slr": "L", "llr": "M", "gnss": "P", "vlbi": "R"}


class SinexBlocks:
    def __init__(self, dset, fid):
        self.dset = dset
        self.fid = fid
        self.tech_prefix = dset.meta["tech"] + "_"
        self._create_state_vector()

    def _create_state_vector(self):
        stations = self.dset.unique("station")
        parameters = self.dset.meta["normal equation"]["names"]
        self.ids = {sta: self.dset.meta["station"][sta].get("site_id", "----") for sta in stations}
        try:
            sources1 = set(self.dset.unique("source"))
            sources2 = {param[13:].rsplit("_", maxsplit=1)[0] for param in parameters if param.startswith("vlbi_src_dir")}
            self.sources = sources1 | sources2
            self.ids.update({src: "{:0>4}".format(i) for i, src in enumerate(self.sources, start=1)})
        except AttributeError:
            pass
        self.ids.update({"----": "----"})

        self.state_vector = list()
        for parameter in parameters:
            partial_type, name = parameter.split("-", maxsplit=1)
            partial_type = partial_type.replace(self.tech_prefix, "")
            name = name.rsplit("_", maxsplit=1)

            if len(name) == 2:
                split_name, _, epoch = name[1].partition(":")
                ident, name = (name[0], split_name)
            elif name[0].split(":", maxsplit=1)[0] in self.ids:
                split_name, _, epoch = name[0].partition(":")
                ident, name = (split_name, split_name)
            else:
                split_name, _, epoch = name[0].partition(":")
                ident, name = ("----", split_name)

            self.state_vector.append({"type": partial_type, "id": ident, "partial": name, "epoch": epoch})

        for e in self.state_vector:
            if e["type"] == "trop_wet":
                _PARAMS["trop_wet"][e["partial"]] = "TROWET"   

    @property
    @lru_cache()
    def _analyst_info(self):
        """Information about analyst

        Uses analyst field in config. If no value is given, current user is used as back-up.
        """
        analyst = config.tech.get("analyst", section="sinex", default="").str
        if analyst:
            return util.get_user_info(analyst)
        else:
            return util.get_user_info()

    def header_line(self):
        """Mandatory header line
        """
        now = time.Time(datetime.now(), scale="utc", fmt="datetime").yydddsssss
        start = self.dset.time.min.yydddsssss
        end = self.dset.time.max.yydddsssss

        file_agency = config.tech.sinex.file_agency.str.upper()
        data_agency = config.tech.sinex.data_agency.str.upper()

        num_params = len(self.dset.meta["normal equation"]["names"])
        constraint = "2"
        self.fid.write(
            f"%=SNX 2.02 {file_agency:<3} {now} {data_agency:<3} {start} {end} R {num_params:>5} {constraint} S E C \n"
        )

    def end_line(self):
        """Mandatory end of file line
        """
        self.fid.write("%ENDSNX\n")

    def write_block(self, block_name, *args):
        """Call the given block so it writes itself"""
        try:
            block_func = getattr(self, block_name)
        except AttributeError:
            log.error(f"Sinex block '{block_name}' is unknown")
            return

        block_func(*args)

    def file_reference(self):
        """Mandatory block
        """
        self.fid.write("+FILE/REFERENCE\n")
        if "inst_name" not in self._analyst_info:
            log.error("Add information about user and institute in configuration. Left blank in Sinex-file")
        self.fid.write(f" {'DESCRIPTION':<18} {self._analyst_info.get('inst_name', ''):<60}\n")
        self.fid.write(f" {'OUTPUT':<18} {'Daily VLBI solution, Normal equations':<60}\n")
        self.fid.write(f" {'ANALYST':<18} {self._analyst_info.get('email', ''):<60}\n")
        contacts = config.tech.get("contacts", section="sinex", default=where.__contact__).list
        for contact in contacts:
            self.fid.write(f" {'CONTACT':<18} {contact:<60}\n")
        self.fid.write(f" {'SOFTWARE':<18} {f'Where v{where.__version__}':<60}\n")
        # self.fid.write(' {'HARDWARE':<18} {'---':<60}\n')
        input_string = f"{self.dset.meta['input']['type']} {self.dset.meta['input']['file']}"
        self.fid.write(f" {'INPUT':<18} {input_string:<60}\n")
        self.fid.write("-FILE/REFERENCE\n")

    def file_comment(self):
        """Optional block
        """
        self.fid.write("+FILE/COMMENT\n")
        self.fid.write(" Analysis configuration: \n")
        cfg_str = config.tech.as_str(width=79, key_width=30).split("\n")
        for line in cfg_str[1:]:
            self.fid.write(f" {line:<79}\n")
        self.fid.write("-FILE/COMMENT\n")

    def input_history(self):
        """Recommended block

        Refers to other SINEX files used to generate this solution
        """
        self.fid.write("+INPUT/HISTORY\n")
        self.fid.write("-INPUT/HISTORY\n")

    def input_files(self):
        """Optional block

        Linked with _input_history.
        """
        self.fid.write("+INPUT/FILES\n")
        self.fid.write("-INPUT/FILES\n")

    def input_acknowledgements(self):
        """Optional block
        """
        self.fid.write("+INPUT/ACKNOWLEDGEMENTS\n")
        institute = self._analyst_info.get("inst_abbreviation", "")
        file_agency = config.tech.get("file_agency", section="sinex", default="").str
        data_agency = config.tech.get("file_agency", section="sinex", default="").str
        agencies = sorted(a for a in {institute, file_agency, data_agency} if a)
        for agency in agencies:
            name = (config.where.get(agency.lower(), section="institution_info", default="").as_list(", *") + [""])[0]
            if not name:
                log.warn(f"Unknown institution {agency!r}. Add information about {agency!r} to configuration")
            self.fid.write(f" {agency:<3} {name:<75}\n")
        self.fid.write("-INPUT/ACKNOWLEDGEMENTS\n")

    def nutation_data(self):
        """Mandatory for VLBI
        """
        self.fid.write("+NUTATION/DATA\n")
        self.fid.write(
            " {:<8} {:<70}\n".format("IAU2000A", "SOFA routines. IAU2006/2000A, CIO based, using X,Y series")
        )
        self.fid.write("-NUTATION/DATA\n")

    def precession_data(self):
        """Mandatory for VLBI
        """
        self.fid.write("+PRECESSION/DATA\n")
        self.fid.write(
            " {:<8} {:<70}\n".format("IAU2006", "SOFA routines. IAU2006/2000A, CIO based, using X,Y series")
        )
        self.fid.write("-PRECESSION/DATA\n")

    def source_id(self):
        """Mandatory for VLBI

        Content:
        *CODE IERS des ICRF designation Comments
        """
        source_names = apriori.get("vlbi_source_names")
        crf = apriori.get("crf", time=self.dset.time)
        self.fid.write("+SOURCE/ID\n")
        self.fid.write("*Code IERS nam ICRF designator  number of observations per source \n")
        for iers_name in self.sources:
            # Sourcenames are saved internally with the letters "dot" instead of the character "." which have a special meaning in Where
            real_iers_name = iers_name.replace("dot", ".")
            if real_iers_name in source_names:
                icrf_name = source_names[real_iers_name]["icrf_name_long"]
            else:
                icrf_name = crf[real_iers_name].meta["icrf_name"] if "icrf_name" in crf[real_iers_name].meta else ""
            if not icrf_name:
                log.warn(f"Missing ICRF designation for {real_iers_name}")
            num_obs = self.dset.num(source=iers_name)
            self.fid.write(" {:0>4} {:<8} {:<16} {:04}\n".format(self.ids[iers_name], real_iers_name, icrf_name, num_obs))
        self.fid.write("-SOURCE/ID\n")

    def site_id(self):
        """Mandatory block.

        Content:
        *Code PT Domes____ T Station description___ Approx_lon_ Approx_lat_ App_h__
        """
        self.fid.write("+SITE/ID\n")
        self.fid.write("*Code PT Domes____ T Station description___ Approx_lon_ Approx_lat_ App_h__\n")
        for sta in self.dset.unique("station"):
            site_id = self.dset.meta["station"][sta]["site_id"]
            domes = self.dset.meta["station"][sta]["domes"]
            marker = self.dset.meta["station"][sta]["marker"]
            height = self.dset.meta["station"][sta]["height"]
            description = self.dset.meta["station"][sta]["description"][0:22]
            long_deg, long_min, long_sec = Unit.rad_to_dms(self.dset.meta["station"][sta]["longitude"])
            lat_deg, lat_min, lat_sec = Unit.rad_to_dms(self.dset.meta["station"][sta]["latitude"])

            self.fid.write(
                " {} {:>2} {:5}{:4} {:1} {:<22} {:>3.0f} {:>2.0f} {:4.1f} {:>3.0f} {:>2.0f} {:4.1f} {:7.1f}"
                "\n".format(
                    site_id,
                    "A",
                    domes,
                    marker,
                    _TECH[self.dset.meta["tech"]],
                    description,
                    (long_deg + 360) % 360,
                    long_min,
                    long_sec,
                    lat_deg,
                    lat_min,
                    lat_sec,
                    height,
                )
            )
        self.fid.write("-SITE/ID\n")

    def site_data(self):
        """Optional block
        """
        self.fid.write("+SITE/DATA\n")
        self.fid.write("-SITE/DATA\n")

    def site_receiver(self):
        """Mandatory for GNSS
        """
        self.fid.write("+SITE/RECEIVER\n")
        self.fid.write("-SITE/RECEIVER\n")

    def site_antenna(self):
        """Mandatory for GNSS
        """
        self.fid.write("+SITE/ANTENNA\n")
        self.fid.write("-SITE/ANTENNA\n")

    def site_gps_phase_center(self):
        """Mandatory for GNSS
        """
        self.fid.write("+SITE/GPS_PHASE_CENTER\n")
        self.fid.write("-SITE/GPS_PHASE_CENTER\n")

    def site_gal_phase_center(self):
        """Mandatory for Galileo
        """
        self.fid.write("+SITE/GAL_PHASE_CENTER\n")
        self.fid.write("-SITE/GAL_PHASE_CENTER\n")

    def site_eccentricity(self):
        """Mandatory
        """
        ecc = apriori.get("eccentricity", rundate=self.dset.analysis["rundate"])
        self.fid.write("+SITE/ECCENTRICITY\n")
        self.fid.write("*Code PT SBIN T Data_Start__ Data_End____ typ Apr --> Benchmark (m)_____\n")

        fieldnames = config.tech.eccentricity.identifier.list
        keys = np.array([self.dset.unique(f, sort=False) for f in fieldnames]).T

        for sta, key in zip(self.dset.unique("station"), keys):
            site_id = self.dset.meta["station"][sta]["site_id"]

            self.fid.write(
                " {:4} {:>2} {:>4} {:1} {:12} {:12} {:3} {: 8.4f} {: 8.4f} {: 8.4f}\n"
                "".format(
                    site_id,
                    "A",
                    1,
                    _TECH[self.dset.meta["tech"]],
                    self.dset.time.yydddsssss[0],
                    self.dset.time.yydddsssss[-1],
                    ecc[tuple(key)]["coord_type"],
                    ecc[tuple(key)]["vector"][0],
                    ecc[tuple(key)]["vector"][1],
                    ecc[tuple(key)]["vector"][2],
                )
            )
        self.fid.write("-SITE/ECCENTRICITY\n")

    def satellite_id(self):
        """Recommended for GNSS
        """
        self.fid.write("+SATELLITE/ID\n")
        self.fid.write("-SATELLITE/ID\n")

    def satellite_phase_center(self):
        """Mandatory for GNSS if satellite antenna offsets are not estimated
        """
        self.fid.write("+SATELLITE/PHASE_CENTER\n")
        self.fid.write("-SATELLITE/PHASE_CENTER\n")

    def solution_epochs(self):
        """Mandatory
        """
        self.fid.write("+SOLUTION/EPOCHS\n")
        self.fid.write("*Code PT SBIN T Data_start__ Data_end____ Mean_epoch__\n")
        for site_id in self.dset.unique("site_id"):
            self.fid.write(
                " {:4} {:>2} {:>4} {:1} {:12} {:12} {:12}\n"
                "".format(
                    site_id,
                    "A",
                    1,
                    _TECH[self.dset.meta["tech"]],
                    self.dset.time.yydddsssss[0],
                    self.dset.time.yydddsssss[-1],
                    self.dset.time.mean.yydddsssss,
                )
            )
        self.fid.write("-SOLUTION/EPOCHS\n")

    def bias_epochs(self):
        """Mandatory if bias parameters are included
        """
        self.fid.write("+BIAS/EPOCHS\n")
        self.fid.write("-BIAS/EPOCHS\n")

    def solution_statistics(self):
        """Recommended if available
        """
        self.fid.write("+SOLUTION/STATISTICS\n")
        self.fid.write("* Units for WRMS: meter\n")
        self.fid.write(" {:<30} {:>22.15f}\n".format("NUMBER OF OBSERVATIONS", self.dset.num_obs))
        self.fid.write(
            " {:<30} {:>22.15f}\n".format("NUMBER OF UNKNOWNS", self.dset.meta["statistics"]["number of unknowns"])
        )
        self.fid.write(
            " {:<30} {:>22.15f}\n".format(
                "SQUARE SUM OF RESIDUALS (VTPV)", self.dset.meta["statistics"]["square sum of residuals"]
            )
        )
        self.fid.write(
            " {:<30} {:>22.15f}\n".format(
                "NUMBER OF DEGREES OF FREEDOM", self.dset.meta["statistics"]["degrees of freedom"]
            )
        )
        self.fid.write(
            " {:<30} {:>22.15f}\n".format("VARIANCE FACTOR", self.dset.meta["statistics"]["variance factor"])
        )
        self.fid.write(
            " {:<30} {:>22.15f}\n".format(
                "WEIGHTED SQUARE SUM OF O-C", self.dset.meta["statistics"]["weighted square sum of o-c"]
            )
        )
        if self.dset.meta["tech"] == "P":
            self.fid.write(" {:<30} {:>22.15f}\n".format("SAMPLING INTERVAL (SECONDS)", 0))
            self.fid.write(" {:<30} {:>22.15f}\n".format("PHASE MEASUREMENTS SIGMA", 0))
            self.fid.write(" {:<30} {:>22.15f}\n".format("CODE MEASUREMENTS SIGMA", 0))
        self.fid.write("-SOLUTION/STATISTICS\n")

    def solution_estimate(self):
        """Mandatory
        """
        self.fid.write("+SOLUTION/ESTIMATE\n")
        self.fid.write("*Index Type__ CODE PT SOLN Ref_epoch___ Unit S Total__value________ _Std_dev___\n")
        sol_id = 1
        for i, param in enumerate(self.state_vector, start=1):
            point_code = "A" if param["type"] == "site_pos" else "--"
            try:
                param_type = _PARAMS[param["type"]][param["partial"]]
                if param["epoch"]:
                    time = Time(param["epoch"], scale="utc", fmt="isot")
                    ref_epoch = time.yydddsssss
                else:
                    time = self.dset.time.mean
                    ref_epoch = time.yydddsssss
            except KeyError:
                continue

            param_unit = self.dset.meta["normal equation"]["unit"][i - 1]
            value = self.dset.meta["normal equation"]["solution"][i - 1] + self._get_apriori_value(param, param_unit, time)
            if self.dset.meta["normal equation"]["covariance"][i - 1][i - 1] < 0:
                log.error(
                    "Negative covariance ({})for {} {}".format(
                        self.dset.meta["normal equation"]["covariance"][i - 1][i - 1],
                        param_type,
                        self.dset.meta["normal equation"]["names"][i - 1],
                    )
                )
            value_sigma = np.sqrt(self.dset.meta["normal equation"]["covariance"][i - 1][i - 1])
            self.fid.write(
                " {:>5} {:6} {:4} {:>2} {:>4} {:12} {:4} {:1} {: 20.14e} {:11.5e}\n"
                "".format(
                    i,
                    param_type,
                    self.ids[param["id"]],
                    point_code,
                    sol_id,
                    ref_epoch,
                    param_unit,
                    2,
                    value,
                    value_sigma,
                )
            )
        self.fid.write("-SOLUTION/ESTIMATE\n")

    def solution_apriori(self):
        """Mandatory
        """
        self.fid.write("+SOLUTION/APRIORI\n")
        self.fid.write("*Index Type__ CODE PT SOLN Ref_epoch___ Unit S Apriori_value________ _Std_dev___\n")
        sol_id = 1

        for i, param in enumerate(self.state_vector, start=1):
            point_code = "A" if param["type"] == "site_pos" else "--"
            try:
                param_type = _PARAMS[param["type"]][param["partial"]]
                if param["epoch"]:
                    time = Time(param["epoch"], scale="utc", fmt="isot")
                    ref_epoch = time.yydddsssss
                else:
                    time = None
                    ref_epoch = self.dset.time.mean.yydddsssss
            except KeyError:
                continue
            
            param_unit = self.dset.meta["normal equation"]["unit"][i - 1]
            value = self._get_apriori_value(param, param_unit, time)
            self.fid.write(
                " {:>5} {:6} {:4} {:>2} {:>4} {:12} {:4} {:1} {: 20.14e} {:11.5e}\n"
                "".format(
                    i,
                    param_type,
                    self.ids[param["id"]],
                    point_code,
                    sol_id,
                    ref_epoch,
                    param_unit,
                    2,
                    value,
                    0,
                )
            )
        self.fid.write("-SOLUTION/APRIORI\n")

    def solution_matrix_estimate(self, matrix_type, structure):
        """Mandatory

        Matrix type can be three values:
            CORR - correlations
            COVA - covariance
            INFO - inverse covariance

        Structure can have two values:
            U - upper triangular matrix
            L - lower triangular matrix
        """
        self.fid.write("+SOLUTION/MATRIX_ESTIMATE {:1} {:4}\n".format(structure, matrix_type))
        self.fid.write("-SOLUTION/MATRIX_ESTIMATE {:1} {:4}\n".format(structure, matrix_type))

    def solution_matrix_apriori(self, matrix_type, structure):
        """Mandatory

         Matrix type can be three values:
            CORR - correlations
            COVA - covariance
            INFO - inverse covariance

        Structure can have two values:
            U - upper triangular matrix
            L - lower triangular matrix
        """
        self.fid.write("+SOLUTION/MATRIX_APRIORI {:1} {:4}\n".format(structure, matrix_type))
        self.fid.write("-SOLUTION/MATRIX_APRIORI {:1} {:4}\n".format(structure, matrix_type))

    def solution_normal_equation_vector(self):
        """Mandatory for normal equations
        """
        self.fid.write("+SOLUTION/NORMAL_EQUATION_VECTOR\n")
        sol_id = 1
        constraint = 2  # TODO
        self.fid.write("*Index Type__ CODE PT SOLN _Ref_Epoch__ Unit S Total_value__________\n")
        for i, param in enumerate(self.state_vector, start=1):
            point_code = "A" if param["type"] == "site_pos" else "--"
            try:
                param_type = _PARAMS[param["type"]][param["partial"]]
                if param["epoch"]:
                    ref_epoch = Time(param["epoch"], scale="utc", fmt="isot").yydddsssss
                else:
                    ref_epoch = self.dset.time.mean.yydddsssss
            except KeyError:
                continue
            param_unit = self.dset.meta["normal equation"]["unit"][i - 1]
            self.fid.write(
                " {:>5} {:6} {:4} {:>2} {:>4} {:12} {:4} {:1} {: 20.14e}\n"
                "".format(
                    i,
                    param_type,
                    self.ids[param["id"]],
                    point_code,
                    sol_id,
                    ref_epoch,
                    param_unit,
                    constraint,
                    self.dset.meta["normal equation"]["vector"][i - 1],
                )
            )
        self.fid.write("-SOLUTION/NORMAL_EQUATION_VECTOR\n")

    def solution_normal_equation_matrix(self, structure):
        """Mandatory for normal equations

        Structure can have two values:
            U - upper triangular matrix
            L - lower triangular matrix

        """
        mat = self.dset.meta["normal equation"]["matrix"]
        self.fid.write("+SOLUTION/NORMAL_EQUATION_MATRIX {:1}\n".format(structure))
        self.fid.write("*Para1 Para2 Para2+0______________ Para2+1______________ Para2+2______________\n")
        for i in range(len(mat)):
            for j in range(i, len(mat), 3):
                if j + 1 == len(mat):
                    self.fid.write(" {:5} {:5} {: 20.14e}\n".format(i + 1, j + 1, mat[i][j]))
                elif j + 2 == len(mat):
                    self.fid.write(" {:5} {:5} {: 20.14e} {: 20.14e}\n".format(i + 1, j + 1, mat[i][j], mat[i][j + 1]))
                else:
                    self.fid.write(
                        " {:5} {:5} {: 20.14e} {: 20.14e} {: 20.14e}\n".format(
                            i + 1, j + 1, mat[i][j], mat[i][j + 1], mat[i][j + 2]
                        )
                    )
        self.fid.write("-SOLUTION/NORMAL_EQUATION_MATRIX {:1}\n".format(structure))

    def _get_apriori_value(self, param, param_unit, time=None):
        if time is None:
            time = self.dset.time.utc.mean
        if param["type"] == "site_pos":
            trf = apriori.get("trf", time=time)
            pos = trf[self.ids[param["id"]]].pos.trs
            return getattr(pos, param["partial"])

        if param["type"] == "src_dir":
            crf = apriori.get("crf", time=self.dset.time)
            # Sourcenames are saved internally with the letters "dot" instead of the character "." which have a special meaning in Where
            src = crf[param["id"].replace("dot",".")]
            if param["partial"] == "ra":
                pos = src.pos.right_ascension
            elif param["partial"] == "dec":
                pos = src.pos.declination
            return pos

        if param["type"] == "eop_nut":
            eop = apriori.get("eop", time=time, models=())
            if param["partial"] == "x":
                return eop.convert_to("dx", param_unit)
            elif param["partial"] == "y":
                return eop.convert_to("dy", param_unit)
        if param["type"] == "eop_pm":
            eop = apriori.get("eop", time=time, models=())
            if param["partial"] == "xp":
                return eop.convert_to("x", param_unit)
            elif param["partial"] == "yp":
                return eop.convert_to("y", param_unit)
        if param["type"] == "eop_pm_rate":
            eop = apriori.get("eop", time=time, models=())
            if param["partial"] == "dxp":
                return eop.convert_to("x_rate", param_unit)
            elif param["partial"] == "dyp":
                return eop.convert_to("y_rate", param_unit)
        if param["type"] == "eop_dut1":
            eop = apriori.get("eop", time=time, models=("rg_zont2"))
            return eop.convert_to("ut1_utc", param_unit)
        if param["type"] == "eop_lod":
            eop = apriori.get("eop", time=time, models=())
            return -1 * eop.convert_to("ut1_utc_rate", param_unit + "/day")
        if param["type"] == "trop_wet":
            from where.models.delay import troposphere_radio
            lat = self.dset.meta[param["id"]]["latitude"]
            lon = self.dset.meta[param["id"]]["longitude"]
            height = self.dset.meta[param["id"]]["height"]
            zenith_distance = np.nan
            _, temp, e, tm, lambd = troposphere_radio.meteorological_data(param["id"], lat, lon, height, time)
            zwd = troposphere_radio.zenith_wet_delay(param["id"], lat, lon, height, time, temp, e, tm, lambd)
            return zwd
        return 0
