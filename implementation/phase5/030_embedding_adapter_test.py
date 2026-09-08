from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys
import unittest

PHASE5_DIR = Path(__file__).resolve().parent


def _load():
    path = PHASE5_DIR / "029_embedding_adapter.py"
    spec = importlib.util.spec_from_file_location("legal_kb_phase5_embedding_adapter_test_target", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EMBED = _load()


class EmbeddingAdapterTest(unittest.TestCase):
    def test_profile_identity_is_deterministic_and_version_sensitive(self):
        first = EMBED.EmbeddingProfile("local", "model-a", "1", 8)
        same = EMBED.EmbeddingProfile("local", "model-a", "1", 8)
        changed = EMBED.EmbeddingProfile("local", "model-a", "2", 8)
        self.assertEqual(EMBED.embedding_profile_id(first), EMBED.embedding_profile_id(same))
        self.assertNotEqual(EMBED.embedding_profile_id(first), EMBED.embedding_profile_id(changed))

    def test_embedding_input_policy_is_exact(self):
        with_context = EMBED.ChunkInput("a" * 64, "第一条 > 第一項", "本文")
        without_context = EMBED.ChunkInput("b" * 64, None, "本文")
        self.assertEqual(
            EMBED.build_embedding_input(with_context, EMBED.DEFAULT_INPUT_POLICY),
            "第一条 > 第一項\n\n本文",
        )
        self.assertEqual(
            EMBED.build_embedding_input(without_context, EMBED.DEFAULT_INPUT_POLICY),
            "本文",
        )

    def test_unknown_input_policy_is_rejected(self):
        chunk = EMBED.ChunkInput("a" * 64, None, "本文")
        with self.assertRaisesRegex(ValueError, "unsupported input_policy"):
            EMBED.build_embedding_input(chunk, "future-policy")

    def test_vector_dimension_and_nonfinite_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "dimension mismatch"):
            EMBED.normalize_vector([0.1, 0.2], 3)
        for bad in (math.nan, math.inf, -math.inf):
            with self.assertRaisesRegex(ValueError, "finite"):
                EMBED.normalize_vector([bad], 1)

    def test_vector_hash_is_float32_canonical(self):
        normalized = EMBED.normalize_vector([0.1, -0.2, 0.3], 3)
        self.assertEqual(
            EMBED.embedding_values_sha256(normalized),
            EMBED.embedding_values_sha256([0.1, -0.2, 0.3]),
        )

    def test_deterministic_test_provider_is_stable(self):
        provider = EMBED.DeterministicTestProvider(dimensions=6)
        first = provider.embed(["同じ入力"])[0]
        second = provider.embed(["同じ入力"])[0]
        other = provider.embed(["別の入力"])[0]
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first), 6)
        self.assertTrue(all(math.isfinite(value) for value in first))

    def test_profile_rejects_invalid_dimensions(self):
        profile = EMBED.EmbeddingProfile("local", "model", "1", 0)
        with self.assertRaisesRegex(ValueError, "positive"):
            profile.validate()

    def test_embedding_input_hash_uses_exact_utf8_bytes(self):
        self.assertNotEqual(
            EMBED.embedding_input_sha256("本文"),
            EMBED.embedding_input_sha256("本文 "),
        )


if __name__ == "__main__":
    unittest.main()
