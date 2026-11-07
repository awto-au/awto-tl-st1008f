savedcmd_gdma_test.mod := printf '%s\n'   gdma_test.o | awk '!x[$$0]++ { print("./"$$0) }' > gdma_test.mod
