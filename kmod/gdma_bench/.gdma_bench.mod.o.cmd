savedcmd_gdma_bench.mod.o := mips-openwrt-linux-musl-gcc -Wp,-MMD,./.gdma_bench.mod.o.d -nostdinc -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/generated -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/generated/uapi -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/generated/uapi -include /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/compiler-version.h -include /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kconfig.h -include /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/compiler_types.h -D__KERNEL__ -DVMLINUX_LOAD_ADDRESS=0xffffffff80100000 -DLINKER_LOAD_ADDRESS=0x80100000 -DDATAOFFSET=0 -Werror -fshort-wchar -funsigned-char -fno-common -fno-PIE -fno-strict-aliasing -std=gnu11 -fms-extensions -mno-check-zero-division -mabi=32 -G 0 -mno-abicalls -fno-pic -pipe -msoft-float -Wa,-msoft-float -ffreestanding -EB -fno-stack-check -Wa,-mno-fix-loongson3-llsc -march=mips32r2 -Wa,--trap -DTOOLCHAIN_SUPPORTS_VIRT -DTOOLCHAIN_SUPPORTS_XPA -DTOOLCHAIN_SUPPORTS_CRC -DTOOLCHAIN_SUPPORTS_DSP -DTOOLCHAIN_SUPPORTS_GINV -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mach-rtl-otto -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mach-generic -I/mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mach-generic -fno-asynchronous-unwind-tables -fno-delete-null-pointer-checks -O2 -fno-allow-store-data-races -fstack-protector -fomit-frame-pointer -fno-stack-clash-protection -fno-inline-functions-called-once -fstrict-flex-arrays=3 -fno-strict-overflow -fno-stack-check -fconserve-stack -fno-builtin-wcslen -Wall -Wextra -Wundef -Werror=implicit-function-declaration -Werror=implicit-int -Werror=return-type -Werror=strict-prototypes -Wno-format-security -Wno-trigraphs -Wno-frame-address -Wno-address-of-packed-member -Wmissing-declarations -Wmissing-prototypes -Wframe-larger-than=1024 -Wno-main -Wno-type-limits -Wno-dangling-pointer -Wvla-larger-than=1 -Wno-pointer-sign -Wcast-function-type -Wno-array-bounds -Wno-stringop-overflow -Wno-alloc-size-larger-than -Wimplicit-fallthrough=5 -Werror=date-time -Werror=incompatible-pointer-types -Werror=designated-init -Wenum-conversion -Wunused -Wno-unused-but-set-variable -Wno-unused-const-variable -Wno-packed-not-aligned -Wno-format-overflow -Wno-format-truncation -Wno-stringop-truncation -Wno-override-init -Wno-missing-field-initializers -Wno-shift-negative-value -Wno-maybe-uninitialized -Wno-sign-compare -Wno-unused-parameter -g -fno-var-tracking -femit-struct-debug-baseonly  -DMODULE -mlong-calls  -DKBUILD_BASENAME='"gdma_bench.mod"' -DKBUILD_MODNAME='"gdma_bench"' -D__KBUILD_MODNAME=gdma_bench -c -o gdma_bench.mod.o gdma_bench.mod.c  

source_gdma_bench.mod.o := gdma_bench.mod.c

deps_gdma_bench.mod.o := \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/compiler-version.h \
    $(wildcard include/config/CC_VERSION_TEXT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kconfig.h \
    $(wildcard include/config/CPU_BIG_ENDIAN) \
    $(wildcard include/config/BOOGER) \
    $(wildcard include/config/FOO) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/compiler_types.h \
    $(wildcard include/config/DEBUG_INFO_BTF) \
    $(wildcard include/config/PAHOLE_HAS_BTF_TAG) \
    $(wildcard include/config/FUNCTION_ALIGNMENT) \
    $(wildcard include/config/CC_HAS_SANE_FUNCTION_ALIGNMENT) \
    $(wildcard include/config/X86_64) \
    $(wildcard include/config/ARM64) \
    $(wildcard include/config/LD_DEAD_CODE_DATA_ELIMINATION) \
    $(wildcard include/config/LTO_CLANG) \
    $(wildcard include/config/HAVE_ARCH_COMPILER_H) \
    $(wildcard include/config/KCSAN) \
    $(wildcard include/config/CC_HAS_ASSUME) \
    $(wildcard include/config/CC_HAS_COUNTED_BY) \
    $(wildcard include/config/FORTIFY_SOURCE) \
    $(wildcard include/config/UBSAN_BOUNDS) \
    $(wildcard include/config/CC_HAS_COUNTED_BY_PTR) \
    $(wildcard include/config/CC_HAS_MULTIDIMENSIONAL_NONSTRING) \
    $(wildcard include/config/CFI) \
    $(wildcard include/config/ARCH_USES_CFI_GENERIC_LLVM_PASS) \
    $(wildcard include/config/CC_HAS_BROKEN_COUNTED_BY_REF) \
    $(wildcard include/config/CC_HAS_ASM_INLINE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/compiler-context-analysis.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/compiler_attributes.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/compiler-gcc.h \
    $(wildcard include/config/ARCH_USE_BUILTIN_BSWAP) \
    $(wildcard include/config/SHADOW_CALL_STACK) \
    $(wildcard include/config/KCOV) \
    $(wildcard include/config/CC_HAS_TYPEOF_UNQUAL) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/compiler.h \
    $(wildcard include/config/CPU_MIPSR6) \
    $(wildcard include/config/CPU_MIPSR5) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/generated/asm/percpu_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/percpu_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/module.h \
    $(wildcard include/config/MODULES) \
    $(wildcard include/config/SYSFS) \
    $(wildcard include/config/MODULES_TREE_LOOKUP) \
    $(wildcard include/config/LIVEPATCH) \
    $(wildcard include/config/STACKTRACE_BUILD_ID) \
    $(wildcard include/config/ARCH_USES_CFI_TRAPS) \
    $(wildcard include/config/MODULE_SIG) \
    $(wildcard include/config/GENERIC_BUG) \
    $(wildcard include/config/KALLSYMS) \
    $(wildcard include/config/SMP) \
    $(wildcard include/config/TRACEPOINTS) \
    $(wildcard include/config/TREE_SRCU) \
    $(wildcard include/config/BPF_EVENTS) \
    $(wildcard include/config/DEBUG_INFO_BTF_MODULES) \
    $(wildcard include/config/JUMP_LABEL) \
    $(wildcard include/config/TRACING) \
    $(wildcard include/config/EVENT_TRACING) \
    $(wildcard include/config/DYNAMIC_FTRACE) \
    $(wildcard include/config/KPROBES) \
    $(wildcard include/config/HAVE_STATIC_CALL_INLINE) \
    $(wildcard include/config/KUNIT) \
    $(wildcard include/config/PRINTK_INDEX) \
    $(wildcard include/config/MODULE_UNLOAD) \
    $(wildcard include/config/CONSTRUCTORS) \
    $(wildcard include/config/FUNCTION_ERROR_INJECTION) \
    $(wildcard include/config/DYNAMIC_DEBUG_CORE) \
    $(wildcard include/config/MITIGATION_RETPOLINE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/list.h \
    $(wildcard include/config/LIST_HARDENED) \
    $(wildcard include/config/DEBUG_LIST) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/container_of.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/build_bug.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/compiler.h \
    $(wildcard include/config/TRACE_BRANCH_PROFILING) \
    $(wildcard include/config/PROFILE_ALL_BRANCHES) \
    $(wildcard include/config/OBJTOOL) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/generated/asm/rwonce.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/rwonce.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kasan-checks.h \
    $(wildcard include/config/KASAN_GENERIC) \
    $(wildcard include/config/KASAN_SW_TAGS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/types.h \
    $(wildcard include/config/HAVE_UID16) \
    $(wildcard include/config/UID16) \
    $(wildcard include/config/ARCH_DMA_ADDR_T_64BIT) \
    $(wildcard include/config/PHYS_ADDR_T_64BIT) \
    $(wildcard include/config/64BIT) \
    $(wildcard include/config/ARCH_32BIT_USTAT_F_TINODE) \
    $(wildcard include/config/KVFREE_RCU_BATCHED) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/int-ll64.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/asm-generic/int-ll64.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/bitsperlong.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitsperlong.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/asm-generic/bitsperlong.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/posix_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/stddef.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/stddef.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/posix_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/sgidefs.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/asm-generic/posix_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kcsan-checks.h \
    $(wildcard include/config/KCSAN_WEAK_MEMORY) \
    $(wildcard include/config/KCSAN_IGNORE_ATOMICS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/poison.h \
    $(wildcard include/config/ILLEGAL_POINTER_VALUE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/const.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/const.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/const.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/barrier.h \
    $(wildcard include/config/CPU_CAVIUM_OCTEON) \
    $(wildcard include/config/SGI_IP28) \
    $(wildcard include/config/CPU_HAS_WB) \
    $(wildcard include/config/WEAK_ORDERING) \
    $(wildcard include/config/WEAK_REORDERING_BEYOND_LLSC) \
    $(wildcard include/config/CPU_LOONGSON3_WORKAROUNDS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/addrspace.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mach-rtl-otto/spaces.h \
    $(wildcard include/config/RTL960X) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mach-generic/spaces.h \
    $(wildcard include/config/MIPS_AUTO_PFN_OFFSET) \
    $(wildcard include/config/32BIT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mipsregs.h \
    $(wildcard include/config/PAGE_SIZE_4KB) \
    $(wildcard include/config/PAGE_SIZE_8KB) \
    $(wildcard include/config/PAGE_SIZE_16KB) \
    $(wildcard include/config/PAGE_SIZE_32KB) \
    $(wildcard include/config/PAGE_SIZE_64KB) \
    $(wildcard include/config/MIPS_HUGE_TLB_SUPPORT) \
    $(wildcard include/config/CPU_LOONGSON64) \
    $(wildcard include/config/XPA) \
    $(wildcard include/config/SYS_SUPPORTS_MIPS16) \
    $(wildcard include/config/SYS_SUPPORTS_MICROMIPS) \
    $(wildcard include/config/CPU_MICROMIPS) \
    $(wildcard include/config/WAR_MIPS34K_MISSED_ITLB) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/linkage.h \
    $(wildcard include/config/ARCH_USE_SYM_ANNOTATIONS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/stringify.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/export.h \
    $(wildcard include/config/MODVERSIONS) \
    $(wildcard include/config/GENDWARFKSYMS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/linkage.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/hazards.h \
    $(wildcard include/config/CPU_MIPSR2) \
    $(wildcard include/config/CPU_MIPSR1) \
    $(wildcard include/config/MIPS_ALCHEMY) \
    $(wildcard include/config/CPU_BMIPS) \
    $(wildcard include/config/CPU_LOONGSON2EF) \
    $(wildcard include/config/CPU_R10000) \
    $(wildcard include/config/CPU_R5500) \
    $(wildcard include/config/CPU_SB1) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/isa-rev.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/sync.h \
    $(wildcard include/config/CPU_HAS_SYNC) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/barrier.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/stat.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/stat.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/stat.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/time.h \
    $(wildcard include/config/POSIX_TIMERS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/cache.h \
    $(wildcard include/config/ARCH_HAS_CACHE_LINE_SIZE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/kernel.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/sysinfo.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/cache.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/cache.h \
    $(wildcard include/config/MIPS_L1_CACHE_SHIFT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mach-rtl-otto/kmalloc.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/math64.h \
    $(wildcard include/config/ARCH_SUPPORTS_INT128) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/math.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/div64.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/div64.h \
    $(wildcard include/config/CC_OPTIMIZE_FOR_PERFORMANCE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/log2.h \
    $(wildcard include/config/ARCH_HAS_ILOG2_U32) \
    $(wildcard include/config/ARCH_HAS_ILOG2_U64) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/bitops.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/bits.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/bits.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/bits.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/overflow.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/limits.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/limits.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/limits.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/typecheck.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitops/generic-non-atomic.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/bitops.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/asm.h \
    $(wildcard include/config/PRINTK) \
    $(wildcard include/config/WAR_R10000_LLSC) \
    $(wildcard include/config/CC_HAS_BROKEN_INLINE_COMPAT_BRANCH) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/asm-eva.h \
    $(wildcard include/config/EVA) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/byteorder.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/byteorder/big_endian.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/byteorder/big_endian.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/swab.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/swab.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/swab.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/byteorder/generic.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/cpu-features.h \
    $(wildcard include/config/MIPS_FP_SUPPORT) \
    $(wildcard include/config/CPU_MIPSR2_IRQ_VI) \
    $(wildcard include/config/CPU_MIPSR2_IRQ_EI) \
    $(wildcard include/config/CPU_HAS_MSA) \
    $(wildcard include/config/MIPS_MT_SMP) \
    $(wildcard include/config/GENERIC_ATOMIC64) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/cpu.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/cpu-info.h \
    $(wildcard include/config/MIPS_ASID_BITS_VARIABLE) \
    $(wildcard include/config/CPU_LOONGSON3_CPUCFG_EMULATION) \
    $(wildcard include/config/MIPS_ASID_SHIFT) \
    $(wildcard include/config/MIPS_ASID_BITS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mach-generic/cpu-feature-overrides.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitops/non-atomic.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitops/non-instrumented-non-atomic.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitops/fls64.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitops/ffz.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitops/sched.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/arch_hweight.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitops/arch_hweight.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitops/const_hweight.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitops/le.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bitops/ext2-atomic.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/math64.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/time64.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/time64.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/time.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/time_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/time32.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/timex.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/timex.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/param.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/param.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/param.h \
    $(wildcard include/config/HZ) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/asm-generic/param.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/timex.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/cpu-type.h \
    $(wildcard include/config/SYS_HAS_CPU_LOONGSON2E) \
    $(wildcard include/config/SYS_HAS_CPU_LOONGSON2F) \
    $(wildcard include/config/SYS_HAS_CPU_LOONGSON64) \
    $(wildcard include/config/SYS_HAS_CPU_LOONGSON32) \
    $(wildcard include/config/SYS_HAS_CPU_MIPS32_R1) \
    $(wildcard include/config/SYS_HAS_CPU_MIPS32_R2) \
    $(wildcard include/config/SYS_HAS_CPU_MIPS32_R5) \
    $(wildcard include/config/SYS_HAS_CPU_MIPS32_R6) \
    $(wildcard include/config/SYS_HAS_CPU_MIPS64_R2) \
    $(wildcard include/config/SYS_HAS_CPU_MIPS64_R5) \
    $(wildcard include/config/SYS_HAS_CPU_MIPS64_R6) \
    $(wildcard include/config/SYS_HAS_CPU_MIPS64_R1) \
    $(wildcard include/config/SYS_HAS_CPU_R3000) \
    $(wildcard include/config/SYS_HAS_CPU_R4300) \
    $(wildcard include/config/SYS_HAS_CPU_R4X00) \
    $(wildcard include/config/SYS_HAS_CPU_TX49XX) \
    $(wildcard include/config/SYS_HAS_CPU_R5000) \
    $(wildcard include/config/SYS_HAS_CPU_R5500) \
    $(wildcard include/config/SYS_HAS_CPU_NEVADA) \
    $(wildcard include/config/SYS_HAS_CPU_R10000) \
    $(wildcard include/config/SYS_HAS_CPU_RM7000) \
    $(wildcard include/config/SYS_HAS_CPU_SB1) \
    $(wildcard include/config/SYS_HAS_CPU_CAVIUM_OCTEON) \
    $(wildcard include/config/SYS_HAS_CPU_BMIPS32_3300) \
    $(wildcard include/config/SYS_HAS_CPU_BMIPS4350) \
    $(wildcard include/config/SYS_HAS_CPU_BMIPS4380) \
    $(wildcard include/config/SYS_HAS_CPU_BMIPS5000) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/smp.h \
    $(wildcard include/config/UP_LATE_INIT) \
    $(wildcard include/config/PREEMPTION) \
    $(wildcard include/config/DEBUG_PREEMPT) \
    $(wildcard include/config/CSD_LOCK_WAIT_DEBUG) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/errno.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/errno.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/errno.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/errno.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/asm-generic/errno-base.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/cpumask.h \
    $(wildcard include/config/FORCE_NR_CPUS) \
    $(wildcard include/config/HOTPLUG_CPU) \
    $(wildcard include/config/PREFERRED_CPU) \
    $(wildcard include/config/DEBUG_PER_CPU_MAPS) \
    $(wildcard include/config/CPUMASK_OFFSTACK) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/atomic.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/atomic.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/irqflags.h \
    $(wildcard include/config/PROVE_LOCKING) \
    $(wildcard include/config/TRACE_IRQFLAGS) \
    $(wildcard include/config/PREEMPT_RT) \
    $(wildcard include/config/IRQSOFF_TRACER) \
    $(wildcard include/config/PREEMPT_TRACER) \
    $(wildcard include/config/DEBUG_IRQFLAGS) \
    $(wildcard include/config/TRACE_IRQFLAGS_SUPPORT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/irqflags_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/cleanup.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/err.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/args.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/irqflags.h \
    $(wildcard include/config/CPU_HAS_DIEI) \
    $(wildcard include/config/CPU_LOONGSON32) \
    $(wildcard include/config/IRQ_MIPS_CPU) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/generated/asm/percpu.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/percpu.h \
    $(wildcard include/config/HAVE_SETUP_PER_CPU_AREA) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/threads.h \
    $(wildcard include/config/NR_CPUS) \
    $(wildcard include/config/BASE_SMALL) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/percpu-defs.h \
    $(wildcard include/config/ARCH_MODULE_NEEDS_WEAK_PER_CPU) \
    $(wildcard include/config/AMD_MEM_ENCRYPT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/cmpxchg.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/bug.h \
    $(wildcard include/config/BUG_ON_DATA_CORRUPTION) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/bug.h \
    $(wildcard include/config/BUG) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/break.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/break.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/bug.h \
    $(wildcard include/config/DEBUG_BUGVERBOSE_DETAILED) \
    $(wildcard include/config/GENERIC_BUG_RELATIVE_POINTERS) \
    $(wildcard include/config/DEBUG_BUGVERBOSE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/instrumentation.h \
    $(wildcard include/config/NOINSTR_VALIDATION) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/once_lite.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/panic.h \
    $(wildcard include/config/PANIC_TIMEOUT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/stdarg.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/printk.h \
    $(wildcard include/config/MESSAGE_LOGLEVEL_DEFAULT) \
    $(wildcard include/config/CONSOLE_LOGLEVEL_DEFAULT) \
    $(wildcard include/config/CONSOLE_LOGLEVEL_QUIET) \
    $(wildcard include/config/EARLY_PRINTK) \
    $(wildcard include/config/DYNAMIC_DEBUG) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/init.h \
    $(wildcard include/config/MEMORY_HOTPLUG) \
    $(wildcard include/config/HAVE_ARCH_PREL32_RELOCATIONS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kern_levels.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/ratelimit_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/spinlock_types_raw.h \
    $(wildcard include/config/DEBUG_SPINLOCK) \
    $(wildcard include/config/DEBUG_LOCK_ALLOC) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/spinlock_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/qspinlock_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/qrwlock_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/lockdep_types.h \
    $(wildcard include/config/PROVE_RAW_LOCK_NESTING) \
    $(wildcard include/config/LOCKDEP) \
    $(wildcard include/config/LOCK_STAT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/dynamic_debug.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/jump_label.h \
    $(wildcard include/config/HAVE_ARCH_JUMP_LABEL_RELATIVE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/jump_label.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/cmpxchg-local.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/atomic/atomic-arch-fallback.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/atomic64.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/atomic/atomic-long.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/atomic/atomic-instrumented.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/instrumented.h \
    $(wildcard include/config/DEBUG_ATOMIC) \
    $(wildcard include/config/DEBUG_ATOMIC_LARGEST_ALIGN) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kmsan-checks.h \
    $(wildcard include/config/KMSAN) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/bitmap.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/align.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/align.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/find.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/string.h \
    $(wildcard include/config/BINARY_PRINTF) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/array_size.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/string.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/string.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/fortify-string.h \
    $(wildcard include/config/CC_HAS_KASAN_MEMINTRINSIC_PREFIX) \
    $(wildcard include/config/GENERIC_ENTRY) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/bitmap-str.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/cpumask_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/gfp_types.h \
    $(wildcard include/config/KASAN_HW_TAGS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/numa.h \
    $(wildcard include/config/NUMA_KEEP_MEMINFO) \
    $(wildcard include/config/NUMA) \
    $(wildcard include/config/HAVE_ARCH_NODE_DEV_GROUP) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/nodemask.h \
    $(wildcard include/config/HIGHMEM) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/minmax.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/nodemask_types.h \
    $(wildcard include/config/NODES_SHIFT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/random.h \
    $(wildcard include/config/VMGENID) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kernel.h \
    $(wildcard include/config/PREEMPT_VOLUNTARY_BUILD) \
    $(wildcard include/config/PREEMPT_) \
    $(wildcard include/config/DEBUG_ATOMIC_SLEEP) \
    $(wildcard include/config/MMU) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kstrtox.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sprintf.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/static_call_types.h \
    $(wildcard include/config/HAVE_STATIC_CALL) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/trace_printk.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/instruction_pointer.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/util_macros.h \
    $(wildcard include/config/FOO_SUSPEND) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/wordpart.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/random.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/ioctl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/ioctl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/ioctl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/asm-generic/ioctl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/irqnr.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/irqnr.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/page.h \
    $(wildcard include/config/PAGE_SHIFT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/smp_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/llist.h \
    $(wildcard include/config/ARCH_HAVE_NMI_SAFE_CMPXCHG) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/preempt.h \
    $(wildcard include/config/HAS_SEPARATE_PREEMPT_RESCHED_BITS) \
    $(wildcard include/config/PREEMPT_COUNT) \
    $(wildcard include/config/TRACE_PREEMPT_TOGGLE) \
    $(wildcard include/config/PREEMPT_NOTIFIERS) \
    $(wildcard include/config/PREEMPT_DYNAMIC) \
    $(wildcard include/config/PREEMPT) \
    $(wildcard include/config/PREEMPT_LAZY) \
    $(wildcard include/config/PREEMPT_NONE) \
    $(wildcard include/config/PREEMPT_VOLUNTARY) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/generated/asm/preempt.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/preempt.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/thread_info.h \
    $(wildcard include/config/THREAD_INFO_IN_TASK) \
    $(wildcard include/config/ARCH_HAS_PREEMPT_LAZY) \
    $(wildcard include/config/HAVE_ARCH_WITHIN_STACK_FRAMES) \
    $(wildcard include/config/SH) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/restart_block.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/thread_info.h \
    $(wildcard include/config/ARCH_HAS_CURRENT_STACK_POINTER) \
    $(wildcard include/config/MIPS_PGD_C0_CONTEXT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/processor.h \
    $(wildcard include/config/MIPS_VA_BITS_48) \
    $(wildcard include/config/CPU_LITTLE_ENDIAN) \
    $(wildcard include/config/CAVIUM_OCTEON_CVMSEG_SIZE) \
    $(wildcard include/config/MIPS_MT_FPAFF) \
    $(wildcard include/config/CPU_HAS_PREFETCH) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sizes.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/cachectl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/dsemul.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/inst.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/inst.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/bitfield.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/prefetch.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/vdso/processor.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/smp.h \
    $(wildcard include/config/MIPS_NR_CPU_NR_MAP) \
    $(wildcard include/config/KEXEC_CORE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/smp-ops.h \
    $(wildcard include/config/SMP_UP) \
    $(wildcard include/config/MIPS_CPS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/time32.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/time.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/uidgid.h \
    $(wildcard include/config/MULTIUSER) \
    $(wildcard include/config/USER_NS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/uidgid_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/highuid.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/buildid.h \
    $(wildcard include/config/VMCORE_INFO) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kmod.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/elf.h \
    $(wildcard include/config/ARCH_HAVE_EXTRA_ELF_NOTES) \
    $(wildcard include/config/ARCH_USE_GNU_PROPERTY) \
    $(wildcard include/config/ARCH_HAVE_ELF_PROT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/elf.h \
    $(wildcard include/config/MIPS_O32_FP64_SUPPORT) \
    $(wildcard include/config/MIPS32_N32) \
    $(wildcard include/config/MIPS32_O32) \
    $(wildcard include/config/MIPS32_COMPAT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/auxvec.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/auxvec.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/auxvec.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/fs.h \
    $(wildcard include/config/FANOTIFY_ACCESS_PERMISSIONS) \
    $(wildcard include/config/FS_POSIX_ACL) \
    $(wildcard include/config/SECURITY) \
    $(wildcard include/config/CGROUP_WRITEBACK) \
    $(wildcard include/config/IMA) \
    $(wildcard include/config/FILE_LOCKING) \
    $(wildcard include/config/FSNOTIFY) \
    $(wildcard include/config/EPOLL) \
    $(wildcard include/config/COMPAT) \
    $(wildcard include/config/FS_DAX) \
    $(wildcard include/config/SWAP) \
    $(wildcard include/config/BLOCK) \
    $(wildcard include/config/UNICODE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/fs/super.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/fs/super_types.h \
    $(wildcard include/config/QUOTA) \
    $(wildcard include/config/FS_ENCRYPTION) \
    $(wildcard include/config/FS_VERITY) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/fs_dirent.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/errseq.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/list_lru.h \
    $(wildcard include/config/MEMCG) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/shrinker.h \
    $(wildcard include/config/SHRINKER_DEBUG) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/refcount.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/refcount_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/spinlock_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rwlock_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/completion.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/swait.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/spinlock.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/interrupt_rc.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/processor.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/bottom_half.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/lockdep.h \
    $(wildcard include/config/DEBUG_LOCKING_API_SELFTESTS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mmiowb.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/mmiowb.h \
    $(wildcard include/config/MMIOWB) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/spinlock.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/generated/asm/qspinlock.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/qspinlock.h \
    $(wildcard include/config/QUEUED_SPINLOCKS_TRACE_CONTENDED_RELEASE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/tracepoint-defs.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/static_key.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/generated/asm/qrwlock.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/qrwlock.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rwlock.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/spinlock_api_smp.h \
    $(wildcard include/config/INLINE_SPIN_LOCK) \
    $(wildcard include/config/INLINE_SPIN_LOCK_BH) \
    $(wildcard include/config/INLINE_SPIN_LOCK_IRQ) \
    $(wildcard include/config/INLINE_SPIN_LOCK_IRQSAVE) \
    $(wildcard include/config/INLINE_SPIN_TRYLOCK) \
    $(wildcard include/config/INLINE_SPIN_TRYLOCK_BH) \
    $(wildcard include/config/UNINLINE_SPIN_UNLOCK) \
    $(wildcard include/config/INLINE_SPIN_UNLOCK_BH) \
    $(wildcard include/config/INLINE_SPIN_UNLOCK_IRQ) \
    $(wildcard include/config/INLINE_SPIN_UNLOCK_IRQRESTORE) \
    $(wildcard include/config/GENERIC_LOCKBREAK) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rwlock_api_smp.h \
    $(wildcard include/config/INLINE_READ_LOCK) \
    $(wildcard include/config/INLINE_WRITE_LOCK) \
    $(wildcard include/config/INLINE_READ_LOCK_BH) \
    $(wildcard include/config/INLINE_WRITE_LOCK_BH) \
    $(wildcard include/config/INLINE_READ_LOCK_IRQ) \
    $(wildcard include/config/INLINE_WRITE_LOCK_IRQ) \
    $(wildcard include/config/INLINE_READ_LOCK_IRQSAVE) \
    $(wildcard include/config/INLINE_WRITE_LOCK_IRQSAVE) \
    $(wildcard include/config/INLINE_READ_TRYLOCK) \
    $(wildcard include/config/INLINE_WRITE_TRYLOCK) \
    $(wildcard include/config/INLINE_READ_UNLOCK) \
    $(wildcard include/config/INLINE_WRITE_UNLOCK) \
    $(wildcard include/config/INLINE_READ_UNLOCK_BH) \
    $(wildcard include/config/INLINE_WRITE_UNLOCK_BH) \
    $(wildcard include/config/INLINE_READ_UNLOCK_IRQ) \
    $(wildcard include/config/INLINE_WRITE_UNLOCK_IRQ) \
    $(wildcard include/config/INLINE_READ_UNLOCK_IRQRESTORE) \
    $(wildcard include/config/INLINE_WRITE_UNLOCK_IRQRESTORE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/wait.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/generated/asm/current.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/current.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/xarray.h \
    $(wildcard include/config/XARRAY_MULTI) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/gfp.h \
    $(wildcard include/config/ZONE_DMA) \
    $(wildcard include/config/ZONE_DMA32) \
    $(wildcard include/config/ZONE_DEVICE) \
    $(wildcard include/config/COMPACTION) \
    $(wildcard include/config/CONTIG_ALLOC) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/mmzone.h \
    $(wildcard include/config/ARCH_FORCE_MAX_ORDER) \
    $(wildcard include/config/PAGE_BLOCK_MAX_ORDER) \
    $(wildcard include/config/HAVE_GIGANTIC_FOLIOS) \
    $(wildcard include/config/SPARSEMEM) \
    $(wildcard include/config/SPARSEMEM_VMEMMAP) \
    $(wildcard include/config/HUGETLB_PAGE) \
    $(wildcard include/config/CMA) \
    $(wildcard include/config/MEMORY_ISOLATION) \
    $(wildcard include/config/ZSMALLOC) \
    $(wildcard include/config/UNACCEPTED_MEMORY) \
    $(wildcard include/config/IOMMU_SUPPORT) \
    $(wildcard include/config/NUMA_BALANCING) \
    $(wildcard include/config/TRANSPARENT_HUGEPAGE) \
    $(wildcard include/config/LRU_GEN) \
    $(wildcard include/config/LRU_GEN_STATS) \
    $(wildcard include/config/LRU_GEN_WALKS_MMU) \
    $(wildcard include/config/VMEMMAP_OPTIMIZATION) \
    $(wildcard include/config/MEMORY_FAILURE) \
    $(wildcard include/config/FLATMEM) \
    $(wildcard include/config/PAGE_EXTENSION) \
    $(wildcard include/config/DEFERRED_STRUCT_PAGE_INIT) \
    $(wildcard include/config/HAVE_MEMORYLESS_NODES) \
    $(wildcard include/config/SPARSEMEM_EXTREME) \
    $(wildcard include/config/HAVE_ARCH_PFN_VALID) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/list_nulls.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/seqlock.h \
    $(wildcard include/config/CC_IS_GCC) \
    $(wildcard include/config/GCC_VERSION) \
    $(wildcard include/config/KASAN) \
    $(wildcard include/config/UBSAN_ALIGNMENT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/mutex.h \
    $(wildcard include/config/DEBUG_MUTEXES) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/osq_lock.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/debug_locks.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/mutex_types.h \
    $(wildcard include/config/MUTEX_SPIN_ON_OWNER) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/seqlock_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/pageblock-flags.h \
    $(wildcard include/config/HUGETLB_PAGE_SIZE_VARIABLE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/page-flags-layout.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/generated/bounds.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/mm_types.h \
    $(wildcard include/config/HAVE_ALIGNED_STRUCT_PAGE) \
    $(wildcard include/config/SLAB_OBJ_EXT) \
    $(wildcard include/config/HUGETLB_PMD_PAGE_TABLE_SHARING) \
    $(wildcard include/config/SLAB_FREELIST_HARDENED) \
    $(wildcard include/config/USERFAULTFD) \
    $(wildcard include/config/ANON_VMA_NAME) \
    $(wildcard include/config/HAVE_ARCH_COMPAT_MMAP_BASES) \
    $(wildcard include/config/MEMBARRIER) \
    $(wildcard include/config/ARCH_HAS_ELF_CORE_EFLAGS) \
    $(wildcard include/config/AIO) \
    $(wildcard include/config/MMU_NOTIFIER) \
    $(wildcard include/config/SPLIT_PMD_PTLOCKS) \
    $(wildcard include/config/ARCH_WANT_BATCHED_UNMAP_TLB_FLUSH) \
    $(wildcard include/config/IOMMU_MM_DATA) \
    $(wildcard include/config/KSM) \
    $(wildcard include/config/MM_ID) \
    $(wildcard include/config/SCHED_MM_CID) \
    $(wildcard include/config/SCHED_CACHE) \
    $(wildcard include/config/CORE_DUMP_DEFAULT_ELF_HEADERS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/mm_types_task.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/page.h \
    $(wildcard include/config/CPU_MIPS32) \
    $(wildcard include/config/DEBUG_VIRTUAL) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/pfn.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/io.h \
    $(wildcard include/config/DMA_NONCOHERENT) \
    $(wildcard include/config/PCI) \
    $(wildcard include/config/PCI_DRIVERS_LEGACY) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/pgtable-bits.h \
    $(wildcard include/config/ARCH_HAS_PTE_SPECIAL) \
    $(wildcard include/config/HAVE_ARCH_SOFT_DIRTY) \
    $(wildcard include/config/CPU_R3K_TLB) \
    $(wildcard include/config/CPU_HAS_RIXI) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mach-generic/mangle-port.h \
    $(wildcard include/config/SWAP_IO_SPACE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/io.h \
    $(wildcard include/config/GENERIC_IOMAP) \
    $(wildcard include/config/TRACE_MMIO_ACCESS) \
    $(wildcard include/config/HAS_IOPORT) \
    $(wildcard include/config/GENERIC_IOREMAP) \
    $(wildcard include/config/HAS_IOPORT_MAP) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/pci_iomap.h \
    $(wildcard include/config/NO_GENERIC_PCI_IOPORT_MAP) \
    $(wildcard include/config/GENERIC_PCI_IOMAP) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/logic_pio.h \
    $(wildcard include/config/INDIRECT_PIO) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/fwnode.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/memory_model.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/getorder.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kref.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rbtree.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rbtree_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rcupdate.h \
    $(wildcard include/config/PREEMPT_RCU) \
    $(wildcard include/config/TINY_RCU) \
    $(wildcard include/config/RCU_STRICT_GRACE_PERIOD) \
    $(wildcard include/config/RCU_LAZY) \
    $(wildcard include/config/RCU_STALL_COMMON) \
    $(wildcard include/config/NO_HZ_FULL) \
    $(wildcard include/config/VIRT_XFER_TO_GUEST_WORK) \
    $(wildcard include/config/RCU_NOCB_CPU) \
    $(wildcard include/config/TASKS_RCU_GENERIC) \
    $(wildcard include/config/TASKS_RCU) \
    $(wildcard include/config/TASKS_RUDE_RCU) \
    $(wildcard include/config/TREE_RCU) \
    $(wildcard include/config/DEBUG_OBJECTS_RCU_HEAD) \
    $(wildcard include/config/PROVE_RCU) \
    $(wildcard include/config/ARCH_WEAK_RELEASE_ACQUIRE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched.h \
    $(wildcard include/config/VIRT_CPU_ACCOUNTING_NATIVE) \
    $(wildcard include/config/SCHED_INFO) \
    $(wildcard include/config/SCHEDSTATS) \
    $(wildcard include/config/SCHED_CORE) \
    $(wildcard include/config/FAIR_GROUP_SCHED) \
    $(wildcard include/config/RT_GROUP_SCHED) \
    $(wildcard include/config/RT_MUTEXES) \
    $(wildcard include/config/UCLAMP_TASK) \
    $(wildcard include/config/UCLAMP_BUCKETS_COUNT) \
    $(wildcard include/config/KMAP_LOCAL) \
    $(wildcard include/config/MEM_ALLOC_PROFILING) \
    $(wildcard include/config/SCHED_CLASS_EXT) \
    $(wildcard include/config/CGROUP_SCHED) \
    $(wildcard include/config/CFS_BANDWIDTH) \
    $(wildcard include/config/BLK_DEV_IO_TRACE) \
    $(wildcard include/config/TASKS_TRACE_RCU) \
    $(wildcard include/config/TRIVIAL_PREEMPT_RCU) \
    $(wildcard include/config/MEMCG_V1) \
    $(wildcard include/config/COMPAT_BRK) \
    $(wildcard include/config/CGROUPS) \
    $(wildcard include/config/BLK_CGROUP) \
    $(wildcard include/config/PSI) \
    $(wildcard include/config/PAGE_OWNER) \
    $(wildcard include/config/EVENTFD) \
    $(wildcard include/config/ARCH_HAS_CPU_PASID) \
    $(wildcard include/config/X86_BUS_LOCK_DETECT) \
    $(wildcard include/config/TASK_DELAY_ACCT) \
    $(wildcard include/config/STACKPROTECTOR) \
    $(wildcard include/config/ARCH_HAS_SCALED_CPUTIME) \
    $(wildcard include/config/VIRT_CPU_ACCOUNTING_GEN) \
    $(wildcard include/config/POSIX_CPUTIMERS) \
    $(wildcard include/config/POSIX_CPU_TIMERS_TASK_WORK) \
    $(wildcard include/config/KEYS) \
    $(wildcard include/config/SYSVIPC) \
    $(wildcard include/config/DETECT_HUNG_TASK) \
    $(wildcard include/config/IO_URING) \
    $(wildcard include/config/AUDIT) \
    $(wildcard include/config/AUDITSYSCALL) \
    $(wildcard include/config/DETECT_HUNG_TASK_BLOCKER) \
    $(wildcard include/config/UBSAN) \
    $(wildcard include/config/UBSAN_TRAP) \
    $(wildcard include/config/TASK_XACCT) \
    $(wildcard include/config/CPUSETS) \
    $(wildcard include/config/X86_CPU_RESCTRL) \
    $(wildcard include/config/PERF_EVENTS) \
    $(wildcard include/config/ARCH_HAS_LAZY_MMU_MODE) \
    $(wildcard include/config/FAULT_INJECTION) \
    $(wildcard include/config/LATENCYTOP) \
    $(wildcard include/config/FUNCTION_GRAPH_TRACER) \
    $(wildcard include/config/UPROBES) \
    $(wildcard include/config/BCACHE) \
    $(wildcard include/config/VMAP_STACK) \
    $(wildcard include/config/BPF_SYSCALL) \
    $(wildcard include/config/KSTACK_ERASE) \
    $(wildcard include/config/KSTACK_ERASE_METRICS) \
    $(wildcard include/config/X86_MCE) \
    $(wildcard include/config/KRETPROBES) \
    $(wildcard include/config/RETHOOK) \
    $(wildcard include/config/ARCH_HAS_PARANOID_L1D_FLUSH) \
    $(wildcard include/config/RV) \
    $(wildcard include/config/RV_PER_TASK_MONITORS) \
    $(wildcard include/config/USER_EVENTS) \
    $(wildcard include/config/UNWIND_USER) \
    $(wildcard include/config/SCHED_PROXY_EXEC) \
    $(wildcard include/config/MEM_ALLOC_PROFILING_DEBUG) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/sched.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/futex_types.h \
    $(wildcard include/config/FUTEX) \
    $(wildcard include/config/FUTEX_PRIVATE_HASH) \
    $(wildcard include/config/FUTEX_ROBUST_UNLOCK) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/pid_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sem_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/shm.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/shmparam.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kmsan_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/plist_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/hrtimer_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/timerqueue_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/timer_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/seccomp_types.h \
    $(wildcard include/config/SECCOMP) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/resource.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/resource.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/resource.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/resource.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/asm-generic/resource.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/latencytop.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched/prio.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched/types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/signal_types.h \
    $(wildcard include/config/OLD_SIGACTION) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/signal.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/signal.h \
    $(wildcard include/config/TRAD_SIGNALS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/signal.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/asm-generic/signal-defs.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/sigcontext.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/sigcontext.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/siginfo.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/asm-generic/siginfo.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/syscall_user_dispatch_types.h \
    $(wildcard include/config/SYSCALL_USER_DISPATCH) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/netdevice_xmit.h \
    $(wildcard include/config/NET_ACT_MIRRED) \
    $(wildcard include/config/NET_EGRESS) \
    $(wildcard include/config/NF_DUP_NETDEV) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/task_io_accounting.h \
    $(wildcard include/config/TASK_IO_ACCOUNTING) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/posix-timers_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rseq_types.h \
    $(wildcard include/config/RSEQ) \
    $(wildcard include/config/RSEQ_SLICE_EXTENSION) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/irq_work_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/workqueue_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kcsan.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rv.h \
    $(wildcard include/config/RV_LTL_MONITOR) \
    $(wildcard include/config/RV_HA_MONITOR) \
    $(wildcard include/config/RV_REACTORS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/unwind_deferred_types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/generated/asm/kmap_size.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/kmap_size.h \
    $(wildcard include/config/DEBUG_KMAP_LOCAL) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/generated/rq-offsets.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched/ext.h \
    $(wildcard include/config/EXT_SUB_SCHED) \
    $(wildcard include/config/EXT_GROUP_SCHED) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/context_tracking_irq.h \
    $(wildcard include/config/CONTEXT_TRACKING_IDLE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rcutree.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/maple_tree.h \
    $(wildcard include/config/DEBUG_MAPLE_TREE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rwsem.h \
    $(wildcard include/config/RWSEM_SPIN_ON_OWNER) \
    $(wildcard include/config/DEBUG_RWSEMS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/uprobes.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/timer.h \
    $(wildcard include/config/DEBUG_OBJECTS_TIMERS) \
    $(wildcard include/config/NO_HZ_COMMON) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/ktime.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/jiffies.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/jiffies.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/generated/timeconst.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/vdso/ktime.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/timekeeping.h \
    $(wildcard include/config/POSIX_AUX_CLOCKS) \
    $(wildcard include/config/GENERIC_CMOS_UPDATE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/clocksource_ids.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/debugobjects.h \
    $(wildcard include/config/DEBUG_OBJECTS) \
    $(wildcard include/config/DEBUG_OBJECTS_FREE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/workqueue.h \
    $(wildcard include/config/DEBUG_OBJECTS_WORK) \
    $(wildcard include/config/FREEZER) \
    $(wildcard include/config/WQ_WATCHDOG) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/alloc_tag.h \
    $(wildcard include/config/MEM_ALLOC_PROFILING_ENABLED_BY_DEFAULT) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/codetag.h \
    $(wildcard include/config/CODE_TAGGING) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/percpu_counter.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/percpu.h \
    $(wildcard include/config/KMALLOC_PARTITION_CACHES) \
    $(wildcard include/config/NEED_PER_CPU_PAGE_FIRST_CHUNK) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/mmdebug.h \
    $(wildcard include/config/DEBUG_VM) \
    $(wildcard include/config/DEBUG_VM_IRQSOFF) \
    $(wildcard include/config/DEBUG_VM_PGFLAGS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mmu.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/page-flags.h \
    $(wildcard include/config/PAGE_IDLE_FLAG) \
    $(wildcard include/config/ARCH_USES_PG_ARCH_2) \
    $(wildcard include/config/ARCH_USES_PG_ARCH_3) \
    $(wildcard include/config/MIGRATION) \
    $(wildcard include/config/DEBUG_KMAP_LOCAL_FORCE_MAP) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/local_lock.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/local_lock_internal.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/zswap.h \
    $(wildcard include/config/ZSWAP) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/memory_hotplug.h \
    $(wildcard include/config/ARCH_HAS_ADD_PAGES) \
    $(wildcard include/config/MEMORY_HOTREMOVE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/notifier.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/srcu.h \
    $(wildcard include/config/TINY_SRCU) \
    $(wildcard include/config/NEED_SRCU_NMI_SAFE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rcu_segcblist.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/srcutree.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rcu_node_tree.h \
    $(wildcard include/config/RCU_FANOUT) \
    $(wildcard include/config/RCU_FANOUT_LEAF) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/topology.h \
    $(wildcard include/config/USE_PERCPU_NUMA_NODE_ID) \
    $(wildcard include/config/SCHED_SMT) \
    $(wildcard include/config/GENERIC_ARCH_TOPOLOGY) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/arch_topology.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/topology.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/mach-generic/topology.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/topology.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched/mm.h \
    $(wildcard include/config/MMU_LAZY_TLB_REFCOUNT) \
    $(wildcard include/config/ARCH_HAS_MEMBARRIER_CALLBACKS) \
    $(wildcard include/config/ARCH_HAS_SYNC_CORE_BEFORE_USERMODE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sync_core.h \
    $(wildcard include/config/ARCH_HAS_PREPARE_SYNC_CORE_CMD) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched/coredump.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/list_bl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/bit_spinlock.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/uuid.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/percpu-rwsem.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rcuwait.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched/signal.h \
    $(wildcard include/config/SCHED_AUTOGROUP) \
    $(wildcard include/config/BSD_PROCESS_ACCT) \
    $(wildcard include/config/TASKSTATS) \
    $(wildcard include/config/STACK_GROWSUP) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rculist.h \
    $(wildcard include/config/PROVE_RCU_LIST) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/signal.h \
    $(wildcard include/config/DYNAMIC_SIGFRAME) \
    $(wildcard include/config/PROC_FS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched/jobctl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched/task.h \
    $(wildcard include/config/HAVE_EXIT_THREAD) \
    $(wildcard include/config/ARCH_WANTS_DYNAMIC_TASK_STRUCT) \
    $(wildcard include/config/HAVE_ARCH_THREAD_STRUCT_WHITELIST) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/uaccess.h \
    $(wildcard include/config/ARCH_HAS_SUBPAGE_FAULTS) \
    $(wildcard include/config/ARCH_MEMORY_ORDER_TSO) \
    $(wildcard include/config/HARDENED_USERCOPY) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/fault-inject-usercopy.h \
    $(wildcard include/config/FAULT_INJECTION_USERCOPY) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/nospec.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/ucopysize.h \
    $(wildcard include/config/HARDENED_USERCOPY_DEFAULT_ON) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/uaccess.h \
    $(wildcard include/config/CPU_DADDI_WORKAROUNDS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/extable.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/asm-generic/access_ok.h \
    $(wildcard include/config/ALTERNATE_USER_ADDRESS_SPACE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/cred.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/capability.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/capability.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/key.h \
    $(wildcard include/config/KEY_NOTIFICATIONS) \
    $(wildcard include/config/NET) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sysctl.h \
    $(wildcard include/config/SYSCTL) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/sysctl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/assoc_array.h \
    $(wildcard include/config/ASSOCIATIVE_ARRAY) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched/user.h \
    $(wildcard include/config/VFIO_PCI_ZDEV_KVM) \
    $(wildcard include/config/IOMMUFD) \
    $(wildcard include/config/SECRETMEM) \
    $(wildcard include/config/WATCH_QUEUE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/ratelimit.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/pid.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rhashtable-types.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/posix-timers.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/alarmtimer.h \
    $(wildcard include/config/RTC_CLASS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/hrtimer.h \
    $(wildcard include/config/HIGH_RES_TIMERS) \
    $(wildcard include/config/TIME_LOW_RES) \
    $(wildcard include/config/TIMERFD) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/hrtimer_rearm.h \
    $(wildcard include/config/HRTIMER_REARM_DEFERRED) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/timerqueue.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rcuref.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/ptrace.h \
    $(wildcard include/config/CPU_HAS_SMARTMIPS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/isadep.h \
    $(wildcard include/config/CPU_R3000) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/ptrace.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rcu_sync.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/quota.h \
    $(wildcard include/config/QUOTA_NETLINK_INTERFACE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/dqblk_xfs.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/dqblk_v1.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/dqblk_v2.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/dqblk_qtree.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/projid.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/quota.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/unicode.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/dcache.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rculist_bl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/lockref.h \
    $(wildcard include/config/ARCH_USE_CMPXCHG_LOCKREF) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/stringhash.h \
    $(wildcard include/config/DCACHE_WORD_ACCESS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/hash.h \
    $(wildcard include/config/HAVE_ARCH_HASH) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/vfsdebug.h \
    $(wildcard include/config/DEBUG_VFS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/wait_bit.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kdev_t.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/kdev_t.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/path.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/radix-tree.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/semaphore.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/fcntl.h \
    $(wildcard include/config/ARCH_32BIT_OFF_T) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/fcntl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/fcntl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/asm-generic/fcntl.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/openat2.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/migrate_mode.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/delayed_call.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/ioprio.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sched/rt.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/iocontext.h \
    $(wildcard include/config/BLK_ICQ) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/ioprio.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/mount.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/mnt_idmapping.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/slab.h \
    $(wildcard include/config/FAILSLAB) \
    $(wildcard include/config/KFENCE) \
    $(wildcard include/config/SLUB_TINY) \
    $(wildcard include/config/SLUB_DEBUG) \
    $(wildcard include/config/KMALLOC_PARTITION_RANDOM) \
    $(wildcard include/config/KMALLOC_PARTITION_TYPED) \
    $(wildcard include/config/SLAB_BUCKETS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/percpu-refcount.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kasan.h \
    $(wildcard include/config/KASAN_STACK) \
    $(wildcard include/config/KASAN_VMALLOC) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kasan-enabled.h \
    $(wildcard include/config/ARCH_DEFER_KASAN) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kasan-tags.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rw_hint.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/file_ref.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/fs.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/elf.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/uapi/linux/elf-em.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/uapi/asm/hwcap.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kobject.h \
    $(wildcard include/config/UEVENT_HELPER) \
    $(wildcard include/config/DEBUG_KOBJECT_RELEASE) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/sysfs.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kernfs.h \
    $(wildcard include/config/KERNFS) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/idr.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/kobject_ns.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/moduleparam.h \
    $(wildcard include/config/ALPHA) \
    $(wildcard include/config/PPC64) \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/rbtree_latch.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/arch/mips/include/asm/module.h \
  /mnt/2tb/git/awto-tl-st1008f/tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009/include/linux/export-internal.h \
    $(wildcard include/config/PARISC) \

gdma_bench.mod.o: $(deps_gdma_bench.mod.o)

$(deps_gdma_bench.mod.o):
