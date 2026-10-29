const toast = document.getElementById("toast");
let lastSearchAfter = null;
let lastQuery = null;

function showToast(message, isError = false) {
  toast.hidden = false;
  toast.textContent = message;
  toast.classList.toggle("error", isError);
}

function buildParams(extra = {}) {
  const p = new URLSearchParams();
  const ssid = document.getElementById("ssid").value.trim();
  const mac = document.getElementById("mac").value.trim();
  const place = document.getElementById("place").value.trim();
  const postalcode = document.getElementById("postalcode").value.trim();
  const country = document.getElementById("country").value.trim();
  const type = document.getElementById("type").value;
  const near = document.getElementById("near").value.trim();
  const radius = document.getElementById("radius").value;
  const limit = document.getElementById("limit").value;
  if (ssid) p.set("ssid", ssid);
  if (mac) p.set("mac", mac);
  if (place) p.set("place", place);
  if (postalcode) p.set("postalcode", postalcode);
  if (country) p.set("country", country);
  if (type) p.set("type", type);
  if (near) {
    p.set("near", near);
    p.set("radius_m", radius || "500");
  }
  if (limit) p.set("limit", limit);
  if (document.getElementById("reverse").checked) p.set("reverse", "true");
  Object.entries(extra).forEach(([k, v]) => {
    if (v != null && v !== "") p.set(k, v);
  });
  return p;
}

function curlFor(params) {
  const key = document.getElementById("apiKeyInput").value.trim();
  const url = `${location.origin}/api/v2/network/search?${params.toString()}`;
  if (key) {
    return `curl -s -H "X-API-Key: ${key}" \\\n  "${url}"`;
  }
  return `curl -s -H "Authorization: Bearer <token-or-wr_key>" \\\n  "${url}"`;
}

function updateCurl(params) {
  document.getElementById("curlBox").textContent = curlFor(params);
}

function paintResults(data) {
  const meta = document.getElementById("resultMeta");
  meta.textContent = data.success
    ? `· ${data.resultCount} shown / ${data.totalResults} matched`
    : "";
  const hint = document.getElementById("geocodeHint");
  if (data.geocode) {
    const g = data.geocode;
    hint.textContent = `Area: ${g.display_name} · bbox ${
      data.bbox ? data.bbox.map((n) => Number(n).toFixed(4)).join(", ") : "-"
    }`;
  } else if (data.error) {
    hint.textContent = data.error;
  } else {
    hint.textContent = "";
  }

  const tbody = document.querySelector("#resultTable tbody");
  tbody.innerHTML = "";
  for (const r of data.results || []) {
    const tr = document.createElement("tr");
    const acc =
      r.location_accuracy_m != null ? `±${Number(r.location_accuracy_m).toFixed(0)}` : "-";
    const addr = r.address || r.place || [r.postcode, r.city].filter(Boolean).join(" ") || "-";
    tr.innerHTML = `
      <td>${escapeHtml(r.ssid || "-")}</td>
      <td><code>${escapeHtml(r.netid || "")}</code></td>
      <td>${escapeHtml(r.type || "")}</td>
      <td title="Estimated location accuracy">${acc}</td>
      <td title="${escapeAttr(addr)}">${escapeHtml(
      addr.length > 48 ? addr.slice(0, 46) + "..." : addr
    )}</td>
      <td>${r.sample_count ?? "-"}</td>
      <td><button type="button" class="btn" data-netid="${escapeAttr(r.netid)}">Detail</button></td>
    `;
    tbody.appendChild(tr);
  }
  tbody.querySelectorAll("[data-netid]").forEach((btn) => {
    btn.addEventListener("click", () => showDetail(btn.dataset.netid));
  });

  lastSearchAfter = data.searchAfter || null;
  document.getElementById("nextPage").hidden = !lastSearchAfter;

  const raw = document.getElementById("rawJson");
  raw.hidden = false;
  raw.textContent = JSON.stringify(data, null, 2);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/'/g, "&#39;");
}

async function runSearch(extra = {}) {
  const params = buildParams(extra);
  lastQuery = params;
  updateCurl(params);
  showToast("Searching...");
  const res = await WardAuth.apiFetch(`/api/v2/network/search?${params.toString()}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(data.detail || data.error || "Search failed", true);
    return;
  }
  if (!data.success) {
    showToast(data.error || "No area match", true);
  } else {
    showToast(`Found ${data.totalResults} network(s)`);
  }
  paintResults(data);
}

async function showDetail(netid) {
  const res = await WardAuth.apiFetch(
    `/api/v2/network/detail?netid=${encodeURIComponent(netid)}&include_samples=true`
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showToast(data.detail || "Detail failed", true);
    return;
  }
  const raw = document.getElementById("rawJson");
  raw.hidden = false;
  raw.textContent = JSON.stringify(data, null, 2);
  const r = data.result || {};
  showToast(
    `${r.ssid || "(no ssid)"} · ${r.place || r.city || ""} · samples ${
      r.samples?.count ?? r.sample_count ?? "-"
    }`
  );
}

document.getElementById("searchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  runSearch();
});

document.getElementById("copyCurl").addEventListener("click", async () => {
  const params = buildParams();
  updateCurl(params);
  const text = document.getElementById("curlBox").textContent;
  try {
    await navigator.clipboard.writeText(text);
    showToast("curl copied");
  } catch {
    showToast("Select and copy manually", true);
  }
});

document.getElementById("nextPage").addEventListener("click", () => {
  if (!lastSearchAfter) return;
  runSearch({ searchAfter: lastSearchAfter });
});

["ssid", "mac", "place", "postalcode", "country", "type", "near", "radius", "limit"].forEach(
  (id) => {
    document.getElementById(id).addEventListener("input", () => updateCurl(buildParams()));
    document.getElementById(id).addEventListener("change", () => updateCurl(buildParams()));
  }
);

(async () => {
  await WardAuth.requireAuth();
  updateCurl(buildParams());
  // Same-origin /api/docs reads wardrivrr_token from localStorage and Authorize's Bearer.
  const swagger = document.getElementById("openSwagger");
  if (swagger && !WardAuth.getToken()) {
    swagger.title = "Log in first - Swagger will pick up your token automatically";
  }
})();
