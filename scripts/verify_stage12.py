"""Byte-level verification for stage 12."""
import struct
import sys

path = sys.argv[1] if len(sys.argv) > 1 else \
    r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch\patched\WW.EXE.stage12'
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


fails = []


def ck(name, cond, extra=''):
    print('  %-46s %s %s' % (name, 'OK' if cond else 'FAIL', extra))
    if not cond:
        fails.append(name)


print('=== stage12 verification: %s ===' % path)

G = 0x650400
code = at(G, 222)
print('  grant size 222 bytes, sha %s' % __import__('hashlib').sha256(code).hexdigest()[:16])
ck('grant: pushad', code[0:1] == b'\x60')
ck('grant: cmp cat,2', bytes.fromhex('80 be a1 44 50 00 02') in code)
ck('grant: cmp clan', bytes.fromhex('3a 05 2c 34 4b 00') in code)
ck('grant: add edi,UDATA', bytes.fromhex('81 c7 a0 a7 4e 00') in code)
ck('grant: all 5 upgrade bits',
   all(bytes.fromhex('80 4f 23 %02x' % b) in code for b in (1, 2, 4, 8, 0x10)))
ck('grant: max speed 0x14 (20)', bytes.fromhex('c6 47 1d 14') in code)
ck('grant: max armour 0x28 (40)', bytes.fromhex('c6 47 1b 28') in code)
ck('grant: max melee 0x28 (40)', bytes.fromhex('c6 47 1a 28') in code)
ck('grant: max vision 0x1e (30)', bytes.fromhex('c6 47 1c 1e') in code)
ck('grant: spell mask 0xFF', bytes.fromhex('c6 47 27 ff') in code)
ck('grant: full mana', bytes.fromhex('88 57 12') in code)
ck('grant: HP floor 150 compare', bytes.fromhex('81 fa 96 00 00 00') in code)
ck('grant: HP floor 150 write', bytes.fromhex('ba 96 00 00 00') in code)
ck('grant: leader class check (cmp 1)', bytes.fromhex('80 b9 38 3c 4b 00 01') in code)
ck('grant: HP store word', bytes.fromhex('66 89 57 10') in code)
ck('grant: popad/ret', code[-2:] == b'\x61\xc3')

# call sites all point at the new grant
ck('sweep calls new grant', call_target(0x4158DD) == G, '-> %08X' % call_target(0x4158DD))
ck('new-unit stub calls new grant', call_target(0x6501BF) == G, '-> %08X' % call_target(0x6501BF))
ck('mindcontrol stub calls new grant', call_target(0x6501D8) == G, '-> %08X' % call_target(0x6501D8))

# stage 11 hooks still intact
def jmp_target(site):
    d = struct.unpack_from('<i', at(site + 1, 4), 0)[0]
    return site + 5 + d

ck('create_unit exit -> stub', jmp_target(0x42CA7A) == 0x6501B4)
ck('mindcontrol site -> stub', jmp_target(0x48D662) == 0x6501CC)
ck('5b cave tail -> sweep', jmp_target(0x4158D3) == 0x4158D8)

# earlier stages
ck('spell costs all 1',
   all(cur[v2f(0x4B63E8) + i * 18 + 6] == 1 for i in range(20)))
ck('units-per-home',
   struct.unpack_from('<4H', cur, v2f(0x4B47E4)) == (0x7FFF,) * 4)
ck('researched x4', at(0x4158AB, 40) == bytes.fromhex(
   'c70588415400ffffffffc70589425400ffffffffc7058a435400ffffffffc7058b445400ffffffff'))

print()
print('RESULT: %s' % ('ALL CHECKS PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
