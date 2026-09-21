#!/usr/bin/env bash
# Local CI lane. Runs exactly what .github/workflows/ci.yml runs, against a bench you
# already have — no GitHub Actions minutes, no account needed.
#
#   ./scripts/ci-local.sh                                   # current bench, testerp2
#   ./scripts/ci-local.sh --site dev-15.local
#   ./scripts/ci-local.sh --bench ~/frappe/bench-v16 --site v16.localhost
#
# Exit code is 0 only if every lane passed, so it also works as a pre-push hook.

set -uo pipefail

BENCH="${BENCH:-$HOME/frappe/frappe-bench-v15}"
SITE="${SITE:-testerp2.web.gargsystems.com}"
SKIP_FRONTEND=0

while [ $# -gt 0 ]; do
	case "$1" in
		--bench) BENCH="$2"; shift 2 ;;
		--site) SITE="$2"; shift 2 ;;
		--skip-frontend) SKIP_FRONTEND=1; shift ;;
		-h|--help) sed -n '2,12p' "$0"; exit 0 ;;
		*) echo "unknown option: $1"; exit 2 ;;
	esac
done

export PATH="$HOME/.local/bin:$PATH"
export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1

APP="$BENCH/apps/fieldmate"
FAILED=()
PASSED=()

step() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }
record() { if [ "$1" -eq 0 ]; then PASSED+=("$2"); echo "  PASS  $2"; else FAILED+=("$2"); echo "  FAIL  $2"; fi; }

echo "bench : $BENCH"
echo "site  : $SITE"
[ -d "$APP" ] || { echo "fieldmate not found at $APP"; exit 2; }

step "host versions"
"$BENCH/env/bin/python" - <<'PY'
import importlib
for app in ("frappe", "erpnext", "hrms"):
	try:
		print(f"  {app:<8} {importlib.import_module(app).__version__}")
	except Exception:
		print(f"  {app:<8} not on this bench")
PY

step "lint"
"$BENCH/env/bin/ruff" check "$APP/fieldmate"
record $? "ruff"

step "tests"
cd "$BENCH" || exit 2
bench --site "$SITE" run-tests --app fieldmate 2>&1 \
	| grep -vE "^\s+File \"|^\s{4}[a-z_^]|Traceback \(most|ModuleNotFoundError: No module named 'ai-interface'" \
	| tail -20
# grep eats the exit code, so ask the suite again in a form we can trust
bench --site "$SITE" run-tests --app fieldmate >/dev/null 2>&1
record $? "tests"

if [ "$SKIP_FRONTEND" -eq 0 ]; then
	step "frontend build"
	if command -v npm >/dev/null 2>&1; then
		( cd "$APP/frontend" && npm ci --silent && npm run build >/dev/null )
		record $? "frontend"
	else
		echo "  SKIP  npm not on PATH (source nvm first)"
	fi
fi

step "summary"
for p in "${PASSED[@]:-}"; do [ -n "$p" ] && echo "  PASS  $p"; done
for f in "${FAILED[@]:-}"; do [ -n "$f" ] && echo "  FAIL  $f"; done

if [ "${#FAILED[@]}" -gt 0 ]; then
	echo
	echo "LANE FAILED on $SITE"
	exit 1
fi
echo
echo "LANE GREEN on $SITE"
