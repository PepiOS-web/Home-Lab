"""Frozen operator bundles must form a reviewed, pinned upgrade chain."""
import ast
import hashlib
import json
import re

import pytest


@pytest.fixture
def assert_current_or_multistream_successor():
    def check(root, name, historical_digest):
        current = hashlib.sha256((root / name).read_text(encoding="utf-8").encode()).hexdigest()
        if current == historical_digest:
            return
        source = (root.parents[1] / "maintenance" / "install-live-multistream.sh").read_text(encoding="utf-8")
        block = re.search(r"<<'PY'\n(.*?)\nPY", source, re.S).group(1)
        tree = ast.parse(block)
        assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == "files" for t in n.targets))
        successor = ast.literal_eval(assignment.value)
        edges = {old: new for key, (old, new) in successor.items() if key == name and old is not None}
        upgrade = json.loads((root.parents[1] / "maintenance" / "iss-stream-upgrade-manifest.json").read_text())
        if name in upgrade["files"]:
            pin = upgrade["files"][name]
            if pin["before"] is not None:
                edges[pin["before"]] = pin["after"]
        seen = {historical_digest}
        point = historical_digest
        while point in edges and edges[point] not in seen:
            point = edges[point]
            seen.add(point)
        assert point == current
        assert {"app/multistream.py", "app/multistream_preflight.py"} <= successor.keys()
    return check
