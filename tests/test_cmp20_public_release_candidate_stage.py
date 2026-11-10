"""CMP20 immutable unsigned staged patch protects owner preimage."""
from __future__ import annotations
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch

FILE=pathlib.Path(__file__).resolve().parents[1]/"scripts"/"cmp20_public_release_candidate_stage.py"
spec=importlib.util.spec_from_file_location("cmp20_patch",FILE)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Tests(unittest.TestCase):
    def setUp(self):
        self.saved=m.NEW_FILES
        self.patch={n:n.encode("ascii") for n in m.NEW_FILES}
        m.NEW_FILES={n:m.gitblob(v) for n,v in self.patch.items()}
        self.addCleanup(lambda:setattr(m,"NEW_FILES",self.saved))
    def test_fixed_manifest_pins_owner_and_disallows_executions(self):
        x=m.manifest_for(self.patch)
        self.assertEqual(x["owner_head_preimage"],m.OWNER_HEAD)
        self.assertFalse(x["privileges"]["production_release_authorized"])
        self.assertFalse(x["privileges"]["task_enable_authorized"])
        self.assertFalse(x["privileges"]["process_stop_authorized"])
    def test_extra_file_rejected(self):
        x=dict(self.patch);x["other.py"]=b"pass"
        with self.assertRaises(m.CandidateHold):m.manifest_for(x)
    def test_missing_file_rejected(self):
        x=dict(self.patch);x.pop(next(iter(x)))
        with self.assertRaises(m.CandidateHold):m.manifest_for(x)
    def test_tampered_bytes_rejected(self):
        x=dict(self.patch);x[next(iter(x))]=b"tamper"
        with self.assertRaises(m.CandidateHold):m.manifest_for(x)
    def test_unsigned_candidate_atomic_readback(self):
        with tempfile.TemporaryDirectory() as root:
            temp=pathlib.Path(root)/"temp"
            final=pathlib.Path(root)/"final"
            digest=m.stage_create_only(self.patch,temp,final)
            self.assertEqual(len(digest),64)
            self.assertFalse(temp.exists())
            self.assertEqual(len(list(final.iterdir())),3)
            self.assertFalse(__import__("json").loads((final/"manifest.json").read_text(encoding="utf8"))["privileges"]["production_release_authorized"])
    def test_existing_release_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            final=pathlib.Path(root)/"final";final.mkdir()
            (final/"keep").write_text("original")
            with self.assertRaises(m.CandidateHold):
                m.stage_create_only(self.patch,pathlib.Path(root)/"tmp",final)
            self.assertEqual((final/"keep").read_text(),"original")
    def test_existing_temp_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            temp=pathlib.Path(root)/"tmp";temp.mkdir()
            with self.assertRaises(m.CandidateHold):
                m.stage_create_only(self.patch,temp,pathlib.Path(root)/"final")
    def test_stage_main_fails_without_owner_readback(self):
        with patch.object(m,"owner_snapshot",side_effect=m.CandidateHold("OWNER_DEPLOYED_HEAD_DRIFT")),\
             patch.object(m,"stage_create_only") as stage,\
             patch.object(m.sys,"argv",["cmp20","--stage"]):
            self.assertEqual(m.main(),2)
            stage.assert_not_called()
    def test_no_task_install_or_run_cli(self):
        with patch.object(m.sys,"argv",["cmp20","--deploy"]),\
             patch.object(m,"owner_snapshot") as collect:
            self.assertEqual(m.main(),2)
            collect.assert_not_called()

if __name__=="__main__":
    unittest.main()
