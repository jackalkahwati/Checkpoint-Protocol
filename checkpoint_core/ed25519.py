"""Ed25519 signing primitives. No Git.

Prefers the audited `cryptography` package when available; otherwise falls back to a
vendored pure-Python RFC 8032 implementation so Checkpoint can sign/verify with only the
standard library. Both paths are RFC 8032 compliant and interoperable (raw 32-byte keys,
64-byte signatures).
"""
from __future__ import annotations

import hashlib
import os

ALGORITHM = "ed25519"

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519 as _c
    from cryptography.hazmat.primitives import serialization as _ser
    _HAVE_CRYPTO = True
except Exception:  # pragma: no cover - exercised only where cryptography is absent
    _HAVE_CRYPTO = False


# --------------------------------------------------------------- public interface

def generate():
    """Return (seed_32_bytes, public_key_32_bytes)."""
    if _HAVE_CRYPTO:
        sk = _c.Ed25519PrivateKey.generate()
        seed = sk.private_bytes(_ser.Encoding.Raw, _ser.PrivateFormat.Raw, _ser.NoEncryption())
        pub = sk.public_key().public_bytes(_ser.Encoding.Raw, _ser.PublicFormat.Raw)
        return seed, pub
    seed = os.urandom(32)
    return seed, _pub_from_seed(seed)


def public_from_seed(seed: bytes) -> bytes:
    if _HAVE_CRYPTO:
        sk = _c.Ed25519PrivateKey.from_private_bytes(seed)
        return sk.public_key().public_bytes(_ser.Encoding.Raw, _ser.PublicFormat.Raw)
    return _pub_from_seed(seed)


def sign(seed: bytes, message: bytes) -> bytes:
    if _HAVE_CRYPTO:
        return _c.Ed25519PrivateKey.from_private_bytes(seed).sign(message)
    return _sign(seed, message)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    if _HAVE_CRYPTO:
        try:
            _c.Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
            return True
        except Exception:
            return False
    return _verify(public_key, message, signature)


def fingerprint(public_key: bytes) -> str:
    return "SHA256:" + hashlib.sha256(public_key).hexdigest()


def short_fingerprint(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()[:16]


# --------------------------------------------------- vendored pure-Python RFC 8032

_b = 256
_q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493


def _H(m: bytes) -> bytes:
    return hashlib.sha512(m).digest()


def _inv(x):
    return pow(x, _q - 2, _q)


_d = (-121665 * _inv(121666)) % _q
_I = pow(2, (_q - 1) // 4, _q)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


_By = (4 * _inv(5)) % _q
_Bx = _xrecover(_By)
_B = [_Bx % _q, _By % _q]


def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _d * x1 * x2 * y1 * y2)
    return [x3 % _q, y3 % _q]


def _scalarmult(P, e):
    if e == 0:
        return [0, 1]
    Q = _scalarmult(P, e // 2)
    Q = _edwards(Q, Q)
    if e & 1:
        Q = _edwards(Q, P)
    return Q


def _bit(h, i):
    return (h[i // 8] >> (i % 8)) & 1


def _encodeint(y):
    return bytes([(y >> (8 * i)) & 0xFF for i in range(_b // 8)])


def _encodepoint(P):
    x, y = P
    bits = [(y >> i) & 1 for i in range(_b - 1)] + [x & 1]
    return bytes([sum(bits[i * 8 + j] << j for j in range(8)) for i in range(_b // 8)])


def _Hint(m):
    h = _H(m)
    return sum(2 ** i * _bit(h, i) for i in range(2 * _b))


def _secret_scalar(sk):
    h = _H(sk)
    return 2 ** (_b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, _b - 2)), h


def _pub_from_seed(sk):
    a, _h = _secret_scalar(sk)
    return _encodepoint(_scalarmult(_B, a))


def _sign(sk, m):
    a, h = _secret_scalar(sk)
    pk = _encodepoint(_scalarmult(_B, a))
    r = _Hint(h[_b // 8:_b // 4] + m)
    R = _scalarmult(_B, r)
    S = (r + _Hint(_encodepoint(R) + pk + m) * a) % _L
    return _encodepoint(R) + _encodeint(S)


def _decodeint(s):
    return sum(2 ** i * _bit(s, i) for i in range(0, _b))


def _isoncurve(P):
    x, y = P
    return (-x * x + y * y - 1 - _d * x * x * y * y) % _q == 0


def _decodepoint(s):
    y = sum(2 ** i * _bit(s, i) for i in range(0, _b - 1))
    x = _xrecover(y)
    if x & 1 != _bit(s, _b - 1):
        x = _q - x
    P = [x, y]
    if not _isoncurve(P):
        raise ValueError("decoding point that is not on curve")
    return P


def _verify(pk, m, s):
    if len(s) != _b // 4 or len(pk) != _b // 8:
        return False
    try:
        R = _decodepoint(s[0:_b // 8])
        A = _decodepoint(pk)
        S = _decodeint(s[_b // 8:_b // 4])
    except Exception:
        return False
    h = _Hint(_encodepoint(R) + pk + m)
    return _scalarmult(_B, S) == _edwards(R, _scalarmult(A, h))
