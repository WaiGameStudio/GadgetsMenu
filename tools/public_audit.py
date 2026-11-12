"""Fail closed on unreviewed files, binaries and known private paths before publication."""
import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_ROOTS = {"upstream", "libs", "src", "build", "gradle", ".idea", ".git"}
PRIVATE_NAMES = {"workspace.json", "overlay-lock.json", "gradlew", "gradlew.bat", "patch/build.py"}
BINARY_SUFFIXES = {".jar", ".class", ".zip", ".bundle", ".iml", ".ipr", ".iws", ".pyc"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def validate_name(name):
    p = PurePosixPath(name)
    require(name and not p.is_absolute() and ".." not in p.parts and "\\" not in name
            and ":" not in name and p.as_posix() == name, "Unsafe public path: " + name)
    require(p.parts[0] not in PRIVATE_ROOTS and name not in PRIVATE_NAMES
            and "build" not in p.parts and "__pycache__" not in p.parts,
            "Private path cannot be published: " + name)
    require(p.suffix.lower() not in BINARY_SUFFIXES, "Binary/private file: " + name)
    require(not name.startswith("docs/") or name in {"docs/README.md", "docs/LICENSE"},
            "Unreviewed documentation/report: " + name)
    require(p.suffix.lower() not in {".md", ".txt", ".rst"} or name.startswith("docs/"),
            "Documentation must be under docs/: " + name)


def validate_content(name, data):
    require(not data.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM: " + name)
    text = data.decode("utf-8", errors="strict")
    require("\r" not in text and "\0" not in text, "Expected LF text: " + name)
    if name.endswith(".java"):
        markers = ["Decompiled with", "Decompiled by", "Could not decompile", "Decompilation failed"]
        require(not any(marker in text for marker in markers), "Recovered source marker: " + name)


def audit(names, read, mode=lambda name: "100644"):
    allowed = json.loads(read("public-files.json").decode("utf-8"))
    require(isinstance(allowed, list) and all(isinstance(n, str) for n in allowed), "Invalid allowlist")
    require(len(allowed) == len(set(allowed)), "Duplicate public path")
    require(set(names) == set(allowed), "Public file set mismatch; extra=" + str(sorted(set(names) - set(allowed)))
            + "; missing=" + str(sorted(set(allowed) - set(names))))
    for name in allowed:
        validate_name(name)
        require(mode(name) in {"100644", "100755"}, "Symlink/submodule not permitted: " + name)
        validate_content(name, read(name))
    return len(allowed)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def audit_git(ref=None):
    if ref:
        lines = git("ls-tree", "-rz", "--full-tree", ref).split(b"\0")
        records = [line.split(b"\t", 1) for line in lines if line]
        modes = {name.decode("utf-8"): info.split()[0].decode() for info, name in records}
        def read(name):
            return git("show", ref + ":" + name)
    else:
        lines = git("ls-files", "--stage", "-z").split(b"\0")
        records = [line.split(b"\t", 1) for line in lines if line]
        require(all(info.split()[2] == b"0" for info, _ in records), "Unmerged index")
        modes = {name.decode("utf-8"): info.split()[0].decode() for info, name in records}
        def read(name):
            return git("show", ":" + name)
    count = audit(modes.keys(), read, modes.get)
    print("PUBLIC_AUDIT_PASS", ref or "index", count, "reviewed text files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--files", action="store_true", help="Check allowlisted working files, NOT Git history")
    mode.add_argument("--ref", help="Check exactly this commit/tree")
    mode.add_argument("--history", action="store_true", help="Audit every commit reachable from local refs")
    args = parser.parse_args()
    if args.files:
        allowed = json.loads((ROOT / "public-files.json").read_text(encoding="utf-8"))
        count = audit(allowed, lambda n: (ROOT / n).read_bytes(),
                      lambda n: "120000" if (ROOT / n).is_symlink() else "100644")
        print("PUBLIC_AUDIT_PASS working allowlist", count, "files (not a Git history check)")
    elif args.history:
        commits = git("rev-list", "--all").decode().splitlines()
        require(commits, "No commits to audit")
        for commit in commits:
            audit_git(commit)
    else:
        audit_git(args.ref)


if __name__ == "__main__":
    main()
