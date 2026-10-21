#!/usr/bin/env python3
"""Real Mihomo DNS checks with an isolated, local deterministic upstream (no LAN)."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
from build_sdk import source_hash

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v1.19.32"
# Official GitHub release asset, digest verified before decompression/execution.
SHA256 = "ba3ce607747a07f948fc35780e108a4a7c7f552a38b9bd4d115f313ebcb89c20"
URL = f"https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}/mihomo-linux-amd64-compatible-{VERSION}.gz"


def transform(operation, *arguments):
    command = shlex.split(os.environ["ADZERO_UCODE"])
    result = subprocess.run(command + [str(ROOT / "scripts/adapter_transform.uc")],
                            input=json.dumps({"operation": operation, "arguments": arguments}),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def question(name, kind):
    return struct.pack("!HHHHHH", 1234, 256, 1, 0, 0, 0) + b"".join(bytes([len(s)]) + s.encode() for s in name.split(".")) + b"\0" + struct.pack("!HH", kind, 1)


def recv_exact(stream, length):
    data = b""
    while len(data) < length:
        chunk = stream.recv(length - len(data))
        if not chunk:
            raise OSError("short DNS TCP reply")
        data += chunk
    return data


def query(port, name, kind=1, tcp=False):
    packet = question(name, kind)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        if tcp:
            sock.connect(("127.0.0.1", port))
            sock.sendall(struct.pack("!H", len(packet)) + packet)
            answer = recv_exact(sock, struct.unpack("!H", recv_exact(sock, 2))[0])
        else:
            sock.sendto(packet, ("127.0.0.1", port))
            answer = sock.recv(4096)
    return answer[3] & 15, struct.unpack("!H", answer[6:8])[0]


def main():
    if os.name == "nt" or os.uname().machine != "x86_64":
        raise SystemExit("Use Linux/WSL x86_64")
    cache = ROOT / "artifacts/upstream"
    cache.mkdir(parents=True, exist_ok=True)
    (ROOT / "artifacts/runtime").mkdir(parents=True, exist_ok=True)
    archive = cache / f"mihomo-linux-amd64-compatible-{VERSION}.gz"
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=60) as source:
            archive.write_bytes(source.read(40 * 1024 * 1024))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit("Mihomo release checksum mismatch")
    binary = Path.home() / ".cache/adzero/mihomo" / VERSION / "mihomo"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(gzip.decompress(archive.read_bytes()))
    binary.chmod(0o755)
    results = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
        upstream.bind(("127.0.0.1", 0))
        upstream.settimeout(0.2)
        stop = threading.Event()

        def respond():
            while not stop.is_set():
                try:
                    packet, peer = upstream.recvfrom(4096)
                except socket.timeout:
                    continue
                kind = struct.unpack("!H", packet[-4:-2])[0]
                ip = socket.inet_pton(socket.AF_INET6 if kind == 28 else socket.AF_INET, "2001:db8::9" if kind == 28 else "192.0.2.9")
                answer = packet[:2] + struct.pack("!HHHHH", 0x8180, 1, 1, 0, 0) + packet[12:] + b"\xc0\x0c" + struct.pack("!HHIH", kind, 1, 60, len(ip)) + ip
                upstream.sendto(answer, peer)

        thread = threading.Thread(target=respond, daemon=True)
        thread.start()
        try:
            for mode in ("redir-host", "fake-ip"):
                with tempfile.TemporaryDirectory(prefix="adzero-mihomo-") as directory:
                    home = Path(directory)
                    provider = home / "adzero.txt"
                    provider.write_text("+.ads.adzero.invalid\n")
                    with socket.socket() as temp:
                        temp.bind(("127.0.0.1", 0))
                        port = temp.getsockname()[1]
                    config = {"mode": "rule", "log-level": "error", "dns": {
                        "enable": True, "listen": f"127.0.0.1:{port}", "ipv6": True,
                        "enhanced-mode": mode, "fake-ip-range": "198.18.0.1/16",
                        "default-nameserver": ["127.0.0.1"],
                        "nameserver": [f"udp://127.0.0.1:{upstream.getsockname()[1]}"],
                    }, "rules": ["MATCH,DIRECT"]}
                    config = transform("mihomo", config, str(provider), False)
                    path = home / "config.json"
                    path.write_text(json.dumps(config))
                    check = subprocess.run([str(binary), "-t", "-d", directory, "-f", str(path)], text=True, capture_output=True)
                    if check.returncode:
                        raise RuntimeError(check.stdout + check.stderr)
                    with (home / "core.log").open("w+") as log:
                        process = subprocess.Popen([str(binary), "-d", directory, "-f", str(path)], stdout=log, stderr=log)
                        try:
                            for _ in range(50):
                                try:
                                    query(port, "normal.adzero.invalid")
                                    break
                                except (OSError, TimeoutError):
                                    if process.poll() is not None:
                                        raise RuntimeError((home / "core.log").read_text())
                                    time.sleep(0.1)
                            for tcp in (False, True):
                                for kind in (1, 28):
                                    blocked = query(port, "sub.ads.adzero.invalid", kind, tcp)
                                    normal = query(port, "normal.adzero.invalid", kind, tcp)
                                    row = {"mode": mode, "transport": "tcp" if tcp else "udp", "query": "AAAA" if kind == 28 else "A", "blocked": blocked, "normal": normal}
                                    results.append(row)
                                    if blocked != (3, 0) or normal[0] != 0 or (kind == 1 and not normal[1]):
                                        raise RuntimeError(f"DNS behavior mismatch: {row}")
                        finally:
                            process.terminate()
                            process.wait(timeout=10)
        finally:
            stop.set()
            thread.join(2)
    report = {"core": VERSION, "asset_sha256": SHA256, "checks": results,
              "source_sha256": source_hash(ROOT / 'luci-app-adzero'),
              "scope": "real local core, deterministic loopback upstream; router/LAN not tested"}
    (ROOT / "artifacts/runtime/mihomo-dns-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
