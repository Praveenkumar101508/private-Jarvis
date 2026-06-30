#!/usr/bin/env python3
"""
portable/setup_master_password.py — one-time master-password setup for IRA portable.

Reads the password twice with no echo (getpass), confirms they match, and stores a
bcrypt hash encrypted at rest. The password is never printed, echoed, or logged.

Usage:
    python portable/setup_master_password.py [--config-dir ./config] [--force]
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# allow running as a standalone script from the repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
from master_password import MasterPasswordError, MasterPasswordStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set the IRA portable master password.")
    parser.add_argument("--config-dir", default="./config", help="where to store the encrypted record")
    parser.add_argument("--force", action="store_true", help="overwrite an existing master password")
    args = parser.parse_args(argv)

    store = MasterPasswordStore(args.config_dir)
    if store.is_initialized() and not args.force:
        print("A master password is already set. Re-run with --force to reset it.")
        return 1

    pw1 = getpass.getpass("New IRA master password (min 8 chars): ")
    pw2 = getpass.getpass("Confirm master password: ")
    if pw1 != pw2:
        print("Passwords do not match.")
        return 1
    try:
        store.setup(pw1, force=args.force)
    except MasterPasswordError as exc:
        print(f"Could not set master password: {exc}")
        return 1
    print(f"Master password set. Encrypted record: {store.enc_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
