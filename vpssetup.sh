#!/usr/bin/env bash
set -e  # agar koi command fail ho jaye to script ruk jayega

VENV_DIR="${1:-venv}"  # default venv folder ka naam "venv" hoga, chaaho to arg se change kar sakte ho

echo ">>> Checking python3..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install python3 first."
  exit 1
fi

echo ">>> Checking venv module..."
if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "python3-venv not installed. Installing..."
  if command -v apt >/dev/null 2>&1; then
    sudo apt update
    sudo apt install -y python3-venv
  else
    echo "apt not found. Install python3-venv manually."
    exit 1
  fi
fi

echo ">>> Creating virtual environment in: $VENV_DIR"
python3 -m venv "$VENV_DIR"

echo ">>> Activating virtual environment..."
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

echo ">>> Upgrading pip, setuptools, wheel..."
pip install --upgrade pip setuptools wheel

echo ">>> Installing main dependencies..."
pip install python-dotenv cryptography httpx
pip install "python-telegram-bot<23,>=22.0"
pip install instagrapi

echo ">>> Installing Playwright + stealth..."
pip install playwright
pip install "playwright-stealth==1.0.6"

echo ">>> Running Playwright installers..."
playwright install
playwright install-deps

echo ">>> Installing extra dependencies..."
pip install setuptools
pip install psutil

echo ">>> Running spbot5.py..."
python3 spbot5.py