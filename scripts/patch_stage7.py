"""War Wind patch, stage 7: instant build/repair + full-HP treatment (NO +10 speed).

Applied ON TOP of WW.EXE.stage6b (tech tree + spell menu, no god-mode).

Reuses the stage-3 build-filter (cave C) and heal stub (cave B), but omits the
+10 movement-speed patch/stub. This gives "building completes in ~1s" and
"repair/treatment instantly full HP" without touching movement or combat.
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import put_text, relocs, no_reloc, d32
from patch_stage3 import (Asm, build_cave_c, rel32, PLAYER_CLAN, BUILDING_HP_FN,
                          VEHICLE_HP_FN, CAVE_C, CAVE_C_END, CAVE_B, CAVE_B_END,
                          CALL_SITES, HEAL_A_SITE, HEAL_A_ORIG, HEAL_A_RESUME,
                          HEAL_B_SITE, HEAL_B_ORIG)

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage6b'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage7'


def build_heal():
    a = Asm(CAVE_B)
    a.label('heal')
    a.b('50')                          # push eax
    a.b('66 8B 45 10')                 # mov ax,[ebp+0x10]   hp
    a.b('66 3B 42 01')                 # cmp ax,[edx+1]      max hp
    a.jcc(0x73, 'done')                # jae done
    a.b('40')                          # inc eax
    a.b('66 89 45 10')                 # mov [ebp+0x10],ax
    a.b('8A 46 18')                    # mov al,[esi+0x18]   clan
    a.b('3A 05') ; a.raw(d32(PLAYER_CLAN))
    a.jcc(0x75, 'done')                # jne done
    a.b('66 8B 42 01')                 # mov ax,[edx+1]      max hp
    a.b('66 89 45 10')                 # mov [ebp+0x10],ax   full hp
    a.label('done')
    a.b('58 C3')                       # pop eax ; ret
    return a.assemble(), a.labels


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    rel = relocs(data)

    c_code, c_lab = build_cave_c()
    b_code, b_lab = build_heal()
    assert CAVE_C + len(c_code) <= CAVE_C_END
    assert CAVE_B + len(b_code) <= CAVE_B_END

    for va, n in ((CAVE_C, CAVE_C_END - CAVE_C), (CAVE_B, CAVE_B_END - CAVE_B),
                  (HEAL_A_SITE, 15), (HEAL_B_SITE, 13)):
        no_reloc(rel, va, n)

    put_text(data, CAVE_C, c_code, expect_fill=(0x90,))
    put_text(data, CAVE_B, b_code, expect_fill=(0,))

    # build / repair call retargets
    for site, orig in CALL_SITES:
        new = c_lab['fV'] if orig == BUILDING_HP_FN else c_lab['fB']
        no_reloc(rel, site, 5)
        put_text(data, site, rel32(0xE8, site, new), expect=rel32(0xE8, site, orig))

    # treatment path A
    a_new = rel32(0xE8, HEAL_A_SITE, b_lab['heal'])
    a_new += bytes([0xEB, HEAL_A_RESUME - (HEAL_A_SITE + 7)])
    a_new += b'\x90' * (len(HEAL_A_ORIG) - len(a_new))
    put_text(data, HEAL_A_SITE, a_new, expect=HEAL_A_ORIG)

    # treatment path B
    b_new = bytes.fromhex('8b 54 24 0c') + rel32(0xE8, HEAL_B_SITE + 4, b_lab['heal'])
    b_new += bytes.fromhex('66 8b 4d 10')
    put_text(data, HEAL_B_SITE, b_new, expect=HEAL_B_ORIG)

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('cave C @%08X (%d B)  cave B heal @%08X (%d B)' % (CAVE_C, len(c_code), CAVE_B, len(b_code)))


if __name__ == '__main__':
    main()
