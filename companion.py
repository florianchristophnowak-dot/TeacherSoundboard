"""Companion-Modus: die lokale Verbindung zu Boîte à Oublis.

Warum ein WebSocket-Server im Soundboard?
    Boîte à Oublis läuft als reine Browser-Anwendung, oft direkt über
    ``file://``. Ein Browserfenster kann keinen Port öffnen, aber es darf sich
    zu ``ws://127.0.0.1`` verbinden. Also hält das Soundboard - die ohnehin
    ständig laufende Unterrichtssteuerung - den Server, und die Tafel-App
    verbindet sich als Client.

Grundsätze:
    * ausschließlich Loopback (127.0.0.1), niemals eine andere Schnittstelle,
    * ein kleines, versioniertes Nachrichtenformat aus reinem JSON,
    * eine feste Liste erlaubter Befehle; alles andere wird verworfen,
    * genau eine aktive Verbindung; eine zweite übernimmt nachvollziehbar,
    * keine Wortschatzdaten, nur Steuerbefehle und Zustandsmeldungen.

Dieses Modul kommt ohne PyQt aus. Dadurch lässt es sich vollständig ohne
Benutzeroberfläche prüfen; die Qt-Anbindung steht in ``soundboard.py``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import struct
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Protokoll
# ---------------------------------------------------------------------------

PROTOCOL = "bao-companion"
PROTOCOL_VERSION = 1

# Feste Portliste, in beiden Programmen identisch. Bewusst unterhalb der
# Bereiche, aus denen Windows und macOS flüchtige Ports vergeben, damit der
# erste Port im Normalfall frei ist.
PORTS: tuple[int, ...] = (8317, 8318, 8319)

HOST = "127.0.0.1"

MAX_MESSAGE_BYTES = 64 * 1024
HANDSHAKE_TIMEOUT = 5.0
HELLO_TIMEOUT = 8.0
IDLE_TIMEOUT = 60.0
PING_INTERVAL = 20.0
PAIRING_TIMEOUT = 90.0
INVITE_LIFETIME = 600.0
MAX_TOKENS = 6

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA

CLIENT_APP = "boite-a-oublis"
SERVER_APP = "teacher-soundboard"


class ProtocolError(Exception):
    """Eine Nachricht verletzt das WebSocket-Format."""


# ---------------------------------------------------------------------------
# WebSocket-Handschlag
# ---------------------------------------------------------------------------

def accept_key(key: str) -> str:
    """Antwortschlüssel nach RFC 6455."""
    digest = hashlib.sha1((key.strip() + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def parse_request(data: bytes) -> dict[str, str] | None:
    """Zerlegt einen HTTP-Anfragekopf. None, solange er unvollständig ist."""
    if b"\r\n\r\n" not in data:
        return None
    head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1")
    lines = head.split("\r\n")
    if not lines:
        return None
    headers: dict[str, str] = {"__request__": lines[0]}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return headers


def origin_allowed(origin: str) -> bool:
    """Nur der eigene Rechner darf sich verbinden.

    Chrome meldet für eine Datei ``null``, Firefox ``file://``. Beides gehört
    zu einer lokal geöffneten Datei. Zusätzlich sind die Adressen eines selbst
    gestarteten lokalen Webservers erlaubt.
    """
    origin = (origin or "").strip()
    if origin in ("", "null", "file://"):
        return True
    return bool(re.match(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?$", origin))


def handshake_response(headers: dict[str, str]) -> bytes | None:
    """Antwort auf einen gültigen Upgrade-Wunsch, sonst None."""
    if not headers:
        return None
    request = headers.get("__request__", "")
    if not request.upper().startswith("GET "):
        return None
    if headers.get("upgrade", "").lower() != "websocket":
        return None
    if "upgrade" not in headers.get("connection", "").lower():
        return None
    if headers.get("sec-websocket-version", "") != "13":
        return None
    key = headers.get("sec-websocket-key", "")
    if not key:
        return None
    if not origin_allowed(headers.get("origin", "")):
        return None
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key(key)}\r\n"
        "\r\n"
    ).encode("ascii")


def encode_frame(payload: str | bytes, opcode: int = OPCODE_TEXT) -> bytes:
    """Ein einzelner, unmaskierter Serverrahmen."""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    header = bytearray()
    header.append(0x80 | (opcode & 0x0F))
    length = len(data)
    if length < 126:
        header.append(length)
    elif length < (1 << 16):
        header.append(126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(127)
        header.extend(struct.pack(">Q", length))
    return bytes(header) + data


class FrameReader:
    """Setzt eingehende Rahmen zu vollständigen Nachrichten zusammen."""

    def __init__(self, max_bytes: int = MAX_MESSAGE_BYTES, require_mask: bool = True):
        self.max_bytes = max_bytes
        # Ein Browser maskiert immer, ein Server nie. Die Richtung entscheidet.
        self.require_mask = require_mask
        self._buffer = bytearray()
        self._fragments = bytearray()
        self._fragment_opcode = 0

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        """Nimmt Netzwerkdaten auf und gibt fertige (opcode, payload) zurück."""
        self._buffer.extend(chunk)
        if len(self._buffer) > self.max_bytes * 2:
            raise ProtocolError("Die Gegenstelle sendet zu große Datenmengen.")

        messages: list[tuple[int, bytes]] = []
        while True:
            frame = self._take_frame()
            if frame is None:
                return messages
            fin, opcode, payload = frame

            if opcode in (OPCODE_CLOSE, OPCODE_PING, OPCODE_PONG):
                if not fin:
                    raise ProtocolError("Steuerrahmen dürfen nicht zerteilt werden.")
                messages.append((opcode, payload))
                continue

            if opcode == OPCODE_CONTINUATION:
                if not self._fragment_opcode:
                    raise ProtocolError("Fortsetzung ohne begonnene Nachricht.")
            else:
                if self._fragment_opcode:
                    raise ProtocolError("Neue Nachricht vor dem Ende der vorigen.")
                self._fragment_opcode = opcode

            self._fragments.extend(payload)
            if len(self._fragments) > self.max_bytes:
                raise ProtocolError("Die Nachricht ist zu groß.")
            if fin:
                messages.append((self._fragment_opcode, bytes(self._fragments)))
                self._fragments = bytearray()
                self._fragment_opcode = 0

    def _take_frame(self) -> tuple[bool, int, bytes] | None:
        buffer = self._buffer
        if len(buffer) < 2:
            return None
        first, second = buffer[0], buffer[1]
        fin = bool(first & 0x80)
        if first & 0x70:
            raise ProtocolError("Unbekannte Rahmen-Erweiterung.")
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        offset = 2

        if length == 126:
            if len(buffer) < offset + 2:
                return None
            length = struct.unpack(">H", buffer[offset:offset + 2])[0]
            offset += 2
        elif length == 127:
            if len(buffer) < offset + 8:
                return None
            length = struct.unpack(">Q", buffer[offset:offset + 8])[0]
            offset += 8

        if length > self.max_bytes:
            raise ProtocolError("Die Nachricht ist zu groß.")
        if masked != self.require_mask:
            raise ProtocolError(
                "Unmaskierte Daten vom Client." if self.require_mask
                else "Maskierte Daten vom Server."
            )
        if len(buffer) < offset + (4 if masked else 0) + length:
            return None

        if masked:
            mask = buffer[offset:offset + 4]
            offset += 4
            payload = bytearray(buffer[offset:offset + length])
            for index in range(length):
                payload[index] ^= mask[index % 4]
        else:
            payload = bytearray(buffer[offset:offset + length])
        offset += length

        del buffer[:offset]
        return fin, opcode, bytes(payload)


def close_frame(code: int = 1000, reason: str = "") -> bytes:
    body = struct.pack(">H", code) + reason.encode("utf-8")[:120]
    return encode_frame(body, OPCODE_CLOSE)


# ---------------------------------------------------------------------------
# Nachrichtenformat
# ---------------------------------------------------------------------------

CLIENT_TYPES = ("hello", "status", "result", "bye")
SERVER_TYPES = ("welcome", "pending", "denied", "command", "ping")

# Erlaubte Befehle. Mehr gibt es nicht: kein freies JavaScript, kein
# Dateizugriff, kein Durchreichen beliebiger Aufrufe.
COMMANDS = (
    "page.next",
    "page.prev",
    "level.set",
    "blank.toggle",
    "blank.set",
    "live.add",
    "session.stop",
    "output.open",
    "library.list",
    "preset.start",
    "status.request",
)


def build(message_type: str, **fields) -> str:
    """Baut eine Nachricht des vereinbarten Formats."""
    payload = {"protocol": PROTOCOL, "v": PROTOCOL_VERSION, "type": message_type}
    payload.update({key: value for key, value in fields.items() if value is not None})
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_message(raw: str | bytes, allowed: Iterable[str] = CLIENT_TYPES) -> dict | None:
    """Prüft Typ, Version und Grundgestalt einer Nachricht.

    Alles Unbekannte, Veraltete oder Fehlerhafte ergibt None - der Aufrufer
    verwirft es dann still, statt daran zu scheitern.
    """
    if isinstance(raw, (bytes, bytearray)):
        if len(raw) > MAX_MESSAGE_BYTES:
            return None
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(raw, str) or len(raw) > MAX_MESSAGE_BYTES:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("protocol") != PROTOCOL:
        return None
    if data.get("v") != PROTOCOL_VERSION:
        return None
    message_type = data.get("type")
    if not isinstance(message_type, str) or message_type not in allowed:
        return None
    return data


def _text(value, limit: int = 300) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return ""
    return value.replace("\r", " ").replace("\n", " ").strip()[:limit]


def _list(value) -> list:
    """Nur echte Listen werden gelesen; alles andere gilt als leer."""
    return value if isinstance(value, list) else []


def _int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, parsed))


def command_args(name: str, args) -> dict | None:
    """Bringt die Parameter eines Befehls in eine geprüfte Form.

    None bedeutet: dieser Befehl existiert nicht oder die Angaben taugen
    nicht. Dann wird nichts gesendet.
    """
    if name not in COMMANDS:
        return None
    args = args if isinstance(args, dict) else {}

    if name == "level.set":
        level = args.get("level")
        try:
            level = int(level)
        except (TypeError, ValueError, OverflowError):
            return None
        return {"level": level} if level in (1, 2, 3) else None
    if name == "blank.set":
        return {"blank": bool(args.get("blank"))}
    if name == "live.add":
        text = _text(args.get("text"), 240)
        if not text:
            return None
        kind = "starter" if args.get("kind") == "starter" else "word"
        return {"text": text, "translation": _text(args.get("translation"), 240), "kind": kind}
    if name == "preset.start":
        target_id = _text(args.get("id"), 120)
        if not target_id:
            return None
        kind = "board" if args.get("kind") == "board" else "bank"
        payload = {"id": target_id, "kind": kind}
        try:
            level = int(args.get("level"))
        except (TypeError, ValueError, OverflowError):
            level = 0
        if level in (1, 2, 3):
            payload["level"] = level
        return payload
    return {}


# ---------------------------------------------------------------------------
# Zustand, den Boîte à Oublis zurückmeldet
# ---------------------------------------------------------------------------

@dataclass
class BoiteStatus:
    """Der zuletzt gemeldete Stand der Tafel-App."""

    connected: bool = False
    kind: str = "none"          # none | bank | board | live
    active: bool = False
    title: str = ""
    group: str = ""
    subject: str = ""
    level: int = 0
    page: int = 0
    pages: int = 0
    blank: bool = False
    has_output: bool = False
    window_blocked: bool = False
    app_version: str = ""

    @property
    def projecting(self) -> bool:
        return self.connected and self.active

    def tile_state(self) -> str:
        """Kurzform für die Kachel: offline | ready | blank | live."""
        if not self.connected:
            return "offline"
        if not self.active:
            return "ready"
        return "blank" if self.blank else "live"


def parse_status(raw) -> BoiteStatus:
    """Nimmt die Statusmeldung entgegen - defensiv, Feld für Feld."""
    data = raw if isinstance(raw, dict) else {}
    kind = data.get("kind")
    if kind not in ("none", "bank", "board", "live"):
        kind = "none"
    return BoiteStatus(
        connected=True,
        kind=kind,
        active=bool(data.get("active")),
        title=_text(data.get("title"), 160),
        group=_text(data.get("group"), 120),
        subject=_text(data.get("subject"), 120),
        level=_int(data.get("level"), 0, 0, 3),
        page=_int(data.get("page"), 0, 0, 9999),
        pages=_int(data.get("pages"), 0, 0, 9999),
        blank=bool(data.get("blank")),
        has_output=bool(data.get("hasOutput")),
        window_blocked=bool(data.get("windowBlocked")),
        app_version=_text(data.get("appVersion"), 40),
    )


def parse_library(raw) -> dict[str, list[dict[str, str]]]:
    """Liste der Wortbanken und Tafeln - nur Titel und Kennungen."""
    data = raw if isinstance(raw, dict) else {}
    result: dict[str, list[dict[str, str]]] = {"banks": [], "boards": []}
    for key in ("banks", "boards"):
        entries = data.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries[:400]:
            if not isinstance(entry, dict):
                continue
            entry_id = _text(entry.get("id"), 120)
            if not entry_id:
                continue
            result[key].append({
                "id": entry_id,
                "title": _text(entry.get("title"), 160) or "Ohne Titel",
                "group": _text(entry.get("group"), 120),
                "subject": _text(entry.get("subject"), 120),
                "scene": _text(entry.get("scene"), 120),
                "level": str(_int(entry.get("defaultLevel"), 2, 1, 3)),
            })
    return result


# ---------------------------------------------------------------------------
# Kopplung
# ---------------------------------------------------------------------------

@dataclass
class PairingRequest:
    """Nachfrage an die Lehrkraft, wenn ein Fenster ohne Einladung anklopft."""

    client_name: str
    client_version: str
    code: str
    _event: threading.Event = field(default_factory=threading.Event, repr=False)
    _approved: bool = False

    def approve(self) -> None:
        self._approved = True
        self._event.set()

    def reject(self) -> None:
        self._approved = False
        self._event.set()

    def wait(self, timeout: float = PAIRING_TIMEOUT) -> bool:
        self._event.wait(timeout)
        return self._approved

    @property
    def answered(self) -> bool:
        return self._event.is_set()


def new_token() -> str:
    return secrets.token_urlsafe(18)


def new_preset_id() -> str:
    return f"pre-{secrets.token_hex(6)}"


def new_invite() -> str:
    """Kurzer Einladungscode für den Aufruf über die Adresszeile."""
    return secrets.token_hex(8)


def short_code(token: str) -> str:
    """Sechsstellige Anzeigeform, damit die Lehrkraft vergleichen kann."""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return str(int(digest[:8], 16) % 1000000).zfill(6)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class _Connection:
    """Eine einzelne Browserverbindung."""

    def __init__(self, sock: socket.socket, server: "CompanionServer"):
        self.sock = sock
        self.server = server
        self.reader = FrameReader()
        self.authenticated = False
        self.client_name = ""
        self.client_version = ""
        self.closed = False
        self._send_lock = threading.Lock()

    # ---- Senden
    def send_raw(self, data: bytes) -> bool:
        if self.closed:
            return False
        with self._send_lock:
            try:
                self.sock.sendall(data)
                return True
            except OSError:
                self.close()
                return False

    def send(self, text: str) -> bool:
        return self.send_raw(encode_frame(text))

    def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.sock.sendall(close_frame(code, reason))
        except OSError:
            pass
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class CompanionServer:
    """Loopback-Server für genau eine Boîte-à-Oublis-Verbindung."""

    def __init__(
        self,
        on_event: Callable[[str, dict], None] | None = None,
        tokens: Iterable[str] = (),
        ports: Iterable[int] = PORTS,
        clock: Callable[[], float] | None = None,
    ):
        self.on_event = on_event or (lambda kind, payload: None)
        self.ports = tuple(ports)
        self.tokens: list[str] = [str(t) for t in tokens if str(t)][:MAX_TOKENS]
        self.port = 0
        self.last_error = ""
        self._clock = clock or time.monotonic
        self._server_socket: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.RLock()
        self._active: _Connection | None = None
        self._invite = ""
        self._invite_until = 0.0
        self._command_counter = 0
        self._pending: dict[str, str] = {}
        self._pairings: list[PairingRequest] = []

    # ---- Lebenszyklus ----------------------------------------------------
    def start(self) -> int:
        """Bindet den ersten freien Port. 0 bedeutet: kein Port frei.

        Port 0 in der Liste überlässt die Wahl dem System; das ist für
        Prüfungen nützlich und im Betrieb ungenutzt.
        """
        if self._running:
            return self.port
        last_error = ""
        for port in self.ports:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if os.name != "nt":
                # Unter Windows erlaubt SO_REUSEADDR das Übernehmen eines
                # fremden Ports - genau das soll hier nicht passieren.
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                server_socket.bind((HOST, port))
                server_socket.listen(4)
                server_socket.settimeout(0.5)
            except OSError as exc:
                last_error = str(exc)
                server_socket.close()
                continue
            self._server_socket = server_socket
            # Bei Port 0 vergibt das System die Nummer - dann gilt die echte.
            self.port = server_socket.getsockname()[1]
            self._running = True
            self.last_error = ""
            self._accept_thread = threading.Thread(
                target=self._accept_loop, name="companion-accept", daemon=True
            )
            self._accept_thread.start()
            return port
        self.last_error = last_error or "Kein freier Port für die Verbindung."
        self.port = 0
        return 0

    def stop(self) -> None:
        self._running = False
        with self._lock:
            active = self._active
            self._active = None
            pairings = list(self._pairings)
            self._pairings.clear()
        for pairing in pairings:
            # Niemand soll auf eine Antwort warten, die nicht mehr kommt.
            pairing.reject()
        if active:
            active.close(1001, "shutdown")
        server_socket = self._server_socket
        self._server_socket = None
        if server_socket:
            try:
                server_socket.close()
            except OSError:
                pass
        thread = self._accept_thread
        self._accept_thread = None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self.port = 0

    @property
    def running(self) -> bool:
        return self._running

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._active is not None and self._active.authenticated

    @property
    def client_name(self) -> str:
        with self._lock:
            return self._active.client_name if self._active else ""

    # ---- Einladung -------------------------------------------------------
    def issue_invite(self) -> str:
        """Einmal gültiger Code, den der Aufruf von Boîte à Oublis mitbringt."""
        with self._lock:
            self._invite = new_invite()
            self._invite_until = self._clock() + INVITE_LIFETIME
            return self._invite

    def _consume_invite(self, invite: str) -> bool:
        with self._lock:
            if not self._invite or not invite:
                return False
            if self._clock() > self._invite_until:
                self._invite = ""
                return False
            if not secrets.compare_digest(invite, self._invite):
                return False
            self._invite = ""
            return True

    def _remember_token(self, token: str) -> None:
        with self._lock:
            if token in self.tokens:
                return
            self.tokens.append(token)
            del self.tokens[:-MAX_TOKENS]
        self.on_event("tokens", {"tokens": list(self.tokens)})

    def _known_token(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            known = list(self.tokens)
        return any(secrets.compare_digest(token, candidate) for candidate in known)

    # ---- Befehle ---------------------------------------------------------
    def send_command(self, name: str, args: dict | None = None) -> str:
        """Sendet einen erlaubten Befehl. Leerer Rückgabewert = nicht gesendet."""
        checked = command_args(name, args or {})
        if checked is None:
            return ""
        with self._lock:
            connection = self._active
            if connection is None or not connection.authenticated:
                return ""
            self._command_counter += 1
            command_id = f"c{self._command_counter}"
            self._pending[command_id] = name
            if len(self._pending) > 64:
                self._pending.pop(next(iter(self._pending)))
        if not connection.send(build("command", id=command_id, name=name, args=checked)):
            return ""
        return command_id

    def disconnect_client(self, reason: str = "closed") -> None:
        with self._lock:
            active = self._active
            self._active = None
        if active:
            active.send(build("denied", reason=reason))
            active.close(1000, reason)
            self.on_event("disconnected", {"reason": reason})

    # ---- Annahmeschleife -------------------------------------------------
    def _accept_loop(self) -> None:
        while self._running:
            server_socket = self._server_socket
            if server_socket is None:
                break
            try:
                client, _address = server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client.settimeout(HANDSHAKE_TIMEOUT)
            threading.Thread(
                target=self._serve, args=(client,), name="companion-client", daemon=True
            ).start()

    def _serve(self, sock: socket.socket) -> None:
        connection = _Connection(sock, self)
        try:
            if not self._handshake(connection):
                return
            self._read_loop(connection)
        except (OSError, ProtocolError):
            pass
        finally:
            self._drop(connection)

    def _handshake(self, connection: _Connection) -> bool:
        data = bytearray()
        deadline = self._clock() + HANDSHAKE_TIMEOUT
        while self._clock() < deadline:
            try:
                chunk = connection.sock.recv(4096)
            except socket.timeout:
                break
            except OSError:
                return False
            if not chunk:
                return False
            data.extend(chunk)
            if len(data) > 16384:
                return False
            headers = parse_request(bytes(data))
            if headers is None:
                continue
            response = handshake_response(headers)
            if response is None:
                try:
                    connection.sock.sendall(
                        b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n"
                    )
                except OSError:
                    pass
                return False
            connection.client_name = _text(headers.get("user-agent"), 120)
            return connection.send_raw(response)
        return False

    def _read_loop(self, connection: _Connection) -> None:
        connection.sock.settimeout(1.0)
        last_seen = self._clock()
        last_ping = self._clock()
        while self._running and not connection.closed:
            try:
                chunk = connection.sock.recv(8192)
            except socket.timeout:
                chunk = b""
            except OSError:
                return
            else:
                if not chunk:
                    return
                last_seen = self._clock()

            if chunk:
                for opcode, payload in connection.reader.feed(chunk):
                    if opcode == OPCODE_CLOSE:
                        return
                    if opcode == OPCODE_PING:
                        connection.send_raw(encode_frame(payload, OPCODE_PONG))
                        continue
                    if opcode == OPCODE_PONG:
                        continue
                    if opcode != OPCODE_TEXT:
                        continue                       # Binärdaten gibt es nicht
                    self._handle_message(connection, payload)
                # Eine Nachricht kann lange dauern - die Rückfrage zur Kopplung
                # wartet auf einen Klick. Danach zählt die Stille neu.
                last_seen = self._clock()
                last_ping = last_seen

            now = self._clock()
            if not connection.authenticated and now - last_seen > HELLO_TIMEOUT:
                return
            if now - last_seen > IDLE_TIMEOUT:
                return
            if connection.authenticated and now - last_ping > PING_INTERVAL:
                last_ping = now
                if not connection.send_raw(encode_frame(b"", OPCODE_PING)):
                    return

    def _handle_message(self, connection: _Connection, payload: bytes) -> None:
        message = parse_message(payload)
        if message is None:
            self.on_event("rejected", {"reason": "unlesbare Nachricht"})
            return
        kind = message["type"]

        if kind == "hello":
            self._handle_hello(connection, message)
            return
        if not connection.authenticated:
            return                                     # vor der Kopplung: nichts
        if kind == "status":
            self.on_event("status", {"status": parse_status(message.get("state"))})
        elif kind == "result":
            command_id = _text(message.get("id"), 40)
            with self._lock:
                name = self._pending.pop(command_id, "")
            self.on_event("result", {
                "id": command_id,
                "name": name,
                "ok": bool(message.get("ok")),
                "error": _text(message.get("error"), 200),
                "data": message.get("data") if isinstance(message.get("data"), dict) else {},
            })
        elif kind == "bye":
            connection.close(1000, "bye")

    def _handle_hello(self, connection: _Connection, message: dict) -> None:
        if connection.authenticated:
            return
        client = message.get("client")
        client = client if isinstance(client, dict) else {}
        if _text(client.get("app"), 60) != CLIENT_APP:
            connection.send(build("denied", reason="unknown-app"))
            connection.close(1008, "unknown-app")
            return

        connection.client_name = _text(client.get("name"), 80) or "Boîte à Oublis"
        connection.client_version = _text(client.get("version"), 40)

        token = _text(message.get("token"), 120)
        invite = _text(message.get("invite"), 120)
        granted = ""

        if self._known_token(token):
            granted = token
        elif self._consume_invite(invite):
            granted = new_token()
            self._remember_token(granted)
        else:
            request = PairingRequest(
                client_name=connection.client_name,
                client_version=connection.client_version,
                code=short_code(f"{connection.client_name}:{self._clock()}"),
            )
            with self._lock:
                self._pairings.append(request)
            # Erst Bescheid geben, dann fragen: Die Gegenstelle weiß damit,
            # dass sie am richtigen Ort ist, und wartet geduldig auf die
            # Entscheidung der Lehrkraft statt weiterzusuchen.
            connection.send(build("pending", reason="pairing"))
            self.on_event("pairing", {"request": request})
            approved = request.wait()
            with self._lock:
                if request in self._pairings:
                    self._pairings.remove(request)
            if not approved:
                connection.send(build("denied", reason="rejected"))
                connection.close(1008, "rejected")
                return
            granted = new_token()
            self._remember_token(granted)

        previous: _Connection | None = None
        with self._lock:
            if self._active is not None and self._active is not connection:
                previous = self._active
            connection.authenticated = True
            self._active = connection
        if previous is not None:
            # Es gibt nur eine Leinwand: Das zuletzt geöffnete Fenster steuert.
            previous.send(build("denied", reason="superseded"))
            previous.close(1000, "superseded")

        connection.send(build(
            "welcome",
            app=SERVER_APP,
            token=granted,
            paired=True,
        ))
        self.on_event("connected", {
            "name": connection.client_name,
            "version": connection.client_version,
        })

    def _drop(self, connection: _Connection) -> None:
        was_active = False
        with self._lock:
            if self._active is connection:
                self._active = None
                was_active = True
        connection.close()
        if was_active:
            self.on_event("disconnected", {"reason": "closed"})


# ---------------------------------------------------------------------------
# Gemeinsame Phasen-Presets
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Kleinschreibung ohne Akzente und Sonderzeichen."""
    folded = unicodedata.normalize("NFKD", str(text or ""))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "", folded.lower())


def _common_prefix(left: str, right: str) -> int:
    length = 0
    for a, b in zip(left, right):
        if a != b:
            break
        length += 1
    return length


# Vorschläge für die mitgelieferten Szenen. Sie sind nur ein Startwert: Jede
# Zuordnung lässt sich überschreiben, und eine umbenannte Szene fällt auf den
# Ähnlichkeitsvergleich zurück.
DEFAULT_SCENE_PHASES = {
    "partnergesprach": "phase-partner",
    "diskussion": "phase-plenum",
    "rollenspiel": "phase-partner",
    "prasentation": "phase-presentation",
    "schreibphase": "phase-individual",
    "textanalyse": "phase-individual",
    "sprachmittlung": "phase-partner",
    "reflexion": "phase-plenum",
    "wortschatzarbeit": "phase-individual",
}


def suggest_phase_for_scene(scene: str, phase_items, overrides: dict[str, str] | None = None) -> str:
    """Schlägt eine Sozialform zu einer Szene vor.

    Reihenfolge: eigene Zuordnung, mitgelieferte Zuordnung, Ähnlichkeit der
    Namen. Findet sich nichts, bleibt die Auswahl leer - geraten wird nicht.
    """
    key = normalize(scene)
    if not key:
        return ""
    available = {item.item_id: item for item in phase_items}
    if not available:
        return ""

    overrides = overrides or {}
    chosen = overrides.get(key, "")
    if chosen in available:
        return chosen

    fallback = DEFAULT_SCENE_PHASES.get(key, "")
    if fallback in available:
        return fallback

    best_id = ""
    best_score = 0
    for item_id, item in available.items():
        candidates = [normalize(item.name)]
        candidates.extend(normalize(part) for part in re.split(r"[\s/,-]+", item.name or "") if part)
        for candidate in candidates:
            if not candidate:
                continue
            score = _common_prefix(key, candidate)
            shortest = min(len(key), len(candidate))
            if score < 5 or shortest == 0 or score / shortest < 0.4:
                continue
            if score > best_score:
                best_score = score
                best_id = item_id
    return best_id


@dataclass
class Preset:
    """Eine Unterrichtsaktivität, die beide Programme gemeinsam starten."""

    preset_id: str = ""
    name: str = ""
    target_kind: str = "bank"        # bank | board
    target_id: str = ""
    target_title: str = ""           # nur zur Anzeige, wenn Boîte nicht läuft
    target_group: str = ""
    level: int = 2
    phase_id: str = ""
    material_ids: list[str] = field(default_factory=list)
    timer_minutes: int = 0
    timer_autostart: bool = False
    missing: bool = False            # Ziel in Boîte à Oublis nicht gefunden

    def label(self) -> str:
        return self.name or self.target_title or "Ohne Namen"

    def to_dict(self) -> dict:
        return {
            "preset_id": self.preset_id,
            "name": self.name,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "target_title": self.target_title,
            "target_group": self.target_group,
            "level": self.level,
            "phase_id": self.phase_id,
            "material_ids": list(self.material_ids),
            "timer_minutes": self.timer_minutes,
            "timer_autostart": self.timer_autostart,
            "missing": self.missing,
        }


def parse_preset(raw) -> Preset | None:
    if not isinstance(raw, dict):
        return None
    target_id = _text(raw.get("target_id"), 120)
    if not target_id:
        return None
    material_ids: list[str] = []
    for item_id in _list(raw.get("material_ids")):
        item_id = _text(item_id, 120)
        if item_id and item_id not in material_ids:
            material_ids.append(item_id)
    return Preset(
        preset_id=_text(raw.get("preset_id"), 120) or f"pre-{secrets.token_hex(6)}",
        name=_text(raw.get("name"), 120),
        target_kind="board" if raw.get("target_kind") == "board" else "bank",
        target_id=target_id,
        target_title=_text(raw.get("target_title"), 160),
        target_group=_text(raw.get("target_group"), 120),
        level=_int(raw.get("level"), 2, 1, 3),
        phase_id=_text(raw.get("phase_id"), 120),
        material_ids=material_ids[:12],
        timer_minutes=_int(raw.get("timer_minutes"), 0, 0, 999),
        timer_autostart=bool(raw.get("timer_autostart")),
        missing=bool(raw.get("missing")),
    )


@dataclass
class CompanionConfig:
    """Alles, was die Verbindung dauerhaft braucht."""

    enabled: bool = False
    app_path: str = ""
    tokens: list[str] = field(default_factory=list)
    scene_map: dict[str, str] = field(default_factory=dict)
    presets: list[Preset] = field(default_factory=list)
    hotkeys: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "app_path": self.app_path,
            "tokens": list(self.tokens),
            "scene_map": dict(self.scene_map),
            "presets": [preset.to_dict() for preset in self.presets],
            "hotkeys": dict(self.hotkeys),
        }

    def preset(self, preset_id: str) -> Preset | None:
        for preset in self.presets:
            if preset.preset_id == preset_id:
                return preset
        return None


# Frei belegbare globale Hotkeys. Leer heißt: nicht vergeben - dadurch kann
# nichts mit den vorhandenen Klang- und Stopp-Hotkeys kollidieren.
HOTKEY_ACTIONS = (
    ("blank", "Sprachhilfe ein-/ausblenden"),
    ("next", "Nächste Seite"),
    ("prev", "Vorherige Seite"),
    ("level_1", "Unterstützungsstufe 1"),
    ("level_2", "Unterstützungsstufe 2"),
    ("level_3", "Unterstützungsstufe 3"),
)
HOTKEY_KEYS = tuple(key for key, _label in HOTKEY_ACTIONS)


def parse_companion_config(raw) -> CompanionConfig:
    """Liest den gespeicherten Stand - jedes Feld einzeln und tolerant."""
    data = raw if isinstance(raw, dict) else {}

    tokens: list[str] = []
    for token in _list(data.get("tokens")):
        token = _text(token, 120)
        if token and token not in tokens:
            tokens.append(token)

    scene_map: dict[str, str] = {}
    raw_map = data.get("scene_map")
    if isinstance(raw_map, dict):
        for scene, phase_id in raw_map.items():
            key = normalize(scene)
            value = _text(phase_id, 120)
            if key and value:
                scene_map[key] = value

    presets: list[Preset] = []
    seen: set[str] = set()
    for entry in _list(data.get("presets")):
        preset = parse_preset(entry)
        if preset is None or preset.preset_id in seen:
            continue
        seen.add(preset.preset_id)
        presets.append(preset)

    hotkeys: dict[str, str] = {}
    raw_hotkeys = data.get("hotkeys")
    if isinstance(raw_hotkeys, dict):
        for key in HOTKEY_KEYS:
            value = _text(raw_hotkeys.get(key), 60)
            if value:
                hotkeys[key] = value

    return CompanionConfig(
        enabled=bool(data.get("enabled")),
        app_path=_text(data.get("app_path"), 1024),
        tokens=tokens[:MAX_TOKENS],
        scene_map=scene_map,
        presets=presets[:60],
        hotkeys=hotkeys,
    )


def invitation_url(app_path: str, port: int, invite: str) -> str:
    """Adresse, die Boîte à Oublis mit Einladung öffnet.

    Die Einladung steht ausschließlich im Textanker (``#``). Der bleibt außen
    vor, wenn der Browser den lokalen Speicher einer Datei zuordnet - ein
    Suchteil (``?``) dürfte das nicht und würde einen zweiten, scheinbar
    leeren Datenbestand erzeugen.
    """
    raw = str(app_path or "")
    if re.match(r"^[A-Za-z]:[\\/]", raw) or "\\" in raw and os.name == "nt":
        location = PureWindowsPath(raw).as_posix()
    else:
        location = Path(raw).expanduser().as_posix()
    if not location.startswith("/"):
        location = "/" + location
    url = "file://" + quote(location, safe="/:")
    if port and invite:
        url += f"#/companion/{port}/{quote(invite, safe='')}"
    return url
