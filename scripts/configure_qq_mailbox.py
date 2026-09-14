"""Safely configure a receive-only QQ mailbox using a hidden local prompt."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.business.email_account_service import (
    EmailAccountServiceError,
    create_default_email_account_service,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    address = args.address.strip().lower()

    service = create_default_email_account_service()
    existing_accounts = service.list_accounts()
    current = next(
        (item for item in existing_accounts if item["provider"] == "qq" and item["address"] == address),
        None,
    )

    print(f"Preparing receive-only QQ mailbox: {address}")
    print("The authorization code is hidden and stored with Windows DPAPI.")
    auth_code = getpass.getpass("QQ IMAP/SMTP authorization code: ").strip()
    if not auth_code:
        print("Cancelled: authorization code was empty.")
        return 1

    payload = {
        "display_name": "QQ inquiry mailbox",
        "auth_code": auth_code,
        "inbound_enabled": True,
        "outbound_enabled": False,
        "poll_seconds": 60,
        "sender_name": "NanoClaw Sales",
        "allowed_senders": [],
        "allowed_recipients": [],
    }
    try:
        if current:
            payload["config_version"] = current["config_version"]
            configured = service.update_account(current["account_id"], payload)
        else:
            configured = service.create_account({
                **payload,
                "provider": "qq",
                "address": address,
            })

        print("Testing IMAP connection with imap.qq.com:993 ...")
        service.test_connection(configured["account_id"])
        service.set_enabled(configured["account_id"], True)

        for account in service.list_accounts():
            if account["account_id"] != configured["account_id"] and account["status"] != "disabled":
                service.set_enabled(account["account_id"], False)

        print("SUCCESS: QQ mailbox is healthy and enabled for receiving.")
        print("The previous mailbox has been disabled. Sending remains disabled.")
        return 0
    except EmailAccountServiceError as exc:
        print(f"FAILED: {exc.code}")
        print("The previous mailbox was not disabled.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
