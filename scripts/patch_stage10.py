"""War Wind patch, stage 10: every spell costs 1 mana.

The spell table lives at VA 0x4B63E8, 20 entries of 18 bytes:
    +4 flag, +6 COST (byte), +10 handler
The mana gate at 0x455631 does `cmp dl,[cost] ; jb not-enough-mana`, so the
cost byte IS the mana price. Overwriting all 20 cost bytes with 1 makes every
spell cost a single mana point, with no code change at all.

Applied ON TOP of WW.EXE.stage9.
"""
import hashlib
import struct
import sys

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage9'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage10'

SPELL_TABLE_VA = 0x4B63E8
ENTRY = 18
COST_OFF = 6
NSPELLS = 20
NEW_COST = 1


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    fo0 = 0x91000 + (SPELL_TABLE_VA - 0x4B0000)
    old = [data[fo0 + i * ENTRY + COST_OFF] for i in range(NSPELLS)]
    print('old spell costs:', old)
    for i in range(NSPELLS):
        data[fo0 + i * ENTRY + COST_OFF] = NEW_COST
    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('%d spell costs -> %d' % (NSPELLS, NEW_COST))


if __name__ == '__main__':
    main()
