#!/usr/bin/env python3
"""Install the bundled Skill without touching SSH, login state or user profiles."""
import argparse
import datetime
import os
from pathlib import Path
import shutil
import sys


def install(source, codex_home, upgrade=False):
    source = Path(source).resolve(strict=True)
    destination = Path(codex_home).expanduser().resolve() / 'skills/instabox-handoff'
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('Source and destination must be separate directories')
    if destination.is_symlink():
        raise ValueError('Refusing to replace a symlink; inspect its target first')
    backup = None
    if destination.exists():
        if not upgrade:
            raise FileExistsError('Skill already installed; use --upgrade to back up and replace it')
        if not destination.is_dir():
            raise ValueError('Existing destination is not a directory')
        # Keep backups outside skills/ so Codex does not discover duplicate Skills.
        backup_root = destination.parent.parent / 'skill-backups' / destination.name
        backup_root.mkdir(parents=True, exist_ok=True)
        backup = backup_root / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        destination.rename(backup)
    try:
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    except Exception:
        if destination.exists():
            shutil.rmtree(destination)
        if backup:
            backup.rename(destination)
        raise
    return destination, backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))))
    parser.add_argument('--upgrade', action='store_true')
    args = parser.parse_args()
    if os.name != 'posix':
        raise RuntimeError('The current Skill helpers require macOS/Linux (POSIX file locking)')
    source = Path(__file__).resolve().parents[1] / 'skills/instabox-handoff'
    destination, backup = install(source, args.codex_home, args.upgrade)
    print('Installed:', destination)
    if backup:
        print('Backup:', backup)
    print('Next: configure your machine and profile using references/setup.md in the installed Skill.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
