"""War Wind patch: remove the "Operation under Windows NT is not supported." prompt.

The game calls GetVersion at 0x4153AD and, when the major version reports NT
(2), pops a modal warning before continuing. On Windows 11 this always fires.

Code:
  004153B4  85 C0           test eax,eax
  004153B6  74 15           je   0x4153CD
  004153B8  83 7D D6 02     cmp  [ebp-42],2
  004153BC  75 0F           jne  0x4153CD
  004153BE  68 CC 02 4B 00  push 0x4B02CC     ; the message string
  004153C3  6A 01           push 1
  004153C5  E8 52 B1 FF FF  call 0x41051C     ; show the warning
  004153CA  83 C4 08        add  esp,8

Fix: replace the `jne` at 0x4153BC with an unconditional `jmp`, so the warning
block is always skipped. Everything else (including the GetVersion call and the
rest of the init sequence) is untouched, so no other behaviour changes.

The whole 13-byte block 0x4153B8..0x4153CA is rewritten to keep lengths exact:
   EB 13            jmp 0x4153CD
   90 x 11          nop padding
"""
import hashlib
import struct
import sys

sys.path.insert(0, r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch')
from patch_godmode import put_text, relocs, no_reloc
from patch_resources import neutralize_reloc

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else r'E:\GAMES\GOG\War Wind\WW.EXE'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else EXE_IN

SITE = 0x4153B8
SKIP = 0x4153CD
# exact original bytes 0x4153B8..0x4153CA (18 bytes, ending with `add esp,8`)
ORIG = bytes.fromhex('837dd602750f68cc024b006a01e852b1ffff83c408')
NEW = bytes([0xEB, SKIP - (SITE + 2)]) + b'\x90' * (len(ORIG) - 2)
assert len(NEW) == len(ORIG)


def main():
    data = bytearray(open(EXE_IN, 'rb').read())
    rel = relocs(data)
    # the embedded string address at 0x4153BF has a HIGHLOW reloc; free it first,
    # then re-read the reloc list (the cached set still contains the old entry).
    neutralize_reloc(data, 0x4153BF)
    rel = relocs(data)
    no_reloc(rel, SITE, len(ORIG))
    put_text(data, SITE, NEW, expect=ORIG)
    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)
    print('%s -> %s' % (EXE_IN, EXE_OUT))
    print('  sha256 %s' % hashlib.sha256(out).hexdigest())
    print('  NT warning skipped: jmp 0x%X at 0x%X (%d bytes)' % (SKIP, SITE, len(NEW)))


if __name__ == '__main__':
    main()
