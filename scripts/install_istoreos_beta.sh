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
        --status) MODE=status ;;
        --install) MODE=install ;;
        --uninstall) MODE=uninstall ;;
        --enable) ENABLE=1 ;;
        --accept-network-risk) RISK=1 ;;
        --local-dir) [ "$#" -ge 2 ] || fail '缺少离线目录'; LOCAL_DIR=$2; shift ;;
        *) fail '仅支持 --menu、--status、--check、--install、--uninstall、--enable --accept-network-risk、--local-dir。' ;;
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
    board_file="$ROOT/tmp/sysinfo/board_name"
    [ -r "$board_file" ] && [ -f "$board_file" ] && [ ! -L "$board_file" ] ||
        fail 'R6XS 原厂板型标识不可用或是符号链接，拒绝安装。'
    IFS= read -r board < "$board_file" || :
    case "$board" in
        fastrhino,r6xs|lunzn,fastrhino-r66s|lunzn,fastrhino-r68s|fastrhino,r66s|fastrhino,r68s) ;;
        '') fail '缺少官方 R6XS 板型标识，请反馈设备型号核实支持情况。' ;;
        *) fail '非原厂 R6XS 兼容板型，禁止跨设备安装。' ;;
    esac
fi
# An inactive OPKG status file is not evidence that OPKG is still running.
# APK's own installed-inventory query works even with overlayfs DB relocation.
command -v apk >/dev/null 2>&1 || fail '缺少 apk-tools。'
command -v sha256sum >/dev/null 2>&1 || fail '缺少 SHA-256 工具。'
ACTUAL_ARCH=$(apk --print-arch) || fail '无法读取实际 APK CPU 架构。'
case "$PROFILE:$ACTUAL_ARCH" in
    x86_64:x86_64|armsr:aarch64|armsr:aarch64_generic|rockchip-r6xs:aarch64|rockchip-r6xs:aarch64_generic) ;;
    *) fail "固件包 ABI 与 APK CPU 架构 $ACTUAL_ARCH 不匹配。" ;;
esac
for pkg in base-files tcpdump luci-base rpcd; do
    apk --root "${ROOT:-/}" --arch "$ARCH" info -e "$pkg" >/dev/null 2>&1 ||
        fail "APK 已安装包查询未确认原厂组件 $pkg；拒绝替换系统依赖。"
done
CTL="$ROOT/usr/libexec/adzero/ctl"
MARKDIR="$ROOT/etc/adzero-beta"
MARKER="$MARKDIR/installed"
REMOVED="$MARKDIR/removed"
CONFIG="$ROOT/etc/config/adzero"
apk_installed() {
    apk --root "${ROOT:-/}" --arch "$ARCH" info -e luci-app-adzero >/dev/null 2>&1
}
app_version() {
    # APK 3.0.5 "info -v" means verbose DESCRIPTION, not package version.
    # list --manifest returns exactly "name version" for installed packages.
    manifest=$(apk --root "${ROOT:-/}" --arch "$ARCH" list --installed --manifest luci-app-adzero 2>/dev/null) ||
        return 1
    printf '%s\n' "$manifest" |
        awk '$1=="luci-app-adzero" && NF==2 && $2 ~ /^[0-9][0-9A-Za-z.+_~-]*$/ {v=$2; n++}
             END {if(n==1) print v; else exit 1}'
}
known_tag() {
    case "$1" in
        "$TAG"|v0.21.5-istoreos-beta.1|v0.21.5-istoreos-beta.2|v0.21.5-istoreos-beta.3) return 0 ;;
        *) return 1 ;;
    esac
}
trusted_record() {
    file=$1
    [ -f "$file" ] && [ ! -L "$file" ] || return 1
    grep -Fxq "profile=$PROFILE" "$file" &&
        grep -Fxq "target=$TARGET" "$file" || return 1
    tag_line=$(sed -n 's/^tag=//p' "$file")
    [ -n "$tag_line" ] && known_tag "$tag_line"
}
owned_app() {
    # No marker means no beta ownership. Only the native APK's own file
    # inventory can authorize a migration/uninstall, never an orphan UCI file.
    apk_installed || return 1
    [ -f "$CONFIG" ] && [ ! -L "$CONFIG" ] &&
        [ -x "$CTL" ] && [ ! -L "$CTL" ] || return 1
    owner=$(apk --root "${ROOT:-/}" --arch "$ARCH" info -W /usr/libexec/adzero/ctl 2>/dev/null) || return 1
    # Require the exact package-ownership statement, not a substring that
    # could appear in an unrelated diagnostic or "not owned by" message.
    case "$owner" in
        "/usr/libexec/adzero/ctl is owned by luci-app-adzero-"[0-9]*)
            case "$owner" in
                *'
'*) return 1 ;;
                *) return 0 ;;
            esac ;;
        *) return 1 ;;
    esac
}
install_state() {
    # Output is a controlled state token, not untrusted user configuration.
    if [ -e "$MARKER" ] || [ -L "$MARKER" ]; then
        if trusted_record "$MARKER" && owned_app; then echo beta; else echo blocked; fi
    elif apk_installed; then
        if owned_app; then echo legacy; else echo blocked; fi
    elif [ -e "$CTL" ] || [ -L "$CTL" ] ||
         [ -e "$CONFIG" ] || [ -L "$CONFIG" ]; then
        if trusted_record "$REMOVED" && [ ! -e "$CTL" ] && [ ! -L "$CTL" ]; then
            echo residual
        else
            echo blocked
        fi
    else
        echo fresh
    fi
}
show_status() {
    state=$(install_state)
    printf 'AdZero 本机检查：固件 %s / %s，目标 %s\n' "$VER" "$REV" "$TARGET"
    if apk_installed; then
        version=$(app_version) || version=
        printf 'APK 软件包：已安装，版本 %s\n' "${version:-无法确认}"
    else
        say 'APK 软件包：未安装'
    fi
    case "$state" in
        beta) say '安装来源：已记录的 iStoreOS Beta；可用菜单 4 安全卸载，重复安装无须执行。' ;;
        legacy) say '安装来源：已有 APK 安装，但无 Beta 标记。可选 2 安全修复，或 4 备份并卸载旧版。' ;;
        residual) say '安装来源：此前由本助手安全卸载，保留原配置；可选 2 重新安装。' ;;
        fresh) say '安装来源：未安装；可选 2 一键安装。' ;;
        *) say '安装状态：不完整、来源冲突或文件不属于 AdZero APK；已禁止自动修改，请保留现场。' ;;
    esac
    if [ -e "$ROOT/etc/adzero/managed" ] || [ -e "$ROOT/etc/adzero/adapter.json" ]; then
        say '网络状态：检测到旧版 DNS/代理管理记录；安装时必须先安全恢复。'
    else
        say '网络状态：未发现 AdZero 接管记录（不等于 LAN 已完成测试）。'
    fi
    say '以上为只读判断，没有修改网络或配置。'
}
ensure_root() {
    [ "$(id -u)" -eq 0 ] || [ "${ADZERO_BETA_TEST_MODE:-}" = 1 ] ||
        fail '安装与卸载需以 root SSH 运行。'
}
no_conflict() {
    [ ! -L "$MARKDIR" ] && [ ! -L "$CONFIG" ] && [ ! -L "$CTL" ] &&
        [ ! -L "$MARKER" ] && [ ! -L "$REMOVED" ] &&
        [ ! -L "$ROOT/etc/adzero" ] &&
        [ ! -L "$ROOT/etc/adzero/managed" ] &&
        [ ! -L "$ROOT/etc/adzero/adapter.json" ] ||
        fail '存在符号链接管理状态，拒绝自动修改。'
    [ ! -e "$ROOT/tmp/adzero.lock" ] && [ ! -L "$ROOT/tmp/adzero.lock" ] ||
        fail '保护任务操作锁存在，请勿并发安装。'
    [ ! -e "$ROOT/tmp/adzero-install.lock" ] && [ ! -L "$ROOT/tmp/adzero-install.lock" ] ||
        fail '安装任务锁存在，拒绝并发操作。'
    # Old protection may still be active. Read-only checks may inspect it,
    # but the installing transaction must restore it *after* making a backup.
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
simulate_reinstall() {
    apk --root "${ROOT:-/}" --arch "$ARCH" add --simulate --force-reinstall \
        --no-network --repositories-file /dev/null --allow-untrusted \
        "$TMP/package/packages/luci-app-adzero-0.21.5-r1.apk" > "$TMP/simulation" 2>&1 ||
        fail '已安装版本的离线安全修复预检失败；没有修改系统，可通过菜单 4 安全卸载旧版。'
    # The only permitted mutation is reinstallation of AdZero itself.
    grep -Eq '^\([0-9]+/[0-9]+\) Reinstalling luci-app-adzero \(' "$TMP/simulation" ||
        fail 'APK 未确认只重新安装 AdZero，拒绝自动接管旧版。'
    if grep -E '^\([0-9]+/[0-9]+\) (Installing|Reinstalling|Upgrading|Downgrading|Removing|Purging) ' "$TMP/simulation" |
        grep -Ev '^\([0-9]+/[0-9]+\) Reinstalling luci-app-adzero \(' | grep -q .; then
        fail 'APK 预检还要改动其他软件包，拒绝自动迁移。'
    fi
    grep -q 'OK:' "$TMP/simulation" || fail 'APK 安全修复未返回成功确认。'
}
preflight() {
    no_conflict
    KIND=$(install_state)
    case "$KIND" in
        beta)
            say '本机已安装已登记的 AdZero Beta；不会重复覆盖，现有配置保留。'
            return 0 ;;
        legacy)
            existing_version=$(app_version) || existing_version=
            [ "$existing_version" = 0.21.5-r1 ] ||
                fail "已安装旧版 AdZero（${existing_version:-无法确认版本}），不强制跨版本覆盖。可用菜单 4 自动备份、安全卸载后再选 2 安装。"
            KIND=reinstall ;;
        residual|fresh)
            [ ! -e "$ROOT/etc/adzero/managed" ] &&
                [ ! -e "$ROOT/etc/adzero/adapter.json" ] ||
                fail '不存在 APK 本体却残留 DNS/代理管理记录，拒绝安装，避免断网。'
            KIND=fresh ;;
        *) fail '已有 AdZero 的 APK 归属/安装标记或配置不完整；拒绝覆盖，请使用菜单 5 查看状态。' ;;
    esac
    make_temp
    fetch_bundle
    if [ "$KIND" = reinstall ]; then
        simulate_reinstall
        say '已核对旧版 APK 所有权与完整发行包，允许只重装 AdZero 本体；不会重装其他系统依赖。'
    else
        set +f
        set -- "$TMP"/package/packages/*.apk
        set -f
        simulate "$@"
        say "固件、revision、板型、ABI、哈希与依赖预检通过：$PROFILE，7 个 APK。"
    fi
}
run_check() (
    preflight
    if [ "$KIND" = beta ]; then
        say '只读检查确认了现有 Beta 的 APK 归属和标记；未重新下载或校验发行包。'
    else
        say '只读发行包与依赖检测成功；没有安装、卸载或修改 DNS/代理。'
    fi
)
save_backup() {
    [ -d "$ROOT/etc/config" ] && [ ! -L "$ROOT/etc/config" ] &&
        [ ! -L "$ROOT/etc/adzero-backups" ] && [ ! -L "$MARKDIR" ] ||
        fail '配置或备份目录异常，无法安全备份。'
    mkdir -p "$ROOT/etc/adzero-backups" "$MARKDIR" || fail '无法创建安全备份父目录。'
    chmod 700 "$ROOT/etc/adzero-backups" "$MARKDIR"
    backup=$(mktemp -d "$ROOT/etc/adzero-backups/istoreos-beta-$(date +%Y%m%d-%H%M%S).XXXXXXXX") ||
        fail '无法创建独立备份目录，拒绝继续。'
    chmod 700 "$backup"
    tar -czf "$backup/config.tar.gz" -C "$ROOT/etc" config ||
        fail '保存原配置失败，未触碰网络设置。'
    if [ -d "$ROOT/etc/adzero" ]; then
        [ ! -L "$ROOT/etc/adzero" ] || fail '旧版状态目录为符号链接，拒绝操作。'
        tar -czf "$backup/state.tar.gz" -C "$ROOT/etc" adzero ||
            fail '备份旧版恢复记录失败。'
        chmod 600 "$backup/state.tar.gz"
    fi
    chmod 600 "$backup/config.tar.gz"
    say "原配置已安全备份：$backup"
}
do_install() (
    ensure_root
    enabled=$1
    preflight
    if [ "$KIND" = beta ]; then
        say '无需重复安装；当前 Beta 的卸载/管理入口已可使用。'
        exit 0
    fi
    mkdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || fail '已有安装任务正在运行。'
    trap 'rmdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || :; rm -rf "$TMP"' 0
    # Recheck after acquiring the mutation lock. We do not adopt an app
    # appearing between the read-only simulation and the actual operation.
    now=$(install_state)
    case "$KIND:$now" in
        reinstall:legacy|fresh:fresh|fresh:residual) ;;
        *) fail '预检后系统安装状态发生变化，拒绝继续操作。' ;;
    esac
    save_backup
    if [ "$KIND" = reinstall ]; then
        say '检测到无 Beta 标记的旧版 APK；先关闭并恢复旧版 DNS/代理，再仅重装同版本 AdZero。'
        "$CTL" disable ||
            fail '旧版恢复 DNS/代理失败；未重新安装。备份已保留，防止断网。'
        [ ! -e "$ROOT/etc/adzero/managed" ] &&
            [ ! -e "$ROOT/etc/adzero/adapter.json" ] ||
            fail '旧版 DNS/代理接管记录未清除，已停止迁移并保留备份。'
        apk --root "${ROOT:-/}" --arch "$ARCH" add --force-reinstall --no-network \
            --repositories-file /dev/null --allow-untrusted \
            "$TMP/package/packages/luci-app-adzero-0.21.5-r1.apk" ||
            fail '本地安全重装失败；不会强制删除旧版，请保留备份与 APK 状态。'
    else
        set +f
        set -- "$TMP"/package/packages/*.apk
        set -f
        say '正在从已经校验的原厂 APK 离线安装。'
        apk --root "${ROOT:-/}" --arch "$ARCH" add --no-network \
            --repositories-file /dev/null --allow-untrusted "$@" ||
            fail 'APK 安装失败，配置备份已保留。'
    fi
    apk_installed && owned_app ||
        fail '安装后未确认 AdZero 的 APK 软件包、控制文件归属和配置完整，保留备份。'
    [ ! -e "$MARKER" ] && [ ! -L "$MARKER" ] || fail '安装记录冲突，保留备份。'
    mark_tmp=$(mktemp "$MARKDIR/.installed.XXXXXXXX") ||
        fail '无法创建安全的 Beta 记录临时文件，配置备份保留。'
    printf 'tag=%s\nprofile=%s\ntarget=%s\n' "$TAG" "$PROFILE" "$TARGET" > "$mark_tmp"
    chmod 600 "$mark_tmp"
    mv "$mark_tmp" "$MARKER" || fail '写入 Beta 来源记录失败，保留备份。'
    if [ "$enabled" = 1 ]; then
        if ! "$CTL" enable; then
            "$CTL" disable || :
            fail '主动启用失败，已尝试恢复配置，测试备份保留。'
        fi
        if [ -x "$ROOT/etc/init.d/adzero" ]; then
            if ! "$ROOT/etc/init.d/adzero" enable || ! "$ROOT/etc/init.d/adzero" start; then
                "$CTL" disable || :
                fail '开机启用或启动服务失败，已尝试撤回保护；请检查配置备份。'
            fi
        fi
        say '已安装并按确认启用，请检查 LAN 上网、DNS 和代理状态。'
    else
        if [ -e "$ROOT/etc/adzero/managed" ] || [ -e "$ROOT/etc/adzero/adapter.json" ]; then
            "$CTL" disable || fail '安装后出现 DNS 管理状态且无法恢复；保留备份。'
            fail '安装后发现意外 DNS 管理状态；已尝试关闭，暂不宣称成功。'
        fi
        say '安装或安全修复完成；DNS 过滤保持关闭，无需手动删除旧版。'
    fi
    rm -f "$REMOVED"
)
do_uninstall() (
    ensure_root
    no_conflict
    original_state=$(install_state)
    case "$original_state" in
        beta|legacy) ;;
        residual|fresh) say '未检测到待卸载的 AdZero APK，已安全退出。'; exit 0 ;;
        *) fail '包来源、控制程序或安装标记不完整，拒绝删除；请用菜单 5 查看只读诊断。' ;;
    esac
    make_temp
    # APK itself decides the dependency closure. Refuse any transaction
    # that would remove unrelated packages, even if the user chose uninstall.
    apk --root "${ROOT:-/}" --arch "$ARCH" del --simulate --no-network \
        --repositories-file /dev/null luci-app-adzero > "$TMP/removal-plan" 2>&1 ||
        fail 'APK 不能安全模拟卸载，不修改已安装的软件包。'
    grep -Eq '^\([0-9]+/[0-9]+\) (Purging|Removing) luci-app-adzero ' "$TMP/removal-plan" ||
        fail '未确认待卸载包属于 AdZero，操作已停止。'
    if grep -E '^\([0-9]+/[0-9]+\) (Purging|Removing|Upgrading|Downgrading|Installing|Reinstalling) ' "$TMP/removal-plan" |
        grep -Ev '^\([0-9]+/[0-9]+\) (Purging|Removing) luci-app-adzero ' | grep -q .; then
        fail 'APK 计划连带修改其他已安装依赖，拒绝卸载；保留原系统与 DNS 状态。'
    fi
    mkdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || fail '另一安装任务正在运行。'
    trap 'rmdir "$ROOT/tmp/adzero-install.lock" 2>/dev/null || :; rm -rf "$TMP"' 0
    [ "$(install_state)" = "$original_state" ] || fail '卸载预检之后安装状态已变化。'
    save_backup
    say '正在关闭 AdZero 并恢复原 DNS/代理；恢复失败将停止卸载。'
    "$CTL" disable || fail 'DNS/代理恢复失败，未卸载任何软件包；已保留备份。'
    [ ! -e "$ROOT/etc/adzero/managed" ] &&
        [ ! -e "$ROOT/etc/adzero/adapter.json" ] ||
        fail '原 DNS/代理仍存在接管记录，拒绝卸载；备份已保留。'
    apk --root "${ROOT:-/}" --arch "$ARCH" del --no-network \
        --repositories-file /dev/null luci-app-adzero ||
        fail 'APK 卸载失败，保留备份和当前安装记录。'
    apk_installed && fail 'APK 未确认已卸载，保留恢复记录。'
    removed_tmp=$(mktemp "$MARKDIR/.removed.XXXXXXXX") ||
        fail '已卸载，但无法创建安全恢复记录临时文件；配置备份保留。'
    printf 'tag=%s\nprofile=%s\ntarget=%s\n' "$TAG" "$PROFILE" "$TARGET" > "$removed_tmp"
    chmod 600 "$removed_tmp"
    mv "$removed_tmp" "$REMOVED" || fail '已卸载，但写入恢复标记失败；配置备份保留。'
    rm -f "$MARKER"
    say 'AdZero 已安全卸载，原系统依赖与配置备份保留；可直接选择菜单 2 重新安装。'
)
menu_action() {
    # Isolate errors: a failed check or install returns to this menu instead
    # of forcing the user to fetch and launch the script again via SSH.
    if [ -n "$LOCAL_DIR" ]; then
        sh "$0" "$@" --local-dir "$LOCAL_DIR"
    else
        sh "$0" "$@"
    fi
}
menu() {
    while :; do
        printf '\n%s\n' '=========== AdZero iStoreOS 公开测试版 ==========='
        printf '发行：%s  固件：%s %s  target=%s\n' "$TAG" "$FW" "$VER" "$TARGET"
        case "$(install_state)" in
            beta) say '状态：当前 Beta 已安装' ;;
            legacy) say '状态：发现旧版 AdZero APK（未登记 Beta）；可直接修复或安全卸载' ;;
            residual) say '状态：上次已安全卸载；旧配置已保留' ;;
            fresh) say '状态：尚未安装 AdZero' ;;
            *) say '状态：原有安装记录不完整（只允许诊断，禁止覆盖）' ;;
        esac
        printf '%s\n' ' 1) 只读检查安装包与依赖'
        printf '%s\n' ' 2) 一键安装 / 安全修复已有 AdZero（默认关闭过滤）'
        printf '%s\n' ' 3) 安装并启用过滤（需再次确认风险）'
        printf '%s\n' ' 4) 安全卸载当前 AdZero（含无 Beta 标记的旧版）'
        printf '%s\n' ' 5) 检测安装来源/版本/恢复状态（只读）'
        printf '%s\n' ' 0) 退出'
        printf '%s' '请输入 [0-5]: '
        IFS= read -r choice || return 0
        case "$choice" in
            1) menu_action --check || say '预检未通过。可查看上方原因和菜单 5，无需重新运行 SSH 命令。' ;;
            2)
                if confirm '确认一键安装或修复？如旧版正在过滤，将先备份并恢复 DNS/代理，完成后保持关闭。'; then
                    menu_action --install || say '未完成安装/修复；请查看上方原因，原配置备份不会删除。'
                fi ;;
            3)
                if confirm '确认安装并准备启用 DNS 拦截？' && risk_confirm; then
                    menu_action --install --enable --accept-network-risk ||
                        say '未完成启用；请检查上方恢复信息。'
                fi ;;
            4)
                if confirm '确认备份、恢复 DNS/代理并卸载本机 AdZero APK（仅限 APK 已确认归属的旧版）？'; then
                    menu_action --uninstall || say '安全卸载未完成；请查看上方拒绝原因。'
                fi ;;
            5) show_status ;;
            0) return 0 ;;
            *) say '请输入 0 至 5。' ;;
        esac
    done
}
case "$MODE" in
    menu) menu ;;
    status) show_status ;;
    check) run_check ;;
    uninstall) do_uninstall ;;
    install)
        [ "$ENABLE" = 0 ] || [ "$RISK" = 1 ] ||
            fail '手动启用过滤需要同时指定 --accept-network-risk。'
        do_install "$ENABLE" ;;
esac
