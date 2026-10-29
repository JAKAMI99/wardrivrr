/* Site-wide theme engine - Classic / Kidcore / CRT
 *
 * Kidcore speech ≈ Prism Launcher "Cute Engwish" (en@uwu) + OwOify baseline:
 * phrase dict, word map, soft r/l→w, ny-after-n — fully deterministic (no RNG).
 * Attribution / notes: tools/cute-engwish/NOTES.md (no source dumps in-repo).
 */
(function () {
  const APP_VERSION = "1.0.0";
  const KEY = "wardrivrr_theme";
  const LEGACY_KEY = "wardrivrr_nav_theme";
  const IDS = ["classic", "kidcore", "crt"];
  const ORIG_KEY = "__kidcoreOrig";

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
      /Drive guided routes and pick up Wi‑Fi and Bluetooth along the way\./gi,
      "Vroom vroom - new streets & get da signals!",
    ],
    [
      /Live navigation into uncovered streets\./gi,
      "Turny-turny into streets you haven't done yet.",
    ],
    [
      /Download city and district maps\./gi,
      "Get city packs ready.",
    ],
    [
      /See which roads you’ve covered\./gi,
      "See which roads you dwove.",
    ],
    [
      /Browse Wi‑Fi and Bluetooth finds\./gi,
      "Peek at Wi-Fi & Bluetooth finds.",
    ],
    [
      /XP, sessions, and badges\./gi,
      "XP, sessions, and toy badges.",
    ],
    [
      /Driven vs never driven/gi,
      "Dwiven vs never dwiven",
    ],
    [
      /Days in a row with at least one new network/gi,
      "Days in a row with a new network find",
    ],
    [/Most new networks in a single day/gi, "Most new finds in one day"],
    [/Private server — invite only\./gi, "Invite-only home - pwease knock."],
    [/Invite-only home server\./gi, "Invite-only home - pwease knock."],
    [/Loading your badges.../gi, "Getting your badges..."],
    [/Pulling today's numbers.../gi, "Getting today's numbers..."],
    [/Preparing map data…/gi, "Making the map ready..."],
    [/Preparing map data.../gi, "Making the map ready..."],
    [/Downloading map pack…/gi, "Getting da map bits..."],
    [/Downloading regional map data.../gi, "Getting da map bits..."],
    [/Building…/gi, "Making your region..."],
    [/Building your region.../gi, "Making your region..."],
    [/Level ready to explore\./gi, "Level ready to expwore!"],
    [/Find a place/gi, "Where we play?"],
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
    [/Build segments/gi, "Build play roads"],
    [/Build playable segments/gi, "Build play roads"],
    [/Finish up/gi, "Almost done"],
    [/Ready to preload/gi, "Ready to preload"],
    [/You're set/gi, "Yay you're set"],
    [/Preload another/gi, "Preload another"],
    [/Your regions/gi, "Your regionsies"],
    [/Choose area/gi, "Pick your area"],
    [/Choose your area/gi, "Pick your area"],
    [/Pack details/gi, "Nerdy bits"],
    [/Technical details/gi, "Nerdy bits"],
    [/Save settings/gi, "Save settingsies"],
    [/Run full calculation now/gi, "Do big math now"],
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

  const FLOAT_EMOJI = ["🎒", "🧸", "⭐", "🖍️", "🌈", "🐸", "🎮", "🦕", "🦖", "💫", "🎀", "🦄"];
  const CLASSIC_FAVICON = "/static/brand/classic/favicon.png";
  const CRT_FAVICON = "/static/brand/crt/favicon.png";
  const KIDCORE_FAVICON = "/static/brand/kidcore/favicon.png";
  const KIDCORE_STICKERS_MANIFEST = "/static/brand/kidcore/stickers.json";
  const CHAR_PACKS = ["bluey", "winnie_pooh", "random_character"];
  /** Fixed mid/lower-right hero — never in the rotating float pool */
  const BLUEY_HERO_FILE = "bluey-19.png";
  const BLUEY_HERO_SRC = "/static/brand/kidcore/stickers/bluey/bluey-19.png";
  /** Full-viewport float slots (kc-i1–12); CSS keeps clear of Bluey hero only */
  const KIDCORE_FLOAT_COUNT = 12;
  /** Filled async from stickers.json packs; decor falls back to emoji until loaded */
  let kidcorePacks = null; // { bluey: urls[], winnie_pooh: urls[], random_character: urls[], legacy: urls[] }
  let kidcoreStickersPromise = null;

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

  function ensureFaviconLink() {
    let link =
      document.getElementById("wardFavicon") ||
      document.querySelector("link#wardFavicon") ||
      document.querySelector("link[rel='icon'], link[rel='shortcut icon']");
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      link.id = "wardFavicon";
      document.head?.appendChild(link);
    }
    if (!link.id) link.id = "wardFavicon";
    return link;
  }

  function setFavicon(theme) {
    const link = ensureFaviconLink();
    const id = normalize(theme);
    let href = CLASSIC_FAVICON;
    if (id === "kidcore") href = KIDCORE_FAVICON;
    else if (id === "crt") href = CRT_FAVICON;
    link.href = href;
    link.type = "image/png";
  }

  function pick(arr, n) {
    const copy = arr.slice();
    for (let i = copy.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy.slice(0, Math.min(n, copy.length));
  }

  function isBlueyHeroUrl(url) {
    return typeof url === "string" && /(?:^|\/)bluey-19\.png(?:\?|$)/i.test(url);
  }

  function urlsFromPackList(base, folder, files) {
    const list = Array.isArray(files) ? files : [];
    return list
      .map((f) => {
        if (typeof f !== "string") return "";
        if (f.startsWith("http") || f.startsWith("/")) return f;
        // Prefer pack-relative "bluey/bluey-01.png" or bare filename under folder/
        if (f.includes("/")) return `${base}/${f}`;
        return `${base}/${folder}/${f}`;
      })
      .filter(Boolean)
      // Hero is a fixed decor img — keep it out of random rotation pools
      .filter((u) => !isBlueyHeroUrl(u) && !u.endsWith(`/${BLUEY_HERO_FILE}`));
  }

  function fetchKidcoreStickersOnce() {
    return fetch(KIDCORE_STICKERS_MANIFEST, { cache: "no-cache" })
      .then((r) => {
        if (!r.ok) throw new Error(`stickers.json HTTP ${r.status}`);
        return r.json();
      })
      .then((body) => {
        const base = (body?.base || "/static/brand/kidcore/stickers").replace(
          /\/$/,
          ""
        );
        const packsIn = body?.packs && typeof body.packs === "object" ? body.packs : null;
        if (packsIn) {
          const packs = {
            bluey: urlsFromPackList(base, "bluey", packsIn.bluey),
            winnie_pooh: urlsFromPackList(base, "winnie_pooh", packsIn.winnie_pooh),
            random_character: urlsFromPackList(
              base,
              "random_character",
              packsIn.random_character
            ),
            legacy: urlsFromPackList(base, "legacy", packsIn.legacy),
          };
          const n =
            packs.bluey.length +
            packs.winnie_pooh.length +
            packs.random_character.length +
            packs.legacy.length;
          if (!n) throw new Error("stickers.json packs are empty");
          return packs;
        }
        // Legacy flat stickers[] — treat as random_character
        const list = Array.isArray(body?.stickers) ? body.stickers : [];
        if (!list.length) {
          throw new Error("stickers.json returned empty list");
        }
        return {
          bluey: [],
          winnie_pooh: [],
          random_character: list.map((f) =>
            f.includes("/") ? `${base}/${f}` : `${base}/${f}`
          ),
          legacy: [],
        };
      });
  }

  function loadKidcoreStickers() {
    if (kidcorePacks) {
      return Promise.resolve(kidcorePacks);
    }
    if (kidcoreStickersPromise) return kidcoreStickersPromise;
    // Retry once on empty/failed load (cache race, cold StaticFiles, etc.)
    kidcoreStickersPromise = fetchKidcoreStickersOnce()
      .catch((err) => {
        console.warn("[wardrivrr] kidcore stickers load failed, retrying once", err);
        return new Promise((resolve) => setTimeout(resolve, 400)).then(
          fetchKidcoreStickersOnce
        );
      })
      .then((packs) => {
        kidcorePacks = packs;
        return kidcorePacks;
      })
      .catch((err) => {
        console.warn(
          "[wardrivrr] kidcore stickers unavailable — falling back to emoji floats. Check /static/brand/kidcore/stickers.json (Docker image must COPY frontend/brand).",
          err
        );
        kidcorePacks = null;
        kidcoreStickersPromise = null;
        return null;
      });
    return kidcoreStickersPromise;
  }

  /** Round-robin pick across character packs so Bluey / Pooh / random don't clump. */
  function pickCharacterUrls(packs, count = KIDCORE_FLOAT_COUNT) {
    if (!packs) return [];
    const keys = CHAR_PACKS.filter((k) => (packs[k] || []).length);
    if (!keys.length) return [];
    const pools = {};
    const idx = {};
    for (const k of keys) {
      // Defense in depth: exclude hero even if an older manifest still lists it
      const filtered = (packs[k] || []).filter((u) => !isBlueyHeroUrl(u));
      pools[k] = pick(filtered, filtered.length);
      idx[k] = 0;
    }
    const out = [];
    while (out.length < count) {
      let added = false;
      for (const k of keys) {
        if (out.length >= count) break;
        if (idx[k] < pools[k].length) {
          out.push(pools[k][idx[k]++]);
          added = true;
        }
      }
      if (!added) break;
    }
    return out;
  }

  /**
   * Cute Engwish — closer to Prism's en@uwu + OwOify baseline
   * (https://github.com/aqua-lzma/OwOify), but UI-safe + fully deterministic:
   *   phrase dict → word map → soft r/l→w → ny-after-n
   * No stutter / random suffixes / probabilistic repeaty (same input → same output).
   * Protects URLs, paths, and ALL-CAPS tokens (API, GPS, XP…).
   */
  const UWU_WORD_MAP = {
    // OwOify core
    love: "wuv",
    mr: "mistuh",
    dog: "doggo",
    cat: "kitteh",
    hello: "hewwo",
    hell: "heck",
    friend: "fwend",
    friends: "fwends",
    stop: "stawp",
    god: "gosh",
    damn: "darn",
    // Prism / toddler UI lexicon
    please: "pwease",
    thanks: "tankyu",
    "thank you": "tankyu",
    yes: "yesh",
    no: "nyo",
    not: "nyot",
    none: "nyone",
    little: "smol",
    small: "smol",
    cute: "cwute",
    you: "u",
    your: "ur",
    "you're": "ur",
    the: "da",
    with: "wif",
    for: "fow",
    or: "ow",
    and: "awnd",
    very: "vewy",
    really: "weally",
    pretty: "pwetty",
    hi: "hii",
    settings: "settingsies",
    explore: "expwore",
    exploring: "expwowing",
    drive: "dwive",
    driving: "dwiving",
  };

  /** Longer keys first so "thank you" wins over "you" */
  const UWU_WORD_KEYS = Object.keys(UWU_WORD_MAP).sort(
    (a, b) => b.length - a.length
  );

  function uwuPreserveCase(match, replacement) {
    const upper = (match.match(/[A-Z]/g) || []).length;
    if (upper > match.length / 2) return replacement.toUpperCase();
    if (match[0] && match[0] === match[0].toUpperCase()) {
      return replacement.charAt(0).toUpperCase() + replacement.slice(1);
    }
    return replacement;
  }

  function uwuProtected(token) {
    if (!token) return true;
    if (/^https?:/i.test(token)) return true;
    if (/^\/static\//i.test(token)) return true;
    if (/^[A-Z]{2,}$/.test(token)) return true; // API GPS XP URL …
    if (/^wr_/i.test(token)) return true;
    if (/^[a-f0-9]{2}(:[a-f0-9]{2}){5}$/i.test(token)) return true;
    if (/^[\d.:/%_-]+$/.test(token)) return true;
    return false;
  }

  function cuteEngwish(input) {
    if (!input || !input.trim()) return input;
    let s = input;

    // 1) App-specific full phrases first
    for (const [re, rep] of PHRASE_DICT) s = s.replace(re, rep);

    // 2) Word map (static dictionary — always the same)
    for (const key of UWU_WORD_KEYS) {
      const re = new RegExp(
        `\\b${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`,
        "gi"
      );
      s = s.replace(re, (m) => {
        if (uwuProtected(m)) return m;
        return uwuPreserveCase(m, UWU_WORD_MAP[key]);
      });
    }

    // 3–4 operate per word so we can skip protected tokens
    s = s
      .split(/(\s+)/)
      .map((word) => {
        if (!word || /^\s+$/.test(word)) return word;
        // Keep leading/trailing punctuation out of transforms
        const m = word.match(/^([^A-Za-z]*)([A-Za-z][A-Za-z']*)([^A-Za-z]*)$/);
        if (!m) return word;
        const [, pre, core, post] = m;
        if (uwuProtected(core)) return word;

        let w = core;

        // 3) Soft r/l → w (OwOify rltow) — skip tiny words so UI stays readable
        if (w.length >= 4) {
          w = w.replace(/[rl]/gi, (ch) =>
            ch.charCodeAt(0) < 97 ? "W" : "w"
          );
        }

        // 4) ny after n+vowel (OwOify yaftern) — name→nyame, need→nyeed
        w = w.replace(/n[aeiou]/gi, (pair) => {
          const n = pair[0];
          const v = pair[1];
          const y = v.charCodeAt(0) < 97 ? "Y" : "y";
          return `${n}${y}${v}`;
        });

        return pre + w + post;
      })
      .join("");

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
    // Real geographic level/region names — never Cute Engwish (Schwelm ≠ Schwewm)
    if (
      el.closest(
        "[data-place-name], .level-card-name, .nav-level-name, #statLevel, #confirmPlace, #previewTitle, .level-place-hint"
      )
    ) {
      return true;
    }
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

  /** Text nodes already speechified (paired with node[ORIG_KEY] = original English) */
  const speechifiedNodes = new WeakSet();
  let speechApplying = false;

  function restoreSpeech(root) {
    const scope = root || document.body;
    if (!scope) return;
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    speechApplying = true;
    try {
      for (const node of nodes) {
        if (node[ORIG_KEY] != null) {
          node.nodeValue = node[ORIG_KEY];
          delete node[ORIG_KEY];
        }
        speechifiedNodes.delete(node);
      }
    } finally {
      speechApplying = false;
    }
  }

  /**
   * Owoify one text node from its English original only.
   * - Stores original on first see / content change
   * - Skips when already equals cuteEngwish(original) (no double-owoify / no flicker)
   * - On DOM text update: treat new nodeValue as new original, transform once
   */
  function applySpeechToTextNode(node) {
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    const parent = node.parentElement;
    if (!parent || shouldSkipElement(parent)) return;

    const current = node.nodeValue || "";
    const orig = node[ORIG_KEY];

    if (orig != null) {
      const expected = cuteEngwish(orig);
      // Already showing the deterministic speech form — leave it
      if (current === expected) {
        speechifiedNodes.add(node);
        return;
      }
      // Still the stored English — re-apply (e.g. after a failed mid-update)
      if (current === orig) {
        if (shouldSkipText(orig)) return;
        speechApplying = true;
        try {
          node.nodeValue = expected;
          speechifiedNodes.add(node);
        } finally {
          speechApplying = false;
        }
        return;
      }
      // App changed the string (GPS status, etc.) — owoify the new original once
      if (shouldSkipText(current)) {
        delete node[ORIG_KEY];
        speechifiedNodes.delete(node);
        return;
      }
      node[ORIG_KEY] = current;
      speechApplying = true;
      try {
        node.nodeValue = cuteEngwish(current);
        speechifiedNodes.add(node);
      } finally {
        speechApplying = false;
      }
      return;
    }

    if (shouldSkipText(current)) return;

    // Fresh node: store English, transform once (never treat speech as original)
    node[ORIG_KEY] = current;
    const transformed = cuteEngwish(current);
    if (transformed === current) {
      speechifiedNodes.add(node);
      return;
    }
    speechApplying = true;
    try {
      node.nodeValue = transformed;
      speechifiedNodes.add(node);
    } finally {
      speechApplying = false;
    }
  }

  function applySpeechToRoot(root) {
    const scope = root || document.body;
    if (!scope) return;
    if (scope.nodeType === Node.TEXT_NODE) {
      applySpeechToTextNode(scope);
      return;
    }
    const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || shouldSkipElement(parent)) return NodeFilter.FILTER_REJECT;
        const source =
          node[ORIG_KEY] != null ? node[ORIG_KEY] : node.nodeValue || "";
        // Still walk speechified nodes so content changes get re-checked
        if (node[ORIG_KEY] == null && shouldSkipText(source)) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) applySpeechToTextNode(node);
  }

  function stopSpeechObserver() {
    if (speechObserver) {
      speechObserver.disconnect();
      speechObserver = null;
    }
  }

  function startSpeechObserver() {
    stopSpeechObserver();
    if (!document.body) return;
    speechObserver = new MutationObserver((mutations) => {
      if (speechApplying || document.hidden || read() !== "kidcore") return;

      for (const m of mutations) {
        if (m.type === "characterData" && m.target) {
          // Fast path: GPS / status chips rewrite the same text node
          applySpeechToTextNode(m.target);
        } else if (m.type === "childList") {
          for (const n of m.addedNodes) {
            if (n.nodeType === Node.TEXT_NODE) applySpeechToTextNode(n);
            else if (n.nodeType === Node.ELEMENT_NODE) {
              if (!shouldSkipElement(n)) applySpeechToRoot(n);
            }
          }
          // Removals need no work — ORIG_KEY dies with the node
        }
      }
    });
    speechObserver.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      characterDataOldValue: false,
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

  function blueyHeroHtml() {
    // Always-on fixed hero (not in rotation). CSS anchors mid/lower-right.
    return `<img class="kc-img kc-bluey-hero" src="${BLUEY_HERO_SRC}" alt="" decoding="async" draggable="false" />`;
  }

  function imgStickerHtml(urls, count = KIDCORE_FLOAT_COUNT) {
    const picked = urls || [];
    if (!picked.length) {
      // Emoji fallbacks share the same full-viewport scatter (kc-f1–12)
      return pick(FLOAT_EMOJI, KIDCORE_FLOAT_COUNT)
        .map((e, i) => `<span class="kc-float kc-f${i + 1}">${e}</span>`)
        .join("");
    }
    return picked
      .slice(0, count)
      .map(
        (src, i) =>
          `<img class="kc-img kc-i${(i % KIDCORE_FLOAT_COUNT) + 1}" src="${src}" alt="" decoding="async" draggable="false" />`
      )
      .join("");
  }

  function legacyPngHtml(packs) {
    const urls = packs?.legacy || [];
    if (!urls.length) return "";
    // At most one word-art PNG, parked in a phrase-zone slot
    const src = pick(urls, 1)[0];
    return `<img class="kc-img kc-legacy kc-leg1" src="${src}" alt="" decoding="async" draggable="false" />`;
  }

  function buildDecorHtml() {
    // Fixed Bluey hero (lower-right) + scattered image floats (no text chips)
    const chars = pickCharacterUrls(kidcorePacks, KIDCORE_FLOAT_COUNT);
    return (
      blueyHeroHtml() +
      imgStickerHtml(chars, KIDCORE_FLOAT_COUNT) +
      legacyPngHtml(kidcorePacks)
    );
  }

  function refreshPhrases(layer) {
    if (!layer) return;
    // Drop any leftover text chips from older builds, then rotate image floats
    layer.querySelectorAll(".kc-sticker, .kc-img, .kc-float").forEach((el) => el.remove());
    const wrap = document.createElement("div");
    wrap.innerHTML = buildDecorHtml();
    while (wrap.firstChild) layer.appendChild(wrap.firstChild);
  }

  function syncKidcoreDecor(theme) {
    let layer = document.getElementById("kidcoreDecor");
    if (theme !== "kidcore") {
      if (layer) layer.remove();
      // Clear leftover custom cursor from older kidcore builds
      document.documentElement.style.removeProperty("cursor");
      setKidcorePaused(false);
      stopSpeechObserver();
      if (phraseTimer) {
        clearInterval(phraseTimer);
        phraseTimer = null;
      }
      restoreSpeech(document.body);
      return;
    }
    bindKidcoreVisibility();
    setKidcorePaused(document.hidden);
    const mount = () => {
      let host = document.getElementById("kidcoreDecor");
      if (!host) {
        host = document.createElement("div");
        host.id = "kidcoreDecor";
        host.className = "kidcore-decor";
        host.setAttribute("aria-hidden", "true");
        document.body?.appendChild(host);
      } else if (document.body && host.parentNode !== document.body) {
        document.body.appendChild(host);
      }
      host.innerHTML = buildDecorHtml();
    };
    mount();
    // Once sticker pack loads, rebuild so emoji placeholders become images
    loadKidcoreStickers().then(() => {
      if (read() !== "kidcore") return;
      mount();
    });
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
    setFavicon(theme);
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

  // Bumped on user pick so a slow syncFromServer cannot clobber the new theme.
  let themeSyncEpoch = 0;

  async function syncFromServer() {
    if (!hasAuthToken() || !window.WardAuth?.apiFetch) {
      return applyGuestClassic({ broadcast: true });
    }
    const epoch = themeSyncEpoch;
    try {
      const res = await WardAuth.apiFetch("/api/settings");
      if (epoch !== themeSyncEpoch) return read();
      if (!res.ok) return apply(read(), { persist: false, broadcast: true });
      const data = await res.json();
      if (epoch !== themeSyncEpoch) return read();
      // Per-user setting from user_settings - never a global/server-wide theme
      const theme = normalize(data.theme || "classic");
      return apply(theme, { persist: true, broadcast: true });
    } catch {
      /* ignore */
    }
    if (epoch !== themeSyncEpoch) return read();
    return apply(read(), { persist: false, broadcast: true });
  }

  async function saveToServer(id) {
    if (!hasAuthToken()) {
      return applyGuestClassic({ broadcast: true });
    }
    themeSyncEpoch += 1;
    const theme = apply(id, { persist: true, broadcast: true });
    if (!window.WardAuth?.apiFetch) return theme;
    try {
      const res = await WardAuth.apiFetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ theme }),
      });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        if (data.theme) {
          return apply(normalize(data.theme), { persist: true, broadcast: true });
        }
      }
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
    APP_VERSION,
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
