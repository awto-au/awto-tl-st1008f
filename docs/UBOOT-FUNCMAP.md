# TL-ST1008F stock U-Boot — SDK function map (loader.bin ↔ dms1250 System.map)

Narrative & dead ends: see [HISTORY.md](HISTORY.md).

Read-only static reverse. Names SDK functions compiled into our `loader.bin` by aligning
against the reyalo **rtk-dms1250** reference build (same U-Boot 2011.12 + longan DAL, same
`0x83f00000` base, different build → addresses differ). Reference for addresses + ABI + method.

Evidence tags: **[BIN]** our loader.bin, **[ELF]** dms1250 `u-boot` ELF symbols,
**[MAP]** System.map, **[SRC]** GPL source line, **SPEC** inferred.

- Our binary: `private/stock-loader-20261007/loader.bin` (local only; 896 KiB, CRC32 `e579e61c`).
- Reference: `sources/uboot-dms1250/{System.map,u-boot}` in a clone of `github.com/reyalo/Realtek`.
- Tooling: [scripts/st1008_uboot_funcmap.py](../scripts/st1008_uboot_funcmap.py) (`align`, `resolve`). Log `tmp/logs/st1008_uboot_funcmap.log`.

---

## 1. Alignment

### Address ↔ file maps (both verified against `addiu sp,sp,-X` prologues)

- **ours**: `VA = file_off − 0x5080 + 0x83f00000`. **[BIN]** `do_rtk`@0x83f1679c = file 0x1b81c =
  `0x27bdffa0` (addiu sp,sp,-0x60); `rtk_network_on`@0x83f199c4 = file 0x1ea44 = `0x27bdffd0`.
- **dms1250**: ELF section `.dram` @ file 0x5040, VA 0x83f00000, size 0xbedd8 — relocated main
  text, every named symbol at the same VA as System.map. `VA = file_off − 0x5040 + 0x83f00000`. **[ELF]**

### Offset is region-dependent

Four string-xref anchors (byte-identical load of the same literal in both builds, backscanned to the prologue):

| function | our VA [BIN] | map VA [MAP] | map−our | anchor string |
|---|---|---|---|---|
| `main_loop` | 0x83f0a1a4 | 0x83f09de0 | **−0x3c4** | `RTL9300# ` |
| `do_parterase` | 0x83f1668c | 0x83f16b34 | **+0x4a8** | `Forbid to erase LOADER partition` |
| `do_rtk` | 0x83f1679c | 0x83f16c44 | **+0x4a8** | `hw_profile_list` |
| `rtk_network_on` | 0x83f199c4 | 0x83f17c3c | **−0x1d88** | `Please wait for PHY init-time` |

Non-monotonic → TP-Link inserted/removed code between regions. Each target is resolved on its own anchor.

### Resolution methods

- **string-xref** — byte-identical `lui`+`addiu`/`ori` (or data-pointer) load of a shared literal, backscan to prologue.
- **content-match** — mask low-16 of every address-bearing insn (lui/addiu/ori/lw/sw/branch) and j/jal
  targets; search our text for the masked signature. Works on functions TP-Link did not edit; fails on the
  customised ones (`rtk_network_on`, `dal_longan_sds_init`), which are pinned by string-xref or callee set.
- Cross-check: content-match puts `uboot_sdk_init` at `0x83f14ef4` and `do_rtk` at `0x83f1679c`, equal to the
  independently derived anchors in [UBOOT-REFERENCE.md](UBOOT-REFERENCE.md).

Confidence: **CONFIRMED** = two methods or unique callee set; **STRONG** = one clean content-match with
verified prologue + internal call graph; **SPEC** = inferred.

---

## 2. Resolved functions in our binary

MIPS o32: args `a0..a3`, 5th+ on stack, return `v0`. `unit` = 0.

| function | our VA [BIN] | map VA | C signature [SRC] | conf |
|---|---|---|---|---|
| `dal_longan_sds_rxCali` | **0x83f8dd70** | 0x83f85790 | `(uint32 unit, uint32 sdsId, uint32 retryCnt)` — `dal_longan_sds.c:4107` | CONFIRMED |
| `dal_longan_sds_rxCali_start` | **0x83f8dc10** | 0x83f85630 | `(uint32 unit, uint32 sdsId)` — `:4058` | CONFIRMED |
| `dal_longan_sds_init` | **0x83f8ebe4** | 0x83f86604 | `(uint32 unit)` — `:4703` | CONFIRMED (callee set) |
| `dal_longan_sds_mode_set` | **0x83f8dfb8** | 0x83f859d8 | `(uint32 unit, uint32 sds, rt_serdesMode_t mode)` — `:1335` | STRONG |
| `dal_longan_sds_rxCaliConf_set` | **0x83f877d0** | 0x83f7f1d4 | `(uint32 unit, uint32 sdsId, rtk_sds_rxCaliConf_t conf)` — `:4004` | STRONG |
| `dal_longan_sds_10gRxIdle_get` | **0x83f8af54** | 0x83f82958 | `(uint32 unit, uint32 sds, uint32 *rxIdle)` | STRONG |
| `dal_longan_sds_rx_rst` | **0x83f88240** | 0x83f7fc44 | `(uint32 unit, uint32 sdsId)` — `:1971` | STRONG |
| `dal_longan_sds_clk_routine` | **0x83f89ef0** | 0x83f818f4 | `(uint32 unit, ...)` | STRONG |
| `dal_longan_sds_linkFault_check` | **0x83f8b0f8** | 0x83f82afc | `(uint32 unit, ...)` | STRONG |
| `hal_serdes_reg_get` | **0x83f2de5c** | 0x83f2fb68 | `(uint32 unit, uint32 sds, uint32 page, uint32 reg)` | STRONG |
| `phy_sdsRxCaliStatus_get` | **0x83f26504** | 0x83f29fa4 | `(… , status*)` | STRONG |
| `uboot_sdk_init` | **0x83f14ef4** | 0x83f1549c | `(uint32 phase)` | CONFIRMED |
| `dal_longan_init` | **0x83f6fe8c** | 0x83f67a48 | `(uint32 unit)` | STRONG |
| `rtk_network_on` | **0x83f199c4** | 0x83f17c3c | `(void)` — `uboot_func.c:422` | CONFIRMED |
| `do_rtk` | **0x83f1679c** | 0x83f16c44 | `cmd_tbl` handler `(cmd_tbl_t*, int, int, char**)` | CONFIRMED |
| `otto_spi_flash_read` | **0x83f00d84** | 0x83f00d18 | `(struct spi_flash*, u32 offset, size_t len, void *buf)` — `otto_spi_flash.c:10` | STRONG |
| `norsf_read` | **0x83f022e8** | 0x83f02210 | `(const norsf_g2_info_t*, u32 offset, u32 len, void *buf, u32 verbose)` — `:147` | STRONG |
| `swnic_send` | **0x83f1f0f4** | 0x83f1fa64 | `(… packet, len)` — switch-NIC TX | STRONG |
| `drv_nic_rx_start` | **0x83f1edb4** | 0x83f1f770 | `(void)` — arm NIC RX | STRONG |

- Call-graph check: `dal_longan_sds_rxCali`@0x83f8dd70 does `jal 0x83f8dc10` at body +88, the content-match
  address of `rxCali_start`, at the same offset as the reference.
- Boot path calls `dal_longan_sds_rxCali(0, sds, 0)` (single shot) **[SRC]** `dal_longan_sds.c:4773`.

---

## 3. Present but not reachable from a command

- Static `jal`-reachability from `do_rtk`: **252 / 1377** detected prologues reachable. The `dal_longan_sds_*`
  cluster is not in that set.
- The longan DAL dispatches through pointer tables (`dal_longan_mapper.c`), so jal-reachability under-counts.
  These functions run only via the boot-time chain `uboot_sdk_init(RTK)` → `dal_longan_init` → mapper →
  `dal_longan_sds_init` → cluster. No `rtk` subcommand or TP-Link top-level command reaches them; the dms1250
  commands that would (`sfp-speed`, `port enable` handler, waMon) are absent from this subset.
- Standalone invocation would need `go <addr>` with a loaded stub.

| area | function | our VA | note |
|---|---|---|---|
| serdes cali | `dal_longan_sds_rxCali` | 0x83f8dd70 | adaptive RX cali w/ retry count |
| serdes cali | `dal_longan_sds_rxCali_start` | 0x83f8dc10 | one foreground pass |
| serdes cali | `dal_longan_sds_rxCaliConf_set` | 0x83f877d0 | load cali params |
| serdes | `dal_longan_sds_init` | 0x83f8ebe4 | per-sds init (boot chain only) |
| serdes | `dal_longan_sds_mode_set` | 0x83f8dfb8 | set `rt_serdesMode_t` |
| serdes | `dal_longan_sds_rx_rst` | 0x83f88240 | RX reset |
| serdes | `dal_longan_sds_clk_routine` | 0x83f89ef0 | post-cali clock routine |
| serdes | `dal_longan_sds_linkFault_check` | 0x83f8b0f8 | link-fault check |
| serdes | `dal_longan_sds_10gRxIdle_get` | 0x83f8af54 | rxIdle gate read |
| serdes diag | `phy_sdsRxCaliStatus_get` | 0x83f26504 | cali OK/FAIL status |
| hal | `hal_serdes_reg_get` | 0x83f2de5c | wrapped by `rtk sdsreg get` (command-reachable) |
| nic | `swnic_send` | 0x83f1f0f4 | raw TX |
| nic | `drv_nic_rx_start` | 0x83f1ee00 | arm RX |
| flash | `otto_spi_flash_read` | 0x83f00d84 | SPI-NOR read |
| flash | `norsf_read` | 0x83f022e8 | NOR serial-flash read |

Note: `drv_nic_rx_start` is listed at `0x83f1edb4` in §2 and `0x83f1ee00` here (both carried from the
original analysis); re-run `resolve drv_nic_rx_start` to settle it.

Extend: `scripts/st1008_uboot_funcmap.py resolve <mapname> ...`.

---

## 4. Status

**CONFIRMED**
- Both address↔file maps, verified on prologues.
- Region-dependent build offset (4 anchors, −0x1d88…+0x4a8).
- Two-method resolution, cross-checked against independent anchors and the rxCali→rxCali_start call.
- sds cali cluster reachable only via the boot-time DAL pointer-table chain.

**SPEC**
- Exact arg types of `clk_routine`, `linkFault_check`, `phy_sdsRxCaliStatus_get`.
- `swnic_send` / `drv_nic_rx_start` argument layout (signatures from dms1250, not re-derived).
