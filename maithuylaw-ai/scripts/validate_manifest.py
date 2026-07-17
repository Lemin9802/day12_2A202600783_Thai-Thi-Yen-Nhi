#!/usr/bin/env python3
"""
validate_manifest.py — deprecated wrapper.

Use scripts/validate_dataset_manifest.py instead.
This file exists only for backward compatibility and delegates to the canonical script.
"""
import subprocess, sys

sys.exit(subprocess.call(
    [sys.executable, str(__import__('pathlib').Path(__file__).parent / 'validate_dataset_manifest.py')] + sys.argv[1:]
))
