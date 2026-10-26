"""Utilitas kriptografi untuk sinkronisasi metadata dan kredensial proxy."""
import base64
import hashlib
import hmac
import json
import secrets

PBKDF2_ITERATIONS = 100000
KEY_LEN = 32
NONCE_LEN = 16
TAG_LEN = 32
CIPHER_PREFIX = "v1:enc:"


class SyncCryptoError(Exception):
    pass


def _to_bytes(value, is_hex=False):
    if isinstance(value, bytes):
        return value
    text = str(value or "")
    if is_hex:
        try:
            return bytes.fromhex(text)
        except ValueError:
            pass
    return text.encode("utf-8")


def generate_salt():
    return secrets.token_hex(16)


def derive_kek(passphrase, salt):
    if not passphrase:
        raise SyncCryptoError("Frasa sandi tidak boleh kosong")
    salt_bytes = _to_bytes(salt, is_hex=True)
    if not salt_bytes:
        raise SyncCryptoError("Salt tidak boleh kosong")
    return hashlib.pbkdf2_hmac(
        "sha256",
        str(passphrase).encode("utf-8"),
        salt_bytes,
        PBKDF2_ITERATIONS,
        KEY_LEN,
    )


def derive_subkey(kek, purpose):
    kek_bytes = _to_bytes(kek, is_hex=len(kek) == 64 if isinstance(kek, str) else False)
    return hmac.new(kek_bytes, str(purpose).encode("utf-8"), hashlib.sha256).digest()


def derive_dedupe_key(kek):
    return derive_subkey(kek, "antidetect-proxy-dedupe-v1")


def compute_key_check(kek):
    kek_bytes = _to_bytes(kek, is_hex=len(kek) == 64 if isinstance(kek, str) else False)
    return hmac.new(
        kek_bytes, b"antidetect-key-check-v1", hashlib.sha256
    ).hexdigest()


def verify_passphrase(passphrase, salt, expected_check_value):
    if not passphrase or not salt:
        return False
    kek = derive_kek(passphrase, salt)
    if not expected_check_value:
        return True
    actual = compute_key_check(kek)
    return hmac.compare_digest(actual, str(expected_check_value))


def _keystream(enc_key, nonce, length):
    out = bytearray()
    counter = 0
    while len(out) < length:
        block_input = nonce + counter.to_bytes(4, "big")
        out.extend(hmac.new(enc_key, block_input, hashlib.sha256).digest())
        counter += 1
    return bytes(out[:length])


def encrypt_secret(plaintext, kek):
    if plaintext is None:
        return None
    raw = str(plaintext).encode("utf-8")
    enc_key = derive_subkey(kek, "antidetect-enc-v1")
    mac_key = derive_subkey(kek, "antidetect-mac-v1")
    nonce = secrets.token_bytes(NONCE_LEN)
    stream = _keystream(enc_key, nonce, len(raw))
    ciphertext = bytes(a ^ b for a, b in zip(raw, stream))
    tag = hmac.new(
        mac_key, CIPHER_PREFIX.encode("ascii") + nonce + ciphertext, hashlib.sha256
    ).digest()
    packed = base64.b64encode(nonce + tag + ciphertext).decode("ascii")
    return f"{CIPHER_PREFIX}{packed}"


def decrypt_secret(ciphertext_token, kek):
    if ciphertext_token in (None, ""):
        return ciphertext_token
    text = str(ciphertext_token)
    if not text.startswith(CIPHER_PREFIX):
        raise SyncCryptoError("Format ciphertext tidak didukung")
    b64_part = text[len(CIPHER_PREFIX):]
    try:
        blob = base64.b64decode(b64_part, validate=True)
    except (ValueError, TypeError) as error:
        raise SyncCryptoError("Data base64 ciphertext rusak") from error
    if len(blob) < NONCE_LEN + TAG_LEN:
        raise SyncCryptoError("Ukuran ciphertext terlalu pendek")
    nonce = blob[:NONCE_LEN]
    tag = blob[NONCE_LEN:NONCE_LEN + TAG_LEN]
    ciphertext = blob[NONCE_LEN + TAG_LEN:]
    enc_key = derive_subkey(kek, "antidetect-enc-v1")
    mac_key = derive_subkey(kek, "antidetect-mac-v1")
    expected_tag = hmac.new(
        mac_key, CIPHER_PREFIX.encode("ascii") + nonce + ciphertext, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(tag, expected_tag):
        raise SyncCryptoError("Verifikasi integritas gagal atau kunci salah")
    stream = _keystream(enc_key, nonce, len(ciphertext))
    plain = bytes(a ^ b for a, b in zip(ciphertext, stream))
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SyncCryptoError("Hasil dekripsi bukan teks UTF-8 valid") from error


def is_encrypted_secret(value):
    return isinstance(value, str) and value.startswith(CIPHER_PREFIX)


def proxy_fingerprint(proxy_config, dedupe_key):
    if not isinstance(proxy_config, dict):
        return None
    proxy_type = str(proxy_config.get("proxy_type") or "").strip().lower()
    proxy_ip = str(proxy_config.get("proxy_ip") or "").strip().lower()
    if not proxy_ip and proxy_type in ("", "direct", "none"):
        return None
    proxy_port = (
        ""
        if proxy_config.get("proxy_port") is None
        else str(proxy_config.get("proxy_port")).strip()
    )
    proxy_user = str(proxy_config.get("proxy_user") or "")
    proxy_password = str(proxy_config.get("proxy_password") or "")
    canonical = json.dumps(
        [proxy_type, proxy_ip, proxy_port, proxy_user, proxy_password],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    key_bytes = _to_bytes(
        dedupe_key,
        is_hex=len(dedupe_key) == 64 if isinstance(dedupe_key, str) else False,
    )
    return hmac.new(key_bytes, canonical, hashlib.sha256).hexdigest()


def encrypt_proxy_config(proxy_config, kek):
    if not isinstance(proxy_config, dict):
        return {}
    result = dict(proxy_config)
    if not kek:
        return result
    if "proxy_password" in result:
        password = result.pop("proxy_password")
        if password not in (None, ""):
            result["proxy_password_enc"] = encrypt_secret(str(password), kek)
        else:
            result["proxy_password_enc"] = None
    return result


def decrypt_proxy_config(proxy_config, kek):
    if not isinstance(proxy_config, dict):
        return {}
    result = dict(proxy_config)
    if "proxy_password_enc" in result:
        enc_val = result.pop("proxy_password_enc")
        if enc_val and kek:
            result["proxy_password"] = decrypt_secret(enc_val, kek)
        elif "proxy_password" not in result:
            result["proxy_password"] = "" if enc_val is None else None
    return result
