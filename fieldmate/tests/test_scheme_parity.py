"""Gate 4's parity suite, Python side.

Every case in `fieldmate/scheme/cases.json` is run through `services.scheme_engine.evaluate` and
checked field by field against the expectation the corpus author computed by hand from
`docs/SCHEME_SPEC.md`. `frontend/scheme/parity.mjs` does the identical thing to the JavaScript
twin, and `scripts/parity.sh` runs both and diffs all three pairings - python against the corpus,
node against the corpus, and python against node.

The three-way shape is the point. Two engines diffed only against each other agree perfectly the
day they share a misreading, and a corpus diffed only against one engine proves that engine agrees
with itself. The corpus is the independent third party, and when it disagrees with both engines the
specification decides which of the three is wrong - never the other way round.

Nothing here needs a site, a database or a bench. The evaluator is a pure function of a cart and a
list of compiled specs, so this file imports no `frappe`, and it runs under a bare `python3` as
readily as under `bench run-tests`. That is deliberate: a rep's phone has no bench either, and a
gate that could only be checked on a configured server would not be checking the thing that ships.

Run it directly for the harness modes `scripts/parity.sh` uses:

    python3 fieldmate/tests/test_scheme_parity.py emit engine   # canonical JSON of the results
    python3 fieldmate/tests/test_scheme_parity.py emit corpus   # canonical JSON of the expectations
    python3 fieldmate/tests/test_scheme_parity.py report a A.json b B.json
    python3 fieldmate/tests/test_scheme_parity.py summary python.json node.json corpus.json
    python3 fieldmate/tests/test_scheme_parity.py timing
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

# tests/ -> fieldmate/ -> the app root, which is the directory `import fieldmate` resolves against.
APP_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = APP_ROOT / "fieldmate" / "scheme" / "cases.json"

# Under `bench run-tests` the app is already importable and this line changes nothing. Under a bare
# `python3 fieldmate/tests/test_scheme_parity.py` it is the only reason the import below resolves,
# and being runnable that way is half of what the suite is asserting: the evaluator reaches for
# nothing outside itself.
if str(APP_ROOT) not in sys.path:
	sys.path.insert(0, str(APP_ROOT))

from fieldmate.services.scheme_engine import evaluate

# Stands for a key one side of a comparison has and the other does not. `None` cannot serve here:
# the spec writes an absent label as `null` on purpose, so a key holding None and a key that is not
# there are two different answers and the diff has to be able to say which it found.
MISSING = object()


def load_cases() -> list[dict]:
	"""The corpus, as written. Never reshaped on the way in - what is on disk is what is run."""
	with open(CORPUS_PATH, encoding="utf-8") as handle:
		return json.load(handle)


def run_case(case: dict) -> dict:
	"""One case through the engine, with the cart and specs handed over untouched."""
	return evaluate(case.get("cart"), case.get("specs"))


def canonical(value):
	"""A result checked for whole numbers on its way to being serialised.

	The integer check is not tidiness. Section 2 of the spec says there is no floating point
	anywhere in the money path, so a float arriving here is the exact class of bug this gate
	exists to catch - and it would otherwise slip through disguised as a formatting difference,
	because Python prints 24.0 where JavaScript prints 24 for arithmetically identical values.
	Booleans are tested before integers because `bool` is a subclass of `int` in Python and
	`budget_warning` would otherwise be serialised as 0 or 1 against JavaScript's true and false.
	"""
	if isinstance(value, bool):
		return value
	if isinstance(value, int):
		return value
	if isinstance(value, float):
		raise ValueError(f"a float reached the result where integer paise were required: {value!r}")
	if isinstance(value, dict):
		return {key: canonical(item) for key, item in value.items()}
	if isinstance(value, list):
		return [canonical(item) for item in value]
	if value is None or isinstance(value, str):
		return value
	raise ValueError(f"a {type(value).__name__} reached the result and has no JSON form: {value!r}")


def canonical_json(value) -> str:
	"""The serialisation both sides of the gate share, so the two files compare as bytes.

	Keys sorted, no whitespace, non-ASCII left as itself. Section 6 says key order does not matter
	and values must be equal; sorting is how that intent becomes a file a `cmp` can settle.
	"""
	return json.dumps(canonical(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def field_diff(got, want, path: str = "") -> list[tuple]:
	"""Every place two results differ, each named by the path a reader can follow in the JSON.

	All of them are collected rather than raising on the first, because a single wrong step
	usually moves five fields at once - a changed measure drags the benefit, the discount and the
	net with it - and seeing all five together is what tells you which step to go and read.
	"""
	differences: list[tuple] = []

	if isinstance(got, dict) and isinstance(want, dict):
		for key in sorted(set(got) | set(want)):
			child = f"{path}.{key}"
			if key not in got:
				differences.append((child, MISSING, want[key]))
			elif key not in want:
				differences.append((child, got[key], MISSING))
			else:
				differences.extend(field_diff(got[key], want[key], child))
		return differences

	if isinstance(got, list) and isinstance(want, list):
		if len(got) != len(want):
			differences.append((f"{path} (length)", len(got), len(want)))
		for index in range(min(len(got), len(want))):
			differences.extend(field_diff(got[index], want[index], f"{path}[{index}]"))
		return differences

	if got != want:
		differences.append((path or "(whole result)", got, want))
	return differences


def describe(value) -> str:
	"""One side of a divergence, short enough to sit on the same line as the other side."""
	if value is MISSING:
		return "<absent>"
	return json.dumps(value, sort_keys=True, ensure_ascii=False)


def format_divergences(case_id: str, differences: list[tuple], left: str, right: str) -> list[str]:
	"""A divergence block: the case that failed, then one line per field with both values."""
	lines = [f"  {case_id}"]
	for path, got, want in differences:
		lines.append(f"    {path}")
		lines.append(f"      {left}: {describe(got)}")
		lines.append(f"      {right}: {describe(want)}")
	return lines


class SchemeParityTest(unittest.TestCase):
	"""One test method per corpus case, so a failure names the case in the runner's output.

	The methods are installed below rather than written out, because the corpus is the thing that
	grows and a hand-written method per case would rot the first time somebody adds one.
	"""

	maxDiff = None

	def test_corpus_is_present(self):
		cases = load_cases()
		self.assertGreater(len(cases), 0, f"the corpus at {CORPUS_PATH} is empty")


def _method_name(case_id: str) -> str:
	"""A case id turned into a Python identifier, keeping the id readable in the failure line."""
	return "test_" + "".join(char if char.isalnum() else "_" for char in case_id)


def _make_test(case: dict):
	def test(self):
		differences = field_diff(run_case(case), case["expect"])
		if differences:
			report = [f"{len(differences)} field(s) differ from the corpus expectation"]
			report.extend(format_divergences(case["id"], differences, "engine", "corpus"))
			self.fail("\n".join(report))

	# The `why` field says what the case is defending, and unittest prints a test's first docstring
	# line beside the failure. It is the fastest route from a red line to the clause it belongs to.
	test.__doc__ = case.get("why")
	return test


def _install_cases() -> None:
	"""Attach one method per case, refusing a duplicate id rather than letting a case vanish.

	Two cases sharing an id would leave only the second installed, and the gate would quietly
	shrink by one while still reporting green. That is worth failing the import over.
	"""
	seen: set[str] = set()
	for case in load_cases():
		case_id = case["id"]
		if case_id in seen:
			raise RuntimeError(f"duplicate case id in {CORPUS_PATH}: {case_id}")
		seen.add(case_id)
		setattr(SchemeParityTest, _method_name(case_id), _make_test(case))


_install_cases()


# --------------------------------------------------------------------------------------
# the harness modes scripts/parity.sh drives
# --------------------------------------------------------------------------------------


def _emit(which: str) -> int:
	cases = load_cases()
	if which == "engine":
		payload = [{"id": case["id"], "result": run_case(case)} for case in cases]
	elif which == "corpus":
		payload = [{"id": case["id"], "result": case["expect"]} for case in cases]
	else:
		sys.stderr.write("emit takes 'engine' or 'corpus'\n")
		return 2
	sys.stdout.write(canonical_json(payload) + "\n")
	return 0


def _load_emitted(path: str) -> dict:
	with open(path, encoding="utf-8") as handle:
		return {entry["id"]: entry["result"] for entry in json.load(handle)}


def _report(left: str, left_path: str, right: str, right_path: str) -> int:
	"""Compare two emitted files field by field and say, in order, what disagrees."""
	got = _load_emitted(left_path)
	want = _load_emitted(right_path)

	# The left file's order, then anything only the right file carried. Every emitted file is
	# written in corpus order, so this makes the listing read the same way cases.json does instead
	# of in whatever order a dict happened to hash.
	ids = list(got) + [case_id for case_id in want if case_id not in got]

	agreeing = 0
	blocks: list[str] = []
	for case_id in ids:
		if case_id not in got:
			blocks.append(f"  {case_id}\n      {left}: <case absent>\n      {right}: <present>")
			continue
		if case_id not in want:
			blocks.append(f"  {case_id}\n      {left}: <present>\n      {right}: <case absent>")
			continue
		differences = field_diff(got[case_id], want[case_id])
		if not differences:
			agreeing += 1
			continue
		blocks.extend(format_divergences(case_id, differences, left, right))

	label = f"{left}-vs-{right}"
	print(f"{label:<18} {agreeing}/{len(ids)} cases agree")
	for line in blocks:
		print(line)
	return 0 if not blocks else 1


def _summary(python_path: str, node_path: str, corpus_path: str) -> int:
	"""The headline count, over all three pairings at once.

	A case counts as passing only when both engines match the corpus and each other. Counting it
	any other way would let a case where the two engines agree on the same wrong number be read as
	a pass, which is the precise failure Gate 4 is built to refuse.
	"""
	sides = {
		"python": _load_emitted(python_path),
		"node": _load_emitted(node_path),
		"corpus": _load_emitted(corpus_path),
	}
	pairings = (("python", "corpus"), ("node", "corpus"), ("python", "node"))

	ids: list[str] = []
	for side in sides.values():
		for case_id in side:
			if case_id not in ids:
				ids.append(case_id)

	diverging = {pairing: 0 for pairing in pairings}
	failing: set[str] = set()
	for case_id in ids:
		for left, right in pairings:
			got = sides[left].get(case_id, MISSING)
			want = sides[right].get(case_id, MISSING)
			if got is MISSING or want is MISSING or field_diff(got, want):
				diverging[(left, right)] += 1
				failing.add(case_id)

	print(f"cases run          : {len(ids)}")
	print(f"cases passing      : {len(ids) - len(failing)}")
	for left, right in pairings:
		print(f"{left + '-vs-' + right:<19}: {diverging[(left, right)]} diverging")
	return 0 if not failing else 1


def _timing() -> int:
	"""What a re-price costs, which is the only early read we have on Gate 4's 150 ms budget.

	Two numbers, and they measure different things. The corpus pass is every case in the file,
	which is the honest "one full evaluation pass" figure. The 40-line figure is the one the gate
	actually names: a rep with a long order re-prices on every edit, against every scheme cached
	for that outlet, and it has to feel instant on a mid-range Android. The cart is assembled here
	rather than taken from the corpus because no case needs forty lines to prove its clause, and
	padding the corpus with a case nobody reads would be a worse trade than a synthetic probe that
	is clearly labelled as one.
	"""
	cases = load_cases()

	start = time.perf_counter()
	for case in cases:
		run_case(case)
	corpus_ms = (time.perf_counter() - start) * 1000

	specs = []
	seen_schemes = set()
	items: list[str] = []
	seen_items = set()
	for case in cases:
		for spec in case.get("specs") or []:
			if spec.get("scheme") not in seen_schemes:
				seen_schemes.add(spec.get("scheme"))
				specs.append(spec)
		for line in (case.get("cart") or {}).get("lines") or []:
			if line.get("item") and line["item"] not in seen_items:
				seen_items.add(line["item"])
				items.append(line["item"])

	# Forty distinct SKUs, because S1 merges duplicates and a cart of the same code forty times
	# would collapse to one line and measure nothing. The real item codes go in first so the money
	# path is genuinely exercised; the rest are padding that still has to be normalised and sorted.
	lines = []
	for index in range(40):
		item = items[index] if index < len(items) else f"FM-PAD-{index:04d}"
		lines.append({"idx": index + 1, "item": item, "qty": 24, "rate_paise": 12200})
	cart = {"outlet": "FM-OUT-00042", "lines": lines}

	evaluate(cart, specs)
	runs = 200
	start = time.perf_counter()
	for _ in range(runs):
		evaluate(cart, specs)
	cart_ms = (time.perf_counter() - start) * 1000 / runs

	print(f"corpus pass        {len(cases)} cases          {corpus_ms:.2f} ms")
	print(f"40-line cart       {len(specs)} schemes         {cart_ms:.3f} ms per re-price")
	return 0


def main(argv: list[str]) -> int:
	if not argv:
		unittest.main(argv=["test_scheme_parity"], exit=False)
		return 0
	if argv[0] == "emit" and len(argv) == 2:
		return _emit(argv[1])
	if argv[0] == "report" and len(argv) == 5:
		return _report(argv[1], argv[2], argv[3], argv[4])
	if argv[0] == "summary" and len(argv) == 4:
		return _summary(argv[1], argv[2], argv[3])
	if argv[0] == "timing" and len(argv) == 1:
		return _timing()
	sys.stderr.write(__doc__.split("Run it directly")[-1])
	return 2


if __name__ == "__main__":
	raise SystemExit(main(sys.argv[1:]))
