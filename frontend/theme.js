/* Site-wide theme engine - Classic / Kidcore / CRT
 *
 * Kidcore speech ≈ Prism Launcher "Cute Engwish" (en@uwu): hewwo, pwease, :3
 */
(function () {
  const KEY = "wardrivrr_theme";
  const LEGACY_KEY = "wardrivrr_nav_theme";
  const IDS = ["classic", "kidcore", "crt"];
  const ORIG_KEY = "__kidcoreOrig";

  const PACIFIER_CURSOR = encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
      <circle cx="16" cy="11" r="7" fill="#ff5cab" stroke="#fff" stroke-width="2"/>
      <circle cx="16" cy="11" r="3.2" fill="#7ee8ff"/>
      <path d="M8 18c2 6 14 6 16 0" fill="#ffe566" stroke="#ff9f1c" stroke-width="1.5"/>
      <ellipse cx="16" cy="20" rx="5" ry="3.5" fill="#ff9f1c"/>
    </svg>`
  );

  /** Floating sticker / phrase pool (picked at random each mount) */
  const PHRASE_POOL = [
    "don't grow up",
    "stay childish",
    "keep exploring",
    "hewwo from toy box",
    "pwease be soft",
    "best fwends forever",
    "no nap · only explore",
    "dino hug zone",
    "rawr means hewwo",
    "smol adventure",
    "snack break soon",
    "PACI POWER",
    "TOY BOX",
    "☆ BEST FWENDS ☆",
    "make weighties",
    "vroom vroom",
    ":3",
    ">:3",
    "UwU",
    "OwO",
    "nya~",
    "rawr :3",
  ];

  /**
   * Full-phrase toddler rewrites (applied before word swaps).
   * Longest / most specific first so short tokens don't steal matches.
   */
  const PHRASE_DICT = [
    [
      /only when you can\s+wait/gi,
      "only when you can make weighties",
    ],
    [/when you can\s+wait/gi, "when you can make weighties"],
    [
      /Drive, explore unread streets, and gather Wi-Fi and Bluetooth as you go\s*-\s*guided routes on a pitched map, one corridor at a time\./gi,
      "Dwive around unread streets & get Wi-Fi and Bluetooth - smol routes, one street at a time.",
    ],
    [
      /Hit the road, clear new streets, and collect signals along the way\./gi,
      "Vroom vroom - new streets & get da signals!",
    ],
    [
      /Go out, explore, and collect signals - turn-by-turn into streets you haven't covered yet\./gi,
      "Go out, expwore, get signals - turny-turny into streets you haven't done yet.",
    ],
    [
      /City and district packs - generate, switch, and clip routing to where you play\./gi,
      "City packs - make 'em, switch 'em, play where you want.",
    ],
    [
      /Locked vs driven road grid for your active level - overview, not turn-by-turn\./gi,
      "Locked vs dwiven roads for your level - peek map, not turny-turny.",
    ],
    [
      /Road grid - locked vs driven \(not turn-by-turn\)/gi,
      "Roads - locked vs dwiven (not turny-turny)",
    ],
    [
      /What you can open today - and what's next\./gi,
      "Toys you can open now - and what's next.",
    ],
    [
      /Applies across the whole app \(maps, HUD, dashboards\)\./gi,
      "Works everywhere (maps, HUD, dashboards).",
    ],
    [
      /Days in a row with at least one new network/gi,
      "Days in a row with a new network find",
    ],
    [/Most new networks in a single day/gi, "Most new finds in one day"],
    [/Invite-only home server\./gi, "Invite-only home - pwease knock."],
    [/Loading your badges.../gi, "Getting your badges..."],
    [/Pulling today's numbers.../gi, "Getting today's numbers..."],
    [/Preparing map data.../gi, "Making the map ready..."],
    [/Downloading regional map data.../gi, "Getting da map bits..."],
    [/Building your region.../gi, "Making your region..."],
    [/Level ready to explore\./gi, "Level ready to expwore!"],
    [/How will you explore\?/gi, "How you gonna expwore?"],
    [/Where do you want to play\?/gi, "Where we play?"],
    [/Spawn, then Start explore/gi, "Spawn, then start expwore"],
    [/Go collect signals/gi, "Go get da signals"],
    [/Drive\s*&\s*explore/gi, "Dwive & expwore"],
    [/Start driving/gi, "Go dwive"],
    [/Start explore/gi, "Start expwore"],
    [/View regions/gi, "See regions"],
    [/Preload region\?/gi, "Preload region?"],
    [/Switch region\?/gi, "Switch region?"],
    [/\bPreload region\b/gi, "Preload region"],
    [/Open Drive\s*->/gi, "Go dwive ->"],
    [/Open drive\s*->/gi, "Go dwive ->"],
    [/View regions\s*->/gi, "See regions ->"],
    [/Open stats\s*->/gi, "See stats ->"],
    [/Open discover\s*->/gi, "Go peek ->"],
    [/Open explorer\s*->/gi, "Go peek ->"],
    [/Open achievements\s*->/gi, "See badges ->"],
    [/Back to regions/gi, "Back to regionsies"],
    [/local explorer/gi, "smol explorer"],
    [/Your exploration/gi, "Your adventure"],
    [/Next Wi-Fi finish line/gi, "Next Wi-Fi finish"],
    [/Total networks/gi, "All da networks"],
    [/Main feature/gi, "Best toy"],
    [/Live services/gi, "Live toys"],
    [/Refresh now/gi, "Peek again"],
    [/Find roads/gi, "Find da roads"],
    [/Build playable segments/gi, "Build play roads"],
    [/Finish up/gi, "Almost done"],
    [/Ready to preload/gi, "Ready to preload"],
    [/Building your region.../gi, "Making your region..."],
    [/You're set/gi, "Yay you're set"],
    [/Preload another/gi, "Preload another"],
    [/Your regions/gi, "Your regionsies"],
    [/Choose your area/gi, "Pick your area"],
    [/Technical details/gi, "Nerdy bits"],
    [/Save settings/gi, "Save settingsies"],
    [/Run full calculation now/gi, "Do big math now"],
    [/Recalculate locations in 3D/gi, "Make locations 3D again"],
    [/Upload\s*&\s*ingest/gi, "Upload & eat file"],
    [/Import capture file/gi, "Bring capture file"],
    [/Download export/gi, "Get export"],
    [/Import backup/gi, "Bring backup"],
    [/Export\s*\/\s*import/gi, "Give / take"],
    [/Create key/gi, "Make key"],
    [/Create user/gi, "Make fwend account"],
    [/Admin\s*·\s*invite user/gi, "Admin · invite fwend"],
    [/Unlocked\s*&\s*in progress/gi, "Got & still getting"],
    [/raw sightings/gi, "peek counts"],
    [/first seen in range/gi, "first peek nearby"],
    [/Sign out/gi, "Byebye"],
    [/Sign in/gi, "Hewwo-in"],
    [/Loading.../g, "Almost ready..."],
    [/Checking.../g, "Looking..."],
    [/Starting.../g, "Getting ready..."],
    [/Preparing.../g, "Making ready..."],
    [/Uploading.../g, "Sending..."],
  ];

  const FLOAT_EMOJI = ["🍼", "🎒", "🧸", "⭐", "🖍️", "🌈", "🐸", "🎮", "🦕", "🦖", "💫", "🎀"];

  const META = {
    classic: {
      label: "Classic Sleek",
      blurb: "Night HUD · cyan & alert red",
      swatches: ["#111315", "#00e5ff", "#e82127"],
      themeColor: "#111315",
    },
    kidcore: {
      label: "Kidcore!!!",
      blurb: "Pacis · pwushies · hewwo speech · :3",
      swatches: ["#ff5cab", "#7ee8ff", "#ffe566", "#b8ff00"],
      themeColor: "#ff9ec8",
    },
    crt: {
      label: "CRT / Matrix",
      blurb: "Phosphor green · amber CRT",
      swatches: ["#050b05", "#00ff66", "#ffb000"],
      themeColor: "#050b05",
    },
  };

  /**
   * Map + fog-of-war colours per theme.
   * fogExplored = driven (muted so TBT route stays readable); fogLocked = never driven.
   */
  const MAP = {
    classic: {
      ahead: "#00e5ff",
      done: "#2ad48a",
      fogExplored: "#2a4a42",
      fogLocked: "#12161e",
      mapDay: "liberty",
      mapNight: "dark",
    },
    kidcore: {
      ahead: "#ff5cab",
      done: "#b8ff00",
      fogExplored: "#5a6230",
      fogLocked: "#160812",
      mapDay: "liberty",
      mapNight: "liberty",
    },
    crt: {
      ahead: "#00ff66",
      done: "#ffb000",
      fogExplored: "#1a4a2e",
      fogLocked: "#030805",
      mapDay: "dark",
      mapNight: "dark",
    },
  };

  function applyFogCssVars(themeId) {
    const pack = MAP[normalize(themeId)] || MAP.classic;
    const root = document.documentElement;
    if (!root?.style) return;
    root.style.setProperty("--fog-explored", pack.fogExplored);
    root.style.setProperty("--fog-locked", pack.fogLocked);
  }

  let speechObserver = null;
  let phraseTimer = null;
  let speechDebounce = null;
  let visibilityBound = false;

  function normalize(id) {
    if (id === "kawaii") return "kidcore";
    return IDS.includes(id) ? id : "classic";
  }

  function hasAuthToken() {
    try {
      return !!(
        localStorage.getItem("wardrivrr_token") ||
        sessionStorage.getItem("wardrivrr_token")
      );
    } catch {
      return false;
    }
  }

  function read() {
    // Guests always classic - never inherit another user's localStorage theme
    if (!hasAuthToken()) return "classic";
    const raw = localStorage.getItem(KEY) || localStorage.getItem(LEGACY_KEY) || "classic";
    return normalize(raw);
  }

  function clearLocalTheme() {
    try {
      localStorage.removeItem(KEY);
      localStorage.removeItem(LEGACY_KEY);
    } catch {
      /* ignore */
    }
  }

  /** Logged-out / after sign-out: classic only, no sticky cache. */
  function applyGuestClassic({ broadcast = true } = {}) {
    clearLocalTheme();
    return apply("classic", { persist: false, broadcast });
  }

  function setMetaThemeColor(id) {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", META[id]?.themeColor || "#111315");
  }

  function pick(arr, n) {
    const copy = arr.slice();
    for (let i = copy.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy.slice(0, n);
  }

  /** Toddler Cute Engwish - phrase rewrites + selective swaps (no blanket r/l->w) */
  function cuteEngwish(input) {
    if (!input || !input.trim()) return input;
    let s = input;

    for (const [re, rep] of PHRASE_DICT) s = s.replace(re, rep);

    // Selective word swaps only (keeps most consonants readable)
    const pairs = [
      [/\bThank you\b/gi, "Tankyu"],
      [/\bHello\b/g, "Hewwo"],
      [/\bhello\b/g, "hewwo"],
      [/\bHi\b/g, "Hii"],
      [/\bPlease\b/g, "Pwease"],
      [/\bplease\b/g, "pwease"],
      [/\bThanks\b/g, "Tankyu"],
      [/\bthanks\b/g, "tankyu"],
      [/\bLove\b/g, "Wuv"],
      [/\blove\b/g, "wuv"],
      [/\bYes\b/g, "Yesh"],
      [/\byes\b/g, "yesh"],
      [/\bNo\b/g, "Nyo"],
      [/\bno\b/g, "nyo"],
      [/\bLittle\b/g, "Smol"],
      [/\blittle\b/g, "smol"],
      [/\bSmall\b/g, "Smol"],
      [/\bsmall\b/g, "smol"],
      [/\bCute\b/g, "Cwute"],
      [/\bcute\b/g, "cwute"],
      [/\bFriend\b/g, "Fwend"],
      [/\bfriend\b/g, "fwend"],
      [/\bFriends\b/g, "Fwends"],
      [/\bfriends\b/g, "fwends"],
      [/\bExplore\b/g, "Expwore"],
      [/\bexplore\b/g, "expwore"],
      [/\bExploring\b/g, "Expwowing"],
      [/\bexploring\b/g, "expwowing"],
      [/\bDrive\b/g, "Dwive"],
      [/\bdrive\b/g, "dwive"],
      [/\bDriving\b/g, "Dwiving"],
      [/\bdriving\b/g, "dwiving"],
      [/\bSettings\b/g, "Settingsies"],
      [/\bsettings\b/g, "settingsies"],
      [/\bVery\b/g, "Vewy"],
      [/\bvery\b/g, "vewy"],
      [/\bReally\b/g, "Weally"],
      [/\breally\b/g, "weally"],
      [/\bPretty\b/g, "Pwetty"],
      [/\bpretty\b/g, "pwetty"],
    ];
    for (const [re, rep] of pairs) s = s.replace(re, rep);

    // Soft stutter - rare
    s = s.replace(/\b([A-Za-z])([a-z]{5,})\b/g, (full, a, rest) => {
      if (Math.random() > 0.04) return full;
      return `${a}-${a}${rest}`;
    });

    // Light :3 / UwU sprinkle on sentence endings
    if (/[.!?]$/.test(s.trim()) && s.length > 18 && Math.random() < 0.12) {
      const tails = [" :3", " UwU", " >:3"];
      s = s.replace(/([.!?])\s*$/, tails[Math.floor(Math.random() * tails.length)]);
    }
    return s;
  }

  function shouldSkipElement(el) {
    if (!el || el.nodeType !== 1) return true;
    const tag = el.tagName;
    if (
      /^(SCRIPT|STYLE|TEXTAREA|INPUT|SELECT|OPTION|CODE|PRE|SVG|PATH|NOSCRIPT|IFRAME|CANVAS)$/.test(
        tag
      )
    ) {
      return true;
    }
    if (el.closest(".kidcore-decor")) return true;
    if (el.closest("[data-kidcore-skip]")) return true;
    if (el.closest(".maplibregl-map, .maplibregl-ctrl, .nav-map")) return true;
    if (el.isContentEditable) return true;
    return false;
  }

  function shouldSkipText(text) {
    const t = text.trim();
    if (t.length < 2) return true;
    if (/^[\d.:/\-_%°]+$/.test(t)) return true;
    if (/^[a-f0-9]{2}(:[a-f0-9]{2}){5}$/i.test(t)) return true;
    if (/^https?:\/\//i.test(t)) return true;
    if (/^wr_/.test(t)) return true;
    return false;
  }

  function restoreSpeech(root) {
    const scope = root || document.body;
    if (!scope) return;
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      if (node[ORIG_KEY] != null) {
        node.nodeValue = node[ORIG_KEY];
        delete node[ORIG_KEY];
      }
    }
  }

  function applySpeechToRoot(root) {
    const scope = root || document.body;
    if (!scope) return;
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || shouldSkipElement(parent)) return NodeFilter.FILTER_REJECT;
        const source = node[ORIG_KEY] != null ? node[ORIG_KEY] : node.nodeValue || "";
        if (shouldSkipText(source)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      // Transform once per text node so MutationObserver does not re-roll stutter forever
      if (node[ORIG_KEY] != null) continue;
      node[ORIG_KEY] = node.nodeValue;
      node.nodeValue = cuteEngwish(node[ORIG_KEY]);
    }
  }

  function stopSpeechObserver() {
    if (speechObserver) {
      speechObserver.disconnect();
      speechObserver = null;
    }
    if (speechDebounce) {
      clearTimeout(speechDebounce);
      speechDebounce = null;
    }
  }

  function startSpeechObserver() {
    stopSpeechObserver();
    if (!document.body) return;
    speechObserver = new MutationObserver(() => {
      if (document.hidden || read() !== "kidcore") return;
      if (speechDebounce) return;
      // Coalesce bursts (status chips, stats) - full TreeWalker is expensive
      speechDebounce = setTimeout(() => {
        speechDebounce = null;
        if (document.hidden || read() !== "kidcore") return;
        applySpeechToRoot(document.body);
      }, 220);
    });
    speechObserver.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: false,
    });
  }

  function setKidcorePaused(paused) {
    document.documentElement.classList.toggle("kidcore-paused", !!paused);
  }

  function bindKidcoreVisibility() {
    if (visibilityBound) return;
    visibilityBound = true;
    document.addEventListener("visibilitychange", () => {
      if (read() !== "kidcore") {
        setKidcorePaused(false);
        return;
      }
      const hidden = document.hidden;
      setKidcorePaused(hidden);
      if (hidden) {
        if (phraseTimer) {
          clearInterval(phraseTimer);
          phraseTimer = null;
        }
        stopSpeechObserver();
      } else {
        applySpeechToRoot(document.body);
        startSpeechObserver();
        startPhraseTimer();
      }
    });
  }

  function startPhraseTimer() {
    if (phraseTimer) clearInterval(phraseTimer);
    phraseTimer = null;
    if (read() !== "kidcore" || document.hidden) return;
    // Rare refresh - DOM churn was waking layout every 14s for little gain
    phraseTimer = setInterval(() => {
      if (document.hidden || read() !== "kidcore") return;
      refreshPhrases(document.getElementById("kidcoreDecor"));
    }, 45000);
  }

  function buildDecorHtml() {
    const emojis = pick(FLOAT_EMOJI, 4);
    const phrases = pick(PHRASE_POOL, 4);
    const floats = emojis
      .map((e, i) => `<span class="kc-float kc-f${i + 1}">${e}</span>`)
      .join("");
    const stickers = phrases
      .map((p, i) => {
        const cls = `kc-sticker kc-s${(i % 6) + 1}${
          /:3|>:3|UwU|OwO|nya/i.test(p) ? " kc-emo" : ""
        }`;
        return `<span class="${cls}">${p}</span>`;
      })
      .join("");
    return floats + stickers;
  }

  function refreshPhrases(layer) {
    if (!layer) return;
    layer.querySelectorAll(".kc-sticker").forEach((el) => el.remove());
    const phrases = pick(PHRASE_POOL, 4);
    phrases.forEach((p, i) => {
      const span = document.createElement("span");
      span.className = `kc-sticker kc-s${(i % 6) + 1}${
        /:3|>:3|UwU|OwO|nya/i.test(p) ? " kc-emo" : ""
      }`;
      span.textContent = p;
      layer.appendChild(span);
    });
  }

  function syncKidcoreDecor(theme) {
    let layer = document.getElementById("kidcoreDecor");
    if (theme !== "kidcore") {
      if (layer) layer.remove();
      document.documentElement.style.removeProperty("cursor");
      setKidcorePaused(false);
      stopSpeechObserver();
      if (speechDebounce) {
        clearTimeout(speechDebounce);
        speechDebounce = null;
      }
      if (phraseTimer) {
        clearInterval(phraseTimer);
        phraseTimer = null;
      }
      restoreSpeech(document.body);
      return;
    }
    bindKidcoreVisibility();
    setKidcorePaused(document.hidden);
    document.documentElement.style.cursor = `url("data:image/svg+xml,${PACIFIER_CURSOR}") 8 4, auto`;
    if (!layer) {
      layer = document.createElement("div");
      layer.id = "kidcoreDecor";
      layer.className = "kidcore-decor";
      layer.setAttribute("aria-hidden", "true");
      layer.innerHTML = buildDecorHtml();
      document.body?.appendChild(layer);
    } else {
      if (document.body && layer.parentNode !== document.body) {
        document.body.appendChild(layer);
      }
      layer.innerHTML = buildDecorHtml();
    }
    if (!document.hidden) {
      applySpeechToRoot(document.body);
      startSpeechObserver();
      startPhraseTimer();
    }
  }

  function apply(id, { persist = true, broadcast = true } = {}) {
    const theme = normalize(id);
    const prev = document.documentElement.dataset.theme;
    if (prev === "kidcore" && theme !== "kidcore") {
      restoreSpeech(document.body);
    }
    document.documentElement.dataset.theme = theme;
    applyFogCssVars(theme);
    if (document.body) {
      document.body.dataset.navTheme = theme;
      syncKidcoreDecor(theme);
    } else {
      document.addEventListener(
        "DOMContentLoaded",
        () => syncKidcoreDecor(theme),
        { once: true }
      );
    }
    setMetaThemeColor(theme);
    // Cache only for the signed-in user (per-user setting lives in user_settings)
    if (persist && hasAuthToken()) {
      localStorage.setItem(KEY, theme);
      localStorage.removeItem(LEGACY_KEY);
    }
    document.querySelectorAll("[data-theme-pick]").forEach((el) => {
      el.classList.toggle("is-active", el.dataset.themePick === theme);
    });
    if (broadcast) {
      window.dispatchEvent(
        new CustomEvent("wardrivrr:theme", { detail: { theme } })
      );
    }
    return theme;
  }

  function mapPack(id) {
    return MAP[normalize(id || read())];
  }

  function fogPack(id) {
    const pack = mapPack(id);
    return {
      explored: pack.fogExplored || "#2a4a42",
      locked: pack.fogLocked || "#12161e",
    };
  }

  async function syncFromServer() {
    if (!hasAuthToken() || !window.WardAuth?.apiFetch) {
      return applyGuestClassic({ broadcast: true });
    }
    try {
      const res = await WardAuth.apiFetch("/api/settings");
      if (!res.ok) return apply(read(), { persist: false, broadcast: true });
      const data = await res.json();
      // Per-user setting from user_settings - never a global/server-wide theme
      const theme = normalize(data.theme || "classic");
      return apply(theme, { persist: true, broadcast: true });
    } catch {
      /* ignore */
    }
    return apply(read(), { persist: false, broadcast: true });
  }

  async function saveToServer(id) {
    if (!hasAuthToken()) {
      return applyGuestClassic({ broadcast: true });
    }
    const theme = apply(id, { persist: true, broadcast: true });
    if (!window.WardAuth?.apiFetch) return theme;
    try {
      await WardAuth.apiFetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme }),
      });
    } catch {
      /* local still applied for this session */
    }
    return theme;
  }

  function mountSettingsPicker(host, { onPick } = {}) {
    if (!host) return;
    host.innerHTML = IDS.map((id) => {
      const m = META[id];
      const sw = m.swatches
        .map((c) => `<i style="background:${c}"></i>`)
        .join("");
      return `<button type="button" class="theme-card" data-theme-pick="${id}" data-kidcore-skip>
        <strong data-kidcore-skip>${m.label}</strong>
        <span data-kidcore-skip>${m.blurb}</span>
        <div class="theme-swatches">${sw}</div>
      </button>`;
    }).join("");
    host.querySelectorAll("[data-theme-pick]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tid = btn.dataset.themePick;
        if (typeof onPick === "function") onPick(tid);
        else apply(tid);
      });
    });
    apply(read(), { persist: false, broadcast: false });
  }

  /** Compact theme list for the global nav popover */
  function mountNavThemeMenu(host, { onPick } = {}) {
    if (!host) return;
    host.innerHTML = IDS.map((id) => {
      const m = META[id];
      const sw = (m.swatches || [])
        .slice(0, 3)
        .map((c) => `<i style="background:${c}"></i>`)
        .join("");
      return `<button type="button" class="nav-theme-option" data-theme-pick="${id}" data-kidcore-skip>
        <span class="nav-theme-option-text" data-kidcore-skip>
          <strong data-kidcore-skip>${m.label}</strong>
          <span class="muted" data-kidcore-skip>${m.blurb}</span>
        </span>
        <span class="nav-theme-option-swatches" aria-hidden="true">${sw}</span>
      </button>`;
    }).join("");
    host.querySelectorAll("[data-theme-pick]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tid = btn.dataset.themePick;
        if (typeof onPick === "function") onPick(tid);
        else saveToServer(tid);
      });
    });
    apply(read(), { persist: false, broadcast: false });
  }

  // Boot: guests -> classic; signed-in -> cached preference until /api/settings sync
  apply(read(), { persist: false, broadcast: false });

  window.WardTheme = {
    KEY,
    IDS,
    META,
    read,
    apply,
    applyGuestClassic,
    clearLocalTheme,
    mapPack,
    fogPack,
    syncFromServer,
    saveToServer,
    mountSettingsPicker,
    mountNavThemeMenu,
    cuteEngwish,
  };
})();
