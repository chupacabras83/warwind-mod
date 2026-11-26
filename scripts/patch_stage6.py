"""War Wind patch, stage 6: spell menu shows all races' spells.

Applied ON TOP of patch_stage5.py output (WW.EXE.stage5).

Makes the spell menu builder (basic pass 0x4558D7 / advanced pass 0x45597A)
iterate ALL 24 spell entries (4 races x 6) instead of the caster's own 6, and
drops the "already known" + "mana requirement" gates. Caves go in a new .wwmod
section (VA 0x650000).
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import put_text
from patch_stage4 import add_section, SEC_VA, SEC_RAW

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage5'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage6'

CAVE1 = SEC_VA
CAVE2 = SEC_VA + 0x20


def rel32(src_after, dst):
    return struct.pack('<i', dst - src_after)


def build_caves():
    # cave1 (basic pass): cmp ebx,216 ; je exit ; jmp loop
    p = CAVE1
    code = bytearray()
    code += b'\x81\xfb\xd8\x00\x00\x00'      # cmp ebx,0xD8
    code += b'\x0f\x84' + rel32(p + 12, 0x455A0E)   # je 0x455A0E
    code += b'\xe9' + rel32(p + 17, 0x4558FE)       # jmp 0x4558FE
    # cave2 (advanced pass): cmp ebx,216 ; jne loop ; jmp exit
    code += b'\x00' * (0x20 - len(code))
    p = CAVE2
    code += b'\x81\xfb\xd8\x00\x00\x00'      # cmp ebx,0xD8
    code += b'\x0f\x85' + rel32(p + 12, 0x4559A1)   # jne 0x4559A1
    code += b'\xe9' + rel32(p + 17, 0x455A0E)       # jmp 0x455A0E
    assert len(code) <= SEC_RAW, len(code)
    return bytes(code)


def main():
    data = bytearray(open(EXE_IN, 'rb').read())

    # 1. ignore race: mov [esp+8],eax -> mov [esp+8],ebx (ebx==0 here)
    put_text(data, 0x4558FA, bytes.fromhex('89 5c 24 08'), expect=bytes.fromhex('89 44 24 08'))
    put_text(data, 0x45599D, bytes.fromhex('89 5c 24 04'), expect=bytes.fromhex('89 44 24 04'))

    # 2. bypass "already known" gate (jne skip -> nop)
    put_text(data, 0x455947, bytes.fromhex('90 90'), expect=bytes.fromhex('75 23'))
    put_text(data, 0x4559E1, bytes.fromhex('90 90'), expect=bytes.fromhex('75 23'))

    # 3. bypass "mana requirement" gate (jb skip -> nop)
    put_text(data, 0x455964, bytes.fromhex('90 90'), expect=bytes.fromhex('72 06'))
    put_text(data, 0x4559FE, bytes.fromhex('90 90'), expect=bytes.fromhex('72 06'))

    # 3b. bypass "researched/available" gate (je skip -> nop)
    put_text(data, 0x45591D, bytes.fromhex('90 90'), expect=bytes.fromhex('74 4d'))
    put_text(data, 0x4559B7, bytes.fromhex('90 90'), expect=bytes.fromhex('74 4d'))

    # 4. basic pass loop tail -> jmp cave1 (11 bytes: cmp+je+jmp -> jmp+NOPx6)
    j1 = b'\xe9' + struct.pack('<i', CAVE1 - (0x45596F + 5))
    put_text(data, 0x45596F, j1 + b'\x90' * 6,
             expect=bytes.fromhex('83 fb 36 0f 84 96 00 00 00 eb 84'))

    # 5. advanced pass loop tail -> jmp cave2 (5 bytes: cmp+jne -> jmp)
    j2 = b'\xe9' + struct.pack('<i', CAVE2 - (0x455A09 + 5))
    put_text(data, 0x455A09, j2, expect=bytes.fromhex('83 fb 36 75 93'))

    # 6. append caves as a new section
    add_section(data, build_caves())

    # 7. bypass the learn/cast handler's research gate (je fail -> nop) so any
    #    spell can be learned/cast regardless of clan research level.
    put_text(data, 0x48B9E5, bytes.fromhex('90' * 6), expect=bytes.fromhex('0f 84 8c 00 00 00'))

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('cave1 @%08X  cave2 @%08X  section .wwmod @%08X' % (CAVE1, CAVE2, SEC_VA))


if __name__ == '__main__':
    main()
