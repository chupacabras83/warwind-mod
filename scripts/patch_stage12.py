"""War Wind patch, stage 12: max combat stats for every player-owned unit.

Applied ON TOP of WW.EXE.stage11 (auto-grant on ownership).

Extends the `grant` routine so that every unit the moment it becomes
player-owned -- hired, trained, summoned, or mind-controlled (including enemy
clan leaders and animals/creatures) -- receives:

  * all 5 upgrades (already in stage 11), so the Stealth upgrade is included
  * spell mask 0xFF + full mana for casters (already in stage 11)
  * MAXIMUM movement speed (unit_data+0x1D clamped to the fastest value)
  * MAXIMUM current HP, raised to at least 150 -- EXCEPT clan-leader classes
    (type-table class 1), whose higher HP is left alone per the user's choice
  * maximum armour, melee damage, ranged damage and vision

All of these are per-unit writes on the player-owned unit only, so enemy units
of the same type are NOT affected.

Stat layout (unit_data = 0x4EA7A0 + idx*0x78)
    +0x10 word  current HP
    +0x12 byte  mana
    +0x1A byte  strength   (melee)
    +0x1B byte  armour
    +0x1C byte  vision
    +0x1D byte  speed
    +0x1E byte  stealth
    +0x23 byte  upgrade bits
    +0x27 byte  spell mask
Type table (0x4B3C38 + type*0x20)
    +0x00 byte class   (1 = clan leader -> leave HP alone)
    +0x01 word max HP
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import put_text, relocs, no_reloc, THING, UDATA, TT, PLAYER_CLAN
from patch_stage11 import Asm2, v2f, put_any, GRANT, GRANT_END, d32

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage11'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage12'

NEW_GRANT = 0x650300        # .wwmod: 0x650000..0x651000; stage-11 uses up to ~0x6501E5
NEW_GRANT_END = 0x651000

HP_FLOOR = 150
MAX_SPEED = 20              # game's fastest walk-rate threshold
MAX_ARMOR = 40
MAX_ATTACK = 40
MAX_VISION = 30
LEADER_CLASS = 1


def build_grant():
    """grant(ax = thing index). All registers preserved. Idempotent."""
    a = Asm2(NEW_GRANT)
    a.b('60')                                          # pushad
    a.b('0F B7 C0')                                    # movzx eax,ax
    a.b('6B F0 7C')                                    # imul esi,eax,0x7C
    a.b('80 BE') ; a.raw(d32(THING + 1)) ; a.b('02')   # cmp byte [esi+cat],2
    a.jcc_near(0x75, 'done')
    a.b('8A 86') ; a.raw(d32(THING + 0x18))            # mov al,[esi+clan]
    a.b('3A 05') ; a.raw(d32(PLAYER_CLAN))             # cmp al,[player_clan]
    a.jcc_near(0x75, 'done')
    a.b('0F B7 BE') ; a.raw(d32(THING + 2))            # movzx edi,[esi+ud_idx]
    a.b('85 FF')                                       # test edi,edi
    a.jcc_near(0x74, 'done')
    a.b('6B FF 78')                                    # imul edi,edi,0x78
    a.b('81 C7') ; a.raw(d32(UDATA))                   # add edi,UDATA

    # ---- upgrades (bit + stat bonus, applied once) ----
    a.b('8A 47 23')                                    # mov al,[edi+upg]
    ups = [(0x01, 'FE 47 1A'),      # Strength
           (0x02, 'FE 47 1E'),      # Stealth
           (0x04, '80 47 1C 04'),   # Vision
           (0x08, 'FE 47 1B'),      # Resilience
           (0x10, '80 47 1D 02')]   # Speed
    for k, (bit, bonus) in enumerate(ups):
        a.b('A8 %02X' % bit)                           # test al,bit
        a.jcc(0x75, 'u%d' % k)
        a.b('80 4F 23 %02X' % bit)                     # or [edi+upg],bit
        a.b(bonus)
        a.label('u%d' % k)

    # ---- max movement speed ----
    a.b('C6 47 1D %02X' % MAX_SPEED)                   # mov byte [edi+speed],MAX

    # ---- max armour / melee / vision ----
    a.b('C6 47 1B %02X' % MAX_ARMOR)                   # armour
    a.b('C6 47 1A %02X' % MAX_ATTACK)                  # melee (strength)
    a.b('C6 47 1C %02X' % MAX_VISION)                  # vision

    # ---- caster: full spell mask + full mana ----
    a.b('0F B6 8E') ; a.raw(d32(THING))                # movzx ecx,[esi+type]
    a.b('C1 E1 05')                                    # shl ecx,5
    a.b('8A 91') ; a.raw(d32(TT + 0x12))               # mov dl,[ecx+maxmana]
    a.b('84 D2')                                       # test dl,dl
    a.jcc_near(0x74, 'hp')                             # not a caster
    a.b('C6 47 27 FF')                                 # mov byte [edi+spells],0xFF
    a.b('88 57 12')                                    # mov [edi+mana],dl

    # ---- HP: max of (type max, 150) but never lower current; leaders untouched ----
    a.label('hp')
    a.b('0F B6 8E') ; a.raw(d32(THING))                # movzx ecx,[esi+type]
    a.b('C1 E1 05')                                    # shl ecx,5
    a.b('80 B9') ; a.raw(d32(TT)) ; a.b('%02X' % LEADER_CLASS)   # cmp byte [ecx+class],1
    a.jcc_near(0x74, 'done')                           # clan leader -> leave HP alone
    a.b('0F B7 91') ; a.raw(d32(TT + 1))               # movzx edx,[ecx+maxhp]
    a.b('81 FA') ; a.raw(d32(HP_FLOOR))                # cmp edx,150
    a.jcc_near(0x73, 'hp_set')                         # jae hp_set (keep the higher max)
    a.b('BA') ; a.raw(d32(HP_FLOOR))                   # mov edx,150
    a.label('hp_set')
    a.b('66 89 57 10')                                 # mov [edi+hp],dx
    a.label('done')
    a.b('61 C3')                                       # popad ; ret
    code = a.assemble()
    assert NEW_GRANT + len(code) <= NEW_GRANT_END
    return code


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    rel = relocs(data)

    grant = build_grant()
    put_any(data, NEW_GRANT, grant, expect_fill=(0,))

    # re-point every stage-11 call site at the new grant by patching the
    # rel32 operand of each known `e8 call <GRANT>` in place.
    NEW_HOOK = 0x6501B4
    MC_HOOK = 0x6501CC
    calls = [(0x4158DD, 'mission sweep'),
             (NEW_HOOK + 11, 'create_unit stub'),
             (MC_HOOK + 12, 'mind-control stub')]
    done = []
    for call_va, what in calls:
        fo = v2f(data, call_va, 5)
        assert data[fo] == 0xE8, '%08X (%s) is not a call' % (call_va, what)
        cur_tgt = call_va + 5 + struct.unpack_from('<i', data, fo + 1)[0]
        assert cur_tgt == GRANT, '%08X (%s) points at %08X, expected %08X' % (call_va, what, cur_tgt, GRANT)
        struct.pack_into('<i', data, fo + 1, NEW_GRANT - (call_va + 5))
        done.append(call_va)

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('grant @%08X (%d B), re-pointed %d call sites: %s' %
          (NEW_GRANT, len(grant), len(done), ' '.join('%08X' % s for s in done)))


if __name__ == '__main__':
    main()
