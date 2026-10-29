import { authedFetch, requireAuth } from "./api.js";

const el = (id) => document.getElementById(id);

// Config catalog
const PLANS = {
  "ECONOMY_NOTE": { amount: 50, name: "Economy Note Token (Pay-As-You-Go)" },
  "STARTUP": { amount: 100, name: "Startup Plan (Weekly)" },
  "BASIC": { amount: 250, name: "Basic Plan (Monthly)" },
  "STANDARD": { amount: 800, name: "Standard Plan (Monthly)" },
  "PREMIUM": { amount: 2500, name: "Premium Plan (Monthly)" },
  "DOWNLOAD_PASS": { amount: 20, name: "Weekly Download Pass (1 Week Access)" }
};

const PLAN_ALIASES = {
  "quick": "ECONOMY_NOTE",
  "lecture": "STARTUP",
  "master": "BASIC",
  "weekly": "STANDARD",
  "monthly": "PREMIUM",
  "download_pass": "DOWNLOAD_PASS"
};

let currentPlanId = "STANDARD";
let currentTxId = null;
let pollInterval = null;

const urlParams = new URLSearchParams(window.location.search);
let returnUrl = urlParams.get("redirect") || "";

function getSelectedPlan() {
  let rawKey = urlParams.get("plan") || "STANDARD";
  if (PLAN_ALIASES[rawKey]) {
    rawKey = PLAN_ALIASES[rawKey];
  }
  return PLANS[rawKey] ? rawKey : "STANDARD";
}

currentPlanId = getSelectedPlan();
const planInfo = PLANS[currentPlanId];

if (el("planName")) el("planName").textContent = planInfo.name;
if (el("planPrice")) el("planPrice").textContent = `${planInfo.amount} KES`;

requireAuth().catch(() => {
  window.location.href = `login.html?redirect=payments.html%3Fplan=${currentPlanId}`;
});

function cleanPhoneNumber(raw) {
  let digits = raw.replace(/[^0-9]/g, "");
  if (digits.startsWith("0")) digits = "254" + digits.substring(1);
  else if (digits.length === 9 && (digits.startsWith("7") || digits.startsWith("1"))) digits = "254" + digits;
  return digits;
}

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
      const res = await authedFetch("/payments/stk-push", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone_number: phone,
          plan_name: currentPlanId,
          amount: planInfo.amount
        })
      });
      
      let data = res;
      if (res.json) data = await res.json();
      
      paymentForm.classList.add("hidden");
      if (el("pollingUI")) el("pollingUI").classList.remove("hidden");
      
      currentTxId = data.transaction_id;
      startFastPolling();
      
    } catch (err) {
      if (errorEl) {
        errorEl.textContent = err.message || err.detail || "Payment initiation failed. Please check your number.";
        errorEl.classList.remove("hidden");
      }
      payBtn.disabled = false;
      payBtn.textContent = "Pay Now";
    }
  });
}

function startFastPolling() {
  const startedAt = Date.now();
  const MAX_MS = 120000; // Allow exactly 120 seconds maximum timeout

  const tick = async () => {
    if (Date.now() - startedAt > MAX_MS) {
      showCompletionUI("TIMEOUT", "We couldn't confirm your payment. If money was deducted, your access will unlock automatically within a few minutes.");
      return;
    }

    try {
      const res = await authedFetch(`/payments/status/${currentTxId}`);
      let data = res;
      if (res.json) data = await res.json();
      
      if (data.status === "COMPLETED") { 
        showCompletionUI("SUCCESS", "Payment Successful! Unlocking your downloads & redirecting...");
        
        setTimeout(() => {
          if (returnUrl) {
            window.location.href = decodeURIComponent(returnUrl);
          } else {
            window.location.href = "dashboard.html";
          }
        }, 1500);
        return; // Break the recursive loop
      } 
      
      if (data.status === "FAILED") {
        showCompletionUI("FAILED", "Transaction was cancelled or failed on your phone.");
        return; // Break the recursive loop
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
    
    // Check again in 2 seconds (non-overlapping chain so Daraja has time to breathe)
    pollInterval = setTimeout(tick, 2000);
  };
  
  tick();
}

function showCompletionUI(status, message) {
  const statusContainer = el("pollingStatus");
  const actionButtons = el("actionButtons");

  if (statusContainer) {
    const color = status === "SUCCESS" ? "#10b981" : (status === "TIMEOUT" ? "#f59e0b" : "#ef4444");
    const heading = status === "SUCCESS" ? "Payment Successful 🎉" : (status === "TIMEOUT" ? "Payment Pending ⏳" : "Payment Cancelled / Failed ❌");
    
    statusContainer.innerHTML = `
      <div style="margin-bottom: 16px;">
        <h3 style="color: ${color}; margin-top: 10px; font-size: 1.4rem;">${heading}</h3>
        <p style="color: var(--text-muted); font-size: 0.95rem; margin-top: 8px;">${message}</p>
      </div>
      ${status !== "SUCCESS" ? `<button onclick="window.location.reload()" class="btn-primary" style="margin-top: 12px; padding: 10px 20px; background: var(--primary); color: white; border: none; border-radius: 6px; cursor: pointer;">Try Again</button>` : ''}
    `;
  }
  
  if (actionButtons) {
    actionButtons.classList.remove("hidden");
  }
}