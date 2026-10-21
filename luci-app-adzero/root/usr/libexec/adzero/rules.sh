# Sourced by ctl. Own only a new, reserved default list; keep user lists intact.
DEFAULT_RULE=adblock-fast.adzero_default
# HaGeZi moved legacy domains/ lists. Use its current, suffix-covering domain
# format directly from GitHub (the same host used by the release installer).
DEFAULT_RULE_URL=https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/light-onlydomains.txt
RULE_MARKER=$STATE_DIR/default_rule.owned

rule_sources_state() {
	[ -n "$(get_uci adblock-fast.config.blocked_domain)" ] && { printf configured; return; }
	source_config=$("$UCI_BIN" -q show adblock-fast 2>/dev/null) || { printf unknown; return; }
	source_sections=$(printf '%s\n' "$source_config" | sed -n \
		-e 's/^\(adblock-fast\.[a-zA-Z0-9_]*\)=file_url$/\1/p' \
		-e 's/^\(adblock-fast\.@file_url\[[0-9][0-9]*\]\)=file_url$/\1/p')
	for section in $source_sections; do
		case "$(get_uci "$section.enabled")" in ''|1) ;; *) continue ;; esac
		case "$(get_uci "$section.action")" in ''|block) ;; *) continue ;; esac
		[ -n "$(get_uci "$section.url")" ] && { printf configured; return; }
	done
	printf empty
}
prepare_default_rule() {
	case "$(rule_sources_state)" in
		configured) return 0 ;;
		empty) ;;
		*) return 1 ;;
	esac
	[ -z "$(get_uci "$DEFAULT_RULE")" ] || return 1
	# Marker precedes writes, so an interrupted creation remains recoverable.
	printf 'hagezi-light-v1\n' > "$RULE_MARKER" || return 1
	"$UCI_BIN" set "$DEFAULT_RULE=file_url" && \
	"$UCI_BIN" set "$DEFAULT_RULE.name=AdZero - HaGeZi Light" && \
	"$UCI_BIN" set "$DEFAULT_RULE.url=$DEFAULT_RULE_URL" && \
	"$UCI_BIN" set "$DEFAULT_RULE.action=block" && \
	"$UCI_BIN" set "$DEFAULT_RULE.enabled=1" && \
	"$UCI_BIN" commit adblock-fast
}
default_rule_unchanged() {
	# Allow incomplete own writes; preserve a list that a user has customized.
	case "$(get_uci "$DEFAULT_RULE")" in ''|file_url) ;; *) return 1 ;; esac
	for option in name url action enabled; do
		current_rule_value=$(get_uci "$DEFAULT_RULE.$option")
		case "$option" in
			name) expected_rule_value='AdZero - HaGeZi Light' ;;
			url) expected_rule_value=$DEFAULT_RULE_URL ;;
			action) expected_rule_value=block ;;
			enabled) expected_rule_value=1 ;;
		esac
		[ -z "$current_rule_value" ] || [ "$current_rule_value" = "$expected_rule_value" ] || return 1
	done
	rule_dump=$("$UCI_BIN" -q show "$DEFAULT_RULE" 2>/dev/null) || return 2
	rule_keys=$(printf '%s\n' "$rule_dump" | cut -d= -f1)
	for key in $rule_keys; do
		case "$key" in
			adblock-fast.adzero_default|adblock-fast.adzero_default.name|adblock-fast.adzero_default.url|adblock-fast.adzero_default.action|adblock-fast.adzero_default.enabled) ;;
			adblock-fast.adzero_default.size)
				# adblock-fast records download sizes in UCI; this is metadata,
				# not a user change to the rule source we created.
				case "$(get_uci "$key")" in ''|*[!0-9]*) return 1 ;; esac ;;
			*) return 1 ;;
		esac
	done
}
restore_default_rule() {
	[ -f "$RULE_MARKER" ] || return 0
	all_rules=$("$UCI_BIN" -q show adblock-fast 2>/dev/null) || return 1
	if printf '%s\n' "$all_rules" | grep -q '^adblock-fast\.adzero_default='; then
		if default_rule_unchanged; then
			delete_uci "$DEFAULT_RULE" adblock-fast || return 1
		else
			[ "$?" = 1 ] || return 1
		fi
	fi
	rm -f "$RULE_MARKER"
}
rule_failure_hint() {
	# Only print our public URL, never a user subscription or its credentials.
	if [ -f "$RULE_MARKER" ] && [ "$(get_uci "$DEFAULT_RULE.url")" = "$DEFAULT_RULE_URL" ] && \
		"$BACKEND_CHECK" download-error >/dev/null 2>&1; then
		printf 'AdZero: 后端报告规则下载错误，可检查默认 HTTPS 地址：%s\n' "$DEFAULT_RULE_URL" >&2
	fi
}
