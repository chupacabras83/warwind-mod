"""Verify a WW.EXE build contains every expected patch."""
import struct
import sys

path = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage10b'
cur = open(path, 'rb').read()


def fb(va):
    return 0x400 + (va - 0x410000)


def dg(va):
    return 0x91000 + (va - 0x4B0000)


def tgt(site):
    d = struct.unpack_from('<i', cur, fb(site) + 1)[0]
    return site + 5 + d


fails = []


def check(name, cond, extra=''):
    print('  %-46s %s %s' % (name, 'OK' if cond else 'FAIL', extra))
    if not cond:
        fails.append(name)


print('=== %s ===' % path)
print('  size %d' % len(cur))
pe = struct.unpack_from('<I', cur, 0x3C)[0]
check('PE signature', cur[pe:pe + 4] == b'PE\0\0')

# stage 5b: researched = -1 for 4 clans (the tail jmp is later re-pointed by
# stage 11's mission sweep, so only the four 10-byte data writes are checked)
expect5b = bytes.fromhex(
    'c70588415400ffffffff c70589425400ffffffff '
    'c7058a435400ffffffff c7058b445400ffffffff')
check('tech tree (all researched x4)', cur[fb(0x4158AB):fb(0x4158AB) + 40] == expect5b)

# stage 6: spell-menu loop redirects
check('spell menu loop redirect x2',
      cur[fb(0x45596F)] == 0xE9 and cur[fb(0x455A09)] == 0xE9)

# stage 9: build/repair calls -> filter, heal calls -> heal stub
check('build call -> filter', tgt(0x42EC0A) == 0x415925, '-> %08X' % tgt(0x42EC0A))
check('build call 2 -> filter', tgt(0x42F077) == 0x415925, '-> %08X' % tgt(0x42F077))
check('vehicle call -> fB', tgt(0x42F104) == 0x41592C, '-> %08X' % tgt(0x42F104))
check('vehicle call 2 -> fB', tgt(0x43002D) == 0x41592C, '-> %08X' % tgt(0x43002D))
check('treatment A -> heal', tgt(0x43982F) == 0x4A0BC0, '-> %08X' % tgt(0x43982F))
check('filter: push ecx/push edi prologue',
      cur[fb(0x415931):fb(0x415933)] == bytes.fromhex('51 57'))
check('filter: pop edi/pop ecx/ret epilogue',
      cur[fb(0x415951):fb(0x415954)] == bytes.fromhex('5f 59 c3'))
check('filter: mov edx,0x7FFF', cur[fb(0x41594C):fb(0x415951)] == bytes.fromhex('ba ff 7f 00 00'))
check('heal stub: pop ecx/pop eax/ret',
      cur[fb(0x4A0BE4):fb(0x4A0BE7)] == bytes.fromhex('59 58 c3'))

# stage 10: all spell costs == 1
costs = [cur[dg(0x4B63E8) + i * 18 + 6] for i in range(20)]
check('all 20 spell costs = 1', all(c == 1 for c in costs), str(costs))

# stage 8: population cap removed
uph = struct.unpack_from('<4H', cur, dg(0x4B47E4))
check('units-per-home raised', uph == (0x7FFF,) * 4, str(uph))

print()
print('RESULT: %s' % ('ALL CHECKS PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
