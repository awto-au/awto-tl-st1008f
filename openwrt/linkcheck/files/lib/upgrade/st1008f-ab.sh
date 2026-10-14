# sysupgrade on tplink,tl-st1008f-v2 (#117): write the slot that is not running, then make it the trial
# slot for the next boot. Called from platform.sh platform_do_upgrade.
. /lib/st1008f-slot.sh

# stage2 ramdisk = its default tool list + RAMFS_COPY_BIN; the bootstate record also needs head
RAMFS_COPY_BIN="$RAMFS_COPY_BIN head"

st1008f_ab_upgrade() {
	local cur next
	cur=$(st1008f_slot_current)
	next=$(st1008f_slot_other "$cur")
	PART_NAME=firmware_$next
	v "A/B: running slot $cur, writing slot $next ($PART_NAME)"
	default_do_upgrade "$1"
	st1008f_bootstate_write "$cur" "$next" && v "A/B: next boot tries slot $next, fallback slot $cur" ||
		v "A/B: bootstate write FAILED: next boot stays on slot $cur"
}
