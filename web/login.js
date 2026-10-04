import { apiFetch, cacheUser } from "./api.js";
import { wireVisibilityToggle } from "./password-utils.js";

const el = (id) => document.getElementById(id);

wireVisibilityToggle(el("password"), el("toggleBtn"));

// 1. Intercept OAuth Redirects
// Supabase sends Google tokens in the URL hash (e.g., #access_token=...&refresh_token=...)
if (window.location.hash && window.location.hash.includes("access_token")) {
  const params = new URLSearchParams(window.location.hash.substring(1));
  const accessToken = params.get("access_token");
  const refreshToken = params.get("refresh_token");
  const expiresIn = params.get("expires_in") || 3600;

  if (accessToken && refreshToken) {
    // Clear hash immediately so tokens aren't sitting in the browser URL bar
    window.history.replaceState(null, "", window.location.pathname);
    
    const submitBtn = el("submitBtn");
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="spinner"></span>Securing session…`;

    apiFetch("/auth/oauth-callback", {
      method: "POST",
      body: JSON.stringify({
        access_token: accessToken,
        refresh_token: refreshToken,
        expires_in: parseInt(expiresIn, 10)
      })
    })
    .then((data) => {
      cacheUser({ display_name: data.display_name, email: data.email });
      window.location.href = "dashboard.html";
    })
    .catch(() => {
      el("formError").textContent = "Google sign-in failed. Please try again.";
      el("formError").classList.remove("hidden");
      submitBtn.disabled = false;
      submitBtn.textContent = "Sign in";
    });
  }
} 
else {
  // 2. Standard Session Check (Only run if we aren't handling an OAuth redirect)
  (async () => {
    try {
      const user = await apiFetch("/auth/me");
      cacheUser(user);
      window.location.href = "dashboard.html";
    } catch {
      /* not signed in — show the form as normal */
    }
  })();
}

// 3. Google Sign In Initialization
el("googleBtn").addEventListener("click", async () => {
  try {
    // Tell the backend where to redirect back to after Google finishes
    const redirectUrl = encodeURIComponent(window.location.href);
    const data = await apiFetch(`/auth/google-url?redirect_to=${redirectUrl}`);
    window.location.href = data.url;
  } catch (err) {
    el("formError").textContent = "Could not initialize Google Sign-in.";
    el("formError").classList.remove("hidden");
  }
});

// 4. Standard Email/Password Login
el("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = el("formError");
  const submitBtn = el("submitBtn");
  errorEl.classList.add("hidden");
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span class="spinner"></span>Signing in…`;

  try {
    const body = { email: el("email").value.trim(), password: el("password").value };
    const data = await apiFetch("/auth/login", { method: "POST", body: JSON.stringify(body) });
    cacheUser({ display_name: data.display_name, email: data.email });
    window.location.href = "dashboard.html";
  } catch (err) {
    errorEl.textContent = err.status === 429
      ? "Too many attempts — please wait a few minutes and try again."
      : err.message;
    errorEl.classList.remove("hidden");
    submitBtn.disabled = false;
    submitBtn.textContent = "Sign in";
  }
});