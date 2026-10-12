# Overclock: run and recover

Facts: [OVERCLOCK.md](OVERCLOCK.md). sw2 only (relay + console); sw1 is never power-cycled.

## Run

- One step over N power cycles, ours RAM-loaded: `./dev.py clocks-cycle cpu|mem|fast [--n 5] [--mhz M] [--cpu E208:E210] [--from-flash] [--stop-on-hang]`; sequences `cpu+mem`, `mem+cpu`. Log `tmp/logs/clocks_cycle.log`, JSONL `tmp/logs/clocks_cycle.jsonl`.
- CPU values: `python3 scripts/clock_calc.py cpu <MHz>`.
- DDR read taps at a bin: `./dev.py mem-tap-sweep dqshift --mhz 650 --values -12-12` (after `./dev.py ramload uboot-mainline --from-flash`).
- Coarse first (n = 5), bisect the edge, n = 20 on the chosen setting.

## Install a U-Boot with new defaults

- sw2: `./dev.py uboot-chain-install --overwrite` (running flash OpenWrt), `./dev.py uboot-chain-env apply`, `./dev.py uboot-chain-env boot`, `./dev.py switch-check --ip 192.168.25.56`.
- sw1: `./dev.py uboot-chain-install-ssh --ip 192.168.25.48` (jffs2-log only, replaces our older copy), `./dev.py switch-check`. Active at sw1's next power-up.

## Recover

- A hang in a RAM test: the next cycle power-cycles (stock SPL, stock clocks).
- Power-up hang: the watchdog resets after 13 s; that boot runs stock clocks (`clocks: the last \`clocks fast\` did not finish`).
- Chain off: `./dev.py uboot-chain-env revert` (stock `boota`, stock clocks).
