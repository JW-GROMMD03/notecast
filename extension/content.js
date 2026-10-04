if (typeof window.noteCastInjected === 'undefined') {
  window.noteCastInjected = true;

  // CRITICAL FIX: Changed from 1000ms to 15000ms to stop Chrome IPC memory crashes
  const FRAME_INTERVAL_MS = 15000; 
  const FRAME_MAX_WIDTH = 640;

  let frameTimer = null;
  let autoStarted = false;

  function getVideoElement() {
    return document.querySelector("video.html5-main-video") || document.querySelector("video");
  }

  // Detects if a YouTube advertisement is currently playing
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
          autoStarted = true;
          const meta = extractMeta();
          try {
            chrome.runtime.sendMessage({
              scope: "notecast",
              type: "AUTO_START_CAPTURE",
              payload: { videoMeta: meta }
            }).catch(() => {});
          } catch (e) {}
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

    // Skip frame capture entirely if a YouTube ad is currently showing
    if (isAdShowing()) {
      return;
    }

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

        // Secondary ad check in case an ad started while processing the blob
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
      0.6
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