#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"
npm install
npm run build
rm -rf "$ROOT/backend/app/static"
mkdir -p "$ROOT/backend/app/static"
cp -R dist/* "$ROOT/backend/app/static/"
echo "Frontend copied to backend/app/static"
