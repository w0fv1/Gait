import hashlib
import json
import os
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]


def prepare():
    lock = json.loads((ROOT / 'dependencies.lock.json').read_text(encoding='utf-8'))
    if lock['hash'] != 'sha256-utf8-lf':
        raise RuntimeError('Unsupported dependency fingerprint format')
    for relative, digest in lock['files'].items():
        source = ROOT / relative
        if not source.is_file() or hashlib.sha256(source.read_text(encoding='utf-8').encode('utf-8')).hexdigest() != digest:
            raise RuntimeError(f'Bundled dependency does not match lock: {source}')
    (ROOT / '.tmp').mkdir(exist_ok=True)


def norm_command():
    launcher = os.environ.get('NORM_CLI') or shutil.which('norm')
    if launcher is None:
        raise RuntimeError('Norm CLI not found. Set NORM_CLI or install a compatible Norm on PATH.')
    return [launcher]


def gait_command():
    executable = os.environ.get('GAIT_EXECUTABLE')
    if executable:
        return [str(Path(executable).resolve())]
    return [*norm_command(), 'run', str(ROOT / 'gait'), '--']
