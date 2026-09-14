"""Regression tests for the migrated in-project foreign-trade business module."""

from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class BusinessMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "business.db"
        self._env = patch.dict(
            os.environ,
            {
                "BUSINESS_DATABASE_BACKEND": "sqlite",
                "BUSINESS_SQLITE_PATH": str(self.db_path),
            },
        )
        self._env.start()

        from agent.business import config

        config.reload_business_config()

        from agent.business import sqlite_database

        sqlite_database.close_all()
        importlib.reload(sqlite_database)
        self.database = sqlite_database

    def tearDown(self) -> None:
        self.database.close_all()
        self._env.stop()
        from agent.business import config

        config.reload_business_config()
        self._temp_dir.cleanup()

    def test_seed_and_deterministic_tools_use_agent_packages(self) -> None:
        from agent.business import seed_data
        from agent.tools.calculate_quote import calculate_quote_impl
        from agent.tools.check_inventory import check_inventory_impl
        from agent.tools.search_product import search_product_catalog_impl

        # The facade and seed module normally resolve to the same SQLite backend.
        seed_data.tx = self.database.tx
        seed_data.init_db = self.database.init_db
        seed_data.get_connection = self.database.get_connection

        self.assertTrue(seed_data.seed_database())
        self.assertEqual(len(self.database.list_products()), 11)
        self.assertIn("BL-1001", search_product_catalog_impl(sku="BL-1001"))
        self.assertIn('"available": true', check_inventory_impl("BL-1001", 100))
        self.assertIn('"sku": "BL-1001"', calculate_quote_impl("BL-1001", 100))

    def test_business_extractor_reuses_nanoclaw_api_key(self) -> None:
        from agent.business import config

        with patch.dict(os.environ, {"NANOCLAW_API_KEY": "simulated-unified-key"}, clear=False):
            loaded = config.reload_business_config()
            self.assertEqual("simulated-unified-key", loaded.api_key)
        config.reload_business_config()


if __name__ == "__main__":
    unittest.main()
