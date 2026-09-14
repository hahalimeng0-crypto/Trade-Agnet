import json

import pytest

from agent.business.email_m5_acceptance import run_email_m5_acceptance


@pytest.mark.parametrize("provider", ["qq", "netease_163", "netease_126"])
def test_m5_configuration_to_mock_smtp_accepted(provider):
    result = run_email_m5_acceptance(provider)
    assert result["milestone"] == "M5"
    assert result["provider"] == provider
    assert result["account_status"] == "healthy"
    assert result["delivery_status"] == "accepted"
    assert result["delivery_id"] == result["duplicate_delivery_id"]
    assert result["attempt_count"] == 1
    assert result["mock_smtp_accept_count"] == 1
    assert result["connection_test_count"] == 1
    assert result["recipient_masked"] == "m***@example.test"
    assert result["credential_in_database"] is False
    assert result["real_network_used"] is False
    serialized = json.dumps(result)
    assert "m5-memory-only-authorization-code" not in serialized
    assert "m5-buyer@example.test" not in serialized

