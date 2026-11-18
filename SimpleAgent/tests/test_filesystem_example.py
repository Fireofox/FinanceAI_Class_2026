import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simple_agent.mcp_client import MCPManager


@pytest.fixture
def filesystem_server(tmp_path):
    source = Path(__file__).resolve().parents[1] / "examples" / "MCP" / "filesystem-mcp-server"
    server = tmp_path / "copied-server"
    shutil.copytree(source, server, ignore=shutil.ignore_patterns(".venv", "__pycache__", "uv.lock"))
    root = tmp_path / "workspace"
    root.mkdir()
    return server, root


def config_for(server, root=None, limit=None):
    config = {"command": sys.executable, "args": ["server.py"], "cwd": str(server)}
    env = {}
    if root is not None:
        env["FILE_MCP_ROOT"] = str(root)
    if limit is not None:
        env["FILE_MCP_MAX_BYTES"] = str(limit)
    if env:
        config["env"] = env
    return {"files": config}


async def routes(manager):
    tools = await manager.list_tools()
    assert len(tools) == 2
    names = [item["function"]["name"] for item in tools]
    return {
        name: next(item for item in names if item.startswith(f"files__{name}_"))
        for name in ("read_file", "write_file")
    }


async def call(manager, name, arguments):
    result = json.loads(await manager.call_tool(name, arguments))
    assert not result.get("isError", False), result
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


async def test_copied_server_reads_creates_and_explicitly_overwrites(filesystem_server):
    server, root = filesystem_server
    (root / "notes").mkdir()
    async with MCPManager(config_for(server, root)) as manager:
        tool = await routes(manager)
        created = await call(manager, tool["write_file"], {"path": "notes/a.md", "content": "你好\n"})
        assert created["status"] == "ok" and created["action"] == "created"
        assert created["bytes"] == len("你好\n".encode("utf-8"))
        read = await call(manager, tool["read_file"], {"path": "notes/a.md"})
        assert read["status"] == "ok" and read["content"] == "你好\n"
        assert read["bytes"] == created["bytes"]
        denied = await call(manager, tool["write_file"], {"path": "notes/a.md", "content": "replace"})
        assert denied["status"] == "error"
        assert (root / "notes" / "a.md").read_text(encoding="utf-8") == "你好\n"
        replaced = await call(manager, tool["write_file"], {"path": "notes/a.md", "content": "更新", "overwrite": True})
        assert replaced["status"] == "ok" and replaced["action"] == "overwritten"
        assert (root / "notes" / "a.md").read_text(encoding="utf-8") == "更新"


async def test_rejects_escape_absolute_paths_and_missing_parent(filesystem_server, tmp_path):
    server, root = filesystem_server
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")
    async with MCPManager(config_for(server, root)) as manager:
        tool = await routes(manager)
        for path in ("../outside.txt", str(outside)):
            assert (await call(manager, tool["read_file"], {"path": path}))["status"] == "error"
            assert (await call(manager, tool["write_file"], {"path": path, "content": "changed", "overwrite": True}))["status"] == "error"
        assert (await call(manager, tool["write_file"], {"path": "missing/new.txt", "content": "x"}))["status"] == "error"
    assert outside.read_text(encoding="utf-8") == "original"
    assert not (root / "missing").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific path forms")
async def test_rejects_windows_device_names_and_alternate_streams(filesystem_server):
    server, root = filesystem_server
    (root / "normal.txt").write_text("original", encoding="utf-8")
    async with MCPManager(config_for(server, root)) as manager:
        tool = await routes(manager)
        for path in ("C:relative.txt", "normal.txt:stream", "NUL.txt", "CON", "trailing."):
            assert (await call(manager, tool["read_file"], {"path": path}))["status"] == "error"
            assert (await call(manager, tool["write_file"], {"path": path, "content": "changed", "overwrite": True}))["status"] == "error"
    assert (root / "normal.txt").read_text(encoding="utf-8") == "original"


async def test_enforces_utf8_and_byte_limit_without_damaging_existing(filesystem_server):
    server, root = filesystem_server
    (root / "large.txt").write_bytes(b"123456789")
    (root / "invalid.txt").write_bytes(b"\xff")
    (root / "existing.txt").write_bytes(b"original")
    async with MCPManager(config_for(server, root, limit=8)) as manager:
        tool = await routes(manager)
        for filename in ("large.txt", "invalid.txt"):
            assert (await call(manager, tool["read_file"], {"path": filename}))["status"] == "error"
        # The limit is bytes, not characters: these four characters take 12 UTF-8 bytes.
        oversized = await call(manager, tool["write_file"], {"path": "existing.txt", "content": "繁體中文", "overwrite": True})
        assert oversized["status"] == "error"
        assert (root / "existing.txt").read_bytes() == b"original"
        assert (await call(manager, tool["write_file"], {"path": "new.txt", "content": "繁體中文"}))["status"] == "error"
        assert not (root / "new.txt").exists()


async def test_rejects_symbolic_link_paths(filesystem_server, tmp_path):
    server, root = filesystem_server
    inside = root / "real"
    inside.mkdir()
    (inside / "file.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "file.txt").write_text("outside", encoding="utf-8")
    try:
        os.symlink(inside, root / "inside-link", target_is_directory=True)
        os.symlink(outside, root / "outside-link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Creating directory symlinks is not permitted on this platform")
    async with MCPManager(config_for(server, root)) as manager:
        tool = await routes(manager)
        for link in ("inside-link", "outside-link"):
            assert (await call(manager, tool["read_file"], {"path": f"{link}/file.txt"}))["status"] == "error"
            assert (await call(manager, tool["write_file"], {"path": f"{link}/file.txt", "content": "changed", "overwrite": True}))["status"] == "error"
    assert (inside / "file.txt").read_text(encoding="utf-8") == "inside"
    assert (outside / "file.txt").read_text(encoding="utf-8") == "outside"


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions are platform-specific")
async def test_rejects_windows_junctions(filesystem_server, tmp_path):
    server, root = filesystem_server
    inside = root / "real"
    inside.mkdir()
    (inside / "file.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "file.txt").write_text("outside", encoding="utf-8")
    junctions = [(root / "inside-junction", inside), (root / "outside-junction", outside)]
    # cmd.exe runs the built-in mklink command; avoid shell metacharacters in
    # pytest paths before passing those paths to it.
    if not all(all(ch.isalnum() or ch in "\\/:._- " for ch in str(path))
               for pair in junctions for path in pair):
        pytest.skip("Temporary path contains cmd.exe metacharacters")
    created = []
    try:
        for link, target in junctions:
            result = subprocess.run(
                ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True, check=False,
            )
            if result.returncode:
                pytest.skip("Creating Windows junctions is not permitted")
            created.append(link)
        async with MCPManager(config_for(server, root)) as manager:
            tool = await routes(manager)
            for link, _ in junctions:
                path = f"{link.name}/file.txt"
                assert (await call(manager, tool["read_file"], {"path": path}))["status"] == "error"
                assert (await call(manager, tool["write_file"], {"path": path, "content": "changed", "overwrite": True}))["status"] == "error"
        assert (inside / "file.txt").read_text(encoding="utf-8") == "inside"
        assert (outside / "file.txt").read_text(encoding="utf-8") == "outside"
    finally:
        # Remove junction entries themselves, never recurse into their targets.
        for link in reversed(created):
            os.rmdir(link)


async def test_default_root_is_server_working_directory(filesystem_server, monkeypatch):
    server, _ = filesystem_server
    monkeypatch.delenv("FILE_MCP_ROOT", raising=False)
    async with MCPManager(config_for(server)) as manager:
        tool = await routes(manager)
        result = await call(manager, tool["write_file"], {"path": "example.txt", "content": "hello"})
        assert result["status"] == "ok"
    assert (server / "example.txt").read_text(encoding="utf-8") == "hello"
