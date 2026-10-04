let currentStream = null;
let rawCaptureStream = null;
let isRecording = false;

const CHUNK_DURATION_MS = 2000;

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.scope !== "notecast-offscreen") return;

  if (message.type === "START_AUDIO") {
    startAudioCapture(message.streamId)
      .then(() => sendResponse({ ok: true }))
      .catch((err) => {
        console.error("NoteCast Offscreen: Start failed", err);
        sendResponse({ ok: false, error: err.message });
      });
    return true; 
  } 
  
  if (message.type === "STOP_AUDIO") {
    stopAudioCapture();
    sendResponse({ ok: true });
    return true;
  }
});

async function startAudioCapture(streamId) {
  stopAudioCapture(); 

  let rawStream;
  try {
    // CRITICAL FIX: Changed from "desktop" to "tab" to match the new tabCapture method.
    rawStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: "tab",
          chromeMediaSourceId: streamId,
        },
      },
      video: {
        mandatory: {
          chromeMediaSource: "tab",
          chromeMediaSourceId: streamId,
        },
      },
    });
  } catch (err) {
    throw new Error(`Media Capture Failed (${err.name}): ${err.message}`);
  }

  const audioTracks = rawStream.getAudioTracks();
  if (audioTracks.length === 0) {
    rawStream.getTracks().forEach(t => t.stop());
    throw new Error("No audio tracks found in the active stream.");
  }

  rawCaptureStream = rawStream;
  currentStream = new MediaStream(audioTracks);
  isRecording = true;

  recordStandaloneChunk();
}

function recordStandaloneChunk() {
  if (!isRecording || !currentStream || !currentStream.active) return;

  let recorder;
  try {
    recorder = new MediaRecorder(currentStream, { mimeType: "audio/webm;codecs=opus" });
  } catch (e) {
    recorder = new MediaRecorder(currentStream);
  }

  const chunks = [];

  recorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) {
      chunks.push(event.data);
    }
  };

  recorder.onstop = () => {
    if (chunks.length > 0 && isRecording) {
      const blob = new Blob(chunks, { type: "audio/webm" });
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64data = reader.result.split(",")[1];
        if (base64data) {
          chrome.runtime.sendMessage({
            scope: "notecast",
            type: "AUDIO_CHUNK",
            seq: Date.now(),
            data_b64: base64data,
            duration_ms: CHUNK_DURATION_MS,
          }).catch(() => {});
        }
      };
      reader.readAsDataURL(blob);
    }

    if (isRecording) {
      setTimeout(recordStandaloneChunk, 50);
    }
  };

  recorder.start();

  setTimeout(() => {
    if (recorder && recorder.state === "recording") {
      recorder.stop();
    }
  }, CHUNK_DURATION_MS);
}

function stopAudioCapture() {
  isRecording = false;
  
  if (currentStream) {
    currentStream.getTracks().forEach((track) => track.stop());
    currentStream = null;
  }
  if (rawCaptureStream) {
    rawCaptureStream.getTracks().forEach((track) => track.stop());
    rawCaptureStream = null;
  }
}