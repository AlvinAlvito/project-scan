// Panel superadmin: dashboard, kompetisi (lokasi/bidang/peserta), lembar, persetujuan peserta baru, akun.
import { api, esc, fileUrl, icon, logout, modal, confirmBox, toast, requireLogin, statusBadge, pctBadge,
  toggleTheme, currentTheme, STATUS, searchSelect, fmtDate, download } from "/static/js/common.js";

const $ = s => document.querySelector(s);
const page = $("#page");
const me = requireLogin("superadmin");
const KOMP_KEY = "ljk_admin_komp";
let kompetisiCache = null;

document.querySelectorAll("[data-icon]").forEach(el => { el.innerHTML = icon(el.dataset.icon) + el.innerHTML; });
const paintTheme = () => { $("#b-theme").innerHTML = icon(currentTheme() === "dark" ? "sun" : "moon") + (currentTheme() === "dark" ? "Tema terang" : "Tema gelap"); };
paintTheme();
$("#b-theme").onclick = () => { toggleTheme(); paintTheme(); };
$("#b-logout").onclick = async () => { if (await confirmBox("Keluar", "Keluar dari panel admin?", "Keluar")) logout(); };
$("#b-menu").onclick = () => $("#side").classList.toggle("open");
$("#b-pw").onclick = () => modal({
  title: "Ganti kata sandi", html: `<label class="field"><span>Kata sandi lama</span><input class="input" type="password" name="lama" autocomplete="current-password"></label>
    <label class="field"><span>Kata sandi baru (min. 6 karakter)</span><input class="input" type="password" name="baru" autocomplete="new-password"></label>`,
  onSubmit: async f => { await api("/api/auth/password", { method: "POST", body: { lama: f.lama.value, baru: f.baru.value } }); toast("Kata sandi diganti."); },
});

// ---------------------------------------------------------------- util
const fmtNum = n => (n ?? 0).toLocaleString("id-ID");
const field = (label, name, value = "", attrs = "") =>
  `<label class="field"><span>${esc(label)}</span><input class="input" name="${name}" value="${esc(value)}" ${attrs}></label>`;
function loading() { page.innerHTML = `<div class="empty"><div class="spin"></div></div>`; }
function fail(e) { page.innerHTML = `<div class="alert err">${icon("alert")}<div>${esc(e.message)}</div></div>`; }
async function kompetisiList(force = false) {
  if (!kompetisiCache || force) kompetisiCache = await api("/api/admin/kompetisi");
  return kompetisiCache;
}
function savedKomp(list) {
  let id = null;
  try { id = +localStorage.getItem(KOMP_KEY); } catch (e) { /* abaikan */ }
  return list.find(k => k.id === id) || list.find(k => k.status === "aktif") || list[0];
}
function rememberKomp(id) { try { localStorage.setItem(KOMP_KEY, id); } catch (e) { /* abaikan */ } }
function kompSelect(list, cur) {
  return `<select class="input" id="sel-komp" aria-label="Kompetisi">${list.map(k =>
    `<option value="${k.id}" ${k.id === cur?.id ? "selected" : ""}>${esc(k.nama)}${k.status !== "aktif" ? " (selesai)" : ""}</option>`).join("")}</select>`;
}
function noKompetisi() {
  page.innerHTML = `<div class="card empty">${icon("trophy")}<b>Belum ada kompetisi</b><span>Buat kompetisi dulu, lalu tambahkan lokasi dan bidangnya.</span>
    <a class="btn primary" href="#/kompetisi">${icon("plus")}Buat kompetisi</a></div>`;
}
async function updatePbCount() {
  try {
    const list = await kompetisiList();
    let n = 0;
    for (const k of list.filter(k => k.status === "aktif")) n += (await api(`/api/admin/dashboard/${k.id}`)).persetujuan;
    $("#nav-pb").hidden = !n; $("#nav-pb").textContent = n;
  } catch (e) { /* abaikan */ }
}

// ---------------------------------------------------------------- router
const routes = { dashboard, kompetisi, bidang: masterBidang, lembar, persetujuan, akun };
async function route() {
  const [, name = "dashboard", arg] = location.hash.split("/");
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("on", a.dataset.r === name));
  $("#side").classList.remove("open");
  loading();
  try { await (routes[name] || dashboard)(arg); } catch (e) { fail(e); }
}
addEventListener("hashchange", route);

// ---------------------------------------------------------------- dashboard
async function dashboard() {
  const list = await kompetisiList(true);
  if (!list.length) return noKompetisi();
  const k = savedKomp(list);
  const d = await api(`/api/admin/dashboard/${k.id}`);
  const sum = key => d.lokasi.reduce((a, r) => a + (r[key] || 0), 0);
  const target = sum("target"), terkirim = sum("terkirim");
  page.innerHTML = `
    <div class="page-head"><div><h1>Dashboard</h1><p class="muted">Kelengkapan kiriman LJK per lokasi.</p></div>
      <div class="toolbar">${kompSelect(list, k)}<button class="btn" id="b-ref">${icon("refresh")}Muat ulang</button></div></div>
    <div class="stats">
      <div class="card stat"><b>${fmtNum(terkirim)}${target ? `<span class="muted" style="font-size:15px"> / ${fmtNum(target)}</span>` : ""}</b><span>Lembar terkirim</span></div>
      <div class="card stat warn"><b>${fmtNum(sum("menunggu"))}</b><span>Menunggu konfirmasi admin</span></div>
      <div class="card stat ok"><b>${fmtNum(sum("dikonfirmasi"))}</b><span>Dikonfirmasi</span></div>
      <div class="card stat info"><b>${fmtNum(sum("ditandai"))}</b><span>Ditandai</span></div>
      <div class="card stat err"><b>${fmtNum(sum("gagal"))}</b><span>Gagal dibaca</span></div>
      <div class="card stat"><b>${fmtNum(sum("ditarik"))}</b><span>Sudah ditarik desktop</span></div>
    </div>
    ${d.persetujuan ? `<a class="alert warn" href="#/persetujuan" style="text-decoration:none">${icon("userPlus")}<div><b>${d.persetujuan} peserta baru</b> menunggu persetujuan Anda.</div></a>` : ""}
    ${d.lokasi.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Lokasi</th><th>Admin</th><th>Progres</th>
      <th class="num">Terkirim</th><th class="num">Menunggu</th><th class="num">Dikonfirmasi</th><th class="num">Ditandai</th><th class="num">Gagal</th><th class="num">Ditarik</th><th>Terakhir</th></tr></thead><tbody>
      ${d.lokasi.map(r => {
        const pct = r.target ? Math.min(100, Math.round(r.terkirim / r.target * 100)) : 0;
        return `<tr class="click" data-l="${r.lokasi.id}"><td><b>${esc(r.lokasi.kota)}</b></td>
          <td class="small">${r.admin.length ? esc(r.admin.join(", ")) : `<span class="badge warn">belum ada</span>`}</td>
          <td><div class="row" style="flex-wrap:nowrap"><div class="bar grow"><i style="width:${pct}%"></i></div><span class="small muted">${r.target ? pct + "%" : "—"}</span></div></td>
          <td class="num">${r.terkirim}${r.target ? `<span class="muted"> / ${r.target}</span>` : ""}</td>
          <td class="num">${r.menunggu || ""}</td><td class="num">${r.dikonfirmasi || ""}</td><td class="num">${r.ditandai || ""}</td>
          <td class="num">${r.gagal || ""}</td><td class="num">${r.ditarik || ""}</td><td class="small muted">${esc(r.terakhir || "—")}</td></tr>`;
      }).join("")}</tbody></table></div>`
      : `<div class="card empty">${icon("mapPin")}<b>Belum ada lokasi</b><span>Tambahkan lokasi di halaman kompetisi.</span><a class="btn" href="#/kompetisi/${k.id}">Buka kompetisi</a></div>`}
    <p class="muted small">Target = target lembar di lokasi, atau jumlah peserta terdaftar bila target kosong.</p>`;
  $("#sel-komp").onchange = e => { rememberKomp(e.target.value); route(); };
  $("#b-ref").onclick = route;
  page.querySelectorAll("tr[data-l]").forEach(tr => tr.onclick = () => { location.hash = `#/lembar/l${tr.dataset.l}`; });
  updatePbCount();
}

// ---------------------------------------------------------------- kompetisi
async function kompetisi(arg) {
  if (arg) return kompetisiDetail(+arg);
  const list = await kompetisiList(true);
  page.innerHTML = `<div class="page-head"><div><h1>Kompetisi</h1><p class="muted">Setiap kompetisi punya lokasi (kota), bidang, dan daftar peserta.</p></div>
      <button class="btn primary" id="b-new">${icon("plus")}Kompetisi baru</button></div>
    ${list.length ? `<div class="kgrid">${list.map(k => `<div class="card kcard" data-id="${k.id}">
      <div class="row"><b class="grow" style="font-size:16px">${esc(k.nama)}</b>${k.status === "aktif" ? `<span class="badge ok">Aktif</span>` : `<span class="badge">Selesai</span>`}</div>
      <div class="meta"><span>${icon("mapPin", "sm")}${k.lokasi.length} lokasi</span><span>${icon("sheet", "sm")}${k.bidang.length} bidang</span><span>${icon("inbox", "sm")}${fmtNum(k.jumlah_lembar)} lembar</span></div>
      <span class="muted small">${esc(fmtDate(k.tanggal) || "Tanggal belum diisi")}</span></div>`).join("")}</div>`
      : `<div class="card empty">${icon("trophy")}<b>Belum ada kompetisi</b><span>Klik "Kompetisi baru" untuk mulai.</span></div>`}`;
  $("#b-new").onclick = () => editKompetisi();
  page.querySelectorAll(".kcard").forEach(c => c.onclick = () => { location.hash = `#/kompetisi/${c.dataset.id}`; });
}

function editKompetisi(k) {
  return modal({
    title: k ? "Ubah kompetisi" : "Kompetisi baru",
    html: field("Nama kompetisi", "nama", k?.nama, 'required placeholder="FSN 2026 Provinsi"') +
      field("Tanggal pelaksanaan", "tanggal", /^\d{4}-\d{2}-\d{2}$/.test(k?.tanggal || "") ? k.tanggal : "", 'type="date"') +
      (k?.tanggal && !/^\d{4}-\d{2}-\d{2}$/.test(k.tanggal) ? `<p class="hint">Tanggal lama: "${esc(k.tanggal)}". Pilih ulang tanggalnya.</p>` : "") +
      `<label class="field"><span>Status</span><select class="input" name="status">
        <option value="aktif" ${k?.status !== "selesai" ? "selected" : ""}>Aktif (admin daerah bisa mengirim)</option>
        <option value="selesai" ${k?.status === "selesai" ? "selected" : ""}>Selesai (kiriman ditutup)</option></select></label>`,
    onSubmit: async f => {
      const body = { nama: f.nama.value.trim(), tanggal: f.tanggal.value || (k?.tanggal ?? ""), status: f.status.value };
      if (!body.nama) { toast("Nama kompetisi wajib diisi.", true); return false; }
      const r = await api(k ? `/api/admin/kompetisi/${k.id}` : "/api/admin/kompetisi", { method: k ? "PUT" : "POST", body });
      kompetisiCache = null;
      toast("Kompetisi tersimpan.");
      if (!k) location.hash = `#/kompetisi/${r.id}`; else route();
    },
  });
}

let detailTab = "lokasi";
async function kompetisiDetail(id) {
  const k = await api(`/api/admin/kompetisi/${id}`);
  rememberKomp(id);
  page.innerHTML = `<div class="page-head"><div><a href="#/kompetisi" class="small">${icon("chevronLeft", "sm")}Semua kompetisi</a>
      <h1 style="margin-top:6px">${esc(k.nama)}</h1><p class="muted">${esc(fmtDate(k.tanggal) || "Tanggal belum diisi")} · ${k.status === "aktif" ? "Aktif" : "Selesai"}</p></div>
      <div class="toolbar"><button class="btn" id="b-edit">${icon("pencil")}Ubah</button><button class="btn danger" id="b-del">${icon("trash")}Hapus</button></div></div>
    <div class="tabs" role="tablist">${[["lokasi", "mapPin", `Lokasi (${k.lokasi.length})`], ["bidang", "sheet", `Bidang (${k.bidang.length})`], ["peserta", "users", "Peserta"]]
      .map(([t, ic, l]) => `<button class="tab ${detailTab === t ? "on" : ""}" data-t="${t}">${icon(ic)}${l}</button>`).join("")}</div>
    <div id="tab-body"></div>`;
  $("#b-edit").onclick = () => editKompetisi(k);
  $("#b-del").onclick = async () => {
    if (!(await confirmBox("Hapus kompetisi", `Hapus "${k.nama}" beserta lokasi, bidang, dan pesertanya?`))) return;
    try { await api(`/api/admin/kompetisi/${id}`, { method: "DELETE" }); kompetisiCache = null; toast("Kompetisi dihapus."); location.hash = "#/kompetisi"; }
    catch (e) { toast(e.message, true); }
  };
  page.querySelectorAll(".tab").forEach(t => t.onclick = () => { detailTab = t.dataset.t; kompetisiDetail(id); });
  const body = $("#tab-body");
  if (detailTab === "lokasi") renderLokasi(k, body);
  else if (detailTab === "bidang") renderBidang(k, body);
  else renderPeserta(k, body);
}

function renderLokasi(k, el) {
  el.innerHTML = `<div class="toolbar" style="justify-content:space-between"><p class="muted small" style="margin:0">Admin daerah diberi akses per lokasi di halaman Akun & akses.</p>
      <button class="btn primary" id="b-add">${icon("plus")}Tambah lokasi</button></div>
    ${k.lokasi.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Kota / lokasi</th><th class="num">Target lembar</th><th></th></tr></thead><tbody>
      ${k.lokasi.map(l => `<tr><td><b>${esc(l.kota)}</b></td><td class="num">${l.target_lembar || "—"}</td>
        <td class="actions"><button class="btn ghost icon-only" data-e="${l.id}" aria-label="Ubah">${icon("pencil")}</button>
        <button class="btn ghost icon-only danger" data-d="${l.id}" aria-label="Hapus">${icon("trash")}</button></td></tr>`).join("")}</tbody></table></div>`
      : `<div class="card empty">${icon("mapPin")}<b>Belum ada lokasi</b><span>Tambahkan kota tempat kompetisi berlangsung.</span></div>`}`;
  const edit = l => modal({
    title: l ? "Ubah lokasi" : "Tambah lokasi",
    html: field("Kota / nama lokasi", "kota", l?.kota, 'required placeholder="Padang"') +
      field("Target lembar (opsional)", "target", l?.target_lembar || "", 'type="number" min="0" inputmode="numeric"'),
    onSubmit: async f => {
      const body = { kota: f.kota.value.trim(), target_lembar: +f.target.value || 0 };
      if (!body.kota) { toast("Nama lokasi wajib diisi.", true); return false; }
      await api(l ? `/api/admin/lokasi/${l.id}` : `/api/admin/kompetisi/${k.id}/lokasi`, { method: l ? "PUT" : "POST", body });
      toast("Lokasi tersimpan."); kompetisiDetail(k.id);
    },
  });
  $("#b-add").onclick = () => edit();
  el.querySelectorAll("[data-e]").forEach(b => b.onclick = () => edit(k.lokasi.find(l => l.id === +b.dataset.e)));
  el.querySelectorAll("[data-d]").forEach(b => b.onclick = async () => {
    const l = k.lokasi.find(x => x.id === +b.dataset.d);
    if (!(await confirmBox("Hapus lokasi", `Hapus lokasi ${l.kota}?`))) return;
    try { await api(`/api/admin/lokasi/${l.id}`, { method: "DELETE" }); toast("Lokasi dihapus."); kompetisiDetail(k.id); } catch (e) { toast(e.message, true); }
  });
}

function renderBidang(k, el) {
  el.innerHTML = `<div class="toolbar" style="justify-content:space-between"><p class="muted small" style="margin:0">Kunci jawaban tidak disimpan di server; kunci tetap diisi di aplikasi desktop.</p>
      <button class="btn primary" id="b-add">${icon("plus")}Tambah bidang</button></div>
    ${k.bidang.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Kode naskah</th><th>Bidang</th><th class="num">Jumlah soal</th><th></th></tr></thead><tbody>
      ${k.bidang.map(b => `<tr><td class="mono"><b>${esc(b.kode_naskah)}</b></td><td>${esc(b.nama)}</td><td class="num">${b.jumlah_soal}</td>
        <td class="actions"><button class="btn ghost icon-only" data-e="${b.id}" aria-label="Ubah">${icon("pencil")}</button>
        <button class="btn ghost icon-only danger" data-d="${b.id}" aria-label="Hapus">${icon("trash")}</button></td></tr>`).join("")}</tbody></table></div>`
      : `<div class="card empty">${icon("sheet")}<b>Belum ada bidang</b><span>Tambahkan kode naskah dan nama bidang yang diujikan.</span></div>`}`;
  const edit = async b => {
    const master = await api("/api/admin/master-bidang");
    const items = master.map(m => ({ id: m.id, label: m.nama, sub: [m.kode_naskah && `kode ${m.kode_naskah}`, m.jumlah_soal && `${m.jumlah_soal} soal`].filter(Boolean).join(" · "), m }));
    const cur = b ? (items.find(i => i.label === b.nama) || { id: 0, label: b.nama }) : null;
    return modal({
    title: b ? "Ubah bidang" : "Tambah bidang",
    html: `<div class="field"><span>Bidang</span><div id="ss-bidang"></div>
        <p class="hint">Ketik untuk mencari. Belum ada? Pilih "Tambah ke master" atau kelola di menu <a href="#/bidang">Master bidang</a>.</p></div>
      <div class="field-row">${field("Kode naskah", "kode", b?.kode_naskah, 'required inputmode="numeric" placeholder="301"')}
      ${field("Jumlah soal", "jumlah", b?.jumlah_soal || "", 'type="number" min="1" max="180" required')}</div>`,
    onOpen: f => searchSelect(f.querySelector("#ss-bidang"), {
      items, value: cur, placeholder: "Cari bidang, mis. matematika",
      createLabel: q => `Tambah "${q}" ke master bidang`,
      onCreate: async q => { const m = await api("/api/admin/master-bidang", { method: "POST", body: { nama: q } }); toast(`"${m.nama}" ditambahkan ke master.`); return { id: m.id, label: m.nama, m }; },
      onPick: it => {
        if (it.m?.kode_naskah && (!b || !f.kode.value)) f.kode.value = it.m.kode_naskah;
        if (it.m?.jumlah_soal && (!b || !f.jumlah.value)) f.jumlah.value = it.m.jumlah_soal;
        (f.kode.value ? f.jumlah : f.kode).focus();
      },
    }),
    onSubmit: async f => {
      const picked = f.querySelector("#ss-bidang").value;
      if (!picked) { toast("Pilih bidang dari daftar.", true); return false; }
      const body = { kode_naskah: f.kode.value.trim(), nama: picked.label, jumlah_soal: +f.jumlah.value };
      if (!body.kode_naskah || !body.nama || !(body.jumlah_soal >= 1 && body.jumlah_soal <= 180)) { toast("Isi kode naskah, nama, dan jumlah soal 1-180.", true); return false; }
      await api(b ? `/api/admin/bidang/${b.id}` : `/api/admin/kompetisi/${k.id}/bidang`, { method: b ? "PUT" : "POST", body });
      toast("Bidang tersimpan."); kompetisiDetail(k.id);
    },
  });
  };
  $("#b-add").onclick = () => edit();
  el.querySelectorAll("[data-e]").forEach(x => x.onclick = () => edit(k.bidang.find(b => b.id === +x.dataset.e)));
  el.querySelectorAll("[data-d]").forEach(x => x.onclick = async () => {
    const b = k.bidang.find(y => y.id === +x.dataset.d);
    if (!(await confirmBox("Hapus bidang", `Hapus bidang ${b.nama} (${b.kode_naskah})?`))) return;
    try { await api(`/api/admin/bidang/${b.id}`, { method: "DELETE" }); toast("Bidang dihapus."); kompetisiDetail(k.id); } catch (e) { toast(e.message, true); }
  });
}

async function renderPeserta(k, el, q = "", offset = 0) {
  const kota = Object.fromEntries(k.lokasi.map(l => [l.id, l.kota]));
  const r = await api(`/api/admin/kompetisi/${k.id}/peserta?q=${encodeURIComponent(q)}&limit=100&offset=${offset}`);
  el.innerHTML = `<div class="toolbar"><div class="row grow"><input class="input" id="q" placeholder="Cari nomor, nama, sekolah" value="${esc(q)}" style="width:100%;max-width:340px"></div>
      <button class="btn" id="b-tpl">${icon("download")}Unduh template</button>
      <button class="btn" id="b-imp">${icon("upload")}Impor Excel/CSV</button><button class="btn primary" id="b-add">${icon("plus")}Tambah peserta</button></div>
    <p class="muted small" style="margin:0">${fmtNum(r.total)} peserta${q ? " cocok" : ""}.</p>
    ${r.items.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Nomor</th><th>Nama</th><th>Sekolah</th><th>Lokasi</th><th></th></tr></thead><tbody>
      ${r.items.map(p => `<tr><td class="mono">${esc(p.nomor)}</td><td><b>${esc(p.nama)}</b>${p.daftar_di_tempat ? ` <span class="badge info">daftar di tempat</span>` : ""}</td>
        <td>${esc(p.sekolah)}</td><td>${esc(kota[p.lokasi_id] || "—")}</td>
        <td class="actions"><button class="btn ghost icon-only" data-e="${p.id}" aria-label="Ubah">${icon("pencil")}</button>
        <button class="btn ghost icon-only danger" data-d="${p.id}" aria-label="Hapus">${icon("trash")}</button></td></tr>`).join("")}</tbody></table></div>
      <div class="pager">${offset ? `<button class="btn" id="pg-prev">${icon("chevronLeft")}Sebelumnya</button>` : ""}
        ${offset + 100 < r.total ? `<button class="btn" id="pg-next">Berikutnya${icon("chevronRight")}</button>` : ""}</div>`
      : `<div class="card empty">${icon("users")}<b>${q ? "Tidak ada yang cocok" : "Belum ada peserta"}</b><span>Impor daftar peserta dari Excel/CSV dengan kolom nomor, nama, sekolah, lokasi.</span></div>`}`;
  let t;
  $("#q").oninput = e => { clearTimeout(t); t = setTimeout(() => renderPeserta(k, el, e.target.value.trim(), 0).then(() => { const i = $("#q"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }), 350); };
  $("#pg-prev") && ($("#pg-prev").onclick = () => renderPeserta(k, el, q, offset - 100));
  $("#pg-next") && ($("#pg-next").onclick = () => renderPeserta(k, el, q, offset + 100));
  const lokOpts = sel => `<option value="">—</option>` + k.lokasi.map(l => `<option value="${l.id}" ${l.id === sel ? "selected" : ""}>${esc(l.kota)}</option>`).join("");
  const edit = p => modal({
    title: p ? "Ubah peserta" : "Tambah peserta",
    html: field("Nomor peserta", "nomor", p?.nomor, 'required inputmode="numeric"') + field("Nama", "nama", p?.nama, "required") +
      field("Sekolah", "sekolah", p?.sekolah) + `<label class="field"><span>Lokasi</span><select class="input" name="lokasi">${lokOpts(p?.lokasi_id)}</select></label>`,
    onSubmit: async f => {
      const body = { nomor: f.nomor.value.trim(), nama: f.nama.value.trim(), sekolah: f.sekolah.value.trim(), lokasi_id: f.lokasi.value ? +f.lokasi.value : null };
      if (!body.nomor || !body.nama) { toast("Nomor dan nama wajib diisi.", true); return false; }
      await api(p ? `/api/admin/peserta/${p.id}` : `/api/admin/kompetisi/${k.id}/peserta`, { method: p ? "PUT" : "POST", body });
      toast("Peserta tersimpan."); renderPeserta(k, el, q, offset);
    },
  });
  $("#b-add").onclick = () => edit();
  el.querySelectorAll("[data-e]").forEach(b => b.onclick = () => edit(r.items.find(p => p.id === +b.dataset.e)));
  el.querySelectorAll("[data-d]").forEach(b => b.onclick = async () => {
    const p = r.items.find(x => x.id === +b.dataset.d);
    if (!(await confirmBox("Hapus peserta", `Hapus ${p.nama} (${p.nomor})?`))) return;
    try { await api(`/api/admin/peserta/${p.id}`, { method: "DELETE" }); toast("Peserta dihapus."); renderPeserta(k, el, q, offset); } catch (e) { toast(e.message, true); }
  });
  $("#b-tpl").onclick = async () => {
    try { await download(`/api/admin/kompetisi/${k.id}/peserta/template`, "Template Peserta.xlsx"); toast("Template diunduh. Isi lalu impor kembali."); }
    catch (e) { toast(e.message, true); }
  };
  $("#b-imp").onclick = () => modal({
    title: "Impor daftar peserta", submitText: "Impor",
    html: `<p class="muted small" style="margin:0">File .xlsx atau .csv. Baris pertama berisi judul kolom: <b>nomor</b>, <b>nama</b>, <b>sekolah</b> (opsional), <b>lokasi</b> atau <b>kota</b> (opsional, harus sama dengan nama lokasi). Nomor yang sudah ada akan diperbarui.
        Paling aman pakai <a href="#" id="tpl-link">template dari sistem</a>.</p>
      <input class="input" type="file" name="file" accept=".xlsx,.csv,text/csv">`,
    onOpen: f => { f.querySelector("#tpl-link").onclick = e => { e.preventDefault(); $("#b-tpl").click(); }; },
    onSubmit: async f => {
      if (!f.file.files[0]) { toast("Pilih file dulu.", true); return false; }
      const fd = new FormData(); fd.append("file", f.file.files[0]);
      const res = await api(`/api/admin/kompetisi/${k.id}/peserta/import`, { method: "POST", form: fd });
      toast(`${res.baru} peserta baru, ${res.diperbarui} diperbarui${res.dilewati ? `, ${res.dilewati} baris dilewati` : ""}.`);
      if (res.lokasi_tidak_dikenal.length) toast(`Lokasi tidak dikenal: ${res.lokasi_tidak_dikenal.join(", ")}. Tambahkan lokasinya lalu impor ulang.`, true);
      renderPeserta(k, el);
    },
  });
}

// ---------------------------------------------------------------- master bidang
async function masterBidang() {
  const list = await api("/api/admin/master-bidang");
  page.innerHTML = `<div class="page-head"><div><h1>Master bidang</h1><p class="muted">Daftar bidang baku. Saat menambah bidang ke kompetisi cukup pilih dari sini.</p></div>
      <button class="btn primary" id="b-add">${icon("plus")}Tambah bidang</button></div>
    <div class="toolbar"><input class="input" id="q" placeholder="Cari bidang" style="width:100%;max-width:340px"></div>
    ${list.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Nama bidang</th><th>Kode naskah bawaan</th><th class="num">Jumlah soal bawaan</th><th class="num">Dipakai</th><th></th></tr></thead><tbody id="rows">
      ${list.map(m => `<tr data-n="${esc(m.nama.toLowerCase())}"><td><b>${esc(m.nama)}</b></td><td class="mono">${esc(m.kode_naskah || "—")}</td>
        <td class="num">${m.jumlah_soal || "—"}</td><td class="num">${m.dipakai ? `${m.dipakai} kompetisi` : `<span class="muted">—</span>`}</td>
        <td class="actions"><button class="btn ghost icon-only" data-e="${m.id}" aria-label="Ubah">${icon("pencil")}</button>
        <button class="btn ghost icon-only danger" data-d="${m.id}" aria-label="Hapus">${icon("trash")}</button></td></tr>`).join("")}</tbody></table></div>`
      : `<div class="card empty">${icon("book")}<b>Master bidang masih kosong</b><span>Tambahkan bidang yang biasa diujikan, mis. Matematika SMA, Fisika SMP.</span></div>`}
    <p class="hint">Kode naskah dan jumlah soal di sini hanya nilai awal; tetap bisa diubah per kompetisi. Mengubah atau menghapus master tidak mengubah kompetisi yang sudah ada.</p>`;
  const q = $("#q");
  q.oninput = () => { const v = q.value.trim().toLowerCase(); page.querySelectorAll("#rows tr").forEach(tr => { tr.hidden = !tr.dataset.n.includes(v); }); };
  const edit = m => modal({
    title: m ? "Ubah bidang" : "Tambah bidang",
    html: field("Nama bidang", "nama", m?.nama, 'required placeholder="Matematika SMA"') +
      `<div class="field-row">${field("Kode naskah bawaan (opsional)", "kode", m?.kode_naskah, 'inputmode="numeric" placeholder="301"')}
      ${field("Jumlah soal bawaan (opsional)", "jumlah", m?.jumlah_soal || "", 'type="number" min="0" max="180"')}</div>`,
    onSubmit: async f => {
      const body = { nama: f.nama.value.trim(), kode_naskah: f.kode.value.trim(), jumlah_soal: +f.jumlah.value || 0 };
      if (!body.nama) { toast("Nama bidang wajib diisi.", true); return false; }
      await api(m ? `/api/admin/master-bidang/${m.id}` : "/api/admin/master-bidang", { method: m ? "PUT" : "POST", body });
      toast("Bidang tersimpan."); route();
    },
  });
  $("#b-add").onclick = () => edit();
  page.querySelectorAll("[data-e]").forEach(b => b.onclick = () => edit(list.find(m => m.id === +b.dataset.e)));
  page.querySelectorAll("[data-d]").forEach(b => b.onclick = async () => {
    const m = list.find(x => x.id === +b.dataset.d);
    if (!(await confirmBox("Hapus bidang", `Hapus "${m.nama}" dari master? Kompetisi yang sudah memakainya tidak berubah.`))) return;
    try { await api(`/api/admin/master-bidang/${m.id}`, { method: "DELETE" }); toast("Bidang dihapus dari master."); route(); } catch (e) { toast(e.message, true); }
  });
}

// ---------------------------------------------------------------- lembar
const lembarFilter = { status: "", lokasi: "", q: "", offset: 0 };
async function lembar(arg) {
  const list = await kompetisiList();
  if (!list.length) return noKompetisi();
  const k = savedKomp(list);
  if (arg && arg.startsWith("l")) { lembarFilter.lokasi = arg.slice(1); lembarFilter.offset = 0; }
  const f = lembarFilter;
  const qs = new URLSearchParams({ kompetisi_id: k.id, limit: 50, offset: f.offset });
  if (f.status) qs.set("status", f.status);
  if (f.lokasi) qs.set("lokasi_id", f.lokasi);
  if (f.q) qs.set("q", f.q);
  const r = await api(`/api/admin/lembar?${qs}`);
  page.innerHTML = `<div class="page-head"><div><h1>Lembar masuk</h1><p class="muted">Semua LJK yang dikirim admin daerah.</p></div></div>
    <div class="toolbar">${kompSelect(list, k)}
      <select class="input" id="f-lok"><option value="">Semua lokasi</option>${k.lokasi.map(l => `<option value="${l.id}" ${String(l.id) === String(f.lokasi) ? "selected" : ""}>${esc(l.kota)}</option>`).join("")}</select>
      <select class="input" id="f-status"><option value="">Semua status</option>${Object.entries(STATUS).map(([v, [t]]) => `<option value="${v}" ${f.status === v ? "selected" : ""}>${t}</option>`).join("")}
        <option value="ditarik" ${f.status === "ditarik" ? "selected" : ""}>Sudah ditarik</option></select>
      <input class="input" id="f-q" placeholder="Cari nomor / nama" value="${esc(f.q)}"></div>
    <p class="muted small" style="margin:0">${fmtNum(r.total)} lembar.</p>
    ${r.items.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>#</th><th>Peserta</th><th>Bidang</th><th>Lokasi</th><th>Status</th><th>Kualitas</th><th>Keyakinan</th><th>Catatan</th><th>Dikirim</th></tr></thead><tbody>
      ${r.items.map(lb => `<tr class="click" data-id="${lb.id}"><td class="mono muted">${lb.id}</td>
        <td><b>${esc(lb.nama || "—")}</b><div class="mono small muted">${esc(lb.nomor || "")}</div></td>
        <td>${esc(lb.bidang?.nama || "")} <span class="mono small muted">${esc(lb.kode)}</span></td><td>${esc(lb.kota)}</td>
        <td>${statusBadge(lb)}</td><td>${pctBadge(lb.skor_kualitas, "")}</td><td>${pctBadge(lb.keyakinan, "")}</td>
        <td class="small">${lb.catatan.length ? `<span class="badge warn">${lb.catatan.length}</span>` : ""}</td>
        <td class="small muted">${esc(lb.dibuat || "")}<div>${esc(lb.uploader)}</div></td></tr>`).join("")}</tbody></table></div>
      <div class="pager">${f.offset ? `<button class="btn" id="pg-prev">${icon("chevronLeft")}Sebelumnya</button>` : ""}${f.offset + 50 < r.total ? `<button class="btn" id="pg-next">Berikutnya${icon("chevronRight")}</button>` : ""}</div>`
      : `<div class="card empty">${icon("inbox")}<b>Belum ada lembar</b><span>Lembar yang dikirim admin daerah akan muncul di sini.</span></div>`}`;
  $("#sel-komp").onchange = e => { rememberKomp(e.target.value); f.lokasi = ""; f.offset = 0; location.hash = "#/lembar"; route(); };
  $("#f-lok").onchange = e => { f.lokasi = e.target.value; f.offset = 0; route(); };
  $("#f-status").onchange = e => { f.status = e.target.value; f.offset = 0; route(); };
  let t; $("#f-q").oninput = e => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim(); f.offset = 0; route(); }, 400); };
  $("#pg-prev") && ($("#pg-prev").onclick = () => { f.offset -= 50; route(); });
  $("#pg-next") && ($("#pg-next").onclick = () => { f.offset += 50; route(); });
  page.querySelectorAll("tr[data-id]").forEach(tr => tr.onclick = () => lembarDetail(+tr.dataset.id));
}

async function lembarDetail(id, after) {
  const lb = await api(`/api/admin/lembar/${id}`);
  const ks = lb.kualitas_server || {}, m = lb.metrik || {};
  const issues = lb.hasil_baca?.issues || [];
  const html = `<div class="detail">
      <div>${lb.urls.cek ? `<a href="${fileUrl(lb.urls.cek)}" target="_blank" rel="noopener"><img src="${fileUrl(lb.urls.cek)}" alt="Gambar hasil baca"></a>`
        : `<a href="${fileUrl(lb.urls.foto)}" target="_blank" rel="noopener"><img src="${fileUrl(lb.urls.foto)}" alt="Foto asli"></a>`}
        <div class="row" style="margin-top:8px"><a class="btn ghost" href="${fileUrl(lb.urls.foto)}" target="_blank" rel="noopener">${icon("image")}Foto asli</a></div></div>
      <div style="display:grid;gap:14px;align-content:start">
        <div class="row">${statusBadge(lb)}${pctBadge(lb.skor_kualitas, "Kualitas")}${pctBadge(lb.keyakinan, "Keyakinan")}</div>
        <dl class="kv"><dt>Nama</dt><dd>${esc(lb.nama || "—")}</dd><dt>Nomor</dt><dd class="mono">${esc(lb.nomor || "—")}</dd>
          <dt>Kode naskah</dt><dd class="mono">${esc(lb.kode || "—")}</dd><dt>Bidang</dt><dd>${esc(lb.bidang?.nama || "")} (${lb.bidang?.jumlah_soal || "?"} soal)</dd>
          <dt>Terisi</dt><dd>${lb.hasil_baca?.terisi ?? 0} jawaban</dd><dt>Lokasi</dt><dd>${esc(lb.kota)}</dd>
          <dt>Pengirim</dt><dd>${esc(lb.uploader)} · ${esc(lb.dibuat)}</dd>
          ${lb.konfirmasi?.aksi ? `<dt>Konfirmasi</dt><dd>${esc(lb.konfirmasi.aksi)}${Object.keys(lb.konfirmasi.koreksi || {}).length ? ` · koreksi: ${esc(Object.entries(lb.konfirmasi.koreksi).map(([a, b]) => `${a}=${b}`).join(", "))}` : ""}${lb.konfirmasi.catatan ? ` · "${esc(lb.konfirmasi.catatan)}"` : ""}</dd>` : ""}
          <dt>Foto</dt><dd class="small">${esc(lb.foto_ukuran)} · terang ${ks.kecerahan ?? "?"} · tajam ${ks.ketajaman ?? "?"} · silau ${ks.silau ?? "?"}%</dd>
          ${m.perangkat ? `<dt>Perangkat</dt><dd class="small muted">${esc(m.perangkat)}</dd>` : ""}</dl>
        ${lb.error ? `<div class="alert err">${icon("alert")}<div>${esc(lb.error)}</div></div>` : ""}
        ${lb.catatan.length ? `<div class="alert warn">${icon("alert")}<ul>${lb.catatan.map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>` : ""}
        ${lb.peserta_baru ? `<div class="alert info">${icon("userPlus")}<div>Peserta baru: <b>${esc(lb.peserta_baru.nama)}</b> (${esc(lb.peserta_baru.nomor)})${lb.peserta_baru.sekolah ? `, ${esc(lb.peserta_baru.sekolah)}` : ""} · ${lb.peserta_baru_status === "disetujui" ? "disetujui" : "menunggu persetujuan"}</div></div>` : ""}
        ${issues.length ? `<details><summary class="small">${issues.length} catatan pembacaan</summary><ul class="small">${issues.map(i => `<li>${esc(i)}</li>`).join("")}</ul></details>` : ""}
      </div></div>`;
  const approve = lb.peserta_baru_status === "diajukan";
  const r = await modal({ title: `Lembar #${lb.id}`, wide: true, html, submitText: approve ? "Setujui peserta baru" : "Hapus lembar", danger: !approve, cancelText: "Tutup",
    onSubmit: async () => {
      if (approve) { await api(`/api/admin/lembar/${id}/setujui-peserta`, { method: "POST" }); toast("Peserta baru disetujui dan ditambahkan ke daftar."); return true; }
      if (!(await confirmBox("Hapus lembar", "Hapus lembar ini beserta fotonya? Admin daerah perlu mengirim ulang."))) return false;
      await api(`/api/admin/lembar/${id}`, { method: "DELETE" }); toast("Lembar dihapus."); return true;
    } });
  if (r) { updatePbCount(); (after || route)(); }
}

// ---------------------------------------------------------------- persetujuan peserta baru
async function persetujuan() {
  const list = await kompetisiList();
  if (!list.length) return noKompetisi();
  const k = savedKomp(list);
  const r = await api(`/api/admin/lembar?kompetisi_id=${k.id}&peserta_baru=true&limit=200`);
  page.innerHTML = `<div class="page-head"><div><h1>Peserta baru</h1><p class="muted">Peserta yang didaftarkan admin daerah di hari H. Periksa lalu setujui.</p></div>${kompSelect(list, k)}</div>
    ${r.items.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Nomor</th><th>Nama</th><th>Sekolah</th><th>Lokasi</th><th>Diajukan oleh</th><th></th></tr></thead><tbody>
      ${r.items.map(lb => `<tr><td class="mono">${esc(lb.peserta_baru.nomor)}</td><td><b>${esc(lb.peserta_baru.nama)}</b></td><td>${esc(lb.peserta_baru.sekolah)}</td>
        <td>${esc(lb.kota)}</td><td class="small">${esc(lb.konfirmasi?.oleh || lb.uploader)}</td>
        <td class="actions"><button class="btn" data-v="${lb.id}">Lihat</button><button class="btn primary" data-a="${lb.id}">${icon("check")}Setujui</button></td></tr>`).join("")}</tbody></table></div>`
      : `<div class="card empty">${icon("userPlus")}<b>Tidak ada pengajuan</b><span>Semua peserta baru sudah diproses.</span></div>`}`;
  $("#sel-komp").onchange = e => { rememberKomp(e.target.value); route(); };
  page.querySelectorAll("[data-v]").forEach(b => b.onclick = () => lembarDetail(+b.dataset.v));
  page.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try { await api(`/api/admin/lembar/${b.dataset.a}/setujui-peserta`, { method: "POST" }); toast("Disetujui."); updatePbCount(); route(); }
    catch (e) { toast(e.message, true); b.disabled = false; }
  });
}

// ---------------------------------------------------------------- akun
async function akun() {
  const [users, list] = await Promise.all([api("/api/admin/users"), kompetisiList(true)]);
  const kotaOf = {};
  list.forEach(k => k.lokasi.forEach(l => { kotaOf[l.id] = `${l.kota} (${k.nama})`; }));
  page.innerHTML = `<div class="page-head"><div><h1>Akun & akses</h1><p class="muted">Admin daerah hanya bisa mengirim LJK untuk lokasi yang dicentang.</p></div>
      <button class="btn primary" id="b-new">${icon("plus")}Akun baru</button></div>
    <div class="table-wrap"><table class="table"><thead><tr><th>Nama</th><th>Username</th><th>Peran</th><th>Akses lokasi</th><th>Status</th><th></th></tr></thead><tbody>
      ${users.map(u => `<tr><td><b>${esc(u.nama)}</b></td><td class="mono">${esc(u.username)}</td>
        <td>${u.peran === "superadmin" ? `<span class="badge info">Superadmin</span>` : "Admin daerah"}</td>
        <td class="small">${u.peran === "superadmin" ? `<span class="muted">semua</span>` : u.lokasi_ids.length ? esc(u.lokasi_ids.map(i => kotaOf[i] || "?").join(", ")) : `<span class="badge warn">belum ada</span>`}</td>
        <td>${u.aktif ? `<span class="badge ok">Aktif</span>` : `<span class="badge">Nonaktif</span>`}</td>
        <td class="actions"><button class="btn ghost icon-only" data-e="${u.id}" aria-label="Ubah">${icon("pencil")}</button>
        ${u.id !== me.id ? `<button class="btn ghost icon-only danger" data-d="${u.id}" aria-label="Hapus">${icon("trash")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
  const edit = u => modal({
    title: u ? `Ubah akun ${u.nama}` : "Akun baru",
    html: field("Nama lengkap", "nama", u?.nama, "required") +
      field("Username", "username", u?.username, 'required autocapitalize="none" autocomplete="off"') +
      field(u ? "Kata sandi baru (kosongkan bila tidak diganti)" : "Kata sandi (min. 6 karakter)", "password", "", 'type="password" autocomplete="new-password"') +
      `<label class="field"><span>Peran</span><select class="input" name="peran">
        <option value="admin_daerah" ${u?.peran !== "superadmin" ? "selected" : ""}>Admin daerah</option>
        <option value="superadmin" ${u?.peran === "superadmin" ? "selected" : ""}>Superadmin</option></select></label>
      <label class="check"><input type="checkbox" name="aktif" ${u?.aktif === false ? "" : "checked"}>Akun aktif</label>
      <div class="field" id="akses-box"><span>Akses lokasi</span>${list.length ? `<div class="akses-grid">${list.map(k => `<fieldset><legend>${esc(k.nama)}${k.status !== "aktif" ? " (selesai)" : ""}</legend>
        ${k.lokasi.length ? k.lokasi.map(l => `<label class="check"><input type="checkbox" name="lok" value="${l.id}" ${u?.lokasi_ids?.includes(l.id) ? "checked" : ""}>${esc(l.kota)}</label>`).join("") : `<span class="muted small">Belum ada lokasi</span>`}
        </fieldset>`).join("")}</div>` : `<span class="muted small">Belum ada kompetisi.</span>`}</div>`,
    onSubmit: async f => {
      const body = { nama: f.nama.value.trim(), username: f.username.value.trim(), password: f.password.value || null,
        peran: f.peran.value, aktif: f.aktif.checked, lokasi_ids: [...f.querySelectorAll('input[name="lok"]:checked')].map(c => +c.value) };
      if (!body.nama || !body.username) { toast("Nama dan username wajib diisi.", true); return false; }
      if (!u && !body.password) { toast("Isi kata sandi untuk akun baru.", true); return false; }
      await api(u ? `/api/admin/users/${u.id}` : "/api/admin/users", { method: u ? "PUT" : "POST", body });
      toast("Akun tersimpan."); route();
    },
  });
  const open = u => { const pr = edit(u); syncAksesBox(); return pr; };
  $("#b-new").onclick = () => open();
  page.querySelectorAll("[data-e]").forEach(b => b.onclick = () => open(users.find(u => u.id === +b.dataset.e)));
  page.querySelectorAll("[data-d]").forEach(b => b.onclick = async () => {
    const u = users.find(x => x.id === +b.dataset.d);
    if (!(await confirmBox("Hapus akun", `Hapus akun ${u.nama} (${u.username})? Lembar yang pernah dikirimnya tetap ada.`))) return;
    try { await api(`/api/admin/users/${u.id}`, { method: "DELETE" }); toast("Akun dihapus."); route(); } catch (e) { toast(e.message, true); }
  });
}
// pilihan lokasi tidak berlaku untuk superadmin
const syncAksesBox = () => {
  const sel = document.querySelector('.modal select[name="peran"]'), box = document.getElementById("akses-box");
  if (sel && box) box.hidden = sel.value === "superadmin";
};
document.addEventListener("change", e => { if (e.target.name === "peran") syncAksesBox(); });

if (me) route();
