import hashlib
import json
import os
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]


def norm_home():
    return Path(os.environ.get('NORM_HOME', ROOT.parent / 'Norm')).resolve()


def prepare():
    norm = norm_home()
    lock = json.loads((ROOT / 'dependencies.lock.json').read_text(encoding='utf-8'))
    if lock['hash'] != 'sha256-utf8-lf':
        raise RuntimeError('Unsupported dependency fingerprint format')
    for relative, digest in lock['norm_files'].items():
        source = norm / relative
        if not source.is_file() or hashlib.sha256(source.read_text(encoding='utf-8').encode('utf-8')).hexdigest() != digest:
            raise RuntimeError(f'Norm dependency does not match lock: {source}')
    source = norm / 'norm/libraries/openai'
    target = ROOT / 'dependencies/openai'
    target.mkdir(parents=True, exist_ok=True)
    for name in sorted(path.name for path in source.glob('*.norm')):
        destination = (target / name).resolve()
        if destination != (source / name).resolve():
            if not destination.is_relative_to(ROOT):
                raise RuntimeError(f'Generated dependency resolves outside gait: {destination}')
            shutil.copy2(source / name, target / name)
    (ROOT / '.tmp').mkdir(exist_ok=True)


def norm_command():
    norm = norm_home()
    descriptor = norm / 'cli/compiler/build/generated/runtime-launchers/launcher.json'
    settings = json.loads(descriptor.read_text(encoding='utf-8'))
    java_home = os.environ.get('JAVA_HOME')
    java = str(Path(java_home) / 'bin' / ('java.exe' if os.name == 'nt' else 'java')) if java_home else 'java'
    return [java, *settings['jvmArguments'], '--module-path', str(norm / 'cli/compiler/build/install/norm/lib'), '--module', settings['module']]


def gait_command():
    executable = os.environ.get('GAIT_EXECUTABLE')
    if executable:
        return [str(Path(executable).resolve())]
    return [*norm_command(), 'run', str(ROOT / 'gait'), '--']
