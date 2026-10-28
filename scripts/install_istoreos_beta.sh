#!/bin/sh
# AdZero iStoreOS PUBLIC opt-in beta: exact vendor APKs, strict SHA pins.
# The ordinary installed version remains 0.21.5; the beta tag is deliberately
# non-semver to prevent the stable LuCI updater selecting unverified beta assets.
set -eu
set -f
umask 077
LC_ALL=C; export LC_ALL
TAG='@RELEASE_TAG@'
BASE_URL="https://github.com/slobys/AdZero/releases/download/$TAG"
SHA_X86='@SHA_X86_64@'
SHA_ARMSR='@SHA_ARMSR@'
SHA_R6XS='@SHA_ROCKCHIP_R6XS@'
ROOT=${ADZERO_BETA_TEST_ROOT:-}
LOCAL_DIR=
MODE=menu
ENABLE=0
RISK=0
fail() { printf 'AdZero iStoreOS 测试版：%s\n' "$*" >&2; exit 1; }
say() { printf 'AdZero iStoreOS 测试版：%s\n' "$*"; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --menu) MODE=menu ;;
        --check) MODE=check ;;
        --install) MODE=install ;;
        --uninstall) MODE=uninstall ;;
        --enable) ENABLE=1 ;;
        --accept-network-risk) RISK=1 ;;
        --local-dir) [ "$#" -ge 2 ] || fail '缺少离线目录'; LOCAL_DIR=$2; shift ;;
        *) fail '仅支持 --menu、--check、--install、--uninstall、--enable --accept-network-risk、--local-dir。' ;;
    esac
    shift
done
[ -z "$ROOT" ] || [ "${ADZERO_BETA_TEST_MODE:-}" = 1 ] ||
    fail '禁止修改真实安装的文件系统根目录。'
[ -r "$ROOT/etc/openwrt_release" ] || fail '找不到固件标识文件。'
release_value() {
    awk -v k="$1" 'index($0,k "=")==1 {s=substr($0,length(k)+2); if(s ~ /^".*"$/ || s ~ /^\047.*\047$/) s=substr(s,2,length(s)-2); print s;exit}' "$ROOT/etc/openwrt_release"
}
FW=$(release_value DISTRIB_ID)
VER=$(release_value DISTRIB_RELEASE)
REV=$(release_value DISTRIB_REVISION)
TARGET=$(release_value DISTRIB_TARGET)
ARCH=$(release_value DISTRIB_ARCH)
[ "$FW" = iStoreOS ] || fail "仅支持 iStoreOS，检测到 ${FW:-未知}。"
[ "$VER" = 25.12.6 ] && [ "$REV" = 2026102312 ] ||
    fail "只支持 25.12.6 修订 2026102312；本机 ${VER:-未知}/${REV:-未知}。"
case "$TARGET:$ARCH" in
    x86/64:x86_64)
        PROFILE=x86_64
        BUNDLE=adzero-istoreos-x86_64-beta.tar.gz
        EXPECTED=$SHA_X86 ;;
    armsr/armv8:aarch64_generic)
        PROFILE=armsr
        BUNDLE=adzero-istoreos-armsr-beta.tar.gz
        EXPECTED=$SHA_ARMSR ;;
    rockchip/armv8:aarch64_generic)
        PROFILE=rockchip-r6xs
        BUNDLE=adzero-istoreos-rockchip-r6xs-beta.tar.gz
        EXPECTED=$SHA_R6XS ;;
    *) fail "不支持的厂商 target/ABI：$TARGET / $ARCH。" ;;
esac
case "$EXPECTED" in *[!0-9a-f]*) fail '安装包摘要无效。' ;; esac
[ "${#EXPECTED}" = 64 ] || fail '安装包摘要长度无效。'
if [ "$PROFILE" = rockchip-r6xs ]; then
    board=
    [ ! -r "$ROOT/tmp/sysinfo/board_name" ] || IFS= read -r board < "$ROOT/tmp/sysinfo/board_name" || :
    case "$board" in
        fastrhino,r6xs|lunzn,fastrhino-r66s|lunzn,fastrhino-r68s|fastrhino,r66s|fastrhino,r68s) ;;
        '') fail '缺少官方 R6XS 板型标识，请反馈设备型号核实支持情况。' ;;
        *) fail '非原厂 R6XS 兼容板型，禁止跨设备安装。' ;;
    esac
fi
[ ! -e "$ROOT/usr/lib/opkg/status" ] || fail '存在 OPKG 包数据库，拒绝混用 APK。'
DB="$ROOT/lib/apk/db/installed"
[ -r "$DB" ] || fail '找不到固件 APK 软件包数据库。'
command -v apk >/dev/null 2>&1 || fail '缺少 apk-tools。'
command -v sha256sum >/dev/null 2>&1 || fail '缺少 SHA-256 工具。'
ACTUAL_ARCH=$(apk --print-arch) || fail '无法读取实际 APK CPU 架构。'
case "$PROFILE:$ACTUAL_ARCH" in
    x86_64:x86_64|armsr:aarch64|armsr:aarch64_generic|rockchip-r6xs:aarch64|rockchip-r6xs:aarch64_generic) ;;
    *) fail "固件包 ABI 与 APK CPU 架构 $ACTUAL_ARCH 不匹配。" ;;
esac
for pkg in tcpdump luci-base rpcd; do
    grep -qx "P:$pkg" "$DB" || fail "原系统完整版软件 $pkg 缺失，不尝试替换。"
done
CTL="$ROOT/usr/libexec/adzero/ctl"
MARKDIR="$ROOT/etc/adzero-beta"
MARKER="$MARKDIR/installed"
installed() { grep -qx 'P:luci-app-adzero' "$DB" || [ -e "$ROOT/etc/config/adzero" ] || [ -e "$CTL" ]; }
ensure_root() {
    [ "$(id -u)" -eq 0 ] || [ "${ADZERO_BETA_TEST_MODE:-}" = 1 ] ||
        fail '安装与卸载需以 root SSH 运行。'
}
no_conflict() {
    [ ! -L "$MARKDIR" ] && [ ! -L "$ROOT/etc/config/adzero" ] &&
        [ ! -L "$CTL" ] || fail '已有符号链接管理状态，不尝试覆盖。'
    [ ! -e "$ROOT/tmp/adzero.lock" ] && [ ! -L "$ROOT/tmp/adzero.lock" ] ||
        fail '保护任务操作锁存在，请勿并发安装。'
    [ ! -e "$ROOT/tmp/adzero-install.lock" ] && [ ! -L "$ROOT/tmp/adzero-install.lock" ] ||
        fail '安装任务锁存在，拒绝并发操作。'
    [ ! -e "$ROOT/etc/adzero/managed" ] && [ ! -e "$ROOT/etc/adzero/adapter.json" ] ||
        fail '已有未恢复 DNS/代理管理状态，先关闭原有保护。'
}
confirm() {
    printf '%s [y/N]: ' "$1"
    IFS= read -r answer || return 1
    case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}
risk_confirm() {
    printf '%s' '启用 DNS 广告过滤可能影响代理或内网访问。确认启用请输入 YES: '
    IFS= read -r answer || return 1
    [ "$answer" = YES ]
}
make_temp() {
    command -v mktemp >/dev/null 2>&1 || fail '系统缺少 mktemp。'
    mkdir -p "$ROOT/tmp"
    TMP=$(mktemp -d "$ROOT/tmp/adzero-istoreos-beta.XXXXXXXX") ||
        fail '创建安全临时目录失败。'
    [ -d "$TMP" ] && [ ! -L "$TMP" ] || fail '临时目录异常。'
    trap 'rm -rf "$TMP"' 0
    trap 'exit 130' 1 2 3 15
}
fetch_bundle() {
    if [ -n "$LOCAL_DIR" ]; then
        case "$LOCAL_DIR" in /*) ;; *) fail '离线目录必须使用绝对路径。' ;; esac
        [ -f "$LOCAL_DIR/$BUNDLE" ] && [ ! -L "$LOCAL_DIR/$BUNDLE" ] ||
            fail '该目录没有当前目标的原厂 beta 包。'
        cp "$LOCAL_DIR/$BUNDLE" "$TMP/archive.tar.gz" || fail '复制离线包失败。'
    else
        command -v curl >/dev/null 2>&1 || fail '需要 curl 下载 HTTPS 安装包。'
        curl --fail --location --proto '=https' --proto-redir '=https' \
            --connect-timeout 15 --max-time 200 --output "$TMP/archive.tar.gz" \
            "$BASE_URL/$BUNDLE" || fail '下载失败，网络/DNS 设置均未修改。'
    fi
    sum=$(sha256sum "$TMP/archive.tar.gz")
    [ "${sum%% *}" = "$EXPECTED" ] || fail '原厂安装包 SHA-256 不一致，拒绝安装。'
    tar -tzf "$TMP/archive.tar.gz" > "$TMP/files" || fail '原厂压缩包损坏。'
    [ "$(wc -l < "$TMP/files")" -eq 10 ] || fail '压缩包文件数量异常。'
    while IFS= read -r path; do
        case "$path" in
            manifest.json|profile.tsv|SHA256SUMS) ;;
            packages/*.apk)
                file=${path#packages/}
                case "$file" in ''|.*|*/*|*[!a-zA-Z0-9._+-]*) fail '非法 APK 路径。' ;; esac ;;
            *) fail '压缩包包含不安全或未授权路径。' ;;
        esac
    done < "$TMP/files"
    mkdir "$TMP/package"
    tar -xzf "$TMP/archive.tar.gz" -C "$TMP/package" || fail '压缩包解压失败。'
    for name in manifest.json profile.tsv SHA256SUMS; do
        [ -f "$TMP/package/$name" ] && [ ! -L "$TMP/package/$name" ] ||
            fail '缺少或存在符号链接的发行元数据。'
    done
    (cd "$TMP/package" && sha256sum -c SHA256SUMS >/dev/null) ||
        fail '原厂 APK 和元数据 SHA-256 校验失败。'
    row=$(printf 'istoreos\t25.12.6\t2026102312\t%s\t%s\t%s\tapk' "$TARGET" "$ARCH" "$PROFILE")
    [ "$(cat "$TMP/package/profile.tsv")" = "$row" ] ||
        fail '包 target、revision 或 ABI 与本机固件不匹配。'
    set +f
    set -- "$TMP"/package/packages/*.apk
    set -f
    [ "$#" -eq 7 ] || fail '缺少原厂依赖：应有 1 个 AdZero 与 6 个依赖包。'
    for file do [ -f "$file" ] && [ ! -L "$file" ] || fail '发现非法 APK 文件。'; done
}
simulate() {
    apk --root "${ROOT:-/}" --arch "$ARCH" add --simulate --no-network \
        --repositories-file /dev/null --allow-untrusted "$@" > "$TMP/simulation" 2>&1 ||
        fail 'APK 离线依赖预检失败，系统保持不变。'
    if grep -Eiq '(^|[^a-z])(Removing|Purging|Upgrading|Downgrading|Reinstalling)([^a-z]|$)' "$TMP/simulation"; then
        fail '发现替换、卸载或升级原有系统软件包的风险，拒绝安装。'
    fi
    planned=$(sed -n 's/^([0-9][0-9]*\/[0-9][0-9]*) Installing \([^ ]*\) (.*$/\1/p' "$TMP/simulation")
    has_app=0
    for name in $planned; do
        case "$name" in
            luci-app-adzero) has_app=1 ;;
            adblock-fast|conntrack|coreutils-timeout|libnetfilter-cthelper0|libnetfilter-cttimeout1|libnetfilter-queue1) ;;
            *) fail "依赖解算出现非原厂测试包：$name" ;;
        esac
    done
    [ "$has_app" = 1 ] || fail '预检没有计划安装 AdZero 本体。'
    grep -q 'OK:' "$TMP/simulation" || fail '依赖解算未成功。'
}
preflight() {
    no_conflict
    installed && fail '本机已安装 AdZero，测试版不会擅自覆盖原有安装，请先备份并安全卸载。'
    make_temp
    fetch_bundle
    set +f
    set -- "$TMP"/package/packages/*.apk
    set -f
    simulate "$@"
    say "固件、revision、板型、ABI、哈希与依赖预检通过：$PROFILE，7 个 APK。"
}
run_check() (
    preflight
    say '只读检测成功。未安装软件或修改 DNS/代理。'
)
do_install() (
    ensure_root
    enabled=$1
    preflight
    [ -d "$ROOT/etc/config" ] && [ ! -L "$ROOT/etc/config" ] ||
        fail '配置目录不可用，无法生成备份。'
    mkdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null ||
        fail '并发安装锁存在。'
    trap 'rmdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || :; rm -rf "$TMP"' 0
    [ ! -e "$MARKER" ] && [ ! -L "$MARKER" ] || fail '存在历史测试版标记，拒绝覆盖。'
    [ ! -L "$ROOT/etc/adzero-backups" ] || fail '配置备份父目录是符号链接，拒绝写入。'
    [ ! -L "$MARKDIR" ] || fail '测试版标记目录是符号链接，拒绝写入。'
    stamp=$(date +%Y%m%d-%H%M%S)
    backup="$ROOT/etc/adzero-backups/istoreos-beta-$stamp"
    [ ! -e "$backup" ] && [ ! -L "$backup" ] || fail '相同备份目录已存在。'
    mkdir -p "$backup" "$MARKDIR" || fail '备份目录创建失败。'
    chmod 700 "$ROOT/etc/adzero-backups" "$backup" "$MARKDIR"
    tar -czf "$backup/config.tar.gz" -C "$ROOT/etc" config ||
        fail '配置备份失败，拒绝安装。'
    chmod 600 "$backup/config.tar.gz"
    set +f
    set -- "$TMP"/package/packages/*.apk
    set -f
    say "正在通过离线原厂 APK 安装；已备份配置：$backup。"
    apk --root "${ROOT:-/}" --arch "$ARCH" add --no-network \
        --repositories-file /dev/null --allow-untrusted "$@" ||
        fail '安装失败。请保留配置备份，联系维护者检查原有网络状态。'
    [ -x "$CTL" ] || fail '安装后找不到控制程序，保留备份以便人工修复。'
    printf 'tag=%s\nprofile=%s\ntarget=%s\n' "$TAG" "$PROFILE" "$TARGET" > "$MARKER"
    chmod 600 "$MARKER"
    if [ "$enabled" = 1 ]; then
        if ! "$CTL" enable; then
            "$CTL" disable || :
            fail '主动启用失败，已尝试恢复配置，测试备份保留。'
        fi
        say '已安装并启用。请立即检查 LAN 上网、DNS 和代理状态。'
    else
        # The factory package is installed disabled. Do not call disable
        # just after installation: that can unnecessarily invoke native DNS
        # adapters on a system that has never enabled AdZero.
        if [ -e "$ROOT/etc/adzero/managed" ] || [ -e "$ROOT/etc/adzero/adapter.json" ]; then
            "$CTL" disable || fail '安装后意外发现已接管 DNS 状态且恢复失败；保留备份。'
            fail '安装后发现意外的 DNS 管理状态；已尝试关闭，暂不宣称安装安全。'
        fi
        say '安装成功；未主动启用 DNS 过滤。请在 LuCI 中确认后手动开启。'
    fi
)
do_uninstall() (
    ensure_root
    [ -f "$MARKER" ] && [ ! -L "$MARKER" ] ||
        fail '未找到本测试版安装标记，拒绝卸载其他 AdZero 版本。'
    grep -qx "tag=$TAG" "$MARKER" && grep -qx "profile=$PROFILE" "$MARKER" ||
        fail '安装标记与本机测试版/目标不一致。'
    [ -x "$CTL" ] && [ ! -L "$CTL" ] || fail '控制程序不可用，拒绝卸载。'
    [ ! -e "$ROOT/tmp/adzero.lock" ] && [ ! -L "$ROOT/tmp/adzero.lock" ] ||
        fail '存在保护任务锁，拒绝并发卸载。'
    mkdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || fail '有其他安装任务正在运行。'
    trap 'rmdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || :' 0
    "$CTL" disable || fail '关闭过滤或恢复代理/DNS 失败，拒绝卸载。'
    [ ! -e "$ROOT/etc/adzero/managed" ] && [ ! -e "$ROOT/etc/adzero/adapter.json" ] ||
        fail '仍有未恢复的代理/DNS 状态，拒绝卸载。'
    apk --root "${ROOT:-/}" del luci-app-adzero || fail 'APK 卸载失败，配置备份已保留。'
    rm -f "$MARKER"
    say '安全卸载完成。保留原厂依赖与配置备份，避免影响其他插件。'
)
menu() {
    while :; do
        printf '\n%s\n' '=========== AdZero iStoreOS 公开测试版 ==========='
        printf '发行：%s  固件：%s %s  target=%s\n' "$TAG" "$FW" "$VER" "$TARGET"
        printf '%s\n' ' 1) 只读检测固件/哈希/依赖'
        printf '%s\n' ' 2) 一键安装（默认关闭过滤，推荐）'
        printf '%s\n' ' 3) 安装并启用过滤（有断网风险，需要再次确认）'
        printf '%s\n' ' 4) 安全卸载（恢复 AdZero 管理的配置）'
        printf '%s\n' ' 0) 退出'
        printf '%s' '请输入 [0-4]: '
        IFS= read -r choice || return 0
        case "$choice" in
            1) run_check ;;
            2) if confirm '确认安装 iStoreOS beta？'; then do_install 0; fi ;;
            3) if confirm '确认安装并准备启用 DNS 拦截？' && risk_confirm; then do_install 1; fi ;;
            4) if confirm '确认关闭、恢复并卸载 beta？'; then do_uninstall; fi ;;
            0) return 0 ;;
            *) say '请输入 0 至 4。' ;;
        esac
    done
}
case "$MODE" in
    menu) menu ;;
    check) run_check ;;
    uninstall) do_uninstall ;;
    install)
        [ "$ENABLE" = 0 ] || [ "$RISK" = 1 ] ||
            fail '手动启用过滤需要同时指定 --accept-network-risk。'
        do_install "$ENABLE" ;;
esac
