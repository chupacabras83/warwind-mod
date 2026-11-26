"""War Wind patch, stage 11: auto-grant full upgrades + all spells on ownership.

Whenever a unit becomes player-owned it immediately receives:
  * all 5 upgrades (Strength, Stealth, Vision, Resilience, Speed) + their stat
    bonuses -- applied once, so repeated calls cannot stack
  * full spell mask (0xFF) and a full mana bar, if the type can cast at all
  * full current HP

Hook points, so every acquisition route is covered:

  1. create_unit exit (0x42CA7A) -- hiring from an Inn, training at a
     War College / Arcanery, heroes and mercenaries. ECX = new thing index.

  2. Mind control (0x48D65B: `mov [0x5044b8+eax*4],bh` forces the target's
     clan to the player's). This is the Command Voice / Nature's Voice
     conversion path; [ebp-4] = target thing index. Covers every converted
     unit, including enemy clan leaders such as Druk Angrak.

  3. Mission start sweep: every existing thing is granted once after load.

Applied ON TOP of WW.EXE.stage10b.
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import Asm, d32, no_reloc, put_text, relocs, THING, UDATA, TT, PLAYER_CLAN


class Asm2(Asm):
    """Asm plus near (rel32) conditional jumps for long forward branches."""

    def jcc_near(self, op, name):
        # op is the short form (0x74 je, 0x75 jne, 0x72 jb); map to 0F 8x
        self.items.append(('jcc_near', op, name))

    def assemble(self):
        sizes = {'raw': None, 'label': 0, 'jcc': 2, 'jcc_near': 6, 'rel32': 5}
        pc = self.base
        for it in self.items:
            if it[0] == 'label':
                self.labels[it[1]] = pc
            pc += len(it[1]) if it[0] == 'raw' else sizes[it[0]]
        out, pc = bytearray(), self.base
        for it in self.items:
            if it[0] == 'raw':
                out += it[1]
            elif it[0] == 'jcc':
                rel = self.labels[it[2]] - (pc + 2)
                assert -128 <= rel <= 127, it
                out += bytes([it[1], rel & 0xFF])
            elif it[0] == 'jcc_near':
                rel = self.labels[it[2]] - (pc + 6)
                out += bytes([0x0F, it[1] + 0x10]) + struct.pack('<i', rel)
            elif it[0] == 'rel32':
                out += bytes([it[1]]) + struct.pack('<i', it[2] - (pc + 5))
            pc = self.base + len(out)
        return bytes(out)

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage10b'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage11'

GRANT = 0x650100          # .wwmod section (added by stage 6); spell caves use
GRANT_END = 0x651000      # only 0x650000..0x650060, so this is all free.

NEW_SITE = 0x42CA7A
NEW_ORIG = bytes.fromhex('89 c8 83 c4 14')
NEW_RESUME = 0x42CA7F

MC_SITE = 0x48D662
MC_ORIG = bytes.fromhex('bb 01 00 00 00')     # mov ebx,1
MC_RESUME = MC_SITE + len(MC_ORIG)

# stage-5b cave tail: the `jmp 0x41FB5B` at 0x4158D3 resumes normally; we
# insert the mission-start sweep in the nop area that follows it.
LS_CAVE = 0x4158D8
LS_CAVE_END = 0x415925
LS_RESUME = 0x41FB5B


def v2f(data, va, n=1):
    """Map a virtual address to a file offset using the PE section table."""
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    opt = pe + 24
    secoff = opt + struct.unpack_from('<H', data, pe + 20)[0]
    imagebase = struct.unpack_from('<I', data, opt + 28)[0]
    rva = va - imagebase
    for i in range(nsec):
        o = secoff + i * 40
        vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', data, o + 8)
        span = max(vsize, rawsize)
        if vaddr <= rva < vaddr + span:
            return rawptr + (rva - vaddr)
    raise ValueError('VA 0x%X not in any section' % va)


def grow_section_for(data, va, n):
    """Ensure the section containing `va` physically holds `n` bytes there.

    Windows maps only SizeOfRawData bytes of a section from the file and
    zero-fills the remainder of the virtual range. Writing past RawSize
    therefore produces code that is not in the loaded image -- calls into it
    jump to zeros and crash. This grows RawSize (and VirtualSize /
    SizeOfImage) and pads the file so the bytes are genuinely present.
    """
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    opt = pe + 24
    secoff = opt + struct.unpack_from('<H', data, pe + 20)[0]
    imagebase = struct.unpack_from('<I', data, opt + 28)[0]
    sizeimage_off = opt + 56
    rva = va - imagebase
    for i in range(nsec):
        o = secoff + i * 40
        vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', data, o + 8)
        span = max(vsize, rawsize)
        if vaddr <= rva < vaddr + span:
            need_rva = (rva - vaddr) + n
            need_raw = (need_rva + 0x1FF) & ~0x1FF
            changed = False
            if need_raw > rawsize:
                struct.pack_into('<I', data, o + 16, need_raw)
                rawsize = need_raw
                changed = True
            if vsize < rawsize:
                struct.pack_into('<I', data, o + 8, rawsize)
                vsize = rawsize
                changed = True
            total = rawptr + rawsize
            if len(data) < total:
                data += b'\x00' * (total - len(data))
                changed = True
            sizeimage = struct.unpack_from('<I', data, sizeimage_off)[0]
            if sizeimage < vaddr + vsize:
                struct.pack_into('<I', data, sizeimage_off,
                                 (vaddr + vsize + 0xFFF) & ~0xFFF)
            return changed
    raise ValueError('VA 0x%X not in any section' % va)


def put_any(data, va, blob, expect_fill=None):
    """put_text for any section; grows the section so the bytes are loaded."""
    grow_section_for(data, va, len(blob))
    fo = v2f(data, va, len(blob))
    cur = bytes(data[fo:fo + len(blob)])
    if expect_fill is not None:
        allowed = tuple(expect_fill) if isinstance(expect_fill, (list, tuple)) else (expect_fill,)
        assert all(b in allowed for b in cur), '%08X: not free: %s' % (va, cur.hex(' '))
    data[fo:fo + len(blob)] = blob


def build_grant():
    a = Asm2(GRANT)
    a.b('60')                                          # pushad
    a.b('0F B7 C0')                                    # movzx eax,ax
    a.b('6B F0 7C')                                    # imul esi,eax,0x7C
    a.b('80 BE') ; a.raw(d32(THING + 1)) ; a.b('02')   # cmp byte [esi+cat],2
    a.jcc_near(0x75, 'done')                           # not a unit
    a.b('8A 86') ; a.raw(d32(THING + 0x18))            # mov al,[esi+clan]
    a.b('3A 05') ; a.raw(d32(PLAYER_CLAN))             # cmp al,[player_clan]
    a.jcc_near(0x75, 'done')                           # not ours
    a.b('0F B7 BE') ; a.raw(d32(THING + 2))            # movzx edi,[esi+ud_idx]
    a.b('85 FF')                                       # test edi,edi
    a.jcc_near(0x74, 'done')
    a.b('6B FF 78')                                    # imul edi,edi,0x78
    a.b('81 C7') ; a.raw(d32(UDATA))                   # add edi,UDATA
    a.b('8A 47 23')                                    # mov al,[edi+0x23]

    ups = [(0x01, 'FE 47 1A'),      # Strength   +1 str
           (0x02, 'FE 47 1E'),      # Stealth    +1 stealth
           (0x04, '80 47 1C 04'),   # Vision     +4 vision
           (0x08, 'FE 47 1B'),      # Resilience +1 armor
           (0x10, '80 47 1D 02')]   # Speed      +2 speed
    for k, (bit, bonus) in enumerate(ups):
        a.b('A8 %02X' % bit)                           # test al,bit
        a.jcc(0x75, 'u%d' % k)                         # already owned
        a.b('80 4F 23 %02X' % bit)                     # or [edi+0x23],bit
        a.b(bonus)                                     # apply bonus
        a.label('u%d' % k)

    a.b('0F B6 8E') ; a.raw(d32(THING))                # movzx ecx,[esi+type]
    a.b('C1 E1 05')                                    # shl ecx,5
    a.b('8A 91') ; a.raw(d32(TT + 0x12))               # mov dl,[ecx+TT.maxmana]
    a.b('84 D2')                                       # test dl,dl
    a.jcc_near(0x74, 'hp')                             # not a caster
    a.b('C6 47 27 FF')                                 # mov byte [edi+0x27],0xFF
    a.b('88 57 12')                                    # mov [edi+0x12],dl

    a.label('hp')
    a.b('0F B6 8E') ; a.raw(d32(THING))                # movzx ecx,[esi+type]
    a.b('C1 E1 05')                                    # shl ecx,5
    a.b('0F B7 91') ; a.raw(d32(TT + 1))               # movzx edx,[ecx+TT+1]
    a.b('85 D2')                                       # test edx,edx
    a.jcc(0x74, 'done')
    a.b('66 89 57 10')                                 # mov [edi+0x10],dx
    a.label('done')
    a.b('61 C3')                                       # popad ; ret
    code = a.assemble()
    assert GRANT + len(code) <= GRANT_END, 'grant too big: %s' % hex(len(code))
    return code


def build_new_hook(at):
    a = Asm2(at)
    a.b('89 C8')                                       # mov eax,ecx
    a.b('83 C4 14')                                    # add esp,0x14
    a.b('60')                                          # pushad
    a.b('0F B7 C1')                                    # movzx eax,cx
    a.b('66 50')                                       # push ax
    a.rel32(0xE8, GRANT)
    a.b('66 58')                                       # pop ax
    a.b('61')                                          # popad
    a.rel32(0xE9, NEW_RESUME)
    code = a.assemble()
    assert len(code) == 0x18, hex(len(code))
    return code


def build_mc_hook(at):
    a = Asm2(at)
    a.b('bb 01 00 00 00')                              # mov ebx,1  (original)
    a.b('60')                                          # pushad
    a.b('66 8B 45 FC')                                 # mov ax,[ebp-4]
    a.b('66 50')                                       # push ax
    a.rel32(0xE8, GRANT)
    a.b('66 58')                                       # pop ax
    a.b('61')                                          # popad
    a.rel32(0xE9, MC_RESUME)
    return a.assemble()


def build_ls_sweep():
    a = Asm2(LS_CAVE)
    a.b('60')                                          # pushad
    a.b('31 C0')                                       # xor eax,eax
    a.label('loop')
    a.b('66 50')                                       # push ax
    a.rel32(0xE8, GRANT)
    a.b('66 58')                                       # pop ax
    a.b('40')                                          # inc eax
    a.b('3D') ; a.raw(d32(0x800))                      # cmp eax,0x800
    a.jcc(0x72, 'loop')                                # jb loop
    a.b('61')                                          # popad
    a.rel32(0xE9, LS_RESUME)
    code = a.assemble()
    assert LS_CAVE + len(code) <= LS_CAVE_END, 'ls sweep too big: %s' % hex(len(code))
    return code


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    rel = relocs(data)

    grant = build_grant()
    new_at = GRANT + len(grant)
    mc_at = new_at + 0x18          # new hook is exactly 24 bytes
    new_hook = build_new_hook(new_at)
    mc_hook = build_mc_hook(mc_at)
    ls_sweep = build_ls_sweep()

    # ---- 1. grant + the two hook stubs live in the zero-filled grant area ----
    off = GRANT
    put_any(data, GRANT, grant, expect_fill=(0,))
    off = GRANT + len(grant)

    new_at = off
    put_any(data, new_at, new_hook, expect_fill=(0,))
    off += len(new_hook)

    mc_at = off
    put_any(data, mc_at, mc_hook, expect_fill=(0,))
    off += len(mc_hook)
    assert off <= GRANT_END, 'stubs overflow .wwmod area'

    # ---- 2. retarget the real sites ----
    def rel32(op, src, dst):
        return bytes([op]) + struct.pack('<i', dst - (src + 5))

    # create_unit exit -> jump to our new-unit stub
    no_reloc(rel, NEW_SITE, 5)
    put_text(data, NEW_SITE, rel32(0xE9, NEW_SITE, new_at), expect=NEW_ORIG)

    # mind-control -> jump to our post-conversion stub
    no_reloc(rel, MC_SITE, 5)
    put_text(data, MC_SITE, rel32(0xE9, MC_SITE, mc_at), expect=MC_ORIG)

    # ---- 3. mission-start sweep in the stage-5b nop tail ----
    put_text(data, LS_CAVE, ls_sweep, expect_fill=(0x90,))
    # re-point the stage-5b cave's final jmp (0x4158D3) at the sweep
    put_text(data, 0x4158D3,
             rel32(0xE9, 0x4158D3, LS_CAVE),
             expect=rel32(0xE9, 0x4158D3, LS_RESUME))

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('grant @%08X (%d B)' % (GRANT, len(grant)))
    print('new-unit stub @%08X (%d B)' % (new_at, len(new_hook)))
    print('mindcontrol stub @%08X (%d B)' % (mc_at, len(mc_hook)))
    print('mission sweep @%08X (%d B)' % (LS_CAVE, len(ls_sweep)))


if __name__ == '__main__':
    main()
