import re
import shutil
import tempfile
from pathlib import Path

import pytest

import mllam_data_prep as mdp

HEIGHT_LEVEL_TEST_SECTION = """\
inputs:
  danra_height_levels:
    path: https://object-store.os-api.cci1.ecmwf.int/mllam-testdata/danra_cropped/v0.2.0/height_levels.zarr
    dims: [time, x, y, altitude]
    variables:
      u:
        altitude:
          values: [100, 50,]
          units: m
      v:
        altitude:
          values: [100, 50, ]
          units: m
    dim_mapping:
      time:
        method: rename
        dim: time
      state_feature:
        method: stack_variables_by_var_name
        dims: [altitude]
        name_format: "{var_name}{altitude}m"
      grid_index:
        method: stack
        dims: [x, y]
    target_output_variable: state
"""

PRESSURE_LEVEL_TEST_SECTION = """\
inputs:
  danra_pressure_levels:
    path: https://object-store.os-api.cci1.ecmwf.int/mllam-testdata/danra_cropped/v0.2.0/pressure_levels.zarr
    dims: [time, x, y, pressure]
    variables:
      u:
        pressure:
          values: [1000,]
          units: hPa
      v:
        pressure:
          values: [1000, ]
          units: hPa
    dim_mapping:
      time:
        method: rename
        dim: time
      state_feature:
        method: stack_variables_by_var_name
        dims: [pressure]
        name_format: "{var_name}{pressure}m"
      grid_index:
        method: stack
        dims: [x, y]
    target_output_variable: state
"""

SINGLE_LEVEL_SELECTED_VARIABLES_TEST_SECTION = """\
inputs:
  danra_single_levels:
    path: https://object-store.os-api.cci1.ecmwf.int/mllam-testdata/danra_cropped/v0.2.0/single_levels.zarr
    dims: [time, x, y]
    variables:
      - t2m
      - pres_seasurface
    dim_mapping:
      time:
        method: rename
        dim: time
      state_feature:
        method: stack_variables_by_var_name
        name_format: "{var_name}"
      grid_index:
        method: stack
        dims: [x, y]
    target_output_variable: state
"""

SINGLE_LEVEL_DERIVED_VARIABLES_TEST_SECTION = """\
inputs:
  danra_single_levels:
    path: https://object-store.os-api.cci1.ecmwf.int/mllam-testdata/danra_cropped/v0.2.0/single_levels.zarr
    dims: [time, x, y]
    derived_variables:
      # derive variables to be used as forcings
      toa_radiation:
        kwargs:
          time: ds_input.time
          lat: ds_input.lat
          lon: ds_input.lon
        function: mllam_data_prep.ops.derive_variable.physical_field.calculate_toa_radiation
    dim_mapping:
      time:
        method: rename
        dim: time
      state_feature:
        method: stack_variables_by_var_name
        name_format: "{var_name}"
      grid_index:
        method: stack
        dims: [x, y]
    target_output_variable: state
"""


def modify_example_config(new_inputs_section):
    """
    Get the example config file as a yaml string and replace the
    `inputs` section with a new inputs section before reading the config

    Parameters
    ----------
    new_inputs_section: str
        String with a new inputs section

    Returns
    -------
    config: Config
        Modified config with the new inputs section replacing the old one
        in the example config
    """
    # Copy the config file to a temporary directory before reading it
    fp_example = "example.danra.yaml"
    tmpdir = tempfile.TemporaryDirectory()
    fp_config_copy = Path(tmpdir.name) / fp_example
    shutil.copy(fp_example, fp_config_copy)

    # Read the example config file as text to preserve the order
    base_config_yaml = Path(fp_config_copy).read_text()

    # Use regex to replace the entire "inputs:" block
    if new_inputs_section:
        modified_yaml = re.sub(
            r"inputs:\n((?:\s{2,}.*\n)*)",  # Matches "inputs:" and all indented content
            new_inputs_section,
            base_config_yaml,
        )
    else:
        modified_yaml = base_config_yaml

    # Read the config
    modified_config = mdp.Config.from_yaml(modified_yaml)

    return modified_config


@pytest.mark.parametrize(
    "new_inputs_section",
    [
        None,  # Does not modify the example config
        PRESSURE_LEVEL_TEST_SECTION,
        HEIGHT_LEVEL_TEST_SECTION,
        SINGLE_LEVEL_SELECTED_VARIABLES_TEST_SECTION,
        SINGLE_LEVEL_DERIVED_VARIABLES_TEST_SECTION,
    ],
)
def test_selected_output_variables(new_inputs_section):
    """
    Test that the variables specified in each input dataset are
    present in the output dataset.
    """
    # Modify the example config
    config = modify_example_config(new_inputs_section)

    # Create the dataset
    ds = mdp.create_dataset(config=config)

    # Check that the output variables are the ones selected
    for dataset_name, input_config in config.inputs.items():
        target_output_variable = input_config.target_output_variable

        # Get the expected selected variable names
        selected_variables = input_config.variables or []
        if isinstance(selected_variables, dict):
            selected_var_names = list(selected_variables.keys())
        elif isinstance(selected_variables, list):
            selected_var_names = selected_variables
        else:
            pytest.fail(
                "Expected either 'list' or 'dict' but got"
                f" type {type(selected_variables)} for 'selected_variables'."
            )

        # Get the expected derived variable names
        derived_variables = input_config.derived_variables or []
        if isinstance(derived_variables, dict):
            derived_var_names = list(derived_variables.keys())
        elif isinstance(derived_variables, list):
            derived_var_names = derived_variables
        else:
            pytest.fail(
                "Expected either 'list' or 'dict' but got"
                f" type {type(derived_variables)} for 'derived_variables'."
            )

        dim_mapping = input_config.dim_mapping[target_output_variable + "_feature"]
        dims = dim_mapping.dims or []
        name_format = dim_mapping.name_format

        if len(dims) == 0:
            selected_vars = selected_var_names
            derived_vars = derived_var_names
        elif len(dims) == 1:
            coord = dims[0]
            # Stack the variable names by coordinates, as is done in
            # mdp.ops.stacking.stack_variables_by_coord_values
            selected_vars = []
            for var_name in selected_var_names:
                coord_values = selected_variables[var_name][coord].values
                formatted_var_names = [
                    name_format.format(var_name=var_name, **{coord: val})
                    for val in coord_values
                ]
                selected_vars += formatted_var_names
            # We currently do not support stacking of variables by coordinates
            # for the derived variables
            derived_vars = []

        expected_variables = selected_vars + derived_vars
        output_variables = ds[target_output_variable + "_feature"].values

        if set(expected_variables) != set(output_variables):
            # Check if there are missing or extra variable
            missing_vars = list(set(expected_variables) - set(output_variables))
            extra_vars = list(set(output_variables) - set(expected_variables))

            error_message = (
                f"Expected {expected_variables}, but got {output_variables}."
            )
            if missing_vars:
                error_message += f"\nMissing variables: {missing_vars}"
            if extra_vars:
                error_message += f"\nExtra variables: {extra_vars}"

            pytest.fail(error_message)


INVALID_PRESSURE_LEVEL_TEST_SECTION = """\
inputs:
  danra_pressure_levels:
    path: https://object-store.os-api.cci1.ecmwf.int/mllam-testdata/danra_cropped/v0.2.0/pressure_levels.zarr
    dims: [time, x, y, pressure]
    variables:
      z:
        pressure:
          values: [1000,]
          units: hPa
      t:
        pressure:
          values: [800, ]
          units: hPa
    dim_mapping:
      time:
        method: rename
        dim: time
      state_feature:
        method: stack_variables_by_var_name
        dims: [pressure]
        name_format: "{var_name}{pressure}m"
      grid_index:
        method: stack
        dims: [x, y]
    target_output_variable: state
"""


@pytest.mark.parametrize(
    "new_inputs_section, expected_result",
    [
        (
            None,
            False,
        ),  # Do not modify the example config - should return False since we're expecting no nans
        (
            INVALID_PRESSURE_LEVEL_TEST_SECTION,
            True,
        ),  # Dataset with nans - should return True
    ],
)
def test_output_dataset_for_nans(new_inputs_section, expected_result):
    """
    Test that the output dataset does not contain any nan values.
    """
    # Modify the example config
    config = modify_example_config(new_inputs_section)

    # Create the dataset
    ds = mdp.create_dataset(config=config)

    # Test that we have no nans
    nan_in_ds = ds.isnull().any().compute().to_array().any().item()
    assert nan_in_ds == expected_result
