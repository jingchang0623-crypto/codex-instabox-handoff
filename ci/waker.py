#!/usr/bin/env python3
"""Poll trusted queued Actions jobs and wake one dedicated Instabox machine."""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


def run(argv, timeout=60):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        # Never log CLI command output or credentials from an authentication error.
        raise RuntimeError(f'{Path(argv[0]).name} failed with exit {p.returncode}')
    return p.stdout


def eligible_run(item, config):
    return (item.get('event') in ('push', 'workflow_dispatch')
            and item.get('head_branch') == config.get('branch', 'main')
            and item.get('path') == config.get('workflow', '.github/workflows/tests.yml')
            and (item.get('head_repository') or {}).get('full_name') == config['repository'])


def matching_jobs(jobs, label):
    return [job for job in jobs if job.get('status') == 'queued' and label in job.get('labels', [])]


def save_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.state-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(data, file, indent=2)
            file.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def tick(config, state, execute=run, now=None):
    now = time.time() if now is None else now
    repository = config['repository']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('repository must be owner/name')
    gh, cli = config['gh'], config['instabox']
    pending = []
    for status in ('queued', 'in_progress'):
        response = json.loads(execute([gh, 'api', f'repos/{repository}/actions/runs?status={status}&per_page=20']))
        for workflow in response.get('workflow_runs', []):
            if not eligible_run(workflow, config):
                continue
            response = json.loads(execute([gh, 'api', f'repos/{repository}/actions/runs/{workflow["id"]}/jobs?per_page=100']))
            for job in matching_jobs(response.get('jobs', []), config['label']):
                pending.append({'runId':workflow['id'], 'jobId':job['id'], 'attempt':workflow.get('run_attempt',1)})
    if not pending:
        return state, None
    if now - state.get('lastWakeAt', 0) < config.get('cooldownSeconds', 120):
        return state, None
    machine = json.loads(execute([cli, 'get', config['machine'], '--json']))
    status = machine.get('state')
    if status in ('suspended', 'paused'):
        execute([cli, 'resume', config['machine'], '--no-vault'], timeout=90)
        action = 'resumed'
    elif status == 'stopped':
        execute([cli, 'start', config['machine'], '--no-vault'], timeout=90)
        action = 'started'
    elif status == 'running':
        # Do not issue `exec` probes: those can count as activity and prevent idle sleep.
        action = 'already-running'
    else:
        action = 'waiting-for-machine'
    record = {'at':datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat(),
              'action':action, 'jobs':pending, 'repository':repository}
    updated = dict(state, lastWakeAt=now, lastAction=record)
    return updated, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    state_path = Path(config.get('statePath', str(args.config.with_name('state.json'))))
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with Path(str(state_path)+'.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        updated, record = tick(config, state)
        if record:
            save_json(state_path, updated)
            print(json.dumps(record), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error':str(error),'at':datetime.datetime.now(datetime.timezone.utc).isoformat()}),flush=True)
        raise SystemExit(1)
