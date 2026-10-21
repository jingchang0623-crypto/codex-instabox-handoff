import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


waker=load('ci_waker',ROOT/'ci/waker.py')
guard=load('ci_job_guard',ROOT/'ci/job_guard.py')


def workflow(**changes):
    return dict({'id':101,'run_attempt':1,'event':'push','head_branch':'main',
                 'path':'.github/workflows/tests.yml','head_repository':{'full_name':'example/repository'}},**changes)


class WakerTests(unittest.TestCase):
    def setUp(self):
        self.config={'repository':'example/repository','machine':'dedicated-ci','label':'instabox-ci',
                     'gh':'gh','instabox':'instabox','cooldownSeconds':120}
        self.calls=[]
        self.workflows=[workflow()]
        self.jobs=[{'id':201,'status':'queued','labels':['instabox-ci']}]
        self.machine_state='suspended'

    def fake(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0]=='gh':
            route=argv[-1]
            if '/jobs?' in route:
                return json.dumps({'jobs':self.jobs})
            return json.dumps({'workflow_runs':self.workflows if 'status=queued' in route else []})
        if argv[1]=='get':
            return json.dumps({'state':self.machine_state})
        return 'ok'

    def test_queue_resumes_only_selected_machine_with_no_vault(self):
        state, record=waker.tick(self.config,{},self.fake,now=1000)
        self.assertEqual(record['action'],'resumed')
        self.assertIn(['instabox','resume','dedicated-ci','--no-vault'],self.calls)
        self.assertEqual(state['lastAction']['jobs'],[{'runId':101,'jobId':201,'attempt':1}])

    def test_no_queue_no_machine_activity(self):
        self.workflows=[]
        state,record=waker.tick(self.config,{},self.fake,now=1000)
        self.assertIsNone(record)
        self.assertFalse(any(c[0]=='instabox' for c in self.calls))

    def test_untrusted_events_refs_and_workflows_never_wake(self):
        for item in (workflow(event='pull_request'),workflow(head_branch='other'),
                     workflow(path='.github/workflows/other.yml'),
                     workflow(head_repository={'full_name':'attacker/fork'})):
            self.calls=[]
            self.workflows=[item]
            _,record=waker.tick(self.config,{},self.fake,now=1000)
            self.assertIsNone(record)
            self.assertFalse(any(c[0]=='instabox' for c in self.calls))

    def test_label_filter_and_cooldown(self):
        self.jobs=[{'id':201,'status':'queued','labels':['ubuntu-latest']}]
        _,record=waker.tick(self.config,{},self.fake,now=1000)
        self.assertIsNone(record)
        self.jobs=[{'id':201,'status':'queued','labels':['instabox-ci']}]
        _,record=waker.tick(self.config,{'lastWakeAt':950},self.fake,now=1000)
        self.assertIsNone(record)
        self.assertFalse(any(c[0]=='instabox' for c in self.calls))

    def test_stopped_starts_running_does_not_probe_or_resume(self):
        self.machine_state='stopped'
        _,record=waker.tick(self.config,{},self.fake,now=1000)
        self.assertEqual(record['action'],'started')
        self.machine_state='running'
        self.calls=[]
        _,record=waker.tick(self.config,{},self.fake,now=1000)
        self.assertEqual(record['action'],'already-running')
        self.assertFalse(any(c[0]=='instabox' and c[1]!='get' for c in self.calls))


class GuardTests(unittest.TestCase):
    def test_default_deny_and_trusted_push_dispatch(self):
        env={'GITHUB_REPOSITORY':'example/repository','GITHUB_REF':'refs/heads/main','GITHUB_EVENT_NAME':'push'}
        self.assertTrue(guard.allowed_job(env,'example/repository'))
        self.assertTrue(guard.allowed_job(dict(env,GITHUB_EVENT_NAME='workflow_dispatch'),'example/repository'))
        self.assertFalse(guard.allowed_job({},'example/repository'))
        self.assertFalse(guard.allowed_job(dict(env,GITHUB_EVENT_NAME='pull_request'),'example/repository'))
        self.assertFalse(guard.allowed_job(dict(env,GITHUB_REF='refs/heads/other'),'example/repository'))
        self.assertFalse(guard.allowed_job(dict(env,GITHUB_REPOSITORY='attacker/fork'),'example/repository'))
