"""
Pre- and post-fit plots of the PostFitShapesFromWorkspace output of datacards/run_gof.py --postfit (b-only fit).

The band is the fit uncertainty of the total background (TotalBkg), the stack uses plot_shapes_control.py's process
order, colours and labels.
"""
import argparse
import logging
from pathlib import Path

import numpy as np
import ROOT

from plotting.plot_shapes_control import CHANNEL_LABELS, PROCESS_COLOURS, _th1_to_numpy, draw_stack_plot, legend_label_dict, lumi_label
from plotting.process_ordering import ControlShapeBkgProcesses
from CustomLogging import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-file", required=True, help="<job>-shapes.root of run_gof.py --postfit")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--era", required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--variable", required=True, help="x label")
    parser.add_argument("--log-y", action="store_true")
    return parser.parse_args()


def main(args):
    ROOT.TH1.AddDirectory(False)
    tfile = ROOT.TFile.Open(args.input_file)
    order = ControlShapeBkgProcesses(embedding=False, fake_factor=True, channel=args.channel)()
    for key in tfile.GetListOfKeys():
        directory = tfile.Get(key.GetName())
        fit = key.GetName().rsplit("_", 1)[-1]  # <bin>_prefit / <bin>_postfit
        names = [k.GetName() for k in directory.GetListOfKeys()]
        procs = [p for p in order if p in names] + [p for p in names if p not in order and not p.startswith(("Total", "data_obs"))]
        edges, _, total_err = _th1_to_numpy(directory.Get("TotalBkg"))
        _, y_data, yerr_data = _th1_to_numpy(directory.Get("data_obs"))
        draw_stack_plot(
            edges=edges,
            stack_values=[_th1_to_numpy(directory.Get(p))[1] for p in procs],
            stack_labels=[legend_label_dict.get(p, p) for p in procs],
            stack_colors=[PROCESS_COLOURS.get(p, "#AAAAAA") for p in procs],
            total_mc_err=total_err,
            x_label=args.variable,
            top_left_label=f"{CHANNEL_LABELS.get(args.channel, args.channel)} ({fit}, b-only)",
            top_right_label=lumi_label(args.era),
            out_dir=Path(args.output_dir),
            fname=f"{args.era}_{args.channel}__{args.variable}__{fit}",
            y_data=y_data,
            yerr_data=yerr_data,
            log_y=args.log_y,
            mc_err_label="Bkg. unc. (fit)" if fit == "postfit" else "Bkg. unc. (prefit)",
        )


if __name__ == "__main__":
    main(parse_arguments())
