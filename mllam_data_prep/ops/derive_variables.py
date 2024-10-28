import dask.array as da
import numpy as np
import xarray as xr


def derive_toa_radiation(ds):
    """
    Derive approximate TOA radiation (instantaneous values [W*m**-2])

    Parameters
    ----------
    ds : xr.Dataset
        The dataset with variables needed to derive TOA radiation

    Returns
    -------
    ds: xr.Dataset
        The dataset with TOA radiation added
    """

    # Need to construct a new dataset with chunks since
    # lat and lon are coordinates and are therefore eagerly loaded
    ds_dict = {}
    ds_dict["lat"] = (list(ds.lat.dims), da.from_array(ds.lat.values, chunks=(-1, -1)))
    ds_dict["lon"] = (list(ds.lon.dims), da.from_array(ds.lon.values, chunks=(-1, -1)))
    ds_dict["t"] = (list(ds.time.dims), da.from_array(ds.time.values, chunks=(10)))
    ds_chunks = xr.Dataset(ds_dict)

    # Calculate TOA radiation
    toa_radiation = calc_toa_radiation(ds_chunks)

    # Assign to the dataset
    ds = ds.assign(toa_radiation=toa_radiation)

    return ds


def calc_toa_radiation(ds):
    """
    Function for calculation top-of-the-atmosphere radiation

    Parameters
    ----------
    ds : xr.Dataset
        The dataset with variables needed to derive TOA radiation

    Returns
    -------
    toa_radiation: xr.DataArray
        TOA radiation data-array
    """
    # Solar constant
    E0 = 1366  # W*m**-2

    day = ds.t.dt.dayofyear
    hr_utc = ds.t.dt.hour

    # Eq. 1.6.1a in Solar Engineering of Thermal Processes 4th ed.
    dec = np.pi / 180 * 23.45 * np.sin(2 * np.pi * (284 + day) / 365)

    hr_lst = hr_utc + ds.lon / 15
    hr_angle = 15 * (hr_lst - 12)

    # Eq. 1.6.2 with beta=0 in Solar Engineering of Thermal Processes 4th ed.
    cos_sza = np.sin(ds.lat * np.pi / 180) * np.sin(dec) + np.cos(
        ds.lat * np.pi / 180
    ) * np.cos(dec) * np.cos(hr_angle * np.pi / 180)

    # Where TOA radiation is negative, set to 0
    toa_radiation = xr.where(E0 * cos_sza < 0, 0, E0 * cos_sza)

    return toa_radiation


def get_variables_for_deriving_toa_radiation():
    """
    Get list of variables needed for the TOA radiation calculation
    """
    return ["lat", "lon", "time"]
