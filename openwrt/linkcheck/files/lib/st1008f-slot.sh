# A/B slot helpers (#117, docs/DEFAULT-BOOT.md#ab-slots); sourced by st1008f-slot and the sysupgrade hook.
# bootstate record (partition `bootstate`, read by our U-Boot): one line, CRC32 over the first 12 bytes
#   S1AB g=<good a|b> t=<trial a|b|-> c=<crc32 hex>

ST_REC_MAGIC="S1AB"

# booted slot: our U-Boot passes st1008f.slot=b for slot B; anything else (stock boota, no arg) = A
st1008f_slot_current() {
	case " $(cat /proc/cmdline) " in
	*" st1008f.slot=b "*) echo b ;;
	*) echo a ;;
	esac
}

st1008f_slot_other() { [ "$1" = a ] && echo b || echo a; }

st1008f_bootstate_dev() {
	local n
	n=$(sed -n 's/^mtd\([0-9]*\): .* "bootstate"$/\1/p' /proc/mtd)
	[ -n "$n" ] && echo /dev/mtdblock$n
}

# CRC32 (IEEE, as U-Boot crc32()) of $1: the gzip trailer holds it little-endian
st1008f_crc32() {
	set -- $(printf '%s' "$1" | gzip -c | tail -c 8 | head -c 4 | hexdump -v -e '4/1 "%02x "')
	echo "$4$3$2$1"
}

# prints "good trial" from a valid record, nothing otherwise
st1008f_bootstate_read() {
	local dev line body crc
	dev=$(st1008f_bootstate_dev) || return 1
	line=$(head -c 24 "$dev" 2>/dev/null)
	body=${line%% c=*}
	crc=${line##* c=}
	case "$body" in "$ST_REC_MAGIC g="[ab]" t="[ab-]) ;; *) return 1 ;; esac
	[ "$crc" = "$(st1008f_crc32 "$body")" ] || return 1
	echo "${body#* g=}" | sed 's/ t=/ /'
}

# st1008f_bootstate_write GOOD TRIAL (TRIAL = a | b | -)
st1008f_bootstate_write() {
	local body="$ST_REC_MAGIC g=$1 t=$2" f=/tmp/st1008f-bootstate.bin
	printf '%s c=%s\n' "$body" "$(st1008f_crc32 "$body")" > $f
	mtd -q write $f bootstate || return 1
	[ "$(st1008f_bootstate_read)" = "$1 $2" ]
}
