"""Launch the TradingAgents web UI via `tradingagents-web` command."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    import importlib.util
    if importlib.util.find_spec("streamlit") is None:
        print(
            "错误：Streamlit 未安装，无法启动 Web UI。\n"
            "安装方法：pip install 'tradingagents-astock[web]'\n"
            "或（开发环境）：pip install -e '.[web]'"
        )
        sys.exit(1)
    app_path = Path(__file__).parent / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])


if __name__ == "__main__":
    main()
