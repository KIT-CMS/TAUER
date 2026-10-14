"""
Histogram paths of the shapes files, read directly by Combine:

    <variable>/<channel>[_<category>][_ss|_ar]/<process>[_<systematic>]

`_ss`/`_ar` mark the same-sign (QCD) and anti-isolated (fake factor) input regions, data is `data_obs`.
The datacards extract `<variable>/$BIN/$PROCESS` and `<variable>/$BIN/$PROCESS_$SYSTEMATIC`.
"""
from ntuple_processor import Unit

DATA = "data_obs"
REGIONS = {"same_sign": "ss", "anti_iso": "ar"}


def bin_name(channel, category=None, region=None):
    return "_".join(part for part in (channel, category, region) if part)


def histogram_name(process, systematic=None):
    return f"{process}_{systematic}" if systematic else process


def path(variable, channel, process, category=None, region=None, systematic=None):
    return f"{variable}/{bin_name(channel, category, region)}/{histogram_name(process, systematic)}"


def split_region(systematic):
    """ntuple_processor systematic name -> (region, shift): 'anti_iso_CMS_xUp' -> ('ar', 'CMS_xUp'), 'CMS_xUp' -> (None, 'CMS_xUp')."""
    for prefix, region in REGIONS.items():
        if systematic == prefix:
            return region, None
        if systematic.startswith(prefix + "_"):
            return region, systematic[len(prefix) + 1:]
    return None, systematic


def systematic_path(nominal, systematic):
    """Path of a shifted histogram from its nominal one, the region of same_sign/anti_iso goes into the bin."""
    variable, bin_, process = nominal.split("/")
    region, shift = split_region(systematic)
    return f"{variable}/{bin_name(bin_, region)}/{histogram_name(process, shift)}"


Unit.systematic_path = staticmethod(systematic_path)


def split_bin(bin_, channel):
    """'mt_ggh_ar' -> ('ggh', 'ar'), 'mt' -> (None, None)."""
    rest = bin_[len(channel) + 1:]
    region = next((r for r in REGIONS.values() if rest == r or rest.endswith("_" + r)), None)
    if region:
        rest = rest[: -len(region)].rstrip("_")
    return rest or None, region


def iter_histograms(tfile):
    """(variable, bin, histogram name) of every histogram of a shapes file."""
    for variable_key in tfile.GetListOfKeys():
        variable_dir = variable_key.ReadObj()
        for bin_key in variable_dir.GetListOfKeys():
            for hist_key in bin_key.ReadObj().GetListOfKeys():
                yield variable_key.GetName(), bin_key.GetName(), hist_key.GetName()


def split_histogram(name, processes):
    """'ZTT_CMS_xUp' -> ('ZTT', 'CMS_xUp') given the known process names (longest match wins), None if unknown."""
    for process in sorted(processes, key=len, reverse=True):
        if name == process:
            return process, None
        if name.startswith(process + "_"):
            return process, name[len(process) + 1:]
    return None


def get(tfile, *args, **kwargs):
    """Histogram at path(*args, **kwargs), raising if it is missing."""
    name = path(*args, **kwargs)
    hist = tfile.Get(name)
    if not hist:
        raise KeyError(f"Histogram {name} not found in {tfile.GetName()}")
    return hist


def write(tfile, hist, name):
    """Write `hist` at path `name` of `tfile`, overwriting an existing one."""
    directory, base = name.rsplit("/", 1)
    tfile.mkdir(directory, "", True).cd()
    hist.SetName(base)
    hist.SetTitle(base)
    hist.Write(base, hist.kOverwrite)
