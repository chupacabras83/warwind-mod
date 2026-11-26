"""War Wind patch, stage 3. Applied ON TOP of patch_godmode.py output.

Usage:
  python patch_stage3.py patched\\WW.EXE.godmode patched\\WW.EXE.stage3

Effects (player-owned only: thing+0x18 clan == [0x4B342C]):

1. +10 movement speed for every player unit (leaders, builders, all).
   The per-move rate is computed at 0x43923C as
       unit_data+0x59 = unit_data+0x1D (speed) - (6 - gamespeed)/2
   The stub adds 10 to the speed term. Rates >= 20 use the game's own
   fastest walk tables (1 tile per step at 0x4B3910 / 0x4B3ABC).
   Nothing is stored, so it cannot stack across saves or level loads.

2. Construction and repair finish on the first work tick.
   Builder work routines add +2 HP per work cycle:
     0x42EC0A, 0x42F077 -> 0x44C028  buildings  (word HP, 0x503F28+idx*7+2)
     0x42F104, 0x43002D -> 0x43F964  vehicles/boats (byte HP, 0x4E9800+idx*40+0x15)
   These four calls are retargeted to a filter that turns the +2 into
   +0x7FFF for player-owned targets (both routines clamp to max HP and
   return 1 = complete). Damage callers of those functions are untouched.

3. Treatment inside a structure heals to full on the first tick.
   0x439839 and 0x43995A each add +1 HP per heal tick (every 16 ticks).
   Both now call a stub that does the original +1 and, for player units,
   sets HP to the type's max (TT+1).

Cave space used:
  0x415925..0x415958  (tail of the stage-1 cave, 0x90 filled)  -> build filter
  0x4A0BC0..0x4A0C00  (after the grant routine, zero filled)   -> heal, speed
"""
import hashlib
import struct
import sys

from patch_godmode import Asm, d32, no_reloc, put_text, relocs, tfoff

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.godmode'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage3'

THING = 0x5044A0
PLAYER_CLAN = 0x4B342C
SPEED_BONUS = 10

BUILDING_HP_FN = 0x44C028
VEHICLE_HP_FN = 0x43F964

CAVE_C, CAVE_C_END = 0x415925, 0x415958
CAVE_B, CAVE_B_END = 0x4A0BC0, 0x4A0C00

SPEED_SITE = 0x43923C
SPEED_ORIG = bytes.fromhex('8a 55 1d 29 c2')            # mov dl,[ebp+1d] ; sub edx,eax

HEAL_A_SITE = 0x43982F
HEAL_A_ORIG = bytes.fromhex('66 8b 45 10 66 3b 42 01 73 32 40 66 89 45 10')
HEAL_A_RESUME = 0x43983E

HEAL_B_SITE = 0x439956
HEAL_B_ORIG = bytes.fromhex('66 8b 4d 10 41 8b 54 24 0c 66 89 4d 10')

CALL_SITES = [(0x42EC0A, BUILDING_HP_FN), (0x42F077, BUILDING_HP_FN),
              (0x42F104, VEHICLE_HP_FN), (0x43002D, VEHICLE_HP_FN)]


def build_cave_c():
    """fV/fB: push the real HP function, filter edx, then `ret` tail-calls it."""
    a = Asm(CAVE_C)
    a.label('fV')
    a.b('68') ; a.raw(d32(BUILDING_HP_FN))            # push 0x44C028
    a.jcc(0xEB, 'filter')
    a.label('fB')
    a.b('68') ; a.raw(d32(VEHICLE_HP_FN))             # push 0x43F964
    a.label('filter')                                 # ax = target thing, edx = delta
    a.b('85 D2')                                      # test edx,edx
    a.jcc(0x7E, 'done')                               # jle done
    a.b('51')                                         # push ecx
    a.b('0F B7 C8')                                   # movzx ecx,ax
    a.b('6B C9 7C')                                   # imul ecx,ecx,0x7C
    a.b('8A 89') ; a.raw(d32(THING + 0x18))           # mov cl,[ecx+thing.clan]
    a.b('3A 0D') ; a.raw(d32(PLAYER_CLAN))            # cmp cl,[player_clan]
    a.b('59')                                         # pop ecx
    a.jcc(0x75, 'done')
    a.b('BA') ; a.raw(d32(0x7FFF))                    # mov edx,0x7FFF (clamped to max)
    a.label('done')
    a.b('C3')                                         # ret -> HP function
    return a.assemble(), a.labels


def build_cave_b():
    a = Asm(CAVE_B)
    # heal: esi = thing ptr, ebp = unit_data ptr, edx = type-table ptr. Preserves regs.
    a.label('heal')
    a.b('50')                                         # push eax
    a.b('66 8B 45 10')                                # mov ax,[ebp+0x10]   hp
    a.b('66 3B 42 01')                                # cmp ax,[edx+1]      max hp
    a.jcc(0x73, 'h_done')                             # jae
    a.b('40')                                         # inc eax             (original +1)
    a.b('66 89 45 10')                                # mov [ebp+0x10],ax
    a.b('8A 46 18')                                   # mov al,[esi+0x18]   clan
    a.b('3A 05') ; a.raw(d32(PLAYER_CLAN))
    a.jcc(0x75, 'h_done')
    a.b('66 8B 42 01')                                # mov ax,[edx+1]
    a.b('66 89 45 10')                                # mov [ebp+0x10],ax   full hp
    a.label('h_done')
    a.b('58 C3')                                      # pop eax ; ret
    # speed: replaces `mov dl,[ebp+0x1d] ; sub edx,eax` (edx is 0 on entry)
    a.label('speed')
    a.b('8A 55 1D')                                   # mov dl,[ebp+0x1d]
    a.b('50')                                         # push eax
    a.b('8A 46 18')                                   # mov al,[esi+0x18]
    a.b('3A 05') ; a.raw(d32(PLAYER_CLAN))
    a.b('58')                                         # pop eax (flags kept)
    a.jcc(0x75, 's_done')
    a.b('83 C2 %02X' % SPEED_BONUS)                   # add edx,10
    a.label('s_done')
    a.b('29 C2 C3')                                   # sub edx,eax ; ret
    return a.assemble(), a.labels


def rel32(op, src, dst):
    return bytes([op]) + struct.pack('<i', dst - (src + 5))


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    rel = relocs(data)

    c_code, c_lab = build_cave_c()
    b_code, b_lab = build_cave_b()
    assert CAVE_C + len(c_code) <= CAVE_C_END, len(c_code)
    assert CAVE_B + len(b_code) <= CAVE_B_END, len(b_code)

    for va, n in ((CAVE_C, CAVE_C_END - CAVE_C), (CAVE_B, CAVE_B_END - CAVE_B),
                  (SPEED_SITE, 5), (HEAL_A_SITE, 15), (HEAL_B_SITE, 13)):
        no_reloc(rel, va, n)

    put_text(data, CAVE_C, c_code, expect_fill=(0x90,))
    put_text(data, CAVE_B, b_code, expect_fill=(0,))

    # 1. speed
    put_text(data, SPEED_SITE, rel32(0xE8, SPEED_SITE, b_lab['speed']), expect=SPEED_ORIG)

    # 2. build / repair call retargets
    for site, orig in CALL_SITES:
        new = c_lab['fV'] if orig == BUILDING_HP_FN else c_lab['fB']
        no_reloc(rel, site, 5)
        put_text(data, site, rel32(0xE8, site, new), expect=rel32(0xE8, site, orig))

    # 3. treatment, path A: call heal ; jmp 0x43983E ; nop*8
    a_new = rel32(0xE8, HEAL_A_SITE, b_lab['heal'])
    a_new += bytes([0xEB, HEAL_A_RESUME - (HEAL_A_SITE + 7)])
    a_new += b'\x90' * (len(HEAL_A_ORIG) - len(a_new))
    put_text(data, HEAL_A_SITE, a_new, expect=HEAL_A_ORIG)

    # treatment, path B: mov edx,[esp+0xc] ; call heal ; mov cx,[ebp+0x10]
    b_new = bytes.fromhex('8b 54 24 0c') + rel32(0xE8, HEAL_B_SITE + 4, b_lab['heal'])
    b_new += bytes.fromhex('66 8b 4d 10')
    assert len(b_new) == len(HEAL_B_ORIG)
    put_text(data, HEAL_B_SITE, b_new, expect=HEAL_B_ORIG)

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('cave C @%08X %2d bytes  fV=%08X fB=%08X' % (CAVE_C, len(c_code), c_lab['fV'], c_lab['fB']))
    print('cave B @%08X %2d bytes  heal=%08X speed=%08X' %
          (CAVE_B, len(b_code), b_lab['heal'], b_lab['speed']))
    print('speed +%d @%08X, build/repair calls %s, treatment @%08X/%08X' %
          (SPEED_BONUS, SPEED_SITE, ' '.join('%08X' % s for s, _ in CALL_SITES),
           HEAL_A_SITE, HEAL_B_SITE))


if __name__ == '__main__':
    main()
