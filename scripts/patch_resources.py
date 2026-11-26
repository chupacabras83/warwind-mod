"""War Wind permanent campaign-start patch (CORRECTED).

Fixes two problems in the previous patch:
  1. Resource value is now 99,999 (0x1869F) - matching the user's Cheat Engine
     table - instead of 9,999,999.
  2. The hook is now UNCONDITIONAL at campaign/clan init, instead of being
     gated behind the map-reveal flag (which only fired late in a mission).

How it works
------------
The campaign/clan init code loads the per-mission starting resources and stores
them to the player-slot globals:

  0041FB4F  8B 86 24 28 4B 00   mov eax,[esi+0x4B2824]   ; per-mission value
  0041FB55  8A 0D 63 26 4B 00   mov cl,[0x4B2663]        ; <-- HOOK here
  0041FB5B  A3 24 41 54 00      mov [0x544124],eax       ; resources
  0041FB60  A3 28 41 54 00      mov [0x544128],eax
  0041FB65  84 C9               test cl,cl

0x41FB55 is reached unconditionally (both the early-exit path and the loop path
converge at 0x41FB39 and fall through).  We replace it with a jump to a code
cave that:
  * forces the three cheat flags to 1  (production / recruit / map reveal)
  * sets EAX = 99,999
  * sets CL = 1 (so the map-reveal branch right below runs)
  * jumps back to 0x41FB5B, which stores EAX to the resource globals

Relocation handling
-------------------
The jump's rel32 lands on the PE relocation site at 0x41FB57 (the old
displacement of `mov cl,[0x4B2663]`).  We neutralise that relocation entry by
changing its type from IMAGE_REL_BASED_HIGHLOW (3) to IMAGE_REL_BASED_ABSOLUTE
(0), so the loader never rewrites our jump displacement.
"""
import struct
import sys
import hashlib

EXE_IN = sys.argv[1] if len(sys.argv) > 1 else 'WW.EXE.orig'
EXE_OUT = sys.argv[2] if len(sys.argv) > 2 else 'WW.EXE'
VALUE = int(sys.argv[3], 0) if len(sys.argv) > 3 else 99999

TEXT_VA = 0x410000
TEXT_FILE = 0x400
TEXT_RAWSIZE = 0x90C00
IMAGE_BASE = 0x400000

HOOK_VA = 0x41FB55
HOOK_ORIG = b'\x8A\x0D' + struct.pack('<I', 0x4B2663)   # mov cl,[0x4B2663]
HOOK_LEN = len(HOOK_ORIG)                                # 6

CAVE_VA = 0x415881
CAVE_LEN = 215

RESUME_VA = HOOK_VA + HOOK_LEN                          # 0x41FB5B

FLAGS = (0x4B2660, 0x4B2661, 0x4B266D)  # production, recruit, fog reveal
REVEAL_FN = 0x42A450                          # "sun also rises" reveal-all routine

# recruit timer: 0x455F20 returns 30 (fast) or 384 (normal) ticks per hero.
# Patch the fast value 30 -> 1 so heroes appear ~1/sec (1 tick each).
RECRUIT_SITE = 0x455F29
RECRUIT_ORIG = b'\xB8\x1E\x00\x00\x00'        # mov eax, 0x1E (30)
RECRUIT_NEW = b'\xB8\x01\x00\x00\x00'         # mov eax, 0x01 (1)


def foff(va, n=1):
    if not (TEXT_VA <= va and va + n <= TEXT_VA + TEXT_RAWSIZE):
        raise SystemExit('0x%08X(+%d) outside BEGTEXT' % (va, n))
    return TEXT_FILE + (va - TEXT_VA)


def build_cave(value):
    """Cave runs at 0x41FB55 (replacing `mov cl,[0x4B2663]`).

    Order matters: the reveal routine clobbers EAX, so we reload the resource
    value AFTER calling it.  `mov cl,[0x4B2663]` is replayed to preserve the
    original branch behaviour at 0x41FB65.
    """
    c = bytearray()
    for g in FLAGS:
        c += b'\xC6\x05' + struct.pack('<I', g) + b'\x01'   # mov byte [g],1
    c += b'\x8A\x0D' + struct.pack('<I', 0x4B2663)          # mov cl,[0x4B2663] (replay)
    rel = REVEAL_FN - (CAVE_VA + len(c) + 5)
    c += b'\xE8' + struct.pack('<i', rel)                   # call reveal-all
    c += b'\xB8' + struct.pack('<I', value)                 # mov eax,value (after call)
    rel = RESUME_VA - (CAVE_VA + len(c) + 5)
    c += b'\xE9' + struct.pack('<i', rel)                   # jmp RESUME_VA
    if len(c) > CAVE_LEN:
        raise SystemExit('cave %d > %d' % (len(c), CAVE_LEN))
    return bytes(c)


def neutralize_reloc(data, va):
    """Set the relocation entry for `va` to IMAGE_REL_BASED_ABSOLUTE (no-op)."""
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    opt = pe + 24
    secoff = opt + struct.unpack_from('<H', data, pe + 20)[0]
    reloc = None
    for i in range(nsec):
        o = secoff + i * 40
        name = data[o:o + 8].rstrip(b'\0')
        if name == b'.reloc':
            reloc = (struct.unpack_from('<I', data, o + 12)[0],      # vaddr
                     struct.unpack_from('<I', data, o + 20)[0],      # rawptr
                     struct.unpack_from('<I', data, o + 16)[0])      # rawsize
            break
    if not reloc:
        raise SystemExit('.reloc section not found')
    rva, rawptr, rawsize = reloc
    off = va - IMAGE_BASE                          # RVA of the site
    page = off & ~0xFFF
    entry_off = off & 0xFFF
    p = rawptr
    end = rawptr + rawsize
    while p < end:
        blockpage = struct.unpack_from('<I', data, p)[0]
        blocksize = struct.unpack_from('<I', data, p + 4)[0]
        if blocksize == 0:
            break
        if blockpage == page:
            for k in range(8, blocksize, 2):
                w = struct.unpack_from('<H', data, p + k)[0]
                typ = w >> 12
                eoff = w & 0xFFF
                if eoff == entry_off:
                    if typ != 3:
                        raise SystemExit('reloc entry at %08X has type %d' % (va, typ))
                    struct.pack_into('<H', data, p + k, eoff)  # type 0 = ABSOLUTE
                    print('  neutralised reloc entry for %08X' % va)
                    return True
        p += blocksize
    raise SystemExit('no relocation entry found for %08X' % va)


def main():
    data = bytearray(open(EXE_IN, 'rb').read())

    # verify hook site
    hoff = foff(HOOK_VA, HOOK_LEN)
    if bytes(data[hoff:hoff + HOOK_LEN]) != HOOK_ORIG:
        raise SystemExit('hook site mismatch at %08X: %s' %
                         (HOOK_VA, bytes(data[hoff:hoff + HOOK_LEN]).hex(' ')))

    # verify cave is empty
    coff = foff(CAVE_VA, CAVE_LEN)
    if any(data[coff:coff + CAVE_LEN]):
        raise SystemExit('cave at %08X is not empty' % CAVE_VA)

    neutralize_reloc(data, HOOK_VA + 2)   # 0x41FB57

    cave = build_cave(VALUE)
    data[coff:coff + CAVE_LEN] = cave + b'\x90' * (CAVE_LEN - len(cave))

    jmp = b'\xE9' + struct.pack('<i', CAVE_VA - (HOOK_VA + 5))
    data[hoff:hoff + HOOK_LEN] = jmp + b'\x90' * (HOOK_LEN - 5)

    # recruit timer: 30 ticks -> 1 tick (heroes every ~1 second)
    roff = foff(RECRUIT_SITE, 5)
    if bytes(data[roff:roff + 5]) != RECRUIT_ORIG:
        raise SystemExit('recruit site mismatch at %08X: %s' %
                         (RECRUIT_SITE, bytes(data[roff:roff + 5]).hex(' ')))
    data[roff:roff + 5] = RECRUIT_NEW

    out = bytes(data)
    open(EXE_OUT, 'wb').write(out)

    print('input  %s' % EXE_IN)
    print('output %s' % EXE_OUT)
    print('       sha256 %s' % hashlib.sha256(out).hexdigest())
    print()
    print('hook @%08X -> jmp %08X   (resume %08X)' % (HOOK_VA, CAVE_VA, RESUME_VA))
    print('cave %d bytes:' % len(cave))
    print('  %s' % cave.hex(' '))
    print()
    print('resources = %d (0x%08X)' % (VALUE, VALUE))
    print('flags set = %s' % ', '.join('0x%X' % g for g in FLAGS))
    print('  (0x4B2660 production, 0x4B2661 recruit, 0x4B266D fog reveal)')
    print('reveal call = 0x%X (clear fog of war)' % REVEAL_FN)
    print('recruit timer @%08X: %s -> %s  (30 ticks -> 1 tick)' %
          (RECRUIT_SITE, RECRUIT_ORIG.hex(' '), RECRUIT_NEW.hex(' ')))


if __name__ == '__main__':
    main()
