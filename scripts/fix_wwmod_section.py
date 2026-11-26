"""Repair the .wwmod section header so the mod code is actually loaded.

stage 6 added a `.wwmod` section with:
    VirtualSize = 0x1000   (fine)
    RawSize     = 0x400    (TOO SMALL)
Later stages wrote code up to VA 0x650x9xx, i.e. beyond RawSize. Windows
loads only RawSize bytes from the file and ZERO-FILLS the rest of the virtual
range, so every call into that code hit zeroed memory (or stray bytes that
happened to follow the file's last section) -> crash / silent no-op.

Fix: set RawSize to the real size of the code in the file, and pad the file
so the section's raw data is fully present and page-aligned.
"""
import hashlib
import struct
import sys

path = sys.argv[1]
data = bytearray(open(path, 'rb').read())

pe = struct.unpack_from('<I', data, 0x3C)[0]
nsec = struct.unpack_from('<H', data, pe + 6)[0]
opt = pe + 24
secoff = opt + struct.unpack_from('<H', data, pe + 20)[0]
imagebase = struct.unpack_from('<I', data, opt + 28)[0]
sizeimage_off = opt + 56

for i in range(nsec):
    o = secoff + i * 40
    name = bytes(data[o:o + 8]).rstrip(b'\0').decode()
    if name != '.wwmod':
        continue
    vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', data, o + 8)
    print('.wwmod before: vsize=0x%X vaddr=0x%X rawsize=0x%X rawptr=0x%X'
          % (vsize, vaddr, rawsize, rawptr))

    # real end of the section's raw data = end of file (nothing follows it)
    real_end = len(data)
    real_raw = real_end - rawptr
    # round up to 0x200 (file alignment used by this exe)
    real_raw = (real_raw + 0x1FF) & ~0x1FF
    if real_raw > vsize:
        # grow VirtualSize too so the mapping covers everything
        vsize = (real_raw + 0xFFF) & ~0xFFF

    # pad the file out to the new raw size
    need = rawptr + real_raw
    if len(data) < need:
        data += b'\x00' * (need - len(data))

    struct.pack_into('<I', data, o + 8, vsize)    # VirtualSize
    struct.pack_into('<I', data, o + 16, real_raw)  # SizeOfRawData
    print('.wwmod after : vsize=0x%X rawsize=0x%X' % (vsize, real_raw))

    # keep SizeOfImage covering the (possibly larger) section
    sizeimage = struct.unpack_from('<I', data, sizeimage_off)[0]
    need_img = vaddr + vsize
    if sizeimage < need_img:
        struct.pack_into('<I', data, sizeimage_off, (need_img + 0xFFF) & ~0xFFF)
        print('SizeOfImage 0x%X -> 0x%X' % (sizeimage, need_img))
    break
else:
    raise SystemExit('no .wwmod section found')

out = bytes(data)
open(path, 'wb').write(out)
print('file size now %d, sha256 %s' % (len(out), hashlib.sha256(out).hexdigest()))
