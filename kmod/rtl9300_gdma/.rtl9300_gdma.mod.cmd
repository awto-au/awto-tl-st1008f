savedcmd_rtl9300_gdma.mod := printf '%s\n'   rtl9300_gdma.o | awk '!x[$$0]++ { print("./"$$0) }' > rtl9300_gdma.mod
