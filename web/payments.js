import { apiFetch, requireAuth } from "./api.js";

const el = (id) => document.getElementById(id);

// Config catalog
const PLANS = {
  "ECONOMY_NOTE": { amount: 50, name: "Economy Note Token (Pay-As-You-Go)" },
  "STARTUP": { amount: 100, name: "Startup Plan (Monthly)" },
  "BASIC": { amount: 250, name: "Basic Plan (Monthly)" },
  "STANDARD": { amount: 800, name: "Standard Plan (Monthly)" },
  "PREMIUM": { amount: 1199, name: "Premium Plan (Monthly)" }
};

// Aliases mapping old landing page keys to active backend keys
const PLAN_ALIASES = {
  "quick": "ECONOMY_NOTE",
  "lecture": "STARTUP",
  "master": "BASIC",
  "weekly": "STANDARD",
  "monthly": "PREMIUM"
};

let currentPlanId = "STANDARD";
let currentTxId = null;
let pollInterval = null;

function getSelectedPlan() {
  const fullSearch = window.location.search;
  let rawKey = "STANDARD";
  
  if (fullSearch.includes("plan=")) {
    const parts = fullSearch.split("plan=");
    if (parts.length > 1) {
      rawKey = parts[1].split("&")[0].trim();
    }
  } else {
    const urlParams = new URLSearchParams(fullSearch);
    if (urlParams.has("plan")) rawKey = urlParams.get("plan");
  }

  // Resolve alias if needed
  if (PLAN_ALIASES[rawKey]) {
    rawKey = PLAN_ALIASES[rawKey];
  }
  
  return PLANS[rawKey] ? rawKey : "STANDARD";
}

currentPlanId = getSelectedPlan();
const planInfo = PLANS[currentPlanId];

// Update DOM
if (el("planName")) el("planName").textContent = planInfo.name;
if (el("planPrice")) el("planPrice").textContent = `${planInfo.amount} KES`;

// Background auth check
requireAuth().catch(() => {
  window.location.href = `login.html?redirect=payments.html%3Fplan=${currentPlanId}`;
});

// Sanitization for Safaricom phone numbers
function cleanPhoneNumber(raw) {
  let digits = raw.replace(/[^0-9]/g, "");
  if (digits.startsWith("0")) {
    digits = "254" + digits.substring(1);
  } else if (digits.length === 9 && (digits.startsWith("7") || digits.startsWith("1"))) {
    digits = "254" + digits;
  }
  return digits;
}

// Payment Form Submit
const paymentForm = el("paymentForm");
if (paymentForm) {
  paymentForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    
    const phoneInput = el("phone").value.trim();
    const phone = cleanPhoneNumber(phoneInput);
    const errorEl = el("paymentError");
    const payBtn = el("payBtn");

    if (phone.length !== 12 || !phone.startsWith("254")) {
      if (errorEl) {
        errorEl.textContent = "Please enter a valid Safaricom phone number (e.g. 0703250550 or 254703250550).";
        errorEl.classList.remove("hidden");
      }
      return;
    }

    if (errorEl) errorEl.classList.add("hidden");
    payBtn.disabled = true;
    payBtn.innerHTML = `<div class="spinner"></div> Processing...`;

    try {
      const data = await apiFetch("/payments/stk-push", {
        method: "POST",
        body: JSON.stringify({
          phone_number: phone,
          plan_name: currentPlanId,
          amount: planInfo.amount
        })
      });
      
      paymentForm.classList.add("hidden");
      if (el("pollingUI")) el("pollingUI").classList.remove("hidden");
      
      currentTxId = data.transaction_id;
      startPolling();
      
    } catch (err) {
      if (errorEl) {
        errorEl.textContent = err.detail || "Payment initiation failed. Please check your number.";
        errorEl.classList.remove("hidden");
      }
      payBtn.disabled = false;
      payBtn.textContent = "Pay Now";
    }
  });
}

function startPolling() {
  let attempts = 0;
  
  pollInterval = setInterval(async () => {
    attempts++;
    if (attempts > 60) {
      clearInterval(pollInterval);
      showCompletionUI("TIMEOUT", "Payment confirmation timed out. Contact support if charged.");
      return;
    }
    
    try {
      const data = await apiFetch(`/payments/status/${currentTxId}`);
      
      if (data.status === "COMPLETED") { 
        clearInterval(pollInterval);
        showCompletionUI("SUCCESS", "Payment Successful! Your account features have been updated.");
      } 
      else if (data.status === "FAILED") {
        clearInterval(pollInterval);
        showCompletionUI("FAILED", "Payment was cancelled or rejected on M-Pesa.");
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  }, 5000);
}

function showCompletionUI(status, message) {
  const statusContainer = el("pollingStatus");
  const actionButtons = el("actionButtons");

  if (statusContainer) {
    const color = status === "SUCCESS" ? "#10b981" : "#ef4444";
    const heading = status === "SUCCESS" ? "Payment Successful" : "Transaction Failed";
    statusContainer.innerHTML = `
      <h3 style="color: ${color}; margin-top: 10px;">${heading}</h3>
      <p style="color: var(--text-muted); font-size: 0.95rem;">${message}</p>
    `;
  }
  
  if (actionButtons) {
    actionButtons.classList.remove("hidden");
  }
}