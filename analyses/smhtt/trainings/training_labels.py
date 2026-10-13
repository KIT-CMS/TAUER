import re

_STXS_BIN_RE = re.compile(r"_bin(\d+)_selection$")


def flag_value(flag_name, current_flag):
    m = _STXS_BIN_RE.search(flag_name)
    if m is None:
        return "(int)1" if flag_name == current_flag else "(int)0"
    if not flag_name.startswith(current_flag + "_"):
        return "(int)0"
    bin_number = int(m.group(1))
    return f"(int)(HTXS_stage1_2_cat_pTjet30GeV == {bin_number})"
