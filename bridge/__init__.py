"""Hermes register(ctx) entrypoint, matched to the probed installed API."""
import json
from pathlib import Path
from .bulk_analyze_client import TOOL_SCHEMA, analyze_async


async def _bulk_analyze_result(args, **kwargs):
    try:
        if not isinstance(args, dict) or set(args) != {'model', 'question', 'files'}:
            return {'ok': False, 'error': 'BAD_ARGUMENTS'}
        config = json.loads((Path(__file__).parent/'client.json').read_text(encoding='utf-8'))
        return await analyze_async(config, args['model'], args['question'], args['files'])
    except (OSError, ValueError):
        return {'ok': False, 'error': 'CLIENT_CONFIG_OR_IO'}


async def bulk_analyze(args, **kwargs):
    """Hermes tool handlers return text; keep the bridge result as JSON."""
    result = await _bulk_analyze_result(args, **kwargs)
    return json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def register(ctx):
    handle = ctx.register_tool(name='bulk_analyze', toolset='bulk_analyze', schema=TOOL_SCHEMA,
                              handler=bulk_analyze, is_async=True,
                              description='Bounded agy analysis with exact source quotations')
    if handle is None:
        raise RuntimeError('bulk_analyze registration was rejected')
