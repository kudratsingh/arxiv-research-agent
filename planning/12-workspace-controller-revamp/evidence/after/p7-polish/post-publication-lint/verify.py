"""Read-only verification; never imports or executes an evidence helper."""

import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "planning/12-workspace-controller-revamp/evidence/after/p7-polish"
OUT = BASE / "post-publication-lint"
MAPPING = json.loads((OUT / "original-python-mapping.json").read_text())


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class Normalize(ast.NodeTransformer):
    def visit_Attribute(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "datetime"
            and node.value.attr == "timezone"
            and node.attr == "utc"
        ):
            return ast.Attribute(
                value=ast.Name(id="datetime", ctx=ast.Load()), attr="UTC", ctx=ast.Load()
            )
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
            and node.func.attr == "run"
        ):
            keywords = []
            for item in node.keywords:
                if (
                    item.arg == "capture_output"
                    and isinstance(item.value, ast.Constant)
                    and item.value.value is True
                ):
                    for name in ("stdout", "stderr"):
                        keywords.append(
                            ast.keyword(
                                arg=name,
                                value=ast.Attribute(
                                    value=ast.Name(id="subprocess", ctx=ast.Load()),
                                    attr="PIPE",
                                    ctx=ast.Load(),
                                ),
                            )
                        )
                else:
                    keywords.append(item)
            node.keywords = sorted(keywords, key=lambda item: item.arg or "")
        return node

    def generic_visit(self, node):
        super().generic_visit(node)
        for field, value in ast.iter_fields(node):
            if (
                isinstance(value, list)
                and value
                and all(isinstance(item, ast.stmt) for item in value)
            ):
                normalized = []
                pending = []
                for item in value + [None]:
                    if isinstance(item, (ast.Import, ast.ImportFrom)):
                        if isinstance(item, ast.Import):
                            pending.extend(ast.Import(names=[alias]) for alias in item.names)
                        else:
                            pending.extend(
                                ast.ImportFrom(module=item.module, names=[alias], level=item.level)
                                for alias in item.names
                            )
                    else:
                        normalized.extend(
                            sorted(
                                pending, key=lambda item: ast.dump(item, include_attributes=False)
                            )
                        )
                        pending = []
                        if item is not None:
                            normalized.append(item)
                setattr(node, field, normalized)
        return node


def normalized_tree(raw, unwrap):
    tree = ast.parse(raw)
    if unwrap:
        functions = [
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
        ]
        if functions:
            assert len(functions) == 1
            function = functions[0]
            assert not function.args.args and not function.decorator_list
            assert (
                isinstance(tree.body[-1], ast.Expr)
                and isinstance(tree.body[-1].value, ast.Call)
                and isinstance(tree.body[-1].value.func, ast.Name)
                and tree.body[-1].value.func.id == "main"
                and not tree.body[-1].value.args
                and not tree.body[-1].value.keywords
            )
            tree.body = [node for node in tree.body[:-1] if node is not function] + function.body
    return ast.dump(Normalize().visit(tree), include_attributes=False)


rows = []
lookup = {}
for item in MAPPING["files"]:
    archive = ROOT / item["archived_path"]
    raw = archive.read_bytes()
    captured = subprocess.run(
        ["git", "show", MAPPING["base_commit"] + ":" + item["original_path"]],
        capture_output=True,
        check=True,
    ).stdout
    assert captured == raw, item["original_path"]
    assert digest(raw) == item["original_sha256"]
    lookup[item["original_path"]] = item["archived_path"]
    row = dict(item, original_commit_bytes_equal=True)
    if item["active_path"]:
        current = (ROOT / item["active_path"]).read_bytes()
        original_tree = normalized_tree(raw, False)
        current_tree = normalized_tree(current, True)
        assert original_tree == current_tree, item["active_path"]
        compile(current, item["active_path"], "exec")
        row.update(
            active_sha256=digest(current),
            normalized_ast_sha256=digest(original_tree.encode()),
            normalized_ast_equal=True,
            compile_pass=True,
        )
    else:
        row["archival_only_no_active_python"] = True
    rows.append(row)

manifest = json.loads((BASE / "browser-artifact-hashes.json").read_text())
resolved = []
for item in manifest["files"]:
    old_path = str((BASE / item["path"]).relative_to(ROOT))
    path = lookup.get(old_path, old_path)
    raw = (ROOT / path).read_bytes()
    assert len(raw) == item["bytes"] and digest(raw) == item["sha256"], old_path
    resolved.append(
        dict(
            original_browser_path=item["path"],
            resolved_repository_path=path,
            sha256=item["sha256"],
            bytes=item["bytes"],
        )
    )

report = dict(
    base_commit=MAPPING["base_commit"],
    application_commit=MAPPING["application_commit"],
    scope="Read-only bytes/AST/compile verification, no helper import/execution, provider or database access.",
    normalized_equivalences=[
        "unwrap unconditional main() execution boundary for guarded fixture scripts",
        "split/sort imports only within each contiguous original import block; never move an import across guards or statements",
        "datetime.timezone.utc equals datetime.UTC on supported Python",
        "subprocess stdout=PIPE,stderr=PIPE equals capture_output=True",
    ],
    helpers=rows,
    original_browser_manifest_sha256=digest((BASE / "browser-artifact-hashes.json").read_bytes()),
    original_browser_entries_verified=len(resolved),
    browser_entries=resolved,
)
(OUT / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
print(
    json.dumps(
        dict(
            helpers=len(rows),
            active_ast_equal=sum(row.get("normalized_ast_equal", False) for row in rows),
            archived_only=1,
            original_browser_entries_verified=len(resolved),
            status="pass",
        ),
        indent=2,
    )
)
