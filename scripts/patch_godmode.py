"""War Wind god-mode patch, stage 2. Applied ON TOP of patch_resources.py output.

Usage:
  python patch_resources.py backup\\WW.EXE.orig patched\\WW.EXE.stage1 99999
  python patch_godmode.py   patched\\WW.EXE.stage1 patched\\WW.EXE

Effects. "Player-owned" means thing+0x18 (clan) == [0x4B342C] (local player clan).

1. Invincible: player-owned units whose type class (TT+0) is
   1 (clan leaders: Minister/War General/Primemaker/Shadow Dancer),
   2 or 3 (builders), or 12 or 13 (named heroes).
   Hook: entry of the damage routine 0x45AA4C. Protected units return 0
   ("not dead") before any HP change or death logic runs.
2. Every spell costs 1 mana. The 20 cost bytes in the spell table at
   0x4B63E8 (stride 18, +6) are set to 1. Nature's voice drain 100 -> 1.
   NOTE: the table is shared, so enemy casters also pay 1.
3. Player-owned units get all 5 upgrades. Each missing upgrade bit is set and
   its stat bonus applied, except the Resilience speed penalty (per user
   choice). Units with mana also get spell mask 0xFF and a full mana bar.
   Applied (a) to every new unit (create_unit exit 0x42CA7A) and
   (b) to all things at mission start (existing 0x41FB55 cave, after load).

Data layout (see wwwork\\swarm_*\\FINDINGS.md):
  thing     = 0x5044A0 + i*0x7C
              +0 type, +1 category (2 = unit), +2 unit_data idx, +0x18 clan
  unit_data = 0x4EA7A0 + a*0x78
              +0x12 mana, +0x1A str, +0x1B armor, +0x1C vision, +0x1D speed,
              +0x1E stealth, +0x23 upgrade bits, +0x27 spell mask
  TT        = 0x4B3C38 + type*0x20
              +0 class, +0x12 max mana
"""
import hashlib
import struct
import sys

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage1'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE'

TEXT_VA, TEXT_FILE, TEXT_RAW = 0x410000, 0x400, 0x90C00
DATA_VA, DATA_FILE = 0x4B0000, 0x91000

THING, UDATA, TT = 0x5044A0, 0x4EA7A0, 0x4B3C38
PLAYER_CLAN = 0x4B342C
PROTECT_CLASSES = (1, 2, 3, 12, 13)

# code locations
GRANT_VA = 0x4A0B30            # 208 free bytes at the end of BEGTEXT
GRANT_END = 0x4A0C00
STAGE1_JMP = 0x4158A6          # final `jmp 0x41FB5B` of the stage-1 cave
FREE2_VA = 0x4158AB            # rest of the stage-1 cave (nop padding)
FREE2_END = 0x415958

DMG_VA, DMG_ORIG, DMG_RESUME = 0x45AA4C, bytes.fromhex('56 57 55 83 EC 1C'), 0x45AA52
NEW_VA, NEW_ORIG, NEW_RESUME = 0x42CA7A, bytes.fromhex('89 C8 83 C4 14'), 0x42CA7F
LS_RESUME = 0x41FB5B

SPELL_COST0 = 0x4B63EE         # cost byte of spell 0; stride 18
SPELL_ORIG = [10, 10, 10, 30, 60, 15, 35, 60, 30, 5, 5, 45, 25, 60, 40, 20, 10, 85, 25, 60]
NV_SITE = 0x453F4C             # Nature's voice: jge +7 ; mov edi,100
NV_ORIG = bytes.fromhex('7D 07 BF 64 00 00 00')
NV_NEW = bytes.fromhex('90 90 BF 01 00 00 00')


def tfoff(va, n=1):
    assert TEXT_VA <= va and va + n <= TEXT_VA + TEXT_RAW, hex(va)
    return TEXT_FILE + va - TEXT_VA


def dfoff(va):
    return DATA_FILE + va - DATA_VA


def d32(x):
    return struct.pack('<I', x & 0xFFFFFFFF)


class Asm:
    """Tiny assembler: raw bytes, short jcc to labels, rel32 jmp/call to absolute VAs."""

    def __init__(self, base):
        self.base, self.items, self.labels = base, [], {}

    def b(self, hexstr):
        self.items.append(('raw', bytes.fromhex(hexstr)))

    def raw(self, data):
        self.items.append(('raw', data))

    def label(self, name):
        self.items.append(('label', name))

    def jcc(self, op, name):            # op: 0x74 je, 0x75 jne, 0x72 jb, 0xEB jmp
        self.items.append(('jcc', op, name))

    def rel32(self, op, target):        # 0xE8 call, 0xE9 jmp
        self.items.append(('rel32', op, target))

    def assemble(self):
        sizes = {'raw': None, 'label': 0, 'jcc': 2, 'rel32': 5}
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
            elif it[0] == 'rel32':
                out += bytes([it[1]]) + struct.pack('<i', it[2] - (pc + 5))
            pc = self.base + len(out)
        return bytes(out)


def build_grant():
    """grant(ax = thing index). Preserves all registers (pushad/popad)."""
    a = Asm(GRANT_VA)
    a.b('60')                                         # pushad
    a.b('0F B7 C0')                                   # movzx eax,ax
    a.b('6B F0 7C')                                   # imul esi,eax,0x7C
    a.b('80 BE') ; a.raw(d32(THING + 1)) ; a.b('02')  # cmp byte [esi+thing.cat],2
    a.jcc(0x75, 'done')
    a.b('8A 86') ; a.raw(d32(THING + 0x18))           # mov al,[esi+thing.clan]
    a.b('3A 05') ; a.raw(d32(PLAYER_CLAN))            # cmp al,[player_clan]
    a.jcc(0x75, 'done')
    a.b('0F B7 BE') ; a.raw(d32(THING + 2))           # movzx edi,word [esi+thing.active]
    a.b('85 FF')                                      # test edi,edi
    a.jcc(0x74, 'done')
    a.b('6B FF 78')                                   # imul edi,edi,0x78
    a.b('81 C7') ; a.raw(d32(UDATA))                  # add edi,unit_data
    a.b('8A 47 23')                                   # mov al,[edi+0x23]
    # (bit, stat bonus instruction) -- Resilience speed penalty intentionally omitted
    ups = [(0x01, 'FE 47 1A'),        # Strength:   inc byte [edi+0x1A]
           (0x02, 'FE 47 1E'),        # Stealth:    inc byte [edi+0x1E]
           (0x04, '80 47 1C 04'),     # Vision:     add byte [edi+0x1C],4
           (0x08, 'FE 47 1B'),        # Resilience: inc byte [edi+0x1B] (armor)
           (0x10, '80 47 1D 02')]     # Speed:      add byte [edi+0x1D],2
    for k, (bit, bonus) in enumerate(ups):
        a.b('A8 %02X' % bit)                          # test al,bit
        a.jcc(0x75, 'u%d' % k)
        a.b('80 4F 23 %02X' % bit)                    # or byte [edi+0x23],bit
        a.b(bonus)
        a.label('u%d' % k)
    a.b('0F B6 8E') ; a.raw(d32(THING))               # movzx ecx,byte [esi+thing.type]
    a.b('C1 E1 05')                                   # shl ecx,5
    a.b('8A 91') ; a.raw(d32(TT + 0x12))              # mov dl,[ecx+TT.maxmana]
    a.b('84 D2')                                      # test dl,dl
    a.jcc(0x74, 'done')                               # no mana -> not a caster
    a.b('C6 47 27 FF')                                # mov byte [edi+0x27],0xFF
    a.b('88 57 12')                                   # mov [edi+0x12],dl (full mana)
    a.label('done')
    a.b('61 C3')                                      # popad ; ret
    return a.assemble()


def build_free2():
    """New-unit stub, level-start stub, damage filter. Returns (code, labels)."""
    a = Asm(FREE2_VA)
    # --- new unit: replaces `mov eax,ecx ; add esp,0x14` at 0x42CA7A
    a.label('new')
    a.b('89 C8 83 C4 14')                             # original instructions
    a.rel32(0xE8, GRANT_VA)                           # call grant (ax = thing idx)
    a.rel32(0xE9, NEW_RESUME)
    # --- level start: reached from the stage-1 cave instead of `jmp 0x41FB5B`
    a.label('ls')
    a.b('60 31 C0')                                   # pushad ; xor eax,eax
    a.label('ls_loop')
    a.rel32(0xE8, GRANT_VA)
    a.b('40')                                         # inc eax
    a.b('3D') ; a.raw(d32(0x800))                     # cmp eax,0x800
    a.jcc(0x72, 'ls_loop')                            # jb
    a.b('61')                                         # popad
    a.rel32(0xE9, LS_RESUME)
    # --- damage filter at entry of 0x45AA4C (edx = victim thing index)
    a.label('dmg')
    a.b('50 51')                                      # push eax ; push ecx
    a.b('0F B7 C2')                                   # movzx eax,dx
    a.b('6B C0 7C')                                   # imul eax,eax,0x7C
    a.b('80 B8') ; a.raw(d32(THING + 1)) ; a.b('02')  # cmp byte [eax+thing.cat],2
    a.jcc(0x75, 'dmg_orig')
    a.b('8A 88') ; a.raw(d32(THING + 0x18))           # mov cl,[eax+thing.clan]
    a.b('3A 0D') ; a.raw(d32(PLAYER_CLAN))            # cmp cl,[player_clan]
    a.jcc(0x75, 'dmg_orig')
    a.b('0F B6 80') ; a.raw(d32(THING))               # movzx eax,byte [eax+thing.type]
    a.b('C1 E0 05')                                   # shl eax,5
    a.b('8A 80') ; a.raw(d32(TT))                     # mov al,[eax+TT.class]
    for c in PROTECT_CLASSES:
        a.b('3C %02X' % c)                            # cmp al,c
        a.jcc(0x74, 'dmg_prot')
    a.label('dmg_orig')
    a.b('59 58')                                      # pop ecx ; pop eax
    a.raw(DMG_ORIG)                                   # push esi/edi/ebp ; sub esp,0x1c
    a.rel32(0xE9, DMG_RESUME)
    a.label('dmg_prot')
    a.b('59 58 31 C0 C3')                             # pop ecx ; pop eax ; xor eax,eax ; ret
    code = a.assemble()
    return code, a.labels


def relocs(data):
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    so = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0]
    for i in range(nsec):
        o = so + i * 40
        if data[o:o + 8].rstrip(b'\0') == b'.reloc':
            p = struct.unpack_from('<I', data, o + 20)[0]
            end = p + struct.unpack_from('<I', data, o + 16)[0]
            break
    out = set()
    while p < end:
        page, size = struct.unpack_from('<II', data, p)
        if size == 0:
            break
        for k in range(8, size, 2):
            w = struct.unpack_from('<H', data, p + k)[0]
            if w >> 12 == 3:
                out.add(0x400000 + page + (w & 0xFFF))
        p += size
    return out


def no_reloc(rel, va, n):
    hit = [r for r in rel if r + 4 > va and r < va + n]
    if hit:
        raise SystemExit('relocation(s) %s overlap %08X+%d' % ([hex(h) for h in hit], va, n))


def put_text(data, va, new, expect=None, expect_fill=None):
    o = tfoff(va, len(new))
    cur = bytes(data[o:o + len(new)])
    if expect is not None and cur != expect:
        raise SystemExit('%08X: expected %s, found %s' % (va, expect.hex(' '), cur.hex(' ')))
    if expect_fill is not None and any(x not in expect_fill for x in cur):
        raise SystemExit('%08X: cave not free: %s' % (va, cur.hex(' ')))
    data[o:o + len(new)] = new


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    rel = relocs(data)

    # stage-1 sanity: the cave must end in `jmp 0x41FB5B` at STAGE1_JMP
    o = tfoff(STAGE1_JMP, 5)
    if data[o] != 0xE9 or STAGE1_JMP + 5 + struct.unpack_from('<i', data, o + 1)[0] != LS_RESUME:
        raise SystemExit('input is not the stage-1 (patch_resources) exe')

    grant = build_grant()
    free2, lab = build_free2()
    assert GRANT_VA + len(grant) <= GRANT_END, len(grant)
    assert FREE2_VA + len(free2) <= FREE2_END, len(free2)
    for va, n in ((GRANT_VA, GRANT_END - GRANT_VA), (FREE2_VA, FREE2_END - FREE2_VA),
                  (DMG_VA, 6), (NEW_VA, 5), (STAGE1_JMP, 5)):
        no_reloc(rel, va, n)

    put_text(data, GRANT_VA, grant, expect_fill=(0,))
    put_text(data, FREE2_VA, free2, expect_fill=(0x90,))

    def jmp(src, dst, pad=0):
        return b'\xE9' + struct.pack('<i', dst - (src + 5)) + b'\x90' * pad

    put_text(data, NEW_VA, jmp(NEW_VA, lab['new']), expect=NEW_ORIG)
    put_text(data, DMG_VA, jmp(DMG_VA, lab['dmg'], 1), expect=DMG_ORIG)
    data[tfoff(STAGE1_JMP):tfoff(STAGE1_JMP) + 5] = jmp(STAGE1_JMP, lab['ls'])

    # spell costs -> 1
    for i, c in enumerate(SPELL_ORIG):
        va = SPELL_COST0 + 18 * i
        if data[dfoff(va)] != c:
            raise SystemExit('spell %d cost %d != expected %d' % (i, data[dfoff(va)], c))
        no_reloc(rel, va, 1)
        data[dfoff(va)] = 1
    put_text(data, NV_SITE, NV_NEW, expect=NV_ORIG)
    no_reloc(rel, NV_SITE, len(NV_NEW))

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('grant   @%08X %3d bytes' % (GRANT_VA, len(grant)))
    print('stubs   @%08X %3d bytes  new=%08X ls=%08X dmg=%08X' %
          (FREE2_VA, len(free2), lab['new'], lab['ls'], lab['dmg']))
    print('hooks   %08X->new  %08X->dmg  %08X->ls' % (NEW_VA, DMG_VA, STAGE1_JMP))
    print('spells  20 costs -> 1, Nature\'s voice drain -> 1')


if __name__ == '__main__':
    main()
