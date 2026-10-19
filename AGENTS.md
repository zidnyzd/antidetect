# Aturan proyek antidetect

## Bahasa & gaya
- Bahasa Indonesia. Tanpa em dash, gunakan koma, titik, titik dua.
- Komentar kode minimal: jelaskan alasan bila tidak jelas, jangan mengulang kode.
- Anti slop: tanpa klise marketing, tanpa kalimat pengisi.

## Lingkup kerja
- Repo: /home/zdna/Projects/antidetect. Tulis hanya di dalam repo ini, kecuali catatan hasil yang ditulis ke /home/zdna/.hermes/cache/scratch/antidetect/ (di luar repo) dan alat pihak ketiga (mis. gost) ke ~/.local/bin.
- Jangan mengubah engine di ~/.local/share/antidetect/squashfs-root maupun venv/site-packages.
- Database pengguna di ~/.local/share/antidetect/antidetect.db: boleh tambah profil uji, jangan hapus profil milik pengguna tanpa alasan.

## Lingkungan
- Engine: ~/.local/share/antidetect/squashfs-root/opt/ungoogled-chromium/chrome (fingerprint-chromium 150, chromedriver di folder sama).
- Venv: ./venv (sudah berisi ixbrowser-local-api dan selenium).
- DISPLAY=:0 (desktop nyata). Boleh membuka Chrome headed, selalu tutup kembali setelah tes.
- Server dev berjalan di 127.0.0.1:53200. Setelah mengubah antidetect/*.py, restart server:
  `PID=$(ss -ltnp | grep ':53200' | grep -oP 'pid=[0-9]+' | head -1 | cut -d= -f2); [ -n "$PID" ] && kill "$PID"; sleep 1; cd /home/zdna/Projects/antidetect && (setsid nohup ./venv/bin/python -m antidetect serve >/home/zdna/.hermes/cache/scratch/antidetect-serve.log 2>&1 &); sleep 2; curl -s http://127.0.0.1:53200/health`

## Kontrak API
- SDK resmi ixBrowser (ixbrowser-local-api) adalah klien acuan. Jangan patch venv.
- Envelope respons wajib: {"error":{"code":0,"message":"..."},"data":...}; list terpaginasi {total,data}.
- Nama action tidak boleh berubah; perilaku harus cocok dengan SDK.

## Bukti
- Setiap klaim harus diverifikasi dengan menjalankan perintah nyata dan menempelkan output mentah di catatan hasil.
- Tes acuan: scripts/selftest.py dan scripts/isolation_test.py (server harus jalan).
