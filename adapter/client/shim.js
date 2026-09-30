/* Transport adapter for the unmodified board. No cookie or extra API credential. */
(() => {
  "use strict";
  const status = document.getElementById("connection-status");
  const prefix = location.pathname.slice(0, -"/client/player".length);
  const parameters = new URLSearchParams(location.search);
  const address = new URL(
    parameters.get("address") || `${prefix}/player${location.search}`,
    location.href
  );
  address.protocol =
    address.protocol === "https:" || address.protocol === "wss:"
      ? "wss:"
      : "ws:";
  address.searchParams.set("mode", "browser");
  let socket;
  let attempts = 0;
  let stableTimer;
  const maxAttempts = 8;
  const pending = new Map();
  const sources = new Map();
  let counter = 0;
  let loaded = false;
  let finished = false;
  const show = (text) => {
    status.textContent = text;
  };
  const nativeFetch = window.fetch.bind(window);
  function pathFor(input) {
    const url = new URL(input, location.href);
    if (url.origin !== location.origin)
      throw new Error("Not available in this game");
    let path = url.pathname;
    if (prefix && path.startsWith(prefix + "/"))
      path = path.slice(prefix.length);
    return path + url.search;
  }
  function request(method, url, body) {
    return new Promise((resolve, reject) => {
      if (socket.readyState !== WebSocket.OPEN) {
        reject(new Error("Disconnected; reconnecting"));
        return;
      }
      const path = pathFor(url);
      const id = ++counter;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error("Game request timed out"));
      }, 20000);
      pending.set(id, { resolve, reject, timer });
      socket.send(
        JSON.stringify({ type: "request", id, method, path, body: body || "" })
      );
    });
  }
  window.fetch = async (input, options = {}) => {
    const url = typeof input === "string" ? input : input.url;
    const response = await request(options.method || "GET", url, options.body);
    return new Response(response.body, {
      status: response.status,
      headers: response.headers,
    });
  };
  class TunnelXHR extends EventTarget {
    constructor() {
      super();
      this.readyState = 0;
      this.status = 0;
      this.responseText = "";
      this.response = "";
      this.responseType = "";
      this.timeout = 0;
      this.upload = new EventTarget();
      this.headers = {};
      this.onloadend = null;
    }
    emit(name) {
      const event = new Event(name);
      this.dispatchEvent(event);
      if (this[`on${name}`]) this[`on${name}`](event);
    }
    open(method, url, asynchronous = true) {
      if (!asynchronous)
        throw new Error("Synchronous requests are not supported");
      this.method = method;
      this.url = url;
      this.readyState = 1;
      this.emit("readystatechange");
    }
    setRequestHeader() {} // Authentication and content types belong to the server transport.
    getAllResponseHeaders() {
      return Object.entries(this.headers)
        .map(([k, v]) => `${k}: ${v}`)
        .join("\r\n");
    }
    getResponseHeader(name) {
      return this.headers[name.toLowerCase()] || null;
    }
    abort() {
      this.aborted = true;
      this.emit("abort");
    }
    send(body) {
      if (body instanceof FormData || body instanceof URLSearchParams)
        body = new URLSearchParams(body).toString();
      request(this.method, this.url, body)
        .then((response) => {
          if (this.aborted) return;
          this.status = response.status;
          this.headers = response.headers;
          this.responseText = response.body;
          this.response =
            this.responseType === "json"
              ? JSON.parse(response.body)
              : response.body;
          this.readyState = 4;
          this.emit("readystatechange");
          this.emit("load");
          this.emit("loadend");
          if (response.status === 403) show("Not available in this game");
        })
        .catch(() => {
          if (!this.aborted) {
            this.emit("error");
            this.emit("loadend");
          }
        });
    }
  }
  window.XMLHttpRequest = TunnelXHR;
  class TunnelEventSource extends EventTarget {
    constructor(url) {
      super();
      this.id = ++counter;
      this.readyState = 0;
      this.path = pathFor(url);
      sources.set(this.id, this);
      this.subscribe();
    }
    subscribe() {
      if (socket.readyState === WebSocket.OPEN)
        socket.send(JSON.stringify({ type: "subscribe", id: this.id, path: this.path }));
    }
    emit(name, data) {
      const event =
        name === "message" ? new MessageEvent(name, { data }) : new Event(name);
      this.dispatchEvent(event);
      if (this[`on${name}`]) this[`on${name}`](event);
    }
    close() {
      this.readyState = 2;
      sources.delete(this.id);
      if (socket.readyState === WebSocket.OPEN)
        socket.send(JSON.stringify({ type: "unsubscribe", id: this.id }));
    }
  }
  window.EventSource = TunnelEventSource;
  // Upstream telemetry includes location.href (the seat capability). Never forward it.
  navigator.sendBeacon = () => false;
  window.wDAds = { shouldShowAds: () => false };
  window.gtag = () => {};
  document.addEventListener(
    "click",
    (event) => {
      const button = event.target.closest("button");
      if (
        button &&
        button.closest("tr")?.textContent.trim().startsWith("Sandbox:")
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
        show("Sandbox is not available in this game");
        return;
      }
      const anchor = event.target.closest("a");
      if (
        anchor &&
        anchor.getAttribute("href") &&
        !anchor.getAttribute("href").startsWith("#")
      ) {
        event.preventDefault();
        event.stopImmediatePropagation();
        show("Site navigation is not available in this game");
      }
    },
    true
  );
  function connect() {
    socket = new WebSocket(address);
    socket.onmessage = async ({ data }) => {
      const message = JSON.parse(data);
      if (message.type === "hello") {
        clearTimeout(stableTimer);
        stableTimer = setTimeout(() => { attempts = 0; }, 10000);
        show("");
        if (loaded) {
          for (const source of sources.values()) {
            source.subscribe();
            source.emit("message", JSON.stringify({channel: "resync"}));
          }
          return;
        }
        loaded = true;
        const url = new URL(location.href);
        url.searchParams.set("gameID", message.webdip.game_id);
        history.replaceState(null, "", url);
        // Load only the build's entrypoints; omit upstream HTML's advertising and analytics tags.
        const manifest = await nativeFetch("board/asset-manifest.json").then(
          (r) => r.json()
        );
        for (const file of manifest.entrypoints) {
          const element = document.createElement(
            file.endsWith(".css") ? "link" : "script"
          );
          if (file.endsWith(".css")) {
            element.rel = "stylesheet";
            element.href = "board/" + file;
          } else {
            element.src = "board/" + file;
            element.async = false;
          }
          document.head.appendChild(element);
        }
        show("");
      } else if (message.type === "response") {
        const item = pending.get(message.id);
        if (item) {
          clearTimeout(item.timer);
          pending.delete(message.id);
          item.resolve(message);
        }
      } else if (message.type.startsWith("event")) {
        const source = sources.get(message.id);
        if (source) {
          if (message.type === "event_open") {
            source.readyState = 1;
            source.emit("open");
          } else
            source.emit(
              message.type === "event" ? "message" : "error",
              message.data
            );
        }
      } else if (message.type === "game_over") {
        finished = true;
        show("Game finished");
        socket.send(JSON.stringify({ type: "game_over_ack" }));
      }
    };
    socket.onclose = () => {
      clearTimeout(stableTimer);
      show(
        finished
          ? "Game finished"
          : loaded
          ? "Disconnected. Reconnecting to your seat…"
          : "Unable to connect. Check your seat link. Reconnecting…"
      );
      for (const item of pending.values()) {
        clearTimeout(item.timer);
        item.reject(new Error("Disconnected"));
      }
      pending.clear();
      if (!finished) {
        if (attempts < maxAttempts) {
          const delay = Math.min(500 * 2 ** attempts++, 5000);
          setTimeout(connect, delay);
        } else show("Disconnected. Automatic reconnect stopped. Check your seat link and reload.");
      }
    };
    socket.onerror = () =>
      show("Unable to connect. Check your seat link. Reconnecting…");
  }
  document.getElementById("dismiss-help").onclick = () => {
    document.getElementById("play-help").hidden = true;
  };
  connect();
})();
