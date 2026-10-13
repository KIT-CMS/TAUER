from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_ROOT = REPO_ROOT / "utils" / "setup_root.sh"


def get_output_features() -> List[str]:
    cmd = (
        f"source {SETUP_ROOT} >/dev/null 2>&1 && "
        'nice -n 19 python -c "from config.analysis import get_output_features; '
        'print(chr(10).join(get_output_features()))"'
    )
    result = subprocess.run(["bash", "-c", cmd], cwd=str(REPO_ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch OUTPUT_FEATURES via {SETUP_ROOT}:\n{result.stderr}")
    return [line for line in result.stdout.splitlines() if line]
