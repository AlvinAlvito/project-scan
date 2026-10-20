// Fungsi bersama: sesi login, panggilan API, ikon, toast, modal, tema.

const TOKEN_KEY = "ljk_token", USER_KEY = "ljk_user", THEME_KEY = "ljk_theme";

function store(get, key, val) {
  try { if (get) return localStorage.getItem(key); if (val == null) localStorage.removeItem(key); else localStorage.setItem(key, val); }
  catch (e) { return null; }
}

export const session = {
  get token() { return store(true, TOKEN_KEY); },
  get user() { try { return JSON.parse(store(true, USER_KEY) || "null"); } catch (e) { return null; } },
  save(token, user) { store(false, TOKEN_KEY, token); store(false, USER_KEY, JSON.stringify(user)); },
  clear() { store(false, TOKEN_KEY, null); store(false, USER_KEY, null); },
};

export function logout() { session.clear(); location.href = "/"; }

/** Pastikan sudah login dengan peran tertentu; bila tidak, kembali ke halaman login. */
export function requireLogin(peran) {
  const u = session.user;
  if (!session.token || !u || (peran && u.peran !== peran && u.peran !== "superadmin")) { location.href = "/"; return null; }
  return u;
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body, form } = {}) {
  const headers = {};
  if (session.token) headers.Authorization = "Bearer " + session.token;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, { method, headers, body: payload }); }
  catch (e) { throw new ApiError(0, "Tidak terhubung ke server. Periksa koneksi internet."); }
  if (res.status === 401) { session.clear(); location.href = "/"; throw new ApiError(401, "Sesi berakhir."); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    let msg = data.detail;
    if (Array.isArray(msg)) msg = msg.map(d => d.msg).join("; ");
    throw new ApiError(res.status, msg || `Gagal (${res.status})`);
  }
  return data;
}

/** URL gambar terlindungi (token lewat query karena <img> tidak bisa mengirim header). */
export function fileUrl(url) { return url ? `${url}?t=${encodeURIComponent(session.token || "")}` : ""; }

export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Ikon garis gaya Lucide (lisensi ISC)
const P = {
  scan: '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/>',
  camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  pencil: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  chevronLeft: '<path d="m15 18-6-6 6-6"/>',
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  dashboard: '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
  trophy: '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  sheet: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  userPlus: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6"/><path d="M22 11h-6"/>',
  mapPin: '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
  image: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
  flash: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
  history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  cloudOff: '<path d="m2 2 20 20"/><path d="M5.782 5.782A7 7 0 0 0 9 19h8.5a4.5 4.5 0 0 0 1.307-.193"/><path d="M21.532 16.5A4.5 4.5 0 0 0 17.5 10h-1.79A7.008 7.008 0 0 0 10 5.07"/>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
  menu: '<path d="M4 12h16"/><path d="M4 6h16"/><path d="M4 18h16"/>',
  book: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
};
export function icon(name, cls = "") { return `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || ""}</svg>`; }

export function toast(msg, err = false) {
  let box = document.querySelector(".toast-box");
  if (!box) { box = document.createElement("div"); box.className = "toast-box"; box.setAttribute("role", "status"); document.body.append(box); }
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  box.append(t);
  setTimeout(() => t.remove(), err ? 6000 : 3200);
}

/** Modal sederhana. html: isi; onOpen(form) dipanggil setelah tampil; onSubmit(form) mengembalikan false untuk tetap terbuka. */
export function modal({ title, html, submitText = "Simpan", danger = false, wide = false, onSubmit, onOpen, cancelText = "Batal" }) {
  return new Promise(resolve => {
    const back = document.createElement("div");
    back.className = "modal-back";
    back.innerHTML = `<form class="modal${wide ? " wide" : ""}" novalidate>
      <div class="row"><h2 class="grow">${esc(title)}</h2><button type="button" class="btn ghost icon-only" data-x aria-label="Tutup">${icon("x")}</button></div>
      <div class="modal-body" style="display:grid;gap:14px">${html}</div>
      <div class="modal-foot">${cancelText ? `<button type="button" class="btn ghost" data-x>${esc(cancelText)}</button>` : ""}
        ${submitText ? `<button class="btn ${danger ? "danger" : "primary"}" type="submit">${esc(submitText)}</button>` : ""}</div></form>`;
    const form = back.querySelector("form");
    const close = v => { back.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
    const onKey = e => { if (e.key === "Escape") close(null); };
    document.addEventListener("keydown", onKey);
    back.querySelectorAll("[data-x]").forEach(b => b.onclick = () => close(null));
    back.addEventListener("mousedown", e => { if (e.target === back) close(null); });
    form.onsubmit = async e => {
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      if (btn) btn.disabled = true;
      try {
        const r = onSubmit ? await onSubmit(form) : true;
        if (r !== false) close(r ?? true);
      } catch (err) { toast(err.message, true); }
      finally { if (btn) btn.disabled = false; }
    };
    document.body.append(back);
    if (onOpen) onOpen(form);
    const first = form.querySelector(".modal-body input, .modal-body select, .modal-body textarea");
    (first || form.querySelector('button[type="submit"]'))?.focus();
  });
}

/**
 * Pilihan dengan pencarian. root: elemen kosong. items: [{id, label, sub}].
 * onPick(item) saat dipilih; onCreate(teks) (opsional) menambah pilihan baru bila tidak ada yang cocok
 * dan mengembalikan item baru. Nilai terpilih: root.value (item atau null).
 */
export function searchSelect(root, { items, placeholder = "Cari…", onPick, onCreate, createLabel = q => `Tambah "${q}"`, value = null }) {
  root.classList.add("ss");
  root.innerHTML = `<div class="ss-box">${icon("search")}<input class="input" type="text" autocomplete="off" role="combobox"
      aria-expanded="false" placeholder="${esc(placeholder)}"></div><ul class="ss-list" role="listbox" hidden></ul>`;
  const input = root.querySelector("input"), list = root.querySelector(".ss-list");
  let shown = [], active = 0;
  root.value = value;
  if (value) input.value = value.label;
  const norm = s => (s || "").toLowerCase();
  function render() {
    const q = input.value.trim();
    const words = norm(q).split(/\s+/).filter(Boolean);
    shown = items.filter(it => words.every(w => norm(it.label + " " + (it.sub || "")).includes(w)));
    const exact = items.some(it => norm(it.label) === norm(q));
    if (onCreate && q && !exact) shown.push({ create: q });
    active = Math.min(active, Math.max(0, shown.length - 1));
    list.innerHTML = shown.length ? shown.map((it, i) => `<li role="option" class="${i === active ? "on" : ""}" data-i="${i}">
        ${it.create ? `${icon("plus", "sm")} ${esc(createLabel(it.create))}` : `<b>${esc(it.label)}</b>${it.sub ? `<span>${esc(it.sub)}</span>` : ""}`}</li>`).join("")
      : `<li class="none">Tidak ada yang cocok</li>`;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }
  function close() { list.hidden = true; input.setAttribute("aria-expanded", "false"); }
  async function pick(i) {
    let it = shown[i];
    if (!it) return;
    if (it.create) {
      try { it = await onCreate(it.create); } catch (e) { toast(e.message, true); return; }
      if (!it) return;
      items.push(it);
    }
    root.value = it;
    input.value = it.label;
    close();
    onPick && onPick(it);
  }
  input.addEventListener("focus", render);
  input.addEventListener("input", () => { root.value = null; active = 0; render(); });
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") { active = Math.min(active + 1, shown.length - 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
    else if (e.key === "Enter" && !list.hidden) { e.preventDefault(); pick(active); }
    else if (e.key === "Escape" && !list.hidden) { e.stopPropagation(); close(); }
  });
  list.addEventListener("mousedown", e => { const li = e.target.closest("li[data-i]"); if (li) { e.preventDefault(); pick(+li.dataset.i); } });
  input.addEventListener("blur", () => setTimeout(close, 120));
  return { input, focus: () => input.focus() };
}

const BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"];
/** "2026-09-24" -> "24 September 2026"; teks lain dikembalikan apa adanya. */
export function fmtDate(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
  return m ? `${+m[3]} ${BULAN[+m[2] - 1]} ${m[1]}` : (s || "");
}

/** Unduh file dari API (dengan token) dan simpan dengan nama dari server. */
export async function download(path, fallbackName) {
  const res = await fetch(path, { headers: { Authorization: "Bearer " + (session.token || "") } });
  if (!res.ok) throw new ApiError(res.status, "Gagal mengunduh file.");
  const cd = res.headers.get("Content-Disposition") || "";
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd) || /filename="?([^";]+)"?/.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function confirmBox(title, text, okText = "Hapus") {
  return modal({ title, html: `<p style="margin:0">${esc(text)}</p>`, submitText: okText, danger: true });
}

// ---- tema
export function applyTheme(t) {
  if (t === "dark" || t === "light") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
}
export function currentTheme() {
  const t = store(true, THEME_KEY);
  if (t) return t;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
export function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  store(false, THEME_KEY, next);
  applyTheme(next);
  return next;
}
applyTheme(store(true, THEME_KEY));

export const STATUS = {
  gagal: ["Gagal dibaca", "err"], menunggu: ["Menunggu konfirmasi", "warn"],
  dikonfirmasi: ["Dikonfirmasi", "ok"], ditandai: ["Ditandai", "info"],
};
export function statusBadge(lb) {
  if (lb.ditarik_at) return `<span class="badge ok">${icon("check")}Ditarik pusat</span>`;
  const [t, c] = STATUS[lb.status] || [lb.status, ""];
  return `<span class="badge ${c}">${esc(t)}</span>`;
}
export function pctBadge(v, label) {
  const c = v >= 90 ? "ok" : v >= 70 ? "warn" : "err";
  return `<span class="badge ${c}" title="${esc(label)}">${esc(label)} ${v}%</span>`;
}
