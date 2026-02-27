#!/usr/bin/env python3
import os
import shutil
import subprocess
from pathlib import Path

BUILD_DIR = Path(__file__).parent.parent/"build"/"obf"
SRC_DIR = Path(__file__).parent.parent/"src"

def run(cmd: str):
    print(f"[RUN] {cmd}")
    subprocess.check_call(cmd, shell=True)

def main():
    print("Cleaning old obfuscated build...")
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    pyarmor_cmd = (
        f"pyarmor gen "
        f"--output {BUILD_DIR} "
        f"--recursive "
        f"--obf-module 1 "
        f"{SRC_DIR}"
    )

    run(pyarmor_cmd)
    print("Obfuscation complete.")

if __name__ == '__main__':
    main()
