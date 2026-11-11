export const API_BASE = "/api";
export const EXTENSION_ID = "oflgnhoaebicbfnfoomfkfjgjldjbglg";
export const CHROME_STORE_URL = "https://chromewebstore.google.com/detail/notecast/oflgnhoaebicbfnfoomfkfjgjldjbglg";

function readCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function csrfHeaders() {
  const token = readCookie("nc_csrf");
  return token ? { "X-CSRF-Token": token } : {};
}

export function cacheUser(user) {
  sessionStorage.setItem("notecast_user", JSON.stringify({ display_name: user.display_name, email: user.email }));
}

export function cachedUser() {
  try {
    return JSON.parse(sessionStorage.getItem("notecast_user") || "null");
  } catch {
    return null;
  }
}

export function clearCachedUser() {
  sessionStorage.removeItem("notecast_user");
}

export async function apiFetch(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const needsCsrf = !["GET", "HEAD"].includes(method);
  
  const headers = {
    ...(needsCsrf ? csrfHeaders() : {}),
    ...(options.headers || {}),
  };

  if (options.body && !(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers,
  });
  
  const ct = resp.headers.get("content-type") || "";
  const body = ct.includes("application/json") ? await resp.json().catch(() => ({})) : null;
  
  if (!resp.ok) {
    const err = new Error((body && body.detail) || `Request failed (${resp.status})`);
    err.status = resp.status;
    throw err;
  }
  return body ?? resp;
}

export async function authedFetch(path, options = {}) {
  try {
    return await apiFetch(path, options);
  } catch (err) {
    if (err.status !== 401) throw err;
    try {
      await apiFetch("/auth/refresh", { method: "POST", body: JSON.stringify({}) });
    } catch {
      clearCachedUser();
      window.location.href = "login.html";
      throw err;
    }
    return apiFetch(path, options);
  }
}

export async function requireAuth() {
  try {
    const user = await authedFetch("/auth/me");
    cacheUser(user);
    return user;
  } catch {
    clearCachedUser();
    window.location.href = "login.html";
    throw new Error("Not authenticated");
  }
}

export async function logout() {
  try {
    await apiFetch("/auth/logout", { method: "POST", body: JSON.stringify({}) });
  } finally {
    clearCachedUser();
  }
}

export function checkExtensionInstalled() {
  return new Promise((resolve) => {
    if (typeof window.chrome !== "undefined" && window.chrome.runtime && window.chrome.runtime.sendMessage) {
      window.chrome.runtime.sendMessage(EXTENSION_ID, { type: "PING" }, (response) => {
        if (window.chrome.runtime.lastError || !response || !response.installed) {
          resolve(false);
        } else {
          resolve(true);
        }
      });
    } else {
      resolve(false);
    }
  });
}