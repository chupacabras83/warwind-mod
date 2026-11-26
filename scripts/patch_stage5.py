"""War Wind patch, stage 5: unlock the whole tech tree from game start.

Applied ON TOP of patch_stage3.py output (WW.EXE.stage3).

The game already contains a "sandbox / everything-unlocked" shortcut gated by
two flags ([0x4B2672] != 0 AND [0x542530] & 1). When set, several checks are
bypassed. This patch rewrites each of those 4 gate sites so the unlocked path is
ALWAYS taken, regardless of the flags:

  0x4138C0  cmp [0x4B2672],0x0  ->  jmp +0x12  (availability check -> return 1)
  0x41458D  cmp [0x4B2672],0x0  ->  jmp +0x12  (availability check -> return 1)
  0x4182A7  cmp [0x4B2672],0x0  ->  jmp 0x4183C6 (skip house/population logic)
  0x42CF76  cmp [0x4B2672],0x0  ->  jmp 0x42D233 (skip build-prerequisite check)

Effects: all researches available/done, all upgrades available, no home/manor
population gate, full building menu (any builder can build anything from start).
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import no_reloc, put_text, relocs, tfoff
from patch_resources import neutralize_reloc

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage3'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage5'

CMP = bytes.fromhex('80 3d 72 26 4b 00 00')  # cmp [0x4B2672],0x0

# (VA, replacement bytes)
PATCHES = [
    (0x4138C0, bytes.fromhex('eb 10 90 90 90 90 90')),  # jmp +0x10 -> mov eax,1
    (0x41458D, bytes.fromhex('eb 10 90 90 90 90 90')),
    (0x4182A7, bytes.fromhex('e9 1a 01 00 00 90 90')),  # jmp 0x4183C6
    (0x42CF76, bytes.fromhex('e9 b8 02 00 00 90 90')),  # jmp 0x42D233
]


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    rel = relocs(bytes(data))

    for va, new in PATCHES:
        o = tfoff(va)
        old = bytes(data[o:o + 7])
        if old != CMP:
            raise SystemExit('0x%08X: unexpected bytes %s' % (va, old.hex(' ')))
        neutralize_reloc(data, va + 2)   # the [0x4B2672] displacement is a reloc site
        put_text(data, va, new)

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('patched %d tech-tree gate sites' % len(PATCHES))


if __name__ == '__main__':
    main()
