#!/usr/bin/env python3
"""Check the configured public default over HTTPS with real rule parsers.

Development/CI only: fresh list download, no router services or UCI changes.
Also runs the pinned adblock-fast 1.2.4-r4 domain filter and sort, using the
OpenWrt BusyBox wrappers when present. This is not a backend lifecycle test.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
from datetime import datetime, timezone

from build_sdk import source_hash

ROOT = Path(__file__).resolve().parents[1]
BACKEND_URL = "https://raw.githubusercontent.com/openwrt/packages/65493e273e4b9cd7014236b69fd6fdc617b88436/net/adblock-fast/files/lib/adblock-fast/adblock-fast.uc"
BACKEND_SHA256 = "19727b189472f380b9791b1fc37c4acdec60eea06650f7d845fea8fafbd49315"
LIMIT = 25_000_000


def default_url():
    rules = (ROOT / "luci-app-adzero/root/usr/libexec/adzero/rules.sh").read_text()
    match = re.search(r"^DEFAULT_RULE_URL=(https://\S+)$", rules, re.M)
    if not match:
        raise ValueError("Missing explicit HTTPS default rule URL")
    return match[1]


def fetch(url, destination):
    subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                    "--proto", "=https", "--proto-redir", "=https",
                    "--connect-timeout", "15", "--max-time", "120",
                    "--max-filesize", str(LIMIT), "--output", str(destination), url],
                   check=True, timeout=130)


def ucode():
    command = shlex.split(os.environ.get("ADZERO_UCODE", ""))
    if not command:
        raise ValueError("Set ADZERO_UCODE to the real OpenWrt interpreter and modules")
    return command


def parse_domains(raw):
    result = subprocess.run(ucode() + [str(ROOT / "scripts/adapter_transform.uc")],
                            input=json.dumps({"operation": "domains", "arguments": [raw, "smartdns.domainset"]}),
                            text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError("Default list rejected by the production domain parser: " + result.stderr)
    return json.loads(result.stdout)


def backend_filter(raw_path, backend_source, directory):
    source = backend_source.read_text()
    start = source.index("const list_formats = {")
    end = source.index("const sym = {", start)
    # Only the pinned, standalone format table is evaluated. Never import or
    # start the backend module (which could write /etc or restart DNS).
    result = subprocess.run(ucode() + ["-e", source[start:end] + "print(list_formats.domains.filter);"],
                            text=True, capture_output=True, check=True)
    filtered = directory / "filtered.txt"
    sorted_path = directory / "sorted.txt"
    with filtered.open("wb") as output:
        subprocess.run(["sed", result.stdout, str(raw_path)], stdout=output, check=True)
    with sorted_path.open("wb") as output:
        subprocess.run(["sort", "-u", str(filtered)], stdout=output, check=True)
    return parse_domains(sorted_path.read_text())


def check_allow_scope(backend_source, directory):
    source = backend_source.read_text()
    start = source.index("\t\tlet sed_content = '';", source.index('// Remove allowed domains'))
    end = source.index('\n\t\tif (sed_content)', start)
    script = subprocess.run(ucode()+['-e', "let all_allowed = 'ads.example';\n"+source[start:end]+"\nprint(sed_content);"],
                            text=True,capture_output=True,check=True).stdout
    path=directory/'allow.sed';path.write_text(script)
    sample='ads.example\nlogin.ads.example\nnotads.example\nother.example\n'
    result=subprocess.run(['sed','-E','-f',str(path)],input=sample,text=True,capture_output=True,check=True)
    if result.stdout != 'notads.example\nother.example\n':
        raise ValueError('Pinned backend allow scope differs from the shared policy')


def main():
    ucode()  # Fail before network activity if the required parser is absent.
    cache = ROOT / "artifacts/upstream"
    cache.mkdir(parents=True, exist_ok=True)
    backend = cache / "adblock-fast-1.2.4-r4.uc"
    if not backend.exists():
        fetch(BACKEND_URL, backend)
    if hashlib.sha256(backend.read_bytes()).hexdigest() != BACKEND_SHA256:
        raise ValueError("Pinned backend source checksum mismatch")
    url = default_url()
    with tempfile.TemporaryDirectory(prefix="adzero-rule-source-") as directory:
        path = Path(directory)
        raw_path = path / "list.txt"
        fetch(url, raw_path)  # Intentionally never reuse a cached rule list.
        raw = raw_path.read_bytes()
        domains = parse_domains(raw.decode("utf-8"))
        if len(domains) < 1000:
            raise ValueError("Unexpectedly small default Light list")
        if backend_filter(raw_path, backend, path) != domains:
            raise ValueError("Backend filtering changed the accepted domain set")
        check_allow_scope(backend,path)
        report = {
            "checked_at": datetime.now(timezone.utc).isoformat(), "url": url,
            "download": "passed", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "domains": len(domains), "production_domain_parser": "passed",
            "backend": "adblock-fast 1.2.4-r4", "backend_source_sha256": BACKEND_SHA256,
            "backend_filter_sort": "passed", "source_sha256": source_hash(ROOT / "luci-app-adzero"),
            "backend_allow_subtree": "passed (actual pinned ucode expression and sed)",
            "scope": "HTTPS download and isolated rule filtering only; no services, UCI, router or LAN execution",
        }
    output = ROOT / "artifacts/runtime/default-rule-source-result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
