#!/usr/bin/env python3
"""Test double. No real CLI, network, credentials or model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if '--child' in sys.argv:
    time.sleep(120)
    raise SystemExit(0)
incoming = json.loads(sys.stdin.readline())
assert sys.stdin.read() == ''
assert incoming['event'] == 'user'
message = incoming['message']['content']
question = message.split('\nQuestion:\n', 1)[1].split('\nUNTRUSTED_SOURCE_JSON:\n', 1)[0]
sources = json.loads(message.split('\nUNTRUSTED_SOURCE_JSON:\n', 1)[1])
if question in ('live_denied_stdout','live_denied_stderr','live_external_tool','live_step_error','live_empty_finish'):
    child = subprocess.Popen([sys.executable, __file__, '--child'])
    Path('pids.json').write_text(json.dumps([os.getpid(), child.pid]))
    if question != 'live_denied_stderr':
        if question == 'live_external_tool':
            event = json.dumps({'event':'step_update','step_update':{'tool_name':'view_file',
                               'tool_info':{'name':'view_file','parameters':{'AbsolutePath':'/fake/path'}}}})+'\n'
        elif question == 'live_step_error':
            event = json.dumps({'event':'step_update','step_update':{'step_type':'error_message','state':'DONE'}})+'\n'
        elif question == 'live_empty_finish':
            event = json.dumps({'event':'step_update','step_update':{'step_type':'tool','state':'ACTIVE','tool_name':'finish',
                               'tool_info':{'name':'finish','parameters':{'findings':[]}}}})+'\n'
        else:
            event = json.dumps({'event':'progress','denied_actions':[{'action':'RunCommand'}]})+'\n'
        sys.stdout.write(event[:17]); sys.stdout.flush(); time.sleep(0.05)
        sys.stdout.write(event[17:]); sys.stdout.flush()
    else:
        sys.stderr.write('RunCommand auto-'); sys.stderr.flush(); time.sleep(0.05)
        sys.stderr.write('denied\n'); sys.stderr.flush()
    time.sleep(120)
if question in ('timeout', 'cancel', 'hold'):
    child = subprocess.Popen([sys.executable, __file__, '--child'])
    Path('pids.json').write_text(json.dumps([os.getpid(), child.pid]))
    time.sleep(120)
if question == 'stdout_limit':
    sys.stdout.write('x' * (3*1024*1024)); sys.stdout.flush(); time.sleep(120)
if question == 'stderr_limit':
    sys.stderr.write('x' * (300*1024)); sys.stderr.flush(); time.sleep(120)
if question == 'invalid_json':
    print('{oops'); raise SystemExit(0)
if question == 'empty':
    raise SystemExit(0)
if question == 'exit':
    raise SystemExit(3)
if question == 'denied_stderr':
    print('RunCommand auto-denied', file=sys.stderr)
lines = sources[0]['numbered_lines']
index = next((i for i, line in enumerate(lines) if 'bridge_marker=' in line), 0)
obj = {'findings': [{'claim': 'The supplied source contains this marker.', 'evidence': [{
    'file': sources[0]['name'], 'start_line': index+1, 'end_line': index+1,
    'quote': lines[index].split('| ',1)[1]}]}]}
if question == 'bad_quote':
    obj['findings'][0]['evidence'][0]['quote'] = 'invented'
if question == 'bad_type':
    obj['findings'][0]['evidence'][0]['start_line'] = True
if question == 'empty_findings':
    obj['findings'] = []
result = {'status': 'SUCCESS', 'response': 'Free text is deliberately not JSON.', 'structured_output': obj}
if question == 'no_structured':
    result.pop('structured_output'); result['response'] = json.dumps(obj)
if question == 'denied':
    result['denied_actions'] = ['RunCommand']
if question == 'status':
    result['status'] = 'ERROR'
print(json.dumps({'event': 'init'}))
print(json.dumps({'event': 'result', 'result': result}))
if question == 'duplicate_result':
    print(json.dumps({'event': 'result', 'result': result}))
