# antidetect

Server API lokal yang meniru kontrak **ixBrowser Local API v2**, berjalan di
atas engine Chromium milik sendiri (fingerprint-chromium). Semua lokal, tanpa
akun, tanpa langganan.

- Engine: fingerprint-chromium 150, AppImage diekstrak ke
  `~/.local/share/antidetect/squashfs-root` (`engine.AppImage` disimpan di sebelahnya).
- API: `http://127.0.0.1:53200/api/v2/`. SDK Python resmi ixBrowser
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
- [x] close halus: target page ditutup lewat `GET /json/close/<id>` sebelum proses
  dimatikan, sehingga cookie/session ter-flush ke disk (SIGTERM langsung tidak flush)
- [x] proxy dengan autentikasi user/password via jembatan gost (http/https/socks5)
- [x] fingerprint: platform, system_version, cores, memory, timezone, language, brand
- [x] selenium/chromedriver attach (kontrak `webdriver` + `debugging_address`)
- [ ] import/export cookie, extensions, GUI

## Pemetaan fingerprint_config ke flag engine

| fingerprint_config | flag engine | efek |
| --- | --- | --- |
| `platform` (`Windows`/`Macos`) | `--fingerprint-platform=windows/macos` | UA string, `navigator.platform`, UA-CH `platform`. Android/iOS (ua_type 2) tidak didukung engine ini |
| `system_version` (`11`/`10`) | `--fingerprint-platform-version=<versi>` | UA-CH high entropy `platformVersion`; UA string tetap `Windows NT 10.0` |
| `hardware_concurrency` | `--fingerprint-hardware-concurrency=N` | `navigator.hardwareConcurrency` |
| `device_memory` | `--fingerprint-memory=N` | `navigator.deviceMemory` |
| `br_version` | `--fingerprint-brand-version=<versi>` | versi brand di UA-CH |
| `language` | `--lang`, `--accept-lang` | `navigator.language` dan header `Accept-Language` |
| `timezone` | `--timezone=<zona>` | zona waktu JS |
| seed profil | `--fingerprint=<seed>` | seed internal engine, sumber konsistensi kanvas/WebGL/fonts |

`system_version` dan `device_memory` hanya diterapkan bila ada isinya; keduanya
terverifikasi berpengaruh lewat `assets/fptest.html` (lihat NOTES-1.md).

## Proxy dengan autentikasi

Chromium tidak bisa mengirim `Proxy-Authorization` untuk proxy hulu. Kalau
`proxy_user`/`proxy_password` diisi, server menjalankan satu proses gost per
profil:

```text
gost -L http://127.0.0.1:<port-lokal> -F http://user:pass@ip:port
```

Chrome diarahkan ke `--proxy-server=http://127.0.0.1:<port-lokal>`; TLS ke proxy
hulu ditangani gost. Proxy `socks5` memakai listener `socks5://` lokal. Saat
`profile-close` (atau open gagal), proses gost ikut dimatikan. PID gost ada di
`state.json` dan `profile-open` mengembalikannya di field `gost_pid` (field
`proxy` berisi alamat hop lokal). Log gost per profil: `profiles/<id>/gost.log`.

Pasang gost (idempoten, rilis linux amd64 terbaru dari `go-gost/gost`):

```bash
scripts/fetch-gost.sh        # butuh gh atau curl; memasang ke ~/.local/bin/gost
```

`ANTIDETECT_GOST` bisa dipakai untuk menunjuk binary gost lain. Uji end-to-end
proxy auth tanpa keluar lewat proxy internet: `scripts/test-auth-proxy.py`
(proxy CONNECT lokal yang menuntut Basic auth, kredensial benar dan salah).

## Yang belum didukung engine

- `resolving_power` (lebar x tinggi layar). Flag `--fingerprint-screen-width`
  dan `--fingerprint-screen-height` ada di binary tapi tidak berefek di engine
  150: headless tetap 800x600, headed mengikuti monitor nyata (1920x1080)
  walaupun flag diisi 1920x1080 atau nilai lain.
- Faktor skala perangkat. `--fingerprint-device-scale-factor` tidak mengubah
  `window.devicePixelRatio` (tetap 1 di headless maupun headed).
- Platform Android/iOS dan mode mobile (ua_type 2): engine hanya Windows/macOS.
- Belum dipetakan dan tidak diklaim: `fonts`, `webrtc`, `canvas`, `audio_context`,
  `webgl_*`, `javascript_memory_type`, dan atribut SDK lain di luar tabel.
- `resolving_power_type`, `language_type`, `timezone_type`, `location*` (tidak
  berpengaruh pada launcher; nilai mentah tetap disimpan di profil).

## Catatan

- Data profil: `~/.local/share/antidetect/profiles/<id>/data`.
- `chrome.log` per profil menampung stderr engine.
- `DISPLAY` default `:0`, `ANTIDETECT_NO_SANDBOX=1` untuk lingkungan tanpa sandbox.
- `ANTIDETECT_ENGINE_DIR` untuk menunjuk engine lain.

## Tes

```bash
./venv/bin/python -m antidetect serve                       # server harus jalan
./venv/bin/python scripts/selftest.py                       # SDK -> API -> engine -> selenium
DISPLAY=:0 ./venv/bin/python scripts/isolation_test.py      # isolasi cookie antar profil + close halus
./venv/bin/python scripts/test-auth-proxy.py                # proxy auth end-to-end
```

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

## UI (prototype)

Frontend prototype di `ui/`: Vue 3 + Element Plus + Vite, berbicara ke API lokal yang sama
(dev server mem-proxy `/api` dan `/health` ke `127.0.0.1:53200`).

```bash
cd ui
npm install
npm run dev        # http://127.0.0.1:5180
```

Butuh Node.js 18+. Shell desktop (Tauri/Electron) menyusul setelah arah UI disetujui.

## Lisensi

AGPL-3.0-only, lihat `LICENSE`. Engine fingerprint-chromium diunduh terpisah
dari repo ini dan merupakan proyek pihak ketiga berlisensi BSD-3-clause; repositori
ini tidak membundel engine. Gost (`go-gost/gost`, MIT) juga pihak ketiga dan
diunduh terpisah oleh `scripts/fetch-gost.sh`, tidak dibundel.
