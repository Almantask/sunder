(() => {
  const $ = (id) => document.getElementById(id);
  const audio = new Audio();
  audio.preload = "none";
  audio.volume = 0.9;

  const state = {
    view: "library",
    job: null,
    poll: null,
    offset: 0,
    limit: 80,
    category: "",
    lastLog: 0,
    playing: null,
    selectedPath: "",
    selectedRow: null,
    categoryNames: [],
    reviewQueue: "pending",
  };

  const copy = {
    library: ["Library", "Choose a folder of tracks, then embed, scan, report, or run a full analysis."],
    categories: ["Categories", "Edit prompt wording freely. Re-classify after saving — no need to re-embed."],
    review: ["Review", "Work through the queue. Accepted and rejected tracks are hidden unless you open Reviewed."],
    settings: ["Settings", "Tune scanning, classification, and how files are copied into category folders."],
  };

  let deviceName = "";

  function toast(message, err) {
    const node = document.createElement("div");
    node.className = "toast" + (err ? " err" : "");
    node.textContent = message;
    $("toasts").appendChild(node);
    setTimeout(() => node.remove(), 4200);
  }

  async function api(path, opts) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const text = await res.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(text || res.statusText);
    }
    if (!res.ok) {
      throw new Error(data.error || res.statusText);
    }
    return data;
  }

  function settingsFromForm() {
    const limitRaw = $("limit").value.trim();
    return {
      library: $("library").value.trim(),
      cache: $("cache").value.trim() || ".sunder_cache",
      categories: $("categories-path").value.trim() || "categories.yaml",
      results: $("results").value.trim() || "results.csv",
      report: $("report").value.trim() || "report.html",
      organize_dest: $("organize-dest").value.trim() || "organized",
      device: $("device").value,
      recursive: $("recursive").checked,
      force: $("force").checked,
      limit: limitRaw === "" ? null : Number(limitRaw),
      save_file: $("save-file").checked,
      embed_track: $("embed-track").checked,
      threshold: Number($("threshold").value),
      min_margin: Number($("min-margin").value),
    };
  }

  function applySettings(s) {
    $("library").value = s.library || "";
    $("cache").value = s.cache || ".sunder_cache";
    $("categories-path").value = s.categories || "categories.yaml";
    $("results").value = s.results || "results.csv";
    $("report").value = s.report || "report.html";
    $("organize-dest").value = s.organize_dest || "organized";
    $("device").value = s.device || "auto";
    $("recursive").checked = s.recursive !== false;
    $("force").checked = Boolean(s.force);
    $("limit").value = s.limit || "";
    $("save-file").checked = s.save_file !== false;
    $("embed-track").checked = Boolean(s.embed_track);
    $("threshold").value = s.threshold ?? 0.35;
    $("min-margin").value = s.min_margin ?? 0.02;
    syncSliders();
    syncDevicePill();
  }

  function syncDevicePill() {
    const bits = ["device · " + ($("device").value || "auto")];
    if (deviceName) bits.push(deviceName);
    $("device-pill").textContent = bits.join(" · ");
  }

  function syncSliders() {
    $("threshold-val").textContent = Number($("threshold").value).toFixed(2);
    $("margin-val").textContent = Number($("min-margin").value).toFixed(3);
  }

  function setView(name) {
    state.view = name;
    document.querySelectorAll(".view").forEach((el) => {
      const on = el.id === "view-" + name;
      el.classList.toggle("is-on", on);
      el.hidden = !on;
    });
    document.querySelectorAll(".nav-btn").forEach((btn) => {
      const on = btn.dataset.view === name;
      btn.classList.toggle("is-active", on);
      if (on) btn.setAttribute("aria-current", "page");
      else btn.removeAttribute("aria-current");
    });
    const [title, lede] = copy[name] || copy.library;
    $("view-title").textContent = title;
    $("view-lede").textContent = lede;
    if (name === "review") {
      loadCategoryList();
      loadResults();
    }
    if (name === "categories") loadCategories();
  }

  function renderStats(boot, scan) {
    $("stat-found").textContent = scan && scan.count != null ? scan.count : "—";
    $("stat-cache").textContent = boot.cache?.tracks ?? "—";
    $("stat-classified").textContent = boot.results?.exists ? boot.results.tracks : "—";
    $("stat-low").textContent = boot.results?.exists ? boot.results.pending ?? boot.results.low : "—";
  }

  function fmtTime(sec) {
    if (!Number.isFinite(sec)) return "0:00";
    const s = Math.max(0, Math.floor(sec));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return m + ":" + String(r).padStart(2, "0");
  }

  function renderJob(job) {
    state.job = job;
    const busy = Boolean(job && job.status === "running");
    document.body.classList.toggle("is-busy", busy);
    $("btn-cancel").disabled = !busy;
    ["btn-embed", "btn-pipeline", "btn-report", "btn-organize", "btn-scan"].forEach((id) => {
      $(id).disabled = busy;
    });
    const pill = $("job-pill");
    pill.classList.remove("is-run", "is-ok", "is-err");
    if (!job) {
      pill.textContent = "idle";
      $("job-msg").textContent = "Ready.";
      $("job-bar").style.width = "0%";
      $("job-counts").textContent = "";
      return;
    }
    pill.textContent = job.status + (job.kind ? " · " + job.kind : "");
    if (job.status === "running") pill.classList.add("is-run");
    if (job.status === "done") pill.classList.add("is-ok");
    if (job.status === "error") pill.classList.add("is-err");
    $("job-msg").textContent = job.message || job.status;
    const total = Number(job.total) || 0;
    const current = Number(job.current) || 0;
    const pct = total ? Math.min(100, Math.round((current / total) * 100)) : busy ? 8 : 0;
    $("job-bar").style.width = pct + "%";
    $("job-counts").textContent = total ? current + " / " + total : "";
    const log = $("log");
    const lines = job.log || [];
    if (lines.length < state.lastLog) {
      log.innerHTML = "";
      state.lastLog = 0;
    }
    for (let i = state.lastLog; i < lines.length; i += 1) {
      const row = document.createElement("div");
      row.textContent = lines[i].line || lines[i];
      log.appendChild(row);
    }
    state.lastLog = lines.length;
    log.scrollTop = log.scrollHeight;
  }

  function startPoll() {
    if (state.poll) return;
    state.poll = setInterval(async () => {
      try {
        const data = await api("/api/job");
        const prev = state.job && state.job.status;
        renderJob(data.job);
        const job = data.job;
        if (!job || job.status !== "running") {
          clearInterval(state.poll);
          state.poll = null;
          if (job && prev === "running") {
            if (job.status === "done") {
              toast(job.message || "Done.");
              await refreshBootstrap();
              if (job.kind === "classify" || job.kind === "pipeline") {
                setView("review");
              }
            } else if (job.status === "error") {
              toast(job.error || "Job failed", true);
            } else if (job.status === "cancelled") {
              toast("Cancelled.");
              await refreshBootstrap();
            }
          }
        }
      } catch (err) {
        toast(err.message, true);
      }
    }, 400);
  }

  async function run(path) {
    try {
      await api("/api/settings", { method: "POST", body: JSON.stringify(settingsFromForm()) });
      const data = await api(path, { method: "POST", body: JSON.stringify(settingsFromForm()) });
      state.lastLog = 0;
      $("log").innerHTML = "";
      renderJob(data.job);
      startPoll();
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function browseInto(input) {
    try {
      const data = await api("/api/pick-folder", { method: "POST", body: "{}" });
      if (data.path) input.value = data.path;
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function loadCategories() {
    try {
      const data = await api("/api/categories");
      $("yaml").value = data.yaml || "";
      $("cat-meta").textContent = data.count
        ? data.count + " categories · " + data.path
        : data.path;
      if (data.error) toast(data.error, true);
    } catch (err) {
      $("cat-meta").textContent = err.message;
    }
  }

  function confLabel(n) {
    return Math.round(n * 100) + "%";
  }

  function decisionLabel(review) {
    if (review === "accepted") return "Accepted";
    if (review === "rejected") return "Rejected";
    return "Pending";
  }

  function fillCategoryList(fromRows) {
    const names = new Set(state.categoryNames);
    (fromRows || []).forEach((row) => {
      if (row.category) names.add(row.category);
      if (row.suggested_category) names.add(row.suggested_category);
    });
    const list = $("review-cat-list");
    list.innerHTML = "";
    Array.from(names)
      .sort((a, b) => a.localeCompare(b))
      .forEach((name) => {
        const opt = document.createElement("option");
        opt.value = name;
        list.appendChild(opt);
      });
  }

  async function loadCategoryList() {
    try {
      const data = await api("/api/categories");
      state.categoryNames = data.names || [];
      fillCategoryList();
    } catch {
      state.categoryNames = [];
    }
  }

  function setReviewEnabled(on) {
    $("review-category").disabled = !on;
    $("review-comment").disabled = !on;
    $("review-accept").disabled = !on;
    $("review-reject").disabled = !on;
  }

  function showReview(row) {
    if (!row) {
      state.selectedPath = "";
      $("review-filename").textContent = "Select a track";
      $("review-suggested").textContent =
        "Click a row, listen, then accept the suggestion, reject it, or type your own category.";
      $("review-category").value = "";
      $("review-comment").value = "";
      setReviewEnabled(false);
      return;
    }
    state.selectedPath = row.path;
    state.selectedRow = row;
    $("review-filename").textContent = row.filename;
    const suggested = row.suggested_category || row.category;
    $("review-suggested").textContent =
      "Suggested: " +
      suggested +
      " · " +
      confLabel(row.confidence) +
      (row.runner_up ? " · runner-up " + row.runner_up : "") +
      (row.review === "accepted" && row.category !== suggested ? " · you chose " + row.category : "");
    $("review-category").value = row.category || "";
    $("review-comment").value = row.comment || "";
    setReviewEnabled(true);
  }

  function emptyQueueMessage(data) {
    if (state.reviewQueue === "pending" && !data.pending) {
      return "Queue is clear. Open Reviewed to see accepted and rejected tracks.";
    }
    return "No tracks match this filter.";
  }

  function syncQueueChips(data) {
    const labels = {
      pending: "To review (" + (data.pending || 0) + ")",
      reviewed: "Reviewed (" + (data.reviewed || 0) + ")",
      all: "All (" + (data.all || 0) + ")",
    };
    document.querySelectorAll("#queue-chips .chip").forEach((btn) => {
      const key = btn.dataset.queue;
      btn.classList.toggle("is-on", state.reviewQueue === key);
      if (labels[key]) btn.textContent = labels[key];
    });
  }

  async function saveReview(review) {
    if (!state.selectedPath) return;
    const category = $("review-category").value.trim();
    if (review === "accepted" && !category) {
      toast("Type or pick a category to accept.", true);
      return;
    }
    const path = state.selectedPath;
    const decided = review === "accepted" || review === "rejected";
    let nextPath = path;
    if (decided) {
      const paths = Array.from(document.querySelectorAll("#track-body tr[data-path]")).map((tr) => tr.dataset.path);
      const idx = paths.indexOf(path);
      nextPath = paths[idx + 1] || paths[idx - 1] || "";
    }
    try {
      await api("/api/results/review", {
        method: "POST",
        body: JSON.stringify({
          path,
          review,
          category: category || undefined,
          comment: $("review-comment").value,
        }),
      });
      if (decided) state.selectedPath = nextPath;
      toast(review === "rejected" ? "Rejected." : review === "accepted" ? "Accepted." : "Comment saved.");
      await loadResults();
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function loadResults() {
    const params = new URLSearchParams({
      q: $("search").value.trim(),
      category: state.category,
      low: $("low-only").checked ? "1" : "0",
      review: state.reviewQueue,
      offset: String(state.offset),
      limit: String(state.limit),
    });
    try {
      const data = await api("/api/results?" + params.toString());
      fillCategoryList(data.rows || []);
      syncQueueChips(data);
      if (data.pending != null) $("stat-low").textContent = data.pending;
      const chips = $("cat-chips");
      chips.innerHTML = "";
      const all = document.createElement("button");
      all.className = "chip" + (state.category === "" ? " is-on" : "");
      all.type = "button";
      all.textContent = "All" + (data.queue != null ? " (" + data.queue + ")" : data.all != null ? " (" + data.all + ")" : "");
      all.addEventListener("click", () => {
        state.category = "";
        state.offset = 0;
        loadResults();
      });
      chips.appendChild(all);
      (data.categories || []).forEach((cat) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "chip" + (state.category === cat.name ? " is-on" : "");
        btn.textContent = cat.name + " (" + cat.count + ")";
        btn.addEventListener("click", () => {
          state.category = cat.name;
          state.offset = 0;
          loadResults();
        });
        chips.appendChild(btn);
      });

      const body = $("track-body");
      body.innerHTML = "";
      if (!data.rows || !data.rows.length) {
        const tr = document.createElement("tr");
        tr.className = "empty-row";
        tr.innerHTML = "<td colspan='6'>" + (data.exists ? emptyQueueMessage(data) : "Classify a library to see results here.") + "</td>";
        body.appendChild(tr);
        showReview(null);
      } else {
        let restored = null;
        data.rows.forEach((row) => {
          const tr = document.createElement("tr");
          const classes = [];
          if (row.low_confidence) classes.push("low");
          if (row.review === "accepted") classes.push("accepted");
          if (row.review === "rejected") classes.push("rejected");
          if (state.selectedPath === row.path) {
            classes.push("is-sel");
            restored = row;
          }
          tr.className = classes.join(" ");
          tr.dataset.path = row.path;
          const pct = Math.max(0, Math.min(100, Math.round(row.confidence * 100)));
          tr.innerHTML =
            "<td><button class='play-mini' type='button' aria-label='Play'>▶</button></td>" +
            "<td><div class='filename'></div><div class='prompt'></div></td>" +
            "<td></td>" +
            "<td><span class='meter" + (row.low_confidence ? " is-low" : "") + "'><i style='width:" + pct + "%'></i></span>" +
            confLabel(row.confidence) + "</td>" +
            "<td><span class='badge'></span></td>" +
            "<td></td>";
          tr.children[1].querySelector(".filename").textContent = row.filename;
          tr.children[1].querySelector(".prompt").textContent = row.matched_prompt || "";
          tr.children[2].textContent = row.category;
          const badge = tr.querySelector(".badge");
          badge.textContent = decisionLabel(row.review);
          badge.classList.add("badge-" + (row.review || "pending"));
          tr.children[5].textContent = row.runner_up + " · " + row.runner_up_score.toFixed(3);
          tr.querySelector(".play-mini").addEventListener("click", (ev) => {
            ev.stopPropagation();
            playRow(row);
          });
          tr.addEventListener("dblclick", () => playRow(row));
          tr.addEventListener("click", () => {
            body.querySelectorAll("tr").forEach((n) => n.classList.remove("is-sel"));
            tr.classList.add("is-sel");
            showReview(row);
          });
          tr.addEventListener("contextmenu", (ev) => {
            ev.preventDefault();
            api("/api/reveal", { method: "POST", body: JSON.stringify({ path: row.path }) }).catch((err) => toast(err.message, true));
          });
          body.appendChild(tr);
        });
        if (restored) showReview(restored);
        else {
          const first = data.rows[0];
          const firstRow = body.querySelector("tr[data-path]");
          if (firstRow) firstRow.classList.add("is-sel");
          showReview(first || null);
        }
        syncPlayButton();
      }
      const start = data.total ? data.offset + 1 : 0;
      const end = Math.min(data.offset + data.limit, data.total);
      $("page-label").textContent = data.total ? start + "–" + end + " of " + data.total : "No results";
      $("page-prev").disabled = data.offset <= 0;
      $("page-next").disabled = data.offset + data.limit >= data.total;
      state.pageTotal = data.total;
    } catch (err) {
      toast(err.message, true);
    }
  }

  function isAudioPlaying() {
    return Boolean(audio.src) && !audio.paused && !audio.ended;
  }

  function syncPlayButton() {
    const on = isAudioPlaying();
    const btn = $("play-btn");
    btn.classList.toggle("is-on", on);
    btn.setAttribute("aria-label", on ? "Pause" : "Play");
    const playingPath = on && state.playing ? state.playing.path : "";
    document.querySelectorAll(".play-mini").forEach((mini) => {
      const rowOn = mini.closest("tr") && mini.closest("tr").dataset.path === playingPath;
      mini.classList.toggle("is-on", rowOn);
      mini.setAttribute("aria-label", rowOn ? "Pause" : "Play");
      mini.textContent = rowOn ? "❚❚" : "▶";
    });
  }

  function playRow(row) {
    if (state.playing && state.playing.path === row.path && audio.src && !audio.paused) {
      audio.pause();
      syncPlayButton();
      return;
    }
    state.playing = row;
    audio.src = row.media;
    $("now-title").textContent = row.filename;
    $("now-meta").textContent = row.category + " · " + confLabel(row.confidence);
    audio.play().catch((err) => {
      syncPlayButton();
      toast(err.message || "Playback blocked", true);
    });
    syncPlayButton();
  }

  function togglePlay() {
    if (!audio.src) return;
    if (audio.paused) {
      audio.play().catch((err) => {
        syncPlayButton();
        toast(err.message || "Playback blocked", true);
      });
    } else {
      audio.pause();
    }
    syncPlayButton();
  }

  async function refreshBootstrap(scan) {
    const boot = await api("/api/bootstrap");
    applySettings(boot.settings);
    $("version").textContent = "v" + boot.version;
    renderStats(boot, scan);
    if (boot.job && boot.job.status === "running") {
      renderJob(boot.job);
      startPoll();
    } else if (boot.job) {
      renderJob(boot.job);
    }
    return boot;
  }

  async function init() {
    try {
      await refreshBootstrap();
    } catch (err) {
      toast(err.message, true);
    }
    api("/api/device")
      .then((dev) => {
        deviceName = dev.name || dev.default || "";
        syncDevicePill();
      })
      .catch(() => {});

    document.querySelectorAll(".nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => setView(btn.dataset.view));
    });
    $("threshold").addEventListener("input", syncSliders);
    $("min-margin").addEventListener("input", syncSliders);
    $("browse-library").addEventListener("click", () => browseInto($("library")));
    $("browse-dest").addEventListener("click", () => browseInto($("organize-dest")));
    $("device").addEventListener("change", syncDevicePill);
    $("btn-save-settings").addEventListener("click", async () => {
      try {
        await api("/api/settings", { method: "POST", body: JSON.stringify(settingsFromForm()) });
        syncDevicePill();
        toast("Settings saved.");
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("btn-scan").addEventListener("click", async () => {
      try {
        await api("/api/settings", { method: "POST", body: JSON.stringify(settingsFromForm()) });
        const scan = await api("/api/scan", { method: "POST", body: JSON.stringify(settingsFromForm()) });
        $("scan-hint").textContent =
          "Found " + scan.count + " tracks" + (scan.sample && scan.sample.length ? " · " + scan.sample.slice(0, 6).join(", ") : "");
        const boot = await api("/api/bootstrap");
        renderStats(boot, scan);
        toast("Found " + scan.count + " tracks");
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("btn-embed").addEventListener("click", () => run("/api/embed"));
    $("btn-pipeline").addEventListener("click", () => run("/api/pipeline"));
    $("btn-report").addEventListener("click", () => run("/api/report"));
    $("btn-cancel").addEventListener("click", () => api("/api/job/cancel", { method: "POST", body: "{}" }));
    $("btn-save-cats").addEventListener("click", async () => {
      try {
        const data = await api("/api/categories", {
          method: "PUT",
          body: JSON.stringify({ yaml: $("yaml").value }),
        });
        toast("Saved " + data.count + " categories");
        $("cat-meta").textContent = data.count + " categories · " + data.path;
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("btn-open-report").addEventListener("click", async () => {
      try {
        await api("/api/open-report", { method: "POST", body: "{}" });
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("search").addEventListener(
      "input",
      debounce(() => {
        state.offset = 0;
        loadResults();
      }, 200)
    );
    $("low-only").addEventListener("change", () => {
      state.offset = 0;
      loadResults();
    });
    document.querySelectorAll("#queue-chips .chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.reviewQueue = btn.dataset.queue;
        state.offset = 0;
        loadResults();
      });
    });
    $("review-accept").addEventListener("click", () => saveReview("accepted"));
    $("review-reject").addEventListener("click", () => saveReview("rejected"));
    $("review-comment").addEventListener(
      "change",
      () => {
        if (state.selectedPath) saveReview(state.selectedRow && state.selectedRow.review);
      }
    );
    $("page-prev").addEventListener("click", () => {
      state.offset = Math.max(0, state.offset - state.limit);
      loadResults();
    });
    $("page-next").addEventListener("click", () => {
      state.offset += state.limit;
      loadResults();
    });
    $("btn-organize").addEventListener("click", async () => {
      const mode = document.querySelector("input[name='org-mode']:checked").value;
      const payload = { ...settingsFromForm(), mode, confirm_move: false };
      if (mode === "move") {
        $("move-confirm").value = "";
        $("modal").showModal();
        return;
      }
      try {
        await api("/api/settings", { method: "POST", body: JSON.stringify(payload) });
        const data = await api("/api/organize", { method: "POST", body: JSON.stringify(payload) });
        state.lastLog = 0;
        $("log").innerHTML = "";
        renderJob(data.job);
        startPoll();
      } catch (err) {
        toast(err.message, true);
      }
    });
    $("modal-cancel").addEventListener("click", () => $("modal").close());
    $("modal-ok").addEventListener("click", async () => {
      if ($("move-confirm").value.trim() !== "MOVE") {
        toast("Type MOVE to confirm.", true);
        return;
      }
      $("modal").close();
      const payload = { ...settingsFromForm(), mode: "move", confirm_move: true };
      try {
        const data = await api("/api/organize", { method: "POST", body: JSON.stringify(payload) });
        state.lastLog = 0;
        $("log").innerHTML = "";
        renderJob(data.job);
        startPoll();
      } catch (err) {
        toast(err.message, true);
      }
    });

    $("play-btn").addEventListener("click", togglePlay);
    $("volume").addEventListener("input", () => {
      audio.volume = Number($("volume").value);
    });
    $("seek").addEventListener("input", () => {
      if (!audio.duration) return;
      audio.currentTime = (Number($("seek").value) / 1000) * audio.duration;
    });
    audio.addEventListener("timeupdate", () => {
      $("t-cur").textContent = fmtTime(audio.currentTime);
      $("t-dur").textContent = fmtTime(audio.duration);
      if (audio.duration) $("seek").value = String(Math.round((audio.currentTime / audio.duration) * 1000));
    });
    ["play", "playing", "pause", "ended", "emptied", "error"].forEach((ev) => {
      audio.addEventListener(ev, syncPlayButton);
    });

    document.addEventListener("keydown", (ev) => {
      const tag = ev.target && ev.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (ev.code === "Space") {
        ev.preventDefault();
        togglePlay();
      }
      if (ev.key === "/") {
        ev.preventDefault();
        setView("review");
        $("search").focus();
      }
      if (state.view === "review" && state.selectedPath) {
        if (ev.key === "a" || ev.key === "A") {
          ev.preventDefault();
          saveReview("accepted");
        }
        if (ev.key === "r" || ev.key === "R") {
          ev.preventDefault();
          saveReview("rejected");
        }
      }
    });
  }

  function debounce(fn, ms) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  init();
})();
