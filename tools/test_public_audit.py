import json
import unittest
import public_audit as a


class PublicAuditTests(unittest.TestCase):
    def fixture(self, extra=None):
        files = {"public-files.json": b"", "patch/Fix.java": b"class Fix {}\n"}
        files.update(extra or {})
        files["public-files.json"] = (json.dumps(sorted(files)) + "\n").encode()
        return files

    def test_allowed_original_text(self):
        files = self.fixture()
        self.assertEqual(2, a.audit(files, files.__getitem__))

    def test_unlisted_file_rejected(self):
        files = self.fixture()
        files["leak.java"] = b"class Leak {}"
        with self.assertRaisesRegex(ValueError, "extra="):
            a.audit(files, files.__getitem__)

    def test_private_and_binary_paths_rejected_even_if_allowlisted(self):
        for name in ["upstream/Source.java", "plugin.jar", "src/main/java/Copy.java", "docs/report.json",
                     "../escape.java", "workspace.json", "README.md"]:
            with self.subTest(name=name):
                files = self.fixture({name: b"data"})
                with self.assertRaises(ValueError):
                    a.audit(files, files.__getitem__)

    def test_encoding_and_recovered_source_rejected(self):
        for data in [b"\xef\xbb\xbfclass Fix {}", b"class Fix {}\r\n", b"\xff", b"/* Decompiled with CFR */"]:
            with self.subTest(data=data):
                files = self.fixture({"patch/Fix.java": data})
                with self.assertRaises((ValueError, UnicodeDecodeError)):
                    a.audit(files, files.__getitem__)

    def test_symlink_rejected(self):
        files = self.fixture()
        with self.assertRaisesRegex(ValueError, "Symlink"):
            a.audit(files, files.__getitem__, lambda n: "120000")


if __name__ == "__main__":
    unittest.main()
