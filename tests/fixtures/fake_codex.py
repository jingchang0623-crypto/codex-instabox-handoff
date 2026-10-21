#!/usr/bin/env python3
"""Isolated JSONL App Server fixture. Never calls a model or reads real chats."""
import json
import sys

initialized = False
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        assert request['method'] == 'initialized'
        initialized = True
        continue
    method, params = request['method'], request['params']
    if method == 'initialize':
        result = {}
    else:
        assert initialized, 'Missing initialized notification'
        if method == 'thread/start':
            assert params['historyMode'] == 'legacy'
            assert set(params) == {'cwd', 'historyMode'}, 'Unexpected permission/model override'
            result = {'thread': {'id': 'test-thread', 'cwd': params['cwd'], 'historyMode': 'legacy'}}
        elif method == 'thread/name/set':
            result = {}
        elif method == 'thread/read':
            result = {'thread': {'id': 'test-thread', 'cwd': '/tmp/test', 'historyMode': 'legacy',
                      'turns': [{'status': 'completed', 'completedAt': 1, 'items': [
                          {'type': 'reasoning', 'text': 'PRIVATE_REASONING_SENTINEL'},
                          {'type': 'agentMessage', 'text': 'public result'}]}]}}
        else:
            raise ValueError(method)
    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
