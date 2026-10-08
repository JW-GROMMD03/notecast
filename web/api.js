// Point to the local relative path so Render's Rewrite rule handles the proxying
export const API_BASE = "/api";

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

/** Core fetch wrapper. Always sends cookies; attaches the CSRF header on
 * any state-changing method (GET/HEAD are exempt). 
 * Intelligently handles FormData (file uploads) without breaking Content-Type boundaries. */
export async function apiFetch(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const needsCsrf = !["GET", "HEAD"].includes(method);
  
  const headers = {
    ...(needsCsrf ? csrfHeaders() : {}),
    ...(options.headers || {}),
  };

  // Only set application/json automatically if we are NOT sending FormData (like file uploads)
  if (options.body && !(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include", // Ensures cookies are transmitted
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

/** Tries a normal authenticated request; on a 401 (expired access token)
 * attempts one silent refresh via the httpOnly refresh cookie, then
 * retries once. This allows sessions to survive access-token expiration seamlessly. */
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
    return apiFetch(path, options); // Retry once with the newly minted access cookie
  }
}

/** Call at the top of any page that requires a signed-in user. */
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