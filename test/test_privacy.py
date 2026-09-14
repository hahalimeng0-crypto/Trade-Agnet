import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config as config_module
from config import load_config
from privacy import configure_privacy_logging, sanitize_text


class PrivacyTests(unittest.TestCase):
    def test_masks_required_personal_fields(self):
        source = (
            "手机号=13812345678 邮箱=alice@example.com "
            "身份证=110101199001011234 合同方名称=示例供应商有限公司"
        )
        masked = sanitize_text(source)
        self.assertNotIn("13812345678", masked)
        self.assertNotIn("alice@example.com", masked)
        self.assertNotIn("110101199001011234", masked)
        self.assertNotIn("示例供应商有限公司", masked)

    def test_masks_credentials(self):
        masked = sanitize_text("api_key=secret-value app_secret: another-value")
        self.assertNotIn("secret-value", masked)
        self.assertNotIn("another-value", masked)

    def test_config_ignores_legacy_json_credentials(self):
        sensitive_names = (
            "NANOCLAW_API_KEY",
            "NANOCLAW_FEISHU_APP_ID",
            "NANOCLAW_FEISHU_APP_SECRET",
            "NANOCLAW_QQ_APP_ID",
            "NANOCLAW_QQ_APP_SECRET",
            "NANOCLAW_EMAIL_ADMIN_TOKEN",
        )
        with patch.dict(os.environ, {name: "" for name in sensitive_names}, clear=False), patch.object(
            config_module, "_PROJECT_ENV_PATH", Path("missing-test.env")
        ):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
                handle.write(
                    '{"api_key":"legacy","feishu":{"app_id":"legacy",'
                    '"app_secret":"legacy"},"qq":{"app_id":"legacy",'
                    '"app_secret":"legacy"},"email_admin_token":"legacy"}'
                )
                path = handle.name
            try:
                config = load_config(path)
                self.assertEqual("", config.api_key)
                self.assertEqual("", config.feishu_app_id)
                self.assertEqual("", config.feishu_app_secret)
                self.assertEqual("", config.qq_app_id)
                self.assertEqual("", config.qq_app_secret)
                self.assertEqual("", config.email_admin_token)
            finally:
                os.unlink(path)

    def test_logging_factory_masks_values(self):
        configure_privacy_logging()
        record = logging.getLogger("privacy-test").makeRecord(
            "privacy-test", logging.INFO, __file__, 1, "邮箱=%s", ("a@example.com",), None
        )
        self.assertNotIn("a@example.com", record.getMessage())

    def test_config_reads_credentials_from_environment(self):
        old_value = os.environ.get("NANOCLAW_API_KEY")
        os.environ["NANOCLAW_API_KEY"] = "simulated-secret"
        try:
            config = load_config("missing-config.json")
            self.assertEqual("simulated-secret", config.api_key)
        finally:
            if old_value is None:
                os.environ.pop("NANOCLAW_API_KEY", None)
            else:
                os.environ["NANOCLAW_API_KEY"] = old_value

    def test_email_admin_auth_config_is_environment_only(self):
        with patch.dict(os.environ, {
            "NANOCLAW_EMAIL_ADMIN_TOKEN": "simulated-admin-token",
            "NANOCLAW_EMAIL_ADMIN_ALLOWED_ORIGINS": "https://workspace.example/, http://127.0.0.1:8765",
        }, clear=False), patch.object(config_module, "_PROJECT_ENV_PATH", Path("missing-test.env")):
            config = load_config("missing-config.json")
        self.assertEqual("simulated-admin-token", config.email_admin_token)
        self.assertEqual(
            ("https://workspace.example", "http://127.0.0.1:8765"),
            config.email_admin_allowed_origins,
        )


if __name__ == "__main__":
    unittest.main()
