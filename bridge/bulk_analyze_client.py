"""Hermes-independent tool body. Loader registration waits for installed API probe."""
import json
import socket
import struct
import asyncio
import contextlib
if __package__:
    from .bridge_core import Failure, MAX_REPLY, encode, decode, validate_request
    from .safe_files import read_sources
else:
    from bridge_core import Failure, MAX_REPLY, encode, decode, validate_request
    from safe_files import read_sources


async def analyze_async(config, model, question, files):
    writer = None
    try:
        request = {'model': model, 'question': question, 'files': read_sources(config['roots'], files)}
        validate_request(request)
        data = encode(request)
        async with asyncio.timeout(650):
            reader, writer = await asyncio.open_unix_connection(config['socket'])
            writer.write(struct.pack('!I', len(data)) + data)
            await writer.drain()
            size, = struct.unpack('!I', await reader.readexactly(4))
            if not 0 < size <= MAX_REPLY:
                raise Failure('REPLY_LIMIT')
            return decode(await reader.readexactly(size))
    except Failure as e:
        return {'ok': False, 'error': e.code}
    except (OSError, KeyError, TypeError, asyncio.IncompleteReadError, TimeoutError):
        return {'ok': False, 'error': 'CLIENT_CONFIG_OR_IO'}
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()


def recv_exact(sock, size):
    chunks = bytearray()
    while len(chunks) < size:
        b = sock.recv(size-len(chunks))
        if not b:
            raise Failure('BRIDGE_DISCONNECTED')
        chunks.extend(b)
    return bytes(chunks)


def analyze(config, model, question, files):
    try:
        request = {'model': model, 'question': question, 'files': read_sources(config['roots'], files)}
        validate_request(request)
        data = encode(request)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(650)
            sock.connect(config['socket'])
            sock.sendall(struct.pack('!I', len(data)) + data)
            size, = struct.unpack('!I', recv_exact(sock, 4))
            if not 0 < size <= MAX_REPLY:
                raise Failure('REPLY_LIMIT')
            return decode(recv_exact(sock, size))
    except Failure as e:
        return {'ok': False, 'error': e.code}
    except (OSError, KeyError, TypeError):
        return {'ok': False, 'error': 'CLIENT_CONFIG_OR_IO'}


TOOL_SCHEMA = {'name': 'bulk_analyze', 'description': 'Analyze approved UTF-8 source files through agy with verified exact source quotations. Alias paths only, e.g. inbox/example.md.',
               'parameters': {'type': 'object', 'additionalProperties': False,
                              'required': ['model', 'question', 'files'], 'properties': {
                                  'model': {'type': 'string', 'enum': ['flash', 'pro']},
                                  'question': {'type': 'string', 'maxLength': 8000},
                                  'files': {'type': 'array', 'minItems': 1, 'maxItems': 12,
                                            'items': {'type': 'string'}}}}}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--config', required=True)
    p.add_argument('--model', choices=['flash', 'pro'], default='flash')
    p.add_argument('--question', required=True)
    p.add_argument('files', nargs='+')
    a = p.parse_args()
    with open(a.config, encoding='utf-8') as f:
        config = json.load(f)
    result = analyze(config, a.model, a.question, a.files)
    print(encode(result).decode('utf-8'))
    raise SystemExit(0 if result.get('ok') else 1)
