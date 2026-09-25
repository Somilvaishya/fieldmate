#!/usr/bin/env bash
# Gate 4's parity runner: one corpus, two engines, three diffs.
#
#   ./scripts/parity.sh                  # run the gate, print the summary
#   PARITY_OUT=/tmp/parity ./scripts/parity.sh   # keep the canonical outputs somewhere findable
#   NODE=/path/to/node ./scripts/parity.sh
#
# It diffs all three pairings rather than just the two engines. Engines diffed only against each
# other agree perfectly the day they share a misreading of the spec, and that is exactly the
# divergence that reaches a shopkeeper - both the phone and the server quote the same wrong rupee
# and nothing in the suite notices. The corpus is the independent third party: its expectations
# were computed by hand from docs/SCHEME_SPEC.md and never read out of either engine.
#
# Exit code is 0 only when all three pairings are clean, so this works as a pre-push hook.
#
# Needs no site, no database and no bench. The evaluator is a pure function, and a gate that could
# only be checked on a configured server would not be checking the thing that ships to the phone.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(cd "$HERE/.." && pwd)"
SUITE="$APP/fieldmate/tests/test_scheme_parity.py"
RUNNER="$APP/frontend/scheme/parity.mjs"
CORPUS="$APP/fieldmate/scheme/cases.json"

PYTHON="${PYTHON:-python3}"
NODE="${NODE:-}"

for path in "$SUITE" "$RUNNER" "$CORPUS"; do
	[ -f "$path" ] || { echo "missing: $path"; exit 2; }
done

# nvm installs node under $HOME and only puts it on PATH from an interactive shell, so a hook or a
# CI step that runs this non-interactively finds nothing. Falling back by hand keeps the gate
# runnable from cron and from a git hook, where "node: command not found" would otherwise read as
# a passing lane that simply never ran.
if [ -z "$NODE" ]; then
	if command -v node >/dev/null 2>&1; then
		NODE="node"
	else
		export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
		# shellcheck disable=SC1091
		[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1
		if command -v node >/dev/null 2>&1; then
			NODE="node"
		else
			NODE="$(find "$NVM_DIR/versions/node" -maxdepth 3 -type f -name node -path '*/bin/*' 2>/dev/null | sort -V | tail -1)"
		fi
	fi
fi
command -v "$NODE" >/dev/null 2>&1 || { echo "node not found - set NODE=/path/to/node"; exit 2; }

OUT="${PARITY_OUT:-$(mktemp -d -t fieldmate-parity-XXXXXX)}"
mkdir -p "$OUT" || exit 2

CASES="$("$PYTHON" -c 'import json,sys; print(len(json.load(open(sys.argv[1], encoding="utf-8"))))' "$CORPUS")" || exit 2

echo "FieldMate scheme parity - Gate 4"
echo "corpus  : $CORPUS ($CASES cases)"
echo "python  : $("$PYTHON" -V 2>&1)"
echo "node    : $("$NODE" -v)"
echo "outputs : $OUT"
echo

# Each side writes its canonical JSON to a file of its own before anything is compared, so a
# failure leaves the two artefacts on disk to be read rather than only a diff of them.
"$PYTHON" "$SUITE" emit engine >"$OUT/python.json" || { echo "python engine pass failed"; exit 2; }
"$NODE" "$RUNNER" >"$OUT/node.json" || { echo "node engine pass failed"; exit 2; }
"$PYTHON" "$SUITE" emit corpus >"$OUT/corpus.json" || { echo "corpus read failed"; exit 2; }

STATUS=0

"$PYTHON" "$SUITE" report python "$OUT/python.json" corpus "$OUT/corpus.json" || STATUS=1
"$PYTHON" "$SUITE" report node "$OUT/node.json" corpus "$OUT/corpus.json" || STATUS=1
"$PYTHON" "$SUITE" report python "$OUT/python.json" node "$OUT/node.json" || STATUS=1

echo
if cmp -s "$OUT/python.json" "$OUT/node.json"; then
	echo "canonical bytes    identical, $(wc -c <"$OUT/python.json" | tr -d ' ') bytes each side"
else
	# The canonical files are one long line apiece, which `diff` cannot say anything useful about.
	# Pretty copies are written purely so the byte-level failure has a readable form beside the
	# field-level report above.
	"$PYTHON" -m json.tool --indent 1 "$OUT/python.json" >"$OUT/python.pretty.json"
	"$PYTHON" -m json.tool --indent 1 "$OUT/node.json" >"$OUT/node.pretty.json"
	echo "canonical bytes    DIFFER - first 40 lines of the diff:"
	diff -u "$OUT/python.pretty.json" "$OUT/node.pretty.json" | head -40
	STATUS=1
fi

echo
"$PYTHON" "$SUITE" summary "$OUT/python.json" "$OUT/node.json" "$OUT/corpus.json" || STATUS=1

echo
"$PYTHON" "$SUITE" timing

echo
if [ "$STATUS" -eq 0 ]; then
	echo "PARITY OK - all three pairings agree on all $CASES cases"
else
	echo "PARITY FAILED - read the divergences above against docs/SCHEME_SPEC.md before touching"
	echo "                either engine. The document decides which of the three is wrong."
fi
exit "$STATUS"
