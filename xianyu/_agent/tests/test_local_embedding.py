import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services' / 'xianyu-worker'))
from pipeline import EmbeddingGateway
from config_store import ConfigStore


class LocalEmbeddingTests(unittest.TestCase):
    def test_enabled_without_credentials_and_ignores_old_remote_config(self):
        with patch.dict(os.environ, {'EMBEDDING_API_KEY': '', 'EMBEDDING_MODEL': 'remote-model'}):
            gateway = EmbeddingGateway()
        self.assertTrue(gateway.enabled)
        self.assertEqual(gateway.model, 'fastembed:BAAI/bge-small-zh-v1.5')

    def test_model_is_shared_and_vectors_are_serializable_lists(self):
        encoder = Mock()
        vector = Mock()
        vector.tolist.return_value = [0.1, 0.2]
        encoder.embed.return_value = [vector]
        with patch.object(EmbeddingGateway, '_encoder', None), patch('fastembed.TextEmbedding', return_value=encoder) as factory:
            self.assertEqual(EmbeddingGateway().embed(['寄出时间']), [[0.1, 0.2]])
            self.assertEqual(EmbeddingGateway().embed(['什么时候发货']), [[0.1, 0.2]])
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(factory.call_args.kwargs['providers'], ['CPUExecutionProvider'])

    def test_empty_input_does_not_load_model(self):
        with patch.object(EmbeddingGateway, '_get_encoder') as load:
            self.assertEqual(EmbeddingGateway().embed([]), [])
            load.assert_not_called()

    def test_legacy_embedding_settings_are_not_exposed_or_applied(self):
        config = {'embedding_api_key': 'old-secret', 'embedding_model': 'old-model', 'embedding_base_url': 'old-url'}
        self.assertFalse(any(key.startswith('embedding_') for key in ConfigStore.masked(config)))
        with patch.dict(os.environ, {}, clear=True):
            ConfigStore.apply_environment(config)
            self.assertNotIn('EMBEDDING_API_KEY', os.environ)


if __name__ == '__main__':
    unittest.main()
