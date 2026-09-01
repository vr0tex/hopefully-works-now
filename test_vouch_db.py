import importlib.util
import json
import os
import tempfile
import unittest

MODULE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app.py.py')

spec = importlib.util.spec_from_file_location('vouch_bot', MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class VouchDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, 'vouches.db')
        module.VOUCH_DB_PATH = self.db_path
        module.init_vouch_database()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_bonus_vouches_persist_in_sqlite(self):
        total = module.add_bonus_vouches('user_42', 3, 'ALS')
        self.assertEqual(total, 3)
        self.assertEqual(module.get_bonus_vouches('user_42')['total'], 3)

    def test_vouch_record_persists(self):
        record_id = module.save_vouch_record(
            booster_id='user_42',
            customer_id='customer_99',
            game='ALS',
            feedback='Great carry',
            star_rating=5,
            ticket_id='123',
            booster_name='Booster',
            source='local'
        )
        self.assertIsNotNone(record_id)
        self.assertEqual(module.get_total_vouches('user_42'), 1)

    def test_welcome_settings_round_trip_per_guild(self):
        module.WELCOME_SETTINGS_FILE = os.path.join(self.tmpdir.name, 'welcome_settings.json')
        module.WELCOME_ENABLED = {123456: True}
        module.WELCOME_CHANNELS = {123456: 987654}

        module.save_welcome_settings()

        module.WELCOME_ENABLED = {}
        module.WELCOME_CHANNELS = {}
        loaded = module.load_welcome_settings()

        self.assertTrue(loaded.get(123456, False))
        self.assertEqual(module.get_welcome_channel_id_for_guild(123456), 987654)

    def test_restore_vouches_from_backup_file(self):
        backup_path = os.path.join(self.tmpdir.name, 'vouches_backup_test.json')
        backup_data = {
            'timestamp': '2026-01-01T00:00:00+00:00',
            'database': 'SQLite',
            'bonus_vouches': [
                {'user_id': 'user_42', 'total': 7, 'games_json': '{"ALS": 7}'},
            ],
            'vouch_records': [
                {
                    'id': 1,
                    'booster_id': 'user_42',
                    'customer_id': 'customer_99',
                    'game': 'ALS',
                    'feedback': 'Great carry',
                    'star_rating': 5,
                    'ticket_id': '123',
                    'booster_name': 'Booster',
                    'created_at': '2026-01-01T00:00:00+00:00',
                    'source': 'local'
                }
            ]
        }
        with open(backup_path, 'w', encoding='utf-8') as fh:
            json.dump(backup_data, fh)

        result = module.restore_vouches_from_backup(backup_path)

        self.assertEqual(result['bonus_vouches'], 1)
        self.assertEqual(result['vouch_records'], 1)
        self.assertEqual(module.get_bonus_vouches('user_42')['total'], 7)
        self.assertEqual(module.get_total_vouches('user_42'), 8)


if __name__ == '__main__':
    import json
    unittest.main()
