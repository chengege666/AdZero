#!/usr/bin/env python3
"""Inspect genuine SDK IPK/APK payloads without installing or running hooks."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

from build_ipk import payload


def inspect(package, apk_tool=None):
    expected = payload()
    with tempfile.TemporaryDirectory(prefix="adzero-sdk-inspect-") as directory:
        files = {}
        if package.suffix == ".ipk":
            # Official opkg SDK uses a gzip tar container (unlike preview ar).
            with tarfile.open(package) as outer:
                member = next(m for m in outer.getmembers() if m.name.lstrip('./') == 'data.tar.gz')
                data = outer.extractfile(member).read()
            with tarfile.open(fileobj=io.BytesIO(data)) as inner:
                for item in inner.getmembers():
                    if item.isfile():
                        files[item.name.lstrip('./')] = (inner.extractfile(item).read(), item.mode & 0o777)
        else:
            if apk_tool is None:
                raise ValueError("APK inspection requires the actual SDK apk-tools executable")
            subprocess.run([str(apk_tool), "extract", "--allow-untrusted", "--no-chown", "--destination", directory, str(package.resolve())], check=True)
            for item in Path(directory).rglob('*'):
                if item.is_file():
                    files[item.relative_to(directory).as_posix()] = (item.read_bytes(), item.stat().st_mode & 0o777)
        for name, (content, mode) in expected.items():
            if name not in files:
                raise ValueError(f"Missing SDK payload: {name}")
            actual, actual_mode = files[name]
            if actual_mode != mode:
                raise ValueError(f"SDK permission mismatch for {name}: {actual_mode:o}, expected {mode:o}")
            if name.endswith('.js'):
                # LuCI SDK minifies JS. Parse the actual delivered result.
                js = Path(directory) / 'view-check.js'
                js.write_bytes(actual)
                subprocess.run(['node', '--check', str(js)], check=True)
                subprocess.run(['node', str(Path(__file__).resolve().parents[1] / 'tests/test_view.cjs'), str(js)], check=True)
            elif actual != content:
                raise ValueError(f"Stale or transformed SDK runtime source: {name}")
        return {"package": package.name, "payload_files_checked": len(expected),
                "runtime_source_and_modes": "passed", "luci_delivered_js_syntax": "passed",
                "luci_delivered_ui_regressions": "passed",
                "scope": "extraction only, no package installation or lifecycle execution"}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--apk-tool', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.package, args.apk_tool), indent=2))
