import subprocess


def _run(*args):
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True,
    )


class TestMcpServe:
    def test_help_shows_options(self):
        r = _run("mcp-serve", "--help")
        assert r.returncode == 0
        assert "transport" in r.stdout
        assert "stdio" in r.stdout
        assert "sse" in r.stdout
        assert "host" in r.stdout
        assert "port" in r.stdout

    def test_default_transport_is_stdio_in_help(self):
        r = _run("mcp-serve", "--help")
        assert "[default: stdio]" in r.stdout

    def test_invalid_transport_errors(self):
        """非法 transport 应传给 server.run 并 ValueError 报错退出（非 0）。"""
        r = _run("mcp-serve", "--transport", "bogus")
        assert r.returncode != 0
        # 错误信息应含 unknown transport（ValueError 的 traceback 或 typer 输出）
        combined = r.stdout + r.stderr
        assert "unknown transport" in combined

    def test_bare_help_still_lists_all_commands(self):
        """v0.5.9 铁律：加子命令后裸跑 --help 列出所有命令。"""
        r = _run("--help")
        assert r.returncode == 0
        assert "mcp-serve" in r.stdout
        assert "advise" in r.stdout
        assert "reports" in r.stdout
        assert "kyc-questionnaire" in r.stdout
