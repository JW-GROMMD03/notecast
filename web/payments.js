import { apiFetch, requireAuth } from "./api.js";

const el = (id) => document.getElementById(id);

// Plan configuration matching your backend and landing page
const PLANS = {
  "quick": { amount: 40, name: "Quick Crash Pass" },
  "lecture": { amount: 60, name: "Standard Lecture" },
  "master": { amount: 150, name: "Extended Master" },
  "weekly": { amount: 500, name: "Weekly Scholar" },
  "monthly": { amount: 1200, name: "Monthly Pro" }
};

let currentPlanId = "weekly"; // Default fallback
let currentTxId = null;
let pollInterval = null;

// 1. ROBUSTLY PARSE PLAN FROM URL (Handles nested redirects and standard queries)
function getSelectedPlan() {
  const fullSearch = window.location.search;
  
  // Check if there's a nested redirect parameter (e.g., ?redirect=payments.html%3Fplan=weekly)
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
  
  return "weekly";
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
      alert("Payment confirmation timed out. If you were charged, please contact support.");
      window.location.reload();
      return;
    }
    
    try {
      const data = await apiFetch(`/payments/status/${currentTxId}`);
      
      if (data.status === "completed") {
        clearInterval(pollInterval);
        if (el("pollingUI")) {
          el("pollingUI").innerHTML = `<h3 style="color: #10b981;">Payment Successful!</h3><p>Redirecting to your dashboard...</p>`;
        }
        setTimeout(() => window.location.href = "dashboard.html", 2000);
      } 
      else if (data.status === "failed") {
        clearInterval(pollInterval);
        alert("Payment failed or was cancelled.");
        window.location.reload();
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  }, 5000);
}