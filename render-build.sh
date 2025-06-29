#!/usr/bin/env bash
# Exit immediately on error
set -e

# Install required system dependencies
apt-get update
apt-get install -y gfortran libatlas-base-dev

# Install Python dependencies
pip install -r requirements.txt