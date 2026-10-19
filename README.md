# antidetect

Server API lokal yang meniru kontrak **ixBrowser Local API v2**, berjalan di
atas engine Chromium milik sendiri (fingerprint-chromium). Semua lokal, tanpa
akun, tanpa langganan.

- Engine: fingerprint-chromium 150, AppImage diekstrak ke
  `~/.local/share/antidetect/squashfs-root` (`engine.AppImage` disimpan di sebelahnya).
- API: `http://127.0.0.1:53200/api/v2/`. SDK Python resmi ixBrowser
  (`ixbrowser-local-api`) bisa dipakai apa adanya sebagai klien.
- UI: Vue 3 + Element Plus di `ui/`, layout mengikuti ixBrowser 2.10 (sidebar
  gelap, topbar putih, tabel profil, dialog 4 tab). Dev server `127.0.0.1:5180`.

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
- [x] UI: daftar profil, buat/edit 4 tab, tag per profil, kelola grup,
  waktu dibuat dan terakhir dibuka, buka/tutup, duplikat/hapus, filter,
  pagination, halaman proxy dan pengaturan
- [x] cookie import/export per profil dan aksi cache (cache, cache + cookie,
  cache simpan extension, hapus password tersimpan)
- [x] keranjang sampah: hapus jadi soft delete, pulihkan, hapus permanen,
  kosongkan keranjang
- [x] operasi massal (buka/tutup, ubah grup, catatan, proxy, platform),
  cek proxy dengan IP dan latensi, pilih proxy tersimpan, atur jendela
- [x] kelola extension lokal (unggah zip/crx, daftar, hapus dengan proteksi
  pemakaian) dan pemilihan extension per profil
- [x] info engine/kernel di Pengaturan, acak seed, kolom GPU Vendor/Renderer
  dan opsi tampilkan GPU host (binary 150 belum menerapkan flag GPU)
- [x] ekspor/impor profil (JSON), penampil bookmark dan password tersimpan
- [x] filter tag, pilih kolom tersimpan, preset platform akun
- [x] halaman Dasbor dan halaman API dengan contoh curl dan Selenium
- [ ] pemilihan versi kernel dan penegakan fingerprint GPU di engine

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
- Flag GPU `--fingerprint-gpu-vendor`, `--fingerprint-gpu-renderer`, dan
  `--disable-gpu-fingerprint` tidak ada di binary 150. Nilai GPU Vendor/Renderer
  tetap disimpan dan UI memberi peringatan, tetapi belum diterapkan engine.
  Opsi tampilkan GPU host memakai `--disable-spoofing=gpu` bila tersedia.
- Pemilihan versi kernel belum ada; `engine-info` hanya melaporkan kernel yang
  terpasang dan launcher selalu memakai engine bawaan.
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

## UI

Frontend di `ui/`: Vue 3 + Element Plus + Vite. Layout mengikuti ixBrowser
2.10.18: sidebar gelap 210 px, topbar putih 50 px, kanvas terang, tabel profil
dengan toolbar dua baris, dan dialog Buat/Edit Profil 4 tab (Akun Platform,
Konfigurasi Proxy, Fingerprint, Preferensi). Halaman Proxy dan Pengaturan juga
aktif. Kolom Waktu menampilkan waktu dibuat dan terakhir dibuka, dengan tooltip
untuk masing-masing nilai. Tombol di samping filter grup membuka kelola grup:
tambah, edit nama dan urutan, cari, serta hapus. Grup Default dan grup yang
masih berisi profil dilindungi dari penghapusan.

Menu tiap baris profil menyediakan Cookie (muat, impor file, salin, unduh,
simpan), bersihkan cache, cache + cookie, cache simpan extension, dan hapus
password tersimpan. Hapus profil memindahkannya ke halaman Keranjang Sampah;
dari sana profil bisa dipulihkan, dihapus permanen, atau dikosongkan
sekaligus.

Centang beberapa profil untuk membuka/menutup, memindahkan grup, mengubah
catatan/proxy/platform, atau menghapus sekaligus. Tombol Atur Jendela menata
jendela profil yang terbuka. Halaman Proxy punya tombol Tes yang menampilkan IP
keluar dan latensi; dialog profil bisa mengisi konfigurasi dari proxy tersimpan.

Halaman Extension menyimpan extension lokal dari unggahan zip/crx, menampilkan
versi dan ukurannya, serta menolak hapus selama masih dipakai profil. Tab
Extension di dialog profil memilih extension yang dimuat saat profil dibuka.

Profil bisa diekspor ke JSON dan diimpor kembali (nama diberi akhiran
"(impor)", seed baru, cookie ikut). Menu baris juga menyediakan penampil
Bookmark dan Password Tersimpan; password didekripsi lokal dan hanya
ditampilkan saat tombol mata ditekan.

Dasbor jadi halaman pertama berisi ringkasan profil, grup, extension, proxy,
dan profil terbaru. Halaman API menampilkan base URL lokal, status health,
contoh payload dan curl per aksi, cuplikan Selenium, serta tombol salin. Daftar
profil punya filter tag di samping filter grup dan status, plus pemilih kolom
yang tersimpan di localStorage. Dialog profil menyediakan preset platform akun
(Facebook, TikTok, Instagram, Shopee, Tokopedia, Google, Lazada, Custom) yang
mengisi `site_id` dan URL awal yang tetap bisa diedit.

```bash
cd ui
npm install
npm run dev        # http://127.0.0.1:5180, proxy /api dan /health ke :53200
npm run build      # hasil produksi ke ui/dist
```

Butuh Node.js 18+. Alur yang sudah diuji lewat UI: buat, edit, duplikat, hapus
ke keranjang, buka/tutup profil dengan timestamp terakhir dibuka, tag per
profil, kelola grup, filter status dan grup, pencarian, pagination, cookie
import/export, aksi cache, pemulihan keranjang sampah, operasi massal, cek
proxy, pilih proxy tersimpan, atur jendela, filter tag, pilih kolom,
ekspor/impor profil, bookmark, password tersimpan, preset platform, dasbor,
halaman API, serta CRUD proxy. Shell desktop (Tauri/Electron) menyusul.

## Lisensi

AGPL-3.0-only, lihat `LICENSE`. Engine fingerprint-chromium diunduh terpisah
dari repo ini dan merupakan proyek pihak ketiga berlisensi BSD-3-clause; repositori
ini tidak membundel engine. Gost (`go-gost/gost`, MIT) juga pihak ketiga dan
diunduh terpisah oleh `scripts/fetch-gost.sh`, tidak dibundel.
