#!/bin/sh
# Exact, opt-in iStoreOS 24.10.8 OPKG-only experimental install channel.
# No automatic enable, no foreign feed, no live-router operations in --check.
set -eu
set -f
umask 077
LC_ALL=C; export LC_ALL
TAG='@RELEASE_TAG@'
BASE="https://github.com/slobys/AdZero/releases/download/$TAG"
PIN_X86_64='@SHA_X86_64@'
PIN_ARMSR='@SHA_ARMSR@'
PIN_R6XS='@SHA_R6XS@'
ROOT=${ADZERO_24108_TEST_ROOT:-}
[ -z "$ROOT" ] || [ "${ADZERO_24108_TEST_MODE:-}" = 1 ] ||
  { echo "Test-root override forbidden" >&2; exit 1; }
ACTION=menu; ENABLE=0; RISK=0; LOCAL_DIR=
fail() { printf 'AdZero 24.10：%s\n' "$*" >&2; exit 1; }
say() { printf 'AdZero 24.10：%s\n' "$*"; }
while [ "$#" -gt 0 ]; do
 case "$1" in
  --menu) ACTION=menu ;;
  --check) ACTION=check ;;
  --install) ACTION=install ;;
  --uninstall) ACTION=uninstall ;;
  --enable) ENABLE=1 ;;
  --accept-network-risk) RISK=1 ;;
  --local-dir) [ "$#" -ge 2 ] || fail '离线目录缺失'; LOCAL_DIR=$2; shift ;;
  *) fail '只允许 --menu、--check、--install、--uninstall 及相关确认参数' ;;
 esac
 shift
done
release() {
 awk -v k="$1" 'index($0,k "=")==1 {v=substr($0,length(k)+2);
 if(v~/^".*"$/||v~/^\047.*\047$/)v=substr(v,2,length(v)-2);print v;exit}' "$ROOT/etc/openwrt_release"
}
[ -r "$ROOT/etc/openwrt_release" ] && [ ! -L "$ROOT/etc/openwrt_release" ] || fail '缺少固件标识'
FW=$(release DISTRIB_ID)
VER=$(release DISTRIB_RELEASE)
REV=$(release DISTRIB_REVISION)
TARGET=$(release DISTRIB_TARGET)
ARCH=$(release DISTRIB_ARCH)
[ "$FW" = iStoreOS ] && [ "$VER" = 24.10.8 ] && [ "$REV" = 2026073111 ] ||
 fail "仅支持 iStoreOS 24.10.8 修订 2026073111；本机为 $FW $VER $REV"
case "$TARGET:$ARCH" in
 x86/64:x86_64) PROFILE=x86_64; PIN=$PIN_X86_64 ;;
 armsr/armv8:aarch64_generic) PROFILE=armsr; PIN=$PIN_ARMSR ;;
 rockchip/armv8:aarch64_generic) PROFILE=r6xs; PIN=$PIN_R6XS ;;
 *) fail "未验证的设备 target/架构：$TARGET / $ARCH" ;;
esac
case "$PIN" in ''|*[!0-9a-f]*) fail '发行校验摘要无效' ;; esac
[ "${#PIN}" -eq 64 ] || fail '发行校验摘要错误'
[ ! -e "$ROOT/lib/apk/db/installed" ] && [ -r "$ROOT/usr/lib/opkg/status" ] ||
 fail '本测试版只支持 OPKG/IPK，不能混用新版 APK'
command -v opkg >/dev/null 2>&1 || fail '未找到 OPKG'
command -v sha256sum >/dev/null 2>&1 || fail '缺少 SHA-256'
DB="$ROOT/usr/lib/opkg/status"
for pkg in opkg luci-base rpcd tcpdump; do
 grep -qx "Package: $pkg" "$DB" || fail "固件预装组件缺失：$pkg"
done
if [ "$PROFILE" = r6xs ]; then
 boardfile="$ROOT/tmp/sysinfo/board_name"
 [ -f "$boardfile" ] && [ -r "$boardfile" ] && [ ! -L "$boardfile" ] ||
   fail 'Rockchip 板型无法安全确认'
 board=
 IFS= read -r board < "$boardfile" || :
 case "$board" in
  fastrhino,r6xs|lunzn,fastrhino-r66s|lunzn,fastrhino-r68s|fastrhino,r66s|fastrhino,r68s) ;;
  *) fail '不是原厂 R6XS 支持的板型' ;;
 esac
fi
ctl="$ROOT/usr/libexec/adzero/ctl"
markdir="$ROOT/etc/adzero-24108-beta"
marker="$markdir/installed"
bundle="adzero-istoreos-24108-$PROFILE-beta.tar.gz"
installed() {
 grep -qx 'Package: luci-app-adzero' "$DB" || [ -e "$ROOT/etc/config/adzero" ] || [ -e "$ctl" ]
}
no_conflict() {
 [ ! -L "$markdir" ] && [ ! -L "$ROOT/etc/config/adzero" ] && [ ! -L "$ctl" ] ||
  fail '发现安装标记或配置符号链接'
 for f in "$ROOT/tmp/adzero.lock" "$ROOT/tmp/adzero-install.lock" "$ROOT/etc/adzero/managed" "$ROOT/etc/adzero/adapter.json"; do
  [ ! -e "$f" ] && [ ! -L "$f" ] || fail '存在未完成的 AdZero 任务或 DNS/代理管理状态'
 done
}
require_root() {
 [ "$(id -u)" -eq 0 ] || [ "${ADZERO_24108_TEST_MODE:-}" = 1 ] ||
  fail '安装和卸载需 root SSH'
}
confirmation() {
 printf '%s [y/N]: ' "$1"
 IFS= read -r answer || return 1
 case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}
extra_confirmation() {
 printf '启用 DNS 过滤可能影响代理和网络，确认请输入 YES: '
 IFS= read -r answer || return 1
 [ "$answer" = YES ]
}
temporary() {
 command -v mktemp >/dev/null 2>&1 || fail '系统缺少 mktemp'
 mkdir -p "$ROOT/tmp"
 tmp=$(mktemp -d "$ROOT/tmp/adzero24108.XXXXXXXX") || fail '创建临时目录失败'
 trap 'rm -rf "$tmp"' 0
 trap 'exit 130' 1 2 3 15
}
fetch_bundle() {
 if [ -n "$LOCAL_DIR" ]; then
  case "$LOCAL_DIR" in /*) ;; *) fail '离线目录必须为绝对路径' ;; esac
  [ -f "$LOCAL_DIR/$bundle" ] && [ ! -L "$LOCAL_DIR/$bundle" ] || fail '当前固件包缺失'
  cp "$LOCAL_DIR/$bundle" "$tmp/package.tar.gz"
 else
  command -v curl >/dev/null 2>&1 || fail '需要 curl 下载公开测试包'
  curl --fail --location --proto '=https' --proto-redir '=https' --connect-timeout 15 \
   --max-time 180 --output "$tmp/package.tar.gz" "$BASE/$bundle" ||
   fail 'HTTPS 下载失败，没有修改系统'
 fi
 actual=$(sha256sum "$tmp/package.tar.gz")
 [ "${actual%% *}" = "$PIN" ] || fail '下载安装包 SHA-256 校验失败'
 tar -tzf "$tmp/package.tar.gz" > "$tmp/files" || fail '压缩包损坏'
 [ "$(wc -l < "$tmp/files" | awk '{print $1}')" -eq 11 ] ||
   fail '候选包不是 8 个 IPK + 3 个元数据'
 while IFS= read -r entry; do
  case "$entry" in
   manifest.json|profile.tsv|SHA256SUMS) ;;
   packages/*.ipk)
    filename=${entry#packages/}
    case "$filename" in ''|.*|*/*|*[!a-zA-Z0-9._+~-]*) fail 'IPK 路径非法' ;; esac ;;
   *) fail '发现未知压缩包路径，拒绝解压' ;;
  esac
 done < "$tmp/files"
 mkdir "$tmp/unpack"
 tar -xzf "$tmp/package.tar.gz" -C "$tmp/unpack" || fail '无法解压候选包'
 for f in manifest.json profile.tsv SHA256SUMS; do
  [ -f "$tmp/unpack/$f" ] && [ ! -L "$tmp/unpack/$f" ] || fail "元数据异常：$f"
 done
 (cd "$tmp/unpack" && sha256sum -c SHA256SUMS >/dev/null) ||
   fail '候选 IPK 文件哈希不匹配'
 expected=$(printf 'istoreos\t24.10.8\t2026073111\t%s\t%s\t%s\tipk' "$TARGET" "$ARCH" "$PROFILE")
 [ "$(cat "$tmp/unpack/profile.tsv")" = "$expected" ] || fail '候选包固件/架构/修订号不匹配'
 set +f; set -- "$tmp"/unpack/packages/*.ipk; set -f
 [ "$#" -eq 8 ] || fail '候选包必须包含 1 个原生 AdZero + 7 个原厂依赖 IPK'
 for f do [ -f "$f" ] && [ ! -L "$f" ] || fail 'IPK 文件无效'; done
}
plan() {
 # No network feeds, original installed package database remains authoritative.
 # A private OPKG config prevents accidentally using stale/foreign feeds.
 # The correct root and package architectures are essential for the real
 # firmware solver to identify installed packages and accept target IPKs.
 mkdir -p "$tmp/lists"
 printf 'dest root %s\nlists_dir ext %s\narch all 1\narch %s 10\n' \
   "${ROOT:-/}" "$tmp/lists" "$ARCH" > "$tmp/offline.conf"
 before=$(sha256sum "$DB")
 opkg -f "$tmp/offline.conf" --noaction install "$@" > "$tmp/plan.log" 2>&1 ||
  fail '原厂 OPKG 模拟失败，拒绝安装'
 after=$(sha256sum "$DB")
 [ "$before" = "$after" ] || fail 'OPKG 模拟改变了系统软件包数据库'
 if grep -Eiq '(Upgrading|Downgrading|Removing|Reinstalling|Conflicting|force-depends)' "$tmp/plan.log"; then
  fail '模拟将替换/升级/删除系统原包，拒绝操作'
 fi
 grep -Eq 'Installing (luci-app-adzero|package luci-app-adzero)' "$tmp/plan.log" ||
  fail '模拟未确认安装 AdZero'
 say 'OPKG 无网络模拟成功；未修改系统'
}
preflight() {
 no_conflict
 installed && fail '已有 AdZero，不能覆盖原有版本'
 temporary
 fetch_bundle
 set +f; set -- "$tmp"/unpack/packages/*.ipk; set -f
 plan "$@"
}
run_check() (
 preflight
 say '仅检查固件、安装包与依赖，未执行安装或改动 DNS'
)
do_install() (
 require_root
 enabled=$1
 preflight
 [ -d "$ROOT/etc/config" ] && [ ! -L "$ROOT/etc/config" ] &&
   [ ! -L "$ROOT/etc/adzero-backups" ] || fail '配置目录异常，无法安全备份'
 mkdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || fail '其他安装任务正在运行'
 trap 'rmdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || :; rm -rf "$tmp"' 0
 [ ! -e "$marker" ] && [ ! -L "$marker" ] || fail '已有测试版安装记录'
 backup="$ROOT/etc/adzero-backups/istoreos-24108-$(date +%Y%m%d-%H%M%S)"
 [ ! -e "$backup" ] && [ ! -L "$backup" ] || fail '备份目录已被占用'
 mkdir -p "$backup" "$markdir" || fail '无法创建配置备份'
 chmod 700 "$ROOT/etc/adzero-backups" "$backup" "$markdir"
 tar -czf "$backup/config.tar.gz" -C "$ROOT/etc" config || fail '备份失败，拒绝安装'
 chmod 600 "$backup/config.tar.gz"
 set +f; set -- "$tmp"/unpack/packages/*.ipk; set -f
 say '正在离线安装，已保存原路由器配置备份'
 opkg -f "$tmp/offline.conf" install "$@" || fail '安装失败，备份已保留'
 [ -x "$ctl" ] && [ ! -L "$ctl" ] || fail '安装后控制器不可用，保留配置备份'
 printf 'tag=%s\nprofile=%s\ntarget=%s\n' "$TAG" "$PROFILE" "$TARGET" > "$marker"
 chmod 600 "$marker"
 if [ "$enabled" -eq 1 ]; then
  if ! "$ctl" enable; then "$ctl" disable || :; fail '过滤启动失败，已尝试恢复'; fi
  if [ -x "$ROOT/etc/init.d/adzero" ]; then
   "$ROOT/etc/init.d/adzero" enable && "$ROOT/etc/init.d/adzero" start ||
    { "$ctl" disable || :; fail '服务启动失败，尝试撤回 DNS 修改'; }
  fi
  say '已按确认开启；请检查 LAN DNS 和代理'
 else
  [ ! -e "$ROOT/etc/adzero/managed" ] && [ ! -e "$ROOT/etc/adzero/adapter.json" ] ||
   { "$ctl" disable || :; fail '检测到意外的 DNS 管理状态'; }
  say '安装完成，默认关闭 DNS 广告过滤'
 fi
)
do_uninstall() (
 require_root
 [ -f "$marker" ] && [ ! -L "$marker" ] &&
  grep -Fxq "tag=$TAG" "$marker" &&
  grep -Fxq "profile=$PROFILE" "$marker" &&
  grep -Fxq "target=$TARGET" "$marker" || fail '不是本 Beta 的安装记录'
 [ -x "$ctl" ] && [ ! -L "$ctl" ] || fail '无法安全执行恢复'
 [ ! -e "$ROOT/tmp/adzero.lock" ] || fail '保护任务进行中'
 mkdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || fail '安装任务锁存在'
 trap 'rmdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || :' 0
 "$ctl" disable || fail '无法恢复 DNS/代理，拒绝卸载'
 [ ! -e "$ROOT/etc/adzero/managed" ] && [ ! -e "$ROOT/etc/adzero/adapter.json" ] ||
  fail 'DNS/代理配置仍未完全恢复'
 opkg remove luci-app-adzero || fail '原厂 OPKG 卸载失败，备份已保留'
 rm -f "$marker"
 say '已安全卸载，保留原系统依赖与备份'
)
menu() {
 while :; do
  printf '\n%s\n' '========= AdZero iStoreOS 24.10.8 实验 Beta ========='
  printf '固件：%s %s 修订 %s，target=%s\n' "$FW" "$VER" "$REV" "$TARGET"
  printf '%s\n' '1) 只读兼容检查' '2) 一键安装（默认不启用过滤）' '3) 安装并启用过滤（需确认风险）' '4) 安全恢复卸载' '0) 退出'
  printf '请选择 [0-4]: '
  IFS= read -r selection || return 0
  case "$selection" in
   1) run_check ;;
   2) if confirmation '确认在测试设备上安装？'; then do_install 0; fi ;;
   3) if confirmation '确认安装并准备启用 DNS 过滤？' && extra_confirmation; then do_install 1; fi ;;
   4) if confirmation '确认关闭并恢复后卸载？'; then do_uninstall; fi ;;
   0) return 0 ;;
   *) say '请选择 0 到 4' ;;
  esac
 done
}
case "$ACTION" in
 menu) menu ;;
 check) run_check ;;
 uninstall) do_uninstall ;;
 install)
  [ "$ENABLE" = 0 ] || [ "$RISK" = 1 ] || fail '启用需要 --accept-network-risk'
  do_install "$ENABLE" ;;
esac
