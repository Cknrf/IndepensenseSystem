# SD Card Migration

Replacing the wearable's boot card with a SanDisk Extreme Pro 64 GB.

This document exists because the device's state is not all in git. The
repository holds the code; the card holds a device credential, an API
key, the user's saved places, the fall traces, the calibration sweep,
the cellular profile, the WiFi passwords and the Tailscale identity —
none of which are committed, and several of which cannot be regenerated
at all. Pulling the card without this list loses them.

Everything below was read off the live device on **2026-10-10** over SSH
(`cknrf@100.113.232.110`). Where a value is quoted, it is the value that
was actually on the machine, not a value from a doc.

---

## 1. Why the card is being replaced

Three independent signals, from weakest to strongest.

**The filesystem is flagged corrupt by the kernel.**

```
$ sudo tune2fs -l /dev/mmcblk0p2 | grep -E 'state|error'
Filesystem state:         clean with errors
Last error time:          Sat Oct 10 19:42:01 2026
Last error function:      ext4_validate_block_bitmap
Last error line #:        423
Last error err:           EFSCORRUPTED
```

`clean with errors` means the journal replayed, but ext4 has recorded
damage it could not repair. It survives reboots — it is a flag in the
superblock, not a transient.

**The damage is evenly spaced, which is the tell.** Every boot produces
the same class of error at near-regular block-group intervals:

```
EXT4-fs error (device mmcblk0p2): ext4_validate_block_bitmap:423:
  comm ext4lazyinit: bg 368: bad block bitmap checksum
  ... bg 496 ... bg 624 ... bg 765 ... bg 882 ...
  ... bg 1008 ... bg 1136 ... bg 1264 ... bg 1392 ... bg 1520
```

Roughly every 128 block groups. Random flash wear does not distribute
itself on a grid. A card whose controller reports more capacity than it
has does exactly this: writes past the real end wrap around and land on
top of earlier regions, so the corruption appears at the wrap period.
`ext4lazyinit` is the kernel initialising block groups it has never
touched before — in other words, the damage shows up precisely in the
parts of the "250 GB" that have never actually been used.

**The card identifies itself as unbranded.** The CID register is the
card's factory identity, and it is not a thing a filesystem can affect:

| CID field | Value | What a genuine card looks like |
|---|---|---|
| product name (`name`) | `asdfg` | `SD64G`, `SC64G`, `SL64G`, `ED4QT`… |
| manufacturer (`manfid`) | `0x000005` | SanDisk `0x000003`, Samsung `0x00001b` |
| OEM (`oemid`) | `0x000c` | `0x5344` ("SD") for SanDisk |
| serial | `0x00000012` | a wide pseudorandom value |
| date | `05/2025` | — |

`asdfg` is keyboard mash. A real manufacturer does not ship that, and a
serial of decimal 18 is not a serial. Combined with a claimed 250 GiB,
the ~24 MB/s measured throughput, and corruption on a wrap grid, this is
a counterfeit card with a falsified capacity descriptor.

**Note on `cmdline.txt`:** a previous repair attempt appended
`fsck.mode=force fsck.repair=yes` to the kernel command line. It is
still there, it runs a forced fsck on every boot, and it has not fixed
anything — because the fault is below the filesystem. **Do not carry
those two options to the new card.**

### What this does *not* excuse

The card is a real fault and worth replacing on its own evidence. But it
is not automatically the cause of every slow boot measured so far: the
~200 s model load and the 24 MB/s figure quoted throughout
`deploy/systemd/README.md` were measured *on this card*. After the swap,
**re-measure before rewriting any of those numbers in the thesis** — the
I/O-ordering work in the systemd units was justified by measurements
that a faster card may partly invalidate. That is a result to report,
not a reason to skip the measurement.

---

## 2. Is 64 GB enough?

Yes, with room to spare. The claimed 250 GB was never being used.

```
Filesystem      Size  Used Avail Use% Mounted on
/dev/mmcblk0p2  246G   22G  214G  10% /
/dev/mmcblk0p1  505M   80M  425M  16% /boot/firmware
```

22 GB used — and about 6 GB of that is disposable:

| Disposable | Size | Why |
|---|---|---|
| `~/.cache/pip` | 3.1 G | pip's wheel cache; safe to delete, never restored |
| `~/ollama-backup-0.32.1` | 2.1 G | a kept copy of an old Ollama release |
| `~/graphhopper/philippines-latest.osm.pbf` | 598 M | **unused** — `config.yml` reads `batangas.osm.pbf` |
| `IndepensenseSystem/venv/` | 32 M | a stale second venv; `.venv/` is the live one |
| `ollama qwen3:4b` | 2.5 G | benchmarking model; `config.NLU_MODEL` uses `qwen3:1.7b` |

Projected footprint on the new card, rebuilt clean:

| Component | Size |
|---|---|
| Raspberry Pi OS Trixie desktop + apt packages (`/usr`, `/var`, `/boot`) | ~11 G |
| `.venv` (torch, ultralytics, transformers, sentence-transformers…) | 1.5 G |
| `models/` (Whisper small+tiny, e5-small, MMS-TGL, Piper, 4× YOLO) | 1.3 G |
| `data/` (test corpus, calibration, battery logs, benchmarks) | 252 M |
| Ollama + `qwen3:1.7b` | 1.9 G |
| GraphHopper (jar + batangas PBF + graph-cache) | 90 M |
| Photon (jar + index) | 484 M |
| **Total** | **≈ 17 G** |

A 64 GB card formats to about 58 GiB usable, so expect **~40 GiB free**.
Comfortable. Keeping `qwen3:4b` and the Philippines PBF still leaves
~37 GiB.

---

## 3. Strategy: fresh install, not a clone

**Do not `dd` the old card onto the new one.** Three reasons:

1. The source filesystem is flagged `EFSCORRUPTED`. A block-level clone
   copies the corruption faithfully, including whatever is wrong in the
   block bitmaps.
2. The partition table claims 250 GiB. It does not fit on a 64 GB card,
   so the clone needs shrinking first — a long operation, run against a
   filesystem already known to be damaged.
3. The live `systemd` units on the card are **older than the ones in
   `deploy/systemd/`** (see §7). A clone preserves that drift; a fresh
   install is an opportunity to fix it.

A fresh Raspberry Pi OS image plus a restore of the list in §4 produces
a known-good system in roughly the same wall-clock time, and the restore
list is reusable the next time a card dies.

### Where the backup goes: the T7

The Mac is not an option — it is down to **1.7 GB free** of 229 GB. The
staging medium is the **Samsung T7 1 TB**, 391 GB free, exFAT.

```
/dev/disk4s1  932G  542G  391G  59%  /Volumes/T7
```

The plan is therefore simpler than a card-to-card copy and needs no USB
microSD reader:

1. Plug the T7 into the **Pi** (USB 3 port).
2. `rsync` the full set — irreplaceable *and* bulk — onto it locally,
   off the old card while it still reads clean. ~5.7 GB at ~28 MB/s is
   about four minutes.
3. Flash and boot the new card.
4. Plug the T7 back into the Pi and restore from it.

The T7 then stays as a durable second copy of everything, which the Mac
could never have held.

**Two exFAT caveats, and they matter:**

- **exFAT stores no POSIX permissions or ownership.** It mounts
  `noowners`. A plain file copy of `/etc/indepensense/device.key` loses
  its `0600` and its `cknrf:cknrf` owner. So anything permission- or
  ownership-sensitive must travel **inside a tar archive**, which
  records mode and owner in the archive itself. That is why §5 tars the
  root-owned state rather than copying it loose — keep it that way.
- **No symlinks.** Nothing in the backup set needs them, but do not
  extend the set to anything that does.

> **Already done:** the §4.1 irreplaceable set is on the T7 at
> `/Volumes/T7/indepensense-migration/pi-backup-20261010/` — 10 traces,
> all three tarballs verified extractable after the copy, `.env` at its
> full 853 bytes. The bulk set (§4.2) still needs step 1 above.

**Do not erase the old card until §8 passes.**

### A note on booting from the SSD instead

The Pi 5 can boot from USB, and an SSD would remove the card as a
bottleneck entirely (~400 MB/s against ~90 MB/s for a good card). It is
the right answer for a desktop Pi and the wrong one here: this is a
**body-worn device**, and a tethered 1 TB drive is not wearable. The T7
is also your general-purpose disk with 542 GB of unrelated data on it.
Staging medium, not boot medium.

### Does the old card's data read back cleanly?

Checked before trusting it as a restore source. Every file under
`models/`, `data/`, `var/`, `graphhopper/`, `photon/`, `/usr/share/ollama`
and `/etc/indepensense` was read end to end (`find -type f | xargs cat >
/dev/null`), with `dmesg` watched for new ext4 errors.

> **Result: clean.** 5.8 GB read in 3 m 31 s (≈28 MB/s) with
> `read_exit=0` on every directory, and no new `EXT4-fs error` lines —
> the count stayed at the ten `ext4lazyinit` ones already present from
> boot, which are in never-allocated block groups, not in file data.

So the data is intact *today*. That is a reason to copy it off now
rather than later, not a reason to relax about the card.

---

## 4. What must be copied

Grouped by how bad it is to lose. **Everything in §4.1 and §4.2 is
outside git** — `.env`, `models/`, `data/` and `var/*` are all
gitignored, and two items are not even inside the repo.

### 4.1 Irreplaceable (~280 MB) — back up first, to the Mac

| What | Path | Size | Lose it and… |
|---|---|---|---|
| **Backend device credential** | `/etc/indepensense/device.key` | 81 B | telemetry, guardian fetch and emergency alerts all fail auth. Re-issuing means going back to the backend repo. **Owner `cknrf:cknrf`, mode `0600`** — restore those too. |
| **Mistral API key** | `IndepensenseSystem/.env` | 853 B | cloud LLM fallback for unknown intents is gone (`INDEPENSENSE_CLOUD_API_KEY`) |
| **Saved places** | `var/places.json` | 4 K | "take me home" stops working; currently holds `cns house`, `bahay`, `this place`, `im twerk` with real coordinates |
| **Guardian cache** | `var/guardians.json` | 4 K | emergency SMS has no recipients until the next successful backend fetch |
| **Language / volume state** | `var/language` (`en`), `var/volume` (`100`) | 8 B | falls back to config defaults — trivial, but free to keep |
| **Fall traces** | `var/traces/*.csv` | 720 K | **the sensitivity/specificity evidence.** Each one cost someone an actual fall onto a mattress. These *are* committed per `.gitignore`'s negation — but `git status` on the Pi shows `var/` untracked, so **they are not actually in any commit yet.** Treat as irreplaceable until that changes. |
| **Calibration + benchmarks + test corpus** | `data/` | 252 M | `calibration/sweep.json` (90 K, magnetometer), `battery/` (160 K), `model_bench/` (148 K), `test/` (229 M), `audio/` (22 M) — thesis measurement evidence, gitignored |
| **Tailscale node identity** | `/var/lib/tailscale/` | 100 K | the Pi comes back as a *new* node with a *new* IP. `100.113.232.110` is in your notes, your SSH config and this doc. Copying this keeps the address. |
| **Network profiles** | `/etc/NetworkManager/system-connections/*.nmconnection` | 2 K | the GOMO APN plus four WiFi PSKs (`mesh3`, `house2`, `iPhone`, `BIDA_E1ED`). Re-typeable, but only if you know the passwords. |
| **SSH access** | `~/.ssh/authorized_keys` | 207 B | you lock yourself out of key-based login |
| **WirePlumber audio fix** | `~/.config/wireplumber/wireplumber.conf.d/` | 5 K | 3 files. `51-no-suspend.conf` is the repo's copy; `50-bluez-policy.conf` and `51-disable-suspension.conf` are **local only and not in the repo** |

> Secrets are copied **as files**. Do not transcribe keys or PSKs into
> this document or any other — it is committed.

### 4.2 Bulk (~5.4 GB) — copy it, do not re-download

**Copy.** The instinct to re-download because the card is bad is the
wrong way round here, for a reason specific to a thesis:

1. **The data on the card is verified good.** Every byte of this set was
   read back with zero errors (see §3). The card's fault is in
   never-allocated regions, not in these files. There is nothing to
   launder by re-downloading.
2. **Re-downloading risks silently changing the weights.** `CLAUDE.md`
   decision 3 exists precisely for this: models load from directories
   laid out once by `fetch_models.py`, and *"the weights in use are the
   ones that were tested."* A Hugging Face repo id resolves to whatever
   revision is current — `fetch_models.py` run today may not return the
   bytes it returned in June. Your `data/model_bench/` figures, the
   embedding-probe accuracy and margin numbers, and the Whisper load
   timings were all measured against **these** files. Swap them and
   every one of those numbers quietly stops describing the system you
   are writing about, with no error to tell you.
3. **The Photon index is the fragile one.** It is a third-party hosted
   country extract. Availability and versioning are outside your
   control, and it is the slowest item to rebuild.
4. **Four minutes versus an evening.** Local USB 3 copy against ~4 GB
   over dorm WiFi.

Copying wholesale is also safer than a selective re-fetch for a plainer
reason: you cannot forget to re-download something you never knew was
there. Take the whole tree.

**Two exceptions — do not copy these:**

- `graph-cache/` — rebuilt automatically on first start and coupled to
  the GraphHopper jar version. Copying a cache built by a different jar
  is how you get a startup failure that looks like corruption.
- `.venv/` — rebuild it (§4.3).

Re-download only if the T7 route is unavailable for some reason; the
commands are at the end of §6.7.

| What | Path | Size | Rebuild cost |
|---|---|---|---|
| Models | `models/` | 1.3 G | `python -m indepensense.tools.fetch_models` + `python -m piper.download_voices en_US-lessac-medium`; YOLO weights pull on first use |
| Ollama blobs | `/usr/share/ollama` | 3.6 G | `ollama pull qwen3:1.7b` (1.4 G). Drop `qwen3:4b` unless still benchmarking. |
| Photon index | `~/photon/photon_data` | 389 M | re-download the Philippines extract — the slowest item to rebuild |
| Photon jar | `~/photon/photon-1.2.0.jar` | 95 M | re-download |
| GraphHopper jar | `~/graphhopper/graphhopper-web-11.0.jar` | 47 M | re-download |
| Batangas extract | `~/graphhopper/batangas.osm.pbf` | 25 M | re-download from Geofabrik |
| Graph cache | `~/graphhopper/graph-cache` | 16 M | rebuilt automatically on first start from the PBF — **delete rather than copy**, it is version-coupled to the jar |

### 4.3 Reproducible from the repo — do not copy

Clone from GitHub on the new card instead — `main` is at `9f158b6`, 362
commits, and **the Pi's checkout is three commits behind**, so cloning
fresh also brings it up to date.

> **Every commit hash in this repo changed on 2026-10-10.** A
> `git filter-branch` wiped the message on all 362 commits and the
> restore rewrote them back, which mints new hashes for identical
> content. Any hash written down before that date no longer resolves.
> The file contents were never touched — the pre- and post-rewrite trees
> are byte-identical (`81c7feb`). Do not try to `git pull` the Pi's old
> checkout onto the restored history; clone fresh, which the migration
> does anyway.

- all of `src/`, `prompts/`, `docs/`, `deploy/`, `tools/`
- `.venv/` — recreate it. It is 1.5 GB of absolute paths baked to
  `/home/cknrf/Desktop/thesis/IndepensenseSystem/.venv`, and it was
  built `--system-site-packages` against the system Python 3.13.5 so it
  can see `python3-picamera2` from apt. Copying it only works if the
  path and the system Python match exactly; rebuilding is safer.

### 4.4 Local scratch — your call

| Path | Size | Note |
|---|---|---|
| `~/nlu-bench`, `~/nlu-bench-results` | 5 M | NLU benchmark harness + results. Small; keep if the numbers feed the thesis. |
| `~/UPS_HAT_E`, `~/UPS_HAT_E.zip` | 180 K | Waveshare vendor sample code |
| `~/.bash_history` | 46 K | occasionally the only record of how something was set up |
| `~/.claude` | 237 M | Claude Code session state; regenerates |
| `~/go.sh` | 65 B | see §7 |

---

## 5. Backup commands

> **This backup has already been taken**, and now lives on the T7 at
> `/Volumes/T7/indepensense-migration/pi-backup-20261010/` (a copy is
> still at `~/pi-backup-20261010/` on the Mac — delete that one once
> you trust the T7, the Mac is at 1.7 GB free). **252 MB**, verified
> after landing on the SSD: all three tarballs still extract,
> `device.key`
> (81 B, mode 0600), all 5 NetworkManager profiles, `tailscaled.state`,
> all 10 fall traces, `var/{language,volume,places.json,guardians.json}`,
> the full `data/` tree, `.env`, `authorized_keys`, all 3 WirePlumber
> confs, and the GraphHopper config + custom model. The commands below
> are kept so it can be re-run — before pulling the card, do re-run them
> to pick up anything changed since.

Run these **from the Mac**. They write to `~/pi-backup-20261010/`, which
is ~250 MB and fits in the 3.0 GB free.

Two macOS gotchas, both hit the first time:

- macOS ships rsync 2.6.9. `--info=progress2` does not exist — use
  `--progress` if you want output.
- The default shell is **zsh**, which does **not** word-split unquoted
  variables. `SSH="ssh -i key"; $SSH host 'cmd'` fails with
  `no such file or directory: ssh -i key`. Write the `ssh` call out in
  full, as below, rather than storing it in a variable.

```bash
PI=cknrf@100.113.232.110
DEST=~/pi-backup-20261010
mkdir -p "$DEST"/{repo,etc,var-lib,home}

# --- repo-local state (gitignored) ---
rsync -av -e "ssh -i ~/.ssh/id_ed25519_pi" \
  "$PI":Desktop/thesis/IndepensenseSystem/{.env,var} "$DEST"/repo/
rsync -av -e "ssh -i ~/.ssh/id_ed25519_pi" \
  "$PI":Desktop/thesis/IndepensenseSystem/data "$DEST"/repo/

# --- root-owned state: stage into /tmp on the Pi first, then pull ---
ssh -i ~/.ssh/id_ed25519_pi "$PI" '
  rm -rf /tmp/pibk && mkdir -p /tmp/pibk
  sudo tar czf /tmp/pibk/etc-indepensense.tgz -C / etc/indepensense
  sudo tar czf /tmp/pibk/nm-connections.tgz   -C / etc/NetworkManager/system-connections
  sudo tar czf /tmp/pibk/tailscale.tgz        -C / var/lib/tailscale
  sudo chown cknrf: /tmp/pibk/*.tgz'
rsync -av -e "ssh -i ~/.ssh/id_ed25519_pi" "$PI":/tmp/pibk/ "$DEST"/etc/

# --- user config ---
rsync -av -e "ssh -i ~/.ssh/id_ed25519_pi" \
  "$PI":{.ssh/authorized_keys,.bash_history,go.sh} "$DEST"/home/
rsync -av -e "ssh -i ~/.ssh/id_ed25519_pi" \
  "$PI":.config/wireplumber "$DEST"/home/
rsync -av -e "ssh -i ~/.ssh/id_ed25519_pi" \
  "$PI":graphhopper/{config.yml,custom_models} "$DEST"/home/graphhopper/

# --- verify ---
du -sh "$DEST"                                      # expect ~252M
for t in "$DEST"/etc/*.tgz; do echo "== $t"; tar tzvf "$t"; done
ls "$DEST"/repo/var/traces/*.csv | wc -l            # expect 10
test -s "$DEST"/repo/.env && echo ".env present"
```

The three tarballs should list, respectively:
`etc/indepensense/device.key` (81 B, `-rw-------`, `cknrf cknrf`); five
`*.nmconnection` files; and `var/lib/tailscale/tailscaled.state`. If
`tailscaled.state` is missing, the Tailscale identity is not backed up
and the Pi will come back on a different IP.

`var/traces/` is the one to eyeball — there were **10** CSVs on the card
on 2026-10-10. If the count comes back short, stop and check before
going further.

---

## 6. Rebuilding the new card

Ordered so that anything that needs a reboot happens before the long
downloads.

### 6.1 Flash

Raspberry Pi Imager → **Raspberry Pi OS (64-bit, Trixie, Desktop)**. In
the advanced options set, to match the old card:

| Setting | Value |
|---|---|
| Hostname | `cknrf` |
| Username | `cknrf` (uid must land on 1000 — it will, as the first user) |
| Locale | `en_GB.UTF-8` |
| Timezone | `Asia/Manila` |
| Keyboard | `us`, model `pc105` |
| WiFi country | `PH` |
| Enable SSH | yes, with `authorized_keys` from the backup |

The username matters more than it looks: `User=cknrf` is hardcoded in
`deploy/systemd/indepensense.service`, in
`deploy/polkit/50-indepensense-modemmanager.rules`, and
`XDG_RUNTIME_DIR=/run/user/1000` assumes uid 1000.

### 6.2 Boot config

Append to `/boot/firmware/config.txt` — this is the block the old card
carried, and without it there is no magnetometer bus and no ultrasonic
UARTs:

```ini
[all]
dtparam=uart0=on
dtoverlay=uart4
dtoverlay=i2c-gpio,bus=4,i2c_gpio_sda=8,i2c_gpio_scl=9
usb_max_current_enable=1
```

Confirm these are present in the stock section too (they are defaults,
but check): `dtparam=i2c_arm=on`, `dtparam=audio=on`,
`camera_auto_detect=1`, `dtoverlay=vc4-kms-v3d`.

In `/boot/firmware/cmdline.txt`, keep `cfg80211.ieee80211_regdom=PH`.
**Do not** add `fsck.mode=force fsck.repair=yes` — that was the failed
repair attempt on the old card. Leave `PARTUUID=` and `/etc/fstab`
alone; the new card has its own PARTUUID and the imager writes both.

### 6.3 Interfaces and groups

```bash
sudo raspi-config nonint do_ssh 0
sudo raspi-config nonint do_vnc 0
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_camera 0
# SPI stays disabled — it was disabled on the old card and nothing uses it

sudo usermod -aG dialout,i2c,gpio,audio,video,render,input,netdev,plugdev,adm cknrf
```

Reboot. Then confirm the old card's group set (`ollama` is added later
by the Ollama installer):

```
cknrf adm dialout cdrom sudo audio video plugdev games users netdev
ollama gpio i2c spi render input
```

Autologin was on (`lightdm` → `autologin-user=cknrf`,
`autologin-session=rpd-labwc`, plus a `getty@tty1` drop-in). Set it with
`sudo raspi-config` → System Options → Boot / Auto Login → Desktop
Autologin if you want the same behaviour.

### 6.4 System packages

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y \
  python3-picamera2 libportaudio2 libsndfile1 \
  tesseract-ocr tesseract-ocr-tgl \
  openjdk-21-jre-headless zstd \
  modemmanager i2c-tools gpiod libcamera-apps \
  alsa-utils htop git
```

Sources: `requirements-pi.txt` (picamera2, portaudio, sndfile,
tesseract), `docs/graphhopper.md` and `docs/photon.md` (Java, zstd),
`docs/sim7600.md` (ModemManager).

### 6.5 Repo and venv

```bash
mkdir -p ~/Desktop/thesis && cd ~/Desktop/thesis
git clone https://github.com/cknrf/IndepensenseSystem.git
cd IndepensenseSystem

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e . -r requirements.txt -r requirements-pi.txt
```

`--system-site-packages` is required — `picamera2` comes from apt and
cannot be pip-installed. The path must be exactly
`/home/cknrf/Desktop/thesis/IndepensenseSystem`; every systemd unit
hardcodes it.

Restore `go.sh`, which is just the shortcut you use to get into the venv:

```bash
cat > ~/go.sh <<'EOF'
cd Desktop/thesis/IndepensenseSystem
source .venv/bin/activate
EOF
chmod +x ~/go.sh     # use as:  source ~/go.sh
```

### 6.6 Restore state

```bash
B=~/pi-backup-20261010      # copied over from the Mac

# repo-local
cp -a "$B"/repo/.env  ~/Desktop/thesis/IndepensenseSystem/
cp -a "$B"/repo/var   ~/Desktop/thesis/IndepensenseSystem/
cp -a "$B"/repo/data  ~/Desktop/thesis/IndepensenseSystem/

# device credential — ownership and mode matter
sudo tar xzf "$B"/etc/etc-indepensense.tgz -C /
sudo chown cknrf:cknrf /etc/indepensense/device.key
sudo chmod 600         /etc/indepensense/device.key

# network profiles
sudo tar xzf "$B"/etc/nm-connections.tgz -C /
sudo chmod 600 /etc/NetworkManager/system-connections/*.nmconnection
sudo systemctl restart NetworkManager

# tailscale identity — service must be stopped while the state is swapped
sudo systemctl stop tailscaled
sudo tar xzf "$B"/etc/tailscale.tgz -C /
sudo systemctl start tailscaled
tailscale status        # expect 100.113.232.110

# audio
cp -a "$B"/home/wireplumber ~/.config/
systemctl --user restart wireplumber
```

### 6.7 Models and sidecars

**Step 1 — capture to the T7, on the OLD card, before flashing.**
Plug the T7 into a USB 3 port on the Pi. Trixie's kernel mounts exFAT
natively; if it does not appear, `sudo apt install -y exfatprogs`.

```bash
lsblk -o NAME,SIZE,FSTYPE,LABEL          # find the T7
sudo mkdir -p /mnt/t7 && sudo mount /dev/sda1 /mnt/t7
T=/mnt/t7/indepensense-migration/bulk && mkdir -p "$T"

rsync -a --info=stats2 ~/Desktop/thesis/IndepensenseSystem/models "$T"/
sudo rsync -a /usr/share/ollama "$T"/
rsync -a ~/photon "$T"/
rsync -a --exclude graph-cache --exclude philippines-latest.osm.pbf \
         ~/graphhopper "$T"/

sync && du -sh "$T"/*            # expect ~1.3G models, ~3.6G ollama,
                                 # ~484M photon, ~72M graphhopper
sudo umount /mnt/t7
```

The two exclusions are deliberate: `graph-cache` is rebuilt on first
start and is coupled to the jar version, and the Philippines PBF is
unused (§2).

**Step 2 — restore onto the NEW card**, T7 mounted at `/mnt/t7` again:

```bash
T=/mnt/t7/indepensense-migration/bulk

rsync -a "$T"/models/ ~/Desktop/thesis/IndepensenseSystem/models/
rsync -a "$T"/photon/ ~/photon/
rsync -a "$T"/graphhopper/ ~/graphhopper/

sudo rsync -a "$T"/ollama/ /usr/share/ollama/
sudo chown -R ollama:ollama /usr/share/ollama    # exFAT carried no ownership
```

That `chown` is not optional — exFAT stores no ownership, so everything
arrives owned by whoever ran the copy and `ollama.service` (which runs
as `User=ollama`) cannot read its own blobs.

**Fallback only — re-download.** Read §4.2 first; this risks changing
the weights your benchmarks were measured against.

```bash
cd ~/Desktop/thesis/IndepensenseSystem && source .venv/bin/activate
python -m indepensense.tools.fetch_models
cd models/voices && python -m piper.download_voices en_US-lessac-medium
# GraphHopper + Photon: follow docs/graphhopper.md and docs/photon.md
```

Ollama itself, either route:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen3:1.7b        # skip if /usr/share/ollama was copied
ollama list                   # expect qwen3:1.7b
```

### 6.8 Services

Install from the **repo**, not from a copy of the old card's
`/etc/systemd/system` — see §7.

```bash
cd ~/Desktop/thesis/IndepensenseSystem

sudo cp deploy/systemd/{indepensense,graphhopper,photon,ollama-warmup}.service \
        /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo cp deploy/systemd/ollama.service.d/override.conf \
        /etc/systemd/system/ollama.service.d/

sudo cp deploy/polkit/50-indepensense-modemmanager.rules /etc/polkit-1/rules.d/
sudo systemctl restart polkit

sudo cp deploy/udev/60-indepensense-sdcard.rules /etc/udev/rules.d/

sudo systemctl daemon-reload
sudo systemctl enable --now ollama graphhopper photon ollama-warmup indepensense
```

The udev rule is the one genuinely missing from the old card — see §7.

### 6.9 Cellular

The restored NetworkManager profile carries the GOMO APN, so this should
come up on its own. Verify:

```bash
mmcli -L                        # expect SIMCOM_SIM7600G-H
mmcli -m any | grep -E 'state|signal|own'
nmcli con show --active | grep gomo
```

Expected, from the old card:

| | |
|---|---|
| APN | `internet.globe.com.ph` |
| Profile | `gomo`, `autoconnect-priority=10`, `autoconnect-retries=0` |
| Own number | `639760365713` |
| IMEI | `862636058626654` |
| Operator ID | `51502` (Globe PH) |
| Firmware | `LE20B04SIM7600G22`, carrier config `ROW_Gen_VoLTE` |

If `mmcli -L` is empty on a fresh ModemManager install, `docs/sim7600.md`
§"After a fresh apt install modemmanager" covers it.

---

## 7. Drift found on the live card

Worth knowing before you copy anything from `/etc`, and worth a line in
the implementation chapter: **the running units are an older generation
than the ones in the repo.** The repo is correct; the card was never
updated.

| Unit | Live | Repo (`deploy/systemd/`) |
|---|---|---|
| `indepensense.service` | `Type=simple`; `After=… graphhopper photon` | `Type=notify` + `NotifyAccess=main` + `TimeoutStartSec=15min`; **`After=network-online.target ollama.service` only** |
| `graphhopper.service` | `After=network-online.target` | `After=… indepensense.service`, plus `Nice=10` and `IOSchedulingClass/Priority` |
| `photon.service` | `After=network-online.target` | same treatment as GraphHopper |
| `ollama-warmup.service` | shell `curl` + unbounded `ExecStartPre` wait; `TimeoutStartSec=180` | `User=cknrf`, `ExecStart=… -m indepensense.tools.warm_nlu`, `TimeoutStartSec=240` |

The live units still have the sidecars starting *before* the wearable —
the exact ordering the repo's comments say was measured and reversed
because a second reader nearly tripled the Whisper load. Installing from
the repo is what makes the measured ordering actually take effect.

Two more gaps on the live card:

- **The bfq udev rule was never installed.** `/etc/udev/rules.d/`
  contains only `99-rpi-keyboard.rules`, and
  `/sys/block/mmcblk0/queue/scheduler` reads `[mq-deadline]`. Every
  `IOSchedulingClass=` line in the sidecar units and the Ollama drop-in
  has therefore been **inert** — the repo's own
  `deploy/udev/README.md` says as much. Install it on the new card.
- **`/var/swap` exists (2.0 GB) but is not active.** `swapon --show`
  lists only `zram0`. A 2 GB file is sitting on the card doing nothing.
  Don't recreate it; `dphys-swapfile` is off by default and zram is
  enough.

Already correct on the live card and worth keeping: the polkit rule is
installed, and the WirePlumber drop-in is in place.

---

## 8. Verification

Run in order. Each line should produce the stated result before you
consider erasing the old card.

**Card is genuine**

```bash
cat /sys/block/mmcblk0/device/name     # expect a real SanDisk PNM, not 'asdfg'
cat /sys/block/mmcblk0/device/manfid   # expect 0x000003
sudo tune2fs -l /dev/mmcblk0p2 | grep 'Filesystem state'   # expect 'clean'
```

Then verify the capacity is real, because that is the fault being fixed:

```bash
sudo apt install -y f3
f3write /path/on/card && f3read /path/on/card    # hours, but definitive
```

Worth the time once. A second counterfeit would present identically to
the first, and you would not find out until the thesis demo.

**Throughput — re-measure, do not assume**

```bash
sudo hdparm -t --direct /dev/mmcblk0
# old card: ~24 MB/s. An Extreme Pro should read 80-90 MB/s on a Pi 5.
```

Record this. It is the number that justifies revisiting the boot-ordering
measurements in `deploy/systemd/README.md`.

**Hardware present**

```bash
sudo i2cdetect -y 1    # expect 0x68 (MPU6050) and 0x2d (UPS HAT)
sudo i2cdetect -y 4    # expect 0x2c (magnetometer, software bus on GPIO 8/9)
ls /dev/ttyAMA0 /dev/ttyAMA4            # the two DYP-A22 ultrasonics
rpicam-hello --list-cameras             # expect imx708_wide
aplay -l && arecord -l                  # expect card 0 'EarPods', playback + capture
```

**Audio levels** — these were the values in use, and the mic one matters:

```bash
wpctl get-volume @DEFAULT_AUDIO_SINK@     # expect 1.00
wpctl get-volume @DEFAULT_AUDIO_SOURCE@   # expect 0.60
amixer -c 0 sset Mic 60%                  # if it came up different
```

**Services**

```bash
systemctl is-active indepensense graphhopper photon ollama
systemctl status indepensense | head -5   # Type=notify: 'started' = voice stack loaded
curl -s localhost:8989/health             # GraphHopper
curl -s 'localhost:2322/api?q=batangas'   # Photon
curl -s localhost:11434/api/tags | grep qwen3
```

**Application**

```bash
cd ~/Desktop/thesis/IndepensenseSystem && source .venv/bin/activate
pytest                                     # full unit suite, no hardware needed
python -m indepensense.tools.system_performance --csv
```

Then the README's **First-Boot Verification Checklist** (§366) end to
end, and at minimum these manual tests, because they are the ones that
exercise restored state rather than code:

- emergency SMS — proves `device.key` and the polkit rule both survived
- a navigation command to a saved place — proves `var/places.json`
- a Tagalog utterance — proves the MMS voice and `var/language`
- the cue test from `docs/audio-portaudio.md` — proves the WirePlumber
  drop-in took (five cues at 3 s gaps, five audible sounds)

**Only after all of the above passes, erase the old card** — and
consider keeping it, unformatted and labelled, as the physical artifact
behind §1 if the thesis discusses the fault.

---

## 9. Machine-state reference

What was on the old card, for comparison after the swap.

### Identity

| | |
|---|---|
| Hostname | `cknrf` |
| OS | Debian GNU/Linux 13 (trixie), `aarch64` |
| Kernel | `6.18.33+rpt-rpi-2712` |
| Python | 3.13.5 (system), venv built `--system-site-packages` |
| Locale / TZ | `en_GB.UTF-8` / `Asia/Manila` (PST, +0800) |
| Tailscale | `cknrf` → `100.113.232.110`, `cknrf.tail704f38.ts.net` |
| User | `cknrf`, uid 1000 |

### Hardware detected

| Bus / port | Address | Device |
|---|---|---|
| `i2c-1` | `0x68` | MPU6050 IMU (`config.MPU6050_ADDRESS`) |
| `i2c-1` | `0x2d` | Waveshare UPS HAT (E) (`config.UPS_HAT_I2C_ADDRESS`) |
| `i2c-4` (GPIO 8/9, software) | `0x2c` | magnetometer (`config.MAG_ADDRESS`) |
| `/dev/ttyAMA0` | — | DYP-A22 ultrasonic, top |
| `/dev/ttyAMA4` | — | DYP-A22 ultrasonic, bottom |
| USB `1e0e:9001` | `ttyUSB0-4`, `cdc-wdm0`, `wwan0` | SIM7600G-H (GPS on `ttyUSB1`, AT on `ttyUSB2/3`) |
| USB `0020:0b21` | card 0 | "EarPods" USB audio — playback **and** capture |
| CSI | — | `imx708_wide` (Camera Module 3 Wide, 4608×2592) |

GPIO assignments live in `config.py` and `docs/hardware.md` — PTT 23,
emergency 25, repeat 24, buzzer 18, vibration 17/27/22.

### Services on the old card

Enabled and project-relevant: `indepensense`, `graphhopper`, `photon`,
`ollama`, `ollama-warmup`, `ModemManager`, `NetworkManager`,
`tailscaled`, `ssh`, `lightdm`, `wayvnc`, `bluetooth`, `cron`.

`ollama-warmup` was in `failed` state at the time of inventory, and
`indepensense` was `inactive` — both expected, since the device was
being inspected rather than worn.

### Project paths

| | |
|---|---|
| Repo | `/home/cknrf/Desktop/thesis/IndepensenseSystem` |
| Venv | `<repo>/.venv` (360 packages) |
| Models | `<repo>/models/` — `whisper/{small,tiny}`, `embeddings/multilingual-e5-small`, `voices/mms-tts-tgl` + `en_US-lessac-medium.onnx`, `yolov8{n,s,m}-oiv7.pt` + `yolov8n.pt` |
| Active YOLO | `models/yolov8m-oiv7.pt` (`config.YOLO_MODEL_PATH`) |
| Device key | `/etc/indepensense/device.key` |
| GraphHopper | `~/graphhopper`, port 8989 (admin 8990), profile `foot`, `batangas.osm.pbf` |
| Photon | `~/photon`, port 2322 |
| Ollama | port 11434, `qwen3:1.7b` active, `qwen3:4b` present |
| Backend | `https://indepensense-api.maendou.com` |

### Git state at inventory

Mac `main` = `9f158b6` (post-rewrite). Pi checkout 3 behind, with `var/`
and `.claude/` untracked. Cloning fresh on the new card picks up the
three missing commits.
