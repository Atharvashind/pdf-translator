#!/usr/bin/env bash
set -e
apt-get install -y tesseract-ocr tesseract-ocr-mar poppler-utils
pip install -r requirements.txt
