"""Prepare the small pinned ucode socket module for isolated native checks."""
from pathlib import Path
import hashlib,io,tarfile,urllib.request
SHA256='4b776b244a346875a399d1b848dd02e8af20e6e2c4d7b4288e1a94f25554b461'
NAME='ucode-mod-socket_2025.07.18~3f64c808-r1_x86_64.ipk'
URL='https://downloads.openwrt.org/releases/24.10.8/packages/x86_64/base/'+NAME
def prepare(root,runtime):
    package=Path(root)/'artifacts/runtime/dns-extras'/NAME
    if not package.exists():
        with urllib.request.urlopen(URL,timeout=30) as r:data=r.read(1048576)
        if hashlib.sha256(data).hexdigest()!=SHA256:raise ValueError('Socket module checksum mismatch')
        package.parent.mkdir(parents=True,exist_ok=True);package.write_bytes(data)
    data=package.read_bytes()
    if hashlib.sha256(data).hexdigest()!=SHA256:raise ValueError('Cached socket module checksum mismatch')
    with tarfile.open(fileobj=io.BytesIO(data)) as outer:
        archive=outer.extractfile(next(m for m in outer if m.name.lstrip('./')=='data.tar.gz')).read()
    with tarfile.open(fileobj=io.BytesIO(archive)) as inner:
        module=next(m for m in inner if m.name.lstrip('./')=='usr/lib/ucode/socket.so')
        (Path(runtime)/'socket.so').write_bytes(inner.extractfile(module).read())
