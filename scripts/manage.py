import argparse
import os
import shutil
import subprocess
import sys

from toolchain import ROOT, gait_command, norm_command, prepare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'run', 'build'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    options = parser.parse_args()
    prepare()
    if options.action == 'prepare':
        return 0
    if options.action == 'run':
        arguments = options.arguments
        if arguments[:1] == ['--']:
            arguments = arguments[1:]
        return subprocess.run([*gait_command(), *arguments]).returncode
    result = subprocess.run([*norm_command(), 'build', str(ROOT / 'gait')])
    if result.returncode:
        return result.returncode
    name = 'gait.exe' if os.name == 'nt' else 'gait'
    source = ROOT / 'gait/build' / name
    destination = ROOT / 'dist'
    destination.mkdir(exist_ok=True)
    shutil.copy2(source, destination / name)
    print(destination / name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
