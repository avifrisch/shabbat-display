"""Apple push notifications for announcements, with the standard library only.

Apple's push service wants two things Python doesn't ship: an ES256 signature (ECDSA on the
P-256 curve) for the sign-in token, and HTTP/2. Both are small enough to write out here, which
keeps the display's rule that there is nothing to pip install.

    devices = Devices("push-devices.json")
    sender = ApplePush(lambda: {"key_file": ..., "key_id": ..., "team_id": ..., "topic": ...}, devices)
    sender.announce("Dinner is ready", origin="Kitchen")    # -> number of devices reached, or False

The key file (a .p8 from the developer account) is a secret: it is read, never logged.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import struct
import threading
import time

# ---------------------------------------------------------------- ES256

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0]:
        if (p[1] + q[1]) % P == 0:
            return None
        m = (3 * p[0] * p[0] + A) * pow(2 * p[1], -1, P) % P
    else:
        m = (q[1] - p[1]) * pow(q[0] - p[0], -1, P) % P
    x = (m * m - p[0] - q[0]) % P
    return x, (m * (p[0] - x) - p[1]) % P


def _mul(k, point):
    out = None
    while k:
        if k & 1:
            out = _add(out, point)
        point = _add(point, point)
        k >>= 1
    return out


def _nonce(d, digest):
    """The per-signature number, made from the key and the message (RFC 6979), so a weak random
    source can never leak the key."""
    x, h = d.to_bytes(32, "big"), (int.from_bytes(digest, "big") % N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        n = int.from_bytes(v, "big")
        if 1 <= n < N:
            return n
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign(d, message):
    """ECDSA P-256 / SHA-256 signature of `message` with private number `d`, as r||s (64 bytes)."""
    digest = hashlib.sha256(message).digest()
    z = int.from_bytes(digest, "big")
    k = _nonce(d, digest)
    r = _mul(k, G)[0] % N
    s = pow(k, -1, N) * (z + r * d) % N
    if not r or not s:
        raise ValueError("signature failed")
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def verify(public, message, signature):
    """Whether `signature` (r||s) is `public`'s for `message`. Used by the tests."""
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    if not (1 <= r < N and 1 <= s < N):
        return False
    z = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, N)
    point = _add(_mul(z * w % N, G), _mul(r * w % N, public))
    return point is not None and point[0] % N == r


def public_of(d):
    return _mul(d, G)


def private_number(pem):
    """The private number in a .p8 key file (PKCS#8, P-256)."""
    body = "".join(line for line in pem.splitlines() if line and not line.startswith("-----"))
    try:
        der = base64.b64decode(body, validate=True)
    except ValueError:
        raise ValueError("the key file isn't a .p8 key") from None
    at = der.find(b"\x02\x01\x01\x04\x20")      # ECPrivateKey: version 1, then the 32-byte number
    if at < 0 or len(der) < at + 37:
        raise ValueError("the key file isn't a P-256 .p8 key")
    d = int.from_bytes(der[at + 5:at + 37], "big")
    if not 1 <= d < N:
        raise ValueError("the key file isn't a P-256 .p8 key")
    return d


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def provider_token(d, key_id, team_id, at):
    """Apple's sign-in token: a JWT signed with the push key."""
    head = _b64(json.dumps({"alg": "ES256", "kid": key_id}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"iss": team_id, "iat": int(at)}, separators=(",", ":")).encode())
    return (head + b"." + claims + b"." + _b64(sign(d, head + b"." + claims))).decode()


# ---------------------------------------------------------------- HTTP/2, just enough to POST

PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"
DATA, HEADERS, RST, SETTINGS, PING, GOAWAY, CONTINUATION = 0, 1, 3, 4, 6, 7, 9
STATIC_STATUS = {8: 200, 9: 204, 10: 206, 11: 304, 12: 400, 13: 404, 14: 500}


def _hint(value, bits, first=0):
    """An HPACK integer with a `bits`-bit prefix."""
    limit = (1 << bits) - 1
    if value < limit:
        return bytes([first | value])
    out, value = [first | limit], value - limit
    while value >= 128:
        out.append(value % 128 + 128)
        value //= 128
    out.append(value)
    return bytes(out)


def header_block(headers):
    """Headers as HPACK literals: no table, no Huffman coding."""
    out = b""
    for name, value in headers:
        name, value = name.encode("ascii"), value.encode("ascii")
        out += b"\x00" + _hint(len(name), 7) + name + _hint(len(value), 7) + value
    return out


def frame(kind, flags, stream, payload=b""):
    return struct.pack(">I", len(payload))[1:] + bytes([kind, flags]) + struct.pack(">I", stream) + payload


def status_of(block):
    """The status in a response's header block when it is one of the common ones, else None
    (Apple's other statuses come with a JSON reason in the body, which is what we report)."""
    i = 0
    while i < len(block) and block[i] & 0xE0 == 0x20:      # table size updates
        i += 1
    if i < len(block) and block[i] & 0x80:
        return STATIC_STATUS.get(block[i] & 0x7F)
    return None


class Connection:
    """One HTTP/2 connection used for a few POSTs, one after another."""

    def __init__(self, host, port=443, timeout=8, context=None):
        self.host = host
        context = context or ssl.create_default_context()
        context.set_alpn_protocols(["h2"])
        raw = socket.create_connection((host, port), timeout=timeout)
        try:
            self.sock = context.wrap_socket(raw, server_hostname=host)
        except Exception:
            raw.close()
            raise
        if self.sock.selected_alpn_protocol() != "h2":
            self.sock.close()
            raise OSError("the push service didn't offer HTTP/2")
        self.sock.sendall(PREFACE + frame(SETTINGS, 0, 0))
        self.next = 1

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _read(self, n):
        out = b""
        while len(out) < n:
            part = self.sock.recv(n - len(out))
            if not part:
                raise OSError("the push service closed the connection")
            out += part
        return out

    def post(self, path, headers, body):
        """POST and return (status or None, body bytes)."""
        stream, self.next = self.next, self.next + 2
        block = header_block([(":method", "POST"), (":scheme", "https"), (":path", path), (":authority", self.host)]
                             + headers + [("content-length", str(len(body)))])
        self.sock.sendall(frame(HEADERS, 0x4, stream, block) + frame(DATA, 0x1, stream, body))
        status, got, answer = None, b"", b""
        while True:
            head = self._read(9)
            size, kind, flags = int.from_bytes(head[:3], "big"), head[3], head[4]
            sid = int.from_bytes(head[5:], "big") & 0x7FFFFFFF
            payload = self._read(size) if size else b""
            if kind == SETTINGS and not flags & 0x1:
                self.sock.sendall(frame(SETTINGS, 0x1, 0))
            elif kind == PING and not flags & 0x1:
                self.sock.sendall(frame(PING, 0x1, 0, payload))
            elif kind == GOAWAY:
                raise OSError("the push service ended the connection")
            elif sid != stream:
                continue
            elif kind == RST:
                raise OSError("the push service refused the request")
            elif kind in (HEADERS, CONTINUATION):
                if kind == HEADERS:
                    pad = payload[0] if flags & 0x8 else 0
                    start = (1 if flags & 0x8 else 0) + (5 if flags & 0x20 else 0)
                    payload = payload[start:len(payload) - pad]
                got += payload
                if flags & 0x4 and status is None:
                    status = status_of(got)
                if kind == HEADERS and flags & 0x1:
                    return status, answer
            elif kind == DATA:
                pad = payload[0] if flags & 0x8 else 0
                answer += payload[1:len(payload) - pad] if flags & 0x8 else payload
                if flags & 0x1:
                    return status, answer


# ---------------------------------------------------------------- the family's devices

HOSTS = {"development": "api.sandbox.push.apple.com", "production": "api.push.apple.com"}
GONE = {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"}


class Devices:
    """The phones and tablets that asked for announcements: {token: {screen, env, at}}."""
    LIMIT = 40

    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return {t: d for t, d in data.items() if isinstance(d, dict)} if isinstance(data, dict) else {}

    def _save(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    def all(self):
        with self.lock:
            return self._load()

    def register(self, token, screen, env):
        """Remember a device. (An app that was removed is forgotten when Apple says so.)"""
        if not (isinstance(token, str) and re.fullmatch(r"[0-9a-fA-F]{64,200}", token)) or env not in HOSTS:
            return False
        screen = screen if isinstance(screen, str) else ""
        with self.lock:
            data = self._load()
            data[token.lower()] = {"screen": screen[:40], "env": env, "at": int(time.time())}
            if len(data) > self.LIMIT:
                for old in sorted(data, key=lambda t: data[t].get("at", 0))[:len(data) - self.LIMIT]:
                    del data[old]
            self._save(data)
        return True

    def forget(self, tokens):
        if not tokens:
            return
        with self.lock:
            data = self._load()
            self._save({t: d for t, d in data.items() if t not in tokens})


class ApplePush:
    def __init__(self, settings, devices, log=print, connect=Connection, now=time.time):
        self.settings, self.devices, self.log, self.connect, self.now = settings, devices, log, connect, now
        self.lock, self._token, self._token_for = threading.Lock(), None, None

    def ready(self):
        s = self.settings()
        return all(isinstance(s.get(k), str) and s[k].strip() for k in ("key_file", "key_id", "team_id", "topic"))

    def _bearer(self, s):
        """The sign-in token, made again every 40 minutes (Apple accepts one for an hour and
        refuses new ones made more often than every 20 minutes)."""
        mark = (s["key_file"], s["key_id"], s["team_id"])
        if self._token and self._token_for == mark and self.now() - self._made < 2400:
            return self._token
        with open(s["key_file"], encoding="ascii") as f:
            d = private_number(f.read())
        self._made = self.now()
        self._token, self._token_for = provider_token(d, s["key_id"].strip(), s["team_id"].strip(), self._made), mark
        return self._token

    def announce(self, text, origin="", skip=""):
        """Send an announcement to every device but the one it was said on (`skip`, its token). Returns how many
        devices Apple accepted it for, or False when push isn't set up or nobody is registered."""
        if not self.ready():
            return False
        targets = {t: d for t, d in self.devices.all().items() if t != skip}
        if not targets:
            return False
        s = self.settings()
        body = json.dumps({"aps": {"alert": {"title": "Announcement", "body": text}, "sound": "default",
                                   "mutable-content": 1, "interruption-level": "time-sensitive"},
                           "announcement": text, "from": origin}).encode("utf-8")
        reached, gone = 0, set()
        with self.lock:
            bearer = self._bearer(s)
            headers = [("authorization", "bearer " + bearer), ("apns-topic", s["topic"].strip()),
                       ("apns-push-type", "alert"), ("apns-priority", "10"),
                       # An announcement that can't be delivered within two minutes is dropped, not said late.
                       ("apns-expiration", str(int(self.now()) + 120)), ("content-type", "application/json")]
            for env, host in HOSTS.items():
                tokens = [t for t, d in targets.items() if d.get("env") == env]
                if not tokens:
                    continue
                try:
                    link = self.connect(host)
                except (OSError, ssl.SSLError) as e:
                    self.log(f"push: couldn't reach Apple ({e})")
                    continue
                try:
                    for token in tokens:
                        status, answer = link.post("/3/device/" + token, headers, body)
                        reason = _reason(answer)
                        if status == 200 and not reason:
                            reached += 1
                        else:
                            name = targets[token].get("screen") or "a device"
                            self.log(f"push: Apple refused the announcement for {name}: {reason or status or 'no reason given'}")
                            if reason in GONE:
                                gone.add(token)
                            if reason in ("InvalidProviderToken", "ExpiredProviderToken"):
                                self._token = None
                except (OSError, ssl.SSLError) as e:
                    self.log(f"push: the connection to Apple failed ({e})")
                finally:
                    link.close()
        self.devices.forget(gone)
        return reached


def _reason(answer):
    try:
        data = json.loads(answer.decode("utf-8")) if answer else {}
    except (ValueError, UnicodeDecodeError):
        return ""
    return data.get("reason", "") if isinstance(data, dict) and isinstance(data.get("reason"), str) else ""
