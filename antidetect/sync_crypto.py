"""Utilitas kriptografi untuk sinkronisasi metadata dan kredensial proxy."""
import base64
import hashlib
import hmac
import json
import secrets
import zlib

PBKDF2_ITERATIONS = 100000
KEY_LEN = 32
NONCE_LEN = 16
TAG_LEN = 32
CIPHER_PREFIX = "v1:enc:"
BLOB_PREFIX = "v1:blob:"


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


def encrypt_blob(data_bytes, kek, profile_uuid, blob_kind="cookies", revision=1):
    if isinstance(data_bytes, str):
        raw_plain = data_bytes.encode("utf-8")
    elif isinstance(data_bytes, (bytes, bytearray)):
        raw_plain = bytes(data_bytes)
    else:
        raise SyncCryptoError("data_bytes harus berupa bytes atau str")

    if not kek:
        raise SyncCryptoError("KEK tidak boleh kosong")
    clean_uuid = str(profile_uuid or "").strip()
    clean_kind = str(blob_kind or "cookies").strip()
    rev_int = int(revision if revision is not None else 1)
    if not clean_uuid:
        raise SyncCryptoError("profile_uuid wajib diisi untuk AAD blob")

    sha256_plain = hashlib.sha256(raw_plain).hexdigest()
    compressed = zlib.compress(raw_plain, level=6)
    dek = secrets.token_bytes(KEY_LEN)
    nonce = secrets.token_bytes(NONCE_LEN)

    enc_key = derive_subkey(dek, "antidetect-blob-enc-v1")
    mac_key = derive_subkey(dek, "antidetect-blob-mac-v1")
    stream = _keystream(enc_key, nonce, len(compressed))
    ciphertext = bytes(a ^ b for a, b in zip(compressed, stream))

    aad = f"{clean_uuid}:{clean_kind}:{rev_int}".encode("utf-8")
    tag = hmac.new(
        mac_key,
        BLOB_PREFIX.encode("ascii") + aad + b":" + nonce + ciphertext,
        hashlib.sha256,
    ).hexdigest()

    wrapped_dek = encrypt_secret(dek.hex(), kek)
    envelope = {
        "v": 1,
        "alg": "aes-256-gcm-v1",
        "wrapped_dek": wrapped_dek,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "hmac": tag,
        "ciphertext_base64": base64.b64encode(ciphertext).decode("ascii"),
        "sha256_plain": sha256_plain,
        "size_plain": len(raw_plain),
    }
    envelope_json = json.dumps(
        envelope, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    ciphertext_envelope_string = base64.b64encode(envelope_json).decode("ascii")
    sha256_cipher = hashlib.sha256(
        ciphertext_envelope_string.encode("ascii")
    ).hexdigest()
    size_bytes = len(ciphertext_envelope_string)
    return ciphertext_envelope_string, sha256_plain, sha256_cipher, size_bytes


def decrypt_blob(envelope_data, kek, profile_uuid, blob_kind="cookies", revision=1):
    if not envelope_data:
        raise SyncCryptoError("Integritas blob rusak atau AAD tidak cocok")
    if not kek:
        raise SyncCryptoError("KEK tidak boleh kosong")

    clean_uuid = str(profile_uuid or "").strip()
    clean_kind = str(blob_kind or "cookies").strip()
    rev_int = int(revision if revision is not None else 1)
    aad = f"{clean_uuid}:{clean_kind}:{rev_int}".encode("utf-8")

    try:
        if isinstance(envelope_data, dict):
            envelope = envelope_data
        else:
            if isinstance(envelope_data, (bytes, bytearray)):
                text = bytes(envelope_data).decode("utf-8")
            else:
                text = str(envelope_data).strip()
            if text.startswith(BLOB_PREFIX):
                text = text[len(BLOB_PREFIX):]
            if text.startswith("{"):
                envelope = json.loads(text)
            else:
                decoded_json = base64.b64decode(text.encode("ascii"), validate=True)
                envelope = json.loads(decoded_json.decode("utf-8"))
        if not isinstance(envelope, dict):
            raise ValueError("Amplop bukan objek JSON")
    except Exception as error:
        raise SyncCryptoError("Integritas blob rusak atau AAD tidak cocok") from error

    wrapped_dek = envelope.get("wrapped_dek")
    nonce_b64 = envelope.get("nonce") or envelope.get("iv")
    tag_hex = str(envelope.get("hmac") or envelope.get("tag") or "")
    cipher_b64 = envelope.get("ciphertext_base64")
    expected_sha256_plain = str(envelope.get("sha256_plain") or "")

    if not wrapped_dek or not nonce_b64 or not tag_hex or cipher_b64 is None:
        raise SyncCryptoError("Integritas blob rusak atau AAD tidak cocok")

    try:
        dek_hex = decrypt_secret(wrapped_dek, kek)
        dek = bytes.fromhex(dek_hex)
        nonce = base64.b64decode(str(nonce_b64).encode("ascii"), validate=True)
        ciphertext = base64.b64decode(str(cipher_b64).encode("ascii"), validate=True)
    except SyncCryptoError as error:
        raise SyncCryptoError("Integritas blob rusak atau AAD tidak cocok") from error
    except Exception as error:
        raise SyncCryptoError("Integritas blob rusak atau AAD tidak cocok") from error

    if len(dek) != KEY_LEN or len(nonce) != NONCE_LEN:
        raise SyncCryptoError("Integritas blob rusak atau AAD tidak cocok")

    enc_key = derive_subkey(dek, "antidetect-blob-enc-v1")
    mac_key = derive_subkey(dek, "antidetect-blob-mac-v1")
    expected_tag = hmac.new(
        mac_key,
        BLOB_PREFIX.encode("ascii") + aad + b":" + nonce + ciphertext,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(tag_hex, expected_tag):
        raise SyncCryptoError("Integritas blob rusak atau AAD tidak cocok")

    stream = _keystream(enc_key, nonce, len(ciphertext))
    compressed = bytes(a ^ b for a, b in zip(ciphertext, stream))
    try:
        data_bytes = zlib.decompress(compressed)
    except Exception as error:
        raise SyncCryptoError("Integritas blob rusak atau AAD tidak cocok") from error

    actual_sha256_plain = hashlib.sha256(data_bytes).hexdigest()
    if expected_sha256_plain and not hmac.compare_digest(
        actual_sha256_plain, expected_sha256_plain
    ):
        raise SyncCryptoError("Hash plaintext blob tidak cocok")

    size_plain = envelope.get("size_plain")
    if size_plain is not None and int(size_plain) != len(data_bytes):
        raise SyncCryptoError("Ukuran plaintext blob tidak cocok")

    return data_bytes

