#!/usr/bin/env bash
# Quarto installation and preview script for Linux

# To install Quarto on Debian/Ubuntu:
# # 1. Download the .deb for Ubuntu/Debian 18+ (change the version as needed):
# curl -LO https://github.com/quarto-dev/quarto-cli/releases/download/v1.7.32/quarto-1.7.32-linux-amd64.deb
# 
# # 2. Install it via apt so dependencies are resolved:
# sudo apt install ./quarto-1.7.32-linux-amd64.deb
#
# Or follow instructions at https://quarto.org/docs/get-started/

# Start the live preview server without opening a browser
quarto preview --no-browser
