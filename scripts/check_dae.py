#!/usr/bin/env python3
"""Validate the generated DNS syntax with the real dae parser; never run dae."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import urllib.request

from check_dns_core import transform, ROOT
from build_sdk import source_hash

URL = "https://github.com/daeuniverse/dae/releases/download/v2.1.1/dae-linux-x86_64.tar.xz"
SHA256 = "c550af580dc97cc90986260da78c4bf72917f3213c2b5d8b79c45199d9c3dc90"


def main():
    archive = ROOT / "artifacts/upstream/dae-v2.1.1.tar.xz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "artifacts/runtime").mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            archive.write_bytes(response.read(50 * 1024 * 1024))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit("dae archive checksum mismatch")
    binary = Path.home() / ".cache/adzero/dae-check/dae"
    binary.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        members = [m for m in tar.getmembers() if m.name.rstrip("/").endswith("/bin/dae") and m.isfile()]
        if len(members) != 1:
            raise SystemExit("Unexpected dae archive")
        binary.write_bytes(tar.extractfile(members[0]).read())
    binary.chmod(0o755)
    raw = 'upstream { alidns: "udp://127.0.0.1:5353" }\nrouting { request { fallback: alidns } response { fallback: accept } }'
    adapted = transform("dae_dns", raw)
    with tempfile.TemporaryDirectory(prefix="adzero-dae-check-") as directory:
        path = Path(directory)
        domains = ["ads.example", "track.example"] + [f"ads{i}.example" for i in range(1000)]
        (path / "adzero-geosite.dat").write_bytes(base64.b64decode(transform("geosite", domains)))
        dns = adapted
        config = path / "config.dae"
        config.write_text("global { log_level: info }\ndns {" + dns + "}\nrouting { fallback: direct }\n")
        config.chmod(0o600)
        result = subprocess.run([str(binary), "validate", "-c", str(config)], text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        report = {"core": "dae v2.1.1", "asset_sha256": SHA256, "dns_parser_validation": "passed",
                  "source_sha256": source_hash(ROOT / 'luci-app-adzero'), "domains": len(domains),
                  "scope": "real dae parser only; no eBPF, daed API, router or LAN execution"}
        (ROOT / "artifacts/runtime/dae-parser-result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
