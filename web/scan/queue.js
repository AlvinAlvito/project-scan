// Antrean offline: foto yang gagal terkirim disimpan di HP (IndexedDB) dan dikirim ulang
// otomatis saat sinyal kembali. Server menolak foto ganda (hash sama), jadi kirim ulang aman.

const DB_NAME = "ljk-antrean", STORE = "foto";

function open() {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

async function tx(mode, fn) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const out = fn(t.objectStore(STORE));
    t.oncomplete = () => { db.close(); resolve(out && "result" in out ? out.result : out); };
    t.onerror = () => { db.close(); reject(t.error); };
  });
}

export const queue = {
  add(item) { return tx("readwrite", s => s.add({ ...item, dibuat: Date.now() })); },
  all() { return tx("readonly", s => s.getAll()); },
  remove(id) { return tx("readwrite", s => s.delete(id)); },
  async count() { try { return (await this.all()).length; } catch (e) { return 0; } },
};

let running = false;

/**
 * Kirim semua isi antrean. send(item) mengunggah satu item dan melempar ApiError status 0
 * bila tidak ada sinyal. Mengembalikan jumlah yang terkirim.
 */
export async function flush(send, onChange) {
  if (running || !navigator.onLine) return 0;
  running = true;
  let sent = 0;
  try {
    for (const item of await queue.all()) {
      try {
        await send(item);
        await queue.remove(item.id);
        sent++;
        onChange && onChange();
      } catch (e) {
        if (e.status === 0) break;          // masih tanpa sinyal: coba lagi nanti
        await queue.remove(item.id);        // ditolak server (mis. akses dicabut): buang, laporkan
        onChange && onChange(e);
      }
    }
  } finally { running = false; }
  return sent;
}
