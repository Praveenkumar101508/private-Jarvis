#!/usr/bin/env python3
"""
portable/verify_master_password.py — startup master-password check for IRA portable.

Prompts once (no echo) and verifies against the encrypted record. Exit code 0 only
on success; non-zero (and a human-readable message) on wrong password, lockout, or
an unset password — so the launcher can refuse to boot. The password is never
printed or logged.

Usage:
    python portable/verify_master_password.py [--config-dir ./config]
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from master_password import MasterPasswordStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the IRA portable master password.")
    parser.add_argument("--config-dir", default="./config")
    args = parser.parse_args(argv)

    store = MasterPasswordStore(args.config_dir)
    if not store.is_initialized():
        print("No master password is set. Run portable/setup_master_password.py first.")
        return 2

    result = store.verify(getpass.getpass("IRA master password: "))
    if result.ok:
        print("Master password verified.")
        return 0
    if result.locked:
        print(f"Locked: {result.message}. Try again in {result.retry_after_seconds}s.")
        return 3
    print(f"Access denied: {result.message}. {result.remaining_attempts} attempts left.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
