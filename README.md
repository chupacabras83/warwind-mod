# War Wind — Mod Toolkit

Binary patch scripts for the GOG release of **War Wind** (DreamForge, 1996).

These scripts modify `WW.EXE` in place to add quality-of-life and cheat features.
They do **not** contain any game assets — you supply your own legally-purchased
`WW.EXE`, and the scripts patch it.

---

## Quick start

```bash
# 1. Back up your original
cp WW.EXE WW.EXE.orig

# 2. Build the confirmed-stable mod set
python scripts/patch_resources.py WW.EXE.orig WW.EXE.stage1
python scripts/patch_stage5b.py  WW.EXE.stage1 WW.EXE.stage5b
python scripts/patch_stage6.py   WW.EXE.stage5b WW.EXE.stage6b
python scripts/patch_stage9.py   WW.EXE.stage6b WW.EXE.stage9
python scripts/patch_stage10.py  WW.EXE.stage9  WW.EXE.stage10
python scripts/patch_stage8.py   WW.EXE.stage10 WW.EXE.stage10b
python scripts/patch_nt_warning.py WW.EXE.stage10b WW.EXE

# 3. Verify
python scripts/verify_build.py WW.EXE
```

Requires Python 3. No third-party packages.

---

## Feature stages

| Script | Adds |
|---|---|
| `patch_resources.py` | 99,999 starting resources, fog of war removed, fast recruit/build |
| `patch_stage5b.py` | Full tech tree — all researches complete for all 4 clans |
| `patch_stage6.py` | All races' spells listed in the star/command menu |
| `patch_stage8.py` | Removes homes/manor population cap |
| `patch_stage9.py` | Buildings complete in ~1 tick; instant repair; full-HP treatment |
| `patch_stage10.py` | All 20 spells cost 1 mana |
| `patch_nt_warning.py` | Bypasses the "Operation under Windows NT is not supported" dialog |
| `patch_stage11.py` | **Auto-upgrade on becoming player-owned** (hire / train / mind control) |
| `patch_stage12.py` | Max stats on ownership: speed, armour, vision, HP ≥ 150 (experimental) |
| `patch_stage13.py` | Damage/max-stat variant (experimental) |
| `patch_stage14.py` | Player-only damage boost by hooking the damage routine (experimental) |
| `patch_stage15.py` | Stealth ladder — hidden on join, invisible after one upgrade (experimental) |

**Stages 12–15 are experimental and were never confirmed working in-game.**
They are included for reference and further development. The confirmed set is
stages 1, 5b, 6, 8, 9, 10, 11 + the NT-warning patch.

Legacy stages (`patch_godmode.py`, `patch_stage3.py`, `patch_stage5.py`,
`patch_stage7.py`) are earlier iterations kept for history. `patch_stage5.py`
in particular is **known to break the game** (black screen) — it patched what
looked like an unlock switch but was actually a per-frame work-skip. Do not use it.

---

## Verifiers

| Script | Purpose |
|---|---|
| `verify_build.py` | Byte-checks every confirmed patch in a built exe |
| `verify_loaded.py` | **Critical**: checks all added code lies inside the section's real `RawSize`, so it is actually mapped into memory |
| `verify_stage11.py` / `verify_stage12.py` | Per-stage byte checks |
| `fix_wwmod_section.py` | Repairs a `.wwmod` section header with `RawSize` smaller than the code written into it |

### The `.wwmod` trap (read this)

The mod code lives in an appended `.wwmod` section. Windows maps only
`SizeOfRawData` bytes of a section from the file and **zero-fills the rest of the
virtual range**. Writing code past `RawSize` therefore produces a binary where
the code "looks" present but is zeros at run time — every call into it jumps to
garbage and crashes the game.

`verify_loaded.py` exists to catch exactly this. Always run it.

---

## Technical notes

* `WW.EXE` is a 1996 WATCOM C/C++ Win32 PE, image base `0x400000`, 716,288 bytes unpatched.
* Disassembler convention used throughout: **no `0x66` prefix = 32-bit; `0x66` = 16-bit**.
* Memory displacements print decimal; immediates print hex.
* Key structures:
  * thing array `0x5044A0` (2048 × 124 bytes): `+1` category (2 = unit), `+0x18` clan
  * unit_data `0x4EA7A0` (120 bytes each): `+0x10` HP, `+0x12` mana, `+0x1A` strength,
    `+0x1B` armour, `+0x1C` vision, `+0x1D` speed, `+0x1E` stealth level,
    `+0x23` upgrade bits, `+0x27` spell mask
  * type table `0x4B3C38` (32 bytes each): `+0` class, `+1` max HP,
    `+5` melee dmg, `+6` melee range, `+7` ranged dmg, `+8` ranged range, `+0x12` max mana
  * clan researched dword `0x544188 + clan*257` (`-1` = everything researched)
  * units-per-home table `0x4B47E4` (one word per race)
  * spell table `0x4B63E8` (20 × 18 bytes): `+6` mana cost
* Stealth is a plain level, not a bitmask: 0 = none, 1–2 = disguised (yellow),
  3 = hidden (blue), 4 = invisible (white). Cap enforced at `0x4510A4`.

---

## Legal

War Wind is © DreamForge Entertainment / Strategic Simulations, Inc.
This repository contains **only original patch scripts** — no game code, assets,
or binaries. You must own a legitimate copy of the game to use them.

Do not redistribute patched executables or game data.
