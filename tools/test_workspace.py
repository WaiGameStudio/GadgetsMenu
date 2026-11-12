import contextlib
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import workspace as w


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # These classes are ours, not proprietary server code. Compile and execute the added class.
        cls.directory = tempfile.TemporaryDirectory(prefix="workspace-tests-", dir=w.ROOT / "build")
        cls.base = Path(cls.directory.name)
        cls.samples = []
        for i in range(2):
            folder = cls.base / ("java" + str(i))
            folder.mkdir()
            source = folder / "Example.java"
            source.write_text('public class Example { public static int value() { return ' + str(i + 1)
                              + '; } public static int same() { return 7; } }\n', encoding="utf-8")
            w.run([shutil.which("javac"), "-g:none", "-d", folder, source])
            cls.samples.append((folder / "Example.class").read_bytes())
        folder = cls.base / "added"
        folder.mkdir()
        source = folder / "Added.java"
        source.write_text('public class Added { public static void main(String[] args) { '
                          'if (Example.value() != 1) throw new AssertionError(); System.out.println("ADDED_CLASS_PASS"); } }\n',
                          encoding="utf-8")
        w.run([shutil.which("javac"), "-cp", cls.base / "java0", "-d", folder, source])
        cls.added = (folder / "Added.class").read_bytes()
        cls.inventories = []
        for i in range(2):
            jar = cls.base / (str(i) + ".jar")
            with zipfile.ZipFile(jar, "w") as z:
                z.writestr("Example.class", cls.samples[i])
            output = cls.base / (str(i) + ".json")
            w.inventory(jar, output)
            cls.inventories.append(w.read_json(output))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.root = Path(self.temp.name)
        self.old = self.snapshot("old", {"Example.class": self.samples[0], "config.yml": b"enabled: true\n"}, 0)
        w.write_json(self.root / "workspace.json", {"active": "upstream/old"})
        self.lock = {"baselineSha256": w.read_json(self.old / "manifest.json")["sha256"],
                     "watchedEntries": {"Example.class": w.digest(self.samples[0])}}
        w.write_json(self.root / "overlay-lock.json", self.lock)

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, name, entries, inventory):
        folder = self.root / "upstream" / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "artifact.jar", "w") as z:
            for entry, data in entries.items():
                z.writestr(entry, data)
        w.write_json(folder / "manifest.json", {"version": name,
                     "sha256": w.digest((folder / "artifact.jar").read_bytes()),
                     "entries": {n: w.digest(v) for n, v in entries.items()}})
        w.write_json(folder / "classes.json", self.inventories[inventory])
        with zipfile.ZipFile(folder / "sources.jar", "w"):
            pass
        return folder

    def test_same_upstream(self):
        result = w.comparison(self.old, self.old, self.lock)
        self.assertEqual([], result["changed"])
        self.assertEqual([], result["conflicts"])

    def test_method_change_conflict(self):
        new = self.snapshot("new", {"Example.class": self.samples[1]}, 1)
        result = w.comparison(self.old, new, self.lock)
        self.assertEqual(["Example.class"], result["conflicts"])
        self.assertEqual(["value()I"], result["methods"]["Example.class"]["changed"])
        self.assertIn("config.yml", result["removed"])

    def test_resource_add_remove_change(self):
        new = self.snapshot("new", {"config.yml": b"enabled: false\n", "new.txt": b"new"}, 0)
        result = w.comparison(self.old, new, self.lock)
        self.assertEqual(["Example.class"], result["removed"])
        self.assertEqual(["new.txt"], result["added"])
        self.assertEqual(["config.yml"], result["changed"])

    def test_snapshot_tamper_rejected(self):
        with (self.old / "artifact.jar").open("ab") as f:
            f.write(b"tamper")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            w.verify(self.root)

    def test_swapping_active_without_review_rejected(self):
        new = self.snapshot("new", {"Example.class": self.samples[1]}, 1)
        w.write_json(self.root / "workspace.json", {"active": new.relative_to(self.root).as_posix()})
        with self.assertRaisesRegex(ValueError, "without reviewed migration"):
            w.verify(self.root)

    def test_unsafe_zip_paths(self):
        for name in ["../bad", "/absolute", "C:/escape", "a\\b"]:
            with self.assertRaises(ValueError):
                w.safe_name(name)

    def test_duplicate_zip_rejected(self):
        import warnings
        file = self.root / "duplicate.jar"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(file, "w") as z:
                z.writestr("same", b"1")
                z.writestr("same", b"2")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            w.jar_entries(file)

    def test_added_class_resource_roundtrip_and_execution(self):
        classes = self.root / "build/classes/java/main"
        resources = self.root / "build/resources/main"
        classes.mkdir(parents=True)
        resources.mkdir(parents=True)
        (classes / "Added.class").write_bytes(self.added)
        (resources / "local.yml").write_bytes(b"custom: true\n")
        output = self.root / "build/libs/custom.jar"
        result = w.assemble(output, self.root)
        self.assertEqual(["Added.class", "local.yml"], result["added"])
        self.assertEqual([], result["changed"])
        self.assertIn("ADDED_CLASS_PASS", w.run([shutil.which("java"), "-Xverify:all", "-cp", output, "Added"]))
        first = output.read_bytes()
        with patch.object(Path, "replace", side_effect=PermissionError("simulated IDEA JAR lock")):
            w.assemble(output, self.root)
        self.assertEqual(first, output.read_bytes())

    def test_untracked_override_rejected(self):
        path = self.root / "build/resources/main/config.yml"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Untracked replacement"):
            w.assemble(self.root / "build/libs/custom.jar", self.root)

    def test_tracked_override_works(self):
        path = self.root / "build/classes/java/main/Example.class"
        path.parent.mkdir(parents=True)
        path.write_bytes(self.samples[1])
        result = w.assemble(self.root / "build/libs/custom.jar", self.root)
        self.assertEqual(["Example.class"], result["changed"])

    def test_signed_jar_rejected(self):
        folder = self.snapshot("signed", {"META-INF/test.SF": b"signature"}, 0)
        w.write_json(self.root / "workspace.json", {"active": folder.relative_to(self.root).as_posix()})
        w.write_json(self.root / "overlay-lock.json", {"baselineSha256":
                     w.read_json(folder / "manifest.json")["sha256"], "watchedEntries": {}})
        with self.assertRaisesRegex(ValueError, "Signed JAR"):
            w.assemble(self.root / "build/libs/custom.jar", self.root)

    def test_stale_inner_classes_removed(self):
        old = self.snapshot("inner", {"Example.class": self.samples[0], "Example$Old.class": b"old-inner"}, 0)
        m = w.read_json(old / "manifest.json")
        w.write_json(self.root / "workspace.json", {"active": old.relative_to(self.root).as_posix()})
        w.write_json(self.root / "overlay-lock.json", {"baselineSha256": m["sha256"], "watchedEntries": m["entries"]})
        path = self.root / "build/classes/java/main/Example.class"
        path.parent.mkdir(parents=True)
        path.write_bytes(self.samples[1])
        result = w.assemble(self.root / "build/libs/custom.jar", self.root)
        self.assertEqual(["Example$Old.class"], result["removed"])

    def test_activate_requires_exact_review_and_preserves_sources(self):
        new = self.snapshot("new", {"Example.class": self.samples[0], "config.yml": b"changed"}, 0)
        source = self.root / "src/main/java/Local.java"
        source.parent.mkdir(parents=True)
        source.write_text("local work", encoding="utf-8")
        with patch.object(w, "ROOT", self.root), patch.object(w, "verify", lambda: (self.old, w.verify_snapshot(self.old), self.lock)):
            with self.assertRaisesRegex(ValueError, "exact new JAR"):
                w.activate(new, "wrong")
            w.activate(new, w.read_json(new / "manifest.json")["sha256"])
        self.assertEqual(new, w.active(self.root))
        self.assertEqual("local work", source.read_text())
        w.verify(self.root)

    def test_activate_conflict_rejected(self):
        new = self.snapshot("new", {"Example.class": self.samples[1]}, 1)
        with patch.object(w, "ROOT", self.root), patch.object(w, "verify", lambda: (self.old, w.verify_snapshot(self.old), self.lock)):
            with self.assertRaisesRegex(ValueError, "manual source rebase"):
                w.activate(new, w.read_json(new / "manifest.json")["sha256"])
        self.assertEqual(self.old, w.active(self.root))

    def test_new_class_collision_detected(self):
        new = self.snapshot("new", {"Example.class": self.samples[0], "Added.class": self.added}, 0)
        path = self.root / "build/classes/java/main/Added.class"
        path.parent.mkdir(parents=True)
        path.write_bytes(self.added)
        with patch.object(w, "ROOT", self.root), patch.object(w, "verify", lambda: (self.old, w.verify_snapshot(self.old), self.lock)):
            result = w.compare(new)
        self.assertEqual(["Added.class"], result["additionCollisions"])

    def patch_fixture(self):
        entry = w.PATCH_ENTRY
        inner = entry.removesuffix(".class") + "$1.class"
        folder = self.snapshot("method-patch", {entry: self.samples[0], inner: b"inner-retained"}, 0)
        m = w.read_json(folder / "manifest.json")
        w.write_json(self.root / "workspace.json", {"active": folder.relative_to(self.root).as_posix()})
        w.write_json(self.root / "overlay-lock.json", {"baselineSha256": m["sha256"], "watchedEntries": m["entries"]})
        w.write_json(self.root / "patch/baseline.json", {"sha256": m["sha256"], "version": m["version"],
                                                      "watchedEntries": list(m["entries"])})
        donor = self.root / "replacement.class"
        donor.write_bytes(self.samples[1])
        return donor, entry, inner

    def test_method_patch_preserves_inner_classes(self):
        donor, entry, inner = self.patch_fixture()
        output = self.root / "build/libs/patched.jar"
        report = w.assemble(output, self.root, patch_class=donor)
        self.assertEqual([entry], report["changed"])
        self.assertEqual([], report["removed"])
        self.assertEqual(b"inner-retained", w.jar_entries(output)[inner])

    def test_extension_cannot_replace_method_donor(self):
        donor, entry, _ = self.patch_fixture()
        path = self.root / "build/classes/java/main" / entry
        path.parent.mkdir(parents=True)
        path.write_bytes(self.samples[1])
        with self.assertRaisesRegex(ValueError, "collides with method patch"):
            w.assemble(self.root / "build/libs/patched.jar", self.root, patch_class=donor)

    def test_unreviewed_patch_baseline_rejected(self):
        self.patch_fixture()
        spec = w.read_json(self.root / "patch/baseline.json")
        spec["sha256"] = "wrong"
        w.write_json(self.root / "patch/baseline.json", spec)
        with self.assertRaisesRegex(ValueError, "not reviewed"):
            w.verify_patch(self.root)

    def test_bukkit_stub_cannot_be_packaged(self):
        path = self.root / "build/classes/java/main/org/bukkit/Bukkit.class"
        path.parent.mkdir(parents=True)
        path.write_bytes(self.samples[0])
        with self.assertRaisesRegex(ValueError, "Test doubles"):
            w.assemble(self.root / "build/libs/patched.jar", self.root)

    def test_bootstrap_rejects_wrong_jar_before_import(self):
        self.patch_fixture()
        with patch.object(w, "ROOT", self.root), patch.object(w, "import_jar") as importer:
            with self.assertRaisesRegex(ValueError, "Unsupported original"):
                w.bootstrap(self.old / "artifact.jar")
            importer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
