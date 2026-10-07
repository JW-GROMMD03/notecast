import { authedFetch, requireAuth, logout } from "./api.js";

const STATUS_LABEL = {
  initializing: "Starting…",
  capturing: "Capturing",
  processing: "Processing",
  completed: "Ready",
  failed: "Failed",
};

async function init() {
  const user = await requireAuth(); // redirects to login.html if not signed in
  document.getElementById("userName").textContent = user.display_name || user.email;

  document.getElementById("logoutBtn").addEventListener("click", async () => {
    await logout();
    window.location.href = "login.html";
  });

  await load();
}

async function load() {
  const videos = await authedFetch("/videos");
  const list = document.getElementById("videoList");
  if (!videos.length) {
    document.getElementById("emptyState").classList.remove("hidden");
    return;
  }
  list.innerHTML = videos
    .map(
      (v) => `
    <li>
      <a class="video-row" href="video.html?id=${v.id}">
        <div>
          <div class="video-row-title">${escapeHtml(v.title)}</div>
          <div class="video-row-meta">${escapeHtml(v.channel)} &middot; ${new Date(v.created_at).toLocaleDateString()}</div>
        </div>
        <span class="status-chip ${v.status}">${STATUS_LABEL[v.status] || v.status}</span>
      </a>
    </li>`
    )
    .join("");
}

function escapeHtml(str) {
  return (str || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

init();