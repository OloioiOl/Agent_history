#!/usr/bin/env python3
"""Linux-only, single-flight Unix socket service. No network listener or shell."""
import argparse
import asyncio
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import struct
import time
import uuid

from bridge_core import (Failure, MAX_REQUEST, MAX_STDOUT, MAX_STDERR, MAX_REPLY,
                         MODELS, SCHEMA, adjudicate, decode, encode, make_reply,
                         prompt, require, validate_request, LiveOutputGuard)


def save(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw)


def prune(root, days=7):
    """Only deletes bridge UUID directories, never arbitrary caller paths."""
    cutoff = time.time() - days * 86400
    for p in root.iterdir():
        if re.fullmatch(r'[0-9a-f]{32}', p.name) and not p.is_symlink() and p.is_dir() and p.stat().st_mtime < cutoff:
            shutil.rmtree(p)


def stored_bytes(root):
    return sum(p.lstat().st_size for p in root.rglob('*') if not p.is_symlink() and p.is_file())


async def drain_and_reap(proc, timeout=5):
    """After killing, drain discarded bytes so paused pipe transports can reach EOF."""
    async def discard(stream):
        while await stream.read(65536):
            pass

    cleanup = asyncio.gather(discard(proc.stdout), discard(proc.stderr), proc.wait())
    try:
        await asyncio.wait_for(cleanup, timeout)
    except asyncio.TimeoutError:
        # Last-resort CPython asyncio transport close; do not wait forever on pipes
        # held by an escaped descendant. Report failure, never successful cleanup.
        proc._transport.close()
        raise Failure('CLEANUP_TIMEOUT') from None


async def execute(command, data, cwd, timeout, stdout_path, stderr_path):
    """Concurrent bounded readers; timeout includes stdin delivery and draining."""
    proc = None
    tasks = []
    chunks = [bytearray(), bytearray()]
    completed = False
    cleanup_error = None
    live = LiveOutputGuard()
    try:
        proc = await asyncio.create_subprocess_exec(*command, cwd=cwd, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)

        async def read(stream, target, cap, observe, finish=None):
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    if finish:
                        finish()
                    return
                remaining = cap-len(target)
                target.extend(chunk[:remaining])
                require(len(chunk) <= remaining, 'OUTPUT_LIMIT')
                observe(chunk)

        async def write():
            try:
                proc.stdin.write(data)
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                proc.stdin.close()

        tasks = [asyncio.create_task(read(proc.stdout, chunks[0], MAX_STDOUT, live.stdout, live.finish)),
                 asyncio.create_task(read(proc.stderr, chunks[1], MAX_STDERR, live.stderr)),
                 asyncio.create_task(write()), asyncio.create_task(proc.wait())]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout)
        except asyncio.TimeoutError:
            raise Failure('TIMEOUT') from None
        completed = True
        return bytes(chunks[0]), bytes(chunks[1]), proc.returncode
    finally:
        if proc is not None:
            # Always kill group, even when leader exited and a descendant holds pipes.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await drain_and_reap(proc)
            except Failure as e:
                cleanup_error = e
        save(stdout_path, bytes(chunks[0]))
        save(stderr_path, bytes(chunks[1]))
        save(Path(stdout_path).parent/'process.json', encode({
            'returncode': proc.returncode if proc is not None else None,
            'capture_complete': completed and cleanup_error is None,
            'cleanup_error': cleanup_error.code if cleanup_error else None,
            'stdout_bytes':len(chunks[0]), 'stderr_bytes':len(chunks[1])}))
        if cleanup_error:
            raise cleanup_error


class Bridge:
    def __init__(self, config):
        self.config = config
        self.busy = False
        self.clients = set()
        self.root = Path(config['results'])

    async def run_request(self, req):
        sources = validate_request(req)
        prune(self.root)
        # Reserve enough for request, escaped prompt-free artifacts and bounded output.
        require(stored_bytes(self.root) < 128*1024*1024-12*1024*1024, 'STORAGE_LIMIT')
        result_id = uuid.uuid4().hex
        run = self.root/result_id
        run.mkdir(mode=0o700)
        workspace = run/'workspace'
        workspace.mkdir(mode=0o700)
        result = {'ok': False, 'error': 'INTERNAL_ERROR', 'result_id': result_id}
        returncode = None
        try:
            save(run/'request.json', encode({**req, 'files': [{'name': n, 'content': c} for n, c in sources.items()]}))
            save(run/'schema.json', encode(SCHEMA))
            command = [self.config['agy'], '--mode', 'plan', '--model', MODELS[req['model']],
                       '--output-format', 'stream-json', '--json-schema', str(run/'schema.json'),
                       '--input-format', 'stream-json', '--print-timeout', '600s', '-p', '']
            data = encode({'event': 'user', 'message': {'content': prompt(req['question'], sources)}}) + b'\n'
            stdout, stderr, returncode = await execute(command, data, workspace,
                    self.config.get('timeout_seconds', 630), run/'stdout.ndjson', run/'stderr.bin')
            structured = adjudicate(stdout, stderr, returncode, sources)
            result = make_reply(result_id, structured)
        except Failure as e:
            result['error'] = e.code
        except asyncio.CancelledError:
            result['error'] = 'CANCELLED'
            raise
        except Exception:
            # Never send exception text, command output or private paths to the caller.
            result['error'] = 'INTERNAL_ERROR'
        finally:
            save(run/'verdict.json', encode({'timestamp': time.time(), 'returncode': returncode, **result}))
        return result

    async def handle(self, reader, writer):
        me = asyncio.current_task()
        if len(self.clients) >= 8:
            writer.close()
            return
        self.clients.add(me)
        work = disconnect = None
        acquired = False
        try:
            peer = writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            _, uid, _ = struct.unpack('3i', peer)
            require(uid in self.config['allowed_uids'], 'PEER_DENIED')
            size, = struct.unpack('!I', await asyncio.wait_for(reader.readexactly(4), 10))
            require(0 < size <= MAX_REQUEST, 'INPUT_LIMIT')
            raw = await asyncio.wait_for(reader.readexactly(size), 10)
            req = decode(raw)
            validate_request(req)
            require(not self.busy, 'BUSY')
            self.busy = acquired = True
            work = asyncio.create_task(self.run_request(req))
            # Exactly one frame per connection; EOF or extra bytes cancels this request.
            disconnect = asyncio.create_task(reader.read(1))
            done, _ = await asyncio.wait([work, disconnect], return_when=asyncio.FIRST_COMPLETED)
            if disconnect in done:
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                return
            response = await work
            self.busy = acquired = False
            await self.reply(writer, response)
        except Failure as e:
            await self.reply(writer, {'ok': False, 'error': e.code})
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, OSError):
            pass
        finally:
            for task in (work, disconnect):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(t for t in (work, disconnect) if t is not None), return_exceptions=True)
            if acquired:
                self.busy = False
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            self.clients.discard(me)

    async def reply(self, writer, response):
        raw = encode(response)
        require(len(raw) <= MAX_REPLY, 'REPLY_LIMIT')
        writer.write(struct.pack('!I', len(raw)) + raw)
        with contextlib.suppress(ConnectionError, OSError, asyncio.TimeoutError):
            await asyncio.wait_for(writer.drain(), 5)


async def serve(config):
    require(os.name == 'posix' and hasattr(socket, 'SO_PEERCRED'), 'LINUX_REQUIRED')
    os.umask(0o077)
    bridge = Bridge(config)
    require(bridge.root.is_dir() and not bridge.root.is_symlink(), 'BAD_RESULTS_DIRECTORY')
    require((bridge.root.stat().st_mode & 0o077) == 0 and bridge.root.stat().st_uid == os.getuid(), 'BAD_RESULTS_PERMISSIONS')
    prune(bridge.root)
    path = Path(config['socket'])
    if path.exists() or path.is_symlink():
        require(stat.S_ISSOCK(path.lstat().st_mode) and path.lstat().st_uid == os.getuid(), 'UNSAFE_SOCKET')
        # Only remove an unresponsive socket; never steal a running listener.
        with socket.socket(socket.AF_UNIX) as probe:
            try:
                probe.connect(str(path))
            except ConnectionRefusedError:
                path.unlink()
            else:
                raise Failure('SOCKET_IN_USE')
    server = await asyncio.start_unix_server(bridge.handle, path=str(path), limit=65536)
    os.chmod(path, 0o660)
    if 'socket_gid' in config:
        os.chown(path, -1, config['socket_gid'])
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async def housekeeping():
        while True:
            await asyncio.sleep(3600)
            prune(bridge.root)

    cleaner = asyncio.create_task(housekeeping())
    try:
        async with server:
            await stop.wait()
    finally:
        cleaner.cancel()
        clients = list(bridge.clients)
        for task in clients:
            task.cancel()
        await asyncio.gather(cleaner, *clients, return_exceptions=True)
        path.unlink(missing_ok=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    a = p.parse_args()
    with open(a.config, encoding='utf-8') as f:
        config = json.load(f)
    asyncio.run(serve(config))
