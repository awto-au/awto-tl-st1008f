# awto boot payload — entry stub.
# Launched by stock U-Boot `go 0x81000000` (DDR already up via the SPL).
# Sets a stack well above the load region, calls main(), then hangs.
.set noreorder
.section .text.start,"ax"
.globl _start
_start:
    lui   $sp, 0x81f0          # sp = 0x81f00000 (inside 512 MB DDR, clear of payload)
    ori   $sp, $sp, 0x0000
    jal   main
    nop
hang:
    b     hang
    nop
