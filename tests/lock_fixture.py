"""Use native ucode locks when available, a real Linux flock otherwise."""
from pathlib import Path
import shlex

def install(root, ucode=None):
    path=Path(root)/'bin/kernel-lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    if ucode:
        source=Path(__file__).resolve().parents[1]/'luci-app-adzero/root/usr/libexec/adzero/lock.uc'
        text='#!/bin/sh\nexec '+shlex.join([*ucode,str(source)])+'\n'
    else:
        text='''#!/usr/bin/env python3
import fcntl,sys
try: fcntl.flock(9,fcntl.LOCK_EX|fcntl.LOCK_NB)
except OSError: sys.exit(75)
'''
    path.write_text(text);path.chmod(0o755)
    return str(path)
