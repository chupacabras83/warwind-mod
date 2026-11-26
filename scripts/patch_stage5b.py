"""War Wind patch, stage 5b: unlock tech tree by marking all research complete.

Applied ON TOP of WW.EXE.stage1 (my original patch, NO god-mode).

The game's own "grant everything" routine sets the clan's researched dword
(0x544188 + clan*257) to -1. This patch does the same for all 4 clans at
mission start, by appending a few instructions after the stage-1 cave and
redirecting the cave's final jump through them.

This does NOT touch any per-frame "skip work" switch, so it cannot cause the
black-screen bug that the earlier stage-5 shortcut approach did.
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import put_text, tfoff
from patch_resources import neutralize_reloc

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'patched\WW.EXE.stage1'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else r'patched\WW.EXE.stage5b'

CAVE_JMP = 0x4158A6   # stage-1 cave's final `jmp 0x41FB5B`
NEW_CODE = 0x4158AB   # free zero padding right after the stage-1 cave
RESUME = 0x41FB5B

RESEARCH_BASE = 0x544188  # researched dword, stride 257 per clan


def build_code():
    c = bytearray()
    for k in range(4):
        addr = RESEARCH_BASE + 257 * k
        c += b'\xc7\x05' + struct.pack('<I', addr) + b'\xff\xff\xff\xff'
    c += b'\xe9' + struct.pack('<i', RESUME - (NEW_CODE + len(c) + 5))
    return bytes(c)


def main():
    data = bytearray(open(EXE_IN, 'rb').read())

    # redirect the stage-1 cave's final jump through our code
    put_text(data, CAVE_JMP, b'\xe9\x00\x00\x00\x00', expect=b'\xe9' + struct.pack('<i', RESUME - (CAVE_JMP + 5)))

    code = build_code()
    put_text(data, NEW_CODE, code, expect_fill=(0x90,))

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('input  %s\noutput %s\n  sha256 %s' % (EXE_IN, EXE_OUT, hashlib.sha256(out).hexdigest()))
    print('researched-dword base 0x%X, 4 clans, code @0x%X (%d bytes)' % (RESEARCH_BASE, NEW_CODE, len(code)))


if __name__ == '__main__':
    main()
