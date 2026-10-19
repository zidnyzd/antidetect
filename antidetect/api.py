"""ixBrowser-compatible local API server (subset), stdlib only."""
import json
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import launcher, store

ACTIONS = {}


class ApiError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message


def action(name):
    def wrap(fn):
        ACTIONS[name] = fn
        return fn
    return wrap


def _pid(params):
    pid = params.get("profile_id")
    if pid is None:
        raise ApiError(1001, "profile_id is required")
    return int(pid)


@action("profile-list")
def profile_list(params):
    page = int(params.get("page") or 1)
    limit = int(params.get("limit") or 10)
    with store.db() as conn:
        total, rows = store.list_profiles(
            conn,
            page=page,
            limit=limit,
            group_id=params.get("group_id"),
            name=params.get("name"),
            profile_id=params.get("profile_id"),
        )
        return {"total": total, "data": [store.profile_to_dict(r) for r in rows]}


@action("profile-create")
def profile_create(params):
    with store.db() as conn:
        pid = store.create_profile(conn, params)
        return {"profile_id": pid, "new_profile_id": pid}


@action("profile-update")
def profile_update(params):
    pid = _pid(params)
    with store.db() as conn:
        if not store.profile_get(conn, pid):
            raise ApiError(1002, "profile not found")
        store.update_profile(conn, pid, params)
        return True


@action("profile-delete")
def profile_delete(params):
    pid = _pid(params)
    launcher.close_profile(pid)
    with store.db() as conn:
        if not store.profile_get(conn, pid):
            raise ApiError(1002, "profile not found")
        store.delete_profile(conn, pid)
        return True


@action("profile-copy")
def profile_copy(params):
    pid = _pid(params)
    with store.db() as conn:
        row = store.profile_get(conn, pid)
        if not row:
            raise ApiError(1002, "profile not found")
        data = store.profile_to_dict(row)
        data.pop("profile_id")
        data["name"] = params.get("name") or f"{row['name']} copy"
        return {"profile_id": store.create_profile(conn, data)}


@action("profile-open")
def profile_open(params):
    pid = _pid(params)
    with store.db() as conn:
        row = store.profile_get(conn, pid)
        if not row:
            raise ApiError(1002, "profile not found")
        profile = store.profile_to_dict(row, include_seed=True)
    profile["id"] = pid
    try:
        return launcher.open_profile(profile, app_args=params.get("args"))
    except launcher.LaunchError as error:
        raise ApiError(1003, str(error))


@action("profile-open-with-random-fingerprint")
def profile_open_random(params):
    pid = _pid(params)
    with store.db() as conn:
        row = store.profile_get(conn, pid)
        if not row:
            raise ApiError(1002, "profile not found")
        profile = store.profile_to_dict(row, include_seed=True)
        fp = dict(profile["fingerprint_config"])
        fp.update(params.get("fingerprint_config") or {})
        proxy = params.get("proxy_config") or profile["proxy_config"]
        store.update_profile(
            conn,
            pid,
            {"fingerprint_config": fp, "proxy_config": proxy, "seed": launcher.rand_seed()},
        )
        profile["fingerprint_config"] = fp
        profile["proxy_config"] = proxy
        profile["seed"] = store.latest_seed(conn, pid)
    profile["id"] = pid
    try:
        return launcher.open_profile(profile, app_args=params.get("args"))
    except launcher.LaunchError as error:
        raise ApiError(1003, str(error))


@action("profile-close")
def profile_close(params):
    launcher.close_profile(_pid(params))
    return True


@action("profile-close-in-batches")
def profile_close_batches(params):
    ids = params.get("profile_id")
    if not isinstance(ids, list):
        ids = [ids]
    for pid in ids:
        launcher.close_profile(int(pid))
    return True


@action("profile-opened-list")
def profile_opened_list(params):
    return launcher.opened_profiles()


@action("native-client-profile-opened-list")
def native_opened_list(params):
    return []


@action("profile-open-state-reset")
def profile_open_state_reset(params):
    launcher.forget(_pid(params))
    return True


@action("profile-random-fingerprint-configuration")
def profile_random_fingerprint(params):
    pid = _pid(params)
    with store.db() as conn:
        row = store.profile_get(conn, pid)
        if not row:
            raise ApiError(1002, "profile not found")
        seed = launcher.rand_seed()
        store.update_profile(conn, pid, {"seed": seed})
        return {"profile_id": pid, "fingerprint_config": store._loads(row["fingerprint_config"])}


def _clear_cache(pid, with_cookies=False):
    if launcher.is_open(pid):
        raise ApiError(1004, "close the profile first")
    default = launcher.PROFILES_DIR / str(pid) / "data" / "Default"
    for name in ("Cache", "Code Cache", "GPUCache", "Service Worker"):
        shutil.rmtree(default / name, ignore_errors=True)
    if with_cookies:
        for name in ("Cookies", "Cookies-journal"):
            try:
                (default / name).unlink()
            except OSError:
                pass
    return True


@action("profile-clear-cache")
def profile_clear_cache(params):
    return _clear_cache(_pid(params))


@action("profile-clear-cache-and-cookies")
def profile_clear_cache_cookies(params):
    return _clear_cache(_pid(params), with_cookies=True)


@action("profile-clear-cache-keep-extensions")
def profile_clear_cache_ext(params):
    return _clear_cache(_pid(params))


@action("empty-recycle-bin")
def empty_recycle_bin(params):
    return True


def _paginated(conn, table, page, limit):
    total = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
    rows = conn.execute(
        f"SELECT * FROM {table} ORDER BY id LIMIT ? OFFSET ?",
        (int(limit), (int(page) - 1) * int(limit)),
    ).fetchall()
    return {"total": total, "data": [dict(r) for r in rows]}


@action("group-list")
def group_list(params):
    with store.db() as conn:
        return _paginated(conn, "groups", params.get("page") or 1, params.get("limit") or 100)


@action("group-create")
def group_create(params):
    with store.db() as conn:
        cur = conn.execute(
            "INSERT INTO groups (title, sort) VALUES (?, ?)",
            (params.get("title") or "Group", int(params.get("sort") or 0)),
        )
        conn.commit()
        return {"id": cur.lastrowid}


@action("group-update")
def group_update(params):
    with store.db() as conn:
        conn.execute(
            "UPDATE groups SET title = COALESCE(?, title), sort = COALESCE(?, sort) WHERE id = ?",
            (params.get("title"), params.get("sort"), int(params.get("id") or 0)),
        )
        conn.commit()
        return True


@action("group-delete")
def group_delete(params):
    with store.db() as conn:
        conn.execute("DELETE FROM groups WHERE id = ?", (int(params.get("id") or 0),))
        conn.commit()
        return True


@action("tag-list")
def tag_list(params):
    with store.db() as conn:
        return _paginated(conn, "tags", params.get("page") or 1, params.get("limit") or 100)


@action("tag-create")
def tag_create(params):
    with store.db() as conn:
        cur = conn.execute("INSERT INTO tags (title) VALUES (?)", (params.get("title") or "Tag",))
        conn.commit()
        return {"id": cur.lastrowid}


@action("tag-update")
def tag_update(params):
    with store.db() as conn:
        conn.execute(
            "UPDATE tags SET title = ? WHERE id = ?",
            (params.get("title"), int(params.get("id") or 0)),
        )
        conn.commit()
        return True


@action("tag-delete")
def tag_delete(params):
    with store.db() as conn:
        conn.execute("DELETE FROM tags WHERE id = ?", (int(params.get("id") or 0),))
        conn.commit()
        return True


@action("proxy-list")
def proxy_list(params):
    with store.db() as conn:
        return _paginated(conn, "proxies", params.get("page") or 1, params.get("limit") or 10)


@action("proxy-create")
def proxy_create(params):
    with store.db() as conn:
        cur = conn.execute(
            """INSERT INTO proxies (proxy_type, proxy_ip, proxy_port, proxy_user,
               proxy_password, note, tag) VALUES (?,?,?,?,?,?,?)""",
            (
                params.get("proxy_type"),
                params.get("proxy_ip"),
                params.get("proxy_port"),
                params.get("proxy_user"),
                params.get("proxy_password"),
                params.get("note"),
                params.get("tag"),
            ),
        )
        conn.commit()
        return {"id": cur.lastrowid}


@action("proxy-update")
def proxy_update(params):
    with store.db() as conn:
        fields, args = [], []
        for key in ("proxy_type", "proxy_ip", "proxy_port", "proxy_user",
                    "proxy_password", "note", "tag"):
            if params.get(key) is not None:
                fields.append(f"{key} = ?")
                args.append(params[key])
        if fields:
            args.append(int(params.get("id") or 0))
            conn.execute(f"UPDATE proxies SET {', '.join(fields)} WHERE id = ?", args)
            conn.commit()
        return True


@action("proxy-delete")
def proxy_delete(params):
    with store.db() as conn:
        conn.execute("DELETE FROM proxies WHERE id = ?", (int(params.get("id") or 0),))
        conn.commit()
        return True


@action("traffic-package-list")
def traffic_package_list(params):
    return {"total": 0, "data": []}


@action("gateway-list")
def gateway_list(params):
    return []


@action("proxy-tag-list")
def proxy_tag_list(params):
    return {"total": 0, "data": []}


@action("proxy-tag-create")
def proxy_tag_create(params):
    return True


@action("proxy-tag-update")
def proxy_tag_update(params):
    return True


@action("proxy-tag-delete")
def proxy_tag_delete(params):
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "antidetect/0.1"

    def do_POST(self):
        if not self.path.startswith("/api/v2/"):
            self._json(404, {"error": {"code": 404, "message": "not found"}})
            return
        name = self.path[len("/api/v2/"):].strip("/")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            params = json.loads(raw) if raw else {}
            if not isinstance(params, dict):
                raise ValueError
        except ValueError:
            self._json(200, {"error": {"code": 1000, "message": "body must be a JSON object"}})
            return

        fn = ACTIONS.get(name)
        if fn is None:
            self._json(200, {"error": {"code": 1001, "message": f"unknown action: {name}"}})
            return
        try:
            data = fn(params)
            self._json(200, {"error": {"code": 0, "message": "success"}, "data": data})
        except ApiError as error:
            self._json(200, {"error": {"code": error.code, "message": error.message}})
        except Exception as error:
            self._json(200, {"error": {"code": 1000, "message": str(error)}})

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._json(200, {"status": "ok", "open": len(launcher.opened_profiles())})
            return
        self._json(404, {"error": {"code": 404, "message": "not found"}})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def serve(host="127.0.0.1", port=53200):
    store.init()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"antidetect API listening on http://{host}:{port}/api/v2/")
    httpd.serve_forever()
