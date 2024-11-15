import importlib
import sys

import dask.array as da
import numpy as np
import xarray as xr
from loguru import logger


def derive_variables(fp, derived_variables):
    """
    Load the dataset, and derive the specified variables

    Parameters
    ---------
    fp : str
        Filepath to the source dataset, for example the path to a zarr dataset
        or a netCDF file (anything that is supported by `xarray.open_dataset` will work)
    derived_variables: dict
        Dictionary with the variables to derive with keys as the variable names and
        values with entries for kwargs and function to be used to derive them

    Returns
    -------
    ds : xr.Dataset
        Dataset with derived variables included
    """
    logger.info("Deriving variables")

    try:
        ds = xr.open_zarr(fp)
    except ValueError:
        ds = xr.open_dataset(fp)

    ds_subset = xr.Dataset()
    ds_subset.attrs.update(ds.attrs)
    # Iterate derived variables
    for _, derived_variable in derived_variables.items():
        required_variables = derived_variable.kwargs
        function_name = derived_variable.function
        # Create the input dataset containing the required variables to derive
        # the specified variable
        ds_input = ds[required_variables.keys()]
        kwargs = {v: ds_input[v] for v in required_variables.values()}
        # Get the function to be used to derive the variable
        func = get_derived_variable_function(function_name)
        # Calculate the derived variable
        derived_field = func(**kwargs)
        # Add the derived variable(s) to the subsetted dataset
        ds_subset[derived_field.name] = derived_field

    return ds


def get_derived_variable_function(function_namespace):
    """
    Function for returning the function to be used to derive
    the specified variable.

    1. Check if the function to use is in globals()
    2. If it is in globals then call it
    3. If it isn't in globals() then import the necessary module
        before calling it
    """
    # Get the name of the calling module
    calling_module = globals()["__name__"]

    if "." in function_namespace:
        # If the function name is a full namespace, get module and function names
        module_name, function_name = function_namespace.rsplit(".", 1)

        # Check if the module_name is pointing to here (the calling module),
        # and if it does then use globals() to get the function otherwise
        # import the correct module and get the correct function
        if module_name == calling_module:
            function = globals().get(function_name)
        else:
            # Check if the module is already imported
            if module_name in sys.modules:
                module = module_name
            else:
                module = importlib.import_module(module_name)

            # Get the function from the module
            function = getattr(module, function_name)
    else:
        # If function name only get it from the calling module (here)
        function = globals().get(function_namespace)
        if not function:
            raise TypeError(
                f"Function '{function_namespace}' was not found in '{calling_module}'."
                f" Check that you have specified the correct function name"
                " and/or that you have defined the full function namespace if you"
                " want to use a function defined outside of of the current module"
                f" '{calling_module}'."
            )

    return function


def derive_toa_radiation(lat, lon, time):
    """
    Derive approximate TOA radiation (instantaneous values [W*m**-2])

    Parameters
    ----------
    lat : xr.DataArray
        Latitude values
    lon : xr.DataArray
        Longitude values
    time : xr.DataArray
        Time

    Returns
    -------
    toa_radiation: xr.DataArray
        TOA radiation data-array
    """
    logger.info("Calculating top-of-atmosphere radiation")

    # Need to construct a new dataset with chunks since
    # lat and lon are coordinates and are therefore eagerly loaded
    ds_dict = {}
    ds_dict["lat"] = (list(lat.dims), da.from_array(lat.values, chunks=(-1, -1)))
    ds_dict["lon"] = (list(lon.dims), da.from_array(lon.values, chunks=(-1, -1)))
    ds_dict["t"] = (list(time.dims), da.from_array(time.values, chunks=(10)))
    ds_chunks = xr.Dataset(ds_dict)

    # Calculate TOA radiation
    toa_radiation = calc_toa_radiation(ds_chunks)

    if isinstance(toa_radiation, xr.DataArray):
        # Add attributes
        toa_radiation.name = "toa_radiation"

    return toa_radiation


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


def derive_hour_of_day(ds):
    """
    Derive hour of day features with a cyclic encoding

    Parameters
    ----------
    ds : xr.Dataset
        The dataset with variables needed to derive hour of day

    Returns
    -------
    ds: xr.Dataset
        The dataset with hour of day added
    """
    logger.info("Calculating hour of day")

    # Get the hour of the day
    hour_of_day = ds.time.dt.hour

    # Cyclic encoding of hour of day
    hour_of_day_cos, hour_of_day_sin = cyclic_encoding(hour_of_day, 24)

    # Assign to the dataset
    ds = ds.assign(hour_of_day_sin=hour_of_day_sin)
    ds = ds.assign(hour_of_day_cos=hour_of_day_cos)

    return ds


def derive_day_of_year(ds):
    """
    Derive day of year features with a cyclic encoding

    Parameters
    ----------
    ds : xr.Dataset
        The dataset with variables needed to derive day of year

    Returns
    -------
    ds: xr.Dataset
        The dataset with day of year added
    """
    logger.info("Calculating day of year")

    # Get the day of year
    day_of_year = ds.time.dt.dayofyear

    # Cyclic encoding of day of year - use 366 to include leap years!
    day_of_year_cos, day_of_year_sin = cyclic_encoding(day_of_year, 366)

    # Assign to the dataset
    ds = ds.assign(day_of_year_sin=day_of_year_sin)
    ds = ds.assign(day_of_year_cos=day_of_year_cos)

    return ds


def cyclic_encoding(da, da_max):
    """
    Cyclic encoding of data

    Parameters
    ----------
    da : xr.DataArray
        xarray data-array that should be cyclically encoded
    da_max: int/float
        Maximum possible value of input data-array

    Returns
    -------
    da_cos: xr.DataArray
        Cosine part of cyclically encoded input data-array
    da_sin: xr.DataArray
        Sine part of cyclically encoded input data-array
    """

    da_sin = np.sin((da / da_max) * 2 * np.pi)
    da_cos = np.cos((da / da_max) * 2 * np.pi)

    return da_cos, da_sin