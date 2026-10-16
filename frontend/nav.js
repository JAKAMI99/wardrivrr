/* Shared site nav — slim primary links + theme + account dropdown */
(function () {
  const PRIMARY = [
    { href: "/navigate", label: "Drive", match: ["/navigate"] },
    { href: "/levels", label: "Levels", match: ["/levels"] },
    { href: "/discover", label: "Discover", match: ["/discover"] },
    { href: "/database", label: "Database", match: ["/database"] },
    { href: "/status", label: "Status", match: ["/status"] },
  ];

  const ACCOUNT = [
    { href: "/stats", label: "Stats" },
    { href: "/achievements", label: "Achievements" },
    { href: "/api", label: "API" },
    { href: "/settings", label: "Settings" },
  ];

  const THEME_ICON = `<svg class="nav-theme-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
    <path fill="currentColor" d="M12 3a9 9 0 1 0 0 18c.7 0 1.2-.6 1.2-1.3 0-.3-.1-.6-.3-.9-.2-.3-.3-.6-.3-1 0-.8.7-1.5 1.5-1.5H16a5 5 0 0 0 0-10H12zm-5.5 9a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm3-4a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm5 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm2.5 4a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z"/>
  </svg>`;

  function pathActive(path, match) {
    return match.some((m) => path === m || path.startsWith(m + "/"));
  }

  function initials(name) {
    const s = String(name || "?").trim();
    if (!s) return "?";
    const parts = s.split(/[\s._-]+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return s.slice(0, 2).toUpperCase();
  }

  function closeMenus() {
    document.querySelectorAll(".account-menu.is-open").forEach((el) => {
      el.classList.remove("is-open");
      el.querySelector(".account-trigger")?.setAttribute("aria-expanded", "false");
      const drop = el.querySelector(".account-dropdown");
      if (drop) drop.hidden = true;
    });
    document.querySelectorAll(".nav-theme-menu.is-open").forEach((el) => {
      el.classList.remove("is-open");
      el.querySelector(".nav-theme-trigger")?.setAttribute("aria-expanded", "false");
      const drop = el.querySelector(".nav-theme-dropdown");
      if (drop) drop.hidden = true;
    });
  }

  function buildThemeMenu() {
    const wrap = document.createElement("div");
    wrap.className = "nav-theme-menu";
    wrap.setAttribute("data-kidcore-skip", "");
    wrap.innerHTML = `
      <button type="button" class="nav-theme-trigger" aria-expanded="false" aria-haspopup="true" title="Appearance" aria-label="Appearance">
        ${THEME_ICON}
      </button>
      <div class="nav-theme-dropdown" hidden>
        <p class="nav-theme-title" data-kidcore-skip>Appearance</p>
        <div class="nav-theme-list" data-kidcore-skip></div>
      </div>`;

    const trigger = wrap.querySelector(".nav-theme-trigger");
    const drop = wrap.querySelector(".nav-theme-dropdown");
    const list = wrap.querySelector(".nav-theme-list");

    if (window.WardTheme?.mountNavThemeMenu) {
      WardTheme.mountNavThemeMenu(list, {
        onPick: (id) => {
          WardTheme.saveToServer(id);
          closeMenus();
        },
      });
    } else {
      list.innerHTML = `<p class="muted">Theme unavailable</p>`;
    }

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = !wrap.classList.contains("is-open");
      closeMenus();
      if (open) {
        wrap.classList.add("is-open");
        drop.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
      } else {
        drop.hidden = true;
      }
    });
    drop.addEventListener("click", (e) => e.stopPropagation());
    return wrap;
  }

  function buildAccountMenu(user) {
    const wrap = document.createElement("div");
    wrap.className = "account-menu";
    const name = user?.username || "Account";
    const ini = initials(name);

    wrap.innerHTML = `
      <button type="button" class="account-trigger" aria-expanded="false" aria-haspopup="true">
        <span class="account-avatar" aria-hidden="true">${ini}</span>
        <span class="account-name">${name}</span>
        <span class="account-caret" aria-hidden="true"></span>
      </button>
      <div class="account-dropdown" hidden>
        <div class="account-dropdown-head">
          <span class="account-avatar lg" aria-hidden="true">${ini}</span>
          <div>
            <strong>${name}</strong>
            <span class="muted">${user?.is_admin ? "Admin" : "Explorer"}</span>
          </div>
        </div>
        <div class="account-dropdown-links">
          ${ACCOUNT.map((l) => `<a href="${l.href}">${l.label}</a>`).join("")}
        </div>
        <div class="account-dropdown-foot">
          <button type="button" class="account-logout" data-logout>Sign out</button>
        </div>
      </div>`;

    const trigger = wrap.querySelector(".account-trigger");
    const drop = wrap.querySelector(".account-dropdown");
    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = !wrap.classList.contains("is-open");
      closeMenus();
      if (open) {
        wrap.classList.add("is-open");
        drop.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
      } else {
        drop.hidden = true;
      }
    });
    wrap.querySelector("[data-logout]")?.addEventListener("click", () => {
      if (window.WardAuth?.logout) WardAuth.logout();
      else location.href = "/login";
    });
    return wrap;
  }

  function buildGuestLink() {
    const a = document.createElement("a");
    a.className = "btn btn-primary nav-signin";
    a.href = `/login?next=${encodeURIComponent(location.pathname)}`;
    a.textContent = "Sign in";
    return a;
  }

  async function resolveUser() {
    if (!window.WardAuth?.apiFetch) return null;
    try {
      const res = await WardAuth.apiFetch("/api/auth/me", {
        redirectOn401: false,
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async function mount() {
    const nav = document.querySelector(".site-nav");
    if (!nav || nav.dataset.wardNav === "1") return;
    nav.dataset.wardNav = "1";

    let links = nav.querySelector(".site-links");
    if (!links) {
      links = document.createElement("div");
      links.className = "site-links";
      nav.appendChild(links);
    }

    const path = location.pathname.replace(/\/$/, "") || "/";
    const isLogin = path === "/login";

    links.innerHTML = "";
    if (!isLogin) {
      const home = document.createElement("a");
      home.href = "/";
      home.textContent = "Home";
      if (path === "/") home.classList.add("active");
      links.appendChild(home);

      for (const item of PRIMARY) {
        const a = document.createElement("a");
        a.href = item.href;
        a.textContent = item.label;
        if (pathActive(path, item.match)) a.classList.add("active");
        if (item.href === "/navigate") a.classList.add("nav-drive");
        links.appendChild(a);
      }
    }

    const tail = document.createElement("div");
    tail.className = "site-nav-tail";
    const user = isLogin ? null : await resolveUser();
    if (user) {
      tail.appendChild(buildThemeMenu());
      tail.appendChild(buildAccountMenu(user));
    } else if (!isLogin) {
      tail.appendChild(buildGuestLink());
    }
    nav.appendChild(tail);

    if (!document.body.dataset.navClickBound) {
      document.body.dataset.navClickBound = "1";
      document.addEventListener("click", () => closeMenus());
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeMenus();
      });
    }

    if (user && window.WardTheme?.syncFromServer) {
      WardTheme.syncFromServer();
    }
  }

  window.WardNav = { mount };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => mount());
  } else {
    mount();
  }
})();
