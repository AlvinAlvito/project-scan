"""Latih model bulatan "juri kedua" dari label panitia (pakai lingkungan PyTorch .venv-latih).

    .venv-latih\\Scripts\\python.exe tools\\latih_bulatan.py [--data FOLDER_DATA] [--epoch 15]

Bahan: <data>/ljk.db (tabel label_bulatan + lembar "Sudah dicek") dan gambar baca tiap lembar
(<data>/event/<id>/<foto>/baca.jpg & baca.npz, dibuat saat foto diproses).

Label:
  emas   = label panitia di layar Latih Model (per bulatan)
  perak  = jawaban akhir lembar Sudah dicek (soal 1..jumlah soal, digit nomor & kode)
  perunggu = bulatan yang sangat jelas (isian tebal / kertas bersih) menurut aturan, sebagai
             contoh dasar; tidak pernah dipakai untuk ujian.
1 dari 4 lembar (tetap, menurut nama foto) disisihkan sebagai lembar UJIAN: tidak pernah dipakai
melatih. Model diaktifkan (<data>/model/aktif.json) hanya bila lulus ujian pada label emas di
lembar ujian (gerbang A). Gerbang B (boleh memutus kasus ragu) lebih ketat.
"""
import argparse
import warnings
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))   # mesin pembaca ljk/
from ljk import belajar as BL  # noqa: E402
from ljk import db as DBM  # noqa: E402
from ljk import omr as OM  # noqa: E402

MIN_EMAS_LATIH = 30       # label emas di lembar latih minimal sebelum melatih
MIN_UJI = 60              # label emas di lembar ujian minimal sebelum model boleh aktif
MIN_UJI_RAGU = 40         # kasus ragu berlabel di lembar ujian minimal untuk gerbang B
MAKS_SALAH_MUDAH = 0.002  # model tidak boleh "berbeda pendapat yakin" pada > 0,2% bulatan jelas
BOBOT = {"emas": 3.0, "perak": 1.0, "perunggu": 0.5}
SIDE = BL.PATCH + 4       # potongan sedikit lebih besar untuk augmentasi geser


class Net(nn.Module):
    """CNN kecil (~73 ribu parameter): potongan 3x32x32 -> peluang (kosong, terisi, hapusan)."""

    def __init__(self):
        super().__init__()

        def blk(i, o):
            return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(),
                                 nn.Conv2d(o, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU())
        self.f = nn.Sequential(blk(3, 16), nn.MaxPool2d(2), blk(16, 32), nn.MaxPool2d(2), blk(32, 64),
                               nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.2), nn.Linear(64, 3))

    def forward(self, x):
        return torch.softmax(self.f(x), dim=1)


def log(msg):
    print(msg, flush=True)


def kumpulkan(data_dir, seed=0):
    """Kumpulkan potongan + label dari semua lembar. Mengembalikan dict berisi array."""
    rng = np.random.default_rng(seed)
    db = DBM.DB(Path(data_dir) / "ljk.db")
    labels = db.labels()
    naskah = {}
    for ev in db.events():
        naskah[ev["id"]] = {s.kode: s.jumlah for s in db.naskah(ev["id"])}
    out = {k: [] for k in ("patch", "label", "sumber", "uji", "aturan", "ragu", "file", "idx")}
    for row in db.all_lembar():
        if row["error"]:
            continue
        data = BL.load_sheet(row)
        if data is None:
            continue
        uji = BL.is_test_sheet(row["file"])
        emas = {idx: lab for (f, idx), lab in labels.items() if f == row["file"]}
        items = [(i, lab, "emas") for i, lab in emas.items()]
        if row["dicek"] and not uji:
            jumlah = naskah.get(row["event_id"], {}).get(row["kode"], 0)
            items += [(i, lab, "perak") for i, lab in BL.review_labels(row, data, jumlah) if i not in emas]
        skor, kilap, pilih, ragu = data["skor"], data["kilap"], data["pilih"], data["ragu"]
        isi = np.flatnonzero(pilih & (skor >= 0.35) & ~ragu)
        bersih = np.flatnonzero((skor <= 0.02) & (kilap == 0) & ~pilih)
        for arr, lab in ((isi, "terisi"), (bersih, "kosong")):
            pick = rng.choice(arr, size=min(len(arr), 60), replace=False) if len(arr) else []
            items += [(int(i), lab, "perunggu") for i in pick if int(i) not in emas]
        if not items:
            continue
        img = BL.read_image(data["dir"])
        idxs = np.array([i for i, _, _ in items])
        P = BL.patches(img, data["xy"][idxs], size=SIDE)
        for (i, lab, src), p in zip(items, P):
            out["patch"].append(p)
            out["label"].append(BL.KELAS.index(lab))
            out["sumber"].append(src)
            out["uji"].append(uji)
            out["aturan"].append(bool(pilih[i]))
            out["ragu"].append(bool(ragu[i]))
            out["file"].append(row["file"])
            out["idx"].append(i)
    return {k: np.array(v) for k, v in out.items()}


def augment(batch, rng):
    """Geser acak +-2 px, kontras/kecerahan per kanal, sedikit derau. batch: N x SIDE x SIDE x 3 uint8."""
    n = len(batch)
    ox, oy = rng.integers(0, SIDE - BL.PATCH + 1, n), rng.integers(0, SIDE - BL.PATCH + 1, n)
    crop = np.stack([b[y:y + BL.PATCH, x:x + BL.PATCH] for b, x, y in zip(batch, ox, oy)])
    f = crop.astype(np.float32)
    f = f * rng.uniform(0.85, 1.15, (n, 1, 1, 3)) + rng.uniform(-12, 12, (n, 1, 1, 1))
    f = f + rng.normal(0, rng.uniform(0, 4, (n, 1, 1, 1)), f.shape)
    return BL.normalize(np.clip(f, 0, 255).astype(np.uint8))


def center(batch):
    o = (SIDE - BL.PATCH) // 2
    return BL.normalize(batch[:, o:o + BL.PATCH, o:o + BL.PATCH])


def latih(D, epochs, seed=0):
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    tr = ~D["uji"]
    X, y = D["patch"][tr], D["label"][tr]
    w = np.array([BOBOT[s] for s in D["sumber"][tr]], np.float64)
    # seimbangkan kelas: peluang terambil tiap kelas sama besar; di dalam kelas sesuai bobot sumber
    for c in range(3):
        m = y == c
        if m.any():
            w[m] = w[m] / w[m].sum()
    net = Net()
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
    steps = max(1, len(X) // 128)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=epochs * steps)
    prob = w / w.sum()
    for ep in range(epochs):
        net.train()
        tot = 0.0
        for _ in range(steps):
            b = rng.choice(len(X), size=128, p=prob)
            xb = torch.from_numpy(augment(X[b], rng))
            yb = torch.from_numpy(y[b].astype(np.int64))
            p = net(xb)
            loss = nn.functional.nll_loss(torch.log(p + 1e-7), yb)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot += loss.item()
        log(f"  putaran {ep + 1}/{epochs}: loss {tot / steps:.4f}")
    return net.eval()


def predict(net, patches_center):
    with torch.no_grad():
        return net(torch.from_numpy(patches_center)).numpy()


def nilai(prob, D, sel):
    """Ukuran mutu pada bulatan terpilih (label emas di lembar ujian)."""
    human = D["label"][sel] == 1
    model = prob[sel][:, 1] >= 0.5
    aturan = D["aturan"][sel]
    return {"n": int(sel.sum()), "akurasi_model": float((model == human).mean()) if sel.any() else None,
            "akurasi_aturan": float((aturan == human).mean()) if sel.any() else None,
            "model_salah": int((model != human).sum()), "aturan_salah": int((aturan != human).sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(Path(os.environ["LOCALAPPDATA"]) / "LJK Reader"))
    ap.add_argument("--epoch", type=int, default=15)
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
    t0 = time.time()
    model_dir = Path(a.data) / "model"
    model_dir.mkdir(parents=True, exist_ok=True)

    log("Mengumpulkan contoh dari lembar yang sudah diproses...")
    D = kumpulkan(a.data)
    if len(D["label"]) == 0:
        log("Belum ada data. Proses foto dulu, lalu beri label di layar Latih Model.")
        return 2
    emas = D["sumber"] == "emas"
    cnt = {s: int((D["sumber"] == s).sum()) for s in BOBOT}
    log(f"Contoh: emas {cnt['emas']} (latih {int((emas & ~D['uji']).sum())}, ujian {int((emas & D['uji']).sum())}), "
        f"perak {cnt['perak']}, perunggu {cnt['perunggu']}")
    if (emas & ~D["uji"]).sum() < MIN_EMAS_LATIH:
        log(f"Label emas di lembar latih baru {int((emas & ~D['uji']).sum())}; perlu minimal {MIN_EMAS_LATIH}. "
            "Tambah label di layar Latih Model.")
        return 2

    log(f"Melatih ({a.epoch} putaran, CPU)...")
    net = latih(D, a.epoch)
    prob = predict(net, center(D["patch"]))

    uji_emas = emas & D["uji"]
    hasil = nilai(prob, D, uji_emas)
    ragu_sel = uji_emas & D["ragu"]
    yakin = (prob[:, 1] >= OM.P_PUTUS) | (prob[:, 1] <= 1 - OM.P_PUTUS)
    rb = ragu_sel & yakin
    benar_rb = ((prob[rb][:, 1] >= 0.5) == (D["label"][rb] == 1))
    mudah = (D["sumber"] == "perunggu") & D["uji"]
    beda_yakin = mudah & (((prob[:, 1] >= 0.9) & ~D["aturan"]) | ((prob[:, 1] <= 0.1) & D["aturan"]))
    salah_mudah = float(beda_yakin.sum() / max(mudah.sum(), 1))

    # model aktif sebelumnya (bila ada) diuji pada lembar ujian yang sama
    lama = None
    akt = model_dir / "aktif.json"
    if akt.exists():
        info = json.loads(akt.read_text(encoding="utf-8"))
        if info.get("aktif") and (model_dir / info["file"]).exists() and uji_emas.any():
            old = BL.Model(model_dir / info["file"], info)
            old.net.setInput(center(D["patch"][uji_emas]))
            po = np.asarray(old.net.forward())
            lama = {"versi": info.get("versi"), "akurasi": float(((po[:, 1] >= 0.5) == (D["label"][uji_emas] == 1)).mean())
                    if uji_emas.any() else None}

    lulus_a = (hasil["n"] >= MIN_UJI and hasil["akurasi_model"] >= hasil["akurasi_aturan"]
               and salah_mudah <= MAKS_SALAH_MUDAH
               and (lama is None or lama["akurasi"] is None or hasil["akurasi_model"] >= lama["akurasi"]))
    lulus_b = lulus_a and int(rb.sum()) >= MIN_UJI_RAGU and float(benar_rb.mean()) >= 0.99

    versi = time.strftime("bulatan-%Y%m%d-%H%M%S")
    onnx_path = model_dir / f"{versi}.onnx"
    dummy = torch.from_numpy(center(D["patch"][:4]))
    torch.onnx.export(net, (dummy,), str(onnx_path), input_names=["x"], output_names=["p"], opset_version=17,
                      dynamic_axes={"x": {0: "n"}, "p": {0: "n"}}, dynamo=False)
    cek = BL.Model(onnx_path, {})
    cek.net.setInput(center(D["patch"][:200]))
    selisih = float(np.abs(np.asarray(cek.net.forward()) - prob[:200]).max())

    laporan = {
        "versi": versi, "waktu_latih_detik": round(time.time() - t0, 1), "contoh": cnt,
        "ujian": hasil, "ujian_kasus_ragu": {"n_yakin": int(rb.sum()), "akurasi_yakin": float(benar_rb.mean()) if rb.any() else None},
        "beda_yakin_pada_bulatan_jelas": salah_mudah, "model_sebelumnya": lama, "selisih_onnx": selisih,
        "gerbang_a": bool(lulus_a), "gerbang_b": bool(lulus_b),
        "syarat": {"min_uji": MIN_UJI, "min_uji_ragu": MIN_UJI_RAGU, "maks_beda_yakin_jelas": MAKS_SALAH_MUDAH},
    }
    (model_dir / f"{versi}.json").write_text(json.dumps(laporan, indent=1, ensure_ascii=False), encoding="utf-8")

    log("")
    log(f"UJIAN pada {hasil['n']} label Anda di lembar ujian (tidak dipakai melatih):")
    if hasil["n"]:
        log(f"  benar: model {hasil['akurasi_model']:.1%} ({hasil['model_salah']} salah) | "
            f"aturan sekarang {hasil['akurasi_aturan']:.1%} ({hasil['aturan_salah']} salah)")
    log(f"  beda pendapat yakin pada bulatan yang jelas: {salah_mudah:.2%} (batas {MAKS_SALAH_MUDAH:.1%})")
    if lama:
        log(f"  model aktif sebelumnya ({lama['versi']}): {lama['akurasi']:.1%}")
    if lulus_a:
        if akt.exists():
            akt.replace(model_dir / "aktif-sebelumnya.json")
        akt.write_text(json.dumps({"aktif": True, "file": onnx_path.name, "versi": versi, "gerbang_b": bool(lulus_b),
                                   "laporan": laporan}, indent=1, ensure_ascii=False), encoding="utf-8")
        log(f"HASIL: LULUS -> model {versi} AKTIF sebagai juri kedua"
            + (" (boleh memutus kasus ragu)." if lulus_b else " (kasus ragu tetap dicek manusia)."))
    else:
        alasan = []
        if hasil["n"] < MIN_UJI:
            alasan.append(f"label di lembar ujian baru {hasil['n']} dari minimal {MIN_UJI}")
        elif hasil["akurasi_model"] < hasil["akurasi_aturan"]:
            alasan.append("model belum lebih baik dari aturan sekarang")
        if salah_mudah > MAKS_SALAH_MUDAH:
            alasan.append("terlalu sering berbeda pendapat pada bulatan yang jelas")
        if lama and lama["akurasi"] is not None and hasil["n"] and hasil["akurasi_model"] < lama["akurasi"]:
            alasan.append("lebih buruk dari model aktif sebelumnya")
        log("HASIL: BELUM LULUS -> model tidak diaktifkan (" + "; ".join(alasan) + ").")
    return 0


if __name__ == "__main__":
    sys.exit(main())
