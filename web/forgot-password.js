import { apiFetch } from "./api.js";

const el = (id) => document.getElementById(id);

el("forgotForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = el("formError");
  const submitBtn = el("submitBtn");
  errorEl.classList.add("hidden");
  submitBtn.disabled = true;
  submitBtn.textContent = "Sending code…";

  try {
    const email = el("email").value.trim();
    sessionStorage.setItem("reset_email", email);
    
    await apiFetch("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) });
    el("formView").classList.add("hidden");
    el("successView").classList.remove("hidden");
  } catch (err) {
    errorEl.textContent = err.status === 429
      ? "Too many attempts — please wait a while before trying again."
      : "Something went wrong sending that — please try again.";
    errorEl.classList.remove("hidden");
    submitBtn.disabled = false;
    submitBtn.textContent = "Send reset code";
  }
});