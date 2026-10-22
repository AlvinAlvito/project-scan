// Web HP admin daerah: pilih kompetisi -> kamera dengan pemandu kualitas -> kirim -> konfirmasi hasil baca.
import { api, esc, fileUrl, icon, logout, modal, pctBadge, requireLogin, statusBadge, toast,
  toggleTheme, currentTheme, confirmBox, fmtDate } from "/static/js/common.js";
import { analyze, grab, measureSharpness, fitFrame, FRAME_ASPECT, ANALYSIS_WIDTH, CHIPS, chipState } from "./quality.js";
import { queue, flush } from "./queue.js";

const $ = s => document.querySelector(s);
const user = requireLogin("admin_daerah");
const SEL_KEY = "ljk_scan_sel";
const state = { akses: [], sel: null, stream: null, track: null, capture: null, timer: null, prev: null,
  smooth: 0, readySince: 0, busy: false, lembar: null, view: "pilih" };

document.querySelectorAll("[data-icon]").forEach(el => { el.innerHTML = icon(el.dataset.icon) + el.innerHTML; });
$("#who").textContent = user ? user.nama : "";
const paintTheme = () => { $("#b-theme").innerHTML = icon(currentTheme() === "dark" ? "sun" : "moon"); };
paintTheme();
$("#b-theme").onclick = () => { toggleTheme(); paintTheme(); };
$("#b-logout").onclick = async () => { if (await confirmBox("Keluar", "Keluar dari akun ini?", "Keluar")) logout(); };

// ---------------------------------------------------------------- navigasi
const VIEWS = ["pilih", "kamera", "hasil", "riwayat"];
function show(v) {
  state.view = v;
  VIEWS.forEach(n => { $("#v-" + n).hidden = n !== v; });
  $("#top").hidden = v === "kamera";
  if (v === "kamera") startCamera(); else stopCamera();
  window.scrollTo(0, 0);
}
function busy(on, text) { $("#v-kirim").hidden = !on; if (text) $("#busy-text").textContent = text; }

// ---------------------------------------------------------------- 1. pilih
function saveSel() { try { localStorage.setItem(SEL_KEY, JSON.stringify({ lokasi: state.sel?.lokasi?.id, bidang: state.sel?.bidang?.id })); } catch (e) { /* abaikan */ } }
function loadSel() { try { return JSON.parse(localStorage.getItem(SEL_KEY) || "{}"); } catch (e) { return {}; } }

async function loadAkses() {
  try { state.akses = await api("/api/scan/akses"); }
  catch (e) { $("#akses-list").innerHTML = `<div class="alert err">${esc(e.message)}</div>`; return; }
  const saved = loadSel();
  const a = state.akses.find(x => x.lokasi.id === saved.lokasi);
  if (a) state.sel = { ...a, bidang: a.bidang.find(b => b.id === saved.bidang) || null };
  renderPilih();
}

function renderPilih() {
  const list = $("#akses-list");
  if (!state.akses.length) {
    list.innerHTML = `<div class="card empty">${icon("inbox")}<b>Belum ada kompetisi untuk Anda</b><span>Minta panitia pusat menambahkan akses lokasi ke akun ini.</span></div>`;
    $("#b-mulai").disabled = true;
    return;
  }
  list.innerHTML = state.akses.map((a, i) => {
    const sel = state.sel && state.sel.lokasi.id === a.lokasi.id;
    const bid = sel ? `<div class="bidang-list">${a.bidang.length ? a.bidang.map(b =>
      `<button class="pill ${state.sel.bidang?.id === b.id ? "sel" : ""}" data-b="${b.id}">${esc(b.nama)} <span class="muted">${esc(b.kode_naskah)}</span></button>`).join("")
      : `<span class="muted small">Belum ada bidang di kompetisi ini.</span>`}</div>` : "";
    return `<div class="card akses ${sel ? "sel" : ""}" data-i="${i}">
      <div class="t"><div class="ic">${icon("trophy")}</div><div class="grow"><b>${esc(a.kompetisi.nama)}</b>
      <div class="muted small">${icon("mapPin", "sm")} ${esc(a.lokasi.kota)}${a.kompetisi.tanggal ? " · " + esc(fmtDate(a.kompetisi.tanggal)) : ""}</div></div></div>${bid}</div>`;
  }).join("");
  list.querySelectorAll(".akses").forEach(card => card.onclick = e => {
    const a = state.akses[+card.dataset.i];
    const b = e.target.closest("[data-b]");
    if (!state.sel || state.sel.lokasi.id !== a.lokasi.id) state.sel = { ...a, bidang: a.bidang.length === 1 ? a.bidang[0] : null };
    if (b) state.sel.bidang = a.bidang.find(x => x.id === +b.dataset.b);
    saveSel();
    renderPilih();
  });
  $("#b-mulai").disabled = !(state.sel && state.sel.bidang);
}
$("#b-mulai").onclick = () => show("kamera");

// ---------------------------------------------------------------- 2. kamera
const video = $("#video"), overlay = $("#overlay"), work = document.createElement("canvas");

async function startCamera() {
  const s = state.sel;
  $("#ctx-bidang").textContent = `${s.bidang.nama} · kode ${s.bidang.kode_naskah}`;
  $("#ctx-lokasi").textContent = `${s.kompetisi.nama} · ${s.lokasi.kota}`;
  $("#cam-msg").hidden = true;
  state.prev = null; state.smooth = 0; state.readySince = 0;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    camMessage("Kamera hanya bisa dipakai lewat alamat HTTPS.<br>Gunakan tombol galeri untuk memilih foto.");
    return;
  }
  if (!state.stream) {
    try {
      // Resolusi setinggi yang didukung HP: gambar yang dikirim adalah potongan bingkai dari video ini.
      state.stream = await navigator.mediaDevices.getUserMedia({ audio: false,
        video: { facingMode: { ideal: "environment" }, width: { ideal: 3840 }, height: { ideal: 2160 } } });
    } catch (e) {
      camMessage("Kamera tidak bisa dibuka. Izinkan akses kamera di pengaturan browser, lalu muat ulang halaman.");
      return;
    }
    state.track = state.stream.getVideoTracks()[0];
    const caps = state.track.getCapabilities ? state.track.getCapabilities() : {};
    $("#b-torch").hidden = !caps.torch;
    try { await state.track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }); } catch (e) { /* tidak didukung */ }
  }
  video.srcObject = state.stream;
  await video.play().catch(() => {});
  clearInterval(state.timer);
  state.timer = setInterval(tick, 140);
}

function stopCamera() {
  clearInterval(state.timer);
  state.timer = null;
  if (state.stream) { state.stream.getTracks().forEach(t => t.stop()); state.stream = null; state.track = null; }
  video.srcObject = null;
}
function camMessage(html) { const m = $("#cam-msg"); m.innerHTML = `<div>${html}</div>`; m.hidden = false; }

function tick() {
  if (state.busy || !video.videoWidth) return;
  const img = grab(video, work);
  if (!img) return;
  const L = frameLayout();
  const r = fitFrame(measureSharpness(video, analyze(img, state.prev), "live"), L.analysis);
  state.prev = r;
  state.smooth = state.smooth ? Math.round(state.smooth * 0.55 + r.score * 0.45) : r.score;
  renderGuide(r);
  const ready = r.ready && state.smooth >= 90;
  $("#b-shutter").disabled = !ready;
  const now = performance.now();
  if (ready) { if (!state.readySince) state.readySince = now; } else state.readySince = 0;
  const hold = 900, prog = ready && $("#c-auto").checked ? Math.min(1, (now - state.readySince) / hold) : 0;
  $("#shutter-ring").style.strokeDashoffset = String(226.2 * (1 - prog));
  if (prog >= 1) takePhoto(r);
}

function renderGuide(r) {
  const p = state.smooth;
  const sc = $("#score");
  sc.style.setProperty("--p", p);
  sc.style.setProperty("--c", p >= 90 ? "#4ade80" : p >= 60 ? "#fbbf24" : "#f87171");
  $("#score-num").textContent = p + "%";
  $("#chips").innerHTML = CHIPS.map(([k, t]) => `<span class="chip ${chipState(r, k) ? "y" : ""}">${t}</span>`).join("");
  const tip = $("#tip");
  tip.className = "tip" + (r.tip.key === "ok" && r.ready ? " ok" : "");
  tip.innerHTML = `<b>${esc(r.tip.title)}</b><span>${esc(r.tip.text)}</span>`;
  // bingkai panduan (seperti scan KTP): area di luar bingkai digelapkan, penanda sudut hijau bila pas
  const L = frameLayout(), dpr = devicePixelRatio || 1;
  if (overlay.width !== Math.round(L.cw * dpr)) { overlay.width = Math.round(L.cw * dpr); overlay.height = Math.round(L.ch * dpr); }
  const ctx = overlay.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, L.cw, L.ch);
  const { fx, fy, fw, fh } = L;
  ctx.fillStyle = "rgba(0,0,0,.55)";
  ctx.beginPath();
  ctx.rect(0, 0, L.cw, L.ch);
  ctx.rect(fx, fy, fw, fh);
  ctx.fill("evenodd");
  const pas = r.gates.sudut && r.gates.jarak;
  const col = r.ready ? "#4ade80" : pas ? "#a3e635" : "#ffffff";
  ctx.strokeStyle = "rgba(255,255,255,.35)"; ctx.lineWidth = 1;
  ctx.strokeRect(fx, fy, fw, fh);
  const b = Math.min(34, fw * 0.12);
  ctx.strokeStyle = col; ctx.lineWidth = 5; ctx.lineCap = "round";
  for (const [x, y, sx, sy] of [[fx, fy, 1, 1], [fx + fw, fy, -1, 1], [fx, fy + fh, 1, -1], [fx + fw, fy + fh, -1, -1]]) {
    ctx.beginPath(); ctx.moveTo(x + sx * b, y); ctx.lineTo(x, y); ctx.lineTo(x, y + sy * b); ctx.stroke();
  }
  if (r.corners) {           // posisi kotak sudut LJK yang terlihat kamera
    const k = video.videoWidth / r.size.w;
    ctx.fillStyle = pas ? "#4ade80" : "#fbbf24";
    for (const n of ["tl", "tr", "br", "bl"]) {
      ctx.beginPath();
      ctx.arc(L.ox + r.corners[n].x * k * L.s, L.oy + r.corners[n].y * k * L.s, 6, 0, 7);
      ctx.fill();
    }
  }
}

/**
 * Letak bingkai panduan: berbentuk LJK, sebesar mungkin di area video yang tidak tertutup bar atas
 * dan panel bawah. Mengembalikan koordinat layar, koordinat video asli, dan koordinat analisis.
 */
function frameLayout() {
  const cw = overlay.clientWidth, ch = overlay.clientHeight;
  const vw = video.videoWidth || 1080, vh = video.videoHeight || 1920;
  const s = Math.min(cw / vw, ch / vh), ox = (cw - vw * s) / 2, oy = (ch - vh * s) / 2;
  const top = Math.max(oy, document.querySelector(".cam-top").offsetHeight) + 8;
  const bottom = Math.min(oy + vh * s, ch - document.querySelector(".cam-bottom").offsetHeight + 24) - 8;
  let fh = Math.max(120, (bottom - top) * 0.96), fw = fh * FRAME_ASPECT;
  const maxW = vw * s * 0.86;     // sisakan tepi gelap di kiri-kanan supaya bingkai jelas terlihat
  if (fw > maxW) { fw = maxW; fh = fw / FRAME_ASPECT; }
  const fx = ox + (vw * s - fw) / 2, fy = top + Math.max(0, (bottom - top - fh) / 2);
  const v = { x0: (fx - ox) / s, y0: (fy - oy) / s, x1: (fx + fw - ox) / s, y1: (fy + fh - oy) / s };   // px video
  const a = ANALYSIS_WIDTH / vw;                                                                       // px analisis
  return { cw, ch, s, ox, oy, fx, fy, fw, fh, video: v,
           analysis: { x0: v.x0 * a, y0: v.y0 * a, x1: v.x1 * a, y1: v.y1 * a } };
}

$("#b-shutter").onclick = () => takePhoto(state.prev);
$("#b-cam-back").onclick = () => show("pilih");
$("#b-torch").onclick = async () => {
  const on = !$("#b-torch").classList.contains("on");
  try { await state.track.applyConstraints({ advanced: [{ torch: on }] }); $("#b-torch").classList.toggle("on", on); }
  catch (e) { toast("Senter tidak bisa dinyalakan di HP ini.", true); }
};
video.addEventListener("click", async () => {      // ketuk layar untuk fokus ulang
  try { await state.track?.applyConstraints({ advanced: [{ focusMode: "single-shot" }] }); } catch (e) { /* abaikan */ }
});

/** Potongan bingkai (plus sedikit margin untuk garis tepi kiri) dari frame video resolusi penuh,
 *  sebagai JPEG. Ini persis gambar yang dilihat & dinilai di layar, dengan LJK memenuhi gambar. */
function frameBlob() {
  const L = frameLayout(), v = L.video, vw = video.videoWidth, vh = video.videoHeight;
  const m = (v.x1 - v.x0) * 0.07;
  const x0 = Math.max(0, Math.round(v.x0 - m)), y0 = Math.max(0, Math.round(v.y0 - m));
  const x1 = Math.min(vw, Math.round(v.x1 + m)), y1 = Math.min(vh, Math.round(v.y1 + m));
  const c = document.createElement("canvas");
  c.width = x1 - x0; c.height = y1 - y0;
  c.getContext("2d").drawImage(video, x0, y0, c.width, c.height, 0, 0, c.width, c.height);
  return new Promise(res => c.toBlob(res, "image/jpeg", 0.95));
}

/** Nilai foto (hasil jepretan / galeri) dengan ambang ketajaman ketat untuk foto. Foto dianalisis
 *  pada lebar 960 px: foto kamera jauh lebih besar & lebih lebar dari video, sehingga pada 480 px
 *  kotak sudutnya terlalu kecil untuk dikenali. */
async function analyzeBlob(blob) {
  const bmp = await createImageBitmap(blob);
  const r = measureSharpness(bmp, analyze(grab(bmp, work, 960), null, { minArea: 0.03 }), "foto");
  r.metrics.foto = `${bmp.width}x${bmp.height}`;
  bmp.close && bmp.close();
  return r;
}

async function takePhoto() {
  if (state.busy) return;
  state.busy = true;
  $("#b-shutter").disabled = true;
  const fl = document.createElement("div"); fl.className = "flash"; $("#v-kamera").append(fl); setTimeout(() => fl.remove(), 400);
  try {
    const blob = await frameBlob();
    let r;
    try { r = await analyzeBlob(blob); } catch (e) { r = null; }
    if (r) { r.metrics.sumber = "bingkai"; r.metrics.video = `${video.videoWidth}x${video.videoHeight}`; }
    // Potongan bingkai = gambar yang barusan dinilai siap di layar; cahaya & bayangan sudah lolos di sana.
    // Yang dipastikan ulang: semua syarat wajib dan ketajaman dengan ambang ketat (HP bisa bergerak saat memotret).
    const lolos = r && Object.values(r.gates).every(Boolean) && r.sub.tajam >= 0.6;
    if (!lolos) {
      const gagal = r && Object.entries(r.gates).find(([, v]) => !v);
      const why = !r ? "Foto tidak bisa dinilai." : !r.gates.sudut ? "4 kotak sudut tidak terlihat di foto."
        : gagal ? `${r.tip.title}.` : "Foto hasil jepretan buram.";
      toast(`${why} Foto tidak dikirim, ulangi dan tahan HP tetap diam. [${r?.metrics.foto || "-"} ${gagal ? gagal[0] : "tajam " + (r?.metrics.tajam ?? "-")}]`, true);
      return;
    }
    await send(blob, r);
  } catch (e) {
    toast(e.message || "Gagal mengambil foto.", true);
  } finally { state.busy = false; state.readySince = 0; }
}

// galeri: foto yang sudah ada di HP tetap dinilai dulu
$("#f-galeri").onchange = async e => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  state.busy = true;
  try {
    const r = await analyzeBlob(f);
    if (!r.ready) {
      const ok = await modal({ title: `Kualitas foto ${r.score}%`, submitText: "Tetap kirim", cancelText: "Batal",
        html: `<div class="alert warn">${icon("alert")}<div><b>${esc(r.tip.title)}</b><br>${esc(r.tip.text)}</div></div>
               <p class="muted small" style="margin:0">Foto dengan kualitas di bawah 90% lebih berisiko salah baca dan akan ditandai di pusat.</p>` });
      if (!ok) return;
    }
    await send(f, r);
  } catch (err) { toast(err.message, true); }
  finally { state.busy = false; }
};

function uploadForm(item) {
  const fd = new FormData();
  fd.append("lokasi_id", item.lokasi_id);
  fd.append("bidang_id", item.bidang_id);
  fd.append("skor_kualitas", item.skor);
  fd.append("metrik", JSON.stringify(item.metrik));
  fd.append("foto", item.blob, "ljk.jpg");
  return fd;
}

async function send(blob, r) {
  const item = { lokasi_id: state.sel.lokasi.id, bidang_id: state.sel.bidang.id, skor: r ? r.score : 0,
    metrik: r ? { ...r.metrics, gates: r.gates, perangkat: navigator.userAgent.slice(0, 160) } : {}, blob };
  busy(true, "Mengirim & membaca LJK…");
  stopCamera();
  try {
    const lb = await api("/api/scan/lembar", { method: "POST", form: uploadForm(item) });
    busy(false);
    if (lb.sudah_ada) toast("Foto ini sudah pernah dikirim; menampilkan hasil sebelumnya.");
    state.lembarFromHistory = false;
    openHasil(lb);
  } catch (e) {
    busy(false);
    if (e.status === 0) {
      await queue.add(item);
      toast("Tidak ada sinyal. Foto disimpan dan dikirim otomatis nanti.");
      refreshQueue();
      show("kamera");
    } else { toast(e.message, true); show("kamera"); }
  }
}

// ---------------------------------------------------------------- 3. hasil
function openHasil(lb) { state.lembar = lb; renderHasil(); show("hasil"); }

function renderHasil(mode = "") {
  const lb = state.lembar, el = $("#v-hasil");
  const locked = !!lb.ditarik_at;
  const head = (cls, ic, title, sub) => `<div class="res-head"><div class="res-ic ${cls}">${icon(ic)}</div><div class="grow"><h1>${title}</h1><div class="muted small">${sub}</div></div></div>`;
  const back = `<button class="btn ghost" id="h-back">${icon("chevronLeft")}Kembali</button>`;
  if (lb.status === "gagal") {
    el.innerHTML = `${head("err", "x", "LJK tidak terbaca", "Lembar #" + lb.id)}
      <div class="alert err">${icon("alert")}<div>${esc(lb.error || "Foto tidak bisa diluruskan.")}</div></div>
      <p class="muted" style="margin:0">Foto ulang dengan cahaya cukup dan pastikan 4 kotak hitam di sudut kertas terlihat.</p>
      <div class="actions"><button class="btn primary big" id="h-retake">${icon("camera")}Foto ulang</button>${back}</div>`;
    $("#h-retake").onclick = () => removeAndRetake(lb, false);
    $("#h-back").onclick = () => show("riwayat");
    return;
  }
  const jml = lb.bidang?.jumlah_soal || 0;
  const hb = lb.hasil_baca || {};
  const ragu = (hb.issues || []).length;
  const notTerdaftar = (lb.catatan || []).some(c => c.includes("tidak ada di daftar peserta"));
  const cls = lb.catatan.length ? "warn" : "ok";
  let html = head(cls, lb.catatan.length ? "alert" : "check", "Periksa hasil baca",
    `Lembar #${lb.id} · ${esc(lb.bidang?.nama || "")} · ${statusBadge(lb)}`);
  if (lb.urls.kotak_nama) html += `<img class="crop" src="${fileUrl(lb.urls.kotak_nama)}" alt="Tulisan nama di LJK">`;
  html += `<div class="card pad"><dl class="kv">
      <dt>Nama</dt><dd class="big">${esc(lb.nama || "—")}</dd>
      <dt>Nomor</dt><dd class="big mono">${esc(lb.nomor || "—")}</dd>
      <dt>Kode naskah</dt><dd class="mono">${esc(lb.kode || "—")}</dd>
      <dt>Jawaban</dt><dd>${hb.terisi ?? 0} terisi${jml ? ` dari ${jml} soal` : ""}</dd></dl></div>
    <div class="metrics">${pctBadge(lb.skor_kualitas, "Kualitas foto")}${pctBadge(lb.keyakinan, "Keyakinan baca")}
      ${ragu ? `<span class="badge warn">${ragu} isian ragu</span>` : ""}</div>`;
  if (lb.catatan.length) html += `<div class="alert warn">${icon("alert")}<ul>${lb.catatan.map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>`;
  if (lb.peserta_baru) html += `<div class="alert info">${icon("userPlus")}<div>Diajukan sebagai peserta baru: <b>${esc(lb.peserta_baru.nama)}</b> (${esc(lb.peserta_baru.nomor)}) · ${lb.peserta_baru_status === "disetujui" ? "disetujui pusat" : "menunggu persetujuan pusat"}</div></div>`;
  if (lb.konfirmasi?.aksi) html += `<p class="muted small" style="margin:0">Dikonfirmasi ${esc(lb.konfirmasi.oleh || "")} · ${esc((lb.konfirmasi.waktu || "").replace("T", " "))}${lb.konfirmasi.catatan ? ` · "${esc(lb.konfirmasi.catatan)}"` : ""}</p>`;
  if (lb.urls.cek) html += `<button class="btn ghost" id="h-cek">${icon("image")}Lihat gambar hasil baca</button>`;

  if (locked) {
    html += `<div class="alert ok">${icon("check")}<div>Lembar ini sudah ditarik panitia pusat dan tidak bisa diubah.</div></div><div class="actions">${back}</div>`;
  } else if (mode === "perbaiki") {
    html += `<form class="card pad form-card" id="h-form">
      <h2>Perbaiki data</h2><p class="muted small" style="margin:0">Samakan dengan yang tertulis di LJK fisik.</p>
      <label class="field"><span>Nama</span><input class="input" name="nama" value="${esc(lb.nama)}" autocapitalize="characters"></label>
      <label class="field"><span>Nomor peserta</span><input class="input" name="nomor" value="${esc(lb.nomor)}" inputmode="numeric"></label>
      <label class="field"><span>Kode naskah</span><input class="input" name="kode" value="${esc(lb.kode)}" inputmode="numeric"></label>
      <label class="field"><span>Catatan untuk pusat (opsional)</span><input class="input" name="catatan" value="${esc(lb.konfirmasi?.catatan || "")}"></label>
      <div class="row"><button type="button" class="btn ghost" id="h-cancel">Batal</button><button class="btn primary grow">Simpan perbaikan</button></div></form>`;
  } else if (mode === "baru") {
    html += `<form class="card pad form-card" id="h-form">
      <h2>Peserta baru (daftar di tempat)</h2><p class="muted small" style="margin:0">Untuk peserta yang belum ada di daftar. Pusat akan menyetujuinya.</p>
      <label class="field"><span>Nomor peserta</span><input class="input" name="nomor" value="${esc(lb.nomor)}" inputmode="numeric" required></label>
      <label class="field"><span>Nama</span><input class="input" name="nama" value="${esc(lb.nama)}" autocapitalize="characters" required></label>
      <label class="field"><span>Sekolah</span><input class="input" name="sekolah"></label>
      <div class="row"><button type="button" class="btn ghost" id="h-cancel">Batal</button><button class="btn primary grow">Ajukan peserta baru</button></div></form>`;
  } else {
    html += `<div class="actions">
      <button class="btn primary big" id="h-ok">${icon("check")}Benar, lanjut scan</button>
      <div class="row"><button class="btn" id="h-fix">${icon("pencil")}Perbaiki data</button>
      <button class="btn ${notTerdaftar ? "primary" : ""}" id="h-new">${icon("userPlus")}Peserta baru</button></div>
      <button class="btn danger" id="h-del">${icon("trash")}Hapus & foto ulang</button>
      ${state.lembarFromHistory ? back : ""}</div>`;
  }
  el.innerHTML = html;
  $("#h-cek") && ($("#h-cek").onclick = () => modal({ title: "Gambar hasil baca", wide: true, submitText: "", cancelText: "Tutup",
    html: `<img src="${fileUrl(lb.urls.cek)}" style="width:100%;border-radius:10px" alt="Gambar hasil baca">` }));
  $("#h-back") && ($("#h-back").onclick = () => show("riwayat"));
  $("#h-ok") && ($("#h-ok").onclick = () => konfirmasi({ aksi: "benar" }, true));
  $("#h-fix") && ($("#h-fix").onclick = () => renderHasil("perbaiki"));
  $("#h-new") && ($("#h-new").onclick = () => renderHasil("baru"));
  $("#h-del") && ($("#h-del").onclick = () => removeAndRetake(lb, true));
  $("#h-cancel") && ($("#h-cancel").onclick = () => renderHasil());
  const f = $("#h-form");
  if (f) f.onsubmit = e => {
    e.preventDefault();
    if (mode === "perbaiki") konfirmasi({ aksi: "perbaiki", koreksi: { nama: f.nama.value, nomor: f.nomor.value, kode: f.kode.value }, catatan: f.catatan.value }, true);
    else {
      if (!f.nomor.value.trim() || !f.nama.value.trim()) { toast("Isi nomor dan nama peserta.", true); return; }
      konfirmasi({ aksi: "peserta_baru", peserta_baru: { nomor: f.nomor.value, nama: f.nama.value, sekolah: f.sekolah.value } }, true);
    }
  };
}

async function konfirmasi(body, next) {
  try {
    const lb = await api(`/api/scan/lembar/${state.lembar.id}/konfirmasi`, { method: "POST", body });
    state.lembar = lb;
    toast(lb.status === "dikonfirmasi" ? "Tersimpan. Siap scan lembar berikutnya." : "Tersimpan dan ditandai untuk dicek pusat.");
    refreshPending();
    if (next && !state.lembarFromHistory) show("kamera"); else renderHasil();
  } catch (e) { toast(e.message, true); }
}

async function removeAndRetake(lb, ask) {
  if (ask && !(await confirmBox("Hapus lembar", "Hapus hasil ini lalu foto ulang LJK yang sama?", "Hapus & foto ulang"))) return;
  try { await api(`/api/scan/lembar/${lb.id}`, { method: "DELETE" }); } catch (e) { toast(e.message, true); return; }
  state.lembarFromHistory = false;
  refreshPending();
  show("kamera");
}

// ---------------------------------------------------------------- 4. riwayat
async function openRiwayat() {
  if (!state.sel) { toast("Pilih kompetisi dulu."); return; }
  show("riwayat");
  $("#riwayat-ctx").textContent = `${state.sel.kompetisi.nama} · ${state.sel.lokasi.kota}`;
  const list = $("#riwayat-list");
  list.innerHTML = `<div class="empty"><div class="spin"></div></div>`;
  try {
    const rows = await api(`/api/scan/lembar?lokasi_id=${state.sel.lokasi.id}&limit=100`);
    const pending = rows.filter(r => r.status === "menunggu").length;
    list.innerHTML = (pending ? `<div class="alert warn">${icon("alert")}<div>${pending} lembar belum dikonfirmasi. Ketuk untuk memeriksa.</div></div>` : "") +
      (rows.length ? `<div class="card">${rows.map(r => `<div class="item" data-id="${r.id}">
        <div class="grow"><b>${esc(r.nama || "(tanpa nama)")}</b><span class="muted small mono">${esc(r.nomor || "—")} · ${esc(r.bidang?.nama || "")} · ${esc((r.dibuat || "").slice(11, 16))}</span></div>
        ${statusBadge(r)}</div>`).join("")}</div>`
        : `<div class="card empty">${icon("inbox")}<b>Belum ada kiriman</b><span>LJK yang Anda kirim akan muncul di sini.</span></div>`);
    list.querySelectorAll(".item").forEach(it => it.onclick = async () => {
      try { state.lembarFromHistory = true; openHasil(await api(`/api/scan/lembar/${it.dataset.id}`)); }
      catch (e) { toast(e.message, true); }
    });
    $("#pending-dot").hidden = !pending;
  } catch (e) { list.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; }
}
$("#b-riwayat").onclick = openRiwayat;
$("#b-riwayat-refresh").onclick = openRiwayat;
$("#b-riwayat-back").onclick = () => show(state.sel?.bidang ? "kamera" : "pilih");

async function refreshPending() {
  if (!state.sel) return;
  try {
    const rows = await api(`/api/scan/lembar?lokasi_id=${state.sel.lokasi.id}&limit=100`);
    $("#pending-dot").hidden = !rows.some(r => r.status === "menunggu");
  } catch (e) { /* abaikan */ }
}

// ---------------------------------------------------------------- antrean offline
async function refreshQueue() {
  const n = await queue.count();
  $("#queue-bar").hidden = !n;
  $("#queue-text").textContent = `${n} foto menunggu sinyal untuk dikirim`;
}
async function flushQueue() {
  const sent = await flush(item => api("/api/scan/lembar", { method: "POST", form: uploadForm(item) }),
    err => { refreshQueue(); if (err) toast(`Satu foto ditolak server: ${err.message}`, true); });
  if (sent) { toast(`${sent} foto dari antrean terkirim. Periksa hasilnya di Riwayat.`); refreshPending(); }
  refreshQueue();
}
$("#b-flush").onclick = flushQueue;
addEventListener("online", flushQueue);
setInterval(flushQueue, 30000);

// ---------------------------------------------------------------- mulai
if (user) {
  loadAkses().then(() => { refreshPending(); });
  refreshQueue().then(flushQueue);
}
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopCamera();
  else if (state.view === "kamera") startCamera();
});
