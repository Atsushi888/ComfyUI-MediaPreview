import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const MP_DEBUG = true;

const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".gif"];
const VIDEO_EXTS = [".mp4", ".webm", ".mov", ".mkv", ".avi"];
const MEDIA_EXTS = [...IMAGE_EXTS, ...VIDEO_EXTS];

let MP_RENDER_SEQ = 0;

/* =========================
   debug
========================= */

function logDbg(tag, obj = null) {
  if (!MP_DEBUG) return;
  try {
    if (obj === null) console.log(tag);
    else console.log(tag, obj);
  } catch (_) {}
}

/* =========================
   basic helpers
========================= */

function isVideo(name) {
  const s = (name || "").toLowerCase();
  return VIDEO_EXTS.some((e) => s.endsWith(e));
}

function isImage(name) {
  const s = (name || "").toLowerCase();
  return IMAGE_EXTS.some((e) => s.endsWith(e));
}

function isMedia(name) {
  const s = (name || "").toLowerCase();
  return MEDIA_EXTS.some((e) => s.endsWith(e));
}

function normalizePath(p) {
  return (p || "").toString().trim().replace(/\\/g, "/");
}

function getWidget(node, name) {
  return (node.widgets || []).find((w) => w?.name === name);
}

function buildFullPath(baseDir, media) {
  const base = (baseDir || "").toString().trim().replace(/[\/\\]+$/, "");
  const name = (media || "").toString().trim().replace(/^[\/\\]+/, "");
  if (!base || !name) return "";
  return `${base}/${name}`.replace(/\\/g, "/");
}

function splitSubfolder(path) {
  const p = normalizePath(path);
  const idx = p.lastIndexOf("/");
  if (idx === -1) return { subfolder: "", filename: p };
  return { subfolder: p.slice(0, idx), filename: p.slice(idx + 1) };
}

function resolveTypeAndRelByPath(fullPath) {
  const s = normalizePath(fullPath);
  if (!s) return { type: "input", rel: "" };

  const inRoot = "/workspace/ComfyUI/input/";
  const outRoot = "/workspace/ComfyUI/output/";
  const tmpRoot = "/workspace/ComfyUI/temp/";

  if (s.startsWith(inRoot)) return { type: "input", rel: s.slice(inRoot.length) };
  if (s.startsWith(outRoot)) return { type: "output", rel: s.slice(outRoot.length) };
  if (s.startsWith(tmpRoot)) return { type: "temp", rel: s.slice(tmpRoot.length) };

  return { type: "input", rel: "" };
}

function buildViewURL(fullPath) {
  const { type, rel } = resolveTypeAndRelByPath(fullPath);
  const { subfolder, filename } = splitSubfolder(rel);

  const q = new URLSearchParams();
  q.set("filename", filename || "");
  q.set("type", type);
  q.set("subfolder", subfolder || "");
  q.set("_ts", String(Date.now()));
  q.set("_seq", String(MP_RENDER_SEQ++));
  q.set("_rand", Math.random().toString(36).slice(2));

  return api.apiURL(`/view?${q.toString()}`);
}

function isInputConnected(node, inputName) {
  try {
    const inputs = node.inputs || [];
    const idx = inputs.findIndex((i) => i?.name === inputName);
    if (idx === -1) return false;
    return !!inputs[idx]?.link;
  } catch (_) {
    return false;
  }
}

function hasAnyExplicitSource(node) {
  const mediaPathConnected = isInputConnected(node, "media_path");
  const imageConnected = isInputConnected(node, "image");
  const maskConnected = isInputConnected(node, "mask");

  const base = (getWidget(node, "base_dir")?.value || "").toString().trim();
  const media = (getWidget(node, "media")?.value || "").toString().trim();

  return !!(
    mediaPathConnected ||
    imageConnected ||
    maskConnected ||
    (base && media)
  );
}

function hasRestoredCoreValues(node) {
  const baseW = getWidget(node, "base_dir");
  const mediaW = getWidget(node, "media");
  if (!baseW || !mediaW) return false;

  const base = (baseW.value || "").toString();
  return base.length > 0;
}

/* =========================
   message readers
========================= */

function readMediaPathFromMsg(msg) {
  return normalizePath(
    msg?.output?.media_path ||
    (Array.isArray(msg?.output) ? msg.output[0] : "") ||
    msg?.media_path ||
    msg?.path ||
    ""
  );
}

function buildPathFromViewParams(type, subfolder, filename) {
  const rootMap = {
    input: "/workspace/ComfyUI/input/",
    output: "/workspace/ComfyUI/output/",
    temp: "/workspace/ComfyUI/temp/",
  };

  const base = rootMap[type] || rootMap.output;
  const sub = (subfolder || "").toString().replace(/^\/+/, "").replace(/\/+$/, "");
  const file = (filename || "").toString().replace(/^\/+/, "");
  if (!file) return "";

  return `${base}${sub ? sub + "/" : ""}${file}`.replace(/\\/g, "/");
}

function readImagePathFromMsg(msg) {
  const img = msg?.output?.images?.[0] || msg?.images?.[0] || null;
  if (!img?.filename) return "";
  return normalizePath(buildPathFromViewParams(img.type || "output", img.subfolder || "", img.filename));
}

function readMaskPathFromMsg(msg) {
  const mask = msg?.output?.masks?.[0] || msg?.masks?.[0] || null;
  if (!mask?.filename) return "";
  return normalizePath(buildPathFromViewParams(mask.type || "output", mask.subfolder || "", mask.filename));
}

/* =========================
   backend helpers
========================= */

function extractUniqueId(msg, node) {
  const raw =
    msg?.unique_id ??
    msg?.node ??
    msg?.id ??
    "";

  const s = String(raw).trim();
  if (s) return s;

  return String(node?.id ?? "").trim();
}

async function fetchPreviewPath(uniqueId, nodeId) {
  const q = new URLSearchParams();
  if (uniqueId) q.set("unique_id", String(uniqueId));
  if (nodeId) q.set("node_id", String(nodeId));

  const url = api.apiURL(`/media_preview/ping?${q.toString()}`);

  logDbg("[MediaPreview][fetchPreviewPath:before]", {
    uniqueId,
    nodeId,
    url,
  });

  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return "";

    const js = await res.json();
    logDbg("[MediaPreview][fetchPreviewPath:after]", js);

    if (!js?.file_exists) return "";
    return normalizePath(js?.path || "");
  } catch (e) {
    logDbg("[MediaPreview][fetchPreviewPath:error]", {
      uniqueId,
      nodeId,
      error: String(e),
    });
    return "";
  }
}

async function fetchMediaList(baseDir) {
  const q = new URLSearchParams();
  q.set("base_dir", (baseDir || "").toString().trim());
  const url = api.apiURL(`/media_preview/list?${q.toString()}`);

  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`list fetch failed: ${res.status}`);

  const js = await res.json();
  const items = Array.isArray(js?.items) ? js.items : [];
  return items.filter((x) => typeof x === "string" && isMedia(x));
}

async function refreshMediaChoices(node) {
  const baseW = getWidget(node, "base_dir");
  const mediaW = getWidget(node, "media");
  if (!baseW || !mediaW) return [];

  const baseDir = (baseW.value || "").toString().trim();

  if (!baseDir) {
    return [];
  }

  try {
    const list = await fetchMediaList(baseDir);
    const cur = (mediaW.value || "").toString().trim();

    const vals = cur && !list.includes(cur) ? ["", cur, ...list] : ["", ...list];
    if (mediaW.options && Array.isArray(mediaW.options.values)) {
      mediaW.options.values = vals;
    }

    node.setDirtyCanvas?.(true, true);
    return list;
  } catch (e) {
    logDbg("[MediaPreview][refreshMediaChoices:error]", {
      node_id: node.id,
      error: String(e),
      baseDir,
    });

    const cur = (mediaW.value || "").toString().trim();
    const vals = cur ? ["", cur] : [""];
    if (mediaW.options && Array.isArray(mediaW.options.values)) {
      mediaW.options.values = vals;
    }

    node.setDirtyCanvas?.(true, true);
    return [];
  }
}

/* =========================
   video helpers
========================= */

async function safePlay(video) {
  try {
    const p = video.play();
    if (p && typeof p.then === "function") {
      await p;
    }
  } catch (_) {}
}

/* =========================
   path resolver
========================= */

async function resolvePreviewPath(node, msg, lastUniqueIdRef) {
  const mediaPathConnected = isInputConnected(node, "media_path");
  const imageConnected = isInputConnected(node, "image");
  const maskConnected = isInputConnected(node, "mask");

  let resolvedPath = "";

  if (mediaPathConnected) {
    const uid = extractUniqueId(msg, node);
    if (uid) lastUniqueIdRef.value = uid;

    resolvedPath = readMediaPathFromMsg(msg);
    logDbg("[MediaPreview][resolvePreviewPath:from_msg]", {
      node_id: node.id,
      unique_id: uid || lastUniqueIdRef.value,
      resolvedPath,
    });
    if (resolvedPath) return resolvedPath;

    resolvedPath = await fetchPreviewPath(uid || lastUniqueIdRef.value, node.id);
    logDbg("[MediaPreview][poll]", {
      node_id: node.id,
      unique_id: lastUniqueIdRef.value || "",
    });

    logDbg("[MediaPreview][resolvePreviewPath:from_ping]", {
      node_id: node.id,
      unique_id: uid || lastUniqueIdRef.value,
      resolvedPath,
    });
    if (resolvedPath) return resolvedPath;

    return "";
  }

  if (imageConnected) {
    const uid = extractUniqueId(msg, node);
    if (uid) lastUniqueIdRef.value = uid;

    resolvedPath = readImagePathFromMsg(msg);
    logDbg("[MediaPreview][resolvePreviewPath:image:from_msg]", {
      node_id: node.id,
      unique_id: uid || lastUniqueIdRef.value,
      resolvedPath,
    });
    if (resolvedPath && isImage(resolvedPath)) {
      return resolvedPath;
    }

    resolvedPath = await fetchPreviewPath(uid || lastUniqueIdRef.value, node.id);
    logDbg("[MediaPreview][resolvePreviewPath:image:from_ping]", {
      node_id: node.id,
      unique_id: uid || lastUniqueIdRef.value,
      resolvedPath,
    });
    if (resolvedPath && isImage(resolvedPath)) {
      return resolvedPath;
    }

    return "";
  }

  if (maskConnected) {
    const uid = extractUniqueId(msg, node);
    if (uid) lastUniqueIdRef.value = uid;

    resolvedPath = readMaskPathFromMsg(msg);
    logDbg("[MediaPreview][resolvePreviewPath:mask:from_msg]", {
      node_id: node.id,
      unique_id: uid || lastUniqueIdRef.value,
      resolvedPath,
    });
    if (resolvedPath && isImage(resolvedPath)) {
      return resolvedPath;
    }

    resolvedPath = await fetchPreviewPath(uid || lastUniqueIdRef.value, node.id);
    logDbg("[MediaPreview][resolvePreviewPath:mask:from_ping]", {
      node_id: node.id,
      unique_id: uid || lastUniqueIdRef.value,
      resolvedPath,
    });
    if (resolvedPath && isImage(resolvedPath)) {
      return resolvedPath;
    }

    return "";
  }

  const base = (getWidget(node, "base_dir")?.value || "").toString().trim();
  const media = (getWidget(node, "media")?.value || "").toString().trim();

  if (base && media) {
    resolvedPath = normalizePath(buildFullPath(base, media));
    if (resolvedPath && isMedia(resolvedPath)) return resolvedPath;
  }

  return "";
}

/* =========================
   extension
========================= */

app.registerExtension({
  name: "media_preview_unified",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== "MediaPreview") return;

    const origOnNodeCreated = nodeType.prototype.onNodeCreated;

    nodeType.prototype.onNodeCreated = function () {
      const r = origOnNodeCreated?.apply(this, arguments);
      const hasPollingSource = () => {
        return (
          isInputConnected(this, "media_path") ||
          isInputConnected(this, "image") ||
          isInputConnected(this, "mask")
        );
      };      

      let previewWidget = null;

      // ===== polling制御 =====
      let pollTimer = null;
      let lastPolledPath = "";
    
      const stopPolling = () => {
        if (pollTimer) {
          clearInterval(pollTimer);
          pollTimer = null;
        }
        lastPolledPath = "";
      };
    
      const startPolling = () => {
        if (pollTimer) return;
    
        pollTimer = setInterval(async () => {
          try {
            if (!hasPollingSource()) {
              stopPolling();
              return;
            }
    
            const path = await fetchPreviewPath(lastUniqueIdRef.value || this.id, this.id);
            const p = normalizePath(path);
    
            if (!p) {
              lastPolledPath = "";
              setMediaPathDisplay("");
              clear();
    
              if (isInputConnected(this, "image")) {
                setStatus("Waiting image...");
              } else if (isInputConnected(this, "mask")) {
                setStatus("Waiting mask...");
              } else {
                setStatus("Waiting input...");
              }
    
              this.setDirtyCanvas?.(true, true);
              return;
            }
    
            if (p === lastPolledPath) return;
    
            lastPolledPath = p;
    
            setMediaPathDisplay(p);
            render(p);
            this.setDirtyCanvas?.(true, true);
    
          } catch (e) {
            console.warn("[MediaPreview] polling error:", e);
          }
        }, 400);
      };

      /* ---------- media_path display DOM ---------- */
      const pathBar = document.createElement("div");
      pathBar.style.width = "100%";
      pathBar.style.display = "block";
      pathBar.style.padding = "0";
      pathBar.style.margin = "0";

      const pathInput = document.createElement("input");
      pathInput.type = "text";
      pathInput.value = "";
      pathInput.readOnly = true;
      pathInput.style.width = "100%";
      pathInput.style.boxSizing = "border-box";
      pathInput.style.fontSize = "11px";
      pathInput.style.padding = "2px 6px";
      pathInput.style.margin = "0";
      pathInput.style.height = "24px";
      pathInput.style.minHeight = "24px";
      pathInput.style.borderRadius = "6px";

      pathBar.appendChild(pathInput);

      let pathWidget = null;
      try {
        pathWidget = this.addDOMWidget?.("media_path_display", "div", pathBar, { serialize: false });
      } catch (_) {}

      if (pathWidget) {
        pathWidget.computeSize = (width) => [Math.max(width || 300, 300), 26];
      }

      const setMediaPathDisplay = (value) => {
        try {
          pathInput.value = normalizePath(value || "");
          this.setDirtyCanvas?.(true, true);
        } catch (_) {}
      };

      /* ---------- preview DOM ---------- */
      const wrap = document.createElement("div");
      wrap.style.width = "100%";
      wrap.style.height = "100%";
      wrap.style.display = "flex";
      wrap.style.alignItems = "center";
      wrap.style.justifyContent = "center";
      wrap.style.background = "rgba(0,0,0,0.15)";
      wrap.style.borderRadius = "8px";
      wrap.style.overflow = "hidden";
      wrap.style.userSelect = "none";

      const status = document.createElement("div");
      status.textContent = "Waiting input...";
      status.style.opacity = "0.7";
      wrap.appendChild(status);

      let currentEl = null;
      let mediaHookedWidget = null;
      let refreshBusy = false;
      const lastUniqueIdRef = { value: "" };
      let renderToken = 0;

      const setStatus = (text) => {
        status.textContent = text;
        if (!wrap.contains(status)) wrap.appendChild(status);
      };

      const clear = () => {
        renderToken += 1;

        if (currentEl) {
          try { currentEl.pause?.(); } catch (_) {}
          try {
            if (currentEl.tagName === "VIDEO") {
              currentEl.removeAttribute("src");
              currentEl.src = "";
              currentEl.load?.();
            }
          } catch (_) {}
          try { currentEl.remove(); } catch (_) {}
          currentEl = null;
        }

        wrap.innerHTML = "";
        wrap.appendChild(status);
      };

      const render = (fullPath) => {
        const p = normalizePath(fullPath);

        logDbg("[MediaPreview][render]", {
          node_id: this.id,
          fullPath: p,
        });

        if (!p) {
          clear();
          setStatus("Waiting input...");
          return;
        }

        if (!isMedia(p)) {
          clear();
          setStatus("Unsupported");
          return;
        }

        const token = ++renderToken;
        const url = buildViewURL(p);

        wrap.innerHTML = "";

        if (isVideo(p)) {
          const v = document.createElement("video");
          v.src = url;
          v.style.width = "100%";
          v.style.height = "100%";
          v.style.objectFit = "contain";
          v.controls = true;
          v.muted = true;
          v.defaultMuted = true;
          v.autoplay = true;
          v.playsInline = true;
          v.loop = !!getWidget(this, "loop")?.value;
          v.preload = "auto";

          v.setAttribute("muted", "");
          v.setAttribute("autoplay", "");
          v.setAttribute("playsinline", "");
          v.setAttribute("webkit-playsinline", "");
          v.setAttribute("preload", "auto");

          v.addEventListener("loadeddata", async () => {
            if (token !== renderToken) return;
            wrap.innerHTML = "";
            currentEl = v;
            wrap.appendChild(v);
            try { status.remove(); } catch (_) {}
            await safePlay(v);
          });

          v.addEventListener("error", () => {
            if (token !== renderToken) return;
            currentEl = null;
            wrap.innerHTML = "";
            setStatus("VIDEO LOAD ERROR");
          });

          try { v.load(); } catch (_) {}
          return;
        }

        const img = document.createElement("img");
        img.src = url;
        img.style.width = "100%";
        img.style.height = "100%";
        img.style.objectFit = "contain";

        img.addEventListener("load", () => {
          if (token !== renderToken) return;
          wrap.innerHTML = "";
          currentEl = img;
          wrap.appendChild(img);
          try { status.remove(); } catch (_) {}
        });

        img.addEventListener("error", () => {
          if (token !== renderToken) return;
          currentEl = null;
          wrap.innerHTML = "";
          setStatus("IMAGE LOAD ERROR");
        });
      };

      try {
        previewWidget = this.addDOMWidget?.("preview", "div", wrap, { serialize: false });
      } catch (_) {}

      if (previewWidget) {
        previewWidget.computeSize = (width) => [Math.max(width || 300, 300), 360];
      }

      const minW = 360;
      const minH = 540;
      this.size = this.size || [minW, minH];
      this.size[0] = Math.max(this.size[0], minW);
      this.size[1] = Math.max(this.size[1], minH);

      const renderCanonical = () => {
        const fullPath = buildFullPath(
          getWidget(this, "base_dir")?.value,
          getWidget(this, "media")?.value
        );
        setMediaPathDisplay(fullPath);
        render(fullPath);
        this.setDirtyCanvas?.(true, true);
      };

      const decideAndRender = async (msg = null) => {
        // polling制御
        if (
          isInputConnected(this, "media_path") ||
          isInputConnected(this, "image") ||
          isInputConnected(this, "mask")
        ) {
          startPolling();
        } else {
          stopPolling();
        }

        if (!hasAnyExplicitSource(this)) {
          setMediaPathDisplay("");
          clear();
          setStatus("Waiting input...");
          this.setDirtyCanvas?.(true, true);
          return;
        }

        if (refreshBusy) return;
        refreshBusy = true;

        try {
          const nextPath = await resolvePreviewPath(this, msg, lastUniqueIdRef);

          logDbg("[MediaPreview][decideAndRender]", {
            node_id: this.id,
            nextPath,
          });

          setMediaPathDisplay(nextPath);

          if (!nextPath) {
            lastPolledPath = "";
            clear();
        
            if (isInputConnected(this, "image")) {
              setStatus("Waiting image...");
            } else if (isInputConnected(this, "mask")) {
              setStatus("Waiting mask...");
            } else {
              setStatus("Waiting input...");
            }
        
            this.setDirtyCanvas?.(true, true);
            return;
          }
            
          lastPolledPath = nextPath;
          render(nextPath);
          this.setDirtyCanvas?.(true, true);
            
        } finally {
          refreshBusy = false;
        }
      };

      const reorderWidgets = (afterRestore = false) => {
        if (!Array.isArray(this.widgets)) return;

        const baseW = getWidget(this, "base_dir");
        const mediaW = getWidget(this, "media");
        const loopW = getWidget(this, "loop");

        if (!afterRestore) {
          return;
        }

        if (pathWidget && !this.widgets.includes(pathWidget)) {
          this.widgets.push(pathWidget);
        }
        if (previewWidget && !this.widgets.includes(previewWidget)) {
          this.widgets.push(previewWidget);
        }

        const keep = [];
        const used = new Set();

        if (baseW) { keep.push(baseW); used.add(baseW); }
        if (mediaW) { keep.push(mediaW); used.add(mediaW); }
        if (loopW) { keep.push(loopW); used.add(loopW); }
        if (pathWidget) { keep.push(pathWidget); used.add(pathWidget); }
        if (previewWidget) { keep.push(previewWidget); used.add(previewWidget); }

        const rest = this.widgets.filter((w) => !used.has(w));
        this.widgets = [...keep, ...rest];

        this.setDirtyCanvas?.(true, true);
      };

      const ensureMediaComboWidget = () => {
        const mediaW = getWidget(this, "media");
        if (!mediaW || !Array.isArray(this.widgets)) return false;

        if ((mediaW.type || "").toLowerCase() === "combo") return false;

        const saved = (mediaW.value || "").toString();
        const idx = this.widgets.indexOf(mediaW);
        if (idx >= 0) this.widgets.splice(idx, 1);

        const combo = this.addWidget(
          "combo",
          "media",
          saved,
          (v) => {
            combo.value = (v || "").toString();
            if (isInputConnected(this, "media_path")) return;
            if (isInputConnected(this, "image")) return;
            if (isInputConnected(this, "mask")) return;
            renderCanonical();
          },
          { values: saved ? ["", saved] : [""] }
        );

        combo.name = "media";
        combo.value = saved;
        mediaHookedWidget = null;
        return true;
      };

      const hookWidget = (name, fn) => {
        const w = getWidget(this, name);
        if (!w) return;

        if (name === "media") {
          if (mediaHookedWidget === w) return;
          mediaHookedWidget = w;
        }

        const orig = w.callback;
        w.callback = (...args) => {
          try { orig?.apply(w, args); } catch (_) {}
          fn?.();
        };
      };

      const hookAllWidgets = () => {
        hookWidget("base_dir", async () => {
          if (isInputConnected(this, "media_path")) return;
          if (isInputConnected(this, "image")) return;
          if (isInputConnected(this, "mask")) return;
          await refreshMediaChoices(this);
          await decideAndRender();
        });

        hookWidget("media", () => {
          if (isInputConnected(this, "media_path")) return;
          if (isInputConnected(this, "image")) return;
          if (isInputConnected(this, "mask")) return;
          renderCanonical();
        });

        hookWidget("loop", () => {
          if (currentEl && currentEl.tagName === "VIDEO") {
            currentEl.loop = !!getWidget(this, "loop")?.value;
          }
        });
      };

      const initAfterRestore = async (retry = 0) => {
        if (retry > 20) {
          reorderWidgets(true);
          hookAllWidgets();
          await decideAndRender();
          return;
        }

        if (!hasRestoredCoreValues(this)) {
          setTimeout(() => {
            initAfterRestore(retry + 1);
          }, 250);
          return;
        }

        ensureMediaComboWidget();
        reorderWidgets(true);
        hookAllWidgets();

        const base = (getWidget(this, "base_dir")?.value || "").toString().trim();
        if (base) {
          await refreshMediaChoices(this);
        }

        await decideAndRender();
      };

      const origOnConn = this.onConnectionsChange;
      this.onConnectionsChange = async (type, slotIndex, connected, linkInfo, ioSlot) => {
        try { origOnConn?.call(this, type, slotIndex, connected, linkInfo, ioSlot); } catch (_) {}
        await decideAndRender();
      };

      const origOnExecuted = this.onExecuted;
      this.onExecuted = async (msg) => {
        try { origOnExecuted?.call(this, msg); } catch (_) {}

        logDbg("========== [MediaPreview.onExecuted] ==========");
        logDbg("[MediaPreview.onExecuted] node_id=", this.id);
        logDbg("[MediaPreview.onExecuted] raw msg=", msg);
        logDbg("[MediaPreview.onExecuted] readMediaPathFromMsg=", readMediaPathFromMsg(msg));

        await decideAndRender(msg);
      };

      setTimeout(() => {
        initAfterRestore(0);
      }, 50);

      const origOnRemoved = this.onRemoved;
      this.onRemoved = () => {
        try { origOnRemoved?.call(this); } catch (_) {}
        stopPolling();  // ←追加
        clear();
        try { wrap.remove(); } catch (_) {}
      };

      return r;
    };
  },
});