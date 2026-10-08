import { apiFetch, cacheUser } from "./api.js";
import { wireVisibilityToggle } from "./password-utils.js";

const el = (id) => document.getElementById(id);

wireVisibilityToggle(el("password"), el("toggleBtn"));

// Helper function to process tokens and send to backend
async function handleOAuthTokens(accessToken, refreshToken, expiresIn) {
  const submitBtn = el("submitBtn");
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.innerHTML = `<span class="spinner"></span>Securing session…`;
  }

  try {
    const data = await apiFetch("/auth/oauth-callback", {
      method: "POST",
      body: JSON.stringify({
        access_token: accessToken,
        refresh_token: refreshToken,
        expires_in: parseInt(expiresIn, 10)
      })
    });
    cacheUser({ display_name: data.display_name, email: data.email });
    window.location.href = "dashboard.html";
  } catch (err) {
    console.error("OAuth callback error:", err);
    el("formError").textContent = "Google sign-in failed to sync session. Please try again.";
    el("formError").classList.remove("hidden");
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Sign in";
    }
  }
}

// 1. Initialization logic wrapped in a function (fixes the illegal return error)
async function checkAuthOnLoad() {
  const hashParams = new URLSearchParams(window.location.hash.substring(1));
  const queryParams = new URLSearchParams(window.location.search);

  const accessToken = hashParams.get("access_token") || queryParams.get("access_token");
  const refreshToken = hashParams.get("refresh_token") || queryParams.get("refresh_token");
  const expiresIn = hashParams.get("expires_in") || queryParams.get("expires_in") || 3600;

  if (accessToken && refreshToken) {
    // Clear URL parameters immediately so tokens aren't exposed in the browser bar
    window.history.replaceState(null, "", window.location.pathname);
    await handleOAuthTokens(accessToken, refreshToken, expiresIn);
    return;
  } 

  // Check if Supabase stored a session client-side
  const supabaseSessionKey = Object.keys(localStorage).find(key => key.includes("supabase.auth.token"));
  
  if (supabaseSessionKey) {
    try {
      const sessionData = JSON.parse(localStorage.getItem(supabaseSessionKey));
      const token = sessionData?.access_token;
      const refresh = sessionData?.refresh_token;
      
      if (token && refresh) {
        localStorage.removeItem(supabaseSessionKey);
        await handleOAuthTokens(token, refresh, 3600);
        return;
      }
    } catch (e) {
      // Ignore parse errors
    }
  }

  // Standard Session Check 
  try {
    const user = await apiFetch("/auth/me");
    cacheUser(user);
    window.location.href = "dashboard.html";
  } catch {
    /* not signed in — show the form as normal */
  }
}

// Execute the check when the script loads
checkAuthOnLoad();


// 2. Google Sign In Initialization
el("googleBtn").addEventListener("click", async () => {
  try {
    const redirectUrl = encodeURIComponent(window.location.origin + "/login.html");
    const data = await apiFetch(`/auth/google-url?redirect_to=${redirectUrl}`);
    window.location.href = data.url;
  } catch (err) {
    el("formError").textContent = "Could not initialize Google Sign-in.";
    el("formError").classList.remove("hidden");
  }
});

// 3. Standard Email/Password Login
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