import { apiFetch } from "./api.js";

const el = (id) => document.getElementById(id);
let registeredEmail = "";

// --- AUTO-FILL REFERRAL FROM URL ---
document.addEventListener("DOMContentLoaded", () => {
  const urlParams = new URLSearchParams(window.location.search);
  const refCode = urlParams.get('ref');
  
  if (refCode) {
    const refInput = el("referralCode");
    if (refInput) {
      refInput.value = refCode.toUpperCase();
      refInput.readOnly = true; 
      refInput.style.backgroundColor = "#f8fafc"; // Visual lock
    }
  }
});

function setupVisibility(inputId, btnId) {
  const input = el(inputId);
  const btn = el(btnId);
  if(!input || !btn) return;
  btn.addEventListener("click", () => {
    const isPw = input.type === "password";
    input.type = isPw ? "text" : "password";
    btn.textContent = isPw ? "Hide" : "Show";
  });
}
setupVisibility("password", "togglePw");
setupVisibility("confirmPassword", "toggleConfirm");

const passwordInput = el("password");
if (passwordInput) {
  passwordInput.addEventListener("input", (e) => {
    const pw = e.target.value;
    let score = 0;
    if (pw.length > 7) score++;
    if (/[A-Z]/.test(pw)) score++;
    if (/[0-9]/.test(pw)) score++;
    if (/[^A-Za-z0-9]/.test(pw)) score++;
    
    const bar = el("strengthBar");
    const hint = el("strengthHint");
    
    if(!bar || !hint) return;
    
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
}

// --- DYNAMIC RESEND TIMER LOGIC ---
let resendTimer = null;
let resendCooldown = 60; // 60 seconds

function startResendTimer() {
  const otpForm = el("otpForm");
  let resendContainer = el("resendContainer");
  
  // Dynamically create the resend UI if it doesn't exist
  if (!resendContainer) {
      resendContainer = document.createElement("div");
      resendContainer.id = "resendContainer";
      resendContainer.style.marginTop = "20px";
      resendContainer.style.textAlign = "center";
      resendContainer.style.fontSize = "0.85rem";
      
      const resendBtn = document.createElement("button");
      resendBtn.id = "resendBtn";
      resendBtn.type = "button";
      resendBtn.style.background = "none";
      resendBtn.style.border = "none";
      resendBtn.style.color = "#3b82f6";
      resendBtn.style.cursor = "pointer";
      resendBtn.style.textDecoration = "underline";
      resendBtn.style.fontWeight = "600";
      
      const timerText = document.createElement("span");
      timerText.id = "resendTimerText";
      timerText.style.color = "#94a3b8";
      timerText.style.marginLeft = "8px";
      
      resendContainer.appendChild(resendBtn);
      resendContainer.appendChild(timerText);
      otpForm.appendChild(resendContainer);

      resendBtn.addEventListener("click", async () => {
          if (resendBtn.disabled) return;
          
          resendBtn.disabled = true;
          resendBtn.textContent = "Sending...";
          const errorEl = el("otpError");
          errorEl.classList.add("hidden");

          try {
              await apiFetch("/auth/resend-otp", {
                  method: "POST",
                  body: JSON.stringify({ email: registeredEmail })
              });
              resendBtn.textContent = "Code Sent!";
              setTimeout(() => startResendTimer(), 2000); // Restart cooldown
          } catch (err) {
              errorEl.textContent = err.message || "Failed to resend code. Try again later.";
              errorEl.classList.remove("hidden");
              resendBtn.textContent = "Resend Code";
              resendBtn.disabled = false;
          }
      });
  }

  const resendBtn = el("resendBtn");
  const timerText = el("resendTimerText");
  
  resendBtn.disabled = true;
  resendBtn.style.color = "#64748b";
  resendBtn.style.cursor = "not-allowed";
  resendBtn.style.textDecoration = "none";
  resendBtn.textContent = "Resend Code";
  
  resendCooldown = 60;
  timerText.textContent = `(in ${resendCooldown}s)`;

  if (resendTimer) clearInterval(resendTimer);
  
  resendTimer = setInterval(() => {
      resendCooldown--;
      if (resendCooldown <= 0) {
          clearInterval(resendTimer);
          resendBtn.disabled = false;
          resendBtn.style.color = "#3b82f6";
          resendBtn.style.cursor = "pointer";
          resendBtn.style.textDecoration = "underline";
          timerText.textContent = "";
      } else {
          timerText.textContent = `(in ${resendCooldown}s)`;
      }
  }, 1000);
}

const signupForm = el("signupForm");
if (signupForm) {
  signupForm.addEventListener("submit", async (e) => {
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
      
      const universityVal = el("university") ? el("university").value : "";
      const courseVal = el("course") ? el("course").value.trim() : "";
      const phoneVal = el("phone") ? el("phone").value.trim() : "";
      const displayNameVal = el("displayName") ? el("displayName").value.trim() : "";
      const refCodeVal = el("referralCode") ? el("referralCode").value.trim().toUpperCase() : "";

      const body = { 
        email: registeredEmail, 
        password, 
        display_name: displayNameVal,
        phone: phoneVal,
        university: universityVal,
        course: courseVal,
        referral_code: refCodeVal 
      };
      
      await apiFetch("/auth/signup", { method: "POST", body: JSON.stringify(body) });

      el("formView").classList.add("hidden");
      el("otpView").classList.remove("hidden");
      el("sentEmail").textContent = registeredEmail;

      // Start the dynamic resend timer here
      startResendTimer();

    } catch (err) {
      errorEl.textContent = err.status === 429
        ? "Too many attempts — please wait a while before trying again."
        : err.message || "Failed to create account.";
      errorEl.classList.remove("hidden");
      submitBtn.disabled = false;
      submitBtn.textContent = "Create account";
    }
  });
}

const otpForm = el("otpForm");
if (otpForm) {
  otpForm.addEventListener("submit", async (e) => {
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
}