"""Prüfungen für den Companion-Modus.

Alles hier läuft ohne Benutzeroberfläche: Rahmenformat, Nachrichtenprüfung,
Kopplung, Befehlsvermittlung und die Presets. Der Server wird dabei wirklich
auf 127.0.0.1 gestartet und mit einem selbst gebauten Browser-Client bedient.
"""

import base64
import json
import os
import secrets
import socket
import struct
import threading
import time
import unittest

import companion


def free_ports(count: int = 1) -> list[int]:
    """Sucht freie Ports, damit parallele Testläufe sich nicht behindern."""
    sockets = []
    ports = []
    for _ in range(count):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        ports.append(probe.getsockname()[1])
        sockets.append(probe)
    for probe in sockets:
        probe.close()
    return ports


class FakeBrowser:
    """Minimaler WebSocket-Client, wie ihn ein Browser spricht (maskiert)."""

    def __init__(self, port: int, origin: str = "null", timeout: float = 5.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.reader = companion.FrameReader(require_mask=False)
        self.buffer: list[tuple[int, bytes]] = []
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET /companion HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Origin: {origin}\r\n"
            "User-Agent: Test\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        self.status_line = head.split(b"\r\n")[0].decode("latin-1")
        self.handshake_ok = "101" in self.status_line
        if rest:
            self.buffer.extend(self.reader.feed(rest))

    # ---- Senden (immer maskiert, wie ein Browser)
    def send(self, text: str) -> None:
        data = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        else:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        mask = secrets.token_bytes(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def hello(self, token: str = "", invite: str = "", app: str = companion.CLIENT_APP) -> None:
        self.send(companion.build(
            "hello",
            client={"app": app, "name": "Boîte à Oublis", "version": "1.2.0"},
            token=token or None,
            invite=invite or None,
        ))

    def status(self, **state) -> None:
        self.send(companion.build("status", state=state))

    def result(self, command_id: str, ok: bool = True, error: str = "", data=None) -> None:
        self.send(companion.build("result", id=command_id, ok=ok, error=error or None, data=data))

    # ---- Empfangen
    def next_message(self, timeout: float = 5.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while self.buffer:
                opcode, payload = self.buffer.pop(0)
                if opcode == companion.OPCODE_TEXT:
                    return json.loads(payload.decode("utf-8"))
                if opcode == companion.OPCODE_CLOSE:
                    return {"type": "__closed__"}
            try:
                chunk = self.sock.recv(8192)
            except socket.timeout:
                continue
            except OSError:
                return None
            if not chunk:
                return None
            self.buffer.extend(self.reader.feed(chunk))
        return None

    def wait_for(self, message_type: str, timeout: float = 5.0) -> dict | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.next_message(timeout=max(0.1, deadline - time.monotonic()))
            if message is None:
                return None
            if message.get("type") == message_type:
                return message
        return None

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class HandshakeTests(unittest.TestCase):
    def test_accept_key_matches_the_specification(self):
        # Beispiel aus RFC 6455.
        self.assertEqual(
            companion.accept_key("dGhlIHNhbXBsZSBub25jZQ=="),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=",
        )

    def test_only_local_origins_are_allowed(self):
        for origin in ("", "null", "file://", "http://127.0.0.1:8765", "http://localhost:5173"):
            self.assertTrue(companion.origin_allowed(origin), origin)
        for origin in ("https://example.com", "http://192.168.0.5:8765", "http://localhost.evil.com"):
            self.assertFalse(companion.origin_allowed(origin), origin)

    def test_a_wrong_request_gets_no_upgrade(self):
        good = {
            "__request__": "GET / HTTP/1.1",
            "upgrade": "websocket",
            "connection": "Upgrade",
            "sec-websocket-version": "13",
            "sec-websocket-key": "dGhlIHNhbXBsZSBub25jZQ==",
            "origin": "null",
        }
        self.assertIsNotNone(companion.handshake_response(good))

        for field, value in [
            ("upgrade", "h2c"),
            ("connection", "keep-alive"),
            ("sec-websocket-version", "8"),
            ("sec-websocket-key", ""),
            ("origin", "https://example.com"),
            ("__request__", "POST / HTTP/1.1"),
        ]:
            broken = dict(good)
            broken[field] = value
            self.assertIsNone(companion.handshake_response(broken), field)
        self.assertIsNone(companion.handshake_response({}))

    def test_an_incomplete_request_is_not_parsed_yet(self):
        self.assertIsNone(companion.parse_request(b"GET / HTTP/1.1\r\nUpgrade: web"))
        headers = companion.parse_request(b"GET / HTTP/1.1\r\nUpgrade: websocket\r\n\r\n")
        self.assertEqual(headers["upgrade"], "websocket")


class FrameTests(unittest.TestCase):
    @staticmethod
    def mask(payload: bytes, opcode: int = companion.OPCODE_TEXT, fin: bool = True) -> bytes:
        header = bytearray([(0x80 if fin else 0) | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        else:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        mask = b"\x01\x02\x03\x04"
        header.extend(mask)
        return bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

    def test_server_frames_are_unmasked_and_readable(self):
        frame = companion.encode_frame("Hallo")
        self.assertEqual(frame[0], 0x81)
        self.assertEqual(frame[1], 5)
        self.assertEqual(frame[2:], b"Hallo")

    def test_long_payloads_use_the_extended_length(self):
        long_frame = companion.encode_frame("x" * 200)
        self.assertEqual(long_frame[1], 126)
        very_long = companion.encode_frame("x" * 70000)
        self.assertEqual(very_long[1], 127)

    def test_fragmented_messages_are_joined(self):
        reader = companion.FrameReader()
        self.assertEqual(reader.feed(self.mask(b"Teil 1 ", fin=False)), [])
        messages = reader.feed(self.mask(b"und Teil 2", companion.OPCODE_CONTINUATION))
        self.assertEqual(messages, [(companion.OPCODE_TEXT, b"Teil 1 und Teil 2")])

    def test_bytes_may_arrive_in_arbitrary_pieces(self):
        reader = companion.FrameReader()
        frame = self.mask("Grüße".encode("utf-8"))
        for index in range(len(frame) - 1):
            self.assertEqual(reader.feed(frame[index:index + 1]), [])
        result = reader.feed(frame[-1:])
        self.assertEqual(result[0][1].decode("utf-8"), "Grüße")

    def test_unmasked_client_data_is_refused(self):
        reader = companion.FrameReader()
        with self.assertRaises(companion.ProtocolError):
            reader.feed(companion.encode_frame("ohne Maske"))

    def test_oversized_messages_are_refused(self):
        reader = companion.FrameReader(max_bytes=64)
        with self.assertRaises(companion.ProtocolError):
            reader.feed(self.mask(b"x" * 200))

    def test_control_frames_pass_through(self):
        reader = companion.FrameReader()
        messages = reader.feed(self.mask(b"", companion.OPCODE_PING))
        self.assertEqual(messages, [(companion.OPCODE_PING, b"")])


class MessageTests(unittest.TestCase):
    def test_a_correct_message_is_accepted(self):
        raw = companion.build("hello", client={"app": companion.CLIENT_APP})
        parsed = companion.parse_message(raw)
        self.assertEqual(parsed["type"], "hello")
        self.assertEqual(parsed["v"], companion.PROTOCOL_VERSION)

    def test_broken_unknown_and_outdated_messages_are_dropped(self):
        cases = [
            "kein json",
            "[]",
            '"text"',
            json.dumps({"protocol": "etwas-anderes", "v": 1, "type": "hello"}),
            json.dumps({"protocol": companion.PROTOCOL, "v": 99, "type": "hello"}),
            json.dumps({"protocol": companion.PROTOCOL, "v": 1, "type": "drop-database"}),
            json.dumps({"protocol": companion.PROTOCOL, "v": 1}),
            json.dumps({"protocol": companion.PROTOCOL, "v": "1", "type": "hello"}),
        ]
        for raw in cases:
            self.assertIsNone(companion.parse_message(raw), raw[:40])

    def test_very_large_messages_are_dropped(self):
        raw = json.dumps({
            "protocol": companion.PROTOCOL, "v": 1, "type": "status",
            "state": {"title": "x" * (companion.MAX_MESSAGE_BYTES + 10)},
        })
        self.assertIsNone(companion.parse_message(raw))

    def test_only_known_commands_pass_with_checked_arguments(self):
        self.assertIsNone(companion.command_args("eval", {"code": "alert(1)"}))
        self.assertIsNone(companion.command_args("level.set", {"level": 9}))
        self.assertEqual(companion.command_args("level.set", {"level": "3"}), {"level": 3})
        self.assertEqual(companion.command_args("page.next", {"weg": "damit"}), {})
        self.assertEqual(companion.command_args("blank.set", {"blank": 1}), {"blank": True})
        self.assertIsNone(companion.command_args("live.add", {"text": "   "}))
        self.assertEqual(
            companion.command_args("live.add", {"text": " Je pense que ", "kind": "starter"}),
            {"text": "Je pense que", "translation": "", "kind": "starter"},
        )
        self.assertIsNone(companion.command_args("preset.start", {}))
        self.assertEqual(
            companion.command_args("preset.start", {"id": "bnk_1", "kind": "kaputt", "level": 2}),
            {"id": "bnk_1", "kind": "bank", "level": 2},
        )
        self.assertEqual(
            companion.command_args("preset.start", {"id": "bnk_1", "level": "wirr"}),
            {"id": "bnk_1", "kind": "bank"},
        )

    def test_status_is_read_field_by_field(self):
        status = companion.parse_status({
            "kind": "unfug", "active": 1, "level": 7, "page": -3,
            "pages": "12", "title": "Au marché", "blank": True,
        })
        self.assertEqual(status.kind, "none")
        self.assertTrue(status.active)
        self.assertEqual(status.level, 3)
        self.assertEqual(status.page, 0)
        self.assertEqual(status.pages, 12)
        self.assertEqual(status.title, "Au marché")
        self.assertEqual(status.tile_state(), "blank")
        self.assertEqual(companion.parse_status("Unsinn").kind, "none")
        self.assertEqual(companion.BoiteStatus().tile_state(), "offline")

    def test_library_entries_without_an_id_are_ignored(self):
        library = companion.parse_library({
            "banks": [{"id": "bnk_1", "title": "Au marché", "defaultLevel": 9}, {"title": "ohne Kennung"}],
            "boards": "kaputt",
        })
        self.assertEqual(len(library["banks"]), 1)
        self.assertEqual(library["banks"][0]["level"], "3")
        self.assertEqual(library["boards"], [])


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.events: list[tuple[str, dict]] = []
        self.auto_pair = False
        self.server = companion.CompanionServer(on_event=self._record, ports=free_ports(2))
        self.clients: list[FakeBrowser] = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.server.stop()

    def _record(self, kind: str, payload: dict) -> None:
        self.events.append((kind, payload))
        if kind == "pairing":
            request = payload["request"]
            request.approve() if self.auto_pair else request.reject()

    def _kinds(self) -> list[str]:
        return [kind for kind, _payload in self.events]

    def browser(self, **kwargs) -> FakeBrowser:
        client = FakeBrowser(self.server.port, **kwargs)
        self.clients.append(client)
        return client

    def wait_until(self, predicate, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def test_an_invitation_pairs_without_a_question(self):
        self.assertTrue(self.server.start())
        invite = self.server.issue_invite()
        client = self.browser()
        self.assertTrue(client.handshake_ok)
        client.hello(invite=invite)

        welcome = client.wait_for("welcome")
        self.assertIsNotNone(welcome)
        self.assertEqual(welcome["app"], companion.SERVER_APP)
        self.assertTrue(welcome["token"])
        self.assertNotIn("pairing", self._kinds())
        self.assertTrue(self.wait_until(lambda: self.server.connected))
        self.assertIn(welcome["token"], self.server.tokens)

    def test_an_invitation_works_only_once(self):
        self.server.start()
        invite = self.server.issue_invite()
        first = self.browser()
        first.hello(invite=invite)
        self.assertIsNotNone(first.wait_for("welcome"))

        second = self.browser()
        second.hello(invite=invite)
        denied = second.wait_for("denied")
        self.assertEqual(denied["reason"], "rejected")

    def test_a_stored_token_reconnects_without_a_question(self):
        token = companion.new_token()
        self.server.tokens.append(token)
        self.server.start()
        client = self.browser()
        client.hello(token=token)
        welcome = client.wait_for("welcome")
        self.assertEqual(welcome["token"], token)
        self.assertNotIn("pairing", self._kinds())

    def test_a_client_without_a_token_needs_approval(self):
        self.auto_pair = True
        self.server.start()
        client = self.browser()
        client.hello()
        # Erst die Zwischenmeldung, dann die Antwort: Die Gegenstelle weiß so,
        # dass sie am richtigen Ort ist, und sucht nicht weiter.
        self.assertIsNotNone(client.wait_for("pending"))
        self.assertIsNotNone(client.wait_for("welcome"))
        self.assertIn("pairing", self._kinds())

        request = next(p["request"] for k, p in self.events if k == "pairing")
        self.assertEqual(len(request.code), 6)
        self.assertTrue(request.answered)

    def test_a_slow_decision_does_not_break_the_connection(self):
        # Die Lehrkraft braucht einen Moment für den Klick. In dieser Zeit darf
        # weder die Verbindung auslaufen noch die Rückfrage verloren gehen.
        self.auto_pair = None
        approvals = []

        def approve_later(kind, payload):
            self.events.append((kind, payload))
            if kind == "pairing":
                request = payload["request"]
                approvals.append(request)
                threading.Timer(1.2, request.approve).start()

        self.server.on_event = approve_later
        self.server.start()
        client = self.browser()
        client.hello()
        self.assertIsNotNone(client.wait_for("pending", timeout=5))
        self.assertIsNotNone(client.wait_for("welcome", timeout=10))
        self.assertTrue(self.wait_until(lambda: self.server.connected))

        client.status(kind="bank", active=True, title="Nach der Rückfrage")
        self.assertTrue(self.wait_until(lambda: "status" in self._kinds()))

    def test_a_pending_request_is_released_when_the_program_closes(self):
        self.auto_pair = None
        self.server.on_event = lambda kind, payload: self.events.append((kind, payload))
        self.server.start()
        client = self.browser()
        client.hello()
        self.assertTrue(self.wait_until(lambda: "pairing" in self._kinds()))
        request = next(p["request"] for k, p in self.events if k == "pairing")
        self.server.stop()
        self.assertTrue(self.wait_until(lambda: request.answered, timeout=5))

    def test_a_rejected_client_stays_outside(self):
        self.auto_pair = False
        self.server.start()
        client = self.browser()
        client.hello()
        denied = client.wait_for("denied")
        self.assertEqual(denied["reason"], "rejected")
        self.assertFalse(self.server.connected)
        self.assertFalse(self.server.tokens)

    def test_a_foreign_program_is_turned_away(self):
        self.server.start()
        client = self.browser()
        client.hello(app="irgendwas-anderes")
        denied = client.wait_for("denied")
        self.assertEqual(denied["reason"], "unknown-app")
        self.assertFalse(self.server.connected)

    def test_a_remote_origin_never_gets_through(self):
        self.server.start()
        client = FakeBrowser(self.server.port, origin="https://example.com")
        self.clients.append(client)
        self.assertFalse(client.handshake_ok)
        self.assertIn("400", client.status_line)

    def test_commands_and_results_travel_in_both_directions(self):
        self.server.start()
        invite = self.server.issue_invite()
        client = self.browser()
        client.hello(invite=invite)
        client.wait_for("welcome")
        self.assertTrue(self.wait_until(lambda: self.server.connected))

        command_id = self.server.send_command("level.set", {"level": 3})
        self.assertTrue(command_id)
        command = client.wait_for("command")
        self.assertEqual(command["name"], "level.set")
        self.assertEqual(command["args"], {"level": 3})

        client.result(command["id"], ok=True, data={"level": 3})
        self.assertTrue(self.wait_until(lambda: "result" in self._kinds()))
        result = next(p for k, p in self.events if k == "result")
        self.assertEqual(result["name"], "level.set")
        self.assertTrue(result["ok"])

    def test_an_unknown_command_is_never_sent(self):
        self.server.start()
        invite = self.server.issue_invite()
        client = self.browser()
        client.hello(invite=invite)
        client.wait_for("welcome")
        self.assertTrue(self.wait_until(lambda: self.server.connected))
        self.assertEqual(self.server.send_command("shell.exec", {"cmd": "rm -rf /"}), "")
        self.assertEqual(self.server.send_command("level.set", {"level": 42}), "")

    def test_status_reaches_the_program(self):
        self.server.start()
        invite = self.server.issue_invite()
        client = self.browser()
        client.hello(invite=invite)
        client.wait_for("welcome")
        client.status(kind="bank", active=True, title="Au marché", group="9b",
                      level=2, page=1, pages=4, blank=False)
        self.assertTrue(self.wait_until(lambda: "status" in self._kinds()))
        status = next(p["status"] for k, p in self.events if k == "status")
        self.assertEqual(status.title, "Au marché")
        self.assertEqual(status.pages, 4)
        self.assertEqual(status.tile_state(), "live")

    def test_garbage_does_not_disturb_a_running_connection(self):
        self.server.start()
        invite = self.server.issue_invite()
        client = self.browser()
        client.hello(invite=invite)
        client.wait_for("welcome")
        self.assertTrue(self.wait_until(lambda: self.server.connected))

        client.send("überhaupt kein JSON")
        client.send(json.dumps({"protocol": "fremd", "v": 1, "type": "status"}))
        client.send(json.dumps({"protocol": companion.PROTOCOL, "v": 7, "type": "status"}))
        self.assertTrue(self.wait_until(lambda: self._kinds().count("rejected") >= 3))

        client.status(kind="bank", active=True, title="Weiter geht es")
        self.assertTrue(self.wait_until(lambda: "status" in self._kinds()))
        self.assertTrue(self.server.connected)

    def test_a_second_window_takes_over_understandably(self):
        self.server.start()
        first = self.browser()
        first.hello(invite=self.server.issue_invite())
        first.wait_for("welcome")
        self.assertTrue(self.wait_until(lambda: self.server.connected))

        second = self.browser()
        second.hello(invite=self.server.issue_invite())
        self.assertIsNotNone(second.wait_for("welcome"))

        denied = first.wait_for("denied")
        self.assertEqual(denied["reason"], "superseded")
        self.assertTrue(self.server.connected)

    def test_a_closed_browser_is_noticed(self):
        self.server.start()
        client = self.browser()
        client.hello(invite=self.server.issue_invite())
        client.wait_for("welcome")
        self.assertTrue(self.wait_until(lambda: self.server.connected))
        client.close()
        # Erst auf die Meldung warten: Die Verbindung gilt einen Wimpernschlag
        # früher als beendet, als das Ereignis eintrifft.
        self.assertTrue(self.wait_until(lambda: "disconnected" in self._kinds(), timeout=8))
        self.assertFalse(self.server.connected)

    def test_the_port_is_only_bound_on_the_loopback_interface(self):
        port = self.server.start()
        self.assertTrue(port)
        with socket.socket() as probe:
            probe.settimeout(1.0)
            self.assertEqual(probe.connect_ex(("127.0.0.1", port)), 0)
        for address in [a for a in _own_addresses() if a != "127.0.0.1"]:
            with socket.socket() as probe:
                probe.settimeout(1.0)
                try:
                    reached = probe.connect_ex((address, port)) == 0
                except OSError:
                    reached = False        # abgewiesen oder gefiltert: beides gut
                self.assertFalse(reached, f"Der Port ist über {address} erreichbar")

    def test_a_taken_port_moves_on_to_the_next(self):
        ports = free_ports(2)
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", ports[0]))
        blocker.listen(1)
        try:
            server = companion.CompanionServer(ports=ports)
            self.assertEqual(server.start(), ports[1])
            server.stop()
        finally:
            blocker.close()

    def test_without_a_free_port_the_program_keeps_running(self):
        blockers = []
        ports = free_ports(2)
        try:
            for port in ports:
                blocker = socket.socket()
                blocker.bind(("127.0.0.1", port))
                blocker.listen(1)
                blockers.append(blocker)
            server = companion.CompanionServer(ports=ports)
            self.assertEqual(server.start(), 0)
            self.assertTrue(server.last_error)
            self.assertFalse(server.connected)
            self.assertEqual(server.send_command("page.next"), "")
            server.stop()
        finally:
            for blocker in blockers:
                blocker.close()

    def test_stopping_twice_is_harmless(self):
        self.server.start()
        self.server.stop()
        self.server.stop()
        self.assertFalse(self.server.running)
        self.assertEqual(self.server.send_command("page.next"), "")


def _own_addresses() -> list[str]:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({info[4][0] for info in infos})


class PhaseSuggestionTests(unittest.TestCase):
    def setUp(self):
        from classroom_modules import default_phase_items
        self.phases = default_phase_items()

    def test_a_scene_suggests_a_matching_social_form(self):
        self.assertEqual(companion.suggest_phase_for_scene("Partnergespräch", self.phases), "phase-partner")
        self.assertEqual(companion.suggest_phase_for_scene("Präsentation", self.phases), "phase-presentation")
        self.assertEqual(companion.suggest_phase_for_scene("Schreibphase", self.phases), "phase-individual")

    def test_an_own_assignment_always_wins(self):
        overrides = {companion.normalize("Partnergespräch"): "phase-group"}
        self.assertEqual(
            companion.suggest_phase_for_scene("Partnergespräch", self.phases, overrides),
            "phase-group",
        )

    def test_an_assignment_to_a_deleted_symbol_is_ignored(self):
        overrides = {companion.normalize("Partnergespräch"): "phase-geloescht"}
        self.assertEqual(
            companion.suggest_phase_for_scene("Partnergespräch", self.phases, overrides),
            "phase-partner",
        )

    def test_a_renamed_scene_is_matched_by_similarity_not_by_equality(self):
        # Szenen sind frei bearbeitbar: Ein starrer Textvergleich würde hier
        # nichts mehr finden.
        self.assertEqual(
            companion.suggest_phase_for_scene("Partnerinterview im Kurs", self.phases),
            "phase-partner",
        )
        self.assertEqual(
            companion.suggest_phase_for_scene("Gruppenpuzzle", self.phases),
            "phase-group",
        )

    def test_nothing_is_guessed_when_nothing_fits(self):
        self.assertEqual(companion.suggest_phase_for_scene("Sprachmittlung", [], {}), "")
        self.assertEqual(companion.suggest_phase_for_scene("", self.phases), "")
        self.assertEqual(companion.suggest_phase_for_scene("Quiz", self.phases), "")


class CompanionConfigTests(unittest.TestCase):
    def test_defaults_keep_the_connection_switched_off(self):
        config = companion.parse_companion_config(None)
        self.assertFalse(config.enabled)
        self.assertEqual(config.app_path, "")
        self.assertEqual(config.presets, [])
        self.assertEqual(config.hotkeys, {})

    def test_broken_entries_are_repaired_or_dropped(self):
        config = companion.parse_companion_config({
            "enabled": "ja",
            "tokens": ["a", "a", "", 5],
            "presets": [
                {"preset_id": "p1", "target_id": "bnk_1", "level": 9, "timer_minutes": -4,
                 "material_ids": ["m1", "m1", "m2"]},
                {"name": "ohne Ziel"},
                "kaputt",
                {"preset_id": "p1", "target_id": "bnk_2"},
            ],
            "scene_map": {"Partnergespräch": "phase-partner", "": "x", "Quiz": ""},
            "hotkeys": {"blank": "ctrl+alt+b", "unbekannt": "F9"},
        })
        self.assertTrue(config.enabled)
        self.assertEqual(config.tokens, ["a", "5"])
        self.assertEqual(len(config.presets), 1)
        preset = config.presets[0]
        self.assertEqual(preset.level, 3)
        self.assertEqual(preset.timer_minutes, 0)
        self.assertEqual(preset.material_ids, ["m1", "m2"])
        self.assertEqual(config.scene_map, {"partnergesprach": "phase-partner"})
        self.assertEqual(config.hotkeys, {"blank": "ctrl+alt+b"})

    def test_a_preset_survives_a_round_trip(self):
        original = companion.Preset(
            preset_id="p1", name="Am Markt", target_kind="bank", target_id="bnk_1",
            target_title="Au marché", target_group="9b", level=3,
            phase_id="phase-partner", material_ids=["material-book"],
            timer_minutes=8, timer_autostart=True,
        )
        config = companion.parse_companion_config({"presets": [original.to_dict()]})
        self.assertEqual(config.presets[0].to_dict(), original.to_dict())

    def test_a_preset_can_be_marked_as_incomplete(self):
        config = companion.parse_companion_config({
            "presets": [{"preset_id": "p1", "target_id": "bnk_weg", "missing": True}],
        })
        self.assertTrue(config.presets[0].missing)
        self.assertEqual(config.preset("p1").target_id, "bnk_weg")
        self.assertIsNone(config.preset("gibt-es-nicht"))

    def test_a_preset_without_a_name_still_has_a_label(self):
        preset = companion.Preset(target_id="bnk_1", target_title="Au marché")
        self.assertEqual(preset.label(), "Au marché")
        self.assertEqual(companion.Preset(target_id="x").label(), "Ohne Namen")


class InvitationUrlTests(unittest.TestCase):
    def test_the_invitation_lives_in_the_fragment_only(self):
        url = companion.invitation_url("/Users/lehrkraft/boite/dist/boite-a-oublis.html", 8317, "abc123")
        self.assertTrue(url.startswith("file:///Users/lehrkraft/boite/dist/boite-a-oublis.html#/"))
        self.assertNotIn("?", url, "Ein Suchteil würde einen zweiten localStorage-Bestand erzeugen")
        self.assertIn("#/companion/8317/abc123", url)

    def test_a_windows_path_becomes_a_file_url(self):
        url = companion.invitation_url(r"C:\Users\Lehrkraft\boite\dist\boite-a-oublis.html", 0, "")
        self.assertTrue(url.startswith("file:///"))
        self.assertNotIn("#", url)

    def test_spaces_and_umlauts_are_encoded(self):
        url = companion.invitation_url("/home/lehrkraft/Meine Dateien/boîte.html", 8317, "a b")
        self.assertNotIn(" ", url)
        self.assertIn("%20", url)


if __name__ == "__main__":
    unittest.main()
