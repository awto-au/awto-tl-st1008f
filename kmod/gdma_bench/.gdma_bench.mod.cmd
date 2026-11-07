savedcmd_gdma_bench.mod := printf '%s\n'   gdma_bench.o | awk '!x[$$0]++ { print("./"$$0) }' > gdma_bench.mod
