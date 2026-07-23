#!/usr/bin/env python3
"""Pipe 模式（JSON-RPC）端到端测试

通过 subprocess 启动 db_tool.py --pipe，通过 stdin/stdout 发送 JSON-RPC
请求/接收响应，覆盖 Agent 与常驻进程通信的完整协议路径。

用 SQLite 文件库（每个测试独立 tmp_path），无需外部数据库驱动。
"""

import json
import os
import subprocess
import sys


import pytest
from _helpers import DB_TOOL, SCRIPT_DIR


class PipeClient:
    """Pipe 模式客户端，封装 JSON-RPC 通信协议。"""

    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self._req_id = 0

    def send(self, method: str, params: dict | None = None) -> dict:
        """发送 JSON-RPC 请求并等待响应。"""
        self._req_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params or {},
        }
        line = json.dumps(request, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

        raw = self.proc.stdout.readline()
        if not raw:
            return {"error": {"code": -1, "message": "pipe closed unexpectedly"}}
        return json.loads(raw)

    def close(self):
        """发送 exit 请求并等待进程结束。"""
        try:
            self.send("exit")
        except (BrokenPipeError, OSError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def pipe_client(tmp_path, monkeypatch):
    """启动 pipe 模式进程并建立连接，返回 PipeClient。

    每个测试独立 DATABASE_EXPLORER_HOME 和 SQLite 文件库，完全隔离。
    """
    home = str(tmp_path / "explorer-home")
    monkeypatch.setenv("DATABASE_EXPLORER_HOME", home)

    db_file = tmp_path / "test.db"
    conn_str = f"sqlite:///{db_file.as_posix()}"
    conn_name = f"pipe-{tmp_path.name}"

    proc = subprocess.Popen(
        [sys.executable, str(DB_TOOL), "--pipe"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(os.environ, PYTHONPATH=str(SCRIPT_DIR), DATABASE_EXPLORER_HOME=home),
    )

    client = PipeClient(proc)

    # 等待 ready 消息
    ready = json.loads(proc.stdout.readline())
    assert ready.get("method") == "ready", f"预期 ready 消息，收到: {ready}"

    # 连接 SQLite
    result = client.send(
        "connect",
        {
            "db_type": "sqlite",
            "connection_string": conn_str,
            "name": conn_name,
        },
    )
    assert result.get("result", {}).get("output", "").startswith("已连接"), f"连接失败: {result}"

    yield client

    client.close()


class TestPipeProtocol:
    """JSON-RPC 协议基础测试。"""

    def test_connect_and_ping(self, pipe_client):
        """连接后 ping 应返回正常。"""
        result = pipe_client.send("ping")
        assert "连接正常" in result.get("result", {}).get("output", "")

    def test_explore_schema(self, pipe_client):
        """explore --object-type schema 返回 schema 列表。"""
        result = pipe_client.send("explore", {"object_type": "schema", "detail": "names"})
        r = result.get("result", {})
        schemas = r.get("schemas", [])
        assert any("main" in s.lower() if isinstance(s, str) else False for s in schemas)

    def test_unknown_method(self, pipe_client):
        """未知 method 返回错误代码 -32601。"""
        result = pipe_client.send("nonexistent_method")
        assert result.get("error", {}).get("code") == -32601

    def test_malformed_json(self, pipe_client):
        """畸形 JSON 返回 parse error。"""
        pipe_client.proc.stdin.write("not json\n")
        pipe_client.proc.stdin.flush()
        raw = pipe_client.proc.stdout.readline()
        import json as json_mod

        resp = json_mod.loads(raw)
        assert resp.get("error", {}).get("code") == -32700


class TestPipeExplain:
    """EXPLAIN 命令在 pipe 模式下的正确性。"""

    def test_explain_select(self, pipe_client):
        """explain SELECT 返回执行计划。"""
        result = pipe_client.send("explain", {"sql": "SELECT 1"})
        r = result.get("result", {})
        output = r.get("output", "")
        assert any(kw in output.upper() for kw in ["SCAN", "SEARCH", "USE", "LIST"])


class TestPipeLearn:
    """P1-4：learn 命令在 pipe 模式下可用（之前 _CMD_HANDLERS 未注册，返回 -32601）。"""

    def test_learn_show_not_method_not_found(self, pipe_client):
        """learn show 在 pipe 模式不再返回 -32601 Method not found。"""
        result = pipe_client.send("learn", {"action": "show"})
        # 关键断言：不是 Method not found（-32601）
        assert result.get("error", {}).get("code") != -32601, "learn 未注册到 pipe _CMD_HANDLERS"

    def test_learn_clear_works(self, pipe_client):
        """learn clear 在 pipe 模式能执行（无学习数据也应正常返回）。"""
        result = pipe_client.send("learn", {"action": "clear"})
        assert result.get("error", {}).get("code") != -32601
        # clear 成功应返回 result（可能含 output 或 status），不应是 error
        assert "result" in result

    def test_learn_default_action_is_show(self, pipe_client):
        """不传 action 时默认 show（_defaults 补全 action=show）。"""
        result = pipe_client.send("learn", {})
        assert result.get("error", {}).get("code") != -32601
