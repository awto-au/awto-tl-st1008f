# Stock initramfs excerpts

Source: TL-ST1008F v2 stock RUNTIME image (Realtek SDK 3.2.0 build, 2022-01-19), gzip cpio inside the kernel,
unpacked from this unit's flash backup with `scripts/st1008_stock_extract.py`. Short quotes only; full files stay in `private/`.

## `/etc/inittab` (whole file, 2 lines)

```
::sysinit:/etc/rc
ttyS0::respawn:/bin/sh
```

## `/etc/passwd` (whole file, 1 line)

```
root::0:0:root:/:/bin/cli
```

- Empty root password. `/bin/cli` is not in the image.

## `/etc/rc` (excerpts)

Module load sequence (each guarded by an existence check and the previous result):

```
insmod drivers/net/switch/rtcore/rtcore.ko
insmod drivers/net/switch/rtk/rtk.ko
insmod drivers/net/switch/rtnic/rtnic.ko
insmod net/switch/rtdrv/rtdrv.ko
```

Network and application start (end of file):

```
ifconfig eth0 192.168.1.1
...
if [ $RESULT -eq 0 ] && [ -f "/bin/diag" ]; then
	diag
fi
```

- `diag` (Realtek SDK shell) runs in the foreground and does not return, so `inittab`'s `ttyS0` respawn is never reached.
- A JFFS2 mount of `/dev/mtdblock3` is present but commented out.

## `/etc/version`

- Paraphrased: Realtek SDK version 3.2.0, built 2022-01-19 16:32:45 CST.

## `/dev`

- Every entry (`console`, `ttyS0`, `null`, …) is a 0-byte regular file in the cpio, not a device node.
