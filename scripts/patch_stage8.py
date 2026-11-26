"""War Wind patch, stage 8: remove the homes/manor population cap.

The game's "units per home" table lives at 0x4B47E4 as one WORD per race:
    [4, 3, 4, 5]  =  Tha'roon, Obblinox, Eaggra, Shama Li
i.e. "you must have 1 home for every N units". Raising N to a huge value means
the required-home count becomes ~0, effectively removing the population cap.

This is a pure data write (4 words), no code change.

Applied ON TOP of WW.EXE.stage7 (tech tree + spell menu + build speed).
"""
import hashlib
import struct
import sys

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage7'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage8'

UNITS_PER_HOME_VA = 0x4B47E4   # WORD[4] = [4,3,4,5]
NEW_VALUE = 0x7FFF             # ~32767 units per home

def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    fo = 0x91000 + (UNITS_PER_HOME_VA - 0x4B0000)   # DGROUP file offset
    old = struct.unpack_from('<4H', data, fo)
    print('old units-per-home:', old)
    for k in range(4):
        struct.pack_into('<H', data, fo + 2 * k, NEW_VALUE)
    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('units-per-home @0x%X -> [%d,%d,%d,%d]' % (UNITS_PER_HOME_VA, NEW_VALUE, NEW_VALUE, NEW_VALUE, NEW_VALUE))

if __name__ == '__main__':
    main()
