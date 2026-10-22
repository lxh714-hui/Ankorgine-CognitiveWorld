"""Package facades must import cleanly in isolated interpreters."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "cognitive_world.decision",
        "cognitive_world.resolution",
        "cognitive_world.runtime",
        "cognitive_world.agent",
    ],
)
def test_layer_package_imports_in_fresh_python_process(module_name: str) -> None:
    project_root = Path(__file__).resolve().parents[1]
    source_root = str(project_root / "src")
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_root
        if not existing_pythonpath
        else source_root + os.pathsep + existing_pythonpath
    )

    # pytest may run without valid inherited Windows console handles. Use a
    # valid NUL stdin and temporary files instead of inheriting stdin or
    # relying on anonymous output pipes. Each invocation remains a new process.
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        result = subprocess.run(
            [sys.executable, "-c", f"import {module_name}"],
            cwd=project_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            check=False,
            timeout=30,
        )
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", errors="replace")
        stderr = stderr_file.read().decode("utf-8", errors="replace")

    assert result.returncode == 0, (
        f"fresh interpreter could not import {module_name}:\n"
        f"stdout:\n{stdout}\nstderr:\n{stderr}"
    )
