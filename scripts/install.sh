#!/bin/sh
# AdZero release installer. Only exact SDK-verified matrix rows are installable.
set -eu
set -f
umask 077
BASE_URL=${ADZERO_BASE_URL:-https://github.com/slobys/AdZero/releases/download/v0.12.3}
LOCAL_DIR=
ENABLE=1
UPGRADE=0
ROOT=${ADZERO_INSTALL_ROOT:-}
fail() { printf 'AdZero: %s\n' "$*" >&2; exit 1; }
while [ "$#" -gt 0 ]; do
	case "$1" in
		--base-url) [ "$#" -ge 2 ] || fail '缺少 URL'; BASE_URL=$2; shift 2 ;;
		--local-dir) [ "$#" -ge 2 ] || fail '缺少发行目录'; LOCAL_DIR=$2; shift 2 ;;
		--no-enable) ENABLE=0; shift ;;
		--upgrade) UPGRADE=1; shift ;;
		*) fail '用法: install.sh {--local-dir DIR | --base-url https://...} [--upgrade] [--no-enable]' ;;
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
[ "$UPGRADE" = 1 ] || [ ! -e "$ROOT/etc/adzero/adapter.json" ] || fail '请使用 --upgrade 自动准备升级，或先在现有版本中关闭保护；保留原有恢复记录。'
TMP=$(mktemp -d "${TMPDIR:-/tmp}/adzero-install.XXXXXX") || fail '无法创建临时目录。'
WATCH="$ROOT/usr/libexec/adzero/watch"
INSTALL_LOCK="$ROOT/tmp/adzero-install.lock"
INSTALL_LOCK_OWNED=0
# Strip the whole comm field, which may contain spaces or parentheses.
# Linux start ticks distinguish a surviving process from a reused PID.
process_snapshot() (
	IFS= read -r proc_stat 2>/dev/null < "/proc/$1/stat" || exit 1
	proc_fields=${proc_stat##*) }
	set -- $proc_fields
	[ "$#" -ge 20 ] || exit 1
	proc_state=$1
	shift 19
	case "$1" in ''|*[!0-9]*) exit 1 ;; esac
	printf '%s %s\n' "$1" "$proc_state"
)
watch_matches() (
	# Only the exact scheduler command and our UID may receive a signal.
	proc_args=$(tr '\000' '\n' 2>/dev/null < "/proc/$1/cmdline") || exit 1
	case "$proc_args" in
		"/bin/sh
$WATCH"|"/bin/ash
$WATCH"|"/bin/busybox
sh
$WATCH"|"/bin/busybox
ash
$WATCH") ;;
		*) exit 1 ;;
	esac
	self_uid=$(awk '/^Uid:/ { print $2, $3, $4, $5 }' /proc/self/status)
	proc_uid=$(awk '/^Uid:/ { print $2, $3, $4, $5 }' "/proc/$1/status" 2>/dev/null) || exit 1
	[ -n "$self_uid" ] && [ "$self_uid" = "$proc_uid" ]
)
resume_watchers() {
	[ -f "$TMP/watchers" ] || return 0
	while read -r watch_pid watch_start; do
		current=$(process_snapshot "$watch_pid") || continue
		[ "${current%% *}" = "$watch_start" ] && watch_matches "$watch_pid" || continue
		kill -CONT "$watch_pid" 2>/dev/null || :
	done < "$TMP/watchers"
}
cleanup() {
	resume_watchers
	[ "$INSTALL_LOCK_OWNED" != 1 ] || rmdir "$INSTALL_LOCK" 2>/dev/null || :
	rm -f "$TMP/releases.tsv" "$TMP/package.$EXT" "$TMP/disable.log" "$TMP/watchers"
	rmdir "$TMP" 2>/dev/null || :
}
trap 'cleanup' 0
trap 'exit 130' 1 2 3 15
watch_candidates() (
	set +f
	grep -lF "$WATCH" /proc/[0-9]*/cmdline 2>/dev/null || :
)
pause_watchers() {
	[ -r /proc/self/stat ] || fail '无法核对后台调度进程，已停止升级。'
	: > "$TMP/watchers"
	# Output only numeric /proc paths, never command-line content.
	for proc_file in $(watch_candidates); do
		watch_pid=${proc_file#/proc/}; watch_pid=${watch_pid%/cmdline}
		case "$watch_pid" in ''|*[!0-9]*) continue ;; esac
		before=$(process_snapshot "$watch_pid") || continue
		watch_matches "$watch_pid" || continue
		current=$(process_snapshot "$watch_pid") || continue
		[ "${current%% *}" = "${before%% *}" ] || fail '后台进程已变化，请重试升级。'
		case "${current#* }" in T|t) continue ;; esac
		printf '%s %s\n' "$watch_pid" "${before%% *}" >> "$TMP/watchers"
		kill -STOP "$watch_pid" 2>/dev/null || fail '无法暂停后台调度，已停止升级。'
		after=$(process_snapshot "$watch_pid") || fail '后台进程已退出，请重试升级。'
		[ "${after%% *}" = "${before%% *}" ] && watch_matches "$watch_pid" || fail '后台进程身份已变化，已停止升级。'
		# SIGSTOP is asynchronous. Its children continue their current work.
		stop_checks=0
		while [ "${after#* }" != T ] && [ "${after#* }" != t ]; do
			[ "$stop_checks" -lt 3 ] || fail '后台调度未暂停，已停止升级。'
			sleep 1
			after=$(process_snapshot "$watch_pid") || fail '后台进程已退出，请重试升级。'
			[ "${after%% *}" = "${before%% *}" ] || fail '后台进程身份已变化，已停止升级。'
			stop_checks=$((stop_checks + 1))
		done
	done
	[ ! -s "$TMP/watchers" ] || printf 'AdZero: 已暂停后台调度，正在让旧版任务完成；退出安装器会恢复调度。\n'
}
upgrade_tick() {
	[ "$upgrade_waits" -lt "$upgrade_limit" ] || fail '旧版操作锁持续占用，已停止升级并恢复后台调度；没有删除锁或安装新包。请提供锁和进程信息。'
	[ "$((upgrade_waits % 15))" != 0 ] || printf 'AdZero: 等待旧版任务完成（已等 %s 秒，最多 %s 秒）；不会终止任务或删除锁。\n' "$upgrade_waits" "$upgrade_limit"
	sleep 1
	upgrade_waits=$((upgrade_waits + 1))
}
wait_upgrade_lock() {
	while [ -e "$ROOT/tmp/adzero.lock" ] || [ -L "$ROOT/tmp/adzero.lock" ]; do upgrade_tick; done
}
backup_state() {
	tar -czf "$BACKUP/config.tar.gz" -C "$ROOT/etc" config || fail '配置备份失败。'
	if [ -d "$ROOT/etc/adzero" ]; then
		tar -czf "$BACKUP/state.tar.gz" -C "$ROOT/etc" adzero || fail '恢复记录备份失败。'
	fi
}
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
# A Windows-authored catalog may use CRLF. Remove only the line terminator;
# retain exact firmware/target/ABI/format matching and duplicate rejection.
ROW=$(awk -F '\t' -v fw="$FIRMWARE" -v ver="$VERSION" -v target="$TARGET" -v arch="$ARCH" -v ext="$EXT" '{ sub(/\r$/, "", $0) } NF==7 && $3==fw && $4==ver && $5==target && $6==arch && $7==ext {print $1 " " $2; n++} END {if(n!=1) exit 1}' "$TMP/releases.tsv") || fail "没有唯一匹配此固件版本的 SDK 安装包（$FIRMWARE $VERSION，target=$TARGET，架构=$ARCH，格式=$EXT）。"
SUM=${ROW%% *}
FILE=${ROW#* }
[ "${#SUM}" = 64 ] || fail '校验清单格式错误。'
case "$SUM" in *[!0-9a-f]*) fail '校验清单格式错误。' ;; esac
case "$FILE" in ''|*[!a-zA-Z0-9._+-]*|.*) fail '不安全的安装包文件名。' ;; esac
fetch "$FILE" "$TMP/package.$EXT"
ACTUAL=$(sha256sum "$TMP/package.$EXT")
[ "${ACTUAL%% *}" = "$SUM" ] || fail 'SHA-256 不匹配，已停止安装。'
mkdir -p "$ROOT/tmp"
mkdir "$INSTALL_LOCK" 2>/dev/null || fail '另一项安装正在进行，或安装器锁仍待检查；没有停止现有保护。'
INSTALL_LOCK_OWNED=1
CTL="$ROOT/usr/libexec/adzero/ctl"
upgrade_limit=${ADZERO_UPGRADE_WAIT_SECONDS:-180}
case "$upgrade_limit" in ''|*[!0-9]*) fail '升级等待时限无效。' ;; esac
[ "$upgrade_limit" -ge 1 ] && [ "$upgrade_limit" -le 300 ] || fail '升级等待时限应为 1 至 300 秒。'
upgrade_waits=0
if [ "$UPGRADE" = 1 ] && [ -x "$CTL" ]; then
	pause_watchers
	wait_upgrade_lock
fi
BACKUP="$ROOT/etc/adzero-backups/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
chmod 700 "$ROOT/etc/adzero-backups" "$BACKUP"
backup_state
if [ "$UPGRADE" = 1 ]; then
	# Keep config and recovery state together before asking the OLD controller
	# to restore its changes. Never replace a controller that still owns them.
	if [ -x "$CTL" ]; then
		# Recent controllers understand zero wait. Older ones fail immediately.
		# Retry only known pre-mutation busy responses, never restore failures.
		while ! ADZERO_LOCK_WAIT_SECONDS=0 "$CTL" disable > "$TMP/disable.log" 2>&1; do
			case "$(cat "$TMP/disable.log")" in
				'AdZero: 另一项操作正在进行；若异常断电可检查临时锁。'|'AdZero: 等待操作锁超时；可能仍有操作或遗留锁。请检查进程后重试，勿直接删除锁。') ;;
				*) cat "$TMP/disable.log" >&2; fail '旧版未能完成关闭与恢复，已停止升级；恢复记录保留。' ;;
			esac
			upgrade_tick
			wait_upgrade_lock
			backup_state
		done
		cat "$TMP/disable.log"
	fi
	[ ! -e "$ROOT/etc/adzero/adapter.json" ] && [ ! -e "$ROOT/etc/adzero/managed" ] || fail '旧版仍有未恢复的所有权记录，已停止升级。'
fi
printf 'AdZero: 安装 %s；配置备份：%s\n' "$FILE" "$BACKUP/config.tar.gz"
if [ "$PM" = opkg ]; then
	opkg update || fail '固件软件源更新失败。'
	opkg install "$TMP/package.ipk" || fail '安装失败，请检查当前固件软件源依赖。'
else
	apk update || fail '固件软件源更新失败。'
	# Refresh repository metadata with normal verification before allowing our unsigned package.
	apk add --allow-untrusted "$TMP/package.apk" || fail '安装失败，请检查当前固件软件源依赖。'
fi
[ -x "$CTL" ] || fail '安装后缺少 AdZero 控制程序。'
if [ "$ENABLE" = 1 ]; then
	"$CTL" enable || fail '安装完成，但启用未成功；请检查 AdZero 诊断与恢复记录。'
	if [ -x "$ROOT/etc/init.d/adzero" ]; then "$ROOT/etc/init.d/adzero" enable; "$ROOT/etc/init.d/adzero" start; fi
fi
printf 'AdZero: 安装完成，请打开 LuCI「服务 → AdZero」。终端过滤效果需实际 DNS 查询验收。\n'
