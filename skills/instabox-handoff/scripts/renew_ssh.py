#!/usr/bin/env python3
"""SSH Match exec hook: renew one official Instabox certificate before expiry."""
import argparse
import datetime
import fcntl
from pathlib import Path
import re
import subprocess
import sys


def is_current(cert, margin_seconds=600):
    result = subprocess.run(['ssh-keygen', '-Lf', str(cert)], capture_output=True, text=True)
    match = re.search(r'Valid: from \S+ to (\S+)', result.stdout)
    if result.returncode or not match:
        return False
    if match.group(1) == 'forever':
        return True
    try:
        expiry = datetime.datetime.fromisoformat(match.group(1))
        now = datetime.datetime.now(expiry.tzinfo)
        return (expiry - now).total_seconds() > margin_seconds
    except ValueError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--machine', required=True)
    parser.add_argument('--cert', type=Path, required=True)
    parser.add_argument('--cli', default='instabox')
    args = parser.parse_args()
    args.cert.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with Path(str(args.cert) + '.codex-refresh.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not is_current(args.cert):
            result = subprocess.run([args.cli, 'ssh-cert', args.machine], stdout=subprocess.DEVNULL, timeout=45)
            if result.returncode or not is_current(args.cert, margin_seconds=0):
                raise RuntimeError('Official certificate renewal failed; check Instabox CLI login')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Instabox SSH refresh: {error}', file=sys.stderr)
        sys.exit(1)
