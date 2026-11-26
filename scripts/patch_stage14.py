"""War Wind patch, stage 14: player-only damage/attack boost (Option B).

Applied ON TOP of WW.EXE.stage13.

Hooks the ENTRY of the damage/attack routine at 0x45AA4C and, when the
ATTACKER is player-owned, raises the damage delta (bx) so the attacker hits
for maximum. Enemy units keep their original damage -- the type table is never
modified.

Routine entry contract (verified from the original bytes 56 57 55 83 EC 1C):
    eax = target thing index   (stored to [esp+12] after the prologue)
    edx = attacker thing index (moved to edi)
    bx  = damage delta         (stored to [esp+16])
    cl  = flag                 (stored to [esp+24])

Because the very first bytes are the prologue, the hook must run BEFORE it.
We relocate the 6 original bytes into the cave, boost bx for player attackers,
then jump back to 0x45AA52 with the stack exactly as the prologue left it.

thing = 0x5044A0 + i*0x7C :  +1 category (2 = unit), +0x18 clan
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import put_text, relocs, no_reloc, THING, PLAYER_CLAN
from patch_stage11 import Asm2, v2f, put_any, d32

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage13'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage14'

DMG_ENTRY = 0x45AA4C
DMG_PROLOGUE = bytes.fromhex('56 57 55 83 ec 1c')     # push esi/edi/ebp ; sub esp,0x1c
DMG_RESUME = DMG_ENTRY + len(DMG_PROLOGUE)            # 0x45AA52

CAVE = 0x650800            # .wwmod, still free after stage 13
CAVE_END = 0x651000

BOOST_DELTA = 0x7FFF       # large but the routine clamps to remaining HP


def build_stub():
    """Boost bx (damage) when the attacker (edx) is a player-owned unit."""
    a = Asm2(CAVE)

    # --- relocated prologue ---
    a.b('56 57 55 83 ec 1c')                           # push esi ; push edi ; push ebp ; sub esp,0x1c

    # --- save what we use ---
    a.b('50')                                          # push eax   (target idx)
    a.b('51')                                          # push ecx   (flag)
    a.b('52')                                          # push edx   (attacker idx)
    a.b('53')                                          # push ebx   (damage delta)

    # attacker index (edx, 16-bit) -> masked thing pointer
    a.b('0F B7 DA')                                    # movzx ebx,dx
    a.b('6B DB 7C')                                    # imul ebx,ebx,0x7C  thing stride
    a.b('8A 9B') ; a.raw(d32(THING + 1))               # mov bl,[ebx+thing.cat]
    a.b('80 FB 02')                                    # cmp bl,2           a unit?
    a.jcc_near(0x75, 'restore')                        # not a unit -> skip

    # check attacker clan == player clan
    a.b('0F B7 DA')                                    # movzx ebx,dx
    a.b('6B DB 7C')                                    # imul ebx,ebx,0x7C
    a.b('8A 9B') ; a.raw(d32(THING + 0x18))            # mov bl,[ebx+thing.clan]
    a.b('3A 1D') ; a.raw(d32(PLAYER_CLAN))             # cmp bl,[player_clan]
    a.jcc_near(0x75, 'restore')                        # enemy -> original damage

    # player attacker: force maximum damage delta
    a.b('5B')                                          # pop ebx   (discard old delta)
    a.b('BB') ; a.raw(d32(BOOST_DELTA))                # mov ebx,0x7FFF
    a.b('53')                                          # push ebx  (rebalance)
    a.label('restore')
    a.b('5B')                                          # pop ebx
    a.b('5A')                                          # pop edx
    a.b('59')                                          # pop ecx
    a.b('58')                                          # pop eax
    a.rel32(0xE9, DMG_RESUME)                          # continue the original routine
    code = a.assemble()
    assert CAVE + len(code) <= CAVE_END, hex(len(code))
    return code


def grow_wwmod(data, need_end_va):
    """Extend .wwmod's RawSize so code up to need_end_va is physically loaded.

    Windows maps only SizeOfRawData bytes from the file and zero-fills the rest
    of the virtual range, so any code written beyond rawsize silently becomes
    zeros at run time (and calls into it crash). Grow the raw extent and pad
    the file so the bytes are really there.
    """
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    opt = pe + 24
    secoff = opt + struct.unpack_from('<H', data, pe + 20)[0]
    imagebase = struct.unpack_from('<I', data, opt + 28)[0]
    sizeimage_off = opt + 56
    for i in range(nsec):
        o = secoff + i * 40
        name = bytes(data[o:o + 8]).rstrip(b'\0').decode()
        if name != '.wwmod':
            continue
        vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', data, o + 8)
        need_rva = need_end_va - imagebase - vaddr
        need_raw = (need_rva + 0x1FF) & ~0x1FF
        if need_raw > rawsize:
            struct.pack_into('<I', data, o + 16, need_raw)
            rawsize = need_raw
        if vsize < need_raw:
            vsize = (need_raw + 0xFFF) & ~0xFFF
            struct.pack_into('<I', data, o + 8, vsize)
        total = rawptr + rawsize
        if len(data) < total:
            data += b'\x00' * (total - len(data))
        sizeimage = struct.unpack_from('<I', data, sizeimage_off)[0]
        if sizeimage < vaddr + vsize:
            struct.pack_into('<I', data, sizeimage_off,
                             (vaddr + vsize + 0xFFF) & ~0xFFF)
        print('.wwmod rawsize=0x%X vsize=0x%X (covers up to VA 0x%X)' %
              (rawsize, vsize, imagebase + vaddr + rawsize))
        return


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    rel = relocs(data)

    stub = build_stub()
    # make room in the file for the stub BEFORE writing it
    grow_wwmod(data, CAVE + len(stub))
    put_any(data, CAVE, stub, expect_fill=(0,))

    # redirect the routine entry to our stub: overwrite the first 5 bytes with
    # a jmp, and nop the leftover 6th byte of the original 6-byte prologue.
    no_reloc(rel, DMG_ENTRY, len(DMG_PROLOGUE))
    put_text(data, DMG_ENTRY, b'\xe9' + struct.pack('<i', CAVE - (DMG_ENTRY + 5)))
    put_text(data, DMG_ENTRY + 5, b'\x90', expect=b'\x1c')

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('damage hook @%08X -> stub @%08X (%d B), resume @%08X' %
          (DMG_ENTRY, CAVE, len(stub), DMG_RESUME))


if __name__ == '__main__':
    main()
