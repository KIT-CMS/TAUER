"""
Sums the shapes.root of several eras into one file, e.g. for plots of the NN scores of a training over all eras.

A shift that only some eras have (era-tagged systematics) takes the nominal of the other eras, so Up/Down stay comparable
to the merged nominal.
"""
import argparse
import logging

import ROOT

from shapes import naming
from CustomLogging import setup_logging

logger = setup_logging(logger=logging.getLogger(__name__))


def parse_arguments():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-files", required=True, nargs="+", help="shapes.root of each era")
    parser.add_argument("--output-file", required=True)
    return parser.parse_args()


def main(args):
    ROOT.TH1.AddDirectory(False)
    files = [ROOT.TFile.Open(f) for f in args.input_files]
    contents = [{} for _ in files]  # per file: directory -> set of histogram names
    for tfile, content in zip(files, contents):
        for variable, bin_, name in naming.iter_histograms(tfile):
            content.setdefault(f"{variable}/{bin_}", set()).add(name)

    output = ROOT.TFile(args.output_file, "RECREATE")
    for directory in sorted(set().union(*contents)):
        for name in sorted(set().union(*(c.get(directory, ()) for c in contents))):
            merged = None
            for tfile, content in zip(files, contents):
                names = content.get(directory, set())
                # missing shift -> the longest histogram name it extends, i.e. its nominal
                source = name if name in names else max((n for n in names if name.startswith(n + "_")), key=len, default=None)
                if source is None:
                    continue
                hist = tfile.Get(f"{directory}/{source}")
                if merged is None:
                    merged = hist.Clone()
                else:
                    merged.Add(hist)
            naming.write(output, merged, f"{directory}/{name}")
    output.Close()
    logger.info(f"Merged {len(files)} eras into {args.output_file}")


if __name__ == "__main__":
    main(parse_arguments())
