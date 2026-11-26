"""Byte-level verification for stage 11 (no disassembler quirks)."""
import struct
import sys

path = sys.argv[1] if len(sys.argv) > 1 else \
    r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch\patched\WW.EXE.stage11'
cur = open(path, 'rb').read()

pe = struct.unpack_from('<I', cur, 0x3C)[0]
nsec = struct.unpack_from('<H', cur, pe + 6)[0]
opt = pe + 24
secoff = opt + struct.unpack_from('<H', cur, pe + 20)[0]
imagebase = struct.unpack_from('<I', cur, opt + 28)[0]
SECS = []
for i in range(nsec):
    o = secoff + i * 40
    vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', cur, o + 8)
    SECS.append((vaddr, max(vsize, rawsize), rawptr))


def v2f(va):
    for vaddr, span, rawptr in SECS:
        if vaddr <= va - imagebase < vaddr + span:
            return rawptr + (va - imagebase - vaddr)
    raise ValueError(hex(va))


def at(va, n):
    o = v2f(va)
    return cur[o:o + n]


def call_target(site):
    d = struct.unpack_from('<i', at(site + 1, 4), 0)[0]
    return site + 5 + d


def jmp_target(site):
    d = struct.unpack_from('<i', at(site + 1, 4), 0)[0]
    return site + 5 + d


fails = []


def ck(name, cond, extra=''):
    print('  %-44s %s %s' % (name, 'OK' if cond else 'FAIL', extra))
    if not cond:
        fails.append(name)


print('=== stage11 byte verification: %s ===' % path)

G = 0x650100
# pushad, movzx eax,ax, imul esi,eax,0x7C
ck('grant: pushad', at(G, 1) == b'\x60')
ck('grant: movzx eax,ax', at(G + 1, 3) == bytes.fromhex('0f b7 c0'))
ck('grant: imul esi,eax,0x7C', at(G + 4, 3) == bytes.fromhex('6b f0 7c'))
ck('grant: cmp cat,2', at(G + 7, 7) == bytes.fromhex('80 be a1 44 50 00 02'))
ck('grant: add edi,UDATA(0x4EA7A0)',
   at(G + 0x38, 6) == bytes.fromhex('81 c7 a0 a7 4e 00'))
ck('grant: 5 upgrade bits present',
   all(b in at(G, 180) for b in (0x01, 0x02, 0x04, 0x08, 0x10)))
ck('grant: spell mask 0xFF', bytes.fromhex('c6 47 27 ff') in at(G, 180))
ck('grant: full mana', bytes.fromhex('88 57 12') in at(G, 180))
ck('grant: full HP write', bytes.fromhex('66 89 57 10') in at(G, 180))
ck('grant: popad', at(G + 178, 1) == b'\x61')
ck('grant: ret', at(G + 179, 1) == b'\xc3')

# new-unit stub
N = 0x6501B4
ck('new stub: mov eax,ecx', at(N, 2) == bytes.fromhex('89 c8'))
ck('new stub: add esp,0x14', at(N + 2, 3) == bytes.fromhex('83 c4 14'))
ck('new stub: pushad', at(N + 5, 1) == b'\x60')
ck('new stub: calls grant', call_target(N + 11) == G, '-> %08X' % call_target(N + 11))
ck('new stub: popad', at(N + 18, 1) == b'\x61')
ck('new stub: jmp resume', jmp_target(N + 19) == 0x42CA7F, '-> %08X' % jmp_target(N + 19))

# mind-control stub
M = 0x6501CC
ck('mc stub: mov ebx,1 kept', at(M, 5) == bytes.fromhex('bb 01 00 00 00'))
ck('mc stub: pushad', at(M + 5, 1) == b'\x60')
ck('mc stub: mov ax,[ebp-4]', at(M + 6, 4) == bytes.fromhex('66 8b 45 fc'))
ck('mc stub: calls grant', call_target(M + 12) == G, '-> %08X' % call_target(M + 12))
ck('mc stub: jmp resume', jmp_target(M + 20) == 0x48D667, '-> %08X' % jmp_target(M + 20))

# mission sweep
L = 0x4158D8
ck('sweep: pushad', at(L, 1) == b'\x60')
ck('sweep: xor eax,eax', at(L + 1, 2) == bytes.fromhex('31 c0'))
ck('sweep: calls grant', call_target(L + 5) == G, '-> %08X' % call_target(L + 5))
ck('sweep: cmp eax,0x800', at(L + 13, 5) == bytes.fromhex('3d 00 08 00 00'))
ck('sweep: popad', at(L + 20, 1) == b'\x61')
ck('sweep: jmp 0x41FB5B', jmp_target(L + 21) == 0x41FB5B, '-> %08X' % jmp_target(L + 21))

# retargeted sites
ck('create_unit exit -> new stub', jmp_target(0x42CA7A) == N, '-> %08X' % jmp_target(0x42CA7A))
ck('mindcontrol site -> mc stub', jmp_target(0x48D662) == M, '-> %08X' % jmp_target(0x48D662))
ck('5b cave tail -> sweep', jmp_target(0x4158D3) == L, '-> %08X' % jmp_target(0x4158D3))

# earlier stages still intact
ck('stage10: spell costs all 1',
   all(cur[v2f(0x4B63E8) + i * 18 + 6] == 1 for i in range(20)))
ck('stage8: units-per-home',
   struct.unpack_from('<4H', cur, v2f(0x4B47E4)) == (0x7FFF,) * 4)
ck('stage5b: researched x4',
   at(0x4158AB, 40) == bytes.fromhex(
       'c70588415400ffffffff'
       'c70589425400ffffffff'
       'c7058a435400ffffffff'
       'c7058b445400ffffffff'))

print()
print('RESULT: %s' % ('ALL CHECKS PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
