/* JellyHome — réglages. Les commandes root passent par le Homebrew Channel ;
 * la connexion Jellyfin se fait ici, en Quick Connect, sans saisir de mot de passe. */
(function () {
  "use strict";

  var APP_ID = "com.smeagolworms4.jellyhome";
  var ROOT = "/media/developer/apps/usr/palm/applications/" + APP_ID + "/root";
  var CTL = ROOT + "/jellyhomectl.sh";
  var FEED = "python3 " + ROOT + "/jellyfeed.py";
  var VERSION = "0.6.2";

  // Valeurs proposées par les sélecteurs (◀ ▶ ou OK pour faire défiler)
  var CHOICES = {
    topSource: ["latest", "mix", "resume", "nextUp", "favorites", "random", "lg"],
    heroSource: ["resume", "mix", "nextUp", "latest", "favorites", "random", "lg"],
    underRow: ["lg", "none", "mix", "resume", "nextUp", "latest", "favorites", "random"],
    // Rangées : masquée, ou affichée avec les images de la série / de l'épisode
    resume: ["series", "episode", "off"],
    nextUp: ["series", "episode", "off"],
    latest: ["series", "episode", "off"]
  };
  var ROWS = ["resume", "nextUp", "latest"];

  // ------------------------------------------------------------- textes

  var I18N = {
    fr: {
      tagline: "Ton Jellyfin sur l'accueil de la TV", home: "Accueil", feeder: "Service Jellyfin",
      server: "Serveur", account: "Compte", content: "Contenu", serverTitle: "Serveur Jellyfin",
      discover: "Rechercher", connect: "Se connecter avec Quick Connect", logout: "Déconnecter",
      onHome: "Sur l'accueil", topSource: "Zone du haut", topLgRow: "Son contenu LG en rangée en dessous", heroSource: "Bandeau à côté des récents", underRow: "Rangée sous ce bandeau",
      rowResume: "Reprendre", rowNextUp: "À suivre", rowLatest: "Derniers ajouts", progress: "Barre de progression",
      hideAds: "Masquer les pubs LG", adTrailers: "Bandes-annonces dans la zone du haut", apply: "Appliquer à l'accueil", refresh: "Actualiser",
      patchOff: "Désactiver le patch", patchOn: "Activer le patch", cancel: "Annuler",
      qcStep1: "Sur ton téléphone, ouvre Jellyfin (déjà connecté) :",
      qcStep2: "Profil → Quick Connect, puis saisis le code", qcWait: "En attente de validation…",
      qcOk: "Validé, connexion…",
      c_mix: "En cours + récents", c_resume: "Reprendre", c_nextUp: "À suivre", c_latest: "Derniers ajouts",
      c_favorites: "Favoris", c_random: "À découvrir", c_lg: "LG d'origine", c_series: "Images série", c_episode: "Images épisode", c_off: "Masquée", c_none: "Aucune",
      s_patched: "patché", s_failsafe: "coupé (sécurité)", s_waiting: "en attente", s_stock: "d'origine",
      s_on: "actif", s_off: "arrêté", s_notConnected: "non connecté", s_connected: "connecté",
      counts: "{r} en cours · {l} récents",
      m_needServer: "Indique d'abord l'adresse du serveur.",
      m_qcDisabled: "Quick Connect est désactivé sur ce serveur (Tableau de bord → Général).",
      m_connected: "Connecté. Appuie sur « Appliquer à l'accueil ».",
      m_qcFail: "Quick Connect : {e}. Relance la connexion.",
      m_loggedOut: "Déconnecté. Retire aussi « JellyHome » dans Jellyfin → Tableau de bord → Appareils.",
      m_searching: "Recherche des serveurs…", m_noServer: "Aucun serveur trouvé : saisis l'adresse à la main.",
      m_found: "Serveur « {n} » trouvé.", m_foundMany: "{c} serveurs trouvés, « {n} » retenu.",
      m_applying: "Application… l'accueil redémarre.", m_refreshing: "Actualisation…",
      m_disabling: "Désactivation… l'accueil redémarre.", m_enabling: "Activation… l'accueil redémarre.",
      m_installing: "Installation… l'accueil redémarre.", m_changed: "Modifié : « Appliquer à l'accueil » pour le voir.",
      m_noHbc: "Le Homebrew Channel ne répond pas ({e}). La TV doit être rootée.", m_error: "Erreur : {e}"
    },
    en: {
      tagline: "Your Jellyfin on the TV home screen", home: "Home screen", feeder: "Jellyfin service",
      server: "Server", account: "Account", content: "Content", serverTitle: "Jellyfin server",
      discover: "Search", connect: "Sign in with Quick Connect", logout: "Sign out",
      onHome: "On the home screen", topSource: "Top area", topLgRow: "Move its LG content to a row below", heroSource: "Banner next to recents", underRow: "Row under this banner",
      rowResume: "Continue watching", rowNextUp: "Next up", rowLatest: "Recently added", progress: "Progress bar",
      hideAds: "Hide LG ads", adTrailers: "Trailers in the top area", apply: "Apply to home screen", refresh: "Refresh",
      patchOff: "Disable patch", patchOn: "Enable patch", cancel: "Cancel",
      qcStep1: "On your phone, open Jellyfin (signed in):",
      qcStep2: "Profile → Quick Connect, then enter the code", qcWait: "Waiting for approval…",
      qcOk: "Approved, signing in…",
      c_mix: "In progress + recent", c_resume: "Continue watching", c_nextUp: "Next up", c_latest: "Recently added",
      c_favorites: "Favorites", c_random: "Discover", c_lg: "LG original", c_series: "Series images", c_episode: "Episode images", c_off: "Hidden", c_none: "None",
      s_patched: "patched", s_failsafe: "off (safety)", s_waiting: "pending", s_stock: "stock",
      s_on: "running", s_off: "stopped", s_notConnected: "not signed in", s_connected: "signed in",
      counts: "{r} in progress · {l} recent",
      m_needServer: "Enter the server address first.",
      m_qcDisabled: "Quick Connect is disabled on this server (Dashboard → General).",
      m_connected: "Signed in. Press “Apply to home screen”.",
      m_qcFail: "Quick Connect: {e}. Try again.",
      m_loggedOut: "Signed out. Also remove “JellyHome” in Jellyfin → Dashboard → Devices.",
      m_searching: "Searching for servers…", m_noServer: "No server found: type the address.",
      m_found: "Found server “{n}”.", m_foundMany: "{c} servers found, using “{n}”.",
      m_applying: "Applying… the home screen restarts.", m_refreshing: "Refreshing…",
      m_disabling: "Disabling… the home screen restarts.", m_enabling: "Enabling… the home screen restarts.",
      m_installing: "Installing… the home screen restarts.", m_changed: "Changed: “Apply to home screen” to see it.",
      m_noHbc: "Homebrew Channel is not responding ({e}). The TV must be rooted.", m_error: "Error: {e}"
    },
    de: {
      tagline: "Dein Jellyfin auf dem Startbildschirm", home: "Startbildschirm", feeder: "Jellyfin-Dienst",
      server: "Server", account: "Konto", content: "Inhalt", serverTitle: "Jellyfin-Server",
      discover: "Suchen", connect: "Mit Quick Connect anmelden", logout: "Abmelden",
      onHome: "Auf dem Startbildschirm", topSource: "Oberer Bereich", topLgRow: "LG-Inhalt als Reihe darunter", heroSource: "Banner neben Zuletzt", underRow: "Reihe darunter",
      rowResume: "Weiterschauen", rowNextUp: "Als Nächstes", rowLatest: "Neu hinzugefügt", progress: "Fortschrittsbalken",
      hideAds: "LG-Werbung ausblenden", adTrailers: "Trailer im oberen Bereich", apply: "Übernehmen", refresh: "Aktualisieren",
      patchOff: "Patch deaktivieren", patchOn: "Patch aktivieren", cancel: "Abbrechen",
      qcStep1: "Öffne Jellyfin auf deinem Handy (angemeldet):",
      qcStep2: "Profil → Quick Connect, dann den Code eingeben", qcWait: "Warte auf Bestätigung…",
      qcOk: "Bestätigt, melde an…",
      c_mix: "Laufend + neu", c_resume: "Weiterschauen", c_nextUp: "Als Nächstes", c_latest: "Neu hinzugefügt",
      c_favorites: "Favoriten", c_random: "Entdecken", c_lg: "LG-Original", c_series: "Serienbilder", c_episode: "Episodenbilder", c_off: "Ausgeblendet", c_none: "Keine",
      s_patched: "gepatcht", s_failsafe: "aus (Sicherheit)", s_waiting: "ausstehend", s_stock: "original",
      s_on: "aktiv", s_off: "gestoppt", s_notConnected: "nicht angemeldet", s_connected: "angemeldet",
      counts: "{r} laufend · {l} neu",
      m_needServer: "Gib zuerst die Serveradresse ein.",
      m_qcDisabled: "Quick Connect ist auf diesem Server deaktiviert (Dashboard → Allgemein).",
      m_connected: "Angemeldet. Drücke „Übernehmen“.",
      m_qcFail: "Quick Connect: {e}. Bitte erneut versuchen.",
      m_loggedOut: "Abgemeldet. Entferne „JellyHome“ auch unter Jellyfin → Dashboard → Geräte.",
      m_searching: "Suche Server…", m_noServer: "Kein Server gefunden: Adresse eingeben.",
      m_found: "Server „{n}“ gefunden.", m_foundMany: "{c} Server gefunden, nutze „{n}“.",
      m_applying: "Wird übernommen… Startbildschirm startet neu.", m_refreshing: "Aktualisiere…",
      m_disabling: "Deaktiviere… Startbildschirm startet neu.", m_enabling: "Aktiviere… Startbildschirm startet neu.",
      m_installing: "Installiere… Startbildschirm startet neu.", m_changed: "Geändert: „Übernehmen“ zum Anzeigen.",
      m_noHbc: "Homebrew Channel antwortet nicht ({e}). Der TV muss gerootet sein.", m_error: "Fehler: {e}"
    },
    es: {
      tagline: "Tu Jellyfin en la pantalla de inicio", home: "Inicio", feeder: "Servicio Jellyfin",
      server: "Servidor", account: "Cuenta", content: "Contenido", serverTitle: "Servidor Jellyfin",
      discover: "Buscar", connect: "Conectar con Quick Connect", logout: "Desconectar",
      onHome: "En el inicio", topSource: "Zona superior", topLgRow: "Su contenido LG en una fila debajo", heroSource: "Banner junto a recientes", underRow: "Fila bajo este banner",
      rowResume: "Seguir viendo", rowNextUp: "A continuación", rowLatest: "Añadido recientemente", progress: "Barra de progreso",
      hideAds: "Ocultar anuncios LG", adTrailers: "Tráileres en la zona superior", apply: "Aplicar al inicio", refresh: "Actualizar",
      patchOff: "Desactivar parche", patchOn: "Activar parche", cancel: "Cancelar",
      qcStep1: "En tu móvil, abre Jellyfin (con sesión iniciada):",
      qcStep2: "Perfil → Quick Connect, e introduce el código", qcWait: "Esperando validación…",
      qcOk: "Validado, conectando…",
      c_mix: "En curso + recientes", c_resume: "Seguir viendo", c_nextUp: "A continuación", c_latest: "Añadido recientemente",
      c_favorites: "Favoritos", c_random: "Descubrir", c_lg: "Original de LG", c_series: "Imágenes serie", c_episode: "Imágenes episodio", c_off: "Oculta", c_none: "Ninguna",
      s_patched: "parcheado", s_failsafe: "cortado (seguridad)", s_waiting: "pendiente", s_stock: "original",
      s_on: "activo", s_off: "detenido", s_notConnected: "sin conectar", s_connected: "conectado",
      counts: "{r} en curso · {l} recientes",
      m_needServer: "Indica primero la dirección del servidor.",
      m_qcDisabled: "Quick Connect está desactivado en este servidor (Panel → General).",
      m_connected: "Conectado. Pulsa «Aplicar al inicio».",
      m_qcFail: "Quick Connect: {e}. Vuelve a intentarlo.",
      m_loggedOut: "Desconectado. Quita también «JellyHome» en Jellyfin → Panel → Dispositivos.",
      m_searching: "Buscando servidores…", m_noServer: "Ningún servidor encontrado: escribe la dirección.",
      m_found: "Servidor «{n}» encontrado.", m_foundMany: "{c} servidores encontrados, uso «{n}».",
      m_applying: "Aplicando… el inicio se reinicia.", m_refreshing: "Actualizando…",
      m_disabling: "Desactivando… el inicio se reinicia.", m_enabling: "Activando… el inicio se reinicia.",
      m_installing: "Instalando… el inicio se reinicia.", m_changed: "Cambiado: «Aplicar al inicio» para verlo.",
      m_noHbc: "Homebrew Channel no responde ({e}). La TV debe estar rooteada.", m_error: "Error: {e}"
    },
    it: {
      tagline: "Il tuo Jellyfin nella schermata Home", home: "Home", feeder: "Servizio Jellyfin",
      server: "Server", account: "Account", content: "Contenuti", serverTitle: "Server Jellyfin",
      discover: "Cerca", connect: "Accedi con Quick Connect", logout: "Esci",
      onHome: "Nella Home", topSource: "Zona in alto", topLgRow: "Il suo contenuto LG in una riga sotto", heroSource: "Banner accanto ai recenti", underRow: "Riga sotto questo banner",
      rowResume: "Continua a guardare", rowNextUp: "Prossimi", rowLatest: "Aggiunti di recente", progress: "Barra di avanzamento",
      hideAds: "Nascondi pubblicità LG", adTrailers: "Trailer nella zona in alto", apply: "Applica alla Home", refresh: "Aggiorna",
      patchOff: "Disattiva patch", patchOn: "Attiva patch", cancel: "Annulla",
      qcStep1: "Sul telefono, apri Jellyfin (con accesso):",
      qcStep2: "Profilo → Quick Connect, poi inserisci il codice", qcWait: "In attesa di conferma…",
      qcOk: "Confermato, accesso…",
      c_mix: "In corso + recenti", c_resume: "Continua a guardare", c_nextUp: "Prossimi", c_latest: "Aggiunti di recente",
      c_favorites: "Preferiti", c_random: "Scopri", c_lg: "Originale LG", c_series: "Immagini serie", c_episode: "Immagini episodio", c_off: "Nascosta", c_none: "Nessuna",
      s_patched: "patchata", s_failsafe: "spenta (sicurezza)", s_waiting: "in attesa", s_stock: "originale",
      s_on: "attivo", s_off: "fermo", s_notConnected: "non connesso", s_connected: "connesso",
      counts: "{r} in corso · {l} recenti",
      m_needServer: "Inserisci prima l'indirizzo del server.",
      m_qcDisabled: "Quick Connect è disattivato su questo server (Dashboard → Generale).",
      m_connected: "Connesso. Premi «Applica alla Home».",
      m_qcFail: "Quick Connect: {e}. Riprova.",
      m_loggedOut: "Disconnesso. Rimuovi anche «JellyHome» in Jellyfin → Dashboard → Dispositivi.",
      m_searching: "Ricerca server…", m_noServer: "Nessun server trovato: inserisci l'indirizzo.",
      m_found: "Server «{n}» trovato.", m_foundMany: "{c} server trovati, uso «{n}».",
      m_applying: "Applicazione… la Home si riavvia.", m_refreshing: "Aggiornamento…",
      m_disabling: "Disattivazione… la Home si riavvia.", m_enabling: "Attivazione… la Home si riavvia.",
      m_installing: "Installazione… la Home si riavvia.", m_changed: "Modificato: «Applica alla Home» per vederlo.",
      m_noHbc: "Homebrew Channel non risponde ({e}). La TV deve essere rootata.", m_error: "Errore: {e}"
    }
  };

  var LANG = (navigator.language || "fr").slice(0, 2).toLowerCase();
  var TXT = I18N[LANG] || I18N.en;

  function t(key, vars) {
    var s = TXT[key] || I18N.fr[key] || key;
    Object.keys(vars || {}).forEach(function (k) { s = s.replace("{" + k + "}", vars[k]); });
    return s;
  }

  function translatePage() {
    document.documentElement.lang = LANG;
    Array.prototype.forEach.call(document.querySelectorAll("[data-i18n]"), function (el) {
      el.textContent = t(el.dataset.i18n);
    });
    $("qcWait").textContent = t("qcWait");
  }

  var $ = function (id) { return document.getElementById(id); };
  var state = { status: null, busy: false, qc: null };

  // ------------------------------------------------------------- luna

  function luna(uri, params) {
    return new Promise(function (resolve, reject) {
      if (typeof PalmServiceBridge === "undefined") {
        reject(new Error("hors TV"));
        return;
      }
      var bridge = new PalmServiceBridge();
      bridge.onservicecallback = function (msg) {
        var res;
        try { res = JSON.parse(msg); } catch (e) { res = { returnValue: false, errorText: msg }; }
        if (res.returnValue === false) reject(new Error(res.errorText || "luna"));
        else resolve(res);
      };
      bridge.call(uri, JSON.stringify(params || {}));
    });
  }

  /** Commande root via le Homebrew Channel ; renvoie stdout. */
  function exec(command) {
    return luna("luna://org.webosbrew.hbchannel.service/exec", { command: command })
      .then(function (r) { return r.stdoutString || ""; });
  }

  function execJson(command) {
    return exec(command).then(function (out) {
      return JSON.parse(out.trim().split("\n").pop());
    });
  }

  function setConfig(patch) {
    var b64 = btoa(unescape(encodeURIComponent(JSON.stringify(patch))));
    return exec(FEED + " set-config " + b64);
  }

  // ---------------------------------------------------------- Jellyfin

  function deviceId() {
    var id;
    try { id = localStorage.getItem("jh.deviceId"); } catch (e) { /* stockage indisponible */ }
    if (!id) {
      id = "jellyhome-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
      try { localStorage.setItem("jh.deviceId", id); } catch (e) { /* idem */ }
    }
    return id;
  }

  function authHeader() {
    return 'MediaBrowser Client="JellyHome", Device="LG webOS TV", DeviceId="' +
      deviceId() + '", Version="' + VERSION + '"';
  }

  function jf(server, path, opts) {
    opts = opts || {};
    return fetch(server + path, {
      method: opts.method || "GET",
      headers: { "Authorization": authHeader(), "Content-Type": "application/json", "Accept": "application/json" },
      body: opts.body ? JSON.stringify(opts.body) : undefined
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status + " " + path);
      return r.json();
    });
  }

  function serverUrl() {
    var v = $("server").value.trim().replace(/\/+$/, "");
    if (v && !/^https?:\/\//.test(v)) v = "http://" + v;
    if (v && !/:\d+$/.test(v) && !/^https:/.test(v)) v += ":8096";
    return v;
  }

  function startQuickConnect() {
    var server = serverUrl();
    if (!server) { say(t("m_needServer")); return; }
    say("");
    jf(server, "/QuickConnect/Enabled").then(function (enabled) {
      if (!enabled) throw new Error(t("m_qcDisabled"));
      return jf(server, "/QuickConnect/Initiate", { method: "POST" });
    }).then(function (qc) {
      state.qc = { server: server, secret: qc.Secret };
      $("qcCode").textContent = qc.Code;
      var url = server + "/web/#/quickconnect";
      $("qcUrl").textContent = url;
      var qr = qrcode(0, "M");
      qr.addData(url);
      qr.make();
      $("qr").innerHTML = qr.createSvgTag({ margin: 0, scalable: true });
      $("qcWait").textContent = t("qcWait");
      openModal();
      pollQuickConnect();
    }).catch(function (e) { say(e.message); });
  }

  function pollQuickConnect() {
    var qc = state.qc;
    if (!qc) return;
    jf(qc.server, "/QuickConnect/Connect?Secret=" + encodeURIComponent(qc.secret)).then(function (r) {
      if (state.qc !== qc) return;
      if (!r.Authenticated) { qc.timer = setTimeout(pollQuickConnect, 2500); return; }
      $("qcWait").textContent = t("qcOk");
      return jf(qc.server, "/Users/AuthenticateWithQuickConnect", { method: "POST", body: { Secret: qc.secret } })
        .then(function (auth) {
          return setConfig({
            server: qc.server, token: auth.AccessToken, userId: auth.User.Id,
            userName: auth.User.Name, deviceId: deviceId(), lang: LANG
          });
        })
        .then(function () { closeModal(); say(t("m_connected")); focus($("btnApply")); return refresh(); });
    }).catch(function (e) {
      if (state.qc !== qc) return;
      // Code expiré : le serveur l'oublie au bout de quelques minutes
      closeModal();
      say(t("m_qcFail", { e: e.message }));
    });
  }

  function logout() {
    setConfig({ token: null, userId: null, userName: null }).then(function () {
      say(t("m_loggedOut"));
      return refresh();
    }).catch(function (e) { say(e.message); });
  }

  function discover() {
    say(t("m_searching"));
    exec(FEED + " discover").then(function (out) {
      var list = JSON.parse(out.trim() || "[]");
      if (!list.length) { say(t("m_noServer")); return; }
      $("server").value = list[0].address;
      say(list.length > 1 ? t("m_foundMany", { c: list.length, n: list[0].name }) : t("m_found", { n: list[0].name }));
    }).catch(function (e) { say(e.message); });
  }

  // ------------------------------------------------------------- état

  function show(st) {
    state.status = st;
    var j = st.jellyfin || {};
    setState("stHome", st.homePatched ? t("s_patched") : st.failsafe ? t("s_failsafe") : st.mounted ? t("s_waiting") : t("s_stock"),
      st.homePatched ? "ok" : st.failsafe ? "bad" : "warn");
    setState("stFeed", st.feeder ? t("s_on") : t("s_off"), st.feeder ? "ok" : "warn");
    setState("stServer", j.server || "—", j.server ? "" : "warn");
    setState("stUser", j.hasToken ? (j.userName || t("s_connected")) : t("s_notConnected"), j.hasToken ? "ok" : "warn");
    var c = j.counts || {};
    var r = c.resume != null ? c.resume : c.mix, l = c.latest != null ? c.latest : "–";
    setState("stCounts", j.error ? j.error : j.counts ? t("counts", { r: r != null ? r : "–", l: l }) : "—",
      j.error ? "bad" : "");
    if (j.server && !$("server").value) $("server").value = j.server;
    state.options = j.options || {};
    renderOptions();
    $("btnPatch").textContent = st.mounted ? t("patchOff") : t("patchOn");
    $("btnLogout").style.display = j.hasToken ? "" : "none";
  }

  /** Valeur affichée d'une option (les rangées combinent activation + images). */
  function optionValue(o, k) {
    if (ROWS.indexOf(k) >= 0) return o[k] ? ((o.episodeImages || {})[k] || "series") : "off";
    return o[k];
  }

  function renderOptions() {
    var o = state.options || {};
    Array.prototype.forEach.call(document.querySelectorAll(".toggle"), function (b) {
      var k = b.dataset.opt;
      if (CHOICES[k]) b.querySelector("b").textContent = t("c_" + optionValue(o, k));
      else b.classList.toggle("on", !!o[k]);
    });
  }

  function setState(id, text, cls) {
    var el = $(id);
    el.textContent = text;
    el.className = cls || "";
  }

  function say(text) { $("msg").textContent = text || ""; }

  function run(command, label) {
    if (state.busy) return Promise.resolve();
    state.busy = true;
    if (label) say(label);
    return execJson(command).then(function (st) { show(st); if (label) say(""); })
      .catch(function (e) { say(t("m_error", { e: e.message })); })
      .then(function () { state.busy = false; });
  }

  function refresh() { return run(CTL + " refresh"); }

  /** Interrupteur, ou sélecteur (dir = ±1). Le service régénère les règles dès
   * que config.json change ; « Appliquer » relance l'accueil qui garde ses rangées en cache. */
  function changeOption(btn, dir) {
    var k = btn.dataset.opt, o = state.options || {}, patch = {};
    if (CHOICES[k]) {
      var list = CHOICES[k], i = list.indexOf(optionValue(o, k));
      var v = list[(i + (dir || 1) + list.length) % list.length];
      if (ROWS.indexOf(k) >= 0) {
        patch[k] = v !== "off";
        if (v !== "off") {
          patch.episodeImages = {};
          patch.episodeImages[k] = v;
          o.episodeImages = o.episodeImages || {};
          o.episodeImages[k] = v;
        }
      } else {
        patch[k] = v;
      }
    } else {
      patch[k] = !o[k];
    }
    o[k] = patch[k];
    state.options = o;
    renderOptions();
    say(t("m_changed"));
    setConfig({ options: patch, lang: LANG }).catch(function (e) { say(e.message); });
  }

  function togglePatch() {
    var on = state.status && state.status.mounted;
    run(CTL + (on ? " stop" : " start"), on ? t("m_disabling") : t("m_enabling"));
  }

  // ------------------------------------------------- télécommande

  var focusables = function () {
    var scope = $("qc").hidden ? document.querySelector(".layout") : $("qc");
    return Array.prototype.filter.call(scope.querySelectorAll(".focusable"),
      function (el) { return el.offsetParent !== null && !el.disabled; });
  };
  var current = null;

  function focus(el) {
    if (current) current.classList.remove("focus");
    current = el;
    if (!el) return;
    el.classList.add("focus");
    if (el.tagName === "INPUT") el.focus(); else if (document.activeElement) document.activeElement.blur();
    // Le panneau défile : garder l'élément focalisé visible
    if (el.scrollIntoView) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  /** Voisin le plus proche dans la direction (géométrie des éléments). */
  function move(dx, dy) {
    var list = focusables();
    if (!current || list.indexOf(current) < 0) { focus(list[0]); return; }
    var a = current.getBoundingClientRect();
    var ax = a.left + a.width / 2, ay = a.top + a.height / 2, best = null, bestScore = Infinity;
    list.forEach(function (el) {
      if (el === current) return;
      var b = el.getBoundingClientRect();
      var ddx = b.left + b.width / 2 - ax, ddy = b.top + b.height / 2 - ay;
      if (dx && (Math.sign(ddx) !== dx || Math.abs(ddx) < 10)) return;
      if (dy && (Math.sign(ddy) !== dy || Math.abs(ddy) < 10)) return;
      var score = dx ? Math.abs(ddx) + Math.abs(ddy) * 3 : Math.abs(ddy) + Math.abs(ddx) * 0.5;
      if (score < bestScore) { bestScore = score; best = el; }
    });
    if (best) focus(best);
  }

  function activate(el) {
    if (!el) return;
    if (el.classList.contains("toggle")) changeOption(el, 1);
    else if (el.tagName === "INPUT") el.focus();
    else el.click();
  }

  function isSelect(el) { return el && el.classList.contains("select"); }

  function openModal() { $("qc").hidden = false; focus($("btnQcCancel")); }
  function closeModal() {
    if (state.qc && state.qc.timer) clearTimeout(state.qc.timer);
    state.qc = null;
    $("qc").hidden = true;
    focus($("btnConnect"));
  }

  document.addEventListener("keydown", function (e) {
    var inInput = document.activeElement && document.activeElement.tagName === "INPUT";
    switch (e.keyCode) {
      case 37:
        if (inInput) break;
        if (isSelect(current)) changeOption(current, -1); else move(-1, 0);
        e.preventDefault(); break;
      case 39:
        if (inInput) break;
        if (isSelect(current)) changeOption(current, 1); else move(1, 0);
        e.preventDefault(); break;
      case 38: move(0, -1); e.preventDefault(); break;
      case 40: move(0, 1); e.preventDefault(); break;
      case 13: if (!inInput) { activate(current); e.preventDefault(); } break;
      case 461: case 27: // Retour
        e.preventDefault();
        if (!$("qc").hidden) closeModal();
        else if (inInput) document.activeElement.blur();
        else if (window.webOS && webOS.platformBack) webOS.platformBack();
        else window.close();
        break;
    }
  });

  document.addEventListener("mouseover", function (e) {
    var el = e.target.closest && e.target.closest(".focusable");
    if (el) focus(el);
  });

  Array.prototype.forEach.call(document.querySelectorAll(".toggle"), function (b) {
    b.addEventListener("click", function () { changeOption(b, 1); });
  });
  $("btnDiscover").addEventListener("click", discover);
  $("btnConnect").addEventListener("click", startQuickConnect);
  $("btnLogout").addEventListener("click", logout);
  $("btnApply").addEventListener("click", function () { run(CTL + " reload", t("m_applying")); });
  $("btnRefresh").addEventListener("click", function () { run(CTL + " refresh", t("m_refreshing")); });
  $("btnPatch").addEventListener("click", togglePatch);
  $("btnQcCancel").addEventListener("click", closeModal);

  // ----------------------------------------------------------- démarrage

  translatePage();
  focus($("btnConnect"));
  execJson(CTL + " status").then(function (st) {
    show(st);
    // Langue de la TV pour les titres des rangées
    if ((st.jellyfin || {}).lang !== LANG) setConfig({ lang: LANG });
    // Première ouverture : pose le hook de boot et active le patch.
    if (!st.bootHook) return run(CTL + " install", t("m_installing"));
    if (!(st.jellyfin && st.jellyfin.server)) discover();
  }).catch(function (e) {
    say(t("m_noHbc", { e: e.message }));
  });
})();
