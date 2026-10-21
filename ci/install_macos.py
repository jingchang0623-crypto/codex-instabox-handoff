#!/usr/bin/env python3
"""Install a user LaunchAgent; credentials remain managed by gh and Instabox."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

LABEL = 'dev.codex.instabox-ci-waker'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository', required=True)
    p.add_argument('--machine', required=True)
    p.add_argument('--label', default='instabox-ci')
    p.add_argument('--gh', default=shutil.which('gh'))
    p.add_argument('--instabox', default=shutil.which('instabox'))
    p.add_argument('--interval', type=int, default=30)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    if sys.platform != 'darwin' and not args.dry_run:
        raise RuntimeError('LaunchAgent installation requires macOS')
    if not args.gh or not args.instabox:
        raise RuntimeError('Pass absolute paths for --gh and --instabox')
    if args.interval < 15:
        raise ValueError('Use a polling interval of at least 15 seconds')
    directory = Path.home()/'Library/Application Support/CodexInstaboxCI'
    config_path = directory/'config.json'
    config = {'repository':args.repository,'machine':args.machine,'label':args.label,
              'workflow':'.github/workflows/tests.yml','branch':'main',
              'gh':str(Path(args.gh).expanduser().absolute()),'instabox':str(Path(args.instabox).expanduser().absolute()),
              'cooldownSeconds':120,'statePath':str(directory/'state.json')}
    plist_path = Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    # No tokens, passwords or SSH keys in the plist or configuration.
    plist = {'Label':LABEL,'ProgramArguments':[sys.executable,str(directory/'waker.py'),'--config',str(config_path)],
             'StartInterval':args.interval,'RunAtLoad':True,'ProcessType':'Background',
             'StandardOutPath':str(directory/'waker.log'),'StandardErrorPath':str(directory/'waker.stderr.log'),
             'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'}}
    if args.dry_run:
        print(json.dumps({'config':config,'plistPath':str(plist_path),'interval':args.interval},indent=2))
        return
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if config_path.exists():
        previous=json.loads(config_path.read_text())
        if previous['repository']!=args.repository or previous['machine']!=args.machine:
            raise RuntimeError('A different waker is already installed; inspect its configuration first')
    shutil.copy2(Path(__file__).with_name('waker.py'),directory/'waker.py')
    config_path.write_text(json.dumps(config,indent=2)+'\n')
    config_path.chmod(0o600)
    plist_path.parent.mkdir(parents=True,exist_ok=True)
    domain=f'gui/{os.getuid()}'
    subprocess.run(['launchctl','bootout',f'{domain}/{LABEL}'],capture_output=True)
    plist_path.write_bytes(plistlib.dumps(plist))
    subprocess.run(['launchctl','bootstrap',domain,str(plist_path)],check=True)
    print(json.dumps({'installed':str(plist_path),'config':str(config_path),'interval':args.interval}))


if __name__ == '__main__':
    main()
