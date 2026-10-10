# Deferred Tasks

## 1. Raspberry Pi 5 SD Card Audit & Backup
**Status:** Complete, deferred for execution  
**Date:** 2026-10-10  
**Details:** See `/Users/cknrf/.../scratchpad/AUDIT_SUMMARY.md` and `BACKUP_CHECKLIST.md`

### Key Findings
- **Safety features up: 17.8s** ✓ (target met)
- **Voice stack ready: 134.5s** (Whisper 72.9s is bottleneck)
- **Full system ready: 225s**

### 🔴 Anomalies to Investigate
1. Guardian fetch shows 24-minute duration in logs (inconsistent with profile)
2. LLM warmup times out after 90s (non-blocking but slow)

### 🔑 Critical Files to Backup Before SD Swap
- `/etc/indepensense/device.key` (81 B) — Device identity, cannot regenerate
- `var/` (~500 KB) — User state, saved places, battery flags
- `~/.ssh/authorized_keys` (250 B) — SSH access
- Optional: `models/` (1.3 GB) or recreate with `fetch_models.py`

### Next Action
Back up critical files to Mac before replacing SD card (suspected corrupted/fake).

---

## 2. OSM Batangas Map Testing on Pi
**Status:** Map file ready locally, needs transfer & testing  
**Date:** 2026-10-10  
**File:** `~/Downloads/batangas-map/batangas.osm.pbf` (local to Mac)

### Goal
- Test latest OSM Philippines data
- Use Batangas province only (geographically constrained)
- Verify it improves routing coverage vs. current map
- Check if new locations appear in saved places

### Next Actions
1. Transfer `batangas.osm.pbf` to Pi
2. Import into GraphHopper
3. Test routing in Batangas region
4. Document any coverage improvements

