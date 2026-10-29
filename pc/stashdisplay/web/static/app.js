// Settings page editor. Alpine.js component; no build step.

//

// `saved` is what is on disk, `draft` is what is being edited. Every edit goes

// to `draft`, the preview follows it, and Save sends it to the PC app.



const WRITE_HEADERS = { "X-Stashdisplay": "1" };

const HISTORY_LIMIT = 100;

const PREVIEW_DEBOUNCE_MS = 60;

const PREVIEW_REFRESH_MS = 30000;

const SCREEN_POLL_MS = 3000;



async function api(path, { method = "GET", json, body, headers = {} } = {}) {

  const opts = { method, headers: { ...headers }, credentials: "same-origin" };

  if (method !== "GET") Object.assign(opts.headers, WRITE_HEADERS);

  if (json !== undefined) {

    opts.headers["Content-Type"] = "application/json";

    opts.body = JSON.stringify(json);

  } else if (body !== undefined) {

    opts.body = body;

  }

  const res = await fetch(path, opts);

  if (!res.ok && res.status !== 409 && res.status !== 400) throw new Error(`${path}: ${res.status}`);

  return res;

}



const clone = (v) => JSON.parse(JSON.stringify(v));

const randomId = () => Math.random().toString(16).slice(2, 10);



document.addEventListener("alpine:init", () => {

  Alpine.data("editor", () => ({

    loaded: false,

    loadError: "",

    tab: "pages",

    strings: { en: {}, fr: {} },

    schema: null,

    saved: null,

    draft: null,

    history: [],

    future: [],

    lastSnapshot: "",

    restoring: false,

    pageIndex: 0,

    selectedSlot: null,

    forceDemo: false,

    isDemo: true,

    previewUrl: "",

    previewTimer: null,

    previewAbort: null,

    media: [],

    uploading: false,

    suggestions: [],

    hasCookie: false,

    cookieInput: "",

    cookieStatus: { kind: "", text: "" },
    pricerStatus: { kind: "", text: "" },

    autostart: { supported: false, enabled: false },

    screen: { state: "off", simulator: false },

    events: { path: null, found: false, characters: [] },

    saving: false,

    addOpen: false,

    dragFrom: null,

    dragOver: null,

    toast: "",

    toastTimer: null,



    // --- Setup ----------------------------------------------------------------



    async init() {

      try {

        const [state, en, fr] = await Promise.all([

          api("/api/state").then((r) => r.json()),

          fetch("/static/i18n/en.json").then((r) => r.json()),

          fetch("/static/i18n/fr.json").then((r) => r.json()),

        ]);

        this.strings = { en, fr };

        this.schema = state.schema;

        this.applyState(state);

        this.loaded = true;

      } catch (e) {

        this.loadError = "Could not load the settings: " + e.message;

        return;

      }

      this.$watch("draft", () => this.recordHistory(), { deep: true });

      this.$watch("draft.pages", () => this.schedulePreview(), { deep: true });

      this.$watch("pageIndex", () => this.schedulePreview());

      this.$watch("forceDemo", () => this.schedulePreview());

      setInterval(() => this.schedulePreview(), PREVIEW_REFRESH_MS);  // clock and "synced" text

      setInterval(() => this.pollScreen(), SCREEN_POLL_MS);

      window.addEventListener("beforeunload", (e) => { if (this.dirty) e.preventDefault(); });

      this.schedulePreview();

    },



    applyState(state) {

      this.saved = { settings: state.settings, pages: state.pages };

      this.draft = clone(this.saved);

      this.lastSnapshot = JSON.stringify(this.draft);

      this.history = [];

      this.future = [];

      this.media = state.media;

      this.hasCookie = state.has_cookie;

      this.autostart = state.autostart;

      this.isDemo = !state.live;

      this.screen = state.screen;

      this.events = state.events;

      this.pageIndex = Math.min(this.pageIndex, this.draft.pages.length - 1);

    },



    // --- Translation ---------------------------------------------------------------



    get lang() { return this.draft ? this.draft.settings.language : "en"; },



    t(key) {

      return this.strings[this.lang]?.[key] ?? this.strings.en[key] ?? key;

    },



    // Like t(), with a fallback taken from the Python definitions (widget names, options...).

    tr(key, fallback) {

      return this.strings[this.lang]?.[key] ?? this.strings.en[key] ?? fallback;

    },



    optLabel(widgetId, opt) {

      return this.tr(`opt.${widgetId}.${opt.key}`, this.tr(`opt.${opt.key}`, opt.label));

    },



    choiceLabel(opt, value) {

      if (opt.kind === "metric") {

        const m = this.schema.metrics.find((x) => x.id === value);

        return this.tr("metric." + value, m ? m.label : value);

      }

      return this.tr("choice." + value, value);

    },



    // --- Current page and slot -------------------------------------------------------



    get page() { return this.draft?.pages[this.pageIndex]; },

    get slot() { return this.page && this.selectedSlot !== null ? this.page.slots[this.selectedSlot] : null; },

    get dirty() { return this.draft && JSON.stringify(this.draft) !== JSON.stringify(this.saved); },



    templateDef(id) { return this.schema.templates.find((t) => t.id === id); },

    widgetDef(id) { return this.schema.widgets.find((w) => w.id === id); },

    slotsOf(page) { return page ? Object.entries(this.templateDef(page.template).slots) : []; },



    slotLabel(name) {

      const slot = this.page?.slots[name];

      const what = slot ? this.tr(`widget.${slot.widget}.name`, slot.widget) : this.t("slot.empty");

      return `${this.tr("slotname." + name, name)} · ${what}`;

    },



    // Percent of the screen, so the hit boxes follow the preview at any size.

    boxStyle([x, y, w, h]) {

      const sx = 100 / this.schema.screen.width, sy = 100 / this.schema.screen.height;

      return `left:${x * sx}%;top:${y * sy}%;width:${w * sx}%;height:${h * sy}%`;

    },



    selectPage(i) {

      this.pageIndex = i;

      this.selectedSlot = null;

    },



    // --- Editing -------------------------------------------------------------------------



    setWidget(id) {

      if (!id) {

        this.page.slots[this.selectedSlot] = null;

        return;

      }

      const def = this.widgetDef(id);

      const slot = { widget: id, frame: def.frame };

      for (const opt of def.options) slot[opt.key] = clone(opt.default);

      this.page.slots[this.selectedSlot] = slot;

    },



    changeTemplate(id) {

      const page = this.page;

      const names = Object.keys(this.templateDef(id).slots);

      const lost = Object.entries(page.slots).filter(([n, s]) => s && !names.includes(n));

      if (lost.length && !confirm(this.t("page.template.confirm").replace("{n}", lost.length))) {

        // Put the select back: Alpine does not re-render an unchanged value.

        this.page.template = page.template;

        return;

      }

      const slots = {};

      for (const n of names) slots[n] = page.slots[n] ?? null;

      page.template = id;

      page.slots = slots;

      this.selectedSlot = null;

    },



    newPage(templateId) {

      const slots = {};

      for (const n of Object.keys(this.templateDef(templateId).slots)) slots[n] = null;

      return {

        id: randomId(), name: this.t("pages.new_name"), hidden: false, template: templateId,

        header: { title: true, clock: true, synced: true },

        background: { kind: "color", value: "#000000", fit: "cover", x: 50, y: 50 },

        slots,

      };

    },



    addPage(templateId) {

      this.draft.pages.push(this.newPage(templateId));

      this.addOpen = false;

      this.selectPage(this.draft.pages.length - 1);

    },



    duplicatePage(i) {

      const copy = clone(this.draft.pages[i]);

      copy.id = randomId();

      copy.name = `${copy.name} (${this.t("pages.copy")})`;

      this.draft.pages.splice(i + 1, 0, copy);

      this.selectPage(i + 1);

    },



    deletePage(i) {

      if (this.draft.pages.length <= 1) return;

      if (!confirm(this.t("pages.delete.confirm").replace("{name}", this.draft.pages[i].name))) return;

      this.draft.pages.splice(i, 1);

      this.selectPage(Math.min(i, this.draft.pages.length - 1));

    },



    dropPage(to) {

      const from = this.dragFrom;

      this.dragOver = null;

      if (from === null || from === to) return;

      const current = this.draft.pages[this.pageIndex];

      const [moved] = this.draft.pages.splice(from, 1);

      this.draft.pages.splice(to, 0, moved);

      this.pageIndex = this.draft.pages.indexOf(current);

      this.dragFrom = null;

    },



    async resetPreset() {

      if (!confirm(this.t("pages.reset.confirm"))) return;

      const { pages } = await api("/api/preset").then((r) => r.json());

      this.draft.pages = pages;

      this.selectPage(0);

    },



    exportPages(pages) {

      const blob = new Blob([JSON.stringify({ stashdisplay_pages: 1, pages }, null, 1)], { type: "application/json" });

      const a = document.createElement("a");

      a.href = URL.createObjectURL(blob);

      a.download = pages.length === 1 ? `page-${pages[0].name}.json` : "stashdisplay-pages.json";

      a.click();

      URL.revokeObjectURL(a.href);

    },



    async importPages(event) {

      const file = event.target.files[0];

      event.target.value = "";

      if (!file) return;

      try {

        const data = JSON.parse(await file.text());

        const res = await api("/api/normalize", { method: "POST", json: { pages: data.pages ?? data } });

        const { pages } = await res.json();

        if (!pages.length) throw new Error("no pages");

        for (const p of pages) p.id = randomId();  // never clash with existing pages

        this.draft.pages.push(...pages);

        this.selectPage(this.draft.pages.length - pages.length);

        this.notify(this.t("pages.imported").replace("{n}", pages.length));

      } catch (e) {

        this.notify(this.t("pages.import.error"));

      }

    },



    // --- Backgrounds -------------------------------------------------------------------



    setBackgroundKind(kind) {

      const bg = this.page.background;

      if (kind === "color") {

        Object.assign(bg, { kind: "color", value: "#000000" });

      } else {

        const first = this.media[0];

        if (first) this.useMedia(first);

        else Object.assign(bg, { kind: "image", value: "" });

      }

    },



    useMedia(m) {

      Object.assign(this.page.background, { kind: m.kind, value: m.id });

    },



    async uploadMedia(event, use = (m) => this.useMedia(m)) {

      const file = event.target.files[0];

      event.target.value = "";

      if (!file) return;

      this.uploading = true;

      try {

        const form = new FormData();

        form.append("file", file);

        let meta = await api("/api/media", { method: "POST", body: form }).then((r) => r.json());

        if (meta.error) throw new Error(meta.error);

        if (meta.needs_still) {

          meta = await this.extractVideoStill(file, meta.id);

          try {

            const framed = await this.extractVideoFrames(file, meta.id);

            if (framed.error) throw new Error(framed.error);

            meta = framed;

          } catch (e) {  // the still frame is there: the video shows it, without moving

            this.notify(this.t("bg.upload.error") + " " + e.message);

          }

        }

        this.media = [meta, ...this.media.filter((m) => m.id !== meta.id)];

        use(meta);

      } catch (e) {

        this.notify(this.t("bg.upload.error") + " " + e.message);

      } finally {

        this.uploading = false;

      }

    },



    // The browser decodes the video and sends its first frame, so the PC needs no ffmpeg for previews.

    extractVideoStill(file, id) {

      return new Promise((resolve, reject) => {

        const video = document.createElement("video");

        video.muted = true;

        video.preload = "auto";

        video.src = URL.createObjectURL(file);

        video.onloadeddata = () => { video.currentTime = Math.min(0.1, video.duration || 0); };

        video.onseeked = () => {

          const canvas = document.createElement("canvas");

          canvas.width = video.videoWidth;

          canvas.height = video.videoHeight;

          canvas.getContext("2d").drawImage(video, 0, 0);

          URL.revokeObjectURL(video.src);

          canvas.toBlob(async (blob) => {

            try {

              const res = await api(`/api/media/${id}/still`, { method: "POST", body: blob });

              resolve(await res.json());

            } catch (e) { reject(e); }

          }, "image/png");

        };

        video.onerror = () => reject(new Error(this.t("bg.video.unreadable")));

      });

    },



    // And its frames for the screen: the first 10 s at 12 fps (docs/SCOPE.md §5), as JPEGs each

    // after its length. The PC fits them to the screen and packs them for it.

    async extractVideoFrames(file, id) {

      const FPS = 12, MAX_SECONDS = 10, MAX_SIDE = 960;

      const video = document.createElement("video");

      video.muted = true;

      video.preload = "auto";

      video.src = URL.createObjectURL(file);

      const seek = (t) => new Promise((resolve, reject) => {

        video.onseeked = resolve;

        video.onerror = () => reject(new Error(this.t("bg.video.unreadable")));

        video.currentTime = t;

      });

      try {

        await new Promise((resolve, reject) => {

          video.onloadeddata = resolve;

          video.onerror = () => reject(new Error(this.t("bg.video.unreadable")));

        });

        const count = Math.max(1, Math.floor(Math.min(video.duration || 0, MAX_SECONDS) * FPS));

        const scale = Math.min(1, MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));

        const canvas = document.createElement("canvas");

        canvas.width = Math.round(video.videoWidth * scale);

        canvas.height = Math.round(video.videoHeight * scale);

        const ctx = canvas.getContext("2d");

        const parts = [];

        for (let i = 0; i < count; i++) {

          await seek(i / FPS);

          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

          const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));

          const size = new DataView(new ArrayBuffer(4));

          size.setUint32(0, blob.size, true);

          parts.push(size.buffer, blob);

        }

        const res = await api(`/api/media/${id}/frames`, { method: "POST", body: new Blob(parts) });

        return await res.json();

      } finally {

        URL.revokeObjectURL(video.src);

      }

    },



    async deleteMedia(m) {

      if (!confirm(this.t("bg.delete.confirm").replace("{name}", m.name))) return;

      const res = await api(`/api/media/${m.id}`, { method: "DELETE" });

      const body = await res.json();

      if (res.status === 409) {

        this.notify(this.t("bg.delete.in_use").replace("{pages}", body.pages.join(", ")));

        return;

      }

      this.media = body.media;

    },



    // --- Items -----------------------------------------------------------------------------



    async suggestItems(query) {

      if (query.length < 2) { this.suggestions = []; return; }

      const { items } = await api("/api/items?q=" + encodeURIComponent(query)).then((r) => r.json());

      this.suggestions = items;

    },



    addItem(list, input) {

      const name = input.value.trim();

      if (name && !list.includes(name)) list.push(name);

      input.value = "";

    },



    // --- Preview -------------------------------------------------------------------------



    schedulePreview() {

      clearTimeout(this.previewTimer);

      this.previewTimer = setTimeout(() => this.renderPreview(), PREVIEW_DEBOUNCE_MS);

    },



    async renderPreview() {

      if (!this.page) return;

      this.previewAbort?.abort();  // only the latest edit matters

      const abort = new AbortController();

      this.previewAbort = abort;

      const visible = this.draft.pages.filter((p) => !p.hidden);

      const index = Math.max(0, visible.indexOf(this.page));

      try {

        const res = await fetch("/api/preview", {

          method: "POST", signal: abort.signal, credentials: "same-origin",

          headers: { ...WRITE_HEADERS, "Content-Type": "application/json" },

          body: JSON.stringify({ page: this.page, index, count: Math.max(1, visible.length), demo: this.forceDemo }),

        });

        if (!res.ok) return;

        this.isDemo = res.headers.get("X-Demo-Data") === "1";

        const url = URL.createObjectURL(await res.blob());

        // Swap only once the new image is decoded, so the preview never flashes.

        const img = new Image();

        img.src = url;

        await img.decode();

        if (abort.signal.aborted) { URL.revokeObjectURL(url); return; }

        const old = this.previewUrl;

        this.previewUrl = url;

        if (old) setTimeout(() => URL.revokeObjectURL(old), 1000);

      } catch (e) {

        if (e.name !== "AbortError") console.warn(e);

      }

    },



    // --- Undo / redo ------------------------------------------------------------------------



    recordHistory() {

      if (this.restoring) return;

      const now = JSON.stringify(this.draft);

      if (now === this.lastSnapshot) return;

      this.history.push(this.lastSnapshot);

      if (this.history.length > HISTORY_LIMIT) this.history.shift();

      this.future = [];

      this.lastSnapshot = now;

    },



    restore(snapshot) {

      this.restoring = true;

      this.draft = JSON.parse(snapshot);

      this.lastSnapshot = snapshot;

      this.pageIndex = Math.min(this.pageIndex, this.draft.pages.length - 1);

      if (this.selectedSlot !== null && !(this.selectedSlot in this.page.slots)) this.selectedSlot = null;

      this.$nextTick(() => { this.restoring = false; this.schedulePreview(); });

    },



    undo() {

      if (!this.history.length) return;

      this.future.push(this.lastSnapshot);

      this.restore(this.history.pop());

    },



    redo() {

      if (!this.future.length) return;

      this.history.push(this.lastSnapshot);

      this.restore(this.future.pop());

    },



    revert() {

      if (!confirm(this.t("revert.confirm"))) return;

      this.history.push(this.lastSnapshot);

      this.restore(JSON.stringify(this.saved));

    },



    shortcut(e) {

      const mod = e.ctrlKey || e.metaKey;

      if (!mod || ["INPUT", "TEXTAREA"].includes(e.target.tagName)) return;

      if (e.key === "z" && !e.shiftKey) { e.preventDefault(); this.undo(); }

      else if (e.key === "y" || (e.key === "z" && e.shiftKey)) { e.preventDefault(); this.redo(); }

      else if (e.key === "s") { e.preventDefault(); this.save(); }

    },



    // --- Saving and settings ------------------------------------------------------------------



    async save() {

      if (!this.dirty || this.saving) return;

      this.saving = true;

      try {

        const portChanged = this.draft.settings.web.port !== this.saved.settings.web.port;

        const state = await api("/api/save", { method: "POST", json: this.draft }).then((r) => r.json());

        const keep = { pageIndex: this.pageIndex, selectedSlot: this.selectedSlot };

        this.restoring = true;

        this.applyState({ ...state, live: !this.isDemo });

        Object.assign(this, keep);

        this.$nextTick(() => { this.restoring = false; });

        this.notify(portChanged ? this.t("saved.port") : this.t("saved"));

      } catch (e) {

        this.notify(this.t("save.error"));

      } finally {

        this.saving = false;

      }

    },



    async saveCookie() {

      await api("/api/cookie", { method: "POST", json: { cookie: this.cookieInput } });

      this.cookieInput = "";

      this.hasCookie = true;

      this.cookieStatus = { kind: "ok", text: this.t("we.cookie.stored") };

    },



    async clearCookie() {

      if (!confirm(this.t("we.cookie.clear.confirm"))) return;

      await api("/api/cookie", { method: "POST", json: { cookie: "" } });

      this.hasCookie = false;

      this.cookieStatus = { kind: "", text: "" };

    },



    async testCookie() {

      const r = await api("/api/cookie/test", { method: "POST", json: {} }).then((x) => x.json());

      this.cookieStatus = r.ok

        ? { kind: "ok", text: this.t("we.test.ok").replace("{total}", r.total).replace("{league}", r.league) }

        : { kind: "warn", text: this.t("we.test." + (r.code || "fail")) };

    },



    async testPoePricer() {

      const r = await api("/api/poepricer/test", { method: "POST", json: { url: this.draft.settings.poepricer.url } })

        .then((x) => x.json());

      this.pricerStatus = r.ok

        ? { kind: "ok", text: this.t("pp.test.ok").replace("{league}", r.league || "?")

            .replace("{divine}", r.divine ? Math.round(r.divine) : "?") }

        : { kind: "warn", text: this.t("pp.test.fail") };

    },



    async setAutostart(enabled) {

      const r = await api("/api/autostart", { method: "POST", json: { enabled } }).then((x) => x.json());

      if (!r.error) this.autostart = r;

    },



    async pollScreen() {

      try {

        [this.screen, this.events] = await Promise.all([

          api("/api/screen").then((r) => r.json()),

          api("/api/events").then((r) => r.json()),

        ]);

      } catch (e) { /* the app is gone; the next save says so */ }

    },



    async setCharacter(name, enabled) {

      this.events = await api("/api/events/character", { method: "POST", json: { name, enabled } }).then((r) => r.json());

    },



    async testEvent(kind) {

      const r = await api("/api/events/test", { method: "POST", json: { kind } }).then((x) => x.json());

      if (!r.played) this.notify(this.t("ev.test.offline"));

    },



    notify(text) {

      this.toast = text;

      clearTimeout(this.toastTimer);

      this.toastTimer = setTimeout(() => { this.toast = ""; }, 3500);

    },

  }));

});

