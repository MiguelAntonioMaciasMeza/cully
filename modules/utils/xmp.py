"""
File: Cully/modules/utils/xmp.py
Description: Writes star ratings the way darktable and Lightroom read them: sidecar .xmp files for RAW
photos, and an XMP block inside JPEGs. Only used on exported copies, never on originals.
Author: Miguel Macias
Date: 2026-11-21
"""

import os
import re
import shutil
import struct
from pathlib import Path

JPEG_SUFFIXES = {".jpg", ".jpeg"}
XMP_ID = b"http://ns.adobe.com/xap/1.0/\x00"  # marks the XMP block inside a JPEG
CULLY_NS = "http://cully.local/ns/1.0/"  # marks sidecars Cully wrote, so it can replace them later


def packet(rating: int) -> str:
    """Returns back a minimal XMP packet with the rating (-1 = rejected)"""
    return f'''<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:cully="{CULLY_NS}"
    xmp:Rating="{rating}"
    cully:written="1"/>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
'''


def sidecar_names(photo: Path) -> list[Path]:
    """Returns back the sidecar names: IMG_1.xmp (Lightroom) and IMG_1.CR2.xmp (darktable).
    JPEGs only get IMG_1.JPG.xmp, Lightroom ignores JPEG sidecars and IMG_1.xmp may belong to the RAW"""
    darktable = photo.with_name(photo.name + ".xmp")
    if photo.suffix.lower() in JPEG_SUFFIXES:
        return [darktable]
    return [photo.with_suffix(".xmp"), darktable]


def _replace(path: Path, data: bytes) -> None:
    """Writes data to path through a temp file, so a crash never leaves half a file"""
    partial = path.with_name(f".{path.name}.part")
    partial.write_bytes(data)
    if path.exists():
        shutil.copystat(path, partial)
    os.replace(partial, path)


def write_sidecars(photo: Path, rating: int) -> bool:
    """Writes the rating to photo's sidecars. Returns back False if one exists that Cully didn't write"""
    sidecars = sidecar_names(photo)
    #An editor's own sidecar holds its edit history, never overwrite it
    if any(s.exists() and CULLY_NS not in s.read_text(errors="replace") for s in sidecars):
        return False
    for sidecar in sidecars:
        _replace(sidecar, packet(rating).encode())
    return True


def remove_sidecars(photo: Path) -> bool:
    """Deletes photo's sidecars that Cully wrote. Returns back True if any were deleted"""
    removed = False
    for sidecar in sidecar_names(photo):
        if sidecar.exists() and CULLY_NS in sidecar.read_text(errors="replace"):
            sidecar.unlink()
            removed = True
    return removed


def _segments(data: bytes):
    """Yields (start, end) of each APPn segment at the start of a JPEG"""
    pos = 2
    while pos + 4 <= len(data) and data[pos] == 0xFF and 0xE0 <= data[pos + 1] <= 0xEF:
        end = pos + 2 + struct.unpack(">H", data[pos + 2:pos + 4])[0]
        yield pos, end
        pos = end


def _set_rating(xmp: str, rating: int) -> str | None:
    """Returns back another app's XMP packet with its rating set, everything else kept. None if it can't tell how"""
    #<xmp:Rating>3</xmp:Rating> or xmp:Rating="3"
    for pattern, new in ((r"<xmp:Rating>[^<]*</xmp:Rating>", f"<xmp:Rating>{rating}</xmp:Rating>"),
                         (r'xmp:Rating="[^"]*"', f'xmp:Rating="{rating}"')):
        if re.search(pattern, xmp):
            return re.sub(pattern, new, xmp, count=1)
    #No rating yet: add it to the first description, declaring the xmp prefix if needed
    match = re.search(r"<rdf:Description\b", xmp)
    if match is None:
        return None
    added = f' xmp:Rating="{rating}"'
    if 'xmlns:xmp="' not in xmp:
        added = f' xmlns:xmp="http://ns.adobe.com/xap/1.0/"{added}'
    return xmp[:match.end()] + added + xmp[match.end():]


def embed_rating(photo: Path, rating: int) -> bool:
    """Puts the rating inside a JPEG. If it already has XMP (from Lightroom, a camera, or an earlier
    export) only the rating in it changes. Returns back False if it can't"""
    data = photo.read_bytes()
    if data[:2] != b"\xff\xd8":
        return False
    insert_at = 2
    xmp = packet(rating)
    for start, end in _segments(data):
        if data[start + 4:start + 4 + len(XMP_ID)] == XMP_ID:
            xmp = _set_rating(data[start + 4 + len(XMP_ID):end].decode("utf-8", errors="replace"), rating)
            if xmp is None:
                return False
            #The old block comes out, the updated one goes in its place
            data = data[:start] + data[end:]
            insert_at = start
            break
        #After APP0 (JFIF) and APP1 (Exif), where editors expect it
        if data[start + 1] in (0xE0, 0xE1):
            insert_at = end
    body = XMP_ID + xmp.encode()
    if len(body) + 2 > 0xFFFF:  # one JPEG segment can't hold more
        return False
    segment = b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body
    _replace(photo, data[:insert_at] + segment + data[insert_at:])
    return True


def write_rating(photo: Path, rating: int) -> bool:
    """Writes the rating where the editors look for it: inside JPEGs, in sidecars for everything else"""
    if photo.suffix.lower() in JPEG_SUFFIXES:
        return embed_rating(photo, rating)
    return write_sidecars(photo, rating)
