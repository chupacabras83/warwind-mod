"""War Wind patch, stage 9: CORRECT instant build/repair + instant treatment.

Fixes two real bugs in the stage-3/7 stub that caused crashes and slow build HP:

  BUG 1 (crash):  cave C laid out fV/fB as
                      fV: push <BHP> ; jmp filter
                      fB: push <VHP>
                  -> fV's jump SKIPPED its own push, so `ret` popped the
                  caller's return address as a function pointer = jump to garbage.
  BUG 2:  the filter clobbered ECX (it held the target thing index at the
                  vehicle call site 0x43002D), and push/pop ecx were swapped,
                  so both the HP add and the return were wrong.

New stub preserves every register except the ones the callee is allowed to
clobber, sets edx=0x7FFF only for player-owned targets, and tail-calls the real
HP function with an intact return address.

Effects:
  * Construction / repair of player buildings & vehicles finishes in 1 tick.
  * Treatment in a structure heals a player unit to full HP on the first tick.
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import Asm, d32, no_reloc, put_text, relocs
from patch_stage3 import (rel32, PLAYER_CLAN, THING, BUILDING_HP_FN, VEHICLE_HP_FN,
                          CAVE_C, CAVE_C_END, CAVE_B, CAVE_B_END,
                          CALL_SITES, HEAL_A_SITE, HEAL_A_ORIG, HEAL_A_RESUME,
                          HEAL_B_SITE, HEAL_B_ORIG)

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage8'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage9'


def build_filter():
    """Entry: ax = target thing index, edx = requested HP delta. ecx/flags kept.

    Only player-owned targets get edx bumped to 0x7FFF. All touched registers
    are saved/restored. Ends with `push fn ; ret` = clean tail call.
    """
    a = Asm(CAVE_C)
    a.label('fV')                       # building variant
    a.b('68') ; a.raw(d32(BUILDING_HP_FN))   # push 0x44C028
    a.jcc(0xEB, 'common')               # jmp common  (skips the other push)
    a.label('fB')                       # vehicle variant
    a.b('68') ; a.raw(d32(VEHICLE_HP_FN))    # push 0x43F964
    a.label('common')
    # Save the registers we touch. The real HP fn must see them exactly as the
    # caller left them, so everything is restored before the tail call.
    a.b('51')                           # push ecx
    a.b('57')                           # push edi
    a.b('85 D2')                        # test edx,edx
    a.jcc(0x7E, 'done')                 # jle done            (damage / no-op)
    a.b('0F B7 F8')                     # movzx edi,ax        thing index
    a.b('6B FF 7C')                     # imul  edi,edi,0x7C  thing record size
    a.b('0F B6 BF') ; a.raw(d32(THING + 0x18))   # movzx edi,[edi+thing.clan]
    a.b('3B 3D') ; a.raw(d32(PLAYER_CLAN))       # cmp edi,[player_clan]
    a.jcc(0x75, 'done')                          # jne done            (enemy)
    a.b('BA') ; a.raw(d32(0x7FFF))               # mov edx,0x7FFF      instant
    a.label('done')
    a.b('5F')                           # pop edi
    a.b('59')                           # pop ecx
    a.b('C3')                           # ret -> tail-calls the real HP fn
    return a.assemble(), a.labels


def build_heal():
    a = Asm(CAVE_B)
    a.label('heal')                     # esi=thing, ebp=unit_data, edx=type table
    a.b('50')                           # push eax
    a.b('51')                           # push ecx
    a.b('66 8B 45 10')                  # mov ax,[ebp+0x10]   current hp
    a.b('66 3B 42 01')                  # cmp ax,[edx+1]      max hp
    a.jcc(0x73, 'done')                 # jae done
    a.b('40')                           # inc eax             (original +1 tick)
    a.b('66 89 45 10')                  # mov [ebp+0x10],ax
    a.b('8A 4E 18')                     # mov cl,[esi+0x18]   clan
    a.b('3A 0D') ; a.raw(d32(PLAYER_CLAN))   # cmp cl,[player_clan]
    a.jcc(0x75, 'done')                 # jne done
    a.b('66 8B 42 01')                  # mov ax,[edx+1]      max hp
    a.b('66 89 45 10')                  # mov [ebp+0x10],ax   full hp
    a.label('done')
    a.b('59')                           # pop ecx
    a.b('58')                           # pop eax
    a.b('C3')                           # ret
    return a.assemble(), a.labels


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    rel = relocs(data)

    c_code, c_lab = build_filter()
    b_code, b_lab = build_heal()
    assert CAVE_C + len(c_code) <= CAVE_C_END, (hex(len(c_code)), hex(CAVE_C_END - CAVE_C))
    assert CAVE_B + len(b_code) <= CAVE_B_END, (hex(len(b_code)), hex(CAVE_B_END - CAVE_B))

    # locate labels by walking the emitted bytes
    for va, n in ((CAVE_C, CAVE_C_END - CAVE_C), (CAVE_B, CAVE_B_END - CAVE_B),
                  (HEAL_A_SITE, 15), (HEAL_B_SITE, 13)):
        no_reloc(rel, va, n)

    put_text(data, CAVE_C, c_code, expect_fill=(0x90,))
    put_text(data, CAVE_B, b_code, expect_fill=(0,))

    fV = CAVE_C
    fB = CAVE_C + 5 + 2          # push(5) + jmp short(2)

    for site, orig in CALL_SITES:
        new = fV if orig == BUILDING_HP_FN else fB
        no_reloc(rel, site, 5)
        put_text(data, site, rel32(0xE8, site, new), expect=rel32(0xE8, site, orig))

    a_new = rel32(0xE8, HEAL_A_SITE, CAVE_B)
    a_new += bytes([0xEB, HEAL_A_RESUME - (HEAL_A_SITE + 7)])
    a_new += b'\x90' * (len(HEAL_A_ORIG) - len(a_new))
    put_text(data, HEAL_A_SITE, a_new, expect=HEAL_A_ORIG)

    b_new = bytes.fromhex('8b 54 24 0c') + rel32(0xE8, HEAL_B_SITE + 4, CAVE_B)
    b_new += bytes.fromhex('66 8b 4d 10')
    put_text(data, HEAL_B_SITE, b_new, expect=HEAL_B_ORIG)

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('filter @%08X (%d B)  fV=%08X fB=%08X  heal=%08X (%d B)' %
          (CAVE_C, len(c_code), fV, fB, CAVE_B, len(b_code)))


if __name__ == '__main__':
    main()
