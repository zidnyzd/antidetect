# antidetect

Server API lokal yang meniru kontrak **ixBrowser Local API v2**, berjalan di
atas engine Chromium milik sendiri (fingerprint-chromium). Semua lokal, tanpa
akun, tanpa langganan.

- Engine: fingerprint-chromium 150, AppImage diekstrak ke
  `~/.local/share/antidetect/squashfs-root` (`engine.AppImage` disimpan di sebelahnya).
- API: `http://127.0.0.1:53200/api/v2/` — SDK Python resmi ixBrowser
  (`ixbrowser-local-api`) bisa dipakai apa adanya sebagai klien.
- UI: belum ada (roadmap).

## Pakai

```bash
python3 -m antidetect serve                                  # jalankan API
python3 -m antidetect create "Akun 1" --tz Asia/Jakarta --lang en-US
python3 -m antidetect open 1
python3 -m antidetect close 1
python3 -m antidetect list
```

Dari Python dengan SDK resmi ixBrowser:

```bash
pip install ixbrowser-local-api selenium
venv/bin/python scripts/selftest.py
```

## Status

- [x] profile create/list/update/delete/copy/open/close/opened-list/random-fingerprint
- [x] group, tag, proxy listing; proxy http/https/socks5 tanpa autentikasi
- [x] fingerprint: platform, cores, timezone, language, brand
- [x] selenium/chromedriver attach (kontrak `webdriver` + `debugging_address`)
- [ ] proxy autentikasi (jembatan gost)
- [ ] import/export cookie, extensions, GUI

## Catatan

- Data profil: `~/.local/share/antidetect/profiles/<id>/data`.
- `chrome.log` per profil menampung stderr engine.
- `DISPLAY` default `:0`, `ANTIDETECT_NO_SANDBOX=1` untuk lingkungan tanpa sandbox.
- `ANTIDETECT_ENGINE_DIR` untuk menunjuk engine lain.

## Autostart (opsional)

```ini
# ~/.config/systemd/user/antidetect.service
[Unit]
Description=antidetect local API
[Service]
Environment=DISPLAY=:0
ExecStart=%h/Projects/antidetect/venv/bin/python -m antidetect serve
WorkingDirectory=%h/Projects/antidetect
Restart=on-failure
[Install]
WantedBy=default.target
```

## Lisensi

AGPL-3.0-only, lihat `LICENSE`. Engine fingerprint-chromium diunduh terpisah dari repo ini dan
merupakan proyek pihak ketiga berlisensi BSD-3-clause; repositori ini tidak membundel engine.
