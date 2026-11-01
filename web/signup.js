import { apiFetch } from "./api.js";

const el = (id) => document.getElementById(id);
let registeredEmail = "";

function setupVisibility(inputId, btnId) {
  const input = el(inputId);
  const btn = el(btnId);
  btn.addEventListener("click", () => {
    const isPw = input.type === "password";
    input.type = isPw ? "text" : "password";
    btn.textContent = isPw ? "Hide" : "Show";
  });
}
setupVisibility("password", "togglePw");
setupVisibility("confirmPassword", "toggleConfirm");

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

el("signupForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = el("formError");
  const submitBtn = el("submitBtn");
  const password = el("password").value;
  const confirm = el("confirmPassword").value;
  
  errorEl.classList.add("hidden");
  el("matchError").classList.add("hidden");

  if (password !== confirm) {
    el("matchError").classList.remove("hidden");
    return;
  }
  if (password.length < 8) {
    errorEl.textContent = "Password must be at least 8 characters.";
    errorEl.classList.remove("hidden");
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = "Creating account...";

  try {
    registeredEmail = el("email").value.trim();
    const body = { 
      email: registeredEmail, 
      password, 
      display_name: el("displayName").value.trim(),
      phone: el("phone").value.trim(),
      university: el("university").value,
      course: el("course").value.trim()
    };
    
    await apiFetch("/auth/signup", { method: "POST", body: JSON.stringify(body) });

    el("formView").classList.add("hidden");
    el("otpView").classList.remove("hidden");
    el("sentEmail").textContent = registeredEmail;
  } catch (err) {
    errorEl.textContent = err.status === 429
      ? "Too many attempts — please wait a while before trying again."
      : err.message || "Failed to create account.";
    errorEl.classList.remove("hidden");
    submitBtn.disabled = false;
    submitBtn.textContent = "Create account";
  }
});

el("otpForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorEl = el("otpError");
  const verifyBtn = el("verifyBtn");
  errorEl.classList.add("hidden");

  const token = el("otpCode").value.trim();
  if (token.length !== 6) {
    errorEl.textContent = "Please enter the complete 6-digit verification code.";
    errorEl.classList.remove("hidden");
    return;
  }

  verifyBtn.disabled = true;
  verifyBtn.textContent = "Verifying...";

  try {
    await apiFetch("/auth/verify-signup-otp", {
      method: "POST",
      body: JSON.stringify({ email: registeredEmail, token, new_password: "" })
    });

    el("otpView").classList.add("hidden");
    el("successView").classList.remove("hidden");
  } catch (err) {
    errorEl.textContent = err.message || "Invalid or expired verification code.";
    errorEl.classList.remove("hidden");
    verifyBtn.disabled = false;
    verifyBtn.textContent = "Verify and Sign in";
  }
});