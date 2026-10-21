#!/usr/bin/env python3
"""Provision a dedicated Instabox runner via official CLIs; no credentials in files."""
import argparse
import base64
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time


def command(argv, **kwargs):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=kwargs.pop('timeout', 60), **kwargs)
    if result.returncode:
        raise RuntimeError(f'Command failed: {argv[0]} (exit {result.returncode})\n{result.stderr[-2000:]}')
    return result.stdout


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository', required=True)
    p.add_argument('--machine', required=True)
    p.add_argument('--name', default='instabox-ci-linux')
    p.add_argument('--label', default='instabox-ci')
    p.add_argument('--instabox', default=shutil.which('instabox') or 'instabox')
    p.add_argument('--gh', default=shutil.which('gh') or 'gh')
    args = p.parse_args()
    for value in (args.repository, args.name, args.label):
        if not re.fullmatch(r'[A-Za-z0-9_.\-/]+', value):
            raise ValueError('Use plain repository/name/label identifiers')
    if len(args.repository.split('/')) != 2:
        raise ValueError('Repository must be owner/name')
    # This machine must be dedicated to trusted CI. Never use the development VM.
    release = json.loads(command([args.gh, 'api', 'repos/actions/runner/releases/latest']))
    asset = next(a for a in release['assets'] if re.fullmatch(r'actions-runner-linux-x64-[0-9.]+\.tar\.gz', a['name']))
    digest = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise RuntimeError('Runner release has no verifiable SHA256 digest')
    token = json.loads(command([args.gh, 'api', '--method', 'POST', f'repos/{args.repository}/actions/runners/registration-token']))['token']
    guard = (Path(__file__).parent/'job_guard.py').read_bytes()
    wrapper = f'#!/bin/sh\nexec /usr/bin/python3 /opt/codex-instabox-ci/job_guard.py --repository {shlex.quote(args.repository)}\n'
    variables = {
        'RUNNER_URL': asset['browser_download_url'], 'RUNNER_SHA': digest.split(':')[1],
        'RUNNER_TOKEN': token, 'REPOSITORY': args.repository, 'RUNNER_NAME': args.name,
        'RUNNER_LABEL': args.label, 'GUARD_B64': base64.b64encode(guard).decode(),
        'WRAPPER_B64': base64.b64encode(wrapper.encode()).decode(),
    }
    prefix = '\n'.join(f'{key}={shlex.quote(value)}' for key, value in variables.items())+'\n'
    script = r'''
set -eu
# Do not enable shell tracing: the one-hour registration token arrives on stdin.
sudo systemctl start docker
if ! id ci-runner >/dev/null 2>&1; then
  sudo useradd --create-home --home-dir /data/ci-runner --shell /bin/bash ci-runner
fi
sudo usermod -aG docker ci-runner
sudo chmod 700 /data/ci-runner
sudo install -d -o ci-runner -g ci-runner /data/ci-runner/actions-runner
sudo install -d -m 755 /opt/codex-instabox-ci
printf '%s' "$GUARD_B64" | base64 -d | sudo tee /opt/codex-instabox-ci/job_guard.py >/dev/null
printf '%s' "$WRAPPER_B64" | base64 -d | sudo tee /opt/codex-instabox-ci/job_guard.sh >/dev/null
sudo chown root:root /opt/codex-instabox-ci/job_guard.*
sudo chmod 755 /opt/codex-instabox-ci/job_guard.*
cd /data/ci-runner/actions-runner
if ! sudo test -f .runner; then
  archive=$(mktemp)
  trap 'rm -f "$archive"' EXIT
  curl --fail --location --silent --show-error "$RUNNER_URL" -o "$archive"
  printf '%s  %s\n' "$RUNNER_SHA" "$archive" | sha256sum --check --status
  sudo tar xzf "$archive" -C /data/ci-runner/actions-runner
  sudo chown -R ci-runner:ci-runner /data/ci-runner/actions-runner
  sudo -u ci-runner ./config.sh --unattended --url "https://github.com/$REPOSITORY" \
    --token "$RUNNER_TOKEN" --name "$RUNNER_NAME" --labels "$RUNNER_LABEL" --no-default-labels --work _work
else
  sudo python3 - "$REPOSITORY" "$RUNNER_NAME" <<'CHECK'
import json,sys
p=json.load(open('.runner',encoding='utf-8-sig'))
assert p['gitHubUrl'].rstrip('/') == 'https://github.com/'+sys.argv[1]
assert p['agentName']==sys.argv[2]
CHECK
fi
# The release ships this launcher in bin/; svc.sh normally copies it to root.
sudo install -o ci-runner -g ci-runner -m 755 bin/runsvc.sh ./runsvc.sh
sudo tee /etc/systemd/system/codex-instabox-runner.service >/dev/null <<'SERVICE'
[Unit]
Description=Dedicated Instabox GitHub Actions runner
After=network-online.target docker.service
Wants=network-online.target docker.service
[Service]
User=ci-runner
Group=ci-runner
SupplementaryGroups=docker
WorkingDirectory=/data/ci-runner/actions-runner
ExecStart=/data/ci-runner/actions-runner/runsvc.sh
Environment=ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/codex-instabox-ci/job_guard.sh
Restart=always
RestartSec=10
KillMode=process
TimeoutStopSec=120
NoNewPrivileges=true
InaccessiblePaths=/data/home /root
[Install]
WantedBy=multi-user.target
SERVICE
sudo systemctl daemon-reload
sudo systemctl enable --now codex-instabox-runner.service
sudo systemctl is-active codex-instabox-runner.service
'''
    # CLI exec treats command arguments as shell text. A plain `bash` plus stdin
    # avoids quoting bugs and keeps the token out of the command metadata.
    result = command([args.instabox, 'exec', args.machine, '--stdin', '--timeout', '600', '--', 'sudo', 'bash'],
                     input=prefix+script, timeout=660)
    # Redact the short-lived token even if an upstream CLI unexpectedly prints it.
    print(result.replace(token, '[redacted]'))
    for attempt in range(6):
        runners=json.loads(command([args.gh,'api',f'repos/{args.repository}/actions/runners']))['runners']
        if any(r['name']==args.name and r['status']=='online' for r in runners):
            print(json.dumps({'runner':args.name,'label':args.label,'version':release['tag_name'],'registered':True,'online':True}))
            break
        if attempt==5:
            raise RuntimeError('Runner registered but not online; inspect its systemd journal before dispatching jobs')
        time.sleep(5)


if __name__ == '__main__':
    main()
