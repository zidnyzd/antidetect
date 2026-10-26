"""Tes otomatis end-to-end untuk sinkronisasi Fase 1 dan Fase 2 tanpa menjalankan engine Chrome."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from unittest import mock

SCRATCH_ROOT = Path("/home/zdna/.hermes/cache/scratch/antigravity")
SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
WORK_DIR = Path(tempfile.mkdtemp(prefix="sync-test-", dir=str(SCRATCH_ROOT)))
os.environ["ANTIDETECT_HOME"] = str(WORK_DIR / "default_home")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from antidetect import api, launcher, store, sync_agent, sync_crypto, sync_server  # noqa: E402

LEGACY_SCHEMA = """
CREATE TABLE profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    group_id INTEGER NOT NULL DEFAULT 1,
    color TEXT,
    note TEXT,
    site_id INTEGER,
    site_url TEXT,
    proxy_config TEXT,
    proxy_key TEXT,
    fingerprint_config TEXT,
    preference_config TEXT,
    tag_ids TEXT DEFAULT '[]',
    last_open_time INTEGER,
    seed INTEGER,
    created_at TEXT,
    updated_at TEXT,
    deleted_at TEXT
);
CREATE TABLE groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TEXT
);
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL
);
CREATE TABLE proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proxy_type TEXT,
    proxy_ip TEXT,
    proxy_port INTEGER,
    proxy_user TEXT,
    proxy_password TEXT,
    note TEXT,
    tag TEXT
);
CREATE TABLE templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    payload TEXT,
    created_at TEXT
);
CREATE TABLE extensions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE,
    title TEXT,
    version TEXT,
    path TEXT,
    created_at TEXT
);
"""


def run_cli(args, home_dir):
    python_bin = REPO / "venv" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)
    env = dict(os.environ)
    env["ANTIDETECT_HOME"] = str(home_dir)
    proc = subprocess.run(
        [str(python_bin), "-m", "antidetect", *args],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"CLI gagal ({proc.returncode}): {' '.join(args)}\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
        )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_1_legacy_migration():
    print("=== Tes 1: Migrasi Database Lama ===")
    legacy_home = WORK_DIR / "legacy_home"
    legacy_home.mkdir(parents=True, exist_ok=True)
    legacy_db = legacy_home / "antidetect.db"

    conn = sqlite3.connect(str(legacy_db))
    conn.executescript(LEGACY_SCHEMA)
    conn.execute("INSERT INTO groups (id, title, sort) VALUES (1, 'Default', 0)")
    conn.execute("INSERT INTO groups (id, title, sort) VALUES (2, 'Marketplace', 10)")
    conn.execute("INSERT INTO tags (id, title) VALUES (1, 'VIP')")
    conn.execute(
        "INSERT INTO proxies (id, proxy_type, proxy_ip, proxy_port) VALUES (1, 'socks5', '10.0.0.1', 1080)"
    )
    conn.execute(
        "INSERT INTO templates (id, name, payload) VALUES (1, 'Tpl Lama', '{\"profiles\":[]}')"
    )
    for pid, name, gid in [(1, "Profil Satu", 1), (2, "Profil Dua", 2), (7, "Profil Tujuh", 2)]:
        conn.execute(
            """INSERT INTO profiles (id, name, group_id, tag_ids, seed, created_at, updated_at)
               VALUES (?, ?, ?, '[1]', ?, '2026-01-01 00:00:00', '2026-01-01 00:00:00')""",
            (pid, name, gid, 1000 + pid),
        )
    conn.commit()
    conn.close()

    store.init(db_path=legacy_db)

    backups = list(legacy_home.glob("antidetect.db.pre-sync-*.bak"))
    assert len(backups) == 1, f"Backup pre-sync harus ada 1, ditemukan: {backups}"
    assert backups[0].stat().st_size > 0

    with store.db(db_path=legacy_db) as mconn:
        prof_rows = mconn.execute("SELECT * FROM profiles ORDER BY id").fetchall()
        assert [r["id"] for r in prof_rows] == [1, 2, 7], "ID integer profil tidak boleh berubah"
        for r in prof_rows:
            assert r["uuid"] and len(r["uuid"]) == 36
            assert r["revision"] == 0
            assert r["sync_dirty"] == 1

        grp_default = mconn.execute("SELECT * FROM groups WHERE id = 1").fetchone()
        grp_mp = mconn.execute("SELECT * FROM groups WHERE id = 2").fetchone()
        assert grp_default["uuid"] == "00000000-0000-4000-8000-000000000001"
        assert grp_mp["uuid"] == store.group_uuid_for_title("Marketplace")

        tag_vip = mconn.execute("SELECT * FROM tags WHERE id = 1").fetchone()
        assert tag_vip["uuid"] == store.tag_uuid_for_title("VIP")

        proxy_row = mconn.execute("SELECT * FROM proxies WHERE id = 1").fetchone()
        assert proxy_row["uuid"] and len(proxy_row["uuid"]) == 36

        tpl_row = mconn.execute("SELECT * FROM templates WHERE id = 1").fetchone()
        assert tpl_row["uuid"] and len(tpl_row["uuid"]) == 36

        tables = {
            r["name"]
            for r in mconn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for required_table in ("sync_state", "sync_outbox", "local_leases", "local_conflicts"):
            assert required_table in tables, f"Tabel {required_table} belum dibuat"

    print(
        json.dumps(
            {
                "backup_file": backups[0].name,
                "preserved_profile_ids": [r["id"] for r in prof_rows],
                "default_group_uuid": grp_default["uuid"],
                "marketplace_group_uuid": grp_mp["uuid"],
            },
            indent=2,
        )
    )


def test_2_and_3_and_4():
    server_dir = WORK_DIR / "server_data"
    home_a = WORK_DIR / "home_a"
    home_b = WORK_DIR / "home_b"
    server_dir.mkdir(parents=True, exist_ok=True)
    home_a.mkdir(parents=True, exist_ok=True)
    home_b.mkdir(parents=True, exist_ok=True)

    httpd = sync_server.start_background_server("127.0.0.1", 0, data_dir=server_dir)
    port = httpd.server_address[1]
    server_url = f"http://127.0.0.1:{port}"
    passphrase = "FrasaSandiRahasia2026!"

    try:
        print("=== Tes 2: Sinkronisasi Dua Device (Device A & Device B) ===")
        tok_a = run_cli(
            [
                "sync-server",
                "token",
                "create",
                "--label",
                "Device-A",
                "--ttl",
                "30",
                "--data-dir",
                str(server_dir),
            ],
            home_a,
        )
        tok_b = run_cli(
            [
                "sync-server",
                "token",
                "create",
                "--label",
                "Device-B",
                "--ttl",
                "30",
                "--data-dir",
                str(server_dir),
            ],
            home_b,
        )

        reg_a = run_cli(
            [
                "sync",
                "setup",
                "--server",
                server_url,
                "--token",
                tok_a["token"],
                "--name",
                "Laptop-A",
                "--passphrase",
                passphrase,
            ],
            home_a,
        )
        reg_b = run_cli(
            [
                "sync",
                "setup",
                "--server",
                server_url,
                "--token",
                tok_b["token"],
                "--name",
                "Desktop-B",
                "--passphrase",
                passphrase,
            ],
            home_b,
        )
        assert reg_a["kdf_salt_hex"] == reg_b["kdf_salt_hex"]
        assert (home_a / "sync_credentials.json").stat().st_mode & 0o777 == 0o600
        assert (home_b / "sync_credentials.json").stat().st_mode & 0o777 == 0o600

        # Buat 1 grup dan 1 profil lokal di Device B agar autoincrement ID di Device B bergeser
        with store.db(db_path=home_b / "antidetect.db") as conn_b:
            gid_b_local = store.create_group(conn_b, "Grup Lokal B", sort=1)
            store.create_profile(conn_b, {"name": "Profil Lokal B", "group_id": gid_b_local})

        # Device A membuat grup "Grup Cabang", tag "Penting", proxy, dan profil "Akun 01"
        with store.db(db_path=home_a / "antidetect.db") as conn_a:
            gid_a = store.create_group(conn_a, "Grup Cabang", sort=5)
            tid_a = store.create_tag(conn_a, "Penting")
            pxid_a = store.create_proxy(
                conn_a,
                {
                    "proxy_type": "socks5",
                    "proxy_ip": "198.51.100.25",
                    "proxy_port": 1080,
                    "proxy_user": "user_cabang",
                    "proxy_password": "rahasia_proxy_123",
                    "note": "Proxy Cabang Utama",
                    "tag": "cabang",
                },
            )
            pid_a = store.create_profile(
                conn_a,
                {
                    "name": "Akun 01",
                    "group_id": gid_a,
                    "color": "#409EFF",
                    "note": "Catatan awal Akun 01",
                    "site_id": 6,
                    "site_url": "https://www.google.com/",
                    "proxy_config": {
                        "proxy_type": "socks5",
                        "proxy_ip": "198.51.100.25",
                        "proxy_port": 1080,
                        "proxy_user": "user_cabang",
                        "proxy_password": "rahasia_proxy_123",
                    },
                    "fingerprint_config": {"platform": "Windows", "hardware_concurrency": 8},
                    "preference_config": {"cookies_backup": 1},
                    "tab_id": [tid_a],
                    "seed": 777888999,
                },
            )
            prof_a_row = store.profile_get(conn_a, pid_a)
            grp_a_row = conn_a.execute("SELECT * FROM groups WHERE id = ?", (gid_a,)).fetchone()
            tag_a_row = conn_a.execute("SELECT * FROM tags WHERE id = ?", (tid_a,)).fetchone()
            px_a_row = conn_a.execute("SELECT * FROM proxies WHERE id = ?", (pxid_a,)).fetchone()

        status_before_a = run_cli(["sync", "status"], home_a)
        assert status_before_a["outbox_count"] == 4

        # Device A sync now; Device B sync now; lalu Device A sync lagi untuk menarik Profil Lokal B
        sync_res_a = run_cli(["sync", "now"], home_a)
        sync_res_b = run_cli(["sync", "now"], home_b)
        run_cli(["sync", "now"], home_a)

        status_after_a = run_cli(["sync", "status"], home_a)
        assert status_after_a["outbox_count"] == 0
        assert status_after_a["last_pulled_seq"] > 0

        # Verifikasi password proxy di server terenkripsi (bukan plaintext)
        with sync_server.connect_server_db(server_dir / "server_sync.db") as sconn:
            s_proxy = sconn.execute(
                "SELECT * FROM sync_proxies WHERE uuid = ?", (px_a_row["uuid"],)
            ).fetchone()
            assert s_proxy is not None
            assert s_proxy["proxy_password_enc"].startswith("v1:enc:")
            assert "rahasia_proxy_123" not in s_proxy["proxy_password_enc"]

            s_prof = sconn.execute(
                "SELECT * FROM sync_profiles WHERE uuid = ?", (prof_a_row["uuid"],)
            ).fetchone()
            assert s_prof is not None
            assert "rahasia_proxy_123" not in s_prof["proxy_config"]
            assert "proxy_password_enc" in s_prof["proxy_config"]

        # Verifikasi data di Device B
        with store.db(db_path=home_b / "antidetect.db") as conn_b:
            prof_b_row = conn_b.execute(
                "SELECT * FROM profiles WHERE uuid = ?", (prof_a_row["uuid"],)
            ).fetchone()
            assert prof_b_row is not None, "Profil Akun 01 harus muncul di Device B"
            assert prof_b_row["name"] == "Akun 01"
            assert prof_b_row["uuid"] == prof_a_row["uuid"]
            assert prof_b_row["id"] != pid_a, "ID integer lokal di Device B berbeda dari Device A"
            assert prof_b_row["note"] == "Catatan awal Akun 01"
            assert prof_b_row["seed"] == 777888999

            grp_b_row = conn_b.execute(
                "SELECT * FROM groups WHERE id = ?", (prof_b_row["group_id"],)
            ).fetchone()
            assert grp_b_row is not None
            assert grp_b_row["title"] == "Grup Cabang"
            assert grp_b_row["uuid"] == grp_a_row["uuid"]

            b_tag_ids = json.loads(prof_b_row["tag_ids"])
            assert len(b_tag_ids) == 1
            tag_b_row = conn_b.execute(
                "SELECT * FROM tags WHERE id = ?", (b_tag_ids[0],)
            ).fetchone()
            assert tag_b_row is not None
            assert tag_b_row["title"] == "Penting"
            assert tag_b_row["uuid"] == tag_a_row["uuid"]

            px_b_row = conn_b.execute(
                "SELECT * FROM proxies WHERE uuid = ?", (px_a_row["uuid"],)
            ).fetchone()
            assert px_b_row is not None
            assert px_b_row["proxy_ip"] == "198.51.100.25"
            assert px_b_row["proxy_password"] == "rahasia_proxy_123"

            b_proxy_cfg = json.loads(prof_b_row["proxy_config"])
            assert b_proxy_cfg["proxy_password"] == "rahasia_proxy_123"
            pid_b = prof_b_row["id"]

        print(
            json.dumps(
                {
                    "profile_uuid": prof_a_row["uuid"],
                    "device_a_local_id": pid_a,
                    "device_b_local_id": pid_b,
                    "group_uuid": grp_a_row["uuid"],
                    "tag_uuid": tag_a_row["uuid"],
                    "sync_a": {"pushed": sync_res_a["pushed"], "pulled": sync_res_a["pulled"]},
                    "sync_b": {"pushed": sync_res_b["pushed"], "pulled": sync_res_b["pulled"]},
                },
                indent=2,
            )
        )

        print("=== Tes 3: Sinkronisasi Dua Arah dan Penghapusan (Soft Delete & Purge) ===")
        # Buat direktori profil lokal di Device B untuk menguji penghapusan direktori saat purge
        prof_dir_b = home_b / "profiles" / str(pid_b) / "data"
        prof_dir_b.mkdir(parents=True, exist_ok=True)
        (prof_dir_b / "Preferences").write_text("{}", encoding="utf-8")

        # Device B mengubah catatan profil "Akun 01"
        with store.db(db_path=home_b / "antidetect.db") as conn_b:
            store.update_profile(
                conn_b, pid_b, {"note": "Catatan diperbarui oleh Device B"}
            )

        run_cli(["sync", "now"], home_b)
        run_cli(["sync", "now"], home_a)

        with store.db(db_path=home_a / "antidetect.db") as conn_a:
            prof_a_updated = store.profile_get(conn_a, pid_a)
            assert prof_a_updated["note"] == "Catatan diperbarui oleh Device B"

        # Device A menghapus profil ke keranjang sampah (soft_delete), sync ke B
        with store.db(db_path=home_a / "antidetect.db") as conn_a:
            store.soft_delete_profile(conn_a, pid_a)

        run_cli(["sync", "now"], home_a)
        run_cli(["sync", "now"], home_b)

        with store.db(db_path=home_b / "antidetect.db") as conn_b:
            prof_b_trashed = store.profile_get(conn_b, pid_b)
            assert prof_b_trashed is not None
            assert prof_b_trashed["deleted_at"] is not None, "Profil di B harus masuk keranjang sampah"

        # Device A menghapus profil secara permanen (purge), sync ke B
        with store.db(db_path=home_a / "antidetect.db") as conn_a:
            store.delete_profile_permanent(conn_a, pid_a)

        run_cli(["sync", "now"], home_a)
        run_cli(["sync", "now"], home_b)

        with store.db(db_path=home_b / "antidetect.db") as conn_b:
            prof_b_purged = store.profile_get(conn_b, pid_b)
            assert prof_b_purged is None, "Profil di Device B harus terhapus permanen"
            assert not (home_b / "profiles" / str(pid_b)).exists(), (
                "Direktori profil lokal di Device B harus ikut terhapus"
            )

        with sync_server.connect_server_db(server_dir / "server_sync.db") as sconn:
            tombstone = sconn.execute(
                "SELECT purged_at FROM sync_profiles WHERE uuid = ?",
                (prof_a_row["uuid"],),
            ).fetchone()
            assert tombstone is not None and tombstone["purged_at"] is not None

        print(
            json.dumps(
                {
                    "bidirectional_note_verified": True,
                    "soft_delete_verified": True,
                    "permanent_purge_verified": True,
                    "server_tombstone_purged_at": tombstone["purged_at"],
                },
                indent=2,
            )
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("=== Tes 4: Offline Outbox dan Coalescing ===")
    # Saat ini server sudah dimatikan (offline). Lakukan mutasi di Device A.
    with store.db(db_path=home_a / "antidetect.db") as conn_a:
        pid_off = store.create_profile(
            conn_a, {"name": "Akun Offline 01", "note": "Draft 1"}
        )
        store.update_profile(conn_a, pid_off, {"note": "Draft 2"})
        store.update_profile(conn_a, pid_off, {"note": "Draft Final Saat Offline"})
        prof_off_row = store.profile_get(conn_a, pid_off)

        outbox_rows = conn_a.execute(
            "SELECT * FROM sync_outbox WHERE entity_uuid = ?",
            (prof_off_row["uuid"],),
        ).fetchall()
        assert len(outbox_rows) == 1, (
            f"Coalescing outbox harus menyatukan upsert berurutan menjadi 1 baris, ditemukan: {len(outbox_rows)}"
        )

        # Coba jalankan push saat server mati; harus gagal namun item tetap di outbox
        failed_as_expected = False
        try:
            sync_agent.sync_cycle(conn_a)
        except sync_agent.SyncAgentError:
            failed_as_expected = True
        assert failed_as_expected, "Sync saat server offline harus melempar SyncAgentError"

        outbox_after_fail = conn_a.execute(
            "SELECT * FROM sync_outbox WHERE entity_uuid = ?",
            (prof_off_row["uuid"],),
        ).fetchone()
        assert outbox_after_fail is not None
        assert outbox_after_fail["attempts"] >= 1

    # Nyalakan kembali server di port yang sama
    httpd2 = sync_server.start_background_server("127.0.0.1", port, data_dir=server_dir)
    try:
        res_online_a = run_cli(["sync", "now"], home_a)
        res_online_b = run_cli(["sync", "now"], home_b)

        status_online_a = run_cli(["sync", "status"], home_a)
        assert status_online_a["outbox_count"] == 0, "Outbox harus kosong setelah server kembali online"

        with store.db(db_path=home_b / "antidetect.db") as conn_b:
            prof_off_b = conn_b.execute(
                "SELECT * FROM profiles WHERE uuid = ?", (prof_off_row["uuid"],)
            ).fetchone()
            assert prof_off_b is not None
            assert prof_off_b["name"] == "Akun Offline 01"
            assert prof_off_b["note"] == "Draft Final Saat Offline"

        print(
            json.dumps(
                {
                    "coalesced_outbox_rows": 1,
                    "outbox_after_reconnect": status_online_a["outbox_count"],
                    "synced_offline_profile_uuid": prof_off_row["uuid"],
                    "synced_note_on_device_b": prof_off_b["note"],
                    "push_online_a": res_online_a["pushed"],
                    "pull_online_b": res_online_b["pulled"],
                },
                indent=2,
            )
        )

        print("=== Tes 5: Distributed Profile Lease ===")
        profile_uuid = prof_off_row["uuid"]
        pid_a_off = prof_off_row["id"]
        pid_b_off = prof_off_b["id"]

        lease_a = test_lease_acquire_and_conflict(home_a, home_b, profile_uuid, pid_b_off)
        test_lease_renew_heartbeat(home_a, profile_uuid, lease_a)
        lease_b = test_lease_release_and_reacquire(
            home_a, home_b, profile_uuid, lease_a, pid_a_off, pid_b_off
        )
        lease_a2 = test_force_takeover(home_a, home_b, profile_uuid, lease_b)
        test_lease_expiration(home_a, home_b, profile_uuid, lease_a2)
    finally:
        httpd2.shutdown()
        httpd2.server_close()

    test_offline_open_policy(home_a, prof_off_row["uuid"])


def test_lease_acquire_and_conflict(home_a, home_b, profile_uuid, pid_b):
    print("--- 5.1 test_lease_acquire_and_conflict ---")
    with store.db(db_path=home_a / "antidetect.db") as conn_a:
        lease_a = sync_agent.acquire_lease(conn_a, profile_uuid)
        assert lease_a["profile_uuid"] == profile_uuid
        assert lease_a["lease_token"].startswith("ls_")
        assert lease_a["fencing_token"] == 1
        assert lease_a["expires_at"] > int(time.time())

        local_row = conn_a.execute(
            "SELECT * FROM local_leases WHERE profile_uuid = ?", (profile_uuid,)
        ).fetchone()
        assert local_row is not None
        assert local_row["is_local_holder"] == 1
        assert local_row["lease_token"] == lease_a["lease_token"]

    # Device B mencoba mengakuisisi profil yang sama -> ditolak dengan error 2004 (LEASE_HELD)
    conflict_caught = None
    with store.db(db_path=home_b / "antidetect.db") as conn_b:
        try:
            sync_agent.acquire_lease(conn_b, profile_uuid)
        except sync_agent.SyncLeaseError as err:
            conflict_caught = err

    assert conflict_caught is not None, "Device B harus ditolak dengan SyncLeaseError"
    assert conflict_caught.code == 2004
    assert "Laptop-A" in conflict_caught.message
    assert conflict_caught.data.get("holder_device_name") == "Laptop-A"
    assert conflict_caught.data.get("retry_after_seconds", 0) >= 1

    # Uji integrasi launcher.open_profile dan api.profile_open di Device B (tanpa membuka Chrome)
    prev_db_path = store.DB_PATH
    store.DB_PATH = home_b / "antidetect.db"
    try:
        api_err_caught = None
        try:
            api.profile_open({"profile_id": pid_b})
        except api.ApiError as api_err:
            api_err_caught = api_err
        assert api_err_caught is not None
        assert api_err_caught.code == 1009
        assert "Laptop-A" in api_err_caught.message
    finally:
        store.DB_PATH = prev_db_path

    print(
        json.dumps(
            {
                "acquired_by": "Laptop-A",
                "fencing_token": lease_a["fencing_token"],
                "conflict_code": conflict_caught.code,
                "conflict_message": conflict_caught.message,
                "api_error_code": 1009,
            },
            indent=2,
        )
    )
    return lease_a


def test_lease_renew_heartbeat(home_a, profile_uuid, lease_a):
    print("--- 5.2 test_lease_renew_heartbeat ---")
    base_time = int(time.time()) + 25
    with mock.patch("antidetect.sync_server.time.time", return_value=base_time):
        with store.db(db_path=home_a / "antidetect.db") as conn_a:
            renew_res = sync_agent.renew_leases(conn_a)
            assert len(renew_res["renewed"]) == 1
            entry = renew_res["renewed"][0]
            assert entry["profile_uuid"] == profile_uuid
            assert entry["status"] == "ok"
            assert entry["expires_at"] == base_time + 60
            assert entry["expires_at"] > lease_a["expires_at"]

            local_row = conn_a.execute(
                "SELECT expires_at FROM local_leases WHERE profile_uuid = ?",
                (profile_uuid,),
            ).fetchone()
            assert local_row["expires_at"] == base_time + 60

    # Uji thread background heartbeat
    hb_time = base_time + 20
    with mock.patch("antidetect.sync_server.time.time", return_value=hb_time):
        sync_agent.start_heartbeat(interval=0.1, db_path=home_a / "antidetect.db")
        try:
            time.sleep(0.25)
        finally:
            sync_agent.stop_heartbeat()

    with store.db(db_path=home_a / "antidetect.db") as conn_a:
        local_row = conn_a.execute(
            "SELECT expires_at FROM local_leases WHERE profile_uuid = ?",
            (profile_uuid,),
        ).fetchone()
        assert local_row["expires_at"] == hb_time + 60

    print(
        json.dumps(
            {
                "previous_expires_at": lease_a["expires_at"],
                "renewed_expires_at": local_row["expires_at"],
                "heartbeat_verified": True,
            },
            indent=2,
        )
    )


def test_lease_release_and_reacquire(
    home_a, home_b, profile_uuid, lease_a, pid_a=None, pid_b=None
):
    print("--- 5.3 test_lease_release_and_reacquire ---")
    with store.db(db_path=home_a / "antidetect.db") as conn_a:
        rel_res = sync_agent.release_lease(
            conn_a, profile_uuid, lease_token=lease_a["lease_token"]
        )
        assert rel_res.get("released") is True
        local_row = conn_a.execute(
            "SELECT * FROM local_leases WHERE profile_uuid = ?", (profile_uuid,)
        ).fetchone()
        assert local_row is None

    with store.db(db_path=home_b / "antidetect.db") as conn_b:
        lease_b = sync_agent.acquire_lease(conn_b, profile_uuid)
        assert lease_b["profile_uuid"] == profile_uuid
        assert lease_b["fencing_token"] == 2
        assert lease_b["lease_token"] != lease_a["lease_token"]

    # Uji pembersihan proses mati (_prune_entry) dan profile-open-state-reset tanpa Chrome
    if pid_b is not None:
        prev_db_path = store.DB_PATH
        store.DB_PATH = home_b / "antidetect.db"
        try:
            dead_entry = {
                "proc": None,
                "info": {
                    "profile_id": pid_b,
                    "uuid": profile_uuid,
                    "pid": 99999999,
                    "lease_token": lease_b["lease_token"],
                    "fencing_token": lease_b["fencing_token"],
                },
            }
            launcher._open[pid_b] = dead_entry
            alive = launcher._prune_entry(pid_b, dead_entry)
            assert alive is False
            assert pid_b not in launcher._open

            # Setelah _prune_entry melepas lease B, Device B mengakuisisi ulang untuk tes berikutnya
            with store.db(db_path=home_b / "antidetect.db") as conn_b:
                lease_b = sync_agent.acquire_lease(conn_b, profile_uuid)
                assert lease_b["fencing_token"] == 3
        finally:
            store.DB_PATH = prev_db_path

    print(
        json.dumps(
            {
                "released_by_a": True,
                "reacquired_by_b": True,
                "prune_dead_process_released_lease": True,
                "new_fencing_token": lease_b["fencing_token"],
            },
            indent=2,
        )
    )
    return lease_b


def test_force_takeover(home_a, home_b, profile_uuid, lease_b):
    print("--- 5.4 test_force_takeover ---")
    # Device B sedang memegang lease aktif (fencing_token=2).
    # Device A melakukan acquire dengan force=True.
    with store.db(db_path=home_a / "antidetect.db") as conn_a:
        lease_a2 = sync_agent.acquire_lease(conn_a, profile_uuid, force=True)
        assert lease_a2["profile_uuid"] == profile_uuid
        assert lease_a2["fencing_token"] == lease_b["fencing_token"] + 1
        assert lease_a2["lease_token"] != lease_b["lease_token"]

    # Device B mencoba memperpanjang lease lamanya -> harus mendapat status "stolen"
    with store.db(db_path=home_b / "antidetect.db") as conn_b:
        renew_b = sync_agent.renew_leases(
            conn_b,
            leases=[
                {
                    "profile_uuid": profile_uuid,
                    "lease_token": lease_b["lease_token"],
                    "fencing_token": lease_b["fencing_token"],
                }
            ],
        )
        assert len(renew_b["renewed"]) == 1
        assert renew_b["renewed"][0]["status"] == "stolen"

        stolen_row = conn_b.execute(
            "SELECT * FROM local_leases WHERE profile_uuid = ? AND is_local_holder = 1",
            (profile_uuid,),
        ).fetchone()
        assert stolen_row is None

    print(
        json.dumps(
            {
                "force_takeover_by_a": True,
                "fencing_token_after_takeover": lease_a2["fencing_token"],
                "device_b_renew_status": renew_b["renewed"][0]["status"],
            },
            indent=2,
        )
    )
    return lease_a2


def test_lease_expiration(home_a, home_b, profile_uuid, lease_a2):
    print("--- 5.5 test_lease_expiration ---")
    # Device A memegang lease (lease_a2). Waktu server dimajukan melampaui TTL 60 detik.
    future_epoch = int(lease_a2["expires_at"]) + 10
    with mock.patch("antidetect.sync_server.time.time", return_value=future_epoch):
        with store.db(db_path=home_b / "antidetect.db") as conn_b:
            lease_b2 = sync_agent.acquire_lease(conn_b, profile_uuid, force=False)
            assert lease_b2["profile_uuid"] == profile_uuid
            assert lease_b2["fencing_token"] == lease_a2["fencing_token"] + 1
            assert lease_b2["expires_at"] == future_epoch + 60

            # Bersihkan lease di akhir tes online
            sync_agent.release_lease(
                conn_b, profile_uuid, lease_token=lease_b2["lease_token"]
            )

    print(
        json.dumps(
            {
                "expired_lease_token": lease_a2["lease_token"],
                "reacquired_without_force": True,
                "new_fencing_token": lease_b2["fencing_token"],
            },
            indent=2,
        )
    )


def test_offline_open_policy(home_a, profile_uuid):
    print("--- 5.6 test_offline_open_policy ---")
    # Server sudah dimatikan (httpd2.shutdown()).
    with store.db(db_path=home_a / "antidetect.db") as conn_a:
        res_offline = sync_agent.acquire_lease(conn_a, profile_uuid, timeout=1.0)
        assert res_offline["status"] == "offline_allowed"
        assert res_offline["offline"] is True
        assert res_offline["fencing_token"] == 0
        assert "warning" in res_offline

    print(
        json.dumps(
            {
                "offline_open_status": res_offline["status"],
                "offline_flag": res_offline["offline"],
                "warning": res_offline["warning"],
            },
            indent=2,
        )
    )


def main():
    try:
        test_1_legacy_migration()
        test_2_and_3_and_4()
        print("ALL SYNC PHASE 1 & PHASE 2 TESTS PASSED")
    finally:
        shutil.rmtree(WORK_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
