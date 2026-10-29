/* Shared site nav - Drive + links, burger + bottom tabs on mobile, account (+ theme) */
(function () {
  const PRIMARY = [
    { href: "/navigate", label: "Drive", match: ["/navigate"], drive: true },
    { href: "/regions", label: "Regions", match: ["/regions", "/levels"] },
    { href: "/progress", label: "Progress", match: ["/progress", "/discover"] },
    { href: "/database", label: "Database", match: ["/database"] },
    { href: "/status", label: "Status", match: ["/status"] },
  ];

  const BOTTOM = [
    {
      href: "/",
      label: "Home",
      match: ["/"],
      exact: true,
      icon: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 3.2 3 11h2.5v8.5h5V14h3v5.5h5V11H21L12 3.2z"/></svg>`,
    },
    {
      href: "/navigate",
      label: "Drive",
      match: ["/navigate"],
      icon: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2C8.2 2 5.3 4.6 5 8.2L4 19h3.2l.6-3h8.4l.6 3H20L19 8.2C18.7 4.6 15.8 2 12 2zm-3.2 11.5.5-2.5h5.4l.5 2.5H8.8zM12 4.5c1.9 0 3.4 1.2 3.8 2.8H8.2C8.6 5.7 10.1 4.5 12 4.5z"/></svg>`,
    },
    {
      href: "/regions",
      label: "Regions",
      match: ["/regions", "/levels"],
      icon: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z"/></svg>`,
    },
    {
      href: "/progress",
      label: "Progress",
      match: ["/progress", "/discover"],
      icon: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M4 19h16v2H4v-2zm2.5-3.5 3.2-8.2 3.1 5.4 2.2-3.4L19 15.5h-2.2l-2.1-3.2-2.7 4.2-3.2-5.5L7.3 15.5H6.5z"/></svg>`,
    },
  ];

  const ACCOUNT = [
    { href: "/stats", label: "Stats" },
    { href: "/api", label: "API" },
    { href: "/settings", label: "Settings" },
  ];

  const BURGER_ICON = `<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
    <path fill="currentColor" d="M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h16v2H4v-2z"/>
  </svg>`;

  function pathActive(path, match, exact) {
    if (exact) return match.some((m) => path === m);
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
    const on = pathActive(path, item.match, item.exact);
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

  function buildBottomNav(path) {
    const bar = document.createElement("nav");
    bar.className = "site-bottom-nav";
    bar.setAttribute("aria-label", "Primary");
    for (const item of BOTTOM) {
      const a = document.createElement("a");
      a.href = item.href;
      a.innerHTML = `${item.icon}<span>${item.label}</span>`;
      if (pathActive(path, item.match, item.exact)) {
        a.classList.add("is-current");
        a.setAttribute("aria-current", "page");
      }
      bar.appendChild(a);
    }
    return bar;
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
      // Home → Drive → rest: keeps Drive CTA clear of Home (was colliding when Drive led).
      const home = document.createElement("a");
      home.href = "/";
      home.textContent = "Home";
      if (path === "/") {
        home.classList.add("active");
        home.setAttribute("aria-current", "page");
      }
      links.appendChild(home);

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

    if (!isLogin) {
      document.querySelector(".site-bottom-nav")?.remove();
      const shell = nav.closest(".app-shell") || document.body;
      shell.appendChild(buildBottomNav(path));
    }

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
