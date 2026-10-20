if (typeof window.noteCastInjected === 'undefined') {
  window.noteCastInjected = true;

  const FRAME_INTERVAL_MS = 15000; 
  const FRAME_MAX_WIDTH = 640;

  let frameTimer = null;
  let autoStarted = false;
  let ncContainer = null;

  function getVideoElement() {
    return document.querySelector("video.html5-main-video") || document.querySelector("video");
  }

  function isAdShowing() {
    const player = document.querySelector("#movie_player") || document.querySelector(".html5-video-player");
    if (!player) return false;
    return player.classList.contains("ad-showing") || 
           player.classList.contains("ad-interrupting") || 
           document.querySelector(".ad-showing") !== null ||
           document.querySelector(".ytp-ad-player-overlay") !== null;
  }

  function extractMeta() {
    const url = new URL(location.href);
    const youtube_id = url.searchParams.get("v") || "";
    
    const titleEl = document.querySelector("h1.ytd-watch-metadata yt-formatted-string, h1.title yt-formatted-string, h1.style-scope.ytd-watch-metadata");
    const channelEl = document.querySelector("ytd-channel-name #text, #channel-name #text, a.yt-simple-endpoint.ytd-channel-name");
    const video = getVideoElement();

    let rawTitle = titleEl?.textContent || document.title || "Untitled video";
    rawTitle = rawTitle.replace(/\s*-\s*YouTube$/, "").trim();

    let rawChannel = channelEl?.textContent || "YouTube Creator";
    rawChannel = rawChannel.trim();

    return {
      youtube_id,
      title: rawTitle,
      channel: rawChannel,
      duration_sec: video ? Math.round(video.duration || 0) : 0,
    };
  }

  function monitorPlayback() {
    const video = getVideoElement();
    if (video && !autoStarted) {
      video.addEventListener("play", () => {
        if (!autoStarted && chrome?.runtime?.id) {
          // Playback monitor hook
        }
      });
    }
  }

  const playbackPoll = setInterval(() => {
    const video = getVideoElement();
    if (video) {
      monitorPlayback();
      clearInterval(playbackPoll);
    }
  }, 1000);

  function captureFrame() {
    if (!chrome?.runtime?.id) {
      if (frameTimer) {
        clearInterval(frameTimer);
        frameTimer = null;
      }
      return;
    }

    if (isAdShowing()) return;

    const video = getVideoElement();
    if (!video || video.paused || video.readyState < 2) return;

    const scale = Math.min(1, FRAME_MAX_WIDTH / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob(
      async (blob) => {
        if (!blob) return;
        const b64 = await blobToBase64(blob);
        
        if (!chrome?.runtime?.id) {
          if (frameTimer) clearInterval(frameTimer);
          return;
        }

        if (isAdShowing()) return;

        try {
          chrome.runtime.sendMessage({
            scope: "notecast",
            type: "FRAME",
            timestamp_ms: Math.round(video.currentTime * 1000),
            data_b64: b64,
          }).catch(() => {});
        } catch (e) {}
      },
      "image/webp",
      0.65
    );
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result.split(",")[1]);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  // --- FLOATING UI INJECTION ---
  function injectNoteCastUI() {
    if (document.getElementById('notecast-floating-ui')) return;
    if (!window.location.href.includes('watch?v=')) return;
  
    ncContainer = document.createElement('div');
    ncContainer.id = 'notecast-floating-ui';
    
    ncContainer.innerHTML = `
      <div class="nc-header">
        <span class="nc-title">NoteCast Studio</span>
        <button id="nc-close-btn" class="nc-close">&times;</button>
      </div>
      <div class="nc-body">
        <p>Automate notes for this video?</p>
        <button id="nc-start-btn" class="nc-btn">Start NoteCast</button>
        <div id="nc-status" class="nc-status hidden"></div>
      </div>
    `;
    document.body.appendChild(ncContainer);
  
    document.getElementById('nc-close-btn').addEventListener('click', () => {
      ncContainer.style.display = 'none';
    });
  
    document.getElementById('nc-start-btn').addEventListener('click', () => {
      const statusEl = document.getElementById('nc-status');
      const btn = document.getElementById('nc-start-btn');
      
      statusEl.textContent = 'Verifying active plan...';
      statusEl.className = 'nc-status';
      btn.disabled = true;
      
      try {
        chrome.runtime.sendMessage({ type: "CHECK_ENTITLEMENT", action: "YOUTUBE_CAPTURE" }, (response) => {
            if (response && response.success) {
                statusEl.textContent = '✅ Capturing! Notes will sync to your dashboard.';
                statusEl.style.color = '#10b981';
                btn.style.display = 'none';
                
                autoStarted = true;
                const meta = extractMeta();
                chrome.runtime.sendMessage({
                    scope: "notecast",
                    type: "AUTO_START_CAPTURE",
                    payload: { videoMeta: meta }
                }).catch(() => {});

            } else {
                statusEl.textContent = '❌ ' + (response?.error || 'Plan limit reached. Please upgrade.');
                statusEl.style.color = '#ef4444';
                btn.disabled = false;
            }
        });
      } catch(e) {
          statusEl.textContent = '❌ Extension error. Please reload.';
          statusEl.style.color = '#ef4444';
          btn.disabled = false;
      }
    });
  }

  document.addEventListener('yt-navigate-finish', () => {
    if (ncContainer) {
      ncContainer.style.display = window.location.href.includes('watch?v=') ? 'block' : 'none';
      const statusEl = document.getElementById('nc-status');
      if (statusEl) {
          statusEl.className = 'nc-status hidden';
          document.getElementById('nc-start-btn').style.display = 'block';
          document.getElementById('nc-start-btn').disabled = false;
      }
      if(frameTimer) {
          clearInterval(frameTimer);
          frameTimer = null;
      }
      autoStarted = false;
    } else {
      injectNoteCastUI();
    }
  });
  
  setTimeout(injectNoteCastUI, 1500);

  if (chrome?.runtime?.onMessage) {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message.scope === "notecast-content") {
        if (message.type === "START_FRAMES") {
          if (frameTimer) clearInterval(frameTimer);
          frameTimer = setInterval(captureFrame, FRAME_INTERVAL_MS);
          sendResponse({ ok: true });
        } else if (message.type === "STOP_FRAMES") {
          if (frameTimer) {
            clearInterval(frameTimer);
            frameTimer = null;
          }
          sendResponse({ ok: true });
        }
        return true;
      }
      if (message.scope === "notecast-meta" && message.type === "GET_META") {
        sendResponse(extractMeta());
        return true;
      }
    });
  }
}