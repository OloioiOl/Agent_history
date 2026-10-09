"""Offline regression for the text boundary; no network or event loop needed."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location(
    'result_contract_plugin', ROOT/'__init__.py', submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)

def finish(coroutine):
    # Patched async analysis completes without IO or awaiting a future.
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coroutine.close()
    raise AssertionError('Unexpected suspension in offline fixture')

class ResultContract(unittest.TestCase):
    def invoke(self, value):
        async def analyze(*args):
            return value
        with patch.object(plugin.Path, 'read_text', return_value='{}'), \
             patch.object(plugin, 'analyze_async', side_effect=analyze):
            raw = finish(plugin.bulk_analyze({'model':'flash','question':'fixture','files':['inbox/test.txt']}))
        self.assertIsInstance(raw, str)
        self.assertEqual(json.loads(raw), value)
        return raw

    def test_error_result_is_json_text(self):
        self.invoke({'ok':False,'error':'PATH_DENIED'})

    def test_success_preserves_unicode_and_quotes(self):
        raw = self.invoke({'ok':True,'findings':[{'claim':'fixture','evidence':[{'quote':'한글 "인용"\n다음 줄'}]}]})
        self.assertIn('한글',raw)

    def test_bad_arguments_do_not_read_config(self):
        with patch.object(plugin.Path,'read_text',side_effect=AssertionError('Must not read')):
            raw = finish(plugin.bulk_analyze({}))
        self.assertIsInstance(raw,str)
        self.assertEqual(json.loads(raw),{'ok':False,'error':'BAD_ARGUMENTS'})

    def test_config_io_error_is_json_text(self):
        with patch.object(plugin.Path,'read_text',side_effect=OSError('fixture')):
            raw = finish(plugin.bulk_analyze({'model':'flash','question':'fixture','files':[]}))
        self.assertIsInstance(raw,str)
        self.assertEqual(json.loads(raw),{'ok':False,'error':'CLIENT_CONFIG_OR_IO'})

if __name__ == '__main__':
    unittest.main()
