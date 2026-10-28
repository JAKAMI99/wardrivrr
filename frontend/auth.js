const AUTH_TOKEN_KEY = "wardrivrr_token";
const AUTH_REMEMBER_KEY = "wardrivrr_remember";

function getToken() {
  try {
    return (
      sessionStorage.getItem(AUTH_TOKEN_KEY) ||
      localStorage.getItem(AUTH_TOKEN_KEY) ||
      null
    );
  } catch (_) {
    return null;
  }
}

function setToken(token, keepLoggedIn = false) {
  try {
    sessionStorage.removeItem(AUTH_TOKEN_KEY);
    sessionStorage.removeItem(AUTH_REMEMBER_KEY);
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_REMEMBER_KEY);
  } catch (_) {}
  if (!token) return;
  const store = keepLoggedIn ? localStorage : sessionStorage;
  try {
    store.setItem(AUTH_TOKEN_KEY, token);
    store.setItem(AUTH_REMEMBER_KEY, keepLoggedIn ? "1" : "0");
  } catch (_) {}
}

function authHeaders(extra = {}) {
  const headers = { ...extra };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function apiFetch(url, options = {}) {
  const { redirectOn401 = true, ...rest } = options;
  const opts = { ...rest };
  opts.credentials = opts.credentials || "same-origin";
  opts.headers = authHeaders(opts.headers || {});
  const res = await fetch(url, opts);
  if (
    redirectOn401 &&
    res.status === 401 &&
    !String(url).includes("/api/auth/login")
  ) {
    setToken(null);
    if (!location.pathname.startsWith("/login")) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    }
  }
  return res;
}

async function requireAuth() {
  const res = await apiFetch("/api/auth/me");
  if (!res.ok) {
    setToken(null);
    if (!location.pathname.startsWith("/login")) {
      location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    }
    return null;
  }
  return res.json();
}

async function logout() {
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    });
  } catch (_) {}
  setToken(null);
  // Guests always get classic - don't leave the previous user's theme sticky
  if (window.WardTheme?.applyGuestClassic) {
    WardTheme.applyGuestClassic({ broadcast: false });
  }
  location.href = "/login";
}

window.WardAuth = { getToken, setToken, authHeaders, apiFetch, requireAuth, logout };
