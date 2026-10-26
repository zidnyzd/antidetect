"""CLI: serve the API or drive profiles directly."""
import argparse
import json
import sys
from urllib.parse import urlparse

from . import api, launcher, store, sync_agent, sync_server


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

    p_sync_srv = sub.add_parser("sync-server", help="run or manage the sync server")
    srv_sub = p_sync_srv.add_subparsers(dest="srv_cmd", required=True)

    p_srv_run = srv_sub.add_parser("run", help="run the sync server")
    p_srv_run.add_argument("--host", default="127.0.0.1")
    p_srv_run.add_argument("--port", type=int, default=53210)
    p_srv_run.add_argument("--data-dir", default=None)

    p_srv_token = srv_sub.add_parser("token", help="manage enrollment tokens")
    tok_sub = p_srv_token.add_subparsers(dest="tok_cmd", required=True)
    p_tok_create = tok_sub.add_parser("create", help="create an enrollment token")
    p_tok_create.add_argument("--label", "--name", dest="label", default=None)
    p_tok_create.add_argument("--ttl", type=int, default=60)
    p_tok_create.add_argument("--data-dir", default=None)

    p_sync = sub.add_parser("sync", help="configure or run device sync")
    sync_sub = p_sync.add_subparsers(dest="sync_cmd", required=True)

    for setup_cmd in ("setup", "init"):
        p_sync_setup = sync_sub.add_parser(setup_cmd, help="register this device with a sync server")
        p_sync_setup.add_argument("--server", required=True)
        p_sync_setup.add_argument("--token", required=True)
        p_sync_setup.add_argument("--name", default=None)
        p_sync_setup.add_argument("--passphrase", required=True)

    sync_sub.add_parser("status", help="show sync status")
    sync_sub.add_parser("now", help="run one push+pull sync cycle")

    args = parser.parse_args(argv)

    if args.cmd == "sync-server":
        if args.srv_cmd == "run":
            sync_server.serve(host=args.host, port=args.port, data_dir=args.data_dir)
        elif args.srv_cmd == "token" and args.tok_cmd == "create":
            tok = sync_server.create_enrollment_token(
                db_path=args.data_dir, label=args.label, ttl_minutes=args.ttl
            )
            print(
                json.dumps(
                    {
                        "token": tok.token,
                        "label": tok.label,
                        "expires_at": tok.expires_at,
                    }
                )
            )
        return

    store.init()

    if args.cmd == "serve":
        api.serve(args.host, args.port)
    elif args.cmd == "sync":
        if args.sync_cmd in ("setup", "init"):
            res = sync_agent.register_device(
                server_url=args.server,
                enrollment_token=args.token,
                device_name=args.name,
                passphrase=args.passphrase,
            )
            print(json.dumps(res))
        elif args.sync_cmd == "status":
            print(json.dumps(sync_agent.get_status()))
        elif args.sync_cmd == "now":
            with store.db() as conn:
                res = sync_agent.sync_cycle(conn)
            print(json.dumps(res))
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
