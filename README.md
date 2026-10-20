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
- [x] impor massal proxy (lima format, laporan per baris) dan ekspor teks
  dengan opsi menyertakan kredensial
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
- [x] preferensi jendela per profil: ukuran, posisi, buka DevTools, dan
  argumen startup yang divalidasi (flag berbahaya ditolak)
- [x] kelola extension lokal (unggah zip/crx, daftar, hapus dengan proteksi
  pemakaian) dan pemilihan extension per profil
- [x] info engine/kernel di Pengaturan, acak seed, GPU vendor dan renderer
  otomatis dari seed fingerprint (engine 150 tidak menerima nilai manual)
- [x] multi-select "Matikan spoofing" (font, audio, canvas, clientrects, gpu)
  yang dikirim ke engine sebagai `--disable-spoofing`
- [x] ekspor/impor profil (JSON), kelola bookmark (tambah/hapus) dan hapus
  password tersimpan per entri
- [x] ekspor profil terenkripsi kata sandi (AES-256, minimal 8 karakter)
- [x] filter tag, pilih kolom tersimpan, preset platform akun
- [x] halaman Dasbor dan halaman API dengan contoh curl dan Selenium
- [x] log operasi lokal dengan filter jenis, pencarian, rentang tanggal,
  ekspor CSV, dan bersihkan log
- [x] log Chrome/Proxy per profil (2000 baris terakhir, batas 1 MB)
- [x] pilih kernel per profil dari folder `kernels/<nama>/chrome` dengan
  validasi path dan fallback ke engine bawaan
- [x] impor profil CSV: satu baris jadi satu profil, grup dan proxy baru
  dibuat otomatis, laporan per baris

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
| seed profil | `--fingerprint=<seed>` | seed internal engine, sumber konsistensi kanvas/WebGL/fonts dan GPU vendor/renderer |
| `disable_spoofing` (`font`, `audio`, `canvas`, `clientrects`, `gpu`) | `--disable-spoofing=<nama,nama>` | komponen yang memakai nilai asli host; `gpu` berarti GPU host |

`system_version` dan `device_memory` hanya diterapkan bila ada isinya; keduanya
terverifikasi berpengaruh lewat `assets/fptest.html` (lihat NOTES-1.md).

GPU vendor dan renderer tidak punya input manual: engine membangkitkannya dari
seed fingerprint. Nilai `disable_spoofing` dikirim apa adanya sebagai daftar
comma separated ke `--disable-spoofing`, dan API menolak nama di luar lima
komponen di atas dengan kode 1000.

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

## Impor profil CSV

Tombol "Impor CSV" di toolbar daftar profil menerima file CSV datar. Satu baris
data jadi satu profil, dan kolom yang dibaca:

| kolom | keterangan |
| --- | --- |
| `name` | wajib, nama profil, maksimal 100 karakter |
| `group` | nama grup, profil baru masuk ke grup itu; grup yang belum ada dibuat otomatis |
| `note` | catatan profil, maksimal 200 karakter |
| `platform` | `Windows` atau `Macos`, default `Windows` |
| `system_version` | versi sesuai platform, default versi terbaru platform tersebut |
| `proxy_type` | `direct`, `http`, `https`, atau `socks5` |
| `proxy_ip`, `proxy_port` | alamat proxy, port 1 sampai 65535 |
| `proxy_user`, `proxy_password` | kredensial proxy, opsional |
| `site_url` | URL awal profil, harus diawali `http://` atau `https://` |

Kolom lain diabaikan. Batas file 1 MB dan 500 baris data, dan header wajib
memuat kolom `name`. Proxy yang belum ada di daftar proxy dibuat otomatis,
begitu juga grup baru. Satu baris bermasalah tidak membatalkan baris lain:
hasil impor menampilkan jumlah profil dibuat, grup baru, proxy baru, dan daftar
error per nomor baris.

Backend memakai action `profile-import-csv` dengan payload
`{"text": "<isi file csv>"}`.

## Riwayat cek proxy

Setiap proxy yang diuji lewat tombol Tes di halaman Proxy, atau lewat action
`proxy-check` dengan `proxy_id`, hasilnya dicatat di tabel `proxy_checks`.
Kolom `Cek Terakhir` di tabel proxy menampilkan hasil terakhir: IP dan latensi
kalau berhasil, "Gagal: <pesan>" kalau gagal, dan "Belum pernah" kalau proxy
belum pernah diuji. Tombol Riwayat di tiap baris membuka daftar hasil per
proxy, lengkap dengan tombol Muat ulang, Bersihkan riwayat, dan Tutup.
Kolom Cek Terakhir bisa disembunyikan lewat tombol Pilih Kolom.

Maksimal 500 baris riwayat per proxy, baris paling lama dibuang otomatis.
Action yang tersedia:

| action | payload | hasil |
| --- | --- | --- |
| `proxy-check-history` | `{proxy_id, limit}` | `{total, data}` terbaru lebih dulu. Tanpa `proxy_id` semua baris riwayat dikembalikan |
| `proxy-check-history-clear` | `{proxy_id}` | `{count}`, jumlah baris yang dihapus |

Kolom `data` berisi `checked_at`, `ok`, `ip`, `latency_ms`, dan `error`.

## Tes proxy sebelum disimpan

Action `proxy-validate` menjalankan cek proxy tanpa menyimpan dan tanpa
menambah riwayat. Action `proxy-create` dan `proxy-update` menerima parameter
opsional `validate: true`. Kalau nilainya true, proxy diuji dulu dan kalau
gagal permintaan ditolak dengan kode 1000 dan pesan "Proxy gagal diuji:
<alasan>", jadi proxy tidak tersimpan. Tanpa parameter itu perilaku lama
berlaku, sehingga SDK yang tidak mengirim `validate` tidak terpengaruh.

Di UI, switch "Tes sebelum menyimpan" di dialog tambah/edit proxy memakai
action `proxy-validate` sebelum menyimpan. Switch mati secara bawaan.

## Template profil

Template menyimpan salinan konfigurasi satu profil supaya profil baru dibuat
dengan setting yang sama. Halaman Template punya tombol Simpan Template yang
memilih profil sumber dari daftar profil, lalu membuat profil baru dari
template dengan nama baru. Seed profil baru dibuat otomatis, jadi hasil
fingerprintnya berbeda dari template.

Grup disalin kalau grupnya masih ada, kalau tidak profil baru masuk ke grup
Default. Proxy juga hanya disalin kalau baris proxy-nya masih ada di daftar
proxy, kalau tidak profil baru memakai proxy direct. Maksimal 50 template,
nama template maksimal 80 karakter dan harus unik.

| action | payload | hasil |
| --- | --- | --- |
| `template-list` | `{page, limit}` | `{total, data}` dengan `id`, `name`, `created_at`, `profile_count` |
| `template-save` | `{profile_id, name}` | `{id, name, profile_count}` |
| `template-delete` | `{id}` | `true` |
| `template-create-profile` | `{id, name}` | `{profile_id, name, group_id, proxy_config}` |

Nama template kosong, nama yang sudah dipakai, dan template yang sudah 50 buah
ditolak dengan kode 1000.

## Yang belum didukung engine

- `resolving_power` (lebar x tinggi layar). Flag `--fingerprint-screen-width`
  dan `--fingerprint-screen-height` ada di binary tapi tidak berefek di engine
  150: headless tetap 800x600, headed mengikuti monitor nyata (1920x1080)
  walaupun flag diisi 1920x1080 atau nilai lain.
- Faktor skala perangkat. `--fingerprint-device-scale-factor` tidak mengubah
  `window.devicePixelRatio` (tetap 1 di headless maupun headed).
- Platform Android/iOS dan mode mobile (ua_type 2): engine hanya Windows/macOS.
- Flag GPU `--fingerprint-gpu-vendor`, `--fingerprint-gpu-renderer`, dan
  `--disable-gpu-fingerprint` tidak ada di binary 150. GPU vendor dan renderer
  dibuat engine dari seed fingerprint, jadi UI tidak menyediakan input manual.
  Untuk memakai GPU asli host, centang GPU pada multi-select "Matikan
  spoofing", yang dikirim sebagai `--disable-spoofing=gpu`.
- Belum ada pengelola unduhan/update kernel; kernel tambahan harus diletakkan
  manual di `~/.local/share/antidetect/kernels/<nama>/chrome`, lalu dipilih
  per profil lewat tab Preferensi.
- Belum dipetakan dan tidak diklaim: `fonts`, `webrtc`, `canvas`, `audio_context`,
  `webgl_*`, `javascript_memory_type`, dan atribut SDK lain di luar tabel.
- `resolving_power_type`, `language_type`, `timezone_type`, `location*` (tidak
  berpengaruh pada launcher; nilai mentah tetap disimpan di profil).

## Keamanan lokal

API hanya mendengarkan di `127.0.0.1:53200`. CORS membatasi browser ke origin
localhost/127.0.0.1; origin lain tidak mendapat header CORS sehingga halaman
web eksternal tidak bisa memanggil API. Tambahan origin tepercaya bisa diisi
lewat `ANTIDETECT_ALLOWED_ORIGINS` (dipisah koma). API tetap tanpa token agar
kompatibel dengan SDK ixBrowser; proses lokal yang sudah berjalan di mesin ini
dianggap tepercaya.

Ekspor profil bisa diberi kata sandi. Isinya dienkripsi AES-256-CBC dengan
PBKDF2-SHA256 lewat `openssl`, dan impor meminta kata sandi yang sama. Ekspor
tanpa kata sandi tetap JSON biasa yang memuat cookie dan kredensial proxy,
jadi simpan file itu di tempat aman.

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
dengan toolbar dua baris, dan dialog Buat/Edit Profil 5 tab (Akun Platform,
Konfigurasi Proxy, Fingerprint, Extension, Preferensi). Halaman Proxy dan Pengaturan juga
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
Impor Massal menerima lima format (komentar dan baris kosong diabaikan) dan
menampilkan jumlah dibuat, duplikat dilewati, serta error per baris. Ekspor
menghasilkan file teks, dengan pilihan menyertakan kredensial.

Tab Fingerprint tidak punya input GPU vendor atau renderer. Keduanya dibuat
otomatis dari seed fingerprint. Multi-select "Matikan spoofing" memilih
komponen yang memakai nilai asli host (Font, Audio, Canvas, ClientRects, GPU),
dan pilihan itu dikirim ke engine sebagai `--disable-spoofing`.

Tab Preferensi menyimpan ukuran dan posisi jendela, switch buka DevTools, dan
argumen startup Chromium. Argumen dipisah spasi; flag yang bisa merusak isolasi
seperti `--user-data-dir`, `--proxy-server`, dan `--remote-debugging-port`
ditolak saat disimpan.

Tombol Impor CSV di toolbar daftar profil membuka dialog impor profil CSV.
Dialog bisa mengunduh template berisi header dan satu baris contoh, memilih
file CSV, lalu menampilkan jumlah profil dibuat, grup baru, proxy baru, dan
daftar error per baris. Grup dan proxy yang disebut di CSV dibuat otomatis
bila belum ada.

Halaman Proxy punya kolom Cek Terakhir, tombol Riwayat per baris yang membuka
dialog riwayat cek proxy, dan pemilih kolom untuk menyembunyikan kolom Cek
Terakhir. Dialog tambah proxy punya switch "Tes sebelum menyimpan": kalau
dinyalakan, proxy diuji dulu dan yang gagal tidak disimpan. Halaman Template
menyimpan template dari profil yang dipilih, membuat profil baru dari template,
dan menghapus template dengan konfirmasi.

Halaman Extension menyimpan extension lokal dari unggahan zip/crx, menampilkan
versi dan ukurannya, serta menolak hapus selama masih dipakai profil. Tab
Extension di dialog profil memilih extension yang dimuat saat profil dibuka.

Profil bisa diekspor ke JSON dan diimpor kembali (nama diberi akhiran
"(impor)", seed baru, cookie ikut). Menu baris punya Ekspor Terenkripsi yang
meminta kata sandi; impor file terenkripsi akan meminta kata sandi yang sama.
Menu baris juga menyediakan Bookmark (tambah dan hapus, folder otomatis
dibuat) dan Password Tersimpan (hapus per entri, ekspor CSV). Password
didekripsi lokal dan hanya ditampilkan saat tombol mata ditekan. Menambah atau
mengubah password belum didukung engine, simpan lewat halaman login di browser.

Dasbor jadi halaman pertama berisi ringkasan profil, grup, extension, proxy,
dan profil terbaru. Halaman API menampilkan base URL lokal, status health,
contoh payload dan curl per aksi, cuplikan Selenium, serta tombol salin. Daftar
profil punya filter tag di samping filter grup dan status, plus pemilih kolom
yang tersimpan di localStorage. Dialog profil menyediakan preset platform akun
(Facebook, TikTok, Instagram, Shopee, Tokopedia, Google, Lazada, Custom) yang
mengisi `site_id` dan URL awal yang tetap bisa diedit.

Halaman Log mencatat operasi penting (profil, proxy, extension, grup, tag,
sistem) di database lokal, dengan filter jenis, pencarian pesan, rentang
tanggal, pagination, ekspor CSV, dan tombol bersihkan. Cookie dan password
tidak pernah ikut dicatat. Menu baris profil punya Log Chrome dan Log Proxy
(2000 baris terakhir, maksimal 1 MB) dengan tombol salin dan unduh.

Kolom Nama, Grup, dan Terakhir Dibuka bisa diurutkan naik/turun lewat server,
sehingga urutan tetap konsisten saat berpindah halaman. Profil yang belum
pernah dibuka selalu berada di akhir urutan Terakhir Dibuka.

Versi Kernel di tab Preferensi memilih binary dari
`~/.local/share/antidetect/kernels/<nama>/chrome`. Bila hanya satu kernel,
yang tampil versi engine dan hint; path di luar folder kernels atau tidak ada
ditolak backend, dan profil kembali ke engine bawaan bila kernel tersimpan
hilang.

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
ekspor/impor profil (termasuk terenkripsi), bookmark, password tersimpan,
preset platform, dasbor,
halaman API, log operasi, pilih kernel per profil, CRUD proxy, multi-select
"Matikan spoofing" pada tab Fingerprint, dan impor profil CSV. Shell
desktop (Tauri/Electron) menyusul.

## Lisensi

AGPL-3.0-only, lihat `LICENSE`. Engine fingerprint-chromium diunduh terpisah
dari repo ini dan merupakan proyek pihak ketiga berlisensi BSD-3-clause; repositori
ini tidak membundel engine. Gost (`go-gost/gost`, MIT) juga pihak ketiga dan
diunduh terpisah oleh `scripts/fetch-gost.sh`, tidak dibundel.
