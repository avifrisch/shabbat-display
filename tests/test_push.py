import base64
import json
import os
import tempfile
import unittest

import push


def p8(d):
    """A .p8 key file holding private number `d`, laid out as Apple's are."""
    inner = b"\x30\x25\x02\x01\x01\x04\x20" + d.to_bytes(32, "big")       # ECPrivateKey (no public part)
    der = (b"\x30\x3d\x02\x01\x00\x30\x13\x06\x07\x2a\x86\x48\xce\x3d\x02\x01\x06\x08\x2a\x86\x48\xce\x3d\x03\x01\x07"
           b"\x04\x27" + inner)
    return "-----BEGIN PRIVATE KEY-----\n" + base64.b64encode(der).decode() + "\n-----END PRIVATE KEY-----\n"


KEY = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721


class Signing(unittest.TestCase):
    def test_the_published_example(self):
        # RFC 6979, A.2.5: P-256 with SHA-256, message "sample".
        sig = push.sign(KEY, b"sample")
        self.assertEqual(sig.hex().upper(), "EFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716"
                                            "F7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8")

    def test_a_signature_checks_out_and_a_changed_message_doesnt(self):
        sig = push.sign(KEY, b"dinner")
        self.assertTrue(push.verify(push.public_of(KEY), b"dinner", sig))
        self.assertFalse(push.verify(push.public_of(KEY), b"dinner!", sig))

    def test_reading_a_key_file(self):
        self.assertEqual(push.private_number(p8(KEY)), KEY)
        for bad in ("", "not a key", "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----"):
            with self.assertRaises(ValueError):
                push.private_number(bad)

    def test_the_sign_in_token(self):
        token = push.provider_token(KEY, "KEYID12345", "TEAM123456", 1_800_000_000)
        head, claims, sig = token.split(".")
        pad = lambda t: base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))
        self.assertEqual(json.loads(pad(head)), {"alg": "ES256", "kid": "KEYID12345"})
        self.assertEqual(json.loads(pad(claims)), {"iss": "TEAM123456", "iat": 1_800_000_000})
        self.assertTrue(push.verify(push.public_of(KEY), (head + "." + claims).encode(), pad(sig)))


class Framing(unittest.TestCase):
    def test_long_header_values(self):
        block = push.header_block([("a", "b"), ("authorization", "x" * 300)])
        self.assertEqual(block[:5], b"\x00\x01a\x01b")
        # 300 = 127 + 173: the prefix is full, then 173 as 0xAD 0x01.
        self.assertEqual(block[5:5 + 15 + 3], b"\x00\x0dauthorization\x7f\xad\x01")

    def test_a_frame(self):
        self.assertEqual(push.frame(push.DATA, 1, 3, b"hi"), b"\x00\x00\x02\x00\x01\x00\x00\x00\x03hi")

    def test_reading_the_status(self):
        self.assertEqual(push.status_of(b"\x88"), 200)
        self.assertEqual(push.status_of(b"\x20\x8c"), 400)
        self.assertIsNone(push.status_of(b"\x48\x03403"))


class FakeLink:
    made = []

    def __init__(self, host, answers):
        self.host, self.answers, self.posts, self.closed = host, answers, [], False
        FakeLink.made.append(self)

    def post(self, path, headers, body):
        self.posts.append((path, dict(headers), json.loads(body)))
        return self.answers.get(path.rsplit("/", 1)[-1], (200, b""))

    def close(self):
        self.closed = True


class Sending(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.key = os.path.join(self.dir.name, "key.p8")
        with open(self.key, "w") as f:
            f.write(p8(KEY))
        self.devices = push.Devices(os.path.join(self.dir.name, "devices.json"))
        self.settings = {"key_file": self.key, "key_id": "KEYID12345", "team_id": "TEAM123456", "topic": "com.example.app"}
        self.answers, self.logged, self.clock = {}, [], [1_800_000_000]
        FakeLink.made = []
        self.push = push.ApplePush(lambda: self.settings, self.devices, log=self.logged.append,
                                   connect=lambda host: FakeLink(host, self.answers), now=lambda: self.clock[0])

    def test_registering(self):
        self.assertTrue(self.devices.register("AB" * 32, "Dov's iPhone", "development"))
        self.assertFalse(self.devices.register("zz" * 32, "x", "development"))
        self.assertFalse(self.devices.register("ab" * 20, "x", "development"))
        self.assertFalse(self.devices.register("ab" * 32, "x", "somewhere"))
        self.assertFalse(self.devices.register(None, "x", "development"))
        # Two devices may have the same name.
        self.assertTrue(self.devices.register("cd" * 32, "Dov's iPhone", "development"))
        self.assertEqual(sorted(self.devices.all()), ["ab" * 32, "cd" * 32])

    def test_not_set_up_or_nobody_registered(self):
        self.assertIs(self.push.announce("Dinner"), False)
        self.devices.register("ab" * 32, "Kid", "development")
        self.settings["key_id"] = ""
        self.assertIs(self.push.announce("Dinner"), False)
        self.assertEqual(FakeLink.made, [])

    def test_everyone_but_the_device_that_said_it(self):
        self.devices.register("aa" * 32, "Kitchen", "development")
        self.devices.register("bb" * 32, "Dov's iPhone", "development")
        self.devices.register("cc" * 32, "Miri's iPad", "production")
        self.assertEqual(self.push.announce("Dinner is ready.", origin="Kitchen", skip="aa" * 32), 2)
        by_host = {link.host: link for link in FakeLink.made}
        self.assertEqual(set(by_host), {"api.sandbox.push.apple.com", "api.push.apple.com"})
        path, headers, body = by_host["api.sandbox.push.apple.com"].posts[0]
        self.assertEqual(path, "/3/device/" + "bb" * 32)
        self.assertEqual(headers["apns-topic"], "com.example.app")
        self.assertEqual(headers["apns-push-type"], "alert")
        self.assertEqual(headers["apns-expiration"], str(1_800_000_120))
        self.assertTrue(headers["authorization"].startswith("bearer "))
        self.assertEqual(body["announcement"], "Dinner is ready.")
        self.assertEqual(body["aps"]["alert"]["body"], "Dinner is ready.")
        self.assertEqual(body["aps"]["mutable-content"], 1)
        self.assertTrue(all(link.closed for link in FakeLink.made))

    def test_a_removed_app_is_forgotten(self):
        self.devices.register("aa" * 32, "Gone", "development")
        self.devices.register("bb" * 32, "Here", "development")
        self.answers["aa" * 32] = (None, b'{"reason":"Unregistered"}')
        self.assertEqual(self.push.announce("Dinner"), 1)
        self.assertEqual(list(self.devices.all()), ["bb" * 32])
        self.assertIn("Unregistered", self.logged[0])

    def test_the_sign_in_token_is_kept_for_forty_minutes(self):
        self.devices.register("aa" * 32, "Kid", "development")
        self.push.announce("one")
        self.clock[0] += 1200
        self.push.announce("two")
        self.clock[0] += 1300
        self.push.announce("three")
        tokens = [link.posts[0][1]["authorization"] for link in FakeLink.made]
        self.assertEqual(tokens[0], tokens[1])
        self.assertNotEqual(tokens[1], tokens[2])

    def test_the_key_never_reaches_the_log(self):
        self.devices.register("aa" * 32, "Kid", "development")
        self.answers["aa" * 32] = (None, b'{"reason":"InvalidProviderToken"}')
        self.assertEqual(self.push.announce("Dinner"), 0)
        self.assertNotIn(format(KEY, "x")[:16], " ".join(self.logged))


if __name__ == "__main__":
    unittest.main()
