"""Membuat sidik jari blok (ljk/ref/*.png) dari lembar acuan yang sudah dipastikan pas.

Pakai:
    python tools/build_reference.py FOTO1.jpg [FOTO2.jpg ...]

Pastikan dulu (lihat gambar hasil pelurusan) bahwa lingkaran template jatuh
tepat di bulatan pada setiap foto acuan. Sidik jari = rata-rata pola tinta
merah tiap blok dari semua foto acuan.
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ljk import align as AL  # noqa: E402
from ljk import template as T  # noqa: E402


def block_aligned_redness(a, name):
    """Peta merah dari foto acuan, dilengkungkan supaya bulatan blok tepat di posisi template."""
    fixed = a.block_map[name].remap(a.canon)
    return AL.ref_redness(fixed).astype(np.float32)


def main(paths):
    # Paksa pelurusan tanpa acuan lama.
    for name in AL.BLOCK_NAMES:
        AL._REF_CACHE[name] = None
    acc = {name: [] for name in AL.BLOCK_NAMES}
    for p in paths:
        a = AL.align(AL.load_image(p))
        print(Path(p).name, "catatan:", a.notes or "-")
        for k, name in enumerate(AL.BLOCK_NAMES):
            x0, y0, x1, y1 = AL.block_bbox(k)
            red = block_aligned_redness(a, name)
            acc[name].append(red[y0 + T.PAD: y1 + T.PAD, x0 + T.PAD: x1 + T.PAD])
    AL.REF_DIR.mkdir(exist_ok=True)
    for name, patches in acc.items():
        ref = np.mean(patches, axis=0)
        out = AL.REF_DIR / f"{AL.block_slug(name)}.png"
        cv2.imwrite(str(out), np.clip(ref, 0, 255).astype(np.uint8))
        print("tersimpan:", out, ref.shape)
    AL._REF_CACHE.clear()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1:])
