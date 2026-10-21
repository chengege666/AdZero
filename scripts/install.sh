#!/bin/sh
# AdZero release installer. Only exact SDK-verified matrix rows are installable.
set -eu
umask 077
BASE_URL=${ADZERO_BASE_URL:-https://github.com/slobys/AdZero/releases/download/v0.6.0}
LOCAL_DIR=
ENABLE=1
ROOT=${ADZERO_INSTALL_ROOT:-}
fail() { printf 'AdZero: %s\n' "$*" >&2; exit 1; }
while [ "$#" -gt 0 ]; do
	case "$1" in
		--base-url) [ "$#" -ge 2 ] || fail '缺少 URL'; BASE_URL=$2; shift 2 ;;
		--local-dir) [ "$#" -ge 2 ] || fail '缺少发行目录'; LOCAL_DIR=$2; shift 2 ;;
		--no-enable) ENABLE=0; shift ;;
		*) fail '用法: install.sh {--local-dir DIR | --base-url https://...} [--no-enable]' ;;
	esac
done
[ "$(id -u)" = 0 ] || fail '请通过路由器 root SSH 执行。'
[ -r "$ROOT/etc/openwrt_release" ] || fail '没有发现 OpenWrt 固件信息。'
release_value() {
	awk -v key="$1" 'index($0,key "=")==1 { v=substr($0,length(key)+2); if (v ~ /^".*"$/ || v ~ /^\047.*\047$/) v=substr(v,2,length(v)-2); print v; exit }' "$ROOT/etc/openwrt_release"
}
FIRMWARE=$(release_value DISTRIB_ID)
VERSION=$(release_value DISTRIB_RELEASE)
TARGET=$(release_value DISTRIB_TARGET)
DECLARED_ARCH=$(release_value DISTRIB_ARCH)
case "$FIRMWARE" in OpenWrt) FIRMWARE=openwrt ;; *) fail '此发行版尚未通过该固件 SDK 验证，请等待兼容矩阵扩展。' ;; esac
case "$TARGET" in
	x86/64) ARCH=x86_64; APK_MACHINE_ARCH=x86_64 ;;
	rockchip/armv8) ARCH=aarch64_generic; APK_MACHINE_ARCH=aarch64 ;;
	'') fail '固件信息中缺少 DISTRIB_TARGET，无法选择安装包。请提供 /etc/openwrt_release、uname -m 和软件包架构输出。尚未安装或修改网络配置。' ;;
	*) fail "检测到固件 target=$TARGET；此发行版未提供该目标安装包（已支持 x86/64、rockchip/armv8）。请提供固件版本及软件包架构以继续适配。尚未安装或修改网络配置。" ;;
esac
[ -z "$DECLARED_ARCH" ] || [ "$DECLARED_ARCH" = "$ARCH" ] || fail "固件声明架构 $DECLARED_ARCH 与目标 $TARGET 的 SDK 架构 $ARCH 不一致。"
PM=
if command -v opkg >/dev/null 2>&1 && [ -r "$ROOT/usr/lib/opkg/status" ]; then PM=opkg; fi
if command -v apk >/dev/null 2>&1 && [ -r "$ROOT/lib/apk/db/installed" ]; then
	[ -z "$PM" ] || fail '同时发现 OPKG 和 APK 数据库，拒绝猜测。'
	PM=apk
fi
[ -n "$PM" ] || fail '无法确定软件包管理器。'
if [ "$PM" = opkg ]; then
	opkg print-architecture | awk -v arch="$ARCH" '$2==arch {found=1} END {exit !found}' || fail '软件包架构不匹配。'
	EXT=ipk
else
	# apk's compiled CPU name can differ from the OpenWrt repository/SDK ABI name.
	# Accept only the explicit alias for this verified target, never a CPU guess.
	ACTUAL_APK_ARCH=$(apk --print-arch)
	[ "$ACTUAL_APK_ARCH" = "$ARCH" ] || [ "$ACTUAL_APK_ARCH" = "$APK_MACHINE_ARCH" ] || fail "APK 架构 $ACTUAL_APK_ARCH 与目标 $TARGET 不匹配。"
	EXT=apk
fi
command -v sha256sum >/dev/null 2>&1 || fail '缺少 sha256sum。'
[ ! -e "$ROOT/etc/adzero/adapter.json" ] || fail '请先在现有版本中关闭保护，再升级；保留原有恢复记录。'
TMP=$(mktemp -d "${TMPDIR:-/tmp}/adzero-install.XXXXXX") || fail '无法创建临时目录。'
trap 'rm -f "$TMP/releases.tsv" "$TMP/package.$EXT"; rmdir "$TMP" 2>/dev/null || :' 0
trap 'exit 130' 1 2 3 15
fetch() {
	if [ -n "$LOCAL_DIR" ]; then
		cp "$LOCAL_DIR/$1" "$2" || fail '本地发行文件缺失。'
	else
		case "$BASE_URL" in https://*) ;; *) fail '请指定发行目录或 HTTPS 下载地址。' ;; esac
		command -v curl >/dev/null 2>&1 || fail 'HTTPS 安装需要 curl；也可下载发行压缩包后使用 --local-dir。'
		curl --fail --location --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 180 --output "$2" "${BASE_URL%/}/$1" || fail '下载失败；没有更改 DNS 配置。'
	fi
}
fetch releases.tsv "$TMP/releases.tsv"
ROW=$(awk -F '\t' -v fw="$FIRMWARE" -v ver="$VERSION" -v target="$TARGET" -v arch="$ARCH" -v ext="$EXT" 'NF==7 && $3==fw && $4==ver && $5==target && $6==arch && $7==ext {print $1 " " $2; n++} END {if(n!=1) exit 1}' "$TMP/releases.tsv") || fail '没有唯一匹配此固件版本的 SDK 安装包。'
SUM=${ROW%% *}
FILE=${ROW#* }
[ "${#SUM}" = 64 ] || fail '校验清单格式错误。'
case "$SUM" in *[!0-9a-f]*) fail '校验清单格式错误。' ;; esac
case "$FILE" in ''|*[!a-zA-Z0-9._+-]*|.*) fail '不安全的安装包文件名。' ;; esac
fetch "$FILE" "$TMP/package.$EXT"
ACTUAL=$(sha256sum "$TMP/package.$EXT")
[ "${ACTUAL%% *}" = "$SUM" ] || fail 'SHA-256 不匹配，已停止安装。'
BACKUP="$ROOT/etc/adzero-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
chmod 700 "$ROOT/etc/adzero-backups" "$BACKUP"
tar -czf "$BACKUP/config.tar.gz" -C "$ROOT/etc" config || fail '配置备份失败。'
printf 'AdZero: 安装 %s；配置备份：%s\n' "$FILE" "$BACKUP/config.tar.gz"
if [ "$PM" = opkg ]; then
	opkg update || fail '固件软件源更新失败。'
	opkg install "$TMP/package.ipk" || fail '安装失败，请检查当前固件软件源依赖。'
else
	apk update || fail '固件软件源更新失败。'
	# Refresh repository metadata with normal verification before allowing our unsigned package.
	apk add --allow-untrusted "$TMP/package.apk" || fail '安装失败，请检查当前固件软件源依赖。'
fi
CTL="$ROOT/usr/libexec/adzero/ctl"
[ -x "$CTL" ] || fail '安装后缺少 AdZero 控制程序。'
if [ "$ENABLE" = 1 ]; then
	"$CTL" enable || fail '安装完成，但启用未成功；请检查 AdZero 诊断与恢复记录。'
	if [ -x "$ROOT/etc/init.d/adzero" ]; then "$ROOT/etc/init.d/adzero" enable; "$ROOT/etc/init.d/adzero" start; fi
fi
printf 'AdZero: 安装完成，请打开 LuCI「服务 → AdZero」。终端过滤效果需实际 DNS 查询验收。\n'
