"""CLI: serve the API or drive profiles directly."""
import argparse
import json
import sys
from urllib.parse import urlparse

from . import api, launcher, store


def _fingerprint_config(args):
    fp = {"platform": args.platform}
    if args.cores:
        fp["hardware_concurrency"] = args.cores
    if args.tz:
        fp["timezone"] = args.tz
    if args.lang:
        fp["language"] = args.lang
    return fp


def _proxy_config(raw):
    if not raw:
        return {}
    parsed = urlparse(raw if "://" in raw else f"socks5://{raw}")
    return {
        "proxy_mode": 2,
        "proxy_type": parsed.scheme,
        "proxy_ip": parsed.hostname,
        "proxy_port": parsed.port,
        "proxy_user": parsed.username,
        "proxy_password": parsed.password,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="antidetect")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run the local API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=53200)

    p_create = sub.add_parser("create", help="create a profile")
    p_create.add_argument("name")
    p_create.add_argument("--platform", default="Windows")
    p_create.add_argument("--cores", type=int)
    p_create.add_argument("--tz")
    p_create.add_argument("--lang")
    p_create.add_argument("--proxy", help="type://[user:pass@]host:port")
    p_create.add_argument("--url")

    sub.add_parser("list", help="list profiles")

    p_open = sub.add_parser("open", help="open a profile")
    p_open.add_argument("profile_id", type=int)

    p_close = sub.add_parser("close", help="close a profile")
    p_close.add_argument("profile_id", type=int)

    p_delete = sub.add_parser("delete", help="delete a profile")
    p_delete.add_argument("profile_id", type=int)

    args = parser.parse_args(argv)
    store.init()

    if args.cmd == "serve":
        api.serve(args.host, args.port)
    elif args.cmd == "create":
        with store.db() as conn:
            pid = store.create_profile(
                conn,
                {
                    "name": args.name,
                    "fingerprint_config": _fingerprint_config(args),
                    "proxy_config": _proxy_config(args.proxy),
                    "site_id": 21 if args.url else 22,
                    "site_url": args.url,
                },
            )
        print(json.dumps({"profile_id": pid}))
    elif args.cmd == "list":
        with store.db() as conn:
            total, rows = store.list_profiles(conn, page=1, limit=100)
            for row in rows:
                print(json.dumps(store.profile_to_dict(row)))
            print(f"total: {total}")
    elif args.cmd == "open":
        with store.db() as conn:
            row = store.profile_get(conn, args.profile_id)
            if not row:
                sys.exit("profile not found")
            profile = store.profile_to_dict(row, include_seed=True)
        profile["id"] = args.profile_id
        info = launcher.open_profile(profile)
        print(json.dumps(info))
    elif args.cmd == "close":
        print(json.dumps({"closed": launcher.close_profile(args.profile_id)}))
    elif args.cmd == "delete":
        launcher.close_profile(args.profile_id)
        with store.db() as conn:
            store.delete_profile(conn, args.profile_id)
        print(json.dumps({"deleted": args.profile_id}))


if __name__ == "__main__":
    main()
