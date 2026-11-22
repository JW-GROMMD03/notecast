/**
 * web/assets/js/book-store-cache.js
 * High-Speed Client Book Store Engine:
 * - Two-tier Stale-While-Revalidate (SWR) cache: Memory Map (L1) + IndexedDB (L2)
 * - HTTP ETag / 304 Not Modified conditional revalidation via requestIdleCallback
 * - O(1) Pre-Partitioned Category Buckets (BOOK, NOVEL, PAST_PAPER, OTHER) + Inverted Prefix Index
 * - Pre-computed Deterministic Typographic SVG Cover Generator for zero-network-latency covers
 */

const DB_NAME = "notecast_bookstore_v2";
const STORE_NAME = "catalog_snapshots";
const SCHEMA_VERSION = 2;

const COVER_PALETTES = [
  ["#1d4ed8", "#0f172a"],
  ["#047857", "#064e3b"],
  ["#6d28d9", "#1e1b4b"],
  ["#b45309", "#451a03"],
  ["#0e7490", "#164e63"],
  ["#be123c", "#4c0519"],
];

const TYPE_PALETTES = {
  NOVEL: ["#be185d", "#31102f"],
  PAST_PAPER: ["#0369a1", "#0c2d48"],
  OTHER: ["#b45309", "#2c1203"],
};

function hashString(str) {
  const input = String(str ?? "");
  let h = 2166136261;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function escapeXml(unsafe) {
  return String(unsafe ?? "")
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
    if (!word) continue;
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= maxChars) {
      current = candidate;
    } else {
      if (current) lines.push(current);
      current = word.slice(0, maxChars);
      if (lines.length >= maxLines) break;
    }
  }

  if (current && lines.length < maxLines) {
    lines.push(current);
  }

  return lines;
}

/**
 * Generates an instant, crisp vector book cover data URI for titles lacking a cover photo.
 */
export function generateBookCoverSvg(book = {}) {
  const type = String(book.item_type || "BOOK").toUpperCase();
  const palette =
    TYPE_PALETTES[type] ||
    COVER_PALETTES[hashString(book.id || book.title || "") % COVER_PALETTES.length];
  const lines = wrapLines(book.title, 20, 4);
  const badgeText =
    type === "NOVEL"
      ? "NOVEL • KES 100"
      : type === "PAST_PAPER"
      ? "PAST PAPER • KES 10"
      : book.is_folder
      ? `FOLDER (${book.folder_file_count || "BUNDLE"})`
      : "NOTECAST";
  const courseLabel = escapeXml(String(book.course || "NoteCast").slice(0, 28).toUpperCase());
  const unitLabel = escapeXml(String(book.unit || "Study Module").slice(0, 32));

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
    <rect x="24" y="28" width="164" height="24" rx="12" fill="rgba(255,255,255,0.18)"/>
    <text x="106" y="44" text-anchor="middle" fill="#ffffff" font-family="system-ui,sans-serif" font-size="10.5" font-weight="700" letter-spacing="0.8">${escapeXml(badgeText)}</text>
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
      try {
        const req = indexedDB.open(DB_NAME, SCHEMA_VERSION);
        req.onupgradeneeded = () => {
          const db = req.result;
          if (!db.objectStoreNames.contains(STORE_NAME)) {
            db.createObjectStore(STORE_NAME);
          }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(null);
      } catch {
        resolve(null);
      }
    });

    return this._dbPromise;
  }

  async get(key) {
    const db = await this._open();
    if (!db) return null;
    return new Promise((resolve) => {
      try {
        const tx = db.transaction(STORE_NAME, "readonly");
        const req = tx.objectStore(STORE_NAME).get(key);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => resolve(null);
      } catch {
        resolve(null);
      }
    });
  }

  async set(key, value) {
    const db = await this._open();
    if (!db) return;
    return new Promise((resolve) => {
      try {
        const tx = db.transaction(STORE_NAME, "readwrite");
        tx.objectStore(STORE_NAME).put(value, key);
        tx.oncomplete = () => resolve();
        tx.onerror = () => resolve();
      } catch {
        resolve();
      }
    });
  }

  async clear() {
    const db = await this._open();
    if (!db) return;
    return new Promise((resolve) => {
      try {
        const tx = db.transaction(STORE_NAME, "readwrite");
        tx.objectStore(STORE_NAME).clear();
        tx.oncomplete = () => resolve();
        tx.onerror = () => resolve();
      } catch {
        resolve();
      }
    });
  }
}

/**
 * O(1) Pre-Bucketed Category Index + Inverted Prefix Search Index.
 * Allows instant 0ms switching across Books, Novels, Past Papers, and Folder Bundles.
 */
class BookSearchIndex {
  constructor() {
    this.books = [];
    this.bookById = new Map();
    this.tokenIndex = new Map(); // prefix -> Set<bookId>
    this.typeBuckets = {
      ALL: [],
      BOOK: [],
      NOVEL: [],
      PAST_PAPER: [],
      OTHER: [],
    };
  }

  _tokenize(text) {
    return String(text ?? "")
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((t) => t.length >= 2);
  }

  build(books) {
    this.books = Array.isArray(books) ? books : [];
    this.bookById.clear();
    this.tokenIndex.clear();
    this.typeBuckets = {
      ALL: this.books,
      BOOK: [],
      NOVEL: [],
      PAST_PAPER: [],
      OTHER: [],
    };

    for (const book of this.books) {
      if (!book || typeof book !== "object") continue;

      const normType = String(book.item_type || "BOOK").toUpperCase();
      book.item_type = normType;
      book._resolvedCover = book.cover_url || generateBookCoverSvg(book);
      book._fieldLower = String(book.field || "").toLowerCase();
      book._courseLower = String(book.course || "").toLowerCase();
      book._haystackLower = `${book.unit || ""} ${book.title || ""} ${book.description || ""} ${normType}`.toLowerCase();

      this.bookById.set(book.id, book);
      if (Object.prototype.hasOwnProperty.call(this.typeBuckets, normType) && normType !== "ALL") {
        this.typeBuckets[normType].push(book);
      } else {
        this.typeBuckets.OTHER.push(book);
      }

      const tokens = this._tokenize(
        `${book.title || ""} ${book.field || ""} ${book.course || ""} ${book.unit || ""} ${normType} ${book.description || ""}`
      );
      for (const tok of tokens) {
        const maxLen = Math.min(tok.length, 10);
        for (let len = 2; len <= maxLen; len++) {
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

  query({ itemType = "ALL", field = "", course = "", unit = "" } = {}) {
    const typeNorm = String(itemType || "ALL").toUpperCase();
    const fieldNorm = String(field || "").trim().toLowerCase();
    const courseNorm = String(course || "").trim().toLowerCase();
    const unitNorm = String(unit || "").trim().toLowerCase();
    const unitTokens = this._tokenize(unitNorm);

    // Fast path: pure category tab switch with no text filters -> O(1) slice
    if (!fieldNorm && !courseNorm && !unitNorm) {
      return this.typeBuckets[typeNorm] || this.books;
    }

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
        : typeNorm !== "ALL" && this.typeBuckets[typeNorm]
        ? this.typeBuckets[typeNorm]
        : this.books;

    return pool.filter((b) => {
      if (typeNorm !== "ALL" && b.item_type !== typeNorm) return false;
      if (fieldNorm && !b._fieldLower.includes(fieldNorm)) return false;
      if (courseNorm && !b._courseLower.includes(courseNorm)) return false;
      if (unitNorm && !b._haystackLower.includes(unitNorm)) return false;
      return true;
    });
  }

  getCounts() {
    return {
      ALL: this.typeBuckets.ALL.length,
      BOOK: this.typeBuckets.BOOK.length,
      NOVEL: this.typeBuckets.NOVEL.length,
      PAST_PAPER: this.typeBuckets.PAST_PAPER.length,
      OTHER: this.typeBuckets.OTHER.length,
    };
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
   * 1. Immediately delivers cached items (L1 RAM -> L2 IndexedDB) via onUpdate(books, { source })
   * 2. Revalidates against /books/store using If-None-Match ETag on idle thread
   * 3. Only triggers a second render if the server returns 200 OK with changed data
   */
  async loadCatalog(userId, onUpdate = () => {}) {
    const key = this._storageKey(userId);
    let servedFromCache = false;

    if (this.l1Memory && Array.isArray(this.l1Memory.books) && this.l1Memory.books.length > 0) {
      this.index.build(this.l1Memory.books);
      onUpdate(this.l1Memory.books, { source: "l1-memory", revalidating: true });
      servedFromCache = true;
    } else {
      const snapshot = await this.l2Db.get(key);
      if (snapshot && Array.isArray(snapshot.books) && snapshot.books.length > 0) {
        this.l1Memory = snapshot;
        this.index.build(snapshot.books);
        onUpdate(snapshot.books, { source: "l2-indexeddb", revalidating: true });
        servedFromCache = true;
      }
    }

    if (this._inflight) return this._inflight;

    const revalidate = async () => {
      try {
        const headers = {};
        if (this.l1Memory?.etag && this.l1Memory.books?.length > 0) {
          headers["If-None-Match"] = this.l1Memory.etag;
        }

        const resp = await this.authedFetch("/books/store", {
          headers,
          rawResponse: true,
        });

        if (resp?.status === 304 && this.l1Memory?.books) {
          return this.l1Memory.books;
        }

        const books = typeof resp?.json === "function" ? await resp.json() : resp;
        const etag = resp?.headers?.get ? resp.headers.get("ETag") || null : null;

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
    };

    if (servedFromCache && typeof requestIdleCallback === "function") {
      this._inflight = new Promise((resolve, reject) => {
        requestIdleCallback(
          () => {
            revalidate().then(resolve, reject);
          },
          { timeout: 1200 }
        );
      });
    } else {
      this._inflight = revalidate();
    }

    return this._inflight;
  }

  filterLocal(filters) {
    return this.index.query(filters);
  }

  getCategoryCounts() {
    return this.index.getCounts();
  }

  async invalidate() {
    this.l1Memory = null;
    this.index.build([]);
    await this.l2Db.clear();
  }
}