import { apiFetch } from "./api.js";

const el = (id) => document.getElementById(id);

el("forgotForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = el("formError");
  const submitBtn = el("submitBtn");
  errorEl.classList.add("hidden");
  submitBtn.disabled = true;
  submitBtn.innerHTML = `<span class="spinner"></span>Sending…`;

  try {
    const body = { email: el("email").value.trim() };
    await apiFetch("/auth/forgot-password", { method: "POST", body: JSON.stringify(body) });
    el("formView").classList.add("hidden");
    el("successView").classList.remove("hidden");
  } catch (err) {
    // The backend already returns the same message whether or not the
    // account exists — the only error worth surfacing here is being
    // rate-limited, or the request not reaching the server at all.
    errorEl.textContent = err.status === 429
      ? "Too many attempts — please wait a while before trying again."
      : "Something went wrong sending that — please try again.";
    errorEl.classList.remove("hidden");
    submitBtn.disabled = false;
    submitBtn.textContent = "Send reset link";
  }
});
