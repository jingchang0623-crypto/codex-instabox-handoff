import unittest
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/instabox-handoff/scripts/handoff.py'

def call(argv, env=None, ok=True):
    if env is None:
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    p = subprocess.run([str(x) for x in argv], capture_output=True, text=True, env=env, timeout=30)
    if ok and p.returncode:
        raise AssertionError(p.stderr + p.stdout)
    return p

def git(path, *args):
    return call(['git', '-C', path, *args]).stdout.strip()

def commit(path, text):
    (path / 'app.txt').write_text(text)
    git(path, 'add', 'app.txt')
    git(path, 'commit', '-m', text)
    return git(path, 'rev-parse', 'HEAD')

class WorkflowTests(unittest.TestCase):
    def test_git_and_legacy_workflow(self):
        with tempfile.TemporaryDirectory(prefix='skill-handoff-') as temporary:
            base = Path(temporary)
            binary = base / 'bin'
            binary.mkdir()
            ssh = binary / 'ssh'
            ssh.write_text('#!/usr/bin/env python3\nimport os,sys\nos.execv("/bin/sh", ["sh", "-c", sys.argv[-1]])\n')
            ssh.chmod(0o700)
            fake = binary / 'codex'
            fake.write_bytes((ROOT/'tests/fixtures/fake_codex.py').read_bytes())
            fake.chmod(0o700)
            env = dict(os.environ, PATH=str(binary)+os.pathsep+os.environ['PATH'], GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
            bare, local, cloud = base / 'shared.git', base / 'local space', base / "cloud space's checkout"
            call(['git', 'init', '--bare', '--initial-branch=main', bare])
            call(['git', 'clone', bare, local])
            for path in (local,):
                git(path, 'config', 'user.name', 'Skill Test')
                git(path, 'config', 'user.email', 'skill-test@localhost')
            initial = commit(local, 'initial')
            git(local, 'push', '-u', 'origin', 'main')
            call(['git', 'clone', bare, cloud])
            git(cloud, 'config', 'user.name', 'Skill Test')
            git(cloud, 'config', 'user.email', 'skill-test@localhost')
            git(cloud, 'remote', 'add', 'sync', str(bare))
            profile = base / 'profile.json'
            profile.write_text(json.dumps({'schemaVersion':1,'projects':{'test':{
                'localPath':str(local),'remotePath':str(cloud),'sshHost':'fake-host',
                'origin':str(bare),'localRemote':'origin','remoteRemote':'sync'}},'sessions':{}}))
            def cli(*args, ok=True):
                return call(['python3', SCRIPT, '--profile', profile, *args], env=env, ok=ok)
            first = commit(local, 'local update')
            preview = cli('sync','--project','test','--direction','to-cloud')
            assert json.loads(preview.stdout)['mode']=='preview'
            assert git(bare,'rev-parse','main')==initial
            cli('sync','--project','test','--direction','to-cloud','--apply')
            assert git(cloud,'rev-parse','HEAD')==first
            second = commit(cloud, 'cloud update')
            cli('sync','--project','test','--direction','from-cloud','--apply')
            assert git(local,'rev-parse','HEAD')==second
            (cloud/'unrelated.txt').write_text('keep me')
            third = commit(local,'next local')
            denied=cli('sync','--project','test','--direction','to-cloud','--apply',ok=False)
            assert denied.returncode and 'Dirty checkout preserved' in denied.stdout
            assert git(bare,'rev-parse','main')==second
            assert (cloud/'unrelated.txt').read_text()=='keep me'
            (cloud/'unrelated.txt').unlink()
            git(cloud, 'checkout', '-b', 'another-branch')
            branch_denied=cli('sync','--project','test','--direction','to-cloud','--apply',ok=False)
            assert branch_denied.returncode and 'Branches differ' in branch_denied.stdout
            assert git(bare,'rev-parse','main')==second
            git(cloud, 'checkout', 'main')
            divergent=commit(cloud,'independent cloud')
            denied=cli('sync','--project','test','--direction','to-cloud','--apply',ok=False)
            assert denied.returncode and 'Source push completed' in denied.stdout
            assert git(cloud,'rev-parse','HEAD')==divergent
            assert git(bare,'rev-parse','main')==third
            created=cli('create','--cwd',str(local),'--title','兼容测试','--session','test')
            state=json.loads(profile.read_text())
            assert state['sessions']['test']['threadId']=='test-thread'
            assert state['projects']['test']['origin']==str(bare)
            duplicate=cli('create','--cwd',str(local),'--title','duplicate','--session','test',ok=False)
            assert duplicate.returncode
            read=cli('read','--thread','test-thread')
            assert 'PRIVATE_REASONING_SENTINEL' not in read.stdout
            assert 'public result' in read.stdout
            invalid=cli('read','--thread','test-thread','--ssh=-oProxyCommand=bad',ok=False)
            assert invalid.returncode and 'Use a saved SSH alias' in invalid.stdout
            print(json.dumps({'preview_no_mutation':'passed','git_bidirectional_with_quoted_paths':'passed',
                'dirty_refusal_before_push':'passed','divergent_target_preserved':'passed',
                'legacy_protocol_no_permission_overrides':'passed','session_collision_guard':'passed',
                'reasoning_omitted':'passed','ssh_option_rejection':'passed'},indent=2))
