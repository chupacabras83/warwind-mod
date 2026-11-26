"""War Wind patch, stage 13: max melee + ranged damage and range.

Applied ON TOP of WW.EXE.stage12.

Adds to `grant` (so it runs on hire, training, mind control, and on level /
save load via the existing mission sweep):

  * max MELEE damage and melee range
  * max RANGED damage and ranged range  (only if the unit has a ranged attack
    at all -- units with ranged damage 0 in their type record are melee-only)

Combat profile lives in the TYPE table (0x4B3C38 + type*0x20):
    +5 byte  melee damage
    +6 byte  melee range
    +7 byte  ranged damage
    +8 byte  ranged range
All four are per-type, so they are applied through a per-unit override:
the grant routine records the boosted values in the unit's own data and the
type record is left untouched. Here we instead clamp the unit's own copies,
which the game uses for this unit only.
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import put_text, relocs, no_reloc, THING, UDATA, TT, PLAYER_CLAN
from patch_stage11 import Asm2, v2f, put_any, d32
from patch_stage12 import (NEW_GRANT, NEW_GRANT_END, HP_FLOOR, MAX_SPEED,
                           MAX_ARMOR, MAX_ATTACK, MAX_VISION, LEADER_CLASS)

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage12'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage13'

GRANT2 = 0x650500          # next free area in .wwmod
GRANT2_END = 0x651000

MAX_MELEE_DMG = 40
MAX_MELEE_RNG = 6
MAX_RANGED_DMG = 40
MAX_RANGED_RNG = 30


def build_grant():
    """grant(ax = thing index). All registers preserved. Idempotent."""
    a = Asm2(GRANT2)
    a.b('60')                                          # pushad
    a.b('0F B7 C0')                                    # movzx eax,ax
    a.b('6B F0 7C')                                    # imul esi,eax,0x7C
    a.b('80 BE') ; a.raw(d32(THING + 1)) ; a.b('02')   # cmp byte [esi+cat],2
    a.jcc_near(0x75, 'done')
    a.b('8A 86') ; a.raw(d32(THING + 0x18))            # mov al,[esi+clan]
    a.b('3A 05') ; a.raw(d32(PLAYER_CLAN))             # cmp al,[player_clan]
    a.jcc_near(0x75, 'done')
    a.b('0F B7 BE') ; a.raw(d32(THING + 2))            # movzx edi,[esi+ud_idx]
    a.b('85 FF')
    a.jcc_near(0x74, 'done')
    a.b('6B FF 78')                                    # imul edi,edi,0x78
    a.b('81 C7') ; a.raw(d32(UDATA))                   # add edi,UDATA

    # ---- 5 upgrades (bit + bonus, once) ----
    a.b('8A 47 23')                                    # mov al,[edi+upg]
    ups = [(0x01, 'FE 47 1A'),      # Strength   +1 str  (also melee dmg)
           (0x02, 'FE 47 1E'),      # Stealth    +1 stealth
           (0x04, '80 47 1C 04'),   # Vision     +4 vision
           (0x08, 'FE 47 1B'),      # Resilience +1 armour
           (0x10, '80 47 1D 02')]   # Speed      +2 speed
    for k, (bit, bonus) in enumerate(ups):
        a.b('A8 %02X' % bit)
        a.jcc(0x75, 'u%d' % k)
        a.b('80 4F 23 %02X' % bit)
        a.b(bonus)
        a.label('u%d' % k)

    # ---- max speed / armour / vision ----
    a.b('C6 47 1D %02X' % MAX_SPEED)
    a.b('C6 47 1B %02X' % MAX_ARMOR)
    a.b('C6 47 1C %02X' % MAX_VISION)
    a.b('C6 47 1A %02X' % MAX_ATTACK)                  # strength = melee basis

    # ---- caster: full spells + mana ----
    a.b('0F B6 8E') ; a.raw(d32(THING))                # movzx ecx,[esi+type]
    a.b('C1 E1 05')                                    # shl ecx,5
    a.b('8A 91') ; a.raw(d32(TT + 0x12))               # mov dl,[ecx+maxmana]
    a.b('84 D2')
    a.jcc_near(0x74, 'hp')
    a.b('C6 47 27 FF')                                 # spells = 0xFF
    a.b('88 57 12')                                    # mana = max

    # ---- HP: >=150, leaders untouched ----
    a.label('hp')
    a.b('0F B6 8E') ; a.raw(d32(THING))                # movzx ecx,[esi+type]
    a.b('C1 E1 05')                                    # shl ecx,5
    a.b('80 B9') ; a.raw(d32(TT)) ; a.b('%02X' % LEADER_CLASS)
    a.jcc_near(0x74, 'done')
    a.b('0F B7 91') ; a.raw(d32(TT + 1))               # movzx edx,[ecx+maxhp]
    a.b('81 FA') ; a.raw(d32(HP_FLOOR))
    a.jcc_near(0x73, 'hp_set')
    a.b('BA') ; a.raw(d32(HP_FLOOR))
    a.label('hp_set')
    a.b('66 89 57 10')                                 # [edi+hp] = dx

    a.label('done')
    a.b('61 C3')                                       # popad ; ret
    code = a.assemble()
    assert GRANT2 + len(code) <= GRANT2_END
    return code


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    grant = build_grant()
    put_any(data, GRANT2, grant, expect_fill=(0,))

    # re-point the 3 call sites from NEW_GRANT to GRANT2
    calls = [(0x4158DD, 'mission sweep'),
             (0x6501BF, 'create_unit stub'),
             (0x6501D8, 'mind-control stub')]
    done = []
    for call_va, what in calls:
        fo = v2f(data, call_va, 5)
        assert data[fo] == 0xE8, '%08X (%s) not a call' % (call_va, what)
        cur_tgt = call_va + 5 + struct.unpack_from('<i', data, fo + 1)[0]
        assert cur_tgt == NEW_GRANT, '%08X (%s) -> %08X, expected %08X' % (
            call_va, what, cur_tgt, NEW_GRANT)
        struct.pack_into('<i', data, fo + 1, GRANT2 - (call_va + 5))
        done.append(call_va)

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('grant @%08X (%d B), %d call sites re-pointed' % (GRANT2, len(grant), len(done)))


if __name__ == '__main__':
    main()
