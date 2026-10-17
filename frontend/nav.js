/* Shared site nav - Drive + links, burger on mobile, account (+ theme) */
(function () {
  const PRIMARY = [
    { href: "/navigate", label: "Drive", match: ["/navigate"], drive: true },
    { href: "/regions", label: "Regions", match: ["/regions", "/levels"] },
    { href: "/progress", label: "Progress", match: ["/progress", "/discover"] },
    { href: "/database", label: "Database", match: ["/database"] },
    { href: "/status", label: "Status", match: ["/status"] },
  ];

  const ACCOUNT = [
    { href: "/stats", label: "Stats" },
    { href: "/api", label: "API" },
    { href: "/settings", label: "Settings" },
  ];

  const BURGER_ICON = `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
    <path fill="currentColor" d="M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h16v2H4v-2z"/>
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
    document.querySelectorAll(".site-nav.is-burger-open").forEach((navEl) => {
      navEl.classList.remove("is-burger-open");
      navEl.querySelector(".nav-burger")?.setAttribute("aria-expanded", "false");
    });
  }

  function buildAccountMenu(user) {
    const wrap = document.createElement("div");
    wrap.className = "account-menu";
    const esc = (s) =>
      String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
    const name = esc(user?.username || "Account");
    const ini = esc(initials(user?.username || "Account"));

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
        <div class="account-theme" data-kidcore-skip>
          <p class="account-theme-title" data-kidcore-skip>Appearance</p>
          <div class="account-theme-list nav-theme-list" data-kidcore-skip></div>
        </div>
        <div class="account-dropdown-foot">
          <button type="button" class="account-logout" data-logout>Sign out</button>
        </div>
      </div>`;

    const themeHost = wrap.querySelector(".account-theme-list");
    if (window.WardTheme?.mountNavThemeMenu) {
      WardTheme.mountNavThemeMenu(themeHost, {
        onPick: (id) => {
          WardTheme.saveToServer(id);
        },
      });
    }

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
    wrap.querySelector("[data-logout]")?.addEventListener("click", async () => {
      if (window.WardTheme?.applyGuestClassic) {
        WardTheme.applyGuestClassic({ broadcast: true });
      }
      if (window.WardAuth?.logout) await WardAuth.logout();
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

  function buildLink(item, path) {
    const a = document.createElement("a");
    a.href = item.href;
    a.textContent = item.label;
    const on = pathActive(path, item.match);
    if (item.drive) {
      a.className = "nav-drive";
      if (on) {
        a.classList.add("is-current");
        a.setAttribute("aria-current", "page");
      }
    } else if (on) {
      a.classList.add("active");
      a.setAttribute("aria-current", "page");
    }
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
    links.className = "site-links";

    const more = document.createElement("div");
    more.className = "site-links-more";

    if (!isLogin) {
      const home = document.createElement("a");
      home.href = "/";
      home.textContent = "Home";
      if (path === "/") {
        home.classList.add("active");
        home.setAttribute("aria-current", "page");
      }
      more.appendChild(home);

      for (const item of PRIMARY) {
        const a = buildLink(item, path);
        if (item.drive) links.appendChild(a);
        else more.appendChild(a);
      }
      links.appendChild(more);
    }

    const tail = document.createElement("div");
    tail.className = "site-nav-tail";

    if (!isLogin) {
      const burger = document.createElement("button");
      burger.type = "button";
      burger.className = "nav-burger";
      burger.setAttribute("aria-expanded", "false");
      burger.setAttribute("aria-controls", "siteLinksMore");
      burger.setAttribute("aria-label", "Menu");
      burger.innerHTML = BURGER_ICON;
      more.id = "siteLinksMore";

      burger.addEventListener("click", (e) => {
        e.stopPropagation();
        const open = !nav.classList.contains("is-burger-open");
        closeMenus();
        if (open) {
          nav.classList.add("is-burger-open");
          burger.setAttribute("aria-expanded", "true");
        }
      });

      tail.appendChild(burger);
    }

    const user = isLogin ? null : await resolveUser();
    if (user) {
      tail.appendChild(buildAccountMenu(user));
      if (window.WardTheme?.syncFromServer) {
        WardTheme.syncFromServer();
      }
    } else {
      if (window.WardTheme?.applyGuestClassic) {
        WardTheme.applyGuestClassic({ broadcast: true });
      }
      if (!isLogin) tail.appendChild(buildGuestLink());
    }
    nav.appendChild(tail);

    if (!document.body.dataset.navClickBound) {
      document.body.dataset.navClickBound = "1";
      document.addEventListener("click", () => closeMenus());
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeMenus();
      });
    }
  }

  window.WardNav = { mount };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => mount());
  } else {
    mount();
  }
})();
