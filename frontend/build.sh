#!/usr/bin/env bash
# Build the PWA and publish the shell as the Frappe web page.
set -e
cd "$(dirname "$0")"
npm run build
cp ../fieldmate/public/pwa/index.html ../fieldmate/www/fieldmate.html
echo "built and published to www/fieldmate.html"
