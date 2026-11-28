"""Small task-specific capability checks; never execute arbitrary model code."""

import ast
import json

PREFIX = "ROUTER_TASK "


def prompt(task: str) -> str:
    tasks = {
        "plan": "Plan a generic optional setting with default count 1, explicit enabled=false preserved, positive integer counts only (not bool). Return fields default_count, preserves_false, rejects_bool and flow listing config, api, generation, legacy, yaml.",
        "implement": "Return field expression: a Python expression normalizing value: None becomes 1; positive non-bool integers are unchanged; all other inputs become None.",
        "repair": "A list guard incorrectly uses index > len(values). Negative indices must also be rejected. Return field expression: a Python expression that is True exactly for invalid integer indices.",
    }
    return (
        " Also solve this synthetic, read-only capability check (do not change files): "
        + tasks[task]
        + " Append one line ROUTER_TASK followed by a JSON object. Expressions may use only "
        "comparisons, and/or/not, conditional expressions, type(value/index), len(values), int and constants."
    )


def expression(source, values):
    if not isinstance(source, str) or len(source) > 1000:
        raise ValueError
    tree = ast.parse(source, mode="eval")
    allowed = (
        ast.Expression,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Compare,
        ast.BoolOp,
        ast.UnaryOp,
        ast.Not,
        ast.And,
        ast.Or,
        ast.IfExp,
        ast.Call,
        ast.Eq,
        ast.NotEq,
        ast.Is,
        ast.IsNot,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
    )
    nodes = list(ast.walk(tree))
    if len(nodes) > 100 or any(not isinstance(node, allowed) for node in nodes):
        raise ValueError
    for node in nodes:
        if isinstance(node, ast.Name) and node.id not in {*values, "type", "len", "int"}:
            raise ValueError
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name)
            or node.func.id not in {"type", "len"}
            or len(node.args) != 1
            or not isinstance(node.args[0], ast.Name)
            or node.args[0].id not in values
            or node.keywords
        ):
            raise ValueError
    return eval(
        compile(tree, "<router-probe>", "eval"),
        {"__builtins__": {}, "type": type, "len": len, "int": int},
        values,
    )


def assess(text: str, task: str) -> dict:
    cases = []
    try:
        lines = [line[len(PREFIX) :] for line in text.splitlines() if line.startswith(PREFIX)]
        if len(lines) != 1:
            raise ValueError
        data = json.loads(lines[0])
        if not isinstance(data, dict) or task not in {"plan", "implement", "repair"}:
            raise ValueError
        if task == "plan":
            cases = [
                type(data.get("default_count")) is int and data["default_count"] == 1,
                data.get("preserves_false") is True,
                data.get("rejects_bool") is True,
                set(data.get("flow", [])) == {"config", "api", "generation", "legacy", "yaml"},
            ]
        elif task == "implement":
            examples: list[tuple[object, object]] = [
                (None, 1),
                (1, 1),
                (7, 7),
                (0, None),
                (-1, None),
                (True, None),
                (False, None),
                ("2", None),
                ([], None),
            ]
            for value, expected in examples:
                actual = expression(data.get("expression"), {"value": value})
                cases.append(type(actual) is type(expected) and actual == expected)
        else:
            for index in (-2, -1, 0, 1, 2, 3):
                actual = expression(data.get("expression"), {"index": index, "values": [1, 2]})
                cases.append(type(actual) is bool and actual == (index < 0 or index >= 2))
    except (ValueError, TypeError, KeyError, SyntaxError, NameError, RecursionError):
        cases.append(False)
    return {
        "task_correct": bool(cases) and all(cases),
        "task_cases_passed": sum(cases),
        "task_cases_total": len(cases),
    }
