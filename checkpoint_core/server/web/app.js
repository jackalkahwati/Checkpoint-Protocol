/* Checkpoint Web Review UI — no build step, talks to the v0.8 hosted API.
   GitHub reviews commits. Checkpoint reviews work sessions. */
(function () {
  "use strict";
  var TOKEN_KEY = "ckpt_token";
  var app = document.getElementById("app");
  var crumbs = document.getElementById("crumbs");
  var authbox = document.getElementById("authbox");
  var serverinfo = document.getElementById("serverinfo");

  // ---------------------------------------------------------------- auth/token
  function getToken() { return localStorage.getItem(TOKEN_KEY) || ""; }
  function setToken(t) { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); }

  // ---------------------------------------------------------------- api client
  function api(method, path, body, opts) {
    opts = opts || {};
    var headers = {};
    var data = null;
    if (getToken()) headers["Authorization"] = "Bearer " + getToken();
    if (body !== undefined && body !== null) { headers["Content-Type"] = "application/json"; data = JSON.stringify(body); }
    return fetch(path, { method: method, headers: headers, body: data }).then(function (r) {
      if (r.status === 401) { setToken(null); var e = new Error("unauthorized"); e.status = 401; throw e; }
      var ct = r.headers.get("Content-Type") || "";
      var p = ct.indexOf("application/json") >= 0 ? r.json() : r.text();
      return p.then(function (payload) {
        if (!r.ok) { var e = new Error((payload && payload.error) || ("HTTP " + r.status)); e.status = r.status; e.payload = payload; throw e; }
        return payload;
      });
    });
  }

  // ---------------------------------------------------------------- helpers
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function short(id) { return id ? String(id).slice(0, 12) : "—"; }
  function badge(text, kind) { return '<span class="badge ' + (kind || "mut") + '">' + esc(text) + "</span>"; }
  function when(ts) { return ts ? esc(String(ts).slice(0, 19).replace("T", " ")) : ""; }
  function pct(x) { return Math.round((x || 0) * 100) + "%"; }

  function statusBadge(s) {
    var k = { accepted: "ok", active: "info", rejected: "warn", rolled_back: "bad", merged: "violet" }[s] || "mut";
    return badge(s || "?", k);
  }
  function actorBadge(actor) {
    actor = actor || {}; var t = actor.type || "human";
    var k = { human: "info", agent: "violet", ci: "cyan", machine: "mut", service: "mut" }[t] || "mut";
    return badge((t) + (actor.name ? " · " + actor.name : (actor.id ? " · " + actor.id : "")), k);
  }
  function trustBadge(status) {
    var k = { valid: "ok", trusted: "ok", untrusted: "warn", unknown_signer: "warn", unknown: "warn", revoked: "bad", invalid: "bad", unsigned: "mut" }[status] || "mut";
    var label = { valid: "trusted ✓", unknown_signer: "unknown signer", unsigned: "unsigned" }[status] || status;
    return badge(label, k);
  }

  function panel(title, bodyHtml, tight) {
    return '<div class="panel"><h3>' + esc(title) + '</h3><div class="body' + (tight ? " tight" : "") + '">' + bodyHtml + "</div></div>";
  }

  function setCrumbs(parts) {
    crumbs.innerHTML = parts.map(function (p, i) {
      if (i === parts.length - 1) return "<b>" + esc(p.t) + "</b>";
      return '<a href="' + p.h + '">' + esc(p.t) + "</a>";
    }).join(' <span class="muted">/</span> ');
  }
  function renderAuth() {
    if (getToken()) authbox.innerHTML = '<span class="badge ok">authenticated</span> <a href="#/logout">logout</a>';
    else authbox.innerHTML = '<a href="#/login">login</a>';
  }

  function handleError(e) {
    if (e && e.status === 401) { location.hash = "#/login"; return; }
    if (e && e.status === 403) { app.innerHTML = '<div class="err"><b>Permission denied (403).</b><br>' + esc(e.message) + '<br><span class="small">Your API token lacks the required scope or repo access.</span></div>'; return; }
    if (e && e.status === 404) { app.innerHTML = '<div class="err">Not found (404): ' + esc(e.message) + "</div>"; return; }
    app.innerHTML = '<div class="err">' + esc(e && e.message || "error") + "</div>";
  }

  // ---------------------------------------------------------------- router
  function parse() {
    var h = location.hash.replace(/^#/, "") || "/repos";
    return h.split("/").filter(Boolean); // e.g. ["repos","acme","app","sessions","cs_..."]
  }
  function go(h) { location.hash = h; }

  function route() {
    renderAuth();
    var seg = parse();
    if (seg[0] === "login") return renderLogin();
    if (seg[0] === "logout") { setToken(null); return go("#/login"); }
    if (!getToken()) return renderLogin();

    if (seg[0] === "repos" && seg.length === 1) return renderRepos();
    if (seg[0] === "repos" && seg.length >= 3) {
      var owner = seg[1], repo = seg[2], sub = seg[3];
      if (!sub) return renderRepo(owner, repo);
      if (sub === "sessions" && seg[4]) return renderSession(owner, repo, seg.slice(4).join("/"));
      if (sub === "sessions") return renderSessions(owner, repo);
      if (sub === "refs") return renderRefs(owner, repo);
      if (sub === "policy") return renderPolicy(owner, repo);
      if (sub === "identities") return renderIdentities(owner, repo);
      if (sub === "integrity") return renderIntegrity(owner, repo);
      if (sub === "audit") return renderAudit(owner, repo);
    }
    return renderRepos();
  }

  // ---------------------------------------------------------------- pages
  function renderLogin() {
    setCrumbs([{ t: "login" }]);
    app.innerHTML =
      '<div class="login">' +
      "<h1>Sign in</h1>" +
      '<p class="muted small">Enter an API token issued by <code>checkpoint-server token create</code>.</p>' +
      panel("API token",
        '<input id="tok" type="password" placeholder="ckpt_…" />' +
        '<div class="note">Dev MVP: the token is stored in browser <b>localStorage</b> on this device only. Use a scoped token; log out to clear it.</div>' +
        '<div class="row"><button class="primary" id="signin">Sign in</button></div>' +
        '<div id="loginerr"></div>') +
      "</div>";
    document.getElementById("signin").onclick = function () {
      var t = document.getElementById("tok").value.trim();
      if (!t) return;
      setToken(t);
      api("GET", "/version").then(function () { go("#/repos"); })
        .catch(function (e) { setToken(null); document.getElementById("loginerr").innerHTML = '<div class="err small">Token rejected. ' + esc(e.message) + "</div>"; });
    };
  }

  function renderRepos() {
    setCrumbs([{ t: "repos" }]);
    app.innerHTML = '<div class="loading">loading…</div>';
    Promise.all([
      api("GET", "/version").catch(function () { return {}; }),
      api("GET", "/repos")
    ]).then(function (res) {
      var ver = res[0], list = res[1].repos || [];
      serverinfo.textContent = ver.api ? "  ·  server " + ver.server_id + " · api " + ver.api : "";
      var rows = list.length ? list.map(function (r) {
        var p = r.split("/");
        return '<tr class="click" data-h="#/repos/' + esc(r) + '"><td class="mono">' + esc(r) + "</td>" +
          '<td><a href="#/repos/' + esc(r) + '/sessions">sessions</a></td>' +
          '<td><a href="#/repos/' + esc(r) + '/integrity">integrity</a></td>' +
          '<td><a href="#/repos/' + esc(r) + '/policy">policy</a></td></tr>';
      }).join("") : '<tr><td colspan="4" class="muted">No repositories. Create one via the API: <code>POST /repos</code></td></tr>';
      app.innerHTML = "<h1>Repositories</h1>" +
        panel("Hosted repos", '<table><thead><tr><th>repo</th><th></th><th></th><th></th></tr></thead><tbody>' + rows + "</tbody></table>", true);
      wireClicks();
    }).catch(handleError);
  }

  function repoNav(owner, repo, active) {
    var base = "#/repos/" + owner + "/" + repo;
    var items = [["", "overview"], ["/sessions", "sessions"], ["/refs", "refs"], ["/policy", "policy"],
      ["/identities", "identities"], ["/integrity", "integrity"], ["/audit", "audit"]];
    return '<div class="badges">' + items.map(function (i) {
      var on = i[1] === active;
      return '<a class="badge ' + (on ? "info" : "mut") + '" href="' + base + i[0] + '">' + i[1] + "</a>";
    }).join("") + "</div>";
  }

  function renderRepo(owner, repo) {
    setCrumbs([{ t: "repos", h: "#/repos" }, { t: owner + "/" + repo }]);
    app.innerHTML = '<div class="loading">loading…</div>';
    var base = "/repos/" + owner + "/" + repo;
    Promise.all([
      api("GET", base), api("GET", base + "/refs"), api("GET", base + "/objects/stats"),
      api("POST", base + "/fsck", {}), api("GET", base + "/sessions").catch(function () { return { sessions: [] }; }),
      api("GET", base + "/identities").catch(function () { return { identities: [] }; }),
      api("GET", base + "/policy").catch(function () { return { policy: null }; }),
      api("POST", base + "/verify-signatures", {}).catch(function () { return { results: [], counts: {} }; })
    ]).then(function (r) {
      var info = r[0], refs = r[1], stats = r[2], fsck = r[3], sessions = r[4].sessions || [],
        ids = r[5].identities || [], pol = r[6].policy, sigs = r[7];
      var heads = Object.keys(refs.heads || {}).map(function (b) {
        return "<tr><td class=mono>" + esc(b) + "</td><td class=mono>" + short(refs.heads[b]) + "</td></tr>"; }).join("")
        || '<tr><td colspan=2 class=muted>no branches yet</td></tr>';
      var sess = sessions.slice(0, 8).map(function (s) {
        return '<tr class="click" data-h="#/repos/' + owner + "/" + repo + "/sessions/" + esc(s.session_id) + '">' +
          "<td>" + esc((s.instruction || "").slice(0, 60)) + "</td><td>" + statusBadge(s.status) + "</td><td>" + actorBadge(s.actor) + "</td></tr>"; }).join("")
        || '<tr><td colspan=3 class=muted>no sessions</td></tr>';
      var fsckBadge = fsck.result === "healthy" ? badge("healthy ✓", "ok") : badge(fsck.result, "bad");
      var sigCounts = sigs.counts || {};
      var trusted = ids.filter(function (i) { return i.trusted && !i.revoked; }).length;
      var polBadge = pol ? badge("policy active", "ok") : badge("no policy", "mut");
      app.innerHTML = "<h1>" + esc(owner + "/" + repo) + "</h1>" + repoNav(owner, repo, "overview") +
        '<div class="grid2">' +
        '<div class="col">' +
        panel("Branches", "<table><thead><tr><th>branch</th><th>head</th></tr></thead><tbody>" + heads + "</tbody></table>", true) +
        panel("Recent sessions", "<table><tbody>" + sess + "</tbody></table>", true) +
        "</div>" +
        '<div class="col">' +
        panel("Integrity", '<div class="kv"><div>fsck</div><div>' + fsckBadge + "</div>" +
          "<div>objects</div><div>" + (stats.counts ? Object.keys(stats.counts).map(function (k) { return k + ":" + stats.counts[k]; }).join("  ") : "—") + "</div>" +
          "<div>bytes</div><div>" + (stats.bytes || 0) + "</div>" +
          "<div>corrupt</div><div>" + (fsck.corrupt ? fsck.corrupt.length : 0) + "</div>" +
          "<div>missing</div><div>" + (fsck.missing ? fsck.missing.length : 0) + "</div>" +
          "<div>dangling</div><div>" + (fsck.dangling || 0) + "</div></div>") +
        panel("Policy &amp; trust", '<div class="kv"><div>policy</div><div>' + polBadge + "</div>" +
          "<div>signatures</div><div>" + (sigCounts.valid || 0) + " valid · " + (sigCounts.untrusted || 0) + " untrusted · " + (sigCounts.invalid || 0) + " invalid</div>" +
          "<div>identities</div><div>" + ids.length + " (" + trusted + " trusted)</div></div>") +
        "</div></div>";
      wireClicks();
    }).catch(handleError);
  }

  function renderSessions(owner, repo) {
    setCrumbs([{ t: "repos", h: "#/repos" }, { t: owner + "/" + repo, h: "#/repos/" + owner + "/" + repo }, { t: "sessions" }]);
    app.innerHTML = '<div class="loading">loading…</div>';
    api("GET", "/repos/" + owner + "/" + repo + "/sessions").then(function (r) {
      var rows = (r.sessions || []).map(function (s) {
        return '<tr class="click" data-h="#/repos/' + owner + "/" + repo + "/sessions/" + esc(s.session_id) + '">' +
          "<td class=mono>" + esc(s.session_id) + "</td><td>" + esc((s.instruction || "").slice(0, 70)) + "</td>" +
          "<td>" + statusBadge(s.status) + "</td><td>" + actorBadge(s.actor) + "</td></tr>"; }).join("")
        || '<tr><td colspan=4 class=muted>no sessions</td></tr>';
      app.innerHTML = "<h1>" + esc(owner + "/" + repo) + "</h1>" + repoNav(owner, repo, "sessions") +
        panel("Sessions", "<table><thead><tr><th>session</th><th>instruction</th><th>status</th><th>actor</th></tr></thead><tbody>" + rows + "</tbody></table>", true);
      wireClicks();
    }).catch(handleError);
  }

  // ---- the main product surface -------------------------------------------
  function renderSession(owner, repo, sid) {
    var base = "/repos/" + owner + "/" + repo;
    setCrumbs([{ t: "repos", h: "#/repos" }, { t: owner + "/" + repo, h: base.replace("/repos", "#/repos") },
      { t: "sessions", h: base.replace("/repos", "#/repos") + "/sessions" }, { t: short(sid) }]);
    app.innerHTML = '<div class="loading">loading session…</div>';
    Promise.all([
      api("GET", base + "/sessions/" + sid),
      api("GET", base + "/sessions/" + sid + "/timeline").catch(function () { return { events: [] }; }),
      api("GET", base + "/sessions/" + sid + "/packet").catch(function () { return null; }),
      api("POST", base + "/verify-signatures", {}).catch(function () { return { results: [] }; }),
      api("GET", base + "/identities").catch(function () { return { identities: [] }; }),
      api("GET", base + "/policy").catch(function () { return { policy: null }; })
    ]).then(function (r) {
      var sess = r[0], timeline = r[1].events || [], packet = r[2], sigs = r[3].results || [],
        ids = r[4].identities || [], hasPolicy = !!r[5].policy;
      var acceptedSnap = (sess.result && sess.result.snapshot) || null;

      // diff (rename-aware) from packet trees
      var diffPromise = (packet && packet.base_tree && packet.current_tree)
        ? api("POST", base + "/diff", { from: packet.base_tree, to: packet.current_tree, unified: true }).catch(function () { return null; })
        : Promise.resolve(null);
      // live policy decision for "accept"
      var changed = packet ? (packet.changed_files || []).map(function (f) { return f.path; }) : [];
      var polPromise = hasPolicy
        ? api("POST", base + "/policy/check", { operation: "accept", actor_type: (sess.actor || {}).type || "human",
            branch: (sess.base || {}).branch, changed_paths: changed }).catch(function () { return null; })
        : Promise.resolve(null);

      Promise.all([diffPromise, polPromise]).then(function (rr) {
        drawSession(owner, repo, sess, timeline, packet, sigs, ids, rr[0], rr[1], acceptedSnap);
      });
    }).catch(handleError);
  }

  function drawSession(owner, repo, sess, timeline, packet, sigs, ids, diff, policy, acceptedSnap) {
    var idMap = {}; ids.forEach(function (i) { idMap[i.identity_id] = i; });
    var agent = sess.agent || {};
    var ver = lastVerification(timeline);

    // header badges
    var hdr = '<h1>' + esc(sess.instruction || sess.session_id) + "</h1>" +
      '<div class="badges">' + statusBadge(sess.status) + actorBadge(sess.actor) +
      (agent.model ? badge("model · " + agent.model, "violet") : "") +
      (agent.tool ? badge("tool · " + agent.tool, "cyan") : "") +
      signaturesBadge(sigs, acceptedSnap) + policyHeaderBadge(policy) + "</div>" +
      '<div class="muted small mono">' + esc(sess.session_id) + "</div>";

    var left = '<div class="col">' + timelinePanel(timeline) + "</div>";
    var mid = '<div class="col">' + packetPanel(packet) + diffPanel(diff) + snapshotsPanel(sess) + "</div>";
    var right = '<div class="col">' + policyPanel(policy, hasPolicyFlag(policy)) +
      signaturePanel(sigs, acceptedSnap, idMap) + verificationPanel(timeline) +
      integrityMiniPanel(owner, repo) + actionsPanel(owner, repo, sess) + "</div>";

    app.innerHTML = hdr + '<div class="grid3" style="margin-top:14px">' + left + mid + right + "</div>";
    wireClicks();
    wireSessionActions(owner, repo, sess, packet);
  }

  function lastVerification(timeline) {
    var v = null; timeline.forEach(function (e) { if (e.type === "verification_run") v = e; }); return v;
  }
  function hasPolicyFlag(p) { return p !== null && p !== undefined; }

  // ---- panels --------------------------------------------------------------
  function timelinePanel(events) {
    var glyph = { session_started: "started", autosave_created: "autosave", snapshot_created: "snapshot",
      verification_run: "verification", accepted: "ACCEPTED", rollback: "rollback", recover_invoked: "recover" };
    var li = events.length ? events.map(function (e) {
      var p = e.payload || {};
      var detail = p.instruction || p.message || p.autosave_id || p.overall || p.target || "";
      return '<li><span class="tdot ' + esc(e.type) + '"></span><div>' +
        '<div class="ttitle">' + esc(glyph[e.type] || e.type) + "</div>" +
        '<div class="tmeta">' + when(e.timestamp) + (detail ? " · " + esc(String(detail).slice(0, 60)) : "") + "</div></div></li>";
    }).join("") : '<li class="muted">no timeline events</li>';
    return panel("Timeline", '<ul class="timeline">' + li + "</ul>");
  }

  function packetPanel(packet) {
    if (!packet) return panel("Packet", '<div class="muted">No change packet for this session. (Generated on <code>accept</code> or <code>packet</code>.)</div>');
    var st = packet.stats || {};
    var risks = (packet.risks || []).map(function (r) { return badge(r, r.indexOf("secrets-detected:0") === 0 ? "mut" : "warn"); }).join(" ");
    return panel("Packet summary", '<div class="kv">' +
      "<div>recommended</div><div>" + badge(packet.recommended_next_action || "—", packet.recommended_next_action === "accept" ? "ok" : "warn") + "</div>" +
      "<div>commit msg</div><div class=mono>" + esc(packet.recommended_commit_message || "—") + "</div>" +
      "<div>files</div><div>" + (st.files_changed || (packet.changed_files || []).length) + " (+" + (st.insertions || 0) + " −" + (st.deletions || 0) + ")</div>" +
      "<div>base</div><div class=mono>" + short(packet.base_snapshot) + "</div>" +
      "<div>risks</div><div>" + (risks || "—") + "</div></div>" +
      (packet.secret_findings && packet.secret_findings.length ? '<div class="err small" style="margin-top:8px">⚠ secrets detected: ' + packet.secret_findings.length + "</div>" : ""));
  }

  function diffPanel(diff) {
    if (!diff) return panel("Diff", '<div class="muted">No diff available.</div>');
    var files = [];
    (diff.renamed || []).forEach(function (r) {
      files.push('<div class="difffile"><div class="fhead"><span class="st renamed">R</span>' +
        '<span>' + esc(r.old_path) + " → " + esc(r.new_path) + "</span>" +
        '<span class="right muted">similarity ' + pct(r.similarity) + " · " + esc(r.kind) + "</span></div></div>"); });
    (diff.modified || []).forEach(function (p) { files.push(fileRow("M", "modified", p)); });
    (diff.added || []).forEach(function (p) { files.push(fileRow("A", "added", p)); });
    (diff.deleted || []).forEach(function (p) { files.push(fileRow("D", "deleted", p)); });
    var dirs = (diff.directory_renames || []).map(function (d) {
      return badge((d.old_dir || ".") + "/ → " + (d.new_dir || ".") + "/ (" + d.count + ")", "cyan"); }).join(" ");
    var unified = diff.unified ? '<div class="difffile"><div class="fhead"><span>unified</span></div><pre>' + colorize(diff.unified) + "</pre></div>" : "";
    var st = diff.stats || {};
    var head = '<div class="muted small" style="margin-bottom:8px">' + (st.files_changed || 0) + " files · +" + (st.insertions || 0) + " −" + (st.deletions || 0) + (dirs ? "  " + dirs : "") + "</div>";
    return panel("Diff (rename-aware)", head + (files.join("") || '<div class="muted">no changes</div>') + unified);
  }
  function fileRow(letter, cls, path) {
    return '<div class="difffile"><div class="fhead"><span class="st ' + cls + '">' + letter + "</span><span>" + esc(path) + "</span></div></div>";
  }
  function colorize(text) {
    return esc(text).split("\n").map(function (l) {
      if (l.indexOf("<<<<<<<") === 0 || l.indexOf("=======") === 0 || l.indexOf(">>>>>>>") === 0) return '<span class="dl-conf">' + l + "</span>";
      if (l[0] === "+") return '<span class="dl-add">' + l + "</span>";
      if (l[0] === "-") return '<span class="dl-del">' + l + "</span>";
      if (l.indexOf("@@") === 0 || l.indexOf("rename ") === 0) return '<span class="dl-hunk">' + l + "</span>";
      return l;
    }).join("\n");
  }

  function snapshotsPanel(sess) {
    var snaps = (sess.snapshots || []).map(function (s) { return "<tr><td>snapshot</td><td class=mono>" + short(s) + "</td></tr>"; });
    var autos = (sess.autosaves || []).map(function (a) { return "<tr><td>autosave</td><td class=mono>" + esc(a) + "</td></tr>"; });
    var body = (snaps.concat(autos).join("")) || '<tr><td colspan=2 class=muted>none</td></tr>';
    return panel("Snapshots &amp; autosaves", "<table><tbody>" + body + "</tbody></table>" +
      '<div class="note" style="margin-top:8px"><b>Autosave</b> = recovery-only state. <b>Snapshot</b> = meaningful intermediate. <b>Accepted snapshot</b> = official history.</div>', true);
  }

  function policyHeaderBadge(policy) {
    if (!policy) return badge("policy n/a", "mut");
    if (policy.effect === "allow") return badge("policy allow", "ok");
    if (policy.effect === "deny") return badge("policy deny", "bad");
    return badge("policy " + policy.effect, "warn");
  }
  function policyPanel(policy) {
    if (!policy) return panel("Policy decision", '<div class="muted">No policy configured for this repo. (Operations are unrestricted.)</div>');
    var head = policy.effect === "allow" ? badge("ALLOW accept", "ok") : (policy.effect === "deny" ? badge("DENY accept", "bad") : badge(policy.effect, "warn"));
    var matched = (policy.rules_matched || []).map(function (r) { return badge(r, "info"); }).join(" ");
    var reasons = (policy.reasons || []).map(function (r) { return '<li class="reason">' + esc(r) + "</li>"; }).join("");
    var actions = (policy.required_actions || []).map(function (a) { return '<li class="action">' + esc(a) + "</li>"; }).join("");
    var ov = policy.override_available ? '<div class="note">A trusted human may override: <span class="cli">checkpoint-core accept --override --reason "…"</span></div>' : "";
    return panel("Policy decision", head +
      (matched ? '<div style="margin:8px 0">' + matched + "</div>" : "") +
      (reasons ? "<b>Reasons</b><ul>" + reasons + "</ul>" : "") +
      (actions ? "<b>Required actions</b><ul>" + actions + "</ul>" : "") + ov);
  }

  function signaturesBadge(sigs, snap) {
    var s = sigForSnap(sigs, snap);
    if (!snap) return badge("no accepted snapshot", "mut");
    if (!s) return trustBadge("unsigned");
    return trustBadge(s.status);
  }
  function sigForSnap(sigs, snap) {
    if (!snap) return null;
    var found = null; (sigs || []).forEach(function (x) { if (x.object === snap) found = x; }); return found;
  }
  function signaturePanel(sigs, snap, idMap) {
    if (!snap) return panel("Signatures &amp; trust", '<div class="muted">Session has no accepted snapshot yet.</div>');
    var s = sigForSnap(sigs, snap);
    if (!s) return panel("Signatures &amp; trust", trustBadge("unsigned") + '<div class="muted small" style="margin-top:6px">The accepted snapshot is not signed.</div>');
    var idr = idMap[s.signer] || {};
    return panel("Signatures &amp; trust", '<div class="kv">' +
      "<div>status</div><div>" + trustBadge(s.status) + "</div>" +
      "<div>verified</div><div>" + (s.ok ? badge("yes ✓", "ok") : badge("FAILED", "bad")) + "</div>" +
      "<div>signer</div><div class=mono>" + esc(s.signer || "—") + "</div>" +
      "<div>type</div><div>" + (idr.type ? actorBadge({ type: idr.type, name: idr.name }) : "—") + "</div>" +
      "<div>revoked</div><div>" + (idr.revoked ? badge("revoked", "bad") : "no") + "</div>" +
      '<div>fingerprint</div><div class="fp">' + esc((idr.fingerprint || "").slice(0, 28)) + "</div></div>");
  }

  function verificationPanel(timeline) {
    var runs = timeline.filter(function (e) { return e.type === "verification_run"; });
    if (!runs.length) return panel("Verification", '<div class="muted">No verification runs recorded.</div>');
    var last = runs[runs.length - 1].payload || {};
    var b = last.overall === "passed" ? badge("passed ✓", "ok") : (last.overall === "failed" ? badge("failed ✗", "bad") : badge(last.overall || "?", "mut"));
    return panel("Verification", '<div class="kv"><div>overall</div><div>' + b + "</div>" +
      "<div>run id</div><div class=mono>" + esc(last.run_id || "—") + "</div>" +
      "<div>runs</div><div>" + runs.length + "</div></div>" +
      '<div class="note small" style="margin-top:8px">Per-command stdout/stderr available via the API: <code>/sessions/{id}</code> verification records.</div>');
  }

  function integrityMiniPanel(owner, repo) {
    return panel("Integrity", '<div id="intg" class="muted">checking…</div>' +
      '<div class="row" style="margin-top:8px"><a class="badge info" href="#/repos/' + owner + "/" + repo + '/integrity">full report →</a></div>');
  }

  function actionsPanel(owner, repo, sess) {
    var cliBase = "checkpoint-core";
    var disabled = function (label, cli) {
      return '<div style="margin-bottom:8px"><button disabled>' + esc(label) + "</button>" +
        '<div class="cli">' + esc(cli) + "</div></div>"; };
    return panel("Review actions",
      '<div class="row" style="gap:8px;margin-bottom:10px">' +
      '<button class="ghost" id="act-policy">Policy check</button>' +
      '<button class="ghost" id="act-verify">Verify signatures</button>' +
      '<button class="ghost" id="act-fsck">fsck</button></div>' +
      "<div id=actout></div>" +
      '<div class="muted small" style="margin:8px 0">Accept/reject/rollback are performed locally by the client (the server only applies verified ref updates):</div>' +
      disabled("Accept", cliBase + ' accept -m "…"') +
      disabled("Reject", cliBase + " reject") +
      disabled("Rollback", cliBase + " rollback --hard"));
  }

  function wireSessionActions(owner, repo, sess, packet) {
    var base = "/repos/" + owner + "/" + repo;
    // integrity mini
    api("POST", base + "/fsck", {}).then(function (f) {
      var el = document.getElementById("intg");
      if (el) el.innerHTML = (f.result === "healthy" ? badge("healthy ✓", "ok") : badge(f.result, "bad")) +
        ' <span class="small muted">' + (f.objects_scanned || 0) + " objects</span>";
    }).catch(function () {});
    var out = function () { return document.getElementById("actout"); };
    var pc = document.getElementById("act-policy");
    if (pc) pc.onclick = function () {
      var changed = packet ? (packet.changed_files || []).map(function (f) { return f.path; }) : [];
      api("POST", base + "/policy/check", { operation: "accept", actor_type: (sess.actor || {}).type || "human",
        branch: (sess.base || {}).branch, changed_paths: changed })
        .then(function (d) { out().innerHTML = '<div class="note small">' + (d.effect === "allow" ? badge("ALLOW", "ok") : badge("DENY", "bad")) +
          " " + esc((d.reasons || []).join("; ") || "ok") + "</div>"; }).catch(function (e) { out().innerHTML = '<div class="err small">' + esc(e.message) + "</div>"; });
    };
    var vf = document.getElementById("act-verify");
    if (vf) vf.onclick = function () {
      api("POST", base + "/verify-signatures", {}).then(function (r) {
        out().innerHTML = '<div class="note small">' + (r.ok ? badge("all valid", "ok") : badge("invalid present", "bad")) + " " + esc(JSON.stringify(r.counts || {})) + "</div>"; })
        .catch(function (e) { out().innerHTML = '<div class="err small">' + esc(e.message) + "</div>"; });
    };
    var fk = document.getElementById("act-fsck");
    if (fk) fk.onclick = function () {
      api("POST", base + "/fsck", {}).then(function (f) {
        out().innerHTML = '<div class="note small">' + (f.result === "healthy" ? badge("healthy", "ok") : badge(f.result, "bad")) +
          " · " + (f.objects_scanned || 0) + " objects · " + (f.dangling || 0) + " dangling</div>"; })
        .catch(function (e) { out().innerHTML = '<div class="err small">' + esc(e.message) + "</div>"; });
    };
  }

  // ---- simple repo subpages ------------------------------------------------
  function renderRefs(owner, repo) {
    setCrumbs([{ t: "repos", h: "#/repos" }, { t: owner + "/" + repo, h: "#/repos/" + owner + "/" + repo }, { t: "refs" }]);
    app.innerHTML = '<div class="loading">loading…</div>';
    api("GET", "/repos/" + owner + "/" + repo + "/refs").then(function (r) {
      var heads = Object.keys(r.heads || {}).map(function (b) { return "<tr><td class=mono>refs/heads/" + esc(b) + "</td><td class=mono>" + short(r.heads[b]) + "</td></tr>"; }).join("");
      var tags = Object.keys(r.tags || {}).map(function (t) { return "<tr><td class=mono>refs/tags/" + esc(t) + "</td><td class=mono>" + short(r.tags[t]) + "</td></tr>"; }).join("");
      app.innerHTML = "<h1>" + esc(owner + "/" + repo) + "</h1>" + repoNav(owner, repo, "refs") +
        panel("Refs", "<table><thead><tr><th>ref</th><th>target</th></tr></thead><tbody>" + (heads + tags || '<tr><td colspan=2 class=muted>none</td></tr>') + "</tbody></table>", true);
    }).catch(handleError);
  }

  function renderPolicy(owner, repo) {
    setCrumbs([{ t: "repos", h: "#/repos" }, { t: owner + "/" + repo, h: "#/repos/" + owner + "/" + repo }, { t: "policy" }]);
    app.innerHTML = '<div class="loading">loading…</div>';
    Promise.all([api("GET", "/repos/" + owner + "/" + repo + "/policy"),
      api("GET", "/repos/" + owner + "/" + repo + "/policy/decisions").catch(function () { return { decisions: [] }; })]).then(function (r) {
      var pol = r[0].policy, decs = r[1].decisions || [];
      var polBody = pol ? "<pre class=mono style='white-space:pre-wrap'>" + esc(JSON.stringify(pol, null, 2)) + "</pre>" : '<div class="muted">No policy configured (enforcement disabled).</div>';
      var rows = decs.slice(-40).reverse().map(function (d) {
        return "<tr><td>" + esc(d.operation) + "</td><td>" + (d.effect === "allow" ? badge("allow", "ok") : badge(d.effect, d.effect === "deny" ? "bad" : "warn")) +
          "</td><td>" + esc((d.rules_matched || []).join(", ")) + "</td><td class=mono>" + short(d.decision_id) + (d.override_used ? " " + badge("override", "violet") : "") + "</td></tr>"; }).join("")
        || '<tr><td colspan=4 class=muted>no decisions recorded</td></tr>';
      app.innerHTML = "<h1>" + esc(owner + "/" + repo) + "</h1>" + repoNav(owner, repo, "policy") +
        panel("Active policy", polBody) +
        panel("Policy decisions (audit)", "<table><thead><tr><th>op</th><th>effect</th><th>matched rules</th><th>id</th></tr></thead><tbody>" + rows + "</tbody></table>", true);
    }).catch(handleError);
  }

  function renderIdentities(owner, repo) {
    setCrumbs([{ t: "repos", h: "#/repos" }, { t: owner + "/" + repo, h: "#/repos/" + owner + "/" + repo }, { t: "identities" }]);
    app.innerHTML = '<div class="loading">loading…</div>';
    api("GET", "/repos/" + owner + "/" + repo + "/identities").then(function (r) {
      var rows = (r.identities || []).map(function (i) {
        var t = i.revoked ? badge("revoked", "bad") : (i.trusted ? badge("trusted", "ok") : badge("untrusted", "warn"));
        return "<tr><td class=mono>" + esc(i.identity_id) + "</td><td>" + actorBadge({ type: i.type, name: i.name }) +
          "</td><td>" + t + '</td><td class="fp">' + esc((i.fingerprint || "").slice(0, 30)) + "</td></tr>"; }).join("")
        || '<tr><td colspan=4 class=muted>no identities</td></tr>';
      app.innerHTML = "<h1>" + esc(owner + "/" + repo) + "</h1>" + repoNav(owner, repo, "identities") +
        panel("Identities", "<table><thead><tr><th>identity</th><th>type</th><th>trust</th><th>fingerprint</th></tr></thead><tbody>" + rows + "</tbody></table>" +
          '<div class="note" style="margin-top:8px">Public keys only — Checkpoint never exposes private key material.</div>', true);
    }).catch(handleError);
  }

  function renderIntegrity(owner, repo) {
    setCrumbs([{ t: "repos", h: "#/repos" }, { t: owner + "/" + repo, h: "#/repos/" + owner + "/" + repo }, { t: "integrity" }]);
    app.innerHTML = '<div class="loading">loading…</div>';
    var base = "/repos/" + owner + "/" + repo;
    Promise.all([api("POST", base + "/fsck", {}), api("POST", base + "/gc", { dry_run: true }),
      api("GET", base + "/objects/stats"), api("POST", base + "/verify-signatures", {})]).then(function (r) {
      var f = r[0], gc = r[1], stats = r[2], sigs = r[3];
      var fb = f.result === "healthy" ? badge("healthy ✓", "ok") : badge(f.result, "bad");
      app.innerHTML = "<h1>" + esc(owner + "/" + repo) + "</h1>" + repoNav(owner, repo, "integrity") +
        '<div class="grid2"><div class="col">' +
        panel("fsck", '<div class="kv"><div>result</div><div>' + fb + "</div>" +
          "<div>objects</div><div>" + (f.objects_scanned || 0) + "</div>" +
          "<div>reachable</div><div>" + (f.reachable || 0) + "</div>" +
          "<div>dangling</div><div>" + (f.dangling || 0) + "</div>" +
          "<div>corrupt</div><div>" + ((f.corrupt || []).length) + "</div>" +
          "<div>missing</div><div>" + ((f.missing || []).length) + "</div></div>" +
          ((f.errors || []).length ? '<div class="err small" style="margin-top:8px">' + esc(f.errors.slice(0, 8).join("\n")) + "</div>" : "")) +
        panel("Signatures", '<div class="kv"><div>counts</div><div>' + esc(JSON.stringify(sigs.counts || {})) + "</div>" +
          "<div>all valid</div><div>" + (sigs.ok ? badge("yes", "ok") : badge("no", "bad")) + "</div></div>") +
        '</div><div class="col">' +
        panel("Object store", '<div class="kv"><div>by type</div><div>' + (stats.counts ? Object.keys(stats.counts).map(function (k) { return k + ": " + stats.counts[k]; }).join("<br>") : "—") + "</div>" +
          "<div>bytes</div><div>" + (stats.bytes || 0) + "</div></div>") +
        panel("GC (dry-run)", '<div class="kv"><div>candidates</div><div>' + ((gc.candidates || []).length) + "</div>" +
          "<div>reachable</div><div>" + (gc.reachable || 0) + "</div>" +
          "<div>bytes reclaimable</div><div>" + (gc.bytes_reclaimed || 0) + "</div></div>") +
        "</div></div>";
    }).catch(handleError);
  }

  function renderAudit(owner, repo) {
    setCrumbs([{ t: "repos", h: "#/repos" }, { t: owner + "/" + repo, h: "#/repos/" + owner + "/" + repo }, { t: "audit" }]);
    app.innerHTML = '<div class="loading">loading…</div>';
    api("GET", "/repos/" + owner + "/" + repo + "/audit").then(function (r) {
      var rows = (r.audit || []).slice(-100).reverse().map(function (e) {
        return "<tr><td class=mono>" + when(e.timestamp) + "</td><td>" + esc(e.operation || "") + "</td><td>" + esc(e.result || "") + "</td><td class=mono>" + esc(e.ref || e.receipt || "") + "</td></tr>"; }).join("")
        || '<tr><td colspan=4 class=muted>no audit events</td></tr>';
      app.innerHTML = "<h1>" + esc(owner + "/" + repo) + "</h1>" + repoNav(owner, repo, "audit") +
        panel("Audit log", "<table><thead><tr><th>when</th><th>operation</th><th>result</th><th>ref/receipt</th></tr></thead><tbody>" + rows + "</tbody></table>", true);
    }).catch(handleError);
  }

  // ---------------------------------------------------------------- wiring
  function wireClicks() {
    Array.prototype.forEach.call(document.querySelectorAll(".click"), function (el) {
      el.onclick = function () { var h = el.getAttribute("data-h"); if (h) go(h); };
    });
  }

  window.addEventListener("hashchange", route);
  window.addEventListener("DOMContentLoaded", route);
  if (document.readyState !== "loading") route();
})();
