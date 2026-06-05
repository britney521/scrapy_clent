from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / 'dist'
BUILD = ROOT / 'build'
SPEC = ROOT / 'client_app.spec'

for path in (DIST, BUILD):
    if path.exists():
        shutil.rmtree(path)

cmd = [
    sys.executable,
    '-m',
    'PyInstaller',
    '--noconfirm',
    '--clean',
    str(SPEC),
]
subprocess.check_call(cmd, cwd=ROOT)
