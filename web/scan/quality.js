// Penilai kualitas foto LJK (berjalan di HP, ±5-10 kali per detik pada gambar kecil).
//
// Langkah:
// 1. Cari 4 kotak hitam di sudut LJK (komponen gelap berbentuk persegi, memakai kanal merah
//    supaya cetakan merah LJK hilang - sama seperti mesin desktop).
// 2. Syarat wajib: 4 sudut terlihat, kertas cukup besar, tidak terpotong, tidak miring, HP sejajar.
// 3. Nilai tambahan: ketajaman, kecerahan, silau, bayangan, HP diam.
// Bila satu syarat wajib gagal, skor ditahan di bawah 60.

export const ANALYSIS_WIDTH = 480;   // lebar gambar analisis (piksel)
export const ASPECT = 1400 / 2000;    // lebar/tinggi bingkai 4 kotak sudut LJK

export const WEIGHTS = { tajam: 30, terang: 25, silau: 20, bayangan: 15, stabil: 10 };
// Ambang (dikalibrasi dari foto LJK asli di lebar 480 px)
export const LIMITS = {
  terangMin: 70, terangBagus: 130, terangLebih: 248,     // tingkat kertas (persentil 75 luminans)
  tajamMin: 60, tajamBagus: 250,                         // variansi Laplacian di dalam kertas
  silauBagus: 0.15, silauMax: 2.0,                       // % piksel jenuh di dalam kertas
  bayanganMin: 0.55, bayanganBagus: 0.82,                // rasio sel tergelap / terterang
  geserBagus: 0.004, geserMax: 0.02,                     // perpindahan sudut antar frame / diagonal
  luasMin: 0.40,                                         // luas 4 sudut / luas layar
  tepi: 0.012,                                           // jarak minimum sudut ke tepi gambar
  miringMax: 15,                                         // derajat
  perspektifMax: 1.3,                                    // rasio sisi berhadapan
};

const ramp = (v, lo, hi) => Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

/** Ambil data piksel kecil dari video/gambar. Mengembalikan ImageData. */
export function grab(source, canvas, width = ANALYSIS_WIDTH) {
  const sw = source.videoWidth || source.naturalWidth || source.width;
  const sh = source.videoHeight || source.naturalHeight || source.height;
  if (!sw || !sh) return null;
  const w = width, h = Math.round(sh * width / sw);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(source, 0, 0, w, h);
  return ctx.getImageData(0, 0, w, h);
}

function percentile(hist, total, p) {
  let acc = 0;
  const target = total * p;
  for (let i = 0; i < 256; i++) { acc += hist[i]; if (acc >= target) return i; }
  return 255;
}

/**
 * Topeng piksel gelap dengan ambang lokal: piksel dibandingkan dengan rata-rata sekitarnya,
 * sehingga kertas yang terkena bayangan tidak ikut dianggap hitam.
 */
export function darkMask(red, w, h) {
  const win = Math.max(9, Math.round(Math.min(w, h) * 0.06)) | 1, r = win >> 1;
  const W = w + 1, sum = new Float64Array(W * (h + 1));
  for (let y = 0; y < h; y++) {
    let row = 0;
    for (let x = 0; x < w; x++) { row += red[y * w + x]; sum[(y + 1) * W + x + 1] = sum[y * W + x + 1] + row; }
  }
  const mask = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const y0 = Math.max(0, y - r), y1 = Math.min(h, y + r + 1);
    for (let x = 0; x < w; x++) {
      const x0 = Math.max(0, x - r), x1 = Math.min(w, x + r + 1);
      const mean = (sum[y1 * W + x1] - sum[y0 * W + x1] - sum[y1 * W + x0] + sum[y0 * W + x0]) / ((y1 - y0) * (x1 - x0));
      const v = red[y * w + x];
      mask[y * w + x] = v < mean * 0.6 && v < 150 ? 1 : 0;
    }
  }
  return mask;
}

/** Komponen gelap berbentuk persegi padat (calon kotak sudut). */
export function findSquares(dark, w, h) {
  const n = w * h;
  const lab = new Int32Array(n);
  const stack = new Int32Array(n);
  const out = [];
  const minDim = Math.min(w, h);
  const sMin = Math.max(3, minDim * 0.008), sMax = minDim * 0.09;
  let next = 1;
  for (let start = 0; start < n; start++) {
    if (lab[start] || !dark[start]) continue;
    let sp = 0, cnt = 0, minx = w, maxx = 0, miny = h, maxy = 0, sx = 0, sy = 0;
    stack[sp++] = start; lab[start] = next;
    let big = false;
    while (sp) {
      const p = stack[--sp];
      const x = p % w, y = (p - x) / w;
      cnt++; sx += x; sy += y;
      if (x < minx) minx = x; if (x > maxx) maxx = x; if (y < miny) miny = y; if (y > maxy) maxy = y;
      if (maxx - minx > sMax * 2 || maxy - miny > sMax * 2) big = true;
      if (x > 0) { const q = p - 1; if (!lab[q] && dark[q]) { lab[q] = next; stack[sp++] = q; } }
      if (x < w - 1) { const q = p + 1; if (!lab[q] && dark[q]) { lab[q] = next; stack[sp++] = q; } }
      if (y > 0) { const q = p - w; if (!lab[q] && dark[q]) { lab[q] = next; stack[sp++] = q; } }
      if (y < h - 1) { const q = p + w; if (!lab[q] && dark[q]) { lab[q] = next; stack[sp++] = q; } }
    }
    next++;
    if (big) continue;
    const bw = maxx - minx + 1, bh = maxy - miny + 1;
    const side = (bw + bh) / 2;
    if (side < sMin || side > sMax) continue;
    const aspect = bw / bh;
    if (aspect < 0.6 || aspect > 1.67) continue;
    if (cnt / (bw * bh) < 0.5) continue;           // kotak miring 45 derajat: ~0,5
    out.push({ x: sx / cnt, y: sy / cnt, side });
  }
  return out;
}

/**
 * Pilih 4 kandidat yang paling cocok sebagai sudut LJK: membentuk jajaran genjang berproporsi
 * ~0,7, ukuran kotak mirip, dan seluas mungkin. Urutan sudut ditentukan dari arah terhadap
 * titik tengahnya, jadi tetap benar walau kertas miring.
 */
const IDEAL = [-3, -1, 1, 3].map(v => v * Math.PI / 4);

export function pickCorners(cands, minArea = 0) {
  const c = [...cands].sort((a, b) => b.side - a.side).slice(0, 12);
  let best = null, bestFit = 0;
  const n = c.length;
  for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) for (let d = b + 1; d < n; d++) for (let e = d + 1; e < n; e++) {
    const pts = [c[a], c[b], c[d], c[e]];
    const sides = pts.map(p => p.side);
    if (Math.max(...sides) / Math.min(...sides) > 2.0) continue;
    const cx = (pts[0].x + pts[1].x + pts[2].x + pts[3].x) / 4, cy = (pts[0].y + pts[1].y + pts[2].y + pts[3].y) / 4;
    // urutkan menurut arah dari titik tengah (searah jarum jam di layar), lalu pilih rotasi yang
    // paling dekat ke arah ideal TL -135, TR -45, BR 45, BL 135 derajat
    const o = pts.map(p => ({ p, t: Math.atan2(p.y - cy, p.x - cx) })).sort((u, v) => u.t - v.t);
    let k = 0, kErr = Infinity;
    for (let r = 0; r < 4; r++) {
      let err = 0;
      for (let i = 0; i < 4; i++) {
        let d = Math.abs(o[(r + i) % 4].t - IDEAL[i]) % (2 * Math.PI);
        err += Math.min(d, 2 * Math.PI - d);
      }
      if (err < kErr) { kErr = err; k = r; }
    }
    const [tl, tr, br, bl] = [0, 1, 2, 3].map(i => o[(k + i) % 4].p);
    const top = dist(tl, tr), bottom = dist(bl, br), left = dist(tl, bl), right = dist(tr, br);
    if (!top || !bottom || !left || !right) continue;
    // LJK boleh tegak atau terputar 90 derajat (HP dipegang mendatar): pakai sisi pendek / sisi panjang
    let aspect = (top + bottom) / (left + right);
    if (aspect > 1) aspect = 1 / aspect;
    if (aspect < 0.55 || aspect > 0.88) continue;
    if (Math.max(top / bottom, bottom / top, left / right, right / left) > 1.7) continue;
    const diag = (dist(tl, br) + dist(tr, bl)) / 2;
    const mid = Math.hypot((tl.x + br.x - tr.x - bl.x) / 2, (tl.y + br.y - tr.y - bl.y) / 2);
    if (mid / diag > 0.1) continue;
    const q = { tl, tr, bl, br, top, bottom, left, right };
    const area = quadArea(q);
    if (area < minArea) continue;
    // utamakan bentuk yang paling mirip bingkai LJK, baru luasnya
    const fit = area * Math.max(0, 1 - 4 * Math.abs(aspect - ASPECT)) * Math.max(0, 1 - 5 * mid / diag);
    if (fit > bestFit) { bestFit = fit; best = q; }
  }
  return best;
}

/**
 * Bila hanya 3 sudut terlihat: cari 3 kandidat yang membentuk sudut siku berproporsi LJK dan
 * perkirakan sudut ke-4. Dipakai hanya bila sudut ke-4 itu berada di luar / di tepi gambar
 * (kertas terpotong), supaya sarannya "terlalu dekat" alih-alih "LJK belum terlihat".
 */
export function pickThree(cands, w, h, minArea) {
  const c = [...cands].sort((a, b) => b.side - a.side).slice(0, 10);
  let best = null, bestArea = 0;
  const n = c.length;
  for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) for (let d = b + 1; d < n; d++) {
    const t = [c[a], c[b], c[d]];
    const sides = t.map(p => p.side);
    if (Math.max(...sides) / Math.min(...sides) > 2.0) continue;
    for (let v = 0; v < 3; v++) {
      const m = t[v], p1 = t[(v + 1) % 3], p2 = t[(v + 2) % 3];
      const ax = p1.x - m.x, ay = p1.y - m.y, bx = p2.x - m.x, by = p2.y - m.y;
      const la = Math.hypot(ax, ay), lb = Math.hypot(bx, by);
      if (!la || !lb || Math.abs((ax * bx + ay * by) / (la * lb)) > 0.15) continue;
      const r = Math.min(la, lb) / Math.max(la, lb);
      if (r < 0.55 || r > 0.88) continue;
      const area = la * lb;
      if (area < minArea || area <= bestArea) continue;
      const side = (m.side + p1.side + p2.side) / 3;
      const q4 = { x: p1.x + p2.x - m.x, y: p1.y + p2.y - m.y, side };
      const edge = side * 1.5;
      if (q4.x > edge && q4.y > edge && q4.x < w - edge && q4.y < h - edge) continue;
      bestArea = area;
      best = [m, p1, p2, q4];
    }
  }
  if (!best) return null;
  // susun ulang 4 titik menjadi TL, TR, BR, BL dengan pickCorners (tanpa batas luas)
  return pickCorners(best, 0);
}

function quadArea(q) {
  const pts = [q.tl, q.tr, q.br, q.bl];
  let a = 0;
  for (let i = 0; i < 4; i++) { const p = pts[i], r = pts[(i + 1) % 4]; a += p.x * r.y - r.x * p.y; }
  return Math.abs(a) / 2;
}

/**
 * Nilai satu frame. prev: hasil frame sebelumnya (untuk kestabilan).
 * Mengembalikan { score, ready, gates, sub, metrics, corners, tip }.
 */
export function analyze(img, prev = null) {
  const { data, width: w, height: h } = img;
  const n = w * h;
  const red = new Uint8Array(n), lum = new Uint8Array(n);
  const histR = new Uint32Array(256);
  for (let i = 0, j = 0; i < n; i++, j += 4) {
    const r = data[j], g = data[j + 1], b = data[j + 2];
    red[i] = r;
    lum[i] = (r * 77 + g * 150 + b * 29) >> 8;
    histR[r]++;
  }
  const paperR = percentile(histR, n, 0.9);
  const cands = paperR > 35 ? findSquares(darkMask(red, w, h), w, h) : [];
  const minArea = w * h * 0.1;
  let q = pickCorners(cands, minArea), inferred = false;
  if (!q) { q = pickThree(cands, w, h, minArea * 0.5); inferred = !!q; }

  // daerah kertas: kotak di antara 4 sudut (sedikit menyusut), atau tengah gambar bila sudut belum ada
  let x0, x1, y0, y1;
  if (q) {
    x0 = Math.max(q.tl.x, q.bl.x); x1 = Math.min(q.tr.x, q.br.x);
    y0 = Math.max(q.tl.y, q.tr.y); y1 = Math.min(q.bl.y, q.br.y);
    const mx = (x1 - x0) * 0.03, my = (y1 - y0) * 0.03;
    x0 += mx; x1 -= mx; y0 += my; y1 -= my;
  } else { x0 = w * 0.2; x1 = w * 0.8; y0 = h * 0.2; y1 = h * 0.8; }
  x0 = Math.max(1, Math.round(x0)); x1 = Math.min(w - 2, Math.round(x1));
  y0 = Math.max(1, Math.round(y0)); y1 = Math.min(h - 2, Math.round(y1));

  // kecerahan, silau, ketajaman di dalam kertas
  const histL = new Uint32Array(256);
  let cnt = 0, sat = 0, lapSum = 0, lapSq = 0, lapN = 0;
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const i = y * w + x, v = lum[i];
      histL[v]++; cnt++;
      if (v >= 250) sat++;
      if (((x + y) & 1) === 0) {
        const lap = lum[i - 1] + lum[i + 1] + lum[i - w] + lum[i + w] - 4 * v;
        lapSum += lap; lapSq += lap * lap; lapN++;
      }
    }
  }
  const terang = cnt ? percentile(histL, cnt, 0.75) : 0;
  const silau = cnt ? (sat / cnt) * 100 : 0;
  const tajam = lapN ? lapSq / lapN - (lapSum / lapN) ** 2 : 0;

  // bayangan: tingkat kertas per sel (persentil 80) dalam kisi 3x4
  const cols = 3, rows = 4, levels = [];
  for (let gy = 0; gy < rows; gy++) {
    for (let gx = 0; gx < cols; gx++) {
      const cx0 = x0 + Math.floor((x1 - x0) * gx / cols), cx1 = x0 + Math.floor((x1 - x0) * (gx + 1) / cols);
      const cy0 = y0 + Math.floor((y1 - y0) * gy / rows), cy1 = y0 + Math.floor((y1 - y0) * (gy + 1) / rows);
      const hc = new Uint32Array(256); let k = 0;
      for (let y = cy0; y < cy1; y += 2) for (let x = cx0; x < cx1; x += 2) { hc[lum[y * w + x]]++; k++; }
      if (k) levels.push(percentile(hc, k, 0.8));
    }
  }
  const bayangan = levels.length ? Math.min(...levels) / Math.max(1, Math.max(...levels)) : 0;

  // geometri
  let luas = 0, miring = 0, perspektif = 1, terpotong = false, geser = 0;
  if (q) {
    luas = quadArea(q) / (w * h);
    const a = Math.abs(Math.atan2(q.tr.y - q.tl.y, q.tr.x - q.tl.x) * 180 / Math.PI) % 90;
    miring = Math.min(a, 90 - a);
    perspektif = Math.max(q.top / q.bottom, q.bottom / q.top, q.left / q.right, q.right / q.left);
    const m = Math.min(w, h) * LIMITS.tepi;
    terpotong = inferred || [q.tl, q.tr, q.bl, q.br].some(p => p.x - p.side / 2 < m || p.y - p.side / 2 < m ||
      p.x + p.side / 2 > w - m || p.y + p.side / 2 > h - m);
    if (prev && prev.corners) {
      const diag = Math.hypot(w, h);
      geser = Math.max(...["tl", "tr", "bl", "br"].map(k => dist(q[k], prev.corners[k]))) / diag;
    }
  } else geser = 1;

  const sub = {
    tajam: ramp(tajam, LIMITS.tajamMin, LIMITS.tajamBagus),
    terang: terang > LIMITS.terangLebih ? 0.4 : ramp(terang, LIMITS.terangMin, LIMITS.terangBagus),
    silau: 1 - ramp(silau, LIMITS.silauBagus, LIMITS.silauMax),
    bayangan: ramp(bayangan, LIMITS.bayanganMin, LIMITS.bayanganBagus),
    stabil: q ? 1 - ramp(geser, LIMITS.geserBagus, LIMITS.geserMax) : 0,
  };
  const gates = {
    sudut: !!q,
    jarak: !!q && luas >= LIMITS.luasMin,
    utuh: !!q && !terpotong,
    lurus: !!q && miring < LIMITS.miringMax,
    sejajar: !!q && perspektif < LIMITS.perspektifMax,
  };
  let score = 0;
  for (const k in WEIGHTS) score += WEIGHTS[k] * sub[k];
  if (!gates.sudut) score = Math.min(score * 0.45, 40);
  else if (!Object.values(gates).every(Boolean)) score = Math.min(score * 0.6, 59);
  score = Math.round(score);

  const tip = pickTip(gates, sub, terang);
  return {
    score, gates, sub, tip,
    ready: Object.values(gates).every(Boolean) && score >= 90,
    corners: q ? { tl: q.tl, tr: q.tr, bl: q.bl, br: q.br } : null,
    size: { w, h },
    metrics: {
      terang: Math.round(terang), tajam: Math.round(tajam), silau: +silau.toFixed(2), bayangan: +bayangan.toFixed(2),
      luas: +luas.toFixed(2), miring: +miring.toFixed(1), perspektif: +perspektif.toFixed(2), geser: +geser.toFixed(4),
    },
  };
}

function pickTip(g, s, terang) {
  if (s.terang < 0.45 && terang <= LIMITS.terangLebih)
    return { key: "terang", title: "Terlalu gelap", text: "Cari tempat yang lebih terang atau nyalakan senter." };
  if (terang > LIMITS.terangLebih)
    return { key: "terang", title: "Terlalu terang", text: "Hindari cahaya langsung yang terlalu kuat." };
  if (!g.sudut && s.tajam < 0.3) return { key: "tajam", title: "Gambar buram", text: "Tahan HP tetap diam, ketuk layar untuk fokus." };
  if (!g.sudut) return { key: "sudut", title: "LJK belum terlihat", text: "Arahkan kamera ke LJK sampai 4 kotak hitam di sudut kertas terlihat." };
  if (!g.utuh) return { key: "utuh", title: "Terlalu dekat", text: "Mundurkan HP sedikit; kotak hitam di sudut jangan terpotong." };
  if (!g.jarak) return { key: "jarak", title: "Kertas terlalu jauh", text: "Dekatkan HP sampai kertas memenuhi bingkai." };
  if (!g.lurus) return { key: "lurus", title: "Kertas miring", text: "Putar HP sampai tepi kertas lurus dengan bingkai." };
  if (!g.sejajar) return { key: "sejajar", title: "HP tidak sejajar", text: "Pegang HP sejajar tepat di atas kertas, jangan dari samping." };
  if (s.tajam < 0.6) return { key: "tajam", title: "Gambar buram", text: "Tahan HP tetap diam, ketuk layar untuk fokus." };
  if (s.silau < 0.6) return { key: "silau", title: "Ada pantulan cahaya", text: "Ubah sudut HP atau lampu supaya tidak ada kilap di kertas." };
  if (s.bayangan < 0.6) return { key: "bayangan", title: "Ada bayangan", text: "Hindari bayangan tangan atau HP di atas kertas." };
  if (s.terang < 0.8) return { key: "terang", title: "Agak gelap", text: "Cahaya sedikit kurang; tambah penerangan bila bisa." };
  if (s.stabil < 0.6) return { key: "stabil", title: "Tahan HP", text: "Tahan sebentar tanpa bergerak." };
  return { key: "ok", title: "Siap", text: "Tahan sebentar, foto diambil otomatis." };
}

export const CHIPS = [["terang", "Cahaya"], ["tajam", "Fokus"], ["sudut", "4 sudut"], ["jarak", "Jarak"], ["silau", "Silau"]];
export function chipState(r, key) {
  if (key in r.gates && key !== "jarak") return r.gates[key];
  if (key === "jarak") return r.gates.jarak && r.gates.utuh;
  return r.sub[key] >= 0.6;
}
