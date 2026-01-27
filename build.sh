#!/usr/bin/env bash
set -e
echo "🚀 Installation des dépendances..."
pip install -r requirements.txt
echo "🎭 Installation de Chromium..."
playwright install chromium
playwright install-deps chromium
echo "✅ Build terminé!"
