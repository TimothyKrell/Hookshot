"""Find textures in a romfs that a bad dump left unreadable, and (with --fix) give each a stand-in in a mod folder.

    python -I scripts/check_romfs.py <game folder or romfs> [--fix]

Why: a texture whose file the dumper could not read whole (seen: the first 12 KB of the compressed file zeroed) never loads. The
game's resource loader does not give up: it opens and decompresses the file and the model that uses it again, ~11 times a second
for as long as the scene is up (one decompression thread at 60% of a core in Link's house, for a Fairy Fountain floor texture).

--fix writes, for each bad texture, a copy of a texture of the same kind into <game>/mods/00-dump-fixes/romfs/Tex, under the bad
one's name (renamed inside: the donor's name must have the same length). The donor must fit the size the game's resource size
table allows for the bad one, or the load fails all the same: it is chosen with the same allowance and the closest name.
Nothing is copied out of the game folder; the stand-ins are made from the player's own files. Re-dumping the game is the real fix.
"""
import argparse
import difflib
import glob
import os
import struct
import sys
import zlib

try:
    import zstandard
except ImportError:
    sys.exit("needs the zstandard module (the builder's Python has it)")


def romfs_of(path):
    return path if os.path.isdir(os.path.join(path, "Tex")) else os.path.join(path, "romfs")


def size_table(romfs):
    """crc32 of the resource's path (without .zs) -> the size the game allows it"""
    p = sorted(glob.glob(os.path.join(romfs, "System", "Resource", "ResourceSizeTable*.rsizetable.zs")))
    if not p:
        return {}
    d = zstandard.ZstdDecompressor().decompressobj().decompress(open(p[-1], "rb").read())
    if d[:6] != b"RESTBL":
        return {}
    ncrc = struct.unpack_from("<I", d, 14)[0]
    return {struct.unpack_from("<I", d, 22 + 8 * i)[0]: struct.unpack_from("<I", d, 26 + 8 * i)[0] for i in range(ncrc)}


def bad_textures(tex):
    dc = zstandard.ZstdDecompressor()
    bad = []
    for f in sorted(os.listdir(tex)):
        if not f.endswith(".bntx.zs"):
            continue
        data = open(os.path.join(tex, f), "rb").read()
        try:
            if zstandard.get_frame_parameters(data).dict_id:
                continue   # (made with one of the game's dictionaries: not checked here)
            if dc.decompressobj().decompress(data)[:4] != b"BNTX":
                bad.append(f[:-len(".bntx.zs")])
        except zstandard.ZstdError:
            bad.append(f[:-len(".bntx.zs")])
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()
    romfs = romfs_of(a.game)
    tex = os.path.join(romfs, "Tex")
    if not os.path.isdir(tex):
        sys.exit("no romfs/Tex in %s" % a.game)
    bad = bad_textures(tex)
    print("%d unreadable texture%s" % (len(bad), "" if len(bad) == 1 else "s"))
    for b in bad:
        print("  " + b)
    if not bad or not a.fix:
        return 1 if bad else 0
    table = size_table(romfs)
    allow = lambda name: table.get(zlib.crc32(("Tex/%s.bntx" % name).encode()))
    names = [f[:-len(".bntx.zs")] for f in os.listdir(tex) if f.endswith(".bntx.zs")]
    out = os.path.join(romfs, "..", "mods", "00-dump-fixes", "romfs", "Tex")
    os.makedirs(out, exist_ok=True)
    dc = zstandard.ZstdDecompressor()
    bad_set = set(bad)
    for b in bad:
        kind = b.rsplit("_", 1)[-1]   # (Nrm, Alb, Rgh, t0 ...: a donor of the same kind)
        want = allow(b)
        pool = [n for n in names if n not in bad_set and len(n) == len(b) and n.rsplit("_", 1)[-1] == kind and
                (want is None or allow(n) == want)]
        if not pool and want is not None:   # (none with the same allowance: any that fits in it)
            pool = [n for n in names if n not in bad_set and len(n) == len(b) and n.rsplit("_", 1)[-1] == kind and
                    allow(n) is not None and allow(n) <= want]
        if not pool:
            print("  %s: no donor of the same kind and name length" % b)
            continue
        donor = max(pool, key=lambda n: difflib.SequenceMatcher(None, n, b).ratio())
        data = dc.decompressobj().decompress(open(os.path.join(tex, donor + ".bntx.zs"), "rb").read())
        data = data.replace(donor.encode(), b.encode())
        with open(os.path.join(out, b + ".bntx.zs"), "wb") as f:
            f.write(zstandard.ZstdCompressor(level=19).compress(data))
        print("  %s <- %s (allowance %s)" % (b, donor, want))
    print("stand-ins in %s" % os.path.normpath(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
