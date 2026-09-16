import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('phase76d_scheduler', HERE / '050_law_watch_local_scheduler.py')
assert SPEC and SPEC.loader
SCHED = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCHED
SPEC.loader.exec_module(SCHED)

class SchedulerTest(unittest.TestCase):
    def test_once_accepts_short_interval(self):
        with tempfile.TemporaryDirectory() as td:
            args = SCHED.parse_args(['--database-url','mock://db','--raw-dir',td,'--once','--interval-seconds','1'])
        self.assertTrue(args.once)

    def test_loop_rejects_sub_hour_interval(self):
        with tempfile.TemporaryDirectory() as td, self.assertRaises(SystemExit):
            SCHED.parse_args(['--database-url','mock://db','--raw-dir',td,'--interval-seconds','3599'])

    def test_exit_codes(self):
        self.assertEqual(SCHED.exit_code({'refresh': {'refresh_status': 'succeeded'}}), 0)
        self.assertEqual(SCHED.exit_code({'refresh': {'refresh_status': 'no-watches'}}), 0)
        self.assertEqual(SCHED.exit_code({'refresh': {'refresh_status': 'busy'}}), 3)
        self.assertEqual(SCHED.exit_code({'refresh': {'refresh_status': 'partial'}}), 2)

    def test_run_once_delegates_without_printing_database_url(self):
        with tempfile.TemporaryDirectory() as td:
            args = SCHED.parse_args(['--database-url','mock://secret','--raw-dir',td,'--once'])
            with patch.object(SCHED.REFRESH, 'run_refresh_cycle', return_value={'refresh': {'refresh_status':'succeeded'}}) as run:
                result = SCHED.run_once(args)
        self.assertEqual(result['refresh']['refresh_status'], 'succeeded')
        run.assert_called_once()

if __name__ == '__main__':
    unittest.main(verbosity=2)
