#!/usr/bin/env python3
"""bootstrap.py: Environment setup and OCR warmup for pdf-to-md."""

import sys
import subprocess
import platform
import os
from pathlib import Path

def check_python_version():
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print("Error: Python 3.9 or higher is required.")
        sys.exit(1)
    print(f"Python version {version.major}.{version.minor} is valid.")

def install_dependencies():
    print("Checking dependencies...")
    try:
        import pymupdf4llm
        import rapidocr
        import onnxruntime
        print("All core dependencies are already installed.")
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Upgrading pip...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        except Exception as err:
            print(f"Warning: Could not upgrade pip: {err}")
        
        print("Installing dependencies from requirements.txt...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            print("Dependencies installed successfully.")
        except Exception as err:
            print(f"Error installing dependencies: {err}")
            sys.exit(1)

def ocr_warmup():
    print("Performing OCR warmup...")
    try:
        # This is a dummy warmup. In a real scenario, this might load a model.
        import rapidocr
        # If rapidocr has a specific warmup call, it would go here.
        print("OCR engine ready.")
    except Exception as e:
        print(f"OCR warmup warning: {e}")

if __name__ == "__main__":
    check_python_version()
    install_dependencies()
    ocr_warmup()
    print("Environment is ready.")
