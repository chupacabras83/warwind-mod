"""Verify that ALL mod code is physically present inside the loaded .wwmod range."""
import struct
import sys

path = sys.argv[1] if len(sys.argv) > 1 else \
    r'E:\Users\Ninja hp LAPTOP\Documents\deepseek-harness\default-workspace\warwind-patch\patched\WW.EXE.stage14'
cur = open(path, 'rb').read()

pe = struct.unpack_from('<I', cur, 0x3C)[0]
nsec = struct.unpack_from('<H', cur, pe + 6)[0]
opt = pe + 24
secoff = opt + struct.unpack_from('<H', cur, pe + 20)[0]
imagebase = struct.unpack_from('<I', cur, opt + 28)[0]

SEC = {}
for i in range(nsec):
    o = secoff + i * 40
    name = cur[o:o + 8].rstrip(b'\0').decode()
    vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', cur, o + 8)
    SEC[name] = (vsize, vaddr, rawsize, rawptr, o)

fails = []


def ck(name, cond, extra=''):
    print('  %-52s %s %s' % (name, 'OK' if cond else 'FAIL', extra))
    if not cond:
        fails.append(name)


vsize, vaddr, rawsize, rawptr, woff = SEC['.wwmod']
print('=== %s ===' % path)
print('  file size 0x%X' % len(cur))
print('  .wwmod vsize=0x%X vaddr=0x%X rawsize=0x%X rawptr=0x%X' %
      (vsize, vaddr, rawsize, rawptr))
print('  loaded VA range: 0x%X .. 0x%X' %
      (imagebase + vaddr, imagebase + vaddr + rawsize))
print('  SizeOfImage matches: %s' %
      (struct.unpack_from('<I', cur, opt + 56)[0] >= vaddr + vsize))


def va_bytes(va, n):
    """Read n bytes at va, but ONLY if inside the section's RawSize."""
    rva = va - imagebase
    if not (vaddr <= rva < vaddr + rawsize):
        return None
    off = rawptr + (rva - vaddr)
    if off + n > rawptr + rawsize or off + n > len(cur):
        return None
    return cur[off:off + n]


def is_loaded(va, n):
    return va_bytes(va, n) is not None


# every mod code block must be inside the raw range
blocks = [(0x650000, 0x60, 'stage6 spell cave 1'),
          (0x650020, 0x60, 'stage6 spell cave 2'),
          (0x650100, 0xE5, 'stage11 grant + hooks'),
          (0x650300, 0xDE, 'stage12 grant'),
          (0x650500, 0xDE, 'stage13 grant'),
          (0x650800, 0x47, 'stage14 damage stub')]
for va, n, what in blocks:
    ck('%s loaded (0x%X, %d B)' % (what, va, n), is_loaded(va, n))
    b = va_bytes(va, min(n, 8))
    ck('  %s non-zero' % what, b is not None and any(b))

# the entry hook
ck('0x45AA4C is a jmp', cur[0x400 + (0x45AA4C - 0x410000)] == 0xE9)
d = struct.unpack_from('<i', cur, 0x400 + (0x45AA4C - 0x410000) + 1)[0]
tgt = 0x45AA4C + 5 + d
ck('0x45AA4C -> 0x650800', tgt == 0x650800, hex(tgt))

# stub stack balance: 4 pushes, 4 pops, then jmp
stub = va_bytes(0x650800, 0x47)
ck('stub present', stub is not None)
if stub:
    ck('stub: relocated prologue 565755 83ec1c',
       stub[0:6] == bytes.fromhex('56 57 55 83 ec 1c'))
    ck('stub: pushes eax/ecx/edx/ebx',
       stub[6:10] == bytes.fromhex('50 51 52 53'))
    ck('stub: pops ebx/edx/ecx/eax',
       bytes.fromhex('5b 5a 59 58') in stub)
    ck('stub: jmp back to 0x45AA52', stub[-5] == 0xE9)
    if stub[-5] == 0xE9:
        d2 = struct.unpack_from('<i', stub, len(stub) - 4)[0]
        back = 0x650800 + len(stub) - 5 + 5 + d2
        ck('  resume target == 0x45AA52', back == 0x45AA52, hex(back))

def raw_bytes(va, n):
    """Read n bytes at va from any section's raw data (None if not mapped)."""
    rva = va - imagebase
    for name, (vsize, vaddr, rawsize, rawptr, o) in SEC.items():
        if rawsize and vaddr <= rva < vaddr + rawsize:
            off = rawptr + (rva - vaddr)
            if off + n <= len(cur):
                return cur[off:off + n]
    return None


# call sites still point at live grants
def call_tgt(va):
    b = raw_bytes(va, 5)
    if b is None or b[0] != 0xE8:
        return None
    return va + 5 + struct.unpack_from('<i', b, 1)[0]


def show(t):
    return 'none' if t is None else '0x%X' % t


GRANT_VA = 0x650B00

ck('sweep calls grant', call_tgt(0x4158DD) == GRANT_VA, show(call_tgt(0x4158DD)))
ck('new-unit stub calls grant', call_tgt(0x6501BF) == GRANT_VA,
   show(call_tgt(0x6501BF)))
ck('mc stub calls grant', call_tgt(0x6501D8) == GRANT_VA,
   show(call_tgt(0x6501D8)))

print()
print('RESULT: %s' % ('ALL CHECKS PASS' if not fails else 'FAILED: ' + ', '.join(fails)))
sys.exit(1 if fails else 0)
