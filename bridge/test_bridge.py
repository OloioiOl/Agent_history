import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest

from bridge_core import *
from bridge_service import Bridge, drain_and_reap
from safe_files import read_sources


def request(question='success', content='alpha\nbridge_marker=sample_7391\ngamma\n'):
    return {'model': 'flash', 'question': question, 'files': [{'name': 'inbox/sample.txt', 'content': content}]}


def valid():
    return {'findings': [{'claim': 'marker', 'evidence': [{'file': 'inbox/sample.txt', 'start_line': 2,
            'end_line': 2, 'quote': 'bridge_marker=sample_7391'}]}]}


class Validation(unittest.TestCase):
    def test_empty_submission_is_allowed_but_never_success(self):
        self.assertEqual(SCHEMA['properties']['findings']['minItems'],0)
        with self.assertRaisesRegex(Failure,'NO_VALID_FINDINGS'):
            validate_structured({'findings':[]},validate_request(request()))
        raw=encode({'event':'result','result':{'status':'SUCCESS','structured_output':{'findings':[]}}})
        with self.assertRaisesRegex(Failure,'NO_VALID_FINDINGS'):
            adjudicate(raw,b'',0,validate_request(request()))

    def test_error_step_and_empty_finish_fail_before_final_result(self):
        for step,code in [({'step_type':'error_message','state':'DONE'},'AGY_STEP_ERROR'),
                          ({'step_type':'tool','state':'ERROR','tool_name':'finish'},'AGY_TOOL_ERROR'),
                          ({'tool_name':'finish','tool_info':{'name':'finish','parameters':{'findings':[]}}},'NO_VALID_FINDINGS')]:
            raw=encode({'event':'step_update','step_update':step})+b'\n'
            with self.assertRaisesRegex(Failure,code): LiveOutputGuard().stdout(raw)

    def test_tool_catalog_and_mentions_do_not_trigger_policy(self):
        guard=LiveOutputGuard()
        guard.stdout(encode({'event':'init','init':{'tools':['view_file','run_command']}})+b'\n')
        guard.stdout(encode({'event':'step_update','step_update':{'text_delta':'view_file and run_command'}})+b'\n')
        guard.finish()

    def test_external_tool_metadata_is_rejected_live_and_offline(self):
        for step in ({'tool_name':'view_file'}, {'tool_info':{'name':'run_command','parameters':{}}}):
            raw=encode({'event':'step_update','step_update':step})+b'\n'
            with self.assertRaisesRegex(Failure,'EXTERNAL_TOOL_OBSERVED'): LiveOutputGuard().stdout(raw)
            with self.assertRaisesRegex(Failure,'EXTERNAL_TOOL_OBSERVED'):
                adjudicate(raw,b'',0,validate_request(request()))

    def test_live_guard_chunked_events_and_stderr(self):
        guard=LiveOutputGuard()
        payload=encode({'event':'progress','denied_actions':[{'action':'RunCommand'}]})
        for byte in payload:
            guard.stdout(bytes([byte]))
        with self.assertRaisesRegex(Failure,'PERMISSION_DENIED'): guard.stdout(b'\n')
        guard=LiveOutputGuard(); guard.stderr(b'RunCommand auto-')
        with self.assertRaisesRegex(Failure,'PERMISSION_DENIED'): guard.stderr(b'denied\n')

    def test_live_guard_text_is_not_a_tool_event(self):
        guard=LiveOutputGuard()
        guard.stdout(encode({'event':'message','content':'RunCommand auto-denied is discussed in the source.'})+b'\n')
        guard.finish()
        self.assertEqual(guard.events_seen,1)

    def test_live_guard_final_line_without_newline(self):
        guard=LiveOutputGuard()
        guard.stdout(encode({'event':'result','result':{'denied_actions':['RunCommand']}}))
        with self.assertRaisesRegex(Failure,'PERMISSION_DENIED'): guard.finish()

    def test_valid_and_no_response_fallback(self):
        sources = validate_request(request())
        self.assertEqual(validate_structured(valid(), sources), valid())
        with self.assertRaisesRegex(Failure, 'BAD_STRUCTURED_OUTPUT'):
            adjudicate(encode({'event':'result', 'result': {'status':'SUCCESS', 'response':json.dumps(valid())}}), b'', 0, sources)

    def test_bad_evidence_never_silently_removed(self):
        for field, value in [('quote','invented'), ('file','other.txt'), ('start_line',True), ('end_line',200)]:
            with self.subTest(field=field):
                obj = valid(); bad = copy.deepcopy(obj['findings'][0]['evidence'][0]); bad[field] = value
                obj['findings'][0]['evidence'].append(bad)
                with self.assertRaises(Failure):
                    validate_structured(obj, validate_request(request()))

    def test_request_validation(self):
        variants = [dict(request(), model='opus'), dict(request(), model=[]), dict(request(), question=''),
                    dict(request(), files=[]), dict(request(), command='sh'), request(content='x'*(MAX_CONTENT+1))]
        for req in variants:
            with self.subTest(req_type=list(req)):
                with self.assertRaises(Failure): validate_request(req)

    def test_duplicate_keys_and_nonfinite(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'not json', b'\xff'):
            with self.assertRaises(Failure): decode(raw)

    def test_result_count_denial_and_malformed(self):
        result=encode({'event':'result','result':{'status':'SUCCESS','structured_output':valid()}})
        for stdout, stderr, rc in [(b'',b'',0), (result+b'\n'+result,b'',0), (b'warning\n'+result,b'',0),
                                   (result,b'RunCommand auto-denied',0),(result,b'',1),
                                   (encode({'event':'progress','denied_actions':['read_url']})+b'\n'+result,b'',0)]:
            with self.assertRaises(Failure): adjudicate(stdout,stderr,rc,validate_request(request()))

    def test_reply_is_not_truncated(self):
        obj=valid(); obj['findings'][0]['claim']='가'*1800
        obj['findings'] *= 8
        with self.assertRaisesRegex(Failure,'REPLY_LIMIT'): make_reply('a'*32,obj)

    def test_newline_normalization(self):
        sources=validate_request(request(content='alpha\r\nbridge_marker=sample_7391\r\ngamma\r\n'))
        self.assertEqual(validate_structured(valid(),sources),valid())

    def test_plugin_registration_contract(self):
        path=Path(__file__).parent
        spec=importlib.util.spec_from_file_location('test_bulk_plugin',path/'__init__.py',submodule_search_locations=[str(path)])
        module=importlib.util.module_from_spec(spec); sys.modules[spec.name]=module; spec.loader.exec_module(module)
        class Context:
            def register_tool(self,**kwargs): self.kwargs=kwargs; return object()
        ctx=Context(); module.register(ctx)
        self.assertTrue(ctx.kwargs['is_async']); self.assertEqual(ctx.kwargs['name'],'bulk_analyze')


@unittest.skipUnless(sys.platform=='linux','cleanup regression executes on target Linux')
class CleanupRegression(unittest.IsolatedAsyncioTestCase):
    async def test_reap_requires_both_pipes_drained(self):
        # Models asyncio's paused-pipe wait: process exit alone is insufficient.
        class Stream:
            def __init__(self): self.eof=asyncio.Event(); self.reads=0
            async def read(self, size):
                self.reads+=1
                if self.reads==1: return b'x'*size
                self.eof.set(); return b''
        class Process:
            def __init__(self): self.stdout=Stream(); self.stderr=Stream()
            async def wait(self):
                await self.stdout.eof.wait(); await self.stderr.eof.wait(); return -9
        proc=Process()
        await drain_and_reap(proc,timeout=0.5)
        self.assertEqual(proc.stdout.reads,2); self.assertEqual(proc.stderr.reads,2)

    async def test_cleanup_has_its_own_deadline(self):
        class Stream:
            async def read(self,size): await asyncio.Event().wait()
        class Transport:
            closed=False
            def close(self): self.closed=True
        class Process:
            stdout=Stream(); stderr=Stream(); _transport=Transport()
            async def wait(self): await asyncio.Event().wait()
        proc=Process()
        with self.assertRaisesRegex(Failure,'CLEANUP_TIMEOUT'):
            await drain_and_reap(proc,timeout=0.03)
        self.assertTrue(proc._transport.closed)


@unittest.skipUnless(sys.platform=='linux','requires Linux openat, Unix sockets, SO_PEERCRED and killpg')
class LinuxIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='agy-bridge-test-')
        self.root=Path(self.temp.name)
        self.runs=self.root/'runs'; self.runs.mkdir(mode=0o700)
        fake=Path(__file__).parent/'fake_agy.py'; fake.chmod(0o755)
        self.bridge=Bridge({'agy':str(fake.resolve()), 'results':str(self.runs), 'allowed_uids':[os.getuid()], 'timeout_seconds':0.8})
        self.sock=str(self.root/'s')
        self.server=await asyncio.start_unix_server(self.bridge.handle,path=self.sock)

    async def asyncTearDown(self):
        self.server.close(); await self.server.wait_closed()
        for task in list(self.bridge.clients): task.cancel()
        await asyncio.gather(*list(self.bridge.clients),return_exceptions=True)
        self.temp.cleanup()

    async def call(self, req):
        r,w=await asyncio.open_unix_connection(self.sock)
        raw=encode(req); w.write(struct.pack('!I',len(raw))+raw); await w.drain()
        n,=struct.unpack('!I',await r.readexactly(4)); result=decode(await r.readexactly(n))
        w.close(); await w.wait_closed()
        return result

    async def test_success_and_failure_matrix(self):
        expected={'success':None,'empty':'RESULT_COUNT','invalid_json':'INVALID_JSON','denied':'PERMISSION_DENIED',
                  'denied_stderr':'PERMISSION_DENIED','stdout_limit':'OUTPUT_LIMIT','stderr_limit':'OUTPUT_LIMIT',
                  'timeout':'TIMEOUT','duplicate_result':'RESULT_COUNT','bad_quote':'EVIDENCE_QUOTE',
                  'bad_type':'EVIDENCE_RANGE','no_structured':'BAD_STRUCTURED_OUTPUT','status':'AGY_STATUS','exit':'AGY_EXIT',
                  'empty_findings':'NO_VALID_FINDINGS'}
        for question,code in expected.items():
            with self.subTest(question=question):
                print(f'  CASE {question}: starting',flush=True)
                result=await self.call(request(question))
                self.assertEqual(result.get('error'),code)
                if code is None: self.assertTrue(result['ok'])
                run=self.runs/result['result_id']
                self.assertTrue((run/'stdout.ndjson').exists()); self.assertTrue((run/'verdict.json').exists())
                self.assertEqual((run/'request.json').stat().st_mode & 0o777,0o600)
                print(f'  CASE {question}: passed',flush=True)

    async def wait_pids(self):
        for _ in range(200):
            files=list(self.runs.glob('*/workspace/pids.json'))
            if files: return json.loads(files[0].read_text())
            await asyncio.sleep(0.01)
        self.fail('fake child not started')

    async def assert_dead(self,pids):
        for _ in range(100):
            alive=[]
            for pid in pids:
                status=Path(f'/proc/{pid}/stat')
                if status.exists() and status.read_text().split()[2]!='Z': alive.append(pid)
            if not alive: return
            await asyncio.sleep(0.01)
        self.fail(f'processes survived: {alive}')

    async def test_cancel_kills_group_and_releases_slot(self):
        r,w=await asyncio.open_unix_connection(self.sock)
        raw=encode(request('cancel')); w.write(struct.pack('!I',len(raw))+raw); await w.drain()
        pids=await self.wait_pids(); w.close(); await w.wait_closed()
        await self.assert_dead(pids)
        for _ in range(100):
            if not self.bridge.busy: break
            await asyncio.sleep(0.01)
        self.assertFalse(self.bridge.busy)
        verdicts=[decode(p.read_bytes()) for p in self.runs.glob('*/verdict.json')]
        self.assertEqual(verdicts[0]['error'],'CANCELLED')
        self.assertTrue((await self.call(request()))['ok'])

    async def test_async_client_cancellation(self):
        from bulk_analyze_client import analyze_async
        inbox=self.root/'input'; inbox.mkdir(); (inbox/'sample.txt').write_text('bridge_marker=cancel_test\n')
        task=asyncio.create_task(analyze_async({'socket':self.sock,'roots':{'inbox':str(inbox)}},'flash','cancel',['inbox/sample.txt']))
        pids=await self.wait_pids(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        await self.assert_dead(pids)

    async def test_timeout_kills_descendants(self):
        task=asyncio.create_task(self.call(request('timeout')))
        pids=await self.wait_pids()
        self.assertEqual((await task)['error'],'TIMEOUT'); await self.assert_dead(pids)

    async def test_live_denials_abort_before_timeout_and_kill_children(self):
        for question in ('live_denied_stdout','live_denied_stderr','live_external_tool','live_step_error','live_empty_finish'):
            with self.subTest(question=question):
                print(f'  CASE {question}: starting',flush=True)
                result=await self.call(request(question))
                codes={'live_external_tool':'EXTERNAL_TOOL_OBSERVED','live_step_error':'AGY_STEP_ERROR','live_empty_finish':'NO_VALID_FINDINGS'}
                self.assertEqual(result['error'],codes.get(question,'PERMISSION_DENIED'))
                run=self.runs/result['result_id']
                pids=decode((run/'workspace/pids.json').read_bytes())
                await self.assert_dead(pids)
                self.assertFalse(decode((run/'process.json').read_bytes())['capture_complete'])
                self.assertFalse(self.bridge.busy)
                print(f'  CASE {question}: passed',flush=True)

    async def test_concurrency_one(self):
        first=asyncio.create_task(self.call(request('hold'))); await self.wait_pids()
        self.assertEqual((await self.call(request()))['error'],'BUSY')
        self.assertEqual(len(list(self.runs.iterdir())),1)
        await first

    async def test_peer_denial(self):
        self.bridge.config['allowed_uids']=[]
        self.assertEqual((await self.call(request()))['error'],'PEER_DENIED')
        self.assertEqual(list(self.runs.iterdir()),[])

    async def test_oversized_frame(self):
        r,w=await asyncio.open_unix_connection(self.sock)
        w.write(struct.pack('!I',MAX_REQUEST+1)); await w.drain()
        n,=struct.unpack('!I',await r.readexactly(4))
        self.assertEqual(decode(await r.readexactly(n))['error'],'INPUT_LIMIT')
        w.close(); await w.wait_closed()

    async def test_large_inline_payload(self):
        content=('padding data 0123456789\n'*42000)+'bridge_marker=large_8192\n'
        self.assertGreater(len(content),900000)
        result=await self.call(request(content=content))
        self.assertTrue(result['ok']); self.assertLessEqual(len(encode(result)),MAX_REPLY)
        self.assertEqual(result['findings'][0]['evidence'][0]['start_line'],42001)

    async def test_path_boundaries(self):
        inbox=self.root/'inbox'; inbox.mkdir(); (inbox/'ok.txt').write_text('allowed')
        outside=self.root/'private.txt'; outside.write_text('private')
        (inbox/'link.txt').symlink_to(outside)
        (inbox/'sub').symlink_to(self.root, target_is_directory=True)
        os.link(outside,inbox/'hard.txt')
        (inbox/'.env.txt').write_text('private')
        roots={'inbox':str(inbox)}
        self.assertEqual(read_sources(roots,['inbox/ok.txt'])[0]['content'],'allowed')
        for name in ('inbox/../private.txt','inbox/link.txt','inbox/sub/private.txt','inbox/hard.txt','inbox/.env.txt','other/ok.txt','/etc/passwd'):
            with self.subTest(name=name):
                with self.assertRaises(Failure): read_sources(roots,[name])


if __name__=='__main__': unittest.main(verbosity=2)
