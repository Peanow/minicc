from pathlib import Path
import ast
import sys

sys.path.insert(0, str(Path(__file__).parent / "src"))
from reporting import summarize


records = [{"score": 3}, {"score": 7}, {"score": -2}]
before = [dict(record) for record in records]
assert summarize(records) == {"count": 3, "total": 8}
assert records == before
assert summarize([]) == {"count": 0, "total": 0}

tree = ast.parse((Path(__file__).parent / "src" / "reporting.py").read_text())
definition = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
assert definition.name == "summarize"
assert [argument.arg for argument in definition.args.args] == ["records"]
