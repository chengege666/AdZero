#!/bin/sh
# OpenWrt + ImmortalWrt ARM64 PUBLIC OPT-IN BETA.
# SHA-pinned SDK build only. Keeps DNS interception DISABLED after first install.
set -eu
set -f
umask 077
LC_ALL=C; export LC_ALL
TAG='@RELEASE_TAG@'
BASE="https://github.com/slobys/AdZero/releases/download/$TAG"
SHA_OPENWRT_ROCKCHIP='@SHA_OPENWRT_ROCKCHIP@'
SHA_OPENWRT_FILOGIC='@SHA_OPENWRT_FILOGIC@'
SHA_IMMORTALWRT_ROCKCHIP='@SHA_IMMORTALWRT_ROCKCHIP@'
SHA_IMMORTALWRT_FILOGIC='@SHA_IMMORTALWRT_FILOGIC@'
ROOT=${ADZERO_ARM64_BETA_TEST_ROOT:-}
[ -z "$ROOT" ] || [ "${ADZERO_ARM64_BETA_TEST_MODE:-}" = 1 ] ||
    { echo 'AdZero ARM64: 不允许重定向真实安装目录。' >&2; exit 1; }
MODE=menu
LOCAL_DIR=
ENABLE=0
RISK=0
fail() { printf 'AdZero ARM64 Beta：%s\n' "$*" >&2; exit 1; }
say() { printf 'AdZero ARM64 Beta：%s\n' "$*"; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --menu) MODE=menu ;;
        --check) MODE=check ;;
        --install) MODE=install ;;
        --uninstall) MODE=uninstall ;;
        --enable) ENABLE=1 ;;
        --accept-network-risk) RISK=1 ;;
        --local-dir) [ "$#" -ge 2 ] || fail '缺少离线发行目录'; LOCAL_DIR=$2; shift ;;
        *) fail '用法: --menu|--check|--install|--uninstall [--enable --accept-network-risk] [--local-dir DIR]' ;;
    esac
    shift
done
[ -r "$ROOT/etc/openwrt_release" ] || fail '找不到 /etc/openwrt_release。'
release_value() {
    awk -v k="$1" 'index($0,k "=")==1 {v=substr($0,length(k)+2);if(v ~ /^".*"$/ || v ~ /^\047.*\047$/)v=substr(v,2,length(v)-2);print v;exit}' "$ROOT/etc/openwrt_release"
}
LABEL=$(release_value DISTRIB_ID)
FW=$(printf '%s' "$LABEL" | tr 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' 'abcdefghijklmnopqrstuvwxyz')
VER=$(release_value DISTRIB_RELEASE)
TARGET=$(release_value DISTRIB_TARGET)
ARCH=$(release_value DISTRIB_ARCH)
case "$FW:$VER:$TARGET:$ARCH" in
    openwrt:25.12.6:rockchip/armv8:aarch64_generic)
        PROFILE=openwrt-rockchip; BUNDLE=adzero-openwrt-rockchip-arm64-beta.tar.gz
        EXPECTED=$SHA_OPENWRT_ROCKCHIP ;;
    openwrt:25.12.6:mediatek/filogic:aarch64_cortex-a53)
        PROFILE=openwrt-filogic; BUNDLE=adzero-openwrt-filogic-arm64-beta.tar.gz
        EXPECTED=$SHA_OPENWRT_FILOGIC ;;
    immortalwrt:25.12.2:rockchip/armv8:aarch64_generic)
        PROFILE=immortalwrt-rockchip; BUNDLE=adzero-immortalwrt-rockchip-arm64-beta.tar.gz
        EXPECTED=$SHA_IMMORTALWRT_ROCKCHIP ;;
    immortalwrt:25.12.2:mediatek/filogic:aarch64_cortex-a53)
        PROFILE=immortalwrt-filogic; BUNDLE=adzero-immortalwrt-filogic-arm64-beta.tar.gz
        EXPECTED=$SHA_IMMORTALWRT_FILOGIC ;;
    *) fail "固件版本/target/架构不在四组公开测试名单：$LABEL $VER $TARGET $ARCH。拒绝跨厂商或跨架构安装。" ;;
esac
case "$EXPECTED" in *[!a-f0-9]*) fail '发行包校验信息无效。' ;; esac
[ "${#EXPECTED}" -eq 64 ] || fail '发行包 SHA-256 无效。'
[ ! -e "$ROOT/usr/lib/opkg/status" ] || fail '此测试版仅支持 APK，不允许 OPKG 混用。'
DB="$ROOT/lib/apk/db/installed"
[ -r "$DB" ] || fail '缺少 /lib/apk/db/installed；当前不是预期的 APK 固件。'
command -v apk >/dev/null 2>&1 || fail '未检测到 apk-tools。'
command -v sha256sum >/dev/null 2>&1 || fail '缺少 sha256sum。'
ACTUAL_ARCH=$(apk --print-arch) || fail '无法查询 APK CPU 架构。'
case "$ARCH:$ACTUAL_ARCH" in
    aarch64_generic:aarch64|aarch64_generic:aarch64_generic|\
    aarch64_cortex-a53:aarch64|aarch64_cortex-a53:aarch64_cortex-a53) ;;
    *) fail "APK 实际架构 $ACTUAL_ARCH 与固件声明 $ARCH 不匹配。" ;;
esac
for essential in luci-base rpcd; do
    grep -qx "P:$essential" "$DB" || fail "未检测到 LuCI 基础组件 $essential。"
done
CTL="$ROOT/usr/libexec/adzero/ctl"
MARKDIR="$ROOT/etc/adzero-arm64-beta"
MARKER="$MARKDIR/installed"
installed() {
    grep -qx 'P:luci-app-adzero' "$DB" ||
        [ -e "$ROOT/etc/config/adzero" ] || [ -e "$CTL" ]
}
read_packages() {
    FEEDS="$ROOT/etc/apk/repositories.d/distfeeds.list"
    [ -f "$FEEDS" ] && [ ! -L "$FEEDS" ] || return 1
    target_count=0
    architecture_count=0
    repo_series=
    # Accept the firmware vendor's own HTTPS repository and USTC's documented
    # mirror of that vendor. Do not modify the user's distfeeds.list.
    # OpenWrt/ImmortalWrt 25.12 may ship '25.12' rolling feeds, or exact
    # patch-version feeds. Never mix versions or accept another patch version.
    while IFS= read -r feed || [ -n "$feed" ]; do
        case "$feed" in ''|'#'*) continue ;; esac
        case "$FW:$feed" in
            openwrt:https://downloads.openwrt.org/releases/*|\
            openwrt:https://mirrors.ustc.edu.cn/openwrt/releases/*|\
            immortalwrt:https://downloads.immortalwrt.org/releases/*|\
            immortalwrt:https://mirrors.ustc.edu.cn/immortalwrt/releases/*) ;;
            *) return 1 ;;
        esac
        suffix=${feed#*/releases/}
        case "$suffix" in
            "$VER"/*) current_series=$VER; relative=${suffix#"$VER"/} ;;
            25.12/*) current_series=25.12; relative=${suffix#25.12/} ;;
            *) return 1 ;;
        esac
        if [ -n "$repo_series" ] && [ "$repo_series" != "$current_series" ]; then
            return 1
        fi
        repo_series=$current_series
        case "$relative" in
            targets/"$TARGET"/packages/packages.adb)
                target_count=$((target_count + 1)) ;;
            targets/"$TARGET"/kmods/*/packages.adb)
                kernel_id=${relative#targets/"$TARGET"/kmods/}
                kernel_id=${kernel_id%/packages.adb}
                case "$kernel_id" in ''|.|..|*/*|*[!a-zA-Z0-9._+-]*) return 1 ;; esac ;;
            packages/"$ARCH"/*/packages.adb)
                category=${relative#packages/"$ARCH"/}
                category=${category%/packages.adb}
                case "$category" in ''|.|..|*/*|*[!a-zA-Z0-9._+-]*) return 1 ;; esac
                architecture_count=$((architecture_count + 1)) ;;
            *) return 1 ;;
        esac
    done < "$FEEDS"
    [ "$target_count" -ge 1 ] && [ "$architecture_count" -ge 1 ]
}
is_installed() { installed; }
ensure_root() {
    [ "$(id -u)" -eq 0 ] || [ "${ADZERO_ARM64_BETA_TEST_MODE:-}" = 1 ] ||
        fail '安装与卸载请以 root 身份运行。'
}
no_conflict() {
    [ ! -L "$MARKDIR" ] && [ ! -L "$ROOT/etc/config/adzero" ] &&
        [ ! -L "$CTL" ] || fail '已有不安全的符号链接安装状态。'
    [ ! -e "$ROOT/tmp/adzero.lock" ] && [ ! -L "$ROOT/tmp/adzero.lock" ] ||
        fail 'AdZero 保护任务锁存在。'
    [ ! -e "$ROOT/tmp/adzero-install.lock" ] && [ ! -L "$ROOT/tmp/adzero-install.lock" ] ||
        fail '安装锁存在。'
    [ ! -e "$ROOT/etc/adzero/managed" ] && [ ! -e "$ROOT/etc/adzero/adapter.json" ] ||
        fail '存在尚未恢复的 DNS/代理管理状态。'
}
confirm() {
    printf '%s [y/N]: ' "$1"
    IFS= read -r reply || return 1
    case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}
confirm_risk() {
    printf '%s' '启用 DNS 过滤可能影响现有代理或局域网访问。确认启用请输入 YES: '
    IFS= read -r reply || return 1
    [ "$reply" = YES ]
}
temporary() {
    command -v mktemp >/dev/null 2>&1 || fail '缺少 mktemp。'
    mkdir -p "$ROOT/tmp"
    TMP=$(mktemp -d "$ROOT/tmp/adzero-arm64-beta.XXXXXXXX") ||
        fail '无法创建临时目录。'
    trap 'rm -rf "$TMP"' 0
    trap 'exit 130' 1 2 3 15
}
fetch_archive() {
    if [ -n "$LOCAL_DIR" ]; then
        case "$LOCAL_DIR" in /*) ;; *) fail '离线目录必须为绝对路径。' ;; esac
        [ -f "$LOCAL_DIR/$BUNDLE" ] && [ ! -L "$LOCAL_DIR/$BUNDLE" ] ||
            fail '离线发行目录缺少本机固件专用 APK 包。'
        cp "$LOCAL_DIR/$BUNDLE" "$TMP/archive.tar.gz" || fail '复制离线包失败。'
    else
        command -v curl >/dev/null 2>&1 || fail 'HTTPS 安装需要 curl，可改用离线安装。'
        curl --fail --location --proto '=https' --proto-redir '=https' \
            --connect-timeout 15 --max-time 200 --output "$TMP/archive.tar.gz" \
            "$BASE/$BUNDLE" || fail 'GitHub 测试版下载失败，系统网络设置未改动。'
    fi
    raw=$(sha256sum "$TMP/archive.tar.gz")
    [ "${raw%% *}" = "$EXPECTED" ] || fail '候选压缩包 SHA-256 不匹配，拒绝安装。'
    tar -tzf "$TMP/archive.tar.gz" > "$TMP/names" || fail '压缩包损坏。'
    [ "$(wc -l < "$TMP/names")" -eq 4 ] || fail '压缩包必须只包含 1 个 APK 与 3 个元数据。'
    while IFS= read -r name; do
        case "$name" in
            manifest.json|profile.tsv|SHA256SUMS|packages/luci-app-adzero-0.21.5-r1.apk) ;;
            *) fail '安装包包含不允许的路径或文件。' ;;
        esac
    done < "$TMP/names"
    mkdir "$TMP/bundle"
    tar -xzf "$TMP/archive.tar.gz" -C "$TMP/bundle" || fail '解压失败。'
    for name in manifest.json profile.tsv SHA256SUMS packages/luci-app-adzero-0.21.5-r1.apk; do
        [ -f "$TMP/bundle/$name" ] && [ ! -L "$TMP/bundle/$name" ] ||
            fail "测试包文件缺失或不安全：$name"
    done
    (cd "$TMP/bundle" && sha256sum -c SHA256SUMS >/dev/null) ||
        fail '测试包内文件 SHA-256 校验失败。'
    expected=$(printf '%s\t%s\t%s\t%s\t%s\tapk' "$FW" "$VER" "$TARGET" "$ARCH" "$PROFILE")
    [ "$(cat "$TMP/bundle/profile.tsv")" = "$expected" ] ||
        fail '固件发行版/target/ABI 与所选 SDK 编译包不一致。'
}
verify_plan() {
    # Use repository package indexes if needed but never replace installed
    # packages, install from unknown vendor feeds, or enable DNS.
    PKG="$TMP/bundle/packages/luci-app-adzero-0.21.5-r1.apk"
    RARGS=
    if apk --root "${ROOT:-/}" --arch "$ARCH" add --simulate --no-network \
        --repositories-file /dev/null --allow-untrusted "$PKG" > "$TMP/plan" 2>&1; then
        LOCAL_ONLY=1
    else
        LOCAL_ONLY=0
        read_packages || fail '原厂软件源非官方、版本/ABI 不匹配或缺失，请恢复官方 distfeeds 后重试。'
        apk --root "${ROOT:-/}" --repositories-file "$FEEDS" update > "$TMP/update.log" 2>&1 ||
            fail '原厂软件仓库索引更新失败；尚未进行软件安装。'
        apk --root "${ROOT:-/}" --arch "$ARCH" --repositories-file "$FEEDS" \
            add --simulate --allow-untrusted "$PKG" > "$TMP/plan" 2>&1 ||
            fail '官方仓库无法提供本固件版本所需依赖；未安装任何软件。'
    fi
    grep -Eiq '(^|[^a-z])(Removing|Purging|Upgrading|Downgrading|Reinstalling)([^a-z]|$)' "$TMP/plan" &&
        fail '安装计划将移除、替换或升级现有系统包，已停止。'
    planned=$(sed -n 's/^([0-9][0-9]*\/[0-9][0-9]*) Installing \([^ ]*\) (.*$/\1/p' "$TMP/plan")
    found=0
    count=0
    for name in $planned; do
        case "$name" in
            luci-app-adzero) found=1 ;;
            *) case "$name" in *[!a-zA-Z0-9_.+-]*|'') fail '依赖包名称不安全。' ;; esac ;;
        esac
        count=$((count+1))
    done
    [ "$found" = 1 ] && [ "$count" -le 30 ] || fail '解算缺少 AdZero 本体或依赖包异常过多。'
    grep -q 'OK:' "$TMP/plan" || fail '依赖模拟没有成功确认。'
    say "官方 SDK APK 已校验；本机预计新安装 $count 个软件包（含 AdZero）。"
}
preflight() {
    no_conflict
    installed && fail '本机已经安装 AdZero，此公测版不自动覆盖旧安装；请先安全卸载并备份。'
    temporary
    fetch_archive
    verify_plan
    say "固件/target/架构/SDK 哈希/依赖检查通过：$FW $VER $TARGET $ARCH。"
}
run_check() (
    preflight
    say '预检完成；未安装软件，也未修改 AdZero 的 DNS/代理配置。'
)
do_install() (
    ensure_root
    enabled=$1
    preflight
    [ -d "$ROOT/etc/config" ] && [ ! -L "$ROOT/etc/config" ] ||
        fail '原有配置目录不安全或不存在。'
    [ ! -L "$ROOT/etc/adzero-backups" ] || fail '配置备份父目录是符号链接。'
    mkdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || fail '并发安装锁存在。'
    trap 'rmdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || :; rm -rf "$TMP"' 0
    [ ! -e "$MARKER" ] && [ ! -L "$MARKER" ] || fail '已有本测试版记录，禁止重复安装。'
    timestamp=$(date +%Y%m%d-%H%M%S)
    backup="$ROOT/etc/adzero-backups/arm64-beta-$timestamp"
    [ ! -e "$backup" ] && [ ! -L "$backup" ] || fail '配置备份路径已被占用。'
    mkdir -p "$backup" "$MARKDIR" || fail '创建配置备份失败。'
    chmod 700 "$ROOT/etc/adzero-backups" "$backup" "$MARKDIR"
    tar -czf "$backup/config.tar.gz" -C "$ROOT/etc" config ||
        fail '配置备份失败；已中止安装。'
    chmod 600 "$backup/config.tar.gz"
    say "已备份原始网络设置。正在安装 $FW SDK 目标包..."
    if [ "$LOCAL_ONLY" = 1 ]; then
        apk --root "${ROOT:-/}" --arch "$ARCH" add --no-network \
            --repositories-file /dev/null --allow-untrusted "$PKG" ||
            fail '离线 APK 安装失败，恢复备份已保留。'
    else
        apk --root "${ROOT:-/}" --arch "$ARCH" --repositories-file "$FEEDS" \
            add --allow-untrusted "$PKG" ||
            fail '官方依赖安装失败，恢复备份已保留。'
    fi
    [ -x "$CTL" ] && [ ! -L "$CTL" ] ||
        fail '安装后未找到 AdZero 控制程序，备份已保留。'
    printf 'tag=%s\nprofile=%s\ntarget=%s\n' "$TAG" "$PROFILE" "$TARGET" > "$MARKER"
    chmod 600 "$MARKER"
    if [ "$enabled" = 1 ]; then
        if ! "$CTL" enable; then
            "$CTL" disable || :
            fail '用户选择启用但保护启动失败；已尝试恢复 DNS 配置，备份保留。'
        fi
        if [ -x "$ROOT/etc/init.d/adzero" ]; then
            "$ROOT/etc/init.d/adzero" enable && "$ROOT/etc/init.d/adzero" start || {
                "$CTL" disable || :
                fail '开机启用或服务启动失败，已尝试撤回保护。'
            }
        fi
        say '已按确认启用过滤。请检查 LAN DNS 和代理是否正常。'
    else
        if [ -e "$ROOT/etc/adzero/managed" ] || [ -e "$ROOT/etc/adzero/adapter.json" ]; then
            "$CTL" disable || :
            fail '安装后意外发现 DNS 管理记录；已尝试恢复，保留备份待核对。'
        fi
        say '一键安装成功；默认不触发 DNS 控制器，请在 LuCI 手动确认后启用。'
    fi
)
do_uninstall() (
    ensure_root
    [ -f "$MARKER" ] && [ ! -L "$MARKER" ] || fail '非本 ARM64 Beta 安装，拒绝卸载。'
    # beta.1 installations remain recoverable from the newer beta.2 menu.
    { grep -Fxq "tag=$TAG" "$MARKER" ||
      grep -Fxq 'tag=v0.21.5-arm64-beta.1' "$MARKER"; } &&
        grep -Fxq "profile=$PROFILE" "$MARKER" &&
        grep -Fxq "target=$TARGET" "$MARKER" ||
        fail '安装记录与当前固件、目标或已知测试版不匹配，拒绝卸载。'
    [ -x "$CTL" ] && [ ! -L "$CTL" ] || fail '控制程序不可用，不能安全卸载。'
    [ ! -e "$ROOT/tmp/adzero.lock" ] && [ ! -L "$ROOT/tmp/adzero.lock" ] ||
        fail '存在 AdZero 保护操作锁，拒绝与运行时配置竞争。'
    mkdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || fail '安装锁存在，稍后重试。'
    trap 'rmdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || :' 0
    "$CTL" disable || fail '关闭过滤与恢复代理/DNS 失败，拒绝卸载。'
    [ ! -e "$ROOT/etc/adzero/managed" ] && [ ! -e "$ROOT/etc/adzero/adapter.json" ] ||
        fail '代理/DNS 所有权尚未完全恢复，停止卸载。'
    apk --root "${ROOT:-/}" del luci-app-adzero ||
        fail 'APK 卸载失败；保留备份和测试版记录。'
    rm -f "$MARKER"
    say 'AdZero 已卸载，保留系统原厂依赖及原始配置备份。'
)
menu() {
    while :; do
        printf '\n%s\n' '============= AdZero OpenWrt / ImmortalWrt ARM64 公测 ============='
        printf '固件：%s %s | target：%s | 测试版：%s\n' "$LABEL" "$VER" "$TARGET" "$TAG"
        printf '%s\n' '  1) 一键检测官方 SDK APK/依赖（不安装）'
        printf '%s\n' '  2) 一键安装（默认不启用过滤）'
        printf '%s\n' '  3) 安装并启用 DNS 过滤（需确认风险）'
        printf '%s\n' '  4) 安全卸载（先恢复 AdZero 管理的网络设置）'
        printf '%s\n' '  0) 退出'
        printf '%s' '请选择 [0-4]: '
        IFS= read -r selected || return 0
        case "$selected" in
            1) run_check ;;
            2) if confirm '确认在当前 ARM64 固件上试装 AdZero？'; then do_install 0; fi ;;
            3) if confirm '确认安装并准备启用 DNS 过滤？' && confirm_risk; then do_install 1; fi ;;
            4) if confirm '确认关闭过滤、恢复并卸载 AdZero？'; then do_uninstall; fi ;;
            0) say '已退出。'; return 0 ;;
            *) say '请输入 0-4。' ;;
        esac
    done
}
case "$MODE" in
    menu) menu ;;
    check) run_check ;;
    uninstall) do_uninstall ;;
    install)
        [ "$ENABLE" = 0 ] || [ "$RISK" = 1 ] ||
            fail '主动启用须同时指定 --enable --accept-network-risk。'
        do_install "$ENABLE" ;;
esac
