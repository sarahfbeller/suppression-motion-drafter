#!/usr/bin/env python3
"""Build the website into dist/, ready to upload as static files (e.g. to Cloudflare Pages).

Usage (from the repo root):
    python3 scripts/build_site.py

dist/ gets the page (app/), the engine and content in one bundle.json, and the Pyodide files the
page runs Python with. The site hosts its own copy of Pyodide and python-docx rather than loading
them from a CDN at run time. They're downloaded once into .cache/ and checked against the hashes below.
Standard library only.
"""
import hashlib
import json
import os
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
CACHE = os.path.join(ROOT, ".cache", "site-vendor")

PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/"
# (file name, URL, sha256). The two Pyodide wheels' hashes match its pyodide-lock.json.
VENDOR = [
    ("pyodide.js", PYODIDE + "pyodide.js",
     "c0069107621d5b942a659e737a12e774cc0451feaa2256f475d72e071d844ec7"),
    ("pyodide.asm.js", PYODIDE + "pyodide.asm.js",
     "919560652ed3dad3707cb3a394785da1e046fb13dc0defa162058ff230cb7eed"),
    ("pyodide.asm.wasm", PYODIDE + "pyodide.asm.wasm",
     "b7e66a19427a55010ac3367c1b6c64b893f9826f783412945fdf0c3337f3bc94"),
    ("python_stdlib.zip", PYODIDE + "python_stdlib.zip",
     "72894522b791858b9d613ac786b951d8b5094035dcf376313ea24a466810f336"),
    ("pyodide-lock.json", PYODIDE + "pyodide-lock.json",
     "cd50b49de944c579045e122fe8628b31f9ce446379f032f36c05e273d38766e0"),
    ("lxml-5.2.1-cp312-cp312-pyodide_2024_0_wasm32.whl", PYODIDE + "lxml-5.2.1-cp312-cp312-pyodide_2024_0_wasm32.whl",
     "162c1a8c58fa7da34c2c492b7a572f8d604318d9708f6cd8c3968bfa5fe8a08b"),
    ("typing_extensions-4.11.0-py3-none-any.whl", PYODIDE + "typing_extensions-4.11.0-py3-none-any.whl",
     "696ecd97bd0abc88fc25d376ac06f4233ab16bba3e992c4b37bbc2715240d4e8"),
    ("python_docx-1.2.0-py3-none-any.whl",
     "https://files.pythonhosted.org/packages/d0/00/1e03a4989fa5795da308cd774f05b704ace555a70f9bf9d3be057b680bcf/"
     "python_docx-1.2.0-py3-none-any.whl",
     "3fd478f3250fbbbfd3b94fe1e985955737c145627498896a8a6bf81f4baf66c7"),
]

# GoatCounter's counting script (visit and motion-download counts), pinned to a version and served from
# the site itself. It sends only the page path, title, referrer, and screen size: never anything typed.
COUNTER = ("count.js", "https://gc.zgo.at/count.v5.js",
           "9e4391f5c18cb24de433b6ef31d8b1f1c85ee41c6f0ad274b28664168063725a")

# The Python the page runs, from scripts/.
PYTHON = ["engine.py", "render.py", "docx_render.py", "site_api.py"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def vendor_file(name, url, digest):
    """The cached copy of a vendored file, downloading it the first time."""
    path = os.path.join(CACHE, name)
    if not (os.path.exists(path) and sha256(path) == digest):
        os.makedirs(CACHE, exist_ok=True)
        print(f"downloading {name}")
        tmp = path + ".part"
        with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        got = sha256(tmp)
        if got != digest:
            os.remove(tmp)
            sys.exit(f"{name}: downloaded file's sha256 is {got}, expected {digest}. Not using it.")
        os.replace(tmp, path)
    return path


def bundle():
    """Engine code and content, {repo-relative path: text}, written into Pyodide's file system."""
    out = {}
    for name in PYTHON:
        out[f"scripts/{name}"] = read(os.path.join(ROOT, "scripts", name))
    for folder, _dirs, files in os.walk(os.path.join(ROOT, "content")):
        for name in sorted(files):
            if name.endswith(".json"):
                path = os.path.join(folder, name)
                out[os.path.relpath(path, ROOT)] = read(path)
    return out


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def main():
    app_js = read(os.path.join(ROOT, "app", "app.js"))
    wheel = next(n for n, _u, _d in VENDOR if n.startswith("python_docx"))
    if f'"{wheel}"' not in app_js:
        sys.exit(f"app/app.js doesn't load {wheel}; update DOCX_WHEEL there to match VENDOR here.")

    shutil.rmtree(DIST, ignore_errors=True)
    os.makedirs(os.path.join(DIST, "pyodide"))
    for name, url, digest in VENDOR:
        shutil.copy(vendor_file(name, url, digest), os.path.join(DIST, "pyodide", name))
    shutil.copy(vendor_file("goatcounter-" + COUNTER[0], *COUNTER[1:]), os.path.join(DIST, COUNTER[0]))

    data = json.dumps(bundle(), ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(DIST, "bundle.json"), "w", encoding="utf-8") as f:
        f.write(data)

    # A build id in the page's links, so browsers fetch the new files after an update.
    pages = sorted(n for n in os.listdir(os.path.join(ROOT, "app")) if n.endswith((".html", ".css")))
    page = "".join(read(os.path.join(ROOT, "app", n)) for n in pages)
    build = hashlib.sha256((data + app_js + page).encode()).hexdigest()[:12]
    for name in os.listdir(os.path.join(ROOT, "app")):
        src = os.path.join(ROOT, "app", name)
        if name.endswith(".html"):
            with open(os.path.join(DIST, name), "w", encoding="utf-8") as f:
                f.write(read(src).replace("__BUILD__", build))
        elif os.path.isfile(src):
            shutil.copy(src, os.path.join(DIST, name))

    size = sum(os.path.getsize(os.path.join(d, n)) for d, _s, ns in os.walk(DIST) for n in ns)
    print(f"built dist/ ({size / 1e6:.1f} MB, build {build})")


if __name__ == "__main__":
    main()
