#!/usr/bin/env bash
# Build the PWA into fieldmate/public/pwa. Served at /assets/fieldmate/pwa/ as true static,
# which is both where the service worker's scope must be and the only path Frappe does not
# run through Jinja.
set -e
cd "$(dirname "$0")"
npm run build
echo "built into fieldmate/public/pwa"
