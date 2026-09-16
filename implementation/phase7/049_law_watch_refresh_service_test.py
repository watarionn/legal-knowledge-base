import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('phase76d_refresh', HERE / '048_law_watch_refresh_service.py')
assert SPEC and SPEC.loader
REFRESH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REFRESH
SPEC.loader.exec_module(REFRESH)

class DummyConn:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def rollback(self): pass

class RefreshServiceTest(unittest.TestCase):
    def noop_content(self):
        return types.SimpleNamespace(refresh_missing_watch_content=lambda *a, **k: {'imported_document_count': 0, 'chunk_count_generated': 0})

    def test_no_watches_skips_run(self):
        importer = types.SimpleNamespace(assert_schema=lambda conn: None)
        with tempfile.TemporaryDirectory() as td, \
             patch.object(REFRESH, 'enabled_watch_law_ids', return_value=[]):
            result = REFRESH.refresh_watched_laws_conn(DummyConn(), Path(td), importer=importer, jsonb_type=object)
        self.assertEqual(result['refresh_status'], 'no-watches')
        self.assertIsNone(result['ingestion_run_id'])

    def test_busy_skips_ingestion(self):
        importer = types.SimpleNamespace(assert_schema=lambda conn: None)
        with tempfile.TemporaryDirectory() as td, \
             patch.object(REFRESH, 'enabled_watch_law_ids', return_value=['129AC0000000089']), \
             patch.object(REFRESH, 'try_refresh_lock', return_value=False):
            result = REFRESH.refresh_watched_laws_conn(DummyConn(), Path(td), importer=importer, jsonb_type=object)
        self.assertEqual(result['refresh_status'], 'busy')

    def test_successful_refresh_finishes_succeeded(self):
        calls = []
        importer = types.SimpleNamespace(
            assert_schema=lambda conn: None,
            insert_run=lambda conn, run_id, sha: calls.append(('insert', run_id)),
            import_revisions=lambda args, conn, run_id, law_id, Jsonb: 3,
            run_manifest_hash=lambda conn, run_id: 'a' * 64,
            issue_counts=lambda conn, run_id: (1, 0),
            finish_run=lambda conn, run_id, status, warnings, errors: calls.append(('finish', status, warnings, errors)),
        )
        with tempfile.TemporaryDirectory() as td, \
             patch.object(REFRESH, 'enabled_watch_law_ids', return_value=['129AC0000000089']), \
             patch.object(REFRESH, 'try_refresh_lock', return_value=True), \
             patch.object(REFRESH, 'release_refresh_lock'), \
             patch.object(REFRESH, 'make_refresh_run_id', return_value='run-watch'):
            result = REFRESH.refresh_watched_laws_conn(DummyConn(), Path(td), importer=importer, content_refresher=self.noop_content(), jsonb_type=object)
        self.assertEqual(result['refresh_status'], 'succeeded')
        self.assertEqual(result['revision_observations_processed'], 3)
        self.assertIn(('finish', 'succeeded', 1, 0), calls)

    def test_partial_refresh_is_not_marked_succeeded(self):
        attempts = []
        def import_revision(args, conn, run_id, law_id, Jsonb):
            attempts.append(law_id)
            if law_id.endswith('89'):
                raise RuntimeError('boom')
            return 2
        finished = []
        importer = types.SimpleNamespace(
            assert_schema=lambda conn: None,
            insert_run=lambda *a: None,
            import_revisions=import_revision,
            run_manifest_hash=lambda conn, run_id: 'b' * 64,
            issue_counts=lambda conn, run_id: (0, 0),
            finish_run=lambda conn, run_id, status, warnings, errors: finished.append(status),
        )
        laws = ['129AC0000000089', '322AC0000000067']
        with tempfile.TemporaryDirectory() as td, \
             patch.object(REFRESH, 'enabled_watch_law_ids', return_value=laws), \
             patch.object(REFRESH, 'try_refresh_lock', return_value=True), \
             patch.object(REFRESH, 'release_refresh_lock'), \
             patch.object(REFRESH.time, 'sleep'):
            result = REFRESH.refresh_watched_laws_conn(DummyConn(), Path(td), importer=importer, content_refresher=self.noop_content(), jsonb_type=object)
        self.assertEqual(result['refresh_status'], 'partial')
        self.assertEqual(result['failed_law_ids'], ['129AC0000000089'])
        self.assertEqual(finished[-1], 'partial')
        self.assertEqual(attempts.count('129AC0000000089'), 2)

    def test_partial_cycle_skips_evaluation(self):
        connections = []
        def connect(url):
            conn = DummyConn(); connections.append(conn); return conn
        with tempfile.TemporaryDirectory() as td, \
             patch.object(REFRESH, 'refresh_watched_laws_conn', return_value={'refresh_status': 'partial'}):
            watch = types.SimpleNamespace(watch_state_ready=lambda conn: True)
            result = REFRESH.run_refresh_cycle('mock://db', Path(td), connect=connect, watch=watch)
        self.assertFalse(result['evaluated'])
        self.assertEqual(result['evaluation_skipped_reason'], 'refresh-partial')
        self.assertEqual(len(connections), 1)

    def test_success_cycle_uses_separate_evaluation_connection(self):
        connections = []
        def connect(url):
            conn = DummyConn(); connections.append(conn); return conn
        watch = types.SimpleNamespace(
            watch_state_ready=lambda conn: True,
            evaluate_all_watches=lambda conn, evaluation_date: [{'state': 'no-change'}],
        )
        with tempfile.TemporaryDirectory() as td, \
             patch.object(REFRESH, 'refresh_watched_laws_conn', return_value={'refresh_status': 'succeeded'}):
            result = REFRESH.run_refresh_cycle('mock://db', Path(td), connect=connect, watch=watch)
        self.assertTrue(result['evaluated'])
        self.assertEqual(result['evaluation_result_count'], 1)
        self.assertEqual(len(connections), 2)
        self.assertIsNot(connections[0], connections[1])


    def test_preflight_blocks_refresh_before_external_work(self):
        connections = []
        def connect(url):
            conn = DummyConn(); connections.append(conn); return conn
        watch = types.SimpleNamespace(watch_state_ready=lambda conn: False)
        with tempfile.TemporaryDirectory() as td, \
             patch.object(REFRESH, 'refresh_watched_laws_conn') as refresh_call:
            with self.assertRaises(REFRESH.WatchStateNotConfiguredError):
                REFRESH.run_refresh_cycle('mock://db', Path(td), connect=connect, watch=watch)
        refresh_call.assert_not_called()
        self.assertEqual(len(connections), 1)

    def test_raw_dir_is_required(self):
        with self.assertRaises(ValueError):
            REFRESH.run_refresh_cycle('mock://db', None)

if __name__ == '__main__':
    unittest.main(verbosity=2)
