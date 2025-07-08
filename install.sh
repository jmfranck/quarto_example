#!/usr/bin/env bash
if [ ! -f quarto-1.7.32-linux-amd64.deb ]; then
curl -LO https://github.com/quarto-dev/quarto-cli/releases/download/v1.7.32/quarto-1.7.32-linux-amd64.deb
fi
sudo apt-get update -y
sudo apt-get install -y ./quarto-1.7.32-linux-amd64.deb
cp githooks/ctags .git/hooks/ctags
