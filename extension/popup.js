import { API_BASE } from "./config.js";

document.getElementById("launchBtn").addEventListener("click", async () => {
  const btn = document.getElementById("launchBtn");
  const errorEl = document.getElementById("errorMsg");
  const statusEl = document.getElementById("statusMsg");
  
  btn.disabled = true;
  errorEl.textContent = "";
  statusEl.textContent = "Checking active plan...";

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url || !tab.url.includes("youtube.com/watch")) {
      throw new Error("Please open an active YouTube video watch page first.");
    }

    // 1. Verify Tier Limit BEFORE Capturing
    chrome.runtime.sendMessage({ type: "CHECK_ENTITLEMENT", action: "YOUTUBE_CAPTURE" }, async (response) => {
        if (!response || !response.success) {
            errorEl.textContent = response?.error || "Plan limit reached. Please upgrade.";
            statusEl.textContent = "Capture blocked.";
            btn.disabled = false;
            return;
        }

        statusEl.textContent = "Requesting tab capture access…";

        try {
            // --> FIX: Programmatically open the Side Panel for the current window
            await chrome.sidePanel.open({ windowId: tab.windowId });

            const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
            const title = tab.title.replace(/\s*-\s*YouTube$/, "").trim();

            const result = await chrome.runtime.sendMessage({
              scope: "notecast",
              type: "START_CAPTURE_WITH_STREAM",
              payload: {
                tabId: tab.id,
                videoMeta: { youtube_id: new URL(tab.url).searchParams.get("v"), title, channel: "YouTube Creator" },
                streamId
              }
            });

            if (!result.ok) {
              throw new Error(result.error || "Failed to initialize backend session.");
            }

            statusEl.textContent = "Capture active! Side panel opened.";
            // Close the popup so the user can focus on the side panel
            setTimeout(() => window.close(), 1000);
        } catch (e) {
            console.error(e);
            errorEl.textContent = e.message;
            statusEl.textContent = "Capture failed.";
            btn.disabled = false;
        }
    });

  } catch (err) {
    console.error(err);
    errorEl.textContent = err.message;
    statusEl.textContent = "Error.";
    btn.disabled = false;
  }
});