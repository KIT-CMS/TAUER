import ROOT
import argparse
import json
import os
import glob
import shutil
from tqdm import tqdm
from multiprocessing import Pool, current_process, RLock
import XRootD.client.glob_funcs as xrdglob
import XRootD.client as client
from XRootD.client.flags import DirListFlags


def args_parser():
    parser = argparse.ArgumentParser(
        description="Generate xsec friend trees for SM-HTT analysis"
    )
    parser.add_argument(
        "--basepath",
        type=str,
        required=True,
        help="Basepath",
    )
    parser.add_argument(
        "--outputpath",
        type=str,
        required=True,
        help="Path to output directory",
    )
    parser.add_argument(
        "--nthreads",
        type=int,
        default=1,
        help="Number of threads to use",
    )
    parser.add_argument(
        "--dataset-config",
        type=str,
        default="TauFakeFactors/datasets/nanoAOD_v12/datasets.json",
        help="path to the datasets.json (use nanoAOD_v12 for 2022/23, nanoAOD_v15 for 2024/25)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="if set, debug mode will be enabled",
    )
    parser.add_argument(
        "--tempdir",
        type=str,
        default="tmp_dir",
        help="Temporary directory to store intermediate files",
    )
    return parser.parse_args()


def parse_filepath(path):
    """
    filepaths always look like this:
    /$basepath/2018/samplenick/mt/samplenick_3.root
    so the channel is the [-2] element
    """
    splitted = path.split("/")
    data = {
        "era": splitted[-4],
        "channel": splitted[-2],
        "nick": splitted[-3],
    }

    return data


def convert_to_xrootd(path):
    if path.startswith("/storage/gridka-nrg/"):
        return path.replace(
            "/storage/gridka-nrg/",
            "root://xrootd-cms.infn.it///store/user/",
        )
    elif path.startswith("/ceph"):
        return path


def job_wrapper(args):
    return friend_producer(*args)


def check_file_exists_remote(serverpath, file_path):
    """
    Check if a remote file exists. Works for both remote (XRootD) and local paths.
    
    Args:
        serverpath: Base server/path (can be remote XRootD or local)
        file_path: Full file path to check
    
    Returns:
        bool: True if file exists, False otherwise
    """
    # Check if path is remote (XRootD) or local
    if serverpath.startswith("root://"):
        # Remote XRootD path
        server_url = serverpath.split("store")[0][:-1] if "store" in serverpath else serverpath.rstrip("/")
        remote_file_path = (
            "/store" + serverpath.split("store")[1] + file_path.replace(serverpath, "")
            if "store" in serverpath
            else file_path
        )
        try:
            myclient = client.FileSystem(server_url)
            status, listing = myclient.stat(remote_file_path, DirListFlags.STAT)
            return status.ok
        except Exception as e:
            print(f"Error checking remote file {remote_file_path}: {e}")
            return False
    else:
        # Local path
        return os.path.exists(file_path)


def friend_producer(
    inputfile, workdir, output_path, dataset_proc, era, channel, debug=False
):
    temp_output_file = os.path.join(
        workdir, era, dataset_proc["nick"], channel, os.path.basename(inputfile)
    )
    final_output_file = os.path.join(
        output_path, era, dataset_proc["nick"], channel, os.path.basename(inputfile)
    )
    if debug:
        print(f"Processing {inputfile}")
        print(f"Outputting to {temp_output_file}")
    os.makedirs(os.path.dirname(temp_output_file), exist_ok=True)
    if (
        dataset_proc["sample_type"] == "data"
        or dataset_proc["sample_type"] == "embedding"
    ):
        return
    if not is_file_empty(inputfile, debug):
        if not check_file_exists_remote(output_path, final_output_file):
            build_rdf(inputfile, dataset_proc, temp_output_file)
            upload_file(output_path, temp_output_file, final_output_file)
    else:
        if not check_file_exists_remote(output_path, final_output_file):
            print(f"{inputfile} is empty, generating empty friend tree")
            generate_empty_friend_tree(temp_output_file)
            upload_file(output_path, temp_output_file, final_output_file)


def is_file_empty(inputfile, debug=False):
    try:
        rootfile = ROOT.TFile.Open(inputfile, "READ")
    except OSError:
        print(f"{inputfile} is broken")
        return True
    if "ntuple" not in [x.GetTitle() for x in rootfile.GetListOfKeys()]:
        print(f"{inputfile} is empty")
        if debug:
            print("Available keys: ", [x.GetTitle() for x in rootfile.GetListOfKeys()])
        rootfile.Close()
        return True
    rootfile.Close()
    return False


def build_rdf(inputfile, dataset_proc, output_file):
    rootfile = ROOT.TFile.Open(inputfile, "READ")
    rdf = ROOT.RDataFrame("ntuple", rootfile)
    numberGeneratedEventsWeight = 1 / float(dataset_proc["nevents"])
    crossSectionPerEventWeight = float(dataset_proc["xsec"])
    negative_events_fraction = float(dataset_proc["generator_weight"])
    rdf = rdf.Define(
        "numberGeneratedEventsWeight",
        "(float){ngw}".format(ngw=numberGeneratedEventsWeight),
    )
    rdf = rdf.Define(
        "crossSectionPerEventWeight",
        "(float){xsec}".format(xsec=crossSectionPerEventWeight),
    )
    rdf = rdf.Define(
        "negative_events_fraction",
        "(float){negative_events_fraction}".format(
            negative_events_fraction=negative_events_fraction
        ),
    )
    rdf.Snapshot(
        "ntuple",
        output_file,
        [
            "numberGeneratedEventsWeight",
            "crossSectionPerEventWeight",
            "negative_events_fraction",
        ],
    )
    rootfile.Close()


def upload_file(redirector, input_file, output_file, max_retries=5):
    success = False
    n = 0
    while not success and n < max_retries:
        if output_file.startswith("root://"):
            os.system(f"xrdcp {input_file} {output_file}")
            if check_file_exists_remote(redirector, output_file):
                success = True
            else:
                print(f"Failed to upload {output_file}")
                print(f"Retrying {n+1}/{max_retries}")
                n += 1
        else:
            if not os.path.exists(os.path.dirname(output_file)):
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
            os.system(f"mv {input_file} {output_file}")
            success = True


def generate_empty_friend_tree(output_file):
    friend_tree = ROOT.TFile(output_file, "CREATE")
    tree = ROOT.TTree("ntuple", "")
    tree.Write()
    friend_tree.Close()


def generate_friend_trees(dataset, ntuples, nthreads, workdir, output_path, debug):
    print("Using {} threads".format(nthreads))
    arguments = [
        (
            ntuple,
            workdir,
            output_path,
            dataset[parse_filepath(ntuple)["nick"]],
            parse_filepath(ntuple)["era"],
            parse_filepath(ntuple)["channel"],
            debug,
        )
        for ntuple in ntuples
    ]
    pbar = tqdm(
        total=len(arguments),
        desc="Total progress",
        position=nthreads + 1,
        dynamic_ncols=True,
        leave=True,
    )
    with Pool(nthreads, initargs=(RLock(),), initializer=tqdm.set_lock) as pool:
        for result in pool.imap_unordered(job_wrapper, arguments):
            pbar.update(1)
    pool.close()
    pbar.close()


if __name__ == "__main__":
    args = args_parser()
    base_path = os.path.join(args.basepath, "*/*/*/*.root")
    output_path = os.path.join(args.outputpath)
    workdir = os.path.join(args.tempdir)
    dataset = json.load(open(args.dataset_config))
    print("Collecting ntuples from {}".format(base_path))
    if base_path.startswith("root://"):
        ntuples = xrdglob.glob(base_path)
    else:
        ntuples = glob.glob(base_path)
    print("Found {} ntuples".format(len(ntuples)))
    # Remove data and embedded samples from ntuple list as friends are not needed for these
    ntuples_wo_data = list(
        filter(
            lambda ntuple: dataset[parse_filepath(ntuple)["nick"]]["sample_type"]
            != "data"
            and dataset[parse_filepath(ntuple)["nick"]]["sample_type"] != "embedding",
            ntuples,
        )
    )
    nthreads = args.nthreads
    if nthreads > len(ntuples_wo_data):
        nthreads = len(ntuples_wo_data)
    generate_friend_trees(
        dataset, ntuples_wo_data, nthreads, workdir, output_path, args.debug
    )
    # remove the temporary directory
    if os.path.exists(workdir):
        shutil.rmtree(workdir)
    print("Done")
