import { apiFetch } from "./api.js";

const el = (id) => document.getElementById(id);

function setupVisibility(inputId, btnId) {
  const input = el(inputId);
  const btn = el(btnId);
  btn.addEventListener("click", () => {
    const isPw = input.type === "password";
    input.type = isPw ? "text" : "password";
    btn.textContent = isPw ? "Hide" : "Show";
  });
}

function extractRecoveryToken() {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  const params = new URLSearchParams(hash);
  const type = params.get("type");
  const accessToken = params.get("access_token");
  history.replaceState(null, "", window.location.pathname); 
  if (type !== "recovery" || !accessToken) return null;
  return accessToken;
}

const recoveryToken = extractRecoveryToken();

if (!recoveryToken) {
  el("invalidView").classList.remove("hidden");
} else {
  el("formView").classList.remove("hidden");
  
  setupVisibility("password", "togglePw");
  setupVisibility("confirmPassword", "toggleConfirm");

  // Visual Password Strength
  el("password").addEventListener("input", (e) => {
    const pw = e.target.value;
    let score = 0;
    if (pw.length > 7) score++;
    if (/[A-Z]/.test(pw)) score++;
    if (/[0-9]/.test(pw)) score++;
    if (/[^A-Za-z0-9]/.test(pw)) score++;
    
    const bar = el("strengthBar");
    const hint = el("strengthHint");
    
    if (pw.length === 0) { bar.style.width = "0"; hint.textContent = ""; return; }
    if (score < 2) {
      bar.style.width = "25%"; bar.style.background = "#ef4444"; hint.textContent = "Weak"; hint.style.color = "#ef4444";
    } else if (score === 2) {
      bar.style.width = "50%"; bar.style.background = "#eab308"; hint.textContent = "Fair"; hint.style.color = "#eab308";
    } else if (score === 3) {
      bar.style.width = "75%"; bar.style.background = "#3b82f6"; hint.textContent = "Good"; hint.style.color = "#3b82f6";
    } else {
      bar.style.width = "100%"; bar.style.background = "#22c55e"; hint.textContent = "Strong"; hint.style.color = "#22c55e";
    }
  });

  el("resetForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = el("formError");
    const submitBtn = el("submitBtn");
    
    errorEl.classList.add("hidden");
    el("matchError").classList.add("hidden");

    const password = el("password").value;
    if (password !== el("confirmPassword").value) {
      el("matchError").classList.remove("hidden");
      return;
    }
    if (password.length < 8) {
      errorEl.textContent = "Password must be at least 8 characters.";
      errorEl.classList.remove("hidden");
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Updating...";

    try {
      await apiFetch("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ recovery_token: recoveryToken, new_password: password }),
      });
      el("formView").classList.add("hidden");
      el("doneView").classList.remove("hidden");
    } catch (err) {
      if (err.status === 400 || err.status === 401) {
        el("formView").classList.add("hidden");
        el("invalidView").classList.remove("hidden");
      } else {
        errorEl.textContent = err.status === 429
          ? "Too many attempts — please wait a while before trying again."
          : err.message || "Failed to update password.";
        errorEl.classList.remove("hidden");
        submitBtn.disabled = false;
        submitBtn.textContent = "Update password";
      }
    }
  });
}