# //// Neoffice — added file (no upstream equivalent).
"""Whoever calls the listing engine speaks its real API (#739).

Three guest endpoints of api.py passed `attribute_filters=` and `field_filters=` to
`ProductQuery.query()`, which takes `attributes` and `fields`, and one of them called
`ProductFiltersBuilder.get_all_filters()`, a method that does not exist. Every call
answered 500, open to any visitor, and nobody noticed for months because nothing in the
fleet ever called them. They are gone.

The tests read the source with `ast` and import nothing of the app, so they run anywhere,
site or no site. They keep the defect from coming back: a method called on an engine
that does not have it, or a keyword the method does not take. A positive control proves
the check would have fired on the old endpoints.
"""

import ast
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
IGNORE = ("__pycache__", "/node_modules/", "/dist/", "/.git/", "/tests/", "/test_")

ENGINES = {
	"ProductQuery": APP / "webshop" / "product_data_engine" / "query.py",
	"ProductFiltersBuilder": APP / "webshop" / "product_data_engine" / "filters.py",
}

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _methods(engine):
	"""{method name: its ast.FunctionDef}, read from the engine's source."""
	tree = ast.parse(ENGINES[engine].read_text(encoding="utf-8"))
	for node in tree.body:
		if isinstance(node, ast.ClassDef) and node.name == engine:
			functions = (ast.FunctionDef, ast.AsyncFunctionDef)
			return {n.name: n for n in node.body if isinstance(n, functions)}
	raise AssertionError(f"class {engine} is not defined in {ENGINES[engine]}")


def _own_nodes(scope):
	"""Every node of a scope, without going down into the scopes nested in it."""
	stack = list(ast.iter_child_nodes(scope))
	while stack:
		node = stack.pop()
		yield node
		if not isinstance(node, SCOPES):
			stack.extend(ast.iter_child_nodes(node))


def _engine_of(call):
	"""The engine class a `Name(...)` call builds, or None."""
	if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in ENGINES:
		return call.func.id
	return None


def _problems(source, where):
	"""What is wrong with the calls made on ProductQuery / ProductFiltersBuilder in `source`."""
	tree = ast.parse(source)
	methods = {engine: _methods(engine) for engine in ENGINES}
	found = []

	functions = (ast.FunctionDef, ast.AsyncFunctionDef)
	scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, functions)]
	for scope in scopes:
		nodes = list(_own_nodes(scope))

		# `engine = ProductQuery(...)` binds the name to an engine for this scope
		bound = {}
		for node in nodes:
			if isinstance(node, ast.Assign) and _engine_of(node.value):
				for target in node.targets:
					if isinstance(target, ast.Name):
						bound[target.id] = _engine_of(node.value)

		for node in nodes:
			if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
				continue
			receiver = node.func.value
			if isinstance(receiver, ast.Name):
				engine = bound.get(receiver.id)
			else:
				engine = _engine_of(receiver)
			if not engine:
				continue

			name = node.func.attr
			label = f"{where}:{node.lineno}: {engine}.{name}()"
			method = methods[engine].get(name)
			if method is None:
				found.append(f"{label} does not exist")
				continue

			spec = method.args
			accepted = {a.arg for a in spec.posonlyargs + spec.args + spec.kwonlyargs}
			positional = [a.arg for a in spec.posonlyargs + spec.args][1:]  # without self
			if spec.kwarg is None:
				for keyword in node.keywords:
					if keyword.arg is not None and keyword.arg not in accepted:
						found.append(f"{label} takes no keyword {keyword.arg!r}")
			given = [a for a in node.args if not isinstance(a, ast.Starred)]
			if spec.vararg is None and len(given) > len(positional):
				found.append(
					f"{label} takes {len(positional)} positional argument(s), got {len(given)}"
				)
	return found


class TestEngineCallersMatchTheEngine(unittest.TestCase):
	def test_every_call_made_on_an_engine_uses_a_method_and_arguments_it_has(self):
		found = []
		for path in sorted(APP.rglob("*.py")):
			if any(part in str(path) for part in IGNORE):
				continue
			source = path.read_text(encoding="utf-8")
			if not any(engine in source for engine in ENGINES):
				continue
			found.extend(_problems(source, str(path.relative_to(APP.parent))))
		self.assertEqual(found, [], "\n" + "\n".join(found))

	def test_the_check_fires_on_the_shape_of_the_three_old_endpoints(self):
		# a control: without it, a check that quietly stopped seeing anything would pass forever
		old_shape = (
			"def get_products_json_for_website(search=None):\n"
			"\tengine = ProductQuery()\n"
			"\treturn engine.query(a_keyword_the_engine_does_not_take={}, search_term=search)\n"
			"\n"
			"def get_product_filter_html(item_group=None):\n"
			"\tfilter_engine = ProductFiltersBuilder(item_group)\n"
			"\treturn filter_engine.a_method_the_engine_does_not_have({}, {})\n"
			"\n"
			"def chained():\n"
			"\treturn ProductQuery().a_method_the_engine_does_not_have()\n"
		)
		found = _problems(old_shape, "old_shape")
		self.assertEqual(len(found), 3, "\n".join(found))
		expected = (
			"takes no keyword 'a_keyword_the_engine_does_not_take'",
			"ProductFiltersBuilder.a_method_the_engine_does_not_have() does not exist",
			"ProductQuery.a_method_the_engine_does_not_have() does not exist",
		)
		for message in expected:
			self.assertTrue(any(message in f for f in found), message)

	def test_a_call_the_engine_does_take_is_not_reported(self):
		source = (
			"def listing(search, group):\n"
			"\tengine = ProductQuery()\n"
			"\tbuilder = ProductFiltersBuilder(group)\n"
			"\tengine.query(fields={}, attributes={}, search_term=search, start=0)\n"
			"\treturn builder.get_price_filters({}, {})\n"
		)
		self.assertEqual(_problems(source, "fine"), [])


if __name__ == "__main__":
	unittest.main()
