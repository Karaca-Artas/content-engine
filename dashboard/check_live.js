/* Pano canlı doğrulama betiği (jenerik) — panoyu bir HTTP sunucusundan açar,
   GitHub API moduyla GERÇEK results/ verisini çeker ve sekme içeriklerini rapora döker.
   Marka bilgisi içermez: depo ve anahtar ortamdan gelir (REPO, GH_TOKEN).
   Kullanım (CI): python3 -m http.server 8000 --directory <content-engine> &
                  REPO=<owner/brand-repo> GH_TOKEN=$GITHUB_TOKEN node dashboard/check_live.js */
"use strict";
const { chromium } = require("playwright");

(async () => {
  const repo = process.env.REPO, token = process.env.GH_TOKEN;
  const base = process.env.DASH_URL || "http://localhost:8000/dashboard/index.html";
  if (!repo || !token) { console.error("REPO ve GH_TOKEN ortam değişkenleri gerekli"); process.exit(1); }

  const launchOpts = process.env.PW_EXECUTABLE
    ? { executablePath: process.env.PW_EXECUTABLE }
    : { channel: process.env.PW_CHANNEL || "chrome" };
  const browser = await chromium.launch(launchOpts);
  const page = await browser.newPage();
  if (process.env.FAKE_API_DIR) {
    // yerel test: api.github.com çağrılarını diskteki sahte JSON'lara yönlendir
    await page.route("https://api.github.com/**", route => {
      const m = route.request().url().match(/contents\/(.+)$/);
      const p = m ? m[1].replace(/[^A-Za-z0-9._\/-]/g, "") : "";
      route.fulfill({ path: process.env.FAKE_API_DIR + "/" + p }).catch(() =>
        route.fulfill({ status: 404, body: "{}" }));
    });
  }
  const jsErrors = [];
  page.on("pageerror", e => jsErrors.push(String(e)));

  await page.goto(base);
  await page.fill("#ghRepo", repo);
  await page.fill("#ghPath", "results");
  await page.fill("#ghToken", token);
  await page.click("#ghFetch");
  // çekim bitti sinyali: düğme metni eski haline döner
  await page.waitForFunction(
    () => document.getElementById("ghFetch").textContent === "Veriyi çek", { timeout: 180000 });

  const S = await page.evaluate(() => {
    const t = id => { const el = document.getElementById(id); return el ? el.innerText.trim() : ""; };
    const rows = sel => Math.max(0, document.querySelectorAll(sel + " tr").length - 1);
    const st = window.CE_DASH.state;
    const counts = {
      quality: Object.keys(st.quality.results).length,
      perf: Object.keys(st.perf.results).length,
      actions: Object.keys(st.actions.results).length,
    };
    const out = { counts, tabsHidden: document.getElementById("tabs").hidden, banners: t("banners") };
    if (counts.perf) {
      window.CE_DASH.setTab("perf");
      const firstPrio = document.querySelector("#pPriority tr:nth-child(2)");
      out.perf = {
        runMeta: t("pRunMeta"), tiles: t("pTiles").replace(/\n/g, " · "),
        sources: t("pSources"),
        priorityFirst: firstPrio ? firstPrio.innerText.replace(/\n/g, " | ").trim() : "(yok)",
        priorityRows: rows("#pPriority"), pageRows: rows("#pPages"),
        cannibal: t("pCannibal").split("\n").slice(0, 6).join(" | "),
        changes: t("pChanges").replace(/\n/g, " · "),
      };
    }
    if (counts.actions) {
      window.CE_DASH.setTab("actions");
      out.actions = {
        runMeta: t("aRunMeta"), queueTitle: t("aQueueTitle"),
        tiles: t("aTiles").replace(/\n/g, " · "),
        inputs: t("aInputs"),
        queueRows: rows("#aQueue"),
        queueText: Array.from(document.querySelectorAll("#aQueue tr")).slice(1)
          .map(r => r.innerText.replace(/\n/g, " | ")).join("\n  "),
        urgentRows: rows("#aUrgent"),
        urgentFirst: (document.querySelector("#aUrgent tr:nth-child(2)") || { innerText: "(yok)" })
          .innerText.replace(/\n/g, " | "),
        consolidationRows: rows("#aConsolidation table"),
        strategic: t("aStrategic"),
      };
    }
    if (counts.quality) out.quality = { tiles: t("tiles").replace(/\n/g, " · ") };
    return out;
  });

  console.log("=== Pano v1.2 canlı doğrulama ===");
  console.log("Yüklü koşu sayıları:", JSON.stringify(S.counts));
  if (S.banners) console.log("Uyarılar:", S.banners.replace(/\n/g, " | "));
  if (S.quality) console.log("\n[KALİTE] " + S.quality.tiles);
  if (S.perf) {
    console.log("\n[PERFORMANS] " + S.perf.runMeta);
    console.log("  Kutucuklar: " + S.perf.tiles);
    console.log("  Kaynaklar: " + S.perf.sources);
    console.log("  Öncelik satırı sayısı: " + S.perf.priorityRows + " · sayfa satırı: " + S.perf.pageRows);
    console.log("  Öncelik 1. satır: " + S.perf.priorityFirst);
    console.log("  Kanibalizm: " + S.perf.cannibal);
    console.log("  Değişim: " + S.perf.changes);
  }
  if (S.actions) {
    console.log("\n[AKSİYON KUYRUĞU] " + S.actions.runMeta);
    console.log("  " + S.actions.queueTitle);
    console.log("  Kutucuklar: " + S.actions.tiles);
    console.log("  Girdiler: " + S.actions.inputs);
    console.log("  Kuyruk (" + S.actions.queueRows + " satır):\n  " + S.actions.queueText);
    console.log("  ACİL satır sayısı: " + S.actions.urgentRows + " · ilk: " + S.actions.urgentFirst);
    console.log("  Birleştirme adayı satırı: " + S.actions.consolidationRows);
    console.log("  Stratejik: " + S.actions.strategic.replace(/\n/g, " | "));
  }

  let fail = 0;
  const need = (name, cond) => { console.log((cond ? "OK  " : "FAIL") + " — " + name); if (!cond) fail++; };
  console.log("\n=== Kontroller ===");
  need("JS hatası yok", jsErrors.length === 0);
  need("sekme çubuğu görünür", !S.tabsHidden);
  need("kalite ailesi yüklendi", S.counts.quality > 0);
  need("performans ailesi yüklendi", S.counts.perf > 0);
  need("aksiyon ailesi yüklendi", S.counts.actions > 0);
  need("öncelik önizlemesi dolu", !!(S.perf && S.perf.priorityRows > 0));
  need("aksiyon kuyruğu dolu", !!(S.actions && S.actions.queueRows > 0));
  if (jsErrors.length) console.log("JS hataları: " + jsErrors.join(" | "));

  await browser.close();
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error("Beklenmeyen hata: " + e); process.exit(1); });
