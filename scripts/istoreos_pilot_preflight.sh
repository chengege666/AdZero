#!/bin/sh
# AdZero iStoreOS pilot: strictly READ-ONLY, never installs/updates/reboots.
set -eu
set -f
LC_ALL=C; export LC_ALL
fail() { printf 'AdZero iStoreOS 预检拒绝：%s\n' "$*" >&2; exit 1; }
[ "$#" -eq 1 ] || fail '仅支持 --check、--solver 或 --report。'
case "$1" in --check|--solver|--report) mode=$1 ;; *) fail '不支持安装操作。' ;; esac
dir=$(CDPATH= cd "$(dirname "$0")" && pwd -P) || fail '离线包目录不可用。'
root=${ADZERO_PILOT_ROOT:-}
[ -r "$root/etc/openwrt_release" ] || fail '缺少固件身份文件。'
for f in profile.tsv SHA256SUMS pilot-manifest.json preflight.sh README.txt; do
    [ -f "$dir/$f" ] && [ ! -L "$dir/$f" ] || fail "文件不可用或为符号链接：$f"
done
[ -d "$dir/packages" ] && [ ! -L "$dir/packages" ] || fail 'APK 文件夹无效。'
count=0
seen=':'
while read -r sha path; do
    [ "${#sha}" -eq 64 ] || fail '无效 SHA-256 摘要长度。'
    case "$sha" in *[!a-f0-9]*) fail '校验摘要包含非法字符。' ;; esac
    case "$path" in
        profile.tsv|pilot-manifest.json|preflight.sh|README.txt) ;;
        packages/*.apk)
            name=${path#packages/}
            case "$name" in ''|.*|*/*|*[!a-zA-Z0-9._+-]*) fail 'APK 文件名包含非法字符。' ;; esac ;;
        *) fail '校验表包含非测试包路径。' ;;
    esac
    case "$seen" in *":$path:"*) fail '校验清单中有重复路径。' ;; esac
    seen="$seen$path:"
    [ -f "$dir/$path" ] && [ ! -L "$dir/$path" ] || fail "缺失或不安全的文件：$path"
    count=$((count+1))
done < "$dir/SHA256SUMS"
[ "$count" -eq 11 ] || fail 'SHA256SUMS 应为 7 个 APK 加 4 个元数据文件。'
(cd "$dir" && sha256sum -c SHA256SUMS >/dev/null) || fail '测试包 SHA-256 核验失败。'
row=$(awk -F '	' 'NR==1 {if(NF!=7)exit 1;for(i=1;i<=NF;i++)if($i !~ /^[a-zA-Z0-9._\/-]+$/)exit 1;print $1,$2,$3,$4,$5,$6,$7} END{if(NR!=1)exit 1}' "$dir/profile.tsv") || fail '目标资料不合法。'
set -- $row
[ "$#" -eq 7 ] || fail '目标资料缺失。'
fw=$1 release=$2 revision=$3 target=$4 arch=$5 profile=$6 fmt=$7
case "$profile:$fw:$release:$revision:$target:$arch:$fmt" in
  armsr:istoreos:25.12.6:2026102312:armsr/armv8:aarch64_generic:apk|\
  rockchip-r6xs:istoreos:25.12.6:2026102312:rockchip/armv8:aarch64_generic:apk) ;;
  *) fail '固件名称、版本、修订、设备或包架构不在原厂预检白名单。' ;;
esac
get_release() {
    awk -v k="$1" 'index($0,k "=")==1 {v=substr($0,length(k)+2);if(v ~ /^".*"$/ || v ~ /^\047.*\047$/)v=substr(v,2,length(v)-2);print v;exit}' "$root/etc/openwrt_release"
}
[ "$(get_release DISTRIB_ID)" = iStoreOS ] || fail '只支持匹配的 iStoreOS 固件。'
[ "$(get_release DISTRIB_RELEASE)" = "$release" ] || fail '固件版本不一致。'
[ "$(get_release DISTRIB_REVISION)" = "$revision" ] || fail '固件修订号不一致。'
[ "$(get_release DISTRIB_TARGET)" = "$target" ] || fail 'target 不一致。'
[ "$(get_release DISTRIB_ARCH)" = "$arch" ] || fail '软件包架构不一致。'
[ ! -e "$root/usr/lib/opkg/status" ] || fail '发现 OPKG 数据库，拒绝多包管理器环境。'
db="$root/lib/apk/db/installed"
[ -r "$db" ] || fail '缺少 APK 已安装数据库。'
for pkg in tcpdump luci-base rpcd; do
    grep -qx "P:$pkg" "$db" || fail "缺少原厂包 $pkg；不得覆盖依赖。"
done
! grep -qx 'P:luci-app-adzero' "$db" || fail '已安装 AdZero，本阶段不试装升级。'
[ ! -e "$root/etc/adzero/managed" ] && [ ! -e "$root/etc/adzero/adapter.json" ] ||
    fail '已有 AdZero 所有权记录，禁止覆盖代理/DNS。'
command -v apk >/dev/null 2>&1 || fail '缺少 APK 管理器。'
command -v sha256sum >/dev/null 2>&1 || fail '缺少 sha256sum。'
cpu=$(apk --print-arch) || fail '无法读取 APK 架构。'
case "$cpu" in aarch64|aarch64_generic) ;; *) fail "APK CPU 架构不一致：$cpu" ;; esac

board_check=not_applicable
if [ "$profile" = rockchip-r6xs ]; then
    # The exact five compatible board identifiers come from the SHA-pinned
    # vendor R6XS image's supported_devices trailer. Never print board IDs.
    board_check=unavailable
    board_file="$root/tmp/sysinfo/board_name"
    if [ -r "$board_file" ] && [ ! -L "$board_file" ]; then
        board_name=
        IFS= read -r board_name < "$board_file" || :
        case "$board_name" in
            fastrhino,r6xs|lunzn,fastrhino-r66s|lunzn,fastrhino-r68s|fastrhino,r66s|fastrhino,r68s)
                board_check=matched ;;
            *) fail '设备板型不在官方 R6XS 固件支持列表，拒绝候选包预检。' ;;
        esac
    fi
fi
set +f
set -- "$dir"/packages/*.apk
set -f
[ "$#" -eq 7 ] || fail '必须有 1 个 AdZero 和 6 个原厂依赖 APK。'
for file do
    [ -f "$file" ] && [ ! -L "$file" ] || fail '发现不可用或符号链接安装包。'
done
if [ "$mode" = --report ]; then
    # Whitelisted status only; no UCI values, proxy credentials, IPs or MACs.
    has_comm() (
        set +f
        for f in "$root"/proc/[0-9]*/comm; do
            [ -r "$f" ] || continue
            IFS= read -r comm < "$f" || :
            [ "$comm" = "$1" ] && exit 0
        done
        exit 1
    )
    has_config() {
        [ -f "$root/etc/config/$1" ] && [ ! -L "$root/etc/config/$1" ]
    }
    as_bool() {
        if "$@"; then printf true; else printf false; fi
    }
    mem=null
    if [ -r "$root/proc/meminfo" ] && [ ! -L "$root/proc/meminfo" ]; then
        available=$(awk '$1=="MemAvailable:" && $2 ~ /^[0-9]+$/ {print $2;exit}' "$root/proc/meminfo")
        case "$available" in ''|*[!0-9]*) ;; *) mem=$available ;; esac
    fi
    overlay=null
    # Test roots must not accidentally query the developer host filesystem.
    if [ -z "$root" ] && [ -d /overlay ]; then
        free_kib=$(df -Pk /overlay 2>/dev/null | awk 'NR==2 {print $4}') || free_kib=
        case "$free_kib" in ''|*[!0-9]*) ;; *) overlay=$free_kib ;; esac
    fi
    manifest_sha=$(sha256sum "$dir/pilot-manifest.json" | awk '{print $1}')
    case "$manifest_sha" in
      '') fail '缺少 pilot manifest SHA。' ;;
      *[!a-f0-9]*) fail '无效 pilot manifest SHA。' ;;
    esac
    [ "${#manifest_sha}" -eq 64 ] || fail 'Pilot manifest SHA 无效。'
    printf '{\n'
    printf '  "schema_version": 1,\n'
    printf '  "report_type": "adzero_istoreos_readonly_readiness",\n'
    printf '  "firmware": "%s", "release": "%s", "revision": "%s",\n' "$fw" "$release" "$revision"
    printf '  "vendor_profile": "%s", "target": "%s", "arch": "%s", "apk_cpu": "%s",\n' "$profile" "$target" "$arch" "$cpu"
    printf '  "pilot_manifest_sha256": "%s",\n' "$manifest_sha"
    printf '  "checked_local_apks": 7,\n'
    printf '  "board_check": "%s",\n' "$board_check"
    printf '  "original_full_tcpdump": true, "luci_base_present": true, "rpcd_present": true,\n'
    printf '  "memory_available_kib": %s, "overlay_available_kib": %s,\n' "$mem" "$overlay"
    printf '  "dns_process_presence": {\n'
    printf '    "dnsmasq": %s, "smartdns": %s, "unbound": %s, "adguardhome": %s\n' \
        "$(as_bool has_comm dnsmasq)" "$(as_bool has_comm smartdns)" \
        "$(as_bool has_comm unbound)" "$(as_bool has_comm AdGuardHome)"
    printf '  },\n'
    printf '  "proxy_config_presence": {\n'
    printf '    "nailink": %s, "passwall": %s, "openclash": %s, "nikki": %s, "homeproxy": %s\n' \
        "$(as_bool has_config nailink)" "$(as_bool has_config passwall)" \
        "$(as_bool has_config openclash)" "$(as_bool has_config nikki)" \
        "$(as_bool has_config homeproxy)"
    printf '  },\n'
    printf '  "proxy_core_presence": {\n'
    printf '    "mihomo": %s, "clash": %s, "sing_box": %s, "xray": %s\n' \
        "$(as_bool has_comm mihomo)" "$(as_bool has_comm clash)" \
        "$(as_bool has_comm sing-box)" "$(as_bool has_comm xray)"
    printf '  },\n'
    printf '  "network_dns_test": "not_run", "proxy_coexistence_test": "not_run",\n'
    printf '  "device_acceptance": "not_run", "installation_authorized": false,\n'
    printf '  "public_release": false, "publishable": false\n'
    printf '}\n'
    exit 0
fi
printf 'AdZero iStoreOS 只读预检通过：%s %s revision=%s target=%s arch=%s（7 个 APK）\n' "$fw" "$release" "$revision" "$target" "$arch"
[ "$mode" = --solver ] || {
    printf '%s\n' '未执行任何安装、重启、UCI、DNS 或代理修改。'
    exit 0
}
output=$(apk --root "${root:-/}" --arch "$arch" add --simulate --no-network \
    --repositories-file /dev/null --allow-untrusted "$@" 2>&1) ||
    fail '原厂 APK 无网络依赖模拟失败，未修改系统。'
if printf '%s\n' "$output" | grep -Eq '(^|[^a-zA-Z])(Removing|Purging|Upgrading|Downgrading|Reinstalling)([^a-zA-Z]|$)'; then
    fail '模拟将变更已安装的原厂软件，拒绝继续。'
fi
planned=$(printf '%s\n' "$output" | awk '/ Installing / { for(i=1;i<NF;i++) if($i=="Installing") print $(i+1) }')
seen_adzero=0
for name in $planned; do
    case "$name" in
        luci-app-adzero) seen_adzero=1 ;;
        adblock-fast|conntrack|coreutils-timeout|libnetfilter-cthelper0|libnetfilter-cttimeout1|libnetfilter-queue1) ;;
        *) fail "模拟尝试安装未列入原厂依赖的包：$name" ;;
    esac
done
[ "$seen_adzero" -eq 1 ] || fail '模拟没有计划安装 AdZero；请检查已安装状态。'
printf '%s\n' "$output" | grep -q 'OK:' || fail '模拟没有成功闭环确认。'
printf '%s\n' 'AdZero 离线依赖模拟通过；没有执行任何安装。'
