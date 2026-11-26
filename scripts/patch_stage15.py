"""War Wind patch, stage 15: stealth ladder (masked -> disguised -> hidden -> invisible).

Applied ON TOP of the rebuilt chain (patched\\b14).

unit_data+0x1E is the STEALTH LEVEL and it directly selects the marker the game
draws over the unit:
    level 0     : nothing
    level 1, 2  : "disguised"  (yellow arrow)
    level 3     : "hidden"     (blue arrow)   <- what the player wants on joining
    level 4     : "invisible"  (white arrow)  <- what one stealth upgrade gives

Evidence:
  * 0x4510A4 / 0x4511A4 / 0x4512A4 / 0x4513AB all do `cmp [edi+0x1E],4`
    (hard cap of 4 = the top of the ladder)
  * 0x447CBB..0x447CC0 is the Stealth upgrade itself:
        inc bh ; mov [edi+0x1E],bh        -> the upgrade bumps the level by 1
  * 0x45D4D5 / 0x45D504 read [eax+0x1E] into dl/bl and index a per-level table
    at [esp] to decide what to draw over the unit (the arrow colour).

So the whole ladder is one numeric byte; no flag bitmask is involved.

This patch sets, for every player-owned unit:
  * stealth level = 3 (hidden / blue arrow) when it joins
  * and lets one further Stealth upgrade push it to 4 (invisible / white arrow),
    which the vanilla `inc` already does.
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import put_text, relocs, no_reloc, THING, UDATA, TT, PLAYER_CLAN
from patch_stage11 import Asm2, v2f, put_any, grow_section_for, d32
from patch_stage12 import HP_FLOOR, MAX_SPEED, MAX_ARMOR, MAX_ATTACK, MAX_VISION, LEADER_CLASS

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\b14'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\b15'

GRANT3 = 0x650B00
STEALTH_ON_JOIN = 3        # hidden / blue arrow
STEALTH_MAX = 4            # invisible / white arrow


def build_grant():
    a = Asm2(GRANT3)
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

    # ---- 5 upgrade bits, each with its once-only stat bonus ----
    a.b('8A 47 23')                                    # mov al,[edi+upg]
    ups = [(0x01, 'FE 47 1A'),      # Strength   +1 str
           (0x02, 'FE 47 1E'),      # Stealth    +1 stealth level
           (0x04, '80 47 1C 04'),   # Vision     +4 vision
           (0x08, 'FE 47 1B'),      # Resilience +1 armour
           (0x10, '80 47 1D 02')]   # Speed      +2 speed
    for k, (bit, bonus) in enumerate(ups):
        a.b('A8 %02X' % bit)
        a.jcc(0x75, 'u%d' % k)
        a.b('80 4F 23 %02X' % bit)
        a.b(bonus)
        a.label('u%d' % k)

    # ---- max speed / armour / vision / melee basis ----
    a.b('C6 47 1D %02X' % MAX_SPEED)
    a.b('C6 47 1B %02X' % MAX_ARMOR)
    a.b('C6 47 1C %02X' % MAX_VISION)
    a.b('C6 47 1A %02X' % MAX_ATTACK)

    # ---- STEALTH LADDER: hidden on joining, but never lower an existing
    #      higher tier (so a unit that is already invisible stays invisible) ----
    a.b('80 7F 1E %02X' % STEALTH_ON_JOIN)             # cmp byte [edi+stealth],3
    a.jcc_near(0x73, 'mana')                           # jae -> already >= 3
    a.b('C6 47 1E %02X' % STEALTH_ON_JOIN)             # mov byte [edi+stealth],3
    a.b('80 4F 23 02')                                 # or [edi+upg],0x02 (own it)

    # ---- caster: full spells + mana ----
    a.label('mana')
    a.b('0F B6 8E') ; a.raw(d32(THING))                # movzx ecx,[esi+type]
    a.b('C1 E1 05')                                    # shl ecx,5
    a.b('8A 91') ; a.raw(d32(TT + 0x12))               # mov dl,[ecx+maxmana]
    a.b('84 D2')
    a.jcc_near(0x74, 'hp')
    a.b('C6 47 27 FF')                                 # spells = 0xFF
    a.b('88 57 12')                                    # mana = max

    # ---- HP: >=150, clan leaders untouched ----
    a.label('hp')
    a.b('0F B6 8E') ; a.raw(d32(THING))
    a.b('C1 E1 05')
    a.b('80 B9') ; a.raw(d32(TT)) ; a.b('%02X' % LEADER_CLASS)
    a.jcc_near(0x74, 'done')
    a.b('0F B7 91') ; a.raw(d32(TT + 1))
    a.b('81 FA') ; a.raw(d32(HP_FLOOR))
    a.jcc_near(0x73, 'hp_set')
    a.b('BA') ; a.raw(d32(HP_FLOOR))
    a.label('hp_set')
    a.b('66 89 57 10')

    a.label('done')
    a.b('61 C3')
    code = a.assemble()
    return code


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    grant = build_grant()
    put_any(data, GRANT3, grant, expect_fill=(0,))

    OLD = 0x650500
    calls = [(0x4158DD, 'mission sweep'),
             (0x6501BF, 'create_unit stub'),
             (0x6501D8, 'mind-control stub')]
    for call_va, what in calls:
        fo = v2f(data, call_va, 5)
        assert data[fo] == 0xE8, '%08X (%s) not a call' % (call_va, what)
        cur_tgt = call_va + 5 + struct.unpack_from('<i', data, fo + 1)[0]
        assert cur_tgt == OLD, '%08X (%s) -> %08X, expected %08X' % (call_va, what, cur_tgt, OLD)
        struct.pack_into('<i', data, fo + 1, GRANT3 - (call_va + 5))

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('grant @%08X (%d B), stealth on join = %d, cap = %d' %
          (GRANT3, len(grant), STEALTH_ON_JOIN, STEALTH_MAX))


if __name__ == '__main__':
    main()
