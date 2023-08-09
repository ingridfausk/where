"""Removes observation epochs of unhealthy GNSS satellites.

Description:
------------
Remove observations epochs for satellites, which are related to unhealthy GNSS broadcast ephemeris

"""
# Standard library imports
from typing import Union

# Third party imports
import numpy as np

# Midgard imports
from midgard.dev import plugins

# Where imports
from where import apriori
from where.lib import log


@plugins.register
def gnss_ignore_unhealthy_satellite(
                        dset: "Dataset", 
                        orbit: Union["AprioriOrbit", None] = None, 
                        dset_brdc_idx: Union[None, np.ndarray] = None,
) -> np.ndarray:
    """Remove observations epochs for satellites, which are related to unhealthy GNSS broadcast ephemeris

    If a satellite is set to unhealthy in one of the given broadcast ephemeris blocks, then the related satellite 
    observation epochs are removed. 

    The definition of the satellite vehicle health flags depends on GNSS:
        - GPS: see section 20.3.3.3.1.4 in :cite:`is-gps-200h`
        - Galileo: see section 5.1.9.3 in :cite:`galileo-os-sis-icd`
        - BeiDou: see section 5.2.4.6 in :cite:`bds-sis-icd`
        - QZSS: see section 4.1.2.3 in :cite:`is-qzss-pnt-001`
        - IRNSS: see section 6.2.1.6 in :cite:`irnss-icd-sps`

    Args:
        dset (Dataset):   A Dataset containing model data.
        orbit:            Apriori orbit object containing broadcast orbit data
        dset_brdc_idx:    Broadcast ephemeris block indices for given observation epochs. Should be used together with
                          'orbit' argument.

    Returns:
        numpy.ndarray:    Array containing False for observations to throw away
    """
    # Get signal health status information from GNSS broadcast orbits
    if not orbit: 
        orbit = apriori.get(
            "orbit",
            rundate=dset.analysis["rundate"],
            station=dset.vars["station"],
            system=tuple(dset.unique("system")),
            apriori_orbit="broadcast",
        )
    remove_idx = orbit.signal_health_status(dset) > 0

    unhealthy_satellites = sorted(set(dset.satellite[remove_idx]))
    log.info(f"Discarding observations for unhealthy satellites: {', '.join(unhealthy_satellites)}")

    return ~remove_idx
