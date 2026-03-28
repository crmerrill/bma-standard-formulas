#!/usr/bin/env python3
"""Launch the BMA Cashflow Engine — single command, everything starts.

Usage:
    python scripts/run_app.py
    python scripts/run_app.py --no-browser
    python scripts/run_app.py --api-port 9000 --ui-port 5200
"""
import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent / "src" / "bma_cfengine_app" / "ui"


def wait_for_server(url: str, timeout: float = 15.0) -> bool:
    """Poll until a URL returns 200 or timeout expires."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main():
    parser = argparse.ArgumentParser(description="BMA Cashflow Engine")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--ui-port", type=int, default=5175)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--prod", action="store_true",
                        help="Serve built UI from FastAPI instead of Vite dev server")
    args = parser.parse_args()

    from bma_cfengine_app.storage.run_store import init_workspace
    ws = init_workspace()

    ui_url = f"http://localhost:{args.ui_port}"
    api_url = f"http://{args.host}:{args.api_port}"

    print()
    print("  ┌─────────────────────────────────────────┐")
    print("  │        BMA Cashflow Engine               │")
    print("  └─────────────────────────────────────────┘")
    print()
    print(f"  Workspace  {ws}")
    print(f"  API        {api_url}")
    print(f"  API Docs   {api_url}/api/docs")
    if not args.prod:
        print(f"  UI         {ui_url}")
    print()

    children: list[subprocess.Popen] = []

    def cleanup(*_):
        for p in children:
            try:
                p.terminate()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    npm = "npm.cmd" if sys.platform == "win32" else "npm"

    if not args.prod:
        if not (UI_DIR / "node_modules").exists():
            print("  Installing UI dependencies...")
            subprocess.run([npm, "install"], cwd=UI_DIR, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        vite_env = {**os.environ, "PORT": str(args.ui_port)}
        vite = subprocess.Popen(
            [npm, "run", "dev", "--", "--port", str(args.ui_port)],
            cwd=UI_DIR,
            env=vite_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        children.append(vite)

    import uvicorn
    api_thread = threading.Thread(
        target=uvicorn.run,
        kwargs={
            "app": "bma_cfengine_app.api.main:app",
            "host": args.host,
            "port": args.api_port,
            "log_level": "warning",
        },
        daemon=True,
    )
    api_thread.start()

    open_url = ui_url if not args.prod else api_url

    if not args.no_browser:
        def _open():
            if wait_for_server(f"{api_url}/api/health"):
                if not args.prod:
                    wait_for_server(ui_url, timeout=10)
                print(f"  Opening {open_url} ...")
                print()
                webbrowser.open(open_url)
            else:
                print("  Warning: API did not start in time")
        threading.Thread(target=_open, daemon=True).start()

    try:
        print("  Press Ctrl+C to stop\n")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
