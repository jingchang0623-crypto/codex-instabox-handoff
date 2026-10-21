#!/usr/bin/env python3
"""Official Codex stdio API helpers and conservative Git synchronization. Stdlib only."""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
from pathlib import Path
import queue
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time

DEFAULT_PROFILE = Path.home() / '.config/codex-instabox-handoff/profile.json'


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def run(argv, timeout=60, check=True):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {shlex.join(argv)}\n{result.stderr[-3000:]}')
    return result


def ssh_prefix(host):
    # Reject options/newlines rather than allowing an untrusted alias to become ssh flags.
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', host):
        raise ValueError('Use a saved SSH alias (no options, spaces or shell syntax)')
    return ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', host]


def on_host(argv, host=None, **kwargs):
    return run(ssh_prefix(host) + [shlex.join(argv)] if host else argv, **kwargs)


def load_profile(path):
    if not path.exists():
        return {'schemaVersion': 1, 'projects': {}, 'sessions': {}}
    data = json.loads(path.read_text())
    if data.get('schemaVersion') != 1:
        raise ValueError('Unsupported profile schema')
    return data


def update_session(path, name, value, replace=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with Path(str(path) + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load_profile(path)
        sessions = data.setdefault('sessions', {})
        if name in sessions and not replace:
            raise ValueError(f'Session {name!r} already exists; choose another name')
        old = sessions.get(name, {})
        record = dict(old, **value)
        record['updatedAt'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sessions[name] = record
        fd, temporary = tempfile.mkstemp(prefix='.profile-', dir=str(path.parent))
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write('\n')
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return record


class AppServer:
    """Own one stdio child. Bound RPC deadlines; never dump raw history/reasoning."""
    def __init__(self, host=None):
        command = ['codex', 'app-server', '--stdio']
        if host:
            command = ssh_prefix(host) + [shlex.join(command)]
        self.child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True)
        self.messages = queue.Queue()
        self.number = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.child.stdout:
            try:
                self.messages.put(json.loads(line))
            except ValueError:
                continue
        self.messages.put(None)

    def send(self, value):
        self.child.stdin.write(json.dumps(value) + '\n')
        self.child.stdin.flush()

    def rpc(self, method, params, timeout=45):
        self.number += 1
        request_id = self.number
        self.send({'id': request_id, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f'App Server timed out: {method}')
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(f'App Server timed out: {method}')
            if message is None:
                raise RuntimeError(f'App Server closed before replying: {method}')
            if message.get('id') == request_id:
                if 'error' in message:
                    raise RuntimeError(f'{method}: {message["error"]}')
                return message['result']

    def __enter__(self):
        try:
            self.rpc('initialize', {
                'clientInfo': {'name': 'instabox_handoff_skill', 'version': '1.0.0'},
                'capabilities': {'experimentalApi': True}})
            self.send({'method': 'initialized'})
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        with contextlib.suppress(OSError):
            self.child.stdin.close()
        try:
            self.child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.child.terminate()
            try:
                self.child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=3)
        self.child.stdout.close()


def read_thread(thread_id, host=None, turns=True):
    with AppServer(host) as server:
        return server.rpc('thread/read', {'threadId': thread_id, 'includeTurns': turns})['thread']


def summary(thread):
    result = {key: thread.get(key) for key in ('id', 'historyMode', 'cwd', 'status')}
    turns = thread.get('turns') or []
    result['turnCount'] = len(turns)
    if turns:
        last = turns[-1]
        result['lastTurn'] = {key: last.get(key) for key in ('id', 'status', 'completedAt')}
        # Deliberately omit reasoning, user input, raw command output and file contents.
        result['lastTurn']['assistantMessages'] = [item.get('text', '') for item in last.get('items', [])
                                                  if item.get('type') == 'agentMessage']
    return result


def git(cwd, *args, host=None, check=True):
    if not cwd.startswith('/') or '\n' in cwd:
        raise ValueError('Git cwd must be an absolute path')
    return on_host(['git', '-C', cwd, *args], host, check=check)


def inspect(cwd, remote, host=None):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', remote):
        raise ValueError('Invalid remote name')
    if host:
        if not cwd.startswith('/') or '\n' in cwd:
            raise ValueError('Git cwd must be an absolute path')
        # One SSH connection per snapshot, instead of seven network round trips.
        code = '''import json,os,subprocess,sys
cwd,remote=sys.argv[1:]
commands={"root":["rev-parse","--show-toplevel"],
"dirty":["status","--porcelain","--untracked-files=all"],
"branch":["symbolic-ref","--quiet","--short","HEAD"],
"origin":["config","--get","remote.origin.url"],
"pushUrl":["remote","get-url","--push",remote],
"fetchUrl":["remote","get-url",remote],"head":["rev-parse","HEAD"]}
result={"realCwd":os.path.realpath(cwd)}
for key,args in commands.items():
 p=subprocess.run(["git","-C",cwd]+args,capture_output=True,text=True,timeout=20)
 if p.returncode:
  sys.exit("Git inspection failed: "+key+"\\n"+p.stderr[-2000:])
 result[key]=p.stdout.strip()
print(json.dumps(result))'''
        snapshot = json.loads(on_host(['python3', '-c', code, cwd, remote], host).stdout)
        if snapshot['root'].rstrip('/') != snapshot['realCwd'].rstrip('/'):
            raise ValueError('Use the actual Git root, not a subdirectory')
        if snapshot['dirty']:
            raise ValueError(f'Dirty checkout preserved: {host}:{cwd}\n{snapshot["dirty"][:2000]}')
        return dict({key: snapshot[key] for key in ('branch', 'origin', 'pushUrl', 'fetchUrl', 'head')},
                    cwd=cwd, host=host, remote=remote)
    root = git(cwd, 'rev-parse', '--show-toplevel', host=host).stdout.strip()
    if Path(root).resolve() != Path(cwd).resolve():
        raise ValueError('Use the actual Git root, not a subdirectory')
    dirty = git(cwd, 'status', '--porcelain', '--untracked-files=all', host=host).stdout
    if dirty:
        raise ValueError(f'Dirty checkout preserved: {host or "local"}:{cwd}\n{dirty[:2000]}')
    branch = git(cwd, 'symbolic-ref', '--quiet', '--short', 'HEAD', host=host).stdout.strip()
    origin = git(cwd, 'config', '--get', 'remote.origin.url', host=host).stdout.strip()
    # Resolves the actual push URL, including pushurl; caller reviews it before --apply.
    push_url = git(cwd, 'remote', 'get-url', '--push', remote, host=host).stdout.strip()
    fetch_url = git(cwd, 'remote', 'get-url', remote, host=host).stdout.strip()
    return {'cwd': cwd, 'host': host, 'branch': branch, 'origin': origin,
            'remote': remote, 'pushUrl': push_url, 'fetchUrl': fetch_url,
            'head': git(cwd, 'rev-parse', 'HEAD', host=host).stdout.strip()}


def synchronize(project, direction, apply=False, source_cwd=None, dest_cwd=None):
    host = project['sshHost']
    local = (project['localPath'], project.get('localRemote', 'origin'), None)
    cloud = (project['remotePath'], project.get('remoteRemote', 'origin'), host)
    source, dest = (local, cloud) if direction == 'to-cloud' else (cloud, local)
    source = (source_cwd or source[0], source[1], source[2])
    dest = (dest_cwd or dest[0], dest[1], dest[2])
    a = inspect(source[0], source[1], source[2])
    b = inspect(dest[0], dest[1], dest[2])
    if a['origin'] != project['origin'] or b['origin'] != project['origin']:
        raise ValueError('origin differs from configured common repository; no changes made')
    if a['branch'] != b['branch']:
        raise ValueError('Branches differ; no checkout or push performed')
    plan = {'source': a, 'destination': b, 'mode': 'apply' if apply else 'preview'}
    if not apply:
        return plan
    # Recheck both checkouts before push; never commit or stash other work.
    if inspect(*source) != a or inspect(*dest) != b:
        raise ValueError('Checkout changed during preflight; retry after edits stop')
    branch = a['branch']
    git(a['cwd'], 'push', '--porcelain', a['remote'], f'{a["head"]}:refs/heads/{branch}', host=a['host'])
    # From this point a source push may have succeeded even if the destination fails.
    try:
        git(b['cwd'], 'fetch', '--no-tags', b['remote'], f'refs/heads/{branch}', host=b['host'])
        fetched = git(b['cwd'], 'rev-parse', 'FETCH_HEAD', host=b['host']).stdout.strip()
        if fetched != a['head']:
            raise ValueError('Remote changed or endpoints differ; target checkout preserved')
        if inspect(*dest) != b:
            raise ValueError('Destination changed; target checkout preserved')
        ancestor = git(b['cwd'], 'merge-base', '--is-ancestor', 'HEAD', 'FETCH_HEAD', host=b['host'], check=False)
        if ancestor.returncode:
            raise ValueError('Destination is ahead or divergent; target checkout preserved')
        git(b['cwd'], 'merge', '--ff-only', 'FETCH_HEAD', host=b['host'])
        final_a, final_b = inspect(*source), inspect(*dest)
        if final_a['head'] != a['head'] or final_b['head'] != a['head']:
            raise ValueError('Concurrent updates detected; verify both checkouts')
    except Exception as error:
        raise RuntimeError(f'Source push completed; destination sync incomplete: {error}') from error
    return dict(plan, status='synchronized', sharedCommit=a['head'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, default=DEFAULT_PROFILE)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('profile', help='Show configured project pairs and latest chat IDs')
    doctor = commands.add_parser('doctor', help='Check existing machine, SSH, and Codex')
    doctor.add_argument('--wake', action='store_true', help='Wake only an automatically idle-suspended machine')
    create = commands.add_parser('create', help='Create one legacy local chat without starting a model turn')
    create.add_argument('--cwd', required=True)
    create.add_argument('--title', required=True)
    create.add_argument('--session', required=True)
    read = commands.add_parser('read', help='Read metadata and last assistant messages through official API')
    read.add_argument('--thread', required=True)
    read.add_argument('--ssh')
    remember = commands.add_parser('remember', help='Verify and record a successful Handoff destination')
    remember.add_argument('--session', required=True)
    remember.add_argument('--thread', required=True)
    remember.add_argument('--host-id', required=True)
    remember.add_argument('--cwd', required=True)
    remember.add_argument('--operation-id')
    sync = commands.add_parser('sync', help='Preview or apply a clean, committed Git transfer')
    sync.add_argument('--project', required=True)
    sync.add_argument('--direction', choices=['to-cloud', 'from-cloud'], required=True)
    sync.add_argument('--apply', action='store_true')
    sync.add_argument('--source-cwd')
    sync.add_argument('--dest-cwd')
    args = parser.parse_args()
    profile = load_profile(args.profile)
    if args.command == 'profile':
        emit(profile)
    elif args.command == 'read':
        emit(summary(read_thread(args.thread, args.ssh)))
    elif args.command == 'create':
        cwd = str(Path(args.cwd).expanduser().resolve(strict=True))
        git(cwd, 'rev-parse', '--show-toplevel')
        if args.session in profile.get('sessions', {}):
            raise ValueError('Session already exists; use another name to avoid losing its chat index')
        with AppServer() as server:
            thread = server.rpc('thread/start', {'cwd': cwd, 'historyMode': 'legacy'})['thread']
            # Print the durable ID immediately so a later title/index error cannot orphan it silently.
            emit({'createdThreadId': thread['id'], 'cwd': thread.get('cwd'), 'historyMode': thread.get('historyMode')})
            if thread.get('historyMode') != 'legacy':
                raise RuntimeError('Server did not return legacy; do not claim Handoff compatibility')
            server.rpc('thread/name/set', {'threadId': thread['id'], 'name': args.title})
        record = update_session(args.profile, args.session, {
            'threadId': thread['id'], 'hostId': 'local', 'cwd': thread['cwd'],
            'historyMode': 'legacy', 'title': args.title})
        emit({'session': args.session, 'record': record})
    elif args.command == 'remember':
        host = None
        if args.host_id != 'local':
            matches = {p['sshHost'] for p in profile.get('projects', {}).values() if p.get('hostId') == args.host_id}
            if len(matches) != 1:
                raise ValueError('Unknown/ambiguous hostId; register the discovered project first')
            host = matches.pop()
        thread = read_thread(args.thread, host, turns=False)
        if thread.get('historyMode') != 'legacy' or thread.get('cwd') != args.cwd:
            raise ValueError('Destination history mode/cwd mismatch; index unchanged')
        record = {'threadId': args.thread, 'hostId': args.host_id, 'cwd': args.cwd, 'historyMode': 'legacy'}
        if args.operation_id:
            record['operationId'] = args.operation_id
        emit(update_session(args.profile, args.session, record, replace=True))
    elif args.command == 'sync':
        if args.project not in profile.get('projects', {}):
            raise ValueError('Project not configured; select or prepare the correct project first')
        emit(synchronize(profile['projects'][args.project], args.direction, args.apply, args.source_cwd, args.dest_cwd))
    elif args.command == 'doctor':
        config = profile.get('instabox', {})
        cli = config.get('cli', 'instabox')
        machine, host = config['machine'], config['sshHost']
        if args.wake:
            run([cli, 'wake', machine], timeout=55)
        machine_info = json.loads(run([cli, 'get', machine, '--json']).stdout)
        probe = on_host(['python3', '-c', 'import json,platform,os; print(json.dumps({"hostname":platform.node(),"system":platform.system(),"home":os.path.expanduser("~")}))'], host)
        emit({'machine': machine, 'machineState': machine_info.get('status', machine_info.get('state')),
              'sshHost': host, 'ssh': json.loads(probe.stdout),
              'localCodex': run(['codex', '--version']).stdout.strip(),
              'remoteCodex': on_host(['codex', '--version'], host).stdout.strip()})


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        emit({'error': str(error) if not isinstance(error, KeyboardInterrupt) else 'Interrupted; inspect state before retry'})
        sys.exit(1)
