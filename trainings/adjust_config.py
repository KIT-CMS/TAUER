
import argparse
import logging
from functools import partial

import yaml
from src.config_modifications import ConfigModification, remove_keys
from src.helper import TRAINING_VARIABLES, Iterate, PipeDict

try:
    from config.logging_setup_configs import setup_logging
except ModuleNotFoundError:
    import sys
    sys.path.extend([".", ".."])
    from config.logging_setup_configs import setup_logging


def parse_args():
    parser = argparse.ArgumentParser(description="Process some integers.")
    parser.add_argument(
        "--configs",
        default=[],
        nargs="+",
        type=str,
        help="Path to the input config file(s) to be modified",
    )
    parser.add_argument(
        "--modified-config",
        type=str,
        default="./mt__tmp_config__modified.yaml",
        help="Path to the output config file",
    )
    parser.add_argument(
        "--training-variables",
        type=str,
        default=TRAINING_VARIABLES,
        nargs="+",
        help="List of training variables to be added to the config",
    )
    parser.add_argument(
        "--common-setup-config",
        type=str,
        default="",
        help="Path to the common setup config file",
    )
    return parser.parse_args()


if __name__ == "__main__":

    logger = setup_logging(logger=logging.getLogger(__name__))
    args = parse_args()

    if args.common_setup_config:
        with open(args.common_setup_config, "r") as f:
            args.common_setup_config = yaml.safe_load(f)
            if not args.common_setup_config:
                logger.warning("No common setup config provided or it is empty, using default settings.")
                args.common_setup_config = {}
    else:
        args.common_setup_config = {}

    args.common_setup_config = PipeDict(args.common_setup_config)

    Iterate.common_dict = partial(Iterate.common_dict)
    training_variables = list(set(args.common_setup_config.get("training_variables", args.training_variables)))
    logger.info(f"Used training variables: {training_variables}")

    config = (
        PipeDict()
        .pipe(ConfigModification.general.recursive_update_from_file, path=args.configs)
        .pipe(ConfigModification.general.set_common)
        .conditional_pipe(
            processes := args.common_setup_config.recursive_get(["config_modifications", "general", "remove_from_config"]),
            ConfigModification.general.remove_from_config,
            processes=processes,
        )
        .conditional_pipe(
            rename := args.common_setup_config.recursive_get(["config_modifications", "general", "rename"]),
            ConfigModification.general.rename,
            processes=rename.get("processes", {}),
            subprocesses=rename.get("subprocesses", {}),
            shifts=rename.get("shifts", {}),
        )
        .pipe(ConfigModification.general.add_era_and_process_name_flags)
        .pipe(ConfigModification.specific.add_anti_iso_cut_and_weight_version)
        .pipe(ConfigModification.specific.convert_weights_and_cuts_to_common)
        .pipe(ConfigModification.specific.add_set_of_training_variables, training_variables=training_variables)
        .pipe(ConfigModification.specific.nest_and_categorize_uncertainties)
        .pipe(remove_keys, keys_to_remove={"var"})
    )

    with open(args.modified_config, "w") as f:
        yaml.dump(dict(config), f, default_flow_style=False)
        logger.info(f"Modified config saved to {args.modified_config}")
