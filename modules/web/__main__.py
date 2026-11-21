"""
File: Cully/modules/web/__main__.py
Description: Starts the Cully web server. Refuses any host that isn't this machine unless --allow-remote is given.
Run from Cully/modules:
    python -m web [--catalog PATH] [--settings PATH] [--host 127.0.0.1] [--port 5000] [--allow-remote] [--open]
Author: Miguel Macias
Date: 2026-11-20
"""

import argparse
import ipaddress
import threading
from pathlib import Path

from report import open_in_browser
from web.app import create_app


def is_local(host: str) -> bool:
    """Returns back True if host is this machine (localhost or a loopback IP)"""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def build_parser() -> argparse.ArgumentParser:
    """Returns back the parser with --catalog, --settings, --host, --port, --allow-remote and --open"""
    parser = argparse.ArgumentParser(
        prog="python -m web", description="Cully web server"
    )
    DEFAULT_ADDRESS = "127.0.0.1"
    DEFAULT_PORT = 5000
    parser.add_argument(
        "--catalog",
        help="Location to your catalog, if none is set it will default to whatever catalog is configured in your configs",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--settings",
        help="Settings file to use, default: ~/.config/cully/settings.json. Runs started from the page use it too",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--host",
        help=f"Address to listen on, default:{DEFAULT_ADDRESS}",
        type=str,
        default=DEFAULT_ADDRESS,
    )
    parser.add_argument(
        "--port",
        help=f"Port to listen on, default:{DEFAULT_PORT}",
        type=int,
        default=DEFAULT_PORT,
    )
    parser.add_argument(
        "--allow-remote",
        help="Set if you want other machines on your network to reach the server",
        action="store_true",
    )
    parser.add_argument(
        "--open",
        help="Set if you want to open the browser once the server is up",
        action="store_true"
    )
    return parser


def main():

    parser = build_parser()
    args = parser.parse_args()

    local = is_local(args.host)
    if not local and not args.allow_remote:
        parser.error(
            f"[web/__main__.py]You've given a non-local ip: ({args.host}). Add --allow-remote"
        )
    elif not local and args.allow_remote:
        print(
            "[web/__main__.py]WARNING: Anyone on this network can see your images, proceed with caution."
        )

    #Catalog() would make a new empty file for a mistyped path, so stop here instead
    if args.catalog is not None and not Path(args.catalog).is_file():
        parser.error(f"[web/__main__.py]No catalog file at {args.catalog}")

    app = create_app(catalog_path=args.catalog, settings_path=args.settings)
    print(f"[web/__main__.py]Serving {args.catalog or 'the default catalog'} at http://{args.host}:{args.port}/")

    if args.open:
        threading.Timer(
            1.0, open_in_browser, [f"http://{args.host}:{args.port}/"]
        ).start()

    app.run(host=args.host, port=args.port, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
