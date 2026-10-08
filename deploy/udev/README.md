# udev rules

One rule: the SD card runs under the `bfq` I/O scheduler so that the
`IOSchedulingClass=` lines in `deploy/systemd/*.service` and the Ollama
drop-in mean something. The default `mq-deadline` ignores them.

```bash
sudo cp 60-indepensense-sdcard.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change /sys/block/mmcblk0
cat /sys/block/mmcblk0/queue/scheduler      # expect: none mq-deadline kyber [bfq]
```

The measurements behind it are in the rule file. The ordering of the
units is the main lever against SD-card contention at boot; this is the
secondary one, for the moments ordering cannot cover.
