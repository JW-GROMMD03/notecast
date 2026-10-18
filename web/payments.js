import { apiFetch, requireAuth } from "./api.js";

const el = (id) => document.getElementById(id);

// Plan configuration matching your FastAPI backend and landing page
const PLANS = {
  "ECONOMY_NOTE": { amount: 50, name: "Economy Note Token (Pay-As-You-Go)" },
  "STARTUP": { amount: 100, name: "Startup Plan (Monthly)" },
  "BASIC": { amount: 250, name: "Basic Plan (Monthly)" },
  "STANDARD": { amount: 800, name: "Standard Plan (Monthly)" },
  "PREMIUM": { amount: 1199, name: "Premium Plan (Monthly)" }
};

let currentPlanId = "STANDARD"; // Default fallback
let currentTxId = null;
let pollInterval = null;

// 1. ROBUSTLY PARSE PLAN FROM URL (Handles nested redirects and standard queries)
function getSelectedPlan() {
  const fullSearch = window.location.search;
  
  // Check if there's a nested redirect parameter (e.g., ?redirect=payments.html%3Fplan=STANDARD)
  if (fullSearch.includes("plan=")) {
    const parts = fullSearch.split("plan=");
    if (parts.length > 1) {
      // Clean up any trailing characters or ampersands
      const planKey = parts[1].split("&")[0].trim();
      if (PLANS[planKey]) {
        return planKey;
      }
    }
  }
  
  // Fallback to standard URL search params
  const urlParams = new URLSearchParams(fullSearch);
  const planParam = urlParams.get("plan");
  if (planParam && PLANS[planParam]) {
    return planParam;
  }
  
  return "STANDARD";
}

currentPlanId = getSelectedPlan();
const planInfo = PLANS[currentPlanId];

// Instantly update the DOM elements
if (el("planName")) el("planName").textContent = planInfo.name;
if (el("planPrice")) el("planPrice").textContent = `${planInfo.amount} KES`;

// 2. VERIFY AUTHENTICATION IN BACKGROUND
requireAuth().catch(() => {
  // If not authenticated, redirect to login while preserving the exact plan choice
  window.location.href = `login.html?redirect=payments.html%3Fplan=${currentPlanId}`;
});

// 3. Handle Payment Form Submission
const paymentForm = el("paymentForm");
if (paymentForm) {
  paymentForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    
    const phone = el("phone").value.trim();
    const errorEl = el("paymentError");
    const payBtn = el("payBtn");

    if (errorEl) errorEl.classList.add("hidden");
    payBtn.disabled = true;
    payBtn.innerHTML = `<div class="spinner" style="width: 14px; height: 14px; border-width: 2px; border-top-color: white;"></div> Processing...`;

    try {
      const data = await apiFetch("/payments/stk-push", {
        method: "POST",
        body: JSON.stringify({
          phone_number: phone,
          plan_name: currentPlanId,
          amount: planInfo.amount
        })
      });
      
      // Hide form, show polling UI
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

// 4. Poll backend for Safaricom confirmation
function startPolling() {
  let attempts = 0;
  
  pollInterval = setInterval(async () => {
    attempts++;
    if (attempts > 60) { // Timeout after ~5 minutes
      clearInterval(pollInterval);
      showCompletionUI("TIMEOUT", "Payment confirmation timed out. If you were charged, please contact support.");
      return;
    }
    
    try {
      const data = await apiFetch(`/payments/status/${currentTxId}`);
      
      if (data.status === "COMPLETED") { 
        clearInterval(pollInterval);
        showCompletionUI("SUCCESS", "Payment Successful! Your account has been upgraded.");
      } 
      else if (data.status === "FAILED") {
        clearInterval(pollInterval);
        showCompletionUI("FAILED", "Payment failed or was cancelled.");
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  }, 5000);
}

// 5. Handle UI State on Success/Failure
function showCompletionUI(status, message) {
  const statusContainer = el("pollingStatus");
  const actionButtons = el("actionButtons");

  if (statusContainer) {
    const color = status === "SUCCESS" ? "#10b981" : "#ef4444";
    const heading = status === "SUCCESS" ? "Success!" : "Transaction Failed";
    statusContainer.innerHTML = `<h3 style="color: ${color}; margin-top: 10px;">${heading}</h3><p style="color: var(--text-muted); font-size: 0.95rem;">${message}<br><br>Redirecting to plans in 5 seconds...</p>`;
  }
  
  if (actionButtons) {
    actionButtons.classList.remove("hidden");
  }

  // Automatically redirect to the plans section after 5 seconds
  setTimeout(() => {
    window.location.href = "index.html#pricing";
  }, 5000);
}