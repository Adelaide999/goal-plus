from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from .helpers.codex_runner import CodexRunner, find_codex
from .hosts import (
    HOSTS,
    HostKind,
    ST_ACTIVE_ENV,
    link_host_assets,
    st_host_from_marker_names,
)


ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = Path(__file__).parent / "prompts"


def _run(
    cmd: list[str],
    timeout: int = 20,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _codex_available() -> bool:
    return find_codex() is not None


def _codex_mcp_runtime_connected() -> tuple[bool, str]:
    if not _codex_available():
        return False, "codex binary not on PATH"
    proc = _run(["codex", "mcp", "list"], timeout=20, cwd=ROOT)
    if proc is None:
        return False, "codex mcp list timed out or failed to launch"
    if proc.returncode != 0:
        return False, f"codex mcp list exited {proc.returncode}: {proc.stderr.strip()[:200]}"
    if "goal-plus" not in proc.stdout:
        return False, "goal-plus MCP server not configured for Codex"
    return True, ""


def _mcp_server_binary_available() -> tuple[bool, str]:
    """Verify `goal-plus` (the MCP server entry point) is on PATH."""
    path = shutil.which("goal-plus")
    if path is None:
        return False, (
            "goal-plus binary not on PATH. "
            "Install with: pip install -e . (from project root)"
        )
    return True, ""


def _pi_console_scripts_available() -> list[tuple[bool, str]]:
    checks = []
    for command in ("goal-plus-pi-tool", "goal-plus-pi-worker"):
        checks.append(
            (
                shutil.which(command) is not None,
                f"{command} binary not on PATH. Install with: pip install -e .",
            )
        )
    return checks


def _fixtures_present() -> tuple[bool, str]:
    """Verify the ST-local fixture specs and evaluators exist.

    ST fixtures live under tests/st/fixtures/<scenario>/ and are independent
    of examples/ and tests/fixtures/ — those are referenced by unit tests and
    example docs, not by ST.
    """
    missing = []
    for scenario in [
        "circle_packing",
        "k_module_problem",
    ]:
        for fname in ("spec.json", "evaluator.py", "initial_program.py", "config.yaml"):
            rel = f"tests/st/fixtures/{scenario}/{fname}"
            if not (ROOT / rel).exists():
                missing.append(rel)
    if missing:
        return False, f"missing ST fixture files under {ROOT}: {missing}"
    return True, ""


def _st_selected(config: pytest.Config) -> bool:
    return "st" in (config.getoption("-m") or "")


def _requested_hosts(config: pytest.Config, st_items: list[pytest.Item]) -> set[HostKind]:
    markexpr = config.getoption("-m") or ""
    explicit = {
        host.kind
        for host in HOSTS.values()
        if host.marker in markexpr
    }
    if explicit:
        return explicit
    return {_item_host(item) for item in st_items}


def _item_host(item: pytest.Item) -> HostKind:
    return st_host_from_marker_names({marker.name for marker in item.iter_markers()})


def _host_checks(host: HostKind) -> list[tuple[bool, str]]:
    checks: list[tuple[bool, str]] = []
    config = HOSTS[host]
    checks.append((shutil.which(config.binary) is not None, f"{config.binary} binary not on PATH"))
    if host == "pi-rpc":
        checks.extend(_pi_console_scripts_available())
    else:
        binary_ok, binary_msg = _mcp_server_binary_available()
        checks.append((binary_ok, binary_msg or "goal-plus on PATH"))

    if host == "codex" and _codex_available():
        mcp_ok, mcp_msg = _codex_mcp_runtime_connected()
        checks.append((mcp_ok, mcp_msg or "goal-plus MCP configured for Codex"))

    fixtures_ok, fixtures_msg = _fixtures_present()
    checks.append((fixtures_ok, fixtures_msg or "fixtures/specs present"))
    return checks


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Pre-flight checks for ST tests. Skip with a concrete reason if any check fails."""
    if not any("st" in [m.name for m in item.iter_markers()] for item in items):
        return

    selected = _st_selected(config)

    if not selected:
        # No need to run expensive checks if user didn't select ST
        for item in items:
            if "st" in [m.name for m in item.iter_markers()]:
                item.add_marker(pytest.mark.skip(
                    reason="ST tests not selected (use `-m st` to run)"
                ))
        return

    nested_scenario = os.environ.get(ST_ACTIVE_ENV)
    if nested_scenario:
        pytest.exit(
            f"refusing to run ST from inside active ST host agent: {nested_scenario}",
            returncode=4,
        )

    st_items = [item for item in items if "st" in [m.name for m in item.iter_markers()]]
    requested_hosts = _requested_hosts(config, st_items)
    for host in requested_hosts:
        host_items = [item for item in st_items if _item_host(item) == host]
        if not host_items:
            continue
        checks = _host_checks(host)
        failed = [msg for ok, msg in checks if not ok]
        if failed:
            reason = (
                f"ST pre-flight check failed for {HOSTS[host].display_name}: "
                + " | ".join(failed)
            )
            for item in host_items:
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture()
def st_project_root(request: pytest.FixtureRequest) -> Path:
    """Temporary project root for an ST run, under <repo>/.tmp/st-runs/.

    Uses the project-local .tmp/ instead of the system tmp_path, because some
    environments restrict /tmp access or have small tmp partitions. Each
    scenario gets its own subdirectory keyed by the test node id so parallel
    runs don't collide.
    """
    base = ROOT / ".tmp" / "st-runs"
    base.mkdir(parents=True, exist_ok=True)
    # Sanitize node id -> dir name (replace :: with _, strip param brackets)
    node = request.node.name.replace("::", "_").replace("[", "_").replace("]", "")
    project_root = base / node
    project_root.mkdir(parents=True, exist_ok=True)

    link_host_assets(project_root, ROOT)

    return project_root


@pytest.fixture()
def st_log_dir(request: pytest.FixtureRequest) -> Path:
    base = ROOT / ".tmp" / "st-logs"
    base.mkdir(parents=True, exist_ok=True)
    node = request.node.name.replace("::", "_").replace("[", "_").replace("]", "")
    log_dir = base / node
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


@pytest.fixture()
def st_runner(
    st_project_root: Path,
    st_log_dir: Path,
):
    return CodexRunner(
        project_root=st_project_root,
        log_dir=st_log_dir,
        default_timeout=int(os.environ.get("ST_CODEX_TIMEOUT", "1800")),
    )


def load_prompt(scenario: str) -> str:
    """Load a prompt template and render {{PROJECT_ROOT}} with the absolute repo path."""
    path = PROMPTS_DIR / f"{scenario}.md"
    assert path.exists(), f"prompt file missing: {path}"
    text = path.read_text(encoding="utf-8")
    return text.replace("{{PROJECT_ROOT}}", str(ROOT))
