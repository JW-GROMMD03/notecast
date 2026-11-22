/**
 * web/assets/js/book-store-cache.js
 * High-Speed Client Book Store Engine:
 * - Two-tier Stale-While-Revalidate (SWR) cache: Memory Map (L1) + IndexedDB (L2)
 * - HTTP ETag / 304 Not Modified conditional revalidation
 * - O(1) Inverted Index for instant 0ms client-side search & cascading filtering
 * - Deterministic Typographic SVG Cover Generator for books without cover art
 */

const DB_NAME = "notecast_bookstore_v1";
const STORE_NAME = "catalog_snapshots";
const SCHEMA_VERSION = 1;

const COVER_PALETTES = [
  ["#1d4ed8", "#0f172a"],
  ["#047857", "#064e3b"],
  ["#6d28d9", "#1e1b4b"],
  ["#b45309", "#451a03"],
  ["#0e7490", "#164e63"],
  ["#be123c", "#4c0519"],
];

function hashString(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function escapeXml(unsafe) {
  return String(unsafe || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function wrapLines(text, maxChars = 22, maxLines = 4) {
  const words = String(text || "NoteCast Study Guide").trim().split(/\s+/);
  const lines = [];
  let current = "";
  for (const word of words) {
    if ((current + " " + word).trim().length <= maxChars) {
      current = (current + " " + word).trim();
    } else {
      if (current) lines.push(current);
      current = word.slice(0, maxChars);
      if (lines.length >= maxLines) break;
    }
  }
  if (current && lines.length < maxLines) lines.push(current);
  return lines;
}

/**
 * Generates an instant, crisp vector book cover data URI for titles lacking a cover photo.
 */
export function generateBookCoverSvg(book) {
  const palette = COVER_PALETTES[hashString(book.id || book.title || "") % COVER_PALETTES.length];
  const lines = wrapLines(book.title, 20, 4);
  const courseLabel = escapeXml((book.course || "NoteCast").slice(0, 28).toUpperCase());
  const unitLabel = escapeXml((book.unit || "Study Module").slice(0, 32));

  const titleSvg = lines
    .map(
      (line, idx) =>
        `<text x="24" y="${125 + idx * 28}" fill="#f8fafc" font-family="system-ui,-apple-system,sans-serif" font-size="20" font-weight="800">${escapeXml(line)}</text>`
    )
    .join("");

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="360" height="440" viewBox="0 0 360 440">
    <defs>
      <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="${palette[0]}"/>
        <stop offset="100%" stop-color="${palette[1]}"/>
      </linearGradient>
    </defs>
    <rect width="360" height="440" fill="url(#g)"/>
    <rect x="0" y="0" width="14" height="440" fill="rgba(0,0,0,0.3)"/>
    <circle cx="310" cy="60" r="90" fill="rgba(255,255,255,0.06)"/>
    <rect x="24" y="28" width="120" height="24" rx="12" fill="rgba(255,255,255,0.16)"/>
    <text x="84" y="44" text-anchor="middle" fill="#ffffff" font-family="system-ui,sans-serif" font-size="11" font-weight="700" letter-spacing="1">NOTECAST</text>
    <text x="24" y="88" fill="rgba(255,255,255,0.8)" font-family="system-ui,sans-serif" font-size="11" font-weight="700" letter-spacing="0.8">${courseLabel}</text>
    ${titleSvg}
    <line x1="24" y1="365" x2="336" y2="365" stroke="rgba(255,255,255,0.2)" stroke-width="1"/>
    <text x="24" y="395" fill="rgba(255,255,255,0.85)" font-family="system-ui,sans-serif" font-size="13" font-weight="600">${unitLabel}</text>
  </svg>`;

  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

class IndexedDBSnapshotStore {
  constructor() {
    this._dbPromise = null;
  }

  _open() {
    if (typeof indexedDB === "undefined") return Promise.resolve(null);
    if (this._dbPromise) return this._dbPromise;

    this._dbPromise = new Promise((resolve) => {
      const req = indexedDB.open(DB_NAME, SCHEMA_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME);
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
    });
    return this._dbPromise;
  }

  async get(key) {
    const db = await this._open();
    if (!db) return null;
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, "readonly");
      const req = tx.objectStore(STORE_NAME).get(key);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => resolve(null);
    });
  }

  async set(key, value) {
    const db = await this._open();
    if (!db) return;
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  }

  async clear() {
    const db = await this._open();
    if (!db) return;
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  }
}

/**
 * O(1) Inverted Index + Hash Map Index over the full book catalog.
 * Allows instant 0ms client-side search & filtering across thousands of books.
 */
class BookSearchIndex {
  constructor() {
    this.books = [];
    this.bookById = new Map();
    this.tokenIndex = new Map(); // token -> Set<bookId>
  }

  _tokenize(text) {
    return String(text || "")
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((t) => t.length >= 2);
  }

  build(books) {
    this.books = Array.isArray(books) ? books : [];
    this.bookById.clear();
    this.tokenIndex.clear();

    for (const book of this.books) {
      this.bookById.set(book.id, book);
      const tokens = this._tokenize(
        `${book.title} ${book.field} ${book.course} ${book.unit} ${book.description}`
      );
      for (const tok of tokens) {
        // Index prefixes of length >= 2 for instant prefix autocomplete matching
        for (let len = 2; len <= Math.min(tok.length, 10); len++) {
          const prefix = tok.slice(0, len);
          let set = this.tokenIndex.get(prefix);
          if (!set) {
            set = new Set();
            this.tokenIndex.set(prefix, set);
          }
          set.add(book.id);
        }
      }
    }
  }

  query({ field = "", course = "", unit = "" } = {}) {
    const fieldNorm = field.trim().toLowerCase();
    const courseNorm = course.trim().toLowerCase();
    const unitTokens = this._tokenize(unit);

    let candidateIds = null;

    if (unitTokens.length > 0) {
      for (const tok of unitTokens) {
        const key = tok.slice(0, 10);
        const matches = this.tokenIndex.get(key) || new Set();
        if (candidateIds === null) {
          candidateIds = new Set(matches);
        } else {
          for (const id of candidateIds) {
            if (!matches.has(id)) candidateIds.delete(id);
          }
        }
      }
    }

    const pool =
      candidateIds !== null
        ? Array.from(candidateIds).map((id) => this.bookById.get(id)).filter(Boolean)
        : this.books;

    return pool.filter((b) => {
      if (fieldNorm && !(b.field || "").toLowerCase().includes(fieldNorm)) return false;
      if (courseNorm && !(b.course || "").toLowerCase().includes(courseNorm)) return false;
      if (unit.trim()) {
        const hay = `${b.unit || ""} ${b.title || ""} ${b.description || ""}`.toLowerCase();
        if (!hay.includes(unit.trim().toLowerCase())) return false;
      }
      return true;
    });
  }
}

export class BookStoreEngine {
  constructor(authedFetchFn) {
    this.authedFetch = authedFetchFn;
    this.l1Memory = null; // { etag, books, updatedAt }
    this.l2Db = new IndexedDBSnapshotStore();
    this.index = new BookSearchIndex();
    this._inflight = null;
  }

  _storageKey(userId) {
    return `catalog:${userId || "anon"}`;
  }

  /**
   * Stale-While-Revalidate loader:
   * 1. Immediately delivers cached books (L1 RAM -> L2 IndexedDB) via onUpdate(books, { source })
   * 2. Revalidates against /books/store using If-None-Match ETag in background
   * 3. Only triggers a second render if the server returns 200 OK with updated books
   */
async loadCatalog(userId, onUpdate) {
    const key = this._storageKey(userId);

    // L1 Memory Hit (<1 ms) — only serve non-empty cached catalogs
    if (this.l1Memory && Array.isArray(this.l1Memory.books) && this.l1Memory.books.length > 0) {
      this.index.build(this.l1Memory.books);
      onUpdate(this.l1Memory.books, { source: "l1-memory", revalidating: true });
    } else {
      // L2 IndexedDB Hit (<5 ms)
      const snapshot = await this.l2Db.get(key);
      if (snapshot && Array.isArray(snapshot.books) && snapshot.books.length > 0) {
        this.l1Memory = snapshot;
        this.index.build(snapshot.books);
        onUpdate(snapshot.books, { source: "l2-indexeddb", revalidating: true });
      }
    }

    if (this._inflight) return this._inflight;

    this._inflight = (async () => {
      try {
        const headers = {};
        if (this.l1Memory?.etag && this.l1Memory.books?.length > 0) {
          headers["If-None-Match"] = this.l1Memory.etag;
        }

        const resp = await this.authedFetch("/books/store", {
          headers,
          rawResponse: true,
        });

        if (resp.status === 304 && this.l1Memory?.books) {
          return this.l1Memory.books;
        }

        const books = await resp.json();
        const etag = resp.headers.get("ETag") || null;

        if (Array.isArray(books)) {
          if (books.length > 0) {
            const snapshot = { etag, books, updatedAt: Date.now() };
            this.l1Memory = snapshot;
            this.index.build(books);
            await this.l2Db.set(key, snapshot);
          } else {
            this.l1Memory = null;
            this.index.build([]);
          }
          onUpdate(books, { source: "network", revalidating: false });
        }
        return books;
      } finally {
        this._inflight = null;
      }
    })();

    return this._inflight;
  }

  filterLocal(filters) {
    return this.index.query(filters);
  }

  async invalidate() {
    this.l1Memory = null;
    await this.l2Db.clear();
  }
}