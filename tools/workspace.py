"""Maintain immutable upstream snapshots and a small, explicitly guarded source overlay."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
PATCH_ENTRY = "com/yapzhenyie/GadgetsMenu/utils/VersionManager.class"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")


def safe_name(name):
    p = PurePosixPath(name)
    require(not p.is_absolute() and ".." not in p.parts and "\\" not in name
            and ":" not in name and name not in ("", "."), "Unsafe ZIP entry: " + name)


def jar_entries(path):
    with zipfile.ZipFile(path) as z:
        require(len(z.namelist()) == len(set(z.namelist())), "Duplicate ZIP entries")
        result = {}
        for item in z.infolist():
            safe_name(item.filename)
            if not item.is_dir():
                result[item.filename] = z.read(item)
        return result


def recaf():
    path = Path(os.environ.get("RECAF_JAR", str(Path(os.environ.get("APPDATA", ".")) / "Recaf/recaf.jar")))
    require(path.is_file(), "Set RECAF_JAR to a Recaf installation containing CFR, ASM and Gson")
    return path.resolve()


def run(command):
    result = subprocess.run([str(x) for x in command], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        output = result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        output = result.stdout.decode("gb18030")
    print(output, end="")
    result.check_returncode()
    return output


def inventory(jar, output):
    classes = ROOT / "tooling/build/classes/java/main"
    require((classes / "local/gadgetsmenu/Inventory.class").is_file(), "Run Gradle :tooling:classes first")
    run([shutil.which("java"), "-cp", os.pathsep.join(map(str, [classes, recaf()])),
         "local.gadgetsmenu.Inventory", jar, output])


def import_jar(jar):
    jar = Path(jar).resolve()
    data = jar.read_bytes()
    entries = jar_entries(jar)
    require("plugin.yml" in entries, "Not a Bukkit plugin JAR")
    match = re.search(r"(?m)^version:\s*['\"]?([^'\"\r\n]+)", entries["plugin.yml"].decode("utf-8"))
    require(match, "Missing plugin version")
    version = match.group(1).strip()
    jar_hash = digest(data)
    folder = ROOT / "upstream" / (re.sub(r"[^A-Za-z0-9._-]", "_", version) + "-" + jar_hash[:12])
    if folder.exists():
        verify_snapshot(folder)
        require(read_json(folder / "manifest.json")["sha256"] == jar_hash, "Snapshot name collision")
        print("Existing immutable snapshot:", folder)
        return folder
    folder.mkdir(parents=True)
    (folder / "artifact.jar").write_bytes(data)
    write_json(folder / "manifest.json", {"version": version, "sha256": jar_hash,
               "entries": {name: digest(value) for name, value in entries.items()}})
    inventory(folder / "artifact.jar", folder / "classes.json")
    print("Imported (not activated):", folder.relative_to(ROOT))
    return folder


def verify_snapshot(folder):
    folder = Path(folder).resolve()
    m = read_json(folder / "manifest.json")
    jar = folder / "artifact.jar"
    require(digest(jar.read_bytes()) == m["sha256"], "Snapshot JAR hash mismatch: " + str(jar))
    require({n: digest(v) for n, v in jar_entries(jar).items()} == m["entries"], "Snapshot entry manifest mismatch")
    return m


def active(root=ROOT):
    require((root / "workspace.json").is_file(), "No baseline. Run Gradle prepareUpstream -PnewJar=<original JAR> first")
    return root / read_json(root / "workspace.json")["active"]


def bootstrap(jar):
    spec = read_json(ROOT / "patch/baseline.json")
    require(digest(Path(jar).read_bytes()) == spec["sha256"],
            "Unsupported original JAR hash; review and port the patch before changing its baseline")
    if (ROOT / "workspace.json").exists() or (ROOT / "overlay-lock.json").exists():
        verify_patch()
        print("Existing baseline retained; no local selection or lock overwritten.")
        return
    folder = import_jar(jar)
    manifest = verify_snapshot(folder)
    require(manifest["version"] == spec["version"], "Unexpected plugin version")
    watched = {name: manifest["entries"][name] for name in spec["watchedEntries"]}
    write_json(ROOT / "overlay-lock.json", {"baselineSha256": spec["sha256"], "watchedEntries": watched})
    write_json(ROOT / "workspace.json", {"active": folder.relative_to(ROOT).as_posix()})
    print("Prepared private baseline. Run Gradle build in a separate invocation.")


def verify_patch(root=ROOT):
    folder, manifest, lock = verify(root)
    spec = read_json(root / "patch/baseline.json")
    require(manifest["sha256"] == spec["sha256"] and manifest["version"] == spec["version"],
            "Patch is not reviewed for this baseline; automatic application refused")
    require(set(spec["watchedEntries"]) <= set(lock["watchedEntries"]), "Missing patch watch entries")
    return folder, manifest, lock


def verify(root=ROOT):
    folder = active(root)
    manifest = verify_snapshot(folder)
    lock = read_json(root / "overlay-lock.json")
    require(lock["baselineSha256"] == manifest["sha256"], "Baseline changed without reviewed migration")
    for name, expected in lock["watchedEntries"].items():
        require(manifest["entries"].get(name) == expected, "Upstream/local conflict: " + name)
    print("Baseline and", len(lock["watchedEntries"]), "watched entries verified.")
    return folder, manifest, lock


def decompile(folder):
    folder = Path(folder).resolve()
    verify_snapshot(folder)
    destination = folder / "sources"
    require(not destination.exists(), "Sources already exist; refusing to overwrite local edits. Use a new snapshot.")
    destination.mkdir()
    output = run([shutil.which("java"), "-Xmx2g", "-cp", recaf(), "org.benf.cfr.reader.Main",
                  folder / "artifact.jar", "--outputdir", destination, "--silent", "true"])
    log = ROOT / "docs/decompilation" / (folder.name + ".txt")
    log.parent.mkdir(parents=True, exist_ok=True)
    failures = []
    for source in destination.rglob("*.java"):
        text = source.read_text(encoding="utf-8-sig")
        source.write_text(text, encoding="utf-8", newline="\n")
        if "Decompilation failed" in text or "Could not decompile" in text:
            failures.append(source.relative_to(destination).as_posix())
    summary = destination / "summary.txt"
    if summary.exists():
        # Decompiler prose is documentation, not project source.
        output += "\n" + summary.read_text(encoding="utf-8")
        summary.unlink()
    classes = read_json(folder / "classes.json")
    missing = []
    for name in classes:
        top_level = name.split("$", 1)[0].removesuffix(".class") + ".java"
        if not (destination / top_level).exists():
            missing.append(name)
    report = {"classFiles": len(classes), "javaFiles": len(list(destination.rglob("*.java"))),
              "missingSourceCoverage": missing, "decompilationFailureMarkers": failures,
              "limitation": "Recovered reference sources, not author source or full compilation equivalence"}
    with zipfile.ZipFile(folder / "sources.jar", "w", zipfile.ZIP_DEFLATED) as z:
        for source in sorted(destination.rglob("*.java")):
            z.writestr(source.relative_to(destination).as_posix(), source.read_bytes())
    for name, value in jar_entries(folder / "artifact.jar").items():
        if not name.endswith(".class"):
            target = folder / "resources" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
    log.write_text(output.replace("\r\n", "\n") + "\n" + json.dumps(report, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    require(not missing and not failures, "Incomplete decompilation: see " + str(log))


def family(name):
    return name.endswith(".class") and name.split("$", 1)[0].removesuffix(".class")


def assemble(output, root=ROOT, patch_class=None):
    folder, manifest, lock = verify(root)
    entries = jar_entries(folder / "artifact.jar")
    require(not any(n.upper().startswith("META-INF/") and n.upper().endswith((".SF", ".RSA", ".DSA", ".EC"))
                    for n in entries), "Signed JAR cannot be merged without a separate signing plan")
    replacements = {}
    for directory in [root / "build/classes/java/main", root / "build/resources/main"]:
        if not directory.exists():
            continue
        for file in directory.rglob("*"):
            if not file.is_file():
                continue
            name = file.relative_to(directory).as_posix()
            safe_name(name)
            require(name not in replacements, "Duplicate overlay entry: " + name)
            require(not name.startswith("org/bukkit/"), "Test doubles must never be packaged")
            if name in entries:
                require(name in lock["watchedEntries"], "Untracked replacement; run track first: " + name)
            replacements[name] = file.read_bytes()
    overlay_families = {family(n) for n in replacements if family(n)}
    removed = [n for n in entries if family(n) in overlay_families and n not in replacements]
    for name in removed:
        require(name in lock["watchedEntries"], "Untracked stale inner-class deletion: " + name)
    if patch_class is not None:
        verify_patch(root)
        require(PATCH_ENTRY not in replacements and family(PATCH_ENTRY) not in overlay_families,
                "Extension collides with method patch; donor and recovered class must not be packaged")
        require(PATCH_ENTRY in lock["watchedEntries"], "Untracked method patch")
        # A method-only patch keeps ALL original inner classes. It is not a source-family replacement.
        replacements[PATCH_ENTRY] = Path(patch_class).read_bytes()
    merged = {n: v for n, v in entries.items() if n not in removed}
    merged.update(replacements)
    output = Path(output).resolve()
    require(root.resolve() in output.parents and output.suffix == ".jar"
            and (root / "build").resolve() in output.parents, "Output must be under workspace build/")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(merged.items()):
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(item, data)
    require(jar_entries(temporary) == merged, "JAR roundtrip mismatch")
    # Do not replace identical artifacts: IDEA may keep the JAR open on Windows.
    if output.is_file() and output.read_bytes() == temporary.read_bytes():
        temporary.unlink()
    else:
        try:
            temporary.replace(output)
        except PermissionError as error:
            raise PermissionError("Output JAR is locked. Previous output was preserved; close its consumer and retry: "
                                  + str(output)) from error
    report = {"baselineSha256": manifest["sha256"], "outputSha256": digest(output.read_bytes()),
              "added": sorted(set(merged) - set(entries)), "removed": sorted(removed),
              "changed": sorted(n for n in set(entries) & set(merged) if entries[n] != merged[n]),
              "unchanged": sum(entries[n] == merged[n] for n in set(entries) & set(merged))}
    write_json(root / "docs/verification/assembly.json", report)
    print("Built", output, json.dumps(report))
    return report


def track(name):
    folder, manifest, lock = verify()
    safe_name(name)
    require(name in manifest["entries"], "Not an upstream entry: " + name)
    names = [n for n in manifest["entries"] if n == name or family(name) and family(n) == family(name)]
    for entry in names:
        lock["watchedEntries"][entry] = manifest["entries"][entry]
    write_json(ROOT / "overlay-lock.json", lock)
    print("Tracked upstream class/resource family:", names)


def checkout(name):
    folder, _, _ = verify()
    safe_name(name)
    if name.endswith(".class"):
        require("$" not in name, "Check out the enclosing top-level class instead")
        relative = name.removesuffix(".class") + ".java"
        source = folder / "sources" / relative
        target = ROOT / "src/main/java" / relative
    else:
        source = folder / "resources" / name
        target = ROOT / "src/main/resources" / name
    require(source.is_file(), "Missing recovered file; decompile the active snapshot first")
    require(not target.exists(), "Local edit already exists; refusing to overwrite: " + str(target))
    track(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    print("Editable copy:", target)


def comparison(old, new, lock):
    a, b = verify_snapshot(old), verify_snapshot(new)
    ai, bi = read_json(old / "classes.json"), read_json(new / "classes.json")
    added = sorted(set(b["entries"]) - set(a["entries"]))
    removed = sorted(set(a["entries"]) - set(b["entries"]))
    changed = sorted(n for n in set(a["entries"]) & set(b["entries"]) if a["entries"][n] != b["entries"][n])
    touched = set(changed + removed)
    conflicts = sorted(touched & set(lock["watchedEntries"]))
    methods = {}
    for name in changed:
        if name not in ai or name not in bi:
            continue
        am, bm = ai[name]["methods"], bi[name]["methods"]
        methods[name] = {"added": sorted(set(bm) - set(am)), "removed": sorted(set(am) - set(bm)),
                         "changed": sorted(n for n in set(am) & set(bm) if am[n] != bm[n]),
                         "normalizedClassChanged": ai[name]["normalizedHash"] != bi[name]["normalizedHash"]}
    return {"oldSha256": a["sha256"], "newSha256": b["sha256"], "added": added, "removed": removed,
            "changed": changed, "methods": methods, "conflicts": conflicts,
            "decision": "manual-rebase-required" if conflicts else "review-and-regression-required",
            "limitation": "No behavioral equivalence claim. Watched entries are explicit, not complete dependency analysis."}


def compare(candidate):
    candidate = Path(candidate).resolve()
    folder, _, lock = verify()
    report = comparison(folder, candidate, lock)
    # Additions may collide with our new classes/resources even if upstream had no old entry.
    local_names = set()
    for directory in [ROOT / "build/classes/java/main", ROOT / "build/resources/main"]:
        if directory.exists():
            local_names.update(p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file())
    report["additionCollisions"] = sorted(set(report["added"]) & local_names)
    if report["additionCollisions"]:
        report["decision"] = "manual-rebase-required"
    path = ROOT / "docs/upgrades" / (folder.name + "--" + candidate.name + ".json")
    write_json(path, report)
    md = path.with_suffix(".md")
    lines = ["# 上游版本差异", "", "- 旧包 SHA-256：`" + report["oldSha256"] + "`",
             "- 新包 SHA-256：`" + report["newSha256"] + "`",
             "- 状态：`" + report["decision"] + "`（不会自动激活）",
             "- 完整类/方法差异见同名 JSON；无冲突不等于功能兼容。", ""]
    for key in ["conflicts", "additionCollisions", "added", "removed", "changed"]:
        lines += ["## " + key, ""] + ["- `" + n + "`" for n in report[key]] + [""]
    md.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    diffs = []
    diff_paths = set()
    for name in report["changed"]:
        relative = (name.split("$", 1)[0].removesuffix(".class") + ".java") if name.endswith(".class") else name
        kind = "sources" if name.endswith(".class") else "resources"
        if (kind, relative) in diff_paths:
            continue
        diff_paths.add((kind, relative))
        left, right = folder / kind / relative, candidate / kind / relative
        if left.is_file() and right.is_file():
            try:
                a, b = left.read_text(encoding="utf-8"), right.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            diffs.extend(difflib.unified_diff(a.splitlines(True), b.splitlines(True),
                         fromfile=folder.name + "/" + relative, tofile=candidate.name + "/" + relative))
    path.with_suffix(".diff").write_text("".join(diffs), encoding="utf-8", newline="\n")
    print("Upgrade report:", path, "decision:", report["decision"])
    return report


def activate(candidate, reviewed_sha256):
    candidate = Path(candidate).resolve()
    require((ROOT / "upstream").resolve() in candidate.parents, "Candidate must be an imported workspace snapshot")
    manifest = verify_snapshot(candidate)
    require(manifest["sha256"] == reviewed_sha256, "Review acknowledgement must match the exact new JAR SHA-256")
    report = compare(candidate)
    require(not report["conflicts"] and not report["additionCollisions"],
            "Conflicts require a manual source rebase; activation refused. No files changed.")
    require((candidate / "sources.jar").is_file(), "Decompile the candidate before activation")
    # Save the old selection and lock for rollback; never rewrite the old snapshots or local sources.
    backup = ROOT / "docs/upgrades" / ("activation-" + manifest["sha256"] + ".json")
    previous = {"workspace": read_json(ROOT / "workspace.json"),
                "overlayLock": read_json(ROOT / "overlay-lock.json")}
    write_json(backup, previous)
    lock = previous["overlayLock"]
    lock["baselineSha256"] = manifest["sha256"]
    write_json(ROOT / "overlay-lock.json", lock)
    write_json(ROOT / "workspace.json", {"active": candidate.relative_to(ROOT).as_posix()})
    print("Activated reviewed snapshot; run Gradle clean build before use. Rollback selection:", backup)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["import", "decompile", "compare", "track", "checkout", "bootstrap"]:
        sub.add_parser(command).add_argument("path")
    activation = sub.add_parser("activate")
    activation.add_argument("path")
    activation.add_argument("--reviewed-sha256", required=True)
    sub.add_parser("verify")
    sub.add_parser("verify-patch")
    sub.add_parser("self-test")
    assembly = sub.add_parser("assemble")
    assembly.add_argument("--output", required=True)
    assembly.add_argument("--patch-class")
    args = parser.parse_args()
    if args.command == "import":
        import_jar(args.path)
    elif args.command == "bootstrap":
        bootstrap(args.path)
    elif args.command == "decompile":
        decompile(args.path)
    elif args.command == "compare":
        report = compare(args.path)
        if report["conflicts"] or report["additionCollisions"]:
            sys.exit(2)
    elif args.command == "track":
        track(args.path)
    elif args.command == "checkout":
        checkout(args.path)
    elif args.command == "activate":
        activate(args.path, args.reviewed_sha256)
    elif args.command == "verify":
        verify()
    elif args.command == "verify-patch":
        verify_patch()
    elif args.command == "assemble":
        assemble(args.output, patch_class=args.patch_class)
    else:
        import unittest
        (ROOT / "build").mkdir(exist_ok=True)
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tools"), pattern="test_*.py")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        sys.exit(not result.wasSuccessful())


if __name__ == "__main__":
    main()
