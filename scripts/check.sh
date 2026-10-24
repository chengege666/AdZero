#!/bin/sh
# Offline-only checks, safe to run on a development workstation.
set -eu
cd "$(dirname "$0")/.."
command -v python3 >/dev/null 2>&1 || { echo 'python3 required' >&2; exit 1; }
command -v node >/dev/null 2>&1 || { echo 'node required' >&2; exit 1; }

sh -n luci-app-adzero/root/usr/libexec/adzero/ctl
sh -n luci-app-adzero/root/usr/libexec/adzero/probe
sh -n luci-app-adzero/root/usr/libexec/adzero/rules.sh
sh -n luci-app-adzero/root/usr/libexec/adzero/adapter
sh -n luci-app-adzero/root/usr/libexec/adzero/backend
sh -n luci-app-adzero/root/usr/libexec/adzero/watch
sh -n luci-app-adzero/root/usr/libexec/adzero/observe
sh -n luci-app-adzero/root/usr/libexec/adzero/dns-handoff
sh -n luci-app-adzero/root/usr/libexec/adzero/dns-enhance
sh -n luci-app-adzero/root/usr/libexec/adzero/dns-guard
sh -n luci-app-adzero/root/etc/init.d/adzero-dns
sh -n luci-app-adzero/root/usr/libexec/adzero/policy
sh -n luci-app-adzero/root/usr/libexec/adzero/sources
sh -n luci-app-adzero/root/usr/libexec/adzero/job
sh -n luci-app-adzero/root/usr/libexec/adzero/cache-curl/curl
sh -n luci-app-adzero/root/usr/libexec/adzero/routing-data
sh -n luci-app-adzero/root/etc/init.d/adzero
sh -n scripts/install.sh
node --check luci-app-adzero/htdocs/luci-static/resources/view/adzero/overview.js
python3 -m unittest discover -s tests -v
node tests/test_view.cjs
echo 'AdZero offline checks passed; no OpenWrt device or DNS service was touched.'
