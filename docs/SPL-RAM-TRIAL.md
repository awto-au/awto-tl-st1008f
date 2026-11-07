# Own SPL from RAM on sw2 (#105): plan

Owner 2026-11-07: trial an own SPL (stage 1) loaded and run from RAM on sw2 only. No flash write, stock loader area `0x0`-`0xDFFFF` untouched. Facts from [DRAM.md](DRAM.md), [CLOCKS.md](CLOCKS.md), [DEFAULT-BOOT.md](DEFAULT-BOOT.md), [SDK-UBOOT-FEATURES.md](SDK-UBOOT-FEATURES.md). V = verified in repo docs/sources, I = inferred, U = unknown.

## Stock SPL today
- `loader.bin` `0x0`-`0x507f` (20,608 B) XIP at `0x9fc00000`; LPLR 16 KiB, header at +0x20; SRAM 64 KiB at `0x9f000000` (V). Stock U-Boot payload 793,720 B copied by fixed length `0xc1c78`.
- Init order (V, SDK `startup.S:76-95`): CPU/cache/SRAM init, copy SRAM code from flash, BSS, SP = SRAM top - 8; then init table: 1 `plr_init_utility`, 11 `cg_copy_info_to_sram`, 13 `cg_init` (CPU/SRAM/LX/SPIF/MEM PLLs), 20 `norsf_detect`, 30 `dram_setup` (`memctlc_init_dram`: PHY preset, DTR/MRS, ZQ, DLL reset, `DDR_Calibration`, size detect), 32 `exit_preloader`.
- Hand-off: DRAM trained at 600 MHz (DCR `0x21421003`); PLLs CPU 800 / LX 175 / SRAM 250 / SPI 25.5; `chsp_jump` passes `&otto_sc` in a0; SFCR2/EN4B set by stock U-Boot, not the SPL.
- Board-specific: stock 600 PHY preset DCSDCR1 `12120888` differs from SDK source `0c0d0888` (DRAM.md:100: source is not a faithful copy of the stock binary); Zentel A3T4GF40BBF-HP tRFC/DCR/taps. U: which `boot0412` ifdefs, LPLR table contents.

## What a RAM trial can and cannot test
| Part | From RAM |
|---|---|
| Compile, link, size; SRAM-only execution | yes |
| DDR init and tap training at 650-700 (DRAM re-init mid-run) | yes |
| Reload payload from the chain slot (read via `0xb4200000`), CRC, jump to `0x81000000` | yes |
| Watchdog recovery | yes |
| Reset vector, XIP fetch at `0xbfc00000`, cold CP0/cache state, SRAM unmap until init | no |
| PLL reset defaults, flash fetch at the reset SPI divider/mode, SFCR2/EN4B set by the SPL | no |
| DRAM power-up ordering (DRAM already running masks a missing reset/CKE step), per-unit/temperature cold margins | no |

## Variants
- A, warm DRAM: stock prompt, tftp, copy to SRAM, `go`. Tests only the hand-off contract; adds nothing over today's chain.
- B, re-train from SRAM: the SRAM program runs `cg_mem_pll_init` + `memctlc_init_dram` at the target clock, stops switch DMA and arms the watchdog first (DRAM.md:183-187), reloads our U-Boot from the installed chain slot (read only), jumps to `0x81000000` with no chain mark. Fits: stock SPL 20 KiB, SRAM 64 KiB.
- `clocks set mem` already reaches 700 MHz with MRS bins CL 11 / CWL 8 plus per-DQ retrain (`ddr-retrain --write`); 725+ fail (DRAM.md:148-152). An own SPL adds: cold boot at the target clock, full DLL/ZQ/FIFO sequence, earlier PLL/SPI timing, a boot path of our own.

## Stages (sw2, relay power-cycle as fallback, `uboot-chain-env revert`)
1. SPL v0: prints a UART marker and returns to stock. Copy to SRAM `0x9f004000` (clear of `0xb70`-`0xbbc`), `go`. Pass: marker, prompt intact, SRAM map restored.
2. Add `cg_init` as a no-op at stock values, read-only DCR/DTR/MPCR dump, diff against live.
3. Re-run DDR init at 600 (stock bin), reload payload from `0xb4200000`, jump. Pass: banner, `memtest`, `crc32` of 16 MiB.
4. Same at 650, then 700 with retrain. Pass: `memtest`, `bench`, 3 relay cycles.
5. Optional: repeat 10 times, compare sw2 taps. sw1 never.
- Host static check that the SPL image contains no SFC write/erase opcodes.
- To write (python in `scripts/`): `build_spl.py`, `spl_ramtrial.py` (through `board_guard`, `dev.py` entry), an SRAM-load command in our U-Boot. Exists: `st1008_ramload.py`, `ddr_retrain.py`, `clocks_cycle.py`, `memtest.py`, `uboot_chain_env.py`, `flash_guard.py`, `ddr_sram.S`, `clocks_sram.S`.

## Readiness for a flash decision (must be proven first)
- Warm reset with flash in 4-byte mode; a cold-boot SPL test (impossible without writing flash, no JTAG planned); a tested recovery (clip programming, SoC holding SPI, flash /RESET and tri-state behaviour: all U); stock loader backup read back with sha256; cache/SRAM init code never executed by ours; sw1 per-unit margins (never swept).
- The trial can show: our code can initialise DDR and load the chain U-Boot at a given clock on sw2 with DRAM already running. It cannot show: that it cold boots, that the reset vector and flash fetch work, that recovery works.

## Cheapest alternative to the performance goal
- `turbo` keys `cpu`, `ddr`, `lx`, `sram`, `swcore` (DEFAULT-BOOT.md). DDR 600 -> 650 moves benchmarks by 4 % or less (DRAM.md:48); the switch-core clock is the big lever for the CPU-port rate (#148). An own SPL gives the DDR gain at power-on instead of about 1 s later.

## Open questions (U)
Stock SPL source-identical to the SDK apart from DCSDCR1? Why the 600 mismatch and what the 650 branch uses; reset-vector recovery for a bad SPL image; SPI pin state during reset for clip programming; stock ifdefs (Q9); LPLR contents (Q1); a stock-like `otto_sc` in a0; write leveling above 700.
