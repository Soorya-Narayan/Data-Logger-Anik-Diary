/**
 * Anik Dairy 10 KL Pasteurizer SCADA Dashboard Script
 * Handles real-time polling for all 30 instruments, Chart.js trends,
 * category filter tabs, alarms, and CSV / Excel / PDF data exports.
 */

document.addEventListener("DOMContentLoaded", () => {
  let trendChart = null;
  let activeMinutes = 15;

  // DOM Elements - Navigation & Clock
  const clockDisplay = document.getElementById("clock-display");
  const stateBanner = document.getElementById("state-banner");
  const statusText = document.getElementById("status-text");
  const lastUpdateText = document.getElementById("last-update-text");
  const valProduct = document.getElementById("val-product");
  const masterAlarmPill = document.getElementById("master-alarm-pill");
  const masterAlarmText = document.getElementById("master-alarm-text");

  // Executive KPI Quick Bar
  const valFeedFlow = document.getElementById("val-feed-flow");
  const valProductTot = document.getElementById("val-product-tot");
  const valTt05 = document.getElementById("val-tt05");       // Holding In TT05
  const valTt06 = document.getElementById("val-tt06");       // Holding Out 1 TT06
  const valTt16 = document.getElementById("val-tt16");       // Chiller Out TT16
  const valDeltaT = document.getElementById("val-delta-t");
  const valSpHeatingBadge = document.getElementById("val-sp-heating-badge");

  // Thermal Profile Matrix (TT01 – TT16 & Delta T)
  const valTt01 = document.getElementById("val-tt01");
  const valTt02 = document.getElementById("val-tt02");
  const valTt03 = document.getElementById("val-tt03");
  const valTt04Sec = document.getElementById("val-tt04-sec");
  const valTt05Full = document.getElementById("val-tt05-full");
  const valTt06Full = document.getElementById("val-tt06-full");
  const valTt07Sec = document.getElementById("val-tt07-sec");
  const valTt08Full = document.getElementById("val-tt08-full");
  const valTt09Sec = document.getElementById("val-tt09-sec");
  const valTt10 = document.getElementById("val-tt10");
  const valTt11 = document.getElementById("val-tt11");
  const valTt12 = document.getElementById("val-tt12");
  const valTt13 = document.getElementById("val-tt13");
  const valTt14 = document.getElementById("val-tt14");
  const valTt15 = document.getElementById("val-tt15");
  const valTt16Full = document.getElementById("val-tt16-full");
  const valDeltaTFull = document.getElementById("val-delta-t-full");

  // Hydraulic Profile (PT01 – PT06)
  const valPt01 = document.getElementById("val-pt01");
  const valPt02 = document.getElementById("val-pt02");
  const valPt03 = document.getElementById("val-pt03");
  const valPt04 = document.getElementById("val-pt04");
  const valPt05 = document.getElementById("val-pt05");
  const valPt06 = document.getElementById("val-pt06");

  // Controls, Levels & Volume
  const valFeedFlowFull = document.getElementById("val-feed-flow-full");
  const valProductTotFull = document.getElementById("val-product-tot-full");
  const valSteamCv = document.getElementById("val-steam-cv");
  const valDeodoriserLevel = document.getElementById("val-deodoriser-level");
  const valRegenEff = document.getElementById("val-regen-eff");

  // Setpoints
  const valSpHeatingTemp = document.getElementById("val-sp-heating-temp");
  const valSpChillFdv = document.getElementById("val-sp-chill-fdv");
  const valSpHeatingHys = document.getElementById("val-sp-heating-hys");
  const valSpChillPress = document.getElementById("val-sp-chill-press");
  const valSpRegenPress = document.getElementById("val-sp-regen-press");

  // Actuators & Valves
  const hotFdvPill = document.getElementById("hot-fdv-pill");
  const hotFdvStatusText = document.getElementById("hot-fdv-status-text");
  const chillFdvPill = document.getElementById("chill-fdv-pill");
  const chillFdvStatusText = document.getElementById("chill-fdv-status-text");
  const forceCircPill = document.getElementById("force-circ-pill");
  const forceFwdPill = document.getElementById("force-fwd-pill");
  const cipPill = document.getElementById("cip-pill");
  const cipStep = document.getElementById("cip-step");

  // System Diagnostics
  const sysCpu = document.getElementById("sys-cpu");
  const sysTemp = document.getElementById("sys-temp");
  const sysRam = document.getElementById("sys-ram");
  const sysDisk = document.getElementById("sys-disk");

  // Export controls
  const exportRange = document.getElementById("export-range");
  const btnExportCsv = document.getElementById("btn-export-csv");
  const btnExportExcel = document.getElementById("btn-export-excel");
  const btnExportPdf = document.getElementById("btn-export-pdf");
  const reportsDropdown = document.getElementById("reports-menu-popover");
  const btnReportsTrigger = document.getElementById("btn-reports-menu");

  // Clock
  setInterval(() => {
    const now = new Date();
    if (clockDisplay) clockDisplay.textContent = now.toLocaleTimeString();
  }, 1000);

  // Helper for numeric formatting
  function fmtNum(val, dec = 2, defaultVal = "--") {
    if (val === null || val === undefined) return defaultVal;
    const n = Number(val);
    if (isNaN(n)) return defaultVal;
    return n.toFixed(dec);
  }

  // Cross-browser timestamp parser (Safari/WebKit safe)
  function parseTimestamp(ts) {
    if (!ts) return new Date();
    let s = String(ts).trim();
    let d = new Date(s);
    if (!isNaN(d.getTime())) return d;
    s = s.replace(" ", "T").replace(/(\.\d{3})\d+/, "$1");
    d = new Date(s);
    return isNaN(d.getTime()) ? new Date() : d;
  }

  // Category Filter Switching
  const catButtons = document.querySelectorAll(".cat-pill");
  const sections = {
    temps: document.getElementById("grp-temps"),
    pressures: document.getElementById("grp-pressures"),
    control: document.getElementById("grp-control"),
    setpoints: document.getElementById("grp-setpoints"),
    valves: document.getElementById("grp-valves"),
    chart: document.getElementById("grp-chart"),
  };

  catButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      catButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const filter = btn.getAttribute("data-filter");

      if (filter === "all") {
        Object.values(sections).forEach(sec => sec && (sec.style.display = "block"));
      } else {
        Object.entries(sections).forEach(([key, sec]) => {
          if (!sec) return;
          if (key === filter) {
            sec.style.display = "block";
            sec.scrollIntoView({ behavior: "smooth", block: "start" });
          } else {
            sec.style.display = "none";
          }
        });
      }
    });
  });

  // Multi-Profile Trend System
  let activeProfile = "overview";
  let lastHistoryRecords = [];

  const TREND_PROFILES = {
    overview: {
      title: "Master Process Telemetry Overview",
      subtitle: "Multi-axis real-time curves for critical pasteurization instruments",
      primaryKey: "temp_tt06",
      primaryLabel: "TT06 Holding Out",
      primaryUnit: "°C",
      axes: ["yTemp", "yFlow", "yPress", "yPct"],
      channels: [
        { key: "temp_tt06", altKey: "temp_holding_out1_tt05", label: "Holding TT06", tag: "TT-06", unit: "°C", color: "#D7262D", axis: "yTemp", width: 2.5, defaultOn: true },
        { key: "temp_tt01", altKey: "temp_product_in_tt01", label: "Infeed TT01", tag: "TT-01", unit: "°C", color: "#C28E3A", axis: "yTemp", width: 1.8, defaultOn: true },
        { key: "temp_tt16", altKey: "temp_chilling_tt08", label: "Chiller TT16", tag: "TT-16", unit: "°C", color: "#0284C7", axis: "yTemp", width: 1.8, defaultOn: true },
        { key: "feed_flow", altKey: "milk_flow", label: "Feed Flow FIT-101", tag: "FIT-101", unit: "L/H", color: "#006837", axis: "yFlow", width: 1.8, fill: true, defaultOn: true },
        { key: "press_raw_milk_pt01", label: "Raw Milk PT01", tag: "PT-01", unit: "Bar", color: "#3B82F6", axis: "yPress", width: 1.6, defaultOn: false },
        { key: "press_regen_r2_pt02", label: "Regen R2 PT02", tag: "PT-02", unit: "Bar", color: "#8B5CF6", axis: "yPress", width: 1.6, defaultOn: false },
        { key: "steam_cv", label: "Steam CV", tag: "CV-01", unit: "%", color: "#EA580C", axis: "yPct", width: 1.6, defaultOn: false },
        { key: "sp_heating_temp", label: "Heating SP (85°C)", tag: "SP-01", unit: "°C", color: "rgba(215, 38, 45, 0.5)", axis: "yTemp", width: 1.4, dash: [4, 4], defaultOn: true }
      ]
    },
    temperatures: {
      title: "Complete Thermal Profile (TT01 – TT16 & Delta-T)",
      subtitle: "Full 16-channel temperature transmitter matrix and legal pasteurization verification",
      primaryKey: "temp_tt06",
      primaryLabel: "TT06 Holding Out",
      primaryUnit: "°C",
      axes: ["yTemp"],
      channels: [
        { key: "temp_tt06", altKey: "temp_holding_out1_tt05", label: "Holding 1 TT06 [Critical]", tag: "TT-06", unit: "°C", color: "#D7262D", axis: "yTemp", width: 2.5, defaultOn: true },
        { key: "temp_tt05", altKey: "temp_holding_in_tt04", label: "Holding In TT05", tag: "TT-05", unit: "°C", color: "#F97316", axis: "yTemp", width: 1.8, defaultOn: true },
        { key: "temp_tt08", altKey: "temp_holding_out2_tt06", label: "Holding 2 TT08", tag: "TT-08", unit: "°C", color: "#9333EA", axis: "yTemp", width: 1.8, defaultOn: true },
        { key: "temp_tt01", altKey: "temp_product_in_tt01", label: "Product In TT01", tag: "TT-01", unit: "°C", color: "#C28E3A", axis: "yTemp", width: 1.8, defaultOn: true },
        { key: "temp_tt11", label: "Regen 1 Out TT11", tag: "TT-11", unit: "°C", color: "#0D9488", axis: "yTemp", width: 1.6, defaultOn: true },
        { key: "temp_tt12", label: "Product Out TT12", tag: "TT-12", unit: "°C", color: "#2563EB", axis: "yTemp", width: 1.6, defaultOn: true },
        { key: "temp_tt15", label: "Chiller In TT15", tag: "TT-15", unit: "°C", color: "#0284C7", axis: "yTemp", width: 1.6, defaultOn: true },
        { key: "temp_tt16", altKey: "temp_chilling_tt08", label: "Chiller Out TT16", tag: "TT-16", unit: "°C", color: "#06B6D4", axis: "yTemp", width: 1.6, defaultOn: true },
        { key: "temp_tt02", label: "Regen 1 In TT02", tag: "TT-02", unit: "°C", color: "#65A30D", axis: "yTemp", width: 1.4, defaultOn: false },
        { key: "temp_tt03", altKey: "temp_regen_r2_tt03", label: "Regen 2 In TT03", tag: "TT-03", unit: "°C", color: "#EAB308", axis: "yTemp", width: 1.4, defaultOn: false },
        { key: "temp_tt04", label: "TBC TT04", tag: "TT-04", unit: "°C", color: "#64748B", axis: "yTemp", width: 1.2, defaultOn: false },
        { key: "temp_tt07", label: "TBC TT07", tag: "TT-07", unit: "°C", color: "#78716C", axis: "yTemp", width: 1.2, defaultOn: false },
        { key: "temp_tt09", label: "TBC TT09", tag: "TT-09", unit: "°C", color: "#71717A", axis: "yTemp", width: 1.2, defaultOn: false },
        { key: "temp_tt10", label: "TBC TT10", tag: "TT-10", unit: "°C", color: "#737373", axis: "yTemp", width: 1.2, defaultOn: false },
        { key: "delta_t", label: "Delta-T Differential", tag: "DIFF", unit: "°C", color: "#6366F1", axis: "yTemp", width: 1.8, defaultOn: true },
        { key: "sp_heating_temp", label: "Heating SP (85°C)", tag: "SP-01", unit: "°C", color: "rgba(215, 38, 45, 0.5)", axis: "yTemp", width: 1.5, dash: [4, 4], defaultOn: true }
      ]
    },
    pressures: {
      title: "Complete Hydraulic Pressure Profile (PT01 – PT06)",
      subtitle: "Differential, pasteurizer backpressure, and chilled media curves",
      primaryKey: "press_raw_milk_pt01",
      primaryLabel: "PT01 Raw Milk",
      primaryUnit: "Bar",
      axes: ["yPress"],
      channels: [
        { key: "press_raw_milk_pt01", label: "Raw Milk PT01", tag: "PT-01", unit: "Bar", color: "#3B82F6", axis: "yPress", width: 2.0, defaultOn: true },
        { key: "press_regen_r2_pt02", label: "Regen R2 PT02", tag: "PT-02", unit: "Bar", color: "#8B5CF6", axis: "yPress", width: 2.0, defaultOn: true },
        { key: "press_holding_in_pt03", label: "Holding In PT03", tag: "PT-03", unit: "Bar", color: "#EC4899", axis: "yPress", width: 2.0, defaultOn: true },
        { key: "press_chilled_milk_pt04", label: "Chilled Milk PT04", tag: "PT-04", unit: "Bar", color: "#14B8A6", axis: "yPress", width: 2.0, defaultOn: true },
        { key: "press_hot_water_pt05", label: "Hot Water PT05", tag: "PT-05", unit: "Bar", color: "#F59E0B", axis: "yPress", width: 1.8, defaultOn: true },
        { key: "press_chilling_pt06", label: "Chilling PT06", tag: "PT-06", unit: "Bar", color: "#64748B", axis: "yPress", width: 1.8, defaultOn: true },
        { key: "sp_chilling_pressure", label: "Chilling SP (6.0 Bar)", tag: "SP-04", unit: "Bar", color: "rgba(100, 116, 139, 0.6)", axis: "yPress", width: 1.4, dash: [4, 4], defaultOn: false },
        { key: "sp_regen_r1_pressure", label: "Regen SP (7.5 Bar)", tag: "SP-05", unit: "Bar", color: "rgba(139, 92, 246, 0.6)", axis: "yPress", width: 1.4, dash: [4, 4], defaultOn: false }
      ]
    },
    flow: {
      title: "Flow Rate & Mass Production Totalizer",
      subtitle: "Instantaneous feed throughput rate (L/H) vs cumulative yield (Liters)",
      primaryKey: "feed_flow",
      primaryLabel: "FIT-101 Flow",
      primaryUnit: "L/H",
      axes: ["yFlow", "yTot"],
      channels: [
        { key: "feed_flow", altKey: "milk_flow", label: "Feed Flow FIT-101", tag: "FIT-101", unit: "L/H", color: "#006837", axis: "yFlow", width: 2.4, fill: true, defaultOn: true },
        { key: "product_tot", label: "Accumulated Totalizer", tag: "TOT", unit: "L", color: "#10B981", axis: "yTot", width: 2.0, defaultOn: true }
      ]
    },
    controls: {
      title: "Process Control Loops, Levels & Setpoints",
      subtitle: "Steam control valve modulation, vessel levels, and diversion setpoints",
      primaryKey: "steam_cv",
      primaryLabel: "Steam CV",
      primaryUnit: "%",
      axes: ["yPct", "yTemp"],
      channels: [
        { key: "steam_cv", label: "Steam CV Modulation", tag: "CV-01", unit: "%", color: "#EA580C", axis: "yPct", width: 2.2, fill: true, defaultOn: true },
        { key: "deodoriser_level", label: "Deodoriser Level", tag: "LT-01", unit: "%", color: "#9333EA", axis: "yPct", width: 2.0, defaultOn: true },
        { key: "regen_efficiency", label: "Regeneration Efficiency", tag: "EFF", unit: "%", color: "#0D9488", axis: "yPct", width: 2.0, defaultOn: true },
        { key: "sp_heating_temp", label: "Heating SP (85°C)", tag: "SP-01", unit: "°C", color: "#D7262D", axis: "yTemp", width: 1.5, dash: [4, 4], defaultOn: true },
        { key: "sp_chill_fdv_diversion", label: "Chill Diversion SP", tag: "SP-02", unit: "°C", color: "#0284C7", axis: "yTemp", width: 1.5, dash: [4, 4], defaultOn: true }
      ]
    }
  };

  // Chart initialization with multi-scale SCADA configuration
  function initChart() {
    if (window.Chart) {
      Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Plus Jakarta Sans", sans-serif';
    }
    const canvas = document.getElementById("trendChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    trendChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: []
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            grid: { color: "rgba(21, 34, 56, 0.05)" },
            ticks: { color: "#64748b", maxTicksLimit: 8, font: { size: 10 } }
          },
          yTemp: {
            type: "linear",
            position: "left",
            display: true,
            title: { display: true, text: "Temperature (°C)", color: "#D7262D", font: { weight: "bold", size: 10 } },
            suggestedMin: 0,
            suggestedMax: 100,
            grid: { color: "rgba(21, 34, 56, 0.05)" },
            ticks: { color: "#D7262D", font: { size: 10 } }
          },
          yFlow: {
            type: "linear",
            position: "right",
            display: true,
            title: { display: true, text: "Flow Rate (L/H)", color: "#006837", font: { weight: "bold", size: 10 } },
            suggestedMin: 0,
            suggestedMax: 30000,
            grid: { drawOnChartArea: false },
            ticks: { color: "#006837", font: { size: 10 } }
          },
          yPress: {
            type: "linear",
            position: "right",
            display: false,
            title: { display: true, text: "Pressure (Bar)", color: "#7C3AED", font: { weight: "bold", size: 10 } },
            suggestedMin: -3,
            suggestedMax: 10,
            grid: { drawOnChartArea: false },
            ticks: { color: "#7C3AED", font: { size: 10 } }
          },
          yPct: {
            type: "linear",
            position: "right",
            display: false,
            title: { display: true, text: "Control / Level (%)", color: "#EA580C", font: { weight: "bold", size: 10 } },
            suggestedMin: 0,
            suggestedMax: 100,
            grid: { drawOnChartArea: false },
            ticks: { color: "#EA580C", font: { size: 10 } }
          },
          yTot: {
            type: "linear",
            position: "right",
            display: false,
            title: { display: true, text: "Totalizer (L)", color: "#10B981", font: { weight: "bold", size: 10 } },
            grid: { drawOnChartArea: false },
            ticks: { color: "#10B981", font: { size: 10 } }
          }
        },
        plugins: {
          legend: { display: false } // Legend is cleanly rendered in interactive chips above
        }
      }
    });

    setupProfile("overview");
  }

  function setupProfile(profileName) {
    activeProfile = profileName;
    const prof = TREND_PROFILES[profileName] || TREND_PROFILES.overview;

    const titleEl = document.getElementById("trend-section-title");
    const subEl = document.getElementById("trend-section-subtitle");
    const countEl = document.getElementById("trend-active-profile-count");

    if (titleEl) titleEl.textContent = prof.title;
    if (subEl) subEl.textContent = prof.subtitle;
    if (countEl) countEl.textContent = prof.channels.length + " CHANNELS IN VIEW";

    if (trendChart) {
      trendChart.data.datasets = prof.channels.map(ch => ({
        label: `${ch.label} (${ch.unit})`,
        data: [],
        borderColor: ch.color,
        backgroundColor: ch.fill ? (ch.color.includes("rgba") ? ch.color : ch.color + "18") : "transparent",
        borderWidth: ch.width || 1.8,
        borderDash: ch.dash || [],
        fill: !!ch.fill,
        yAxisID: ch.axis || "yTemp",
        tension: 0.15,
        pointRadius: 0,
        hidden: !ch.defaultOn
      }));

      const activeAxes = prof.axes || ["yTemp"];
      trendChart.options.scales.yTemp.display = activeAxes.includes("yTemp");
      trendChart.options.scales.yFlow.display = activeAxes.includes("yFlow");
      trendChart.options.scales.yPress.display = activeAxes.includes("yPress");
      trendChart.options.scales.yPct.display = activeAxes.includes("yPct");
      trendChart.options.scales.yTot.display = activeAxes.includes("yTot");
    }

    renderChips(prof);
    if (lastHistoryRecords && lastHistoryRecords.length > 0) {
      renderTrendData();
    }
  }

  function renderChips(prof) {
    const listEl = document.getElementById("trend-chips-list");
    if (!listEl) return;
    listEl.innerHTML = "";

    prof.channels.forEach((ch, idx) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "trend-chip" + (ch.defaultOn ? "" : " inactive");
      chip.dataset.idx = idx;
      chip.dataset.key = ch.key;

      const dot = document.createElement("span");
      dot.className = "trend-chip-dot";
      dot.style.background = ch.color;

      const txt = document.createElement("span");
      txt.textContent = ch.label;

      const val = document.createElement("span");
      val.className = "trend-chip-val";
      val.id = `chip-val-${ch.key}`;
      val.textContent = "--";

      chip.appendChild(dot);
      chip.appendChild(txt);
      chip.appendChild(val);

      chip.addEventListener("click", () => {
        if (!trendChart) return;
        const isVisible = trendChart.isDatasetVisible(idx);
        trendChart.setDatasetVisibility(idx, !isVisible);
        chip.classList.toggle("inactive", isVisible);
        trendChart.update("none");
        updateTrendStats(lastHistoryRecords);
      });

      listEl.appendChild(chip);
    });
  }

  function renderTrendData() {
    if (!trendChart || !lastHistoryRecords || lastHistoryRecords.length === 0) return;
    const prof = TREND_PROFILES[activeProfile] || TREND_PROFILES.overview;

    const labels = [];
    const channelData = prof.channels.map(() => []);

    lastHistoryRecords.forEach(pt => {
      const t = parseTimestamp(pt.timestamp);
      labels.push(t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));

      prof.channels.forEach((ch, idx) => {
        let val = pt[ch.key];
        if ((val === undefined || val === null) && ch.altKey) {
          val = pt[ch.altKey];
        }
        channelData[idx].push(val !== undefined && val !== null ? Number(val) : null);
      });
    });

    trendChart.data.labels = labels;
    prof.channels.forEach((ch, idx) => {
      if (trendChart.data.datasets[idx]) {
        trendChart.data.datasets[idx].data = channelData[idx];
      }
    });

    trendChart.update("none");

    // Update live value tags on the chips
    const latestPt = lastHistoryRecords[lastHistoryRecords.length - 1];
    if (latestPt) {
      prof.channels.forEach(ch => {
        const valEl = document.getElementById(`chip-val-${ch.key}`);
        if (valEl) {
          let val = latestPt[ch.key];
          if ((val === undefined || val === null) && ch.altKey) val = latestPt[ch.altKey];
          valEl.textContent = fmtNum(val, 1) + " " + ch.unit;
        }
      });
    }

    updateTrendStats(lastHistoryRecords);
  }

  function updateTrendStats(records) {
    if (!records || records.length === 0) return;
    const prof = TREND_PROFILES[activeProfile] || TREND_PROFILES.overview;

    const statPrimary = document.getElementById("trend-stat-primary");
    const statCurrent = document.getElementById("trend-stat-current");
    const statMin = document.getElementById("trend-stat-min");
    const statMax = document.getElementById("trend-stat-max");
    const statAvg = document.getElementById("trend-stat-avg");
    const statSamples = document.getElementById("trend-stat-samples");

    if (statPrimary) statPrimary.textContent = prof.primaryLabel;
    if (statSamples) statSamples.textContent = records.length + " pts";

    const primaryKey = prof.primaryKey;
    const nums = [];
    records.forEach(r => {
      let v = r[primaryKey];
      if (v === undefined || v === null) {
        const ch = prof.channels.find(c => c.key === primaryKey);
        if (ch && ch.altKey) v = r[ch.altKey];
      }
      if (v !== undefined && v !== null && !isNaN(Number(v))) {
        nums.push(Number(v));
      }
    });

    if (nums.length > 0) {
      const cur = nums[nums.length - 1];
      const min = Math.min(...nums);
      const max = Math.max(...nums);
      const avg = nums.reduce((a, b) => a + b, 0) / nums.length;

      if (statCurrent) statCurrent.textContent = fmtNum(cur, 2) + " " + prof.primaryUnit;
      if (statMin) statMin.textContent = fmtNum(min, 2) + " " + prof.primaryUnit;
      if (statMax) statMax.textContent = fmtNum(max, 2) + " " + prof.primaryUnit;
      if (statAvg) statAvg.textContent = fmtNum(avg, 2) + " " + prof.primaryUnit;
    }
  }

  // Poll real-time current telemetry
  async function pollCurrent() {
    try {
      const res = await fetch("/api/current");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const json = await res.json();

      if (json.status === "ok" && json.data) {
        const d = json.data;

        // 1. Process State Banner
        statusText.textContent = d.status || "STANDBY";
        valProduct.textContent = d.product || "--";
        const sampleTime = parseTimestamp(d.timestamp || json.server_time);
        const refreshSec = Math.round((window.POLL_INTERVAL_MS || 3000) / 1000);
        lastUpdateText.textContent = "Last sample: " + sampleTime.toLocaleTimeString() + " (" + refreshSec + "s Refresh)";

        // 2. Master Alarm / Failures Pill
        const failures = d.failures || "NORMAL";
        if (failures !== "NORMAL" && failures !== "" && !failures.includes("NORMAL")) {
          masterAlarmPill.className = "alarm-pill pill-alarm";
          masterAlarmText.textContent = "ALARM: " + failures;
        } else {
          masterAlarmPill.className = "alarm-pill pill-normal";
          masterAlarmText.textContent = "SYSTEM: NORMAL";
        }

        // 3. Executive KPI Quick Bar
        const flowVal = d.feed_flow !== undefined && d.feed_flow !== null ? d.feed_flow : d.milk_flow;
        valFeedFlow.textContent = fmtNum(flowVal, 1);
        valProductTot.textContent = fmtNum(d.product_tot, 1);
        // TT05 is Holding Inlet
        const tt05Val = d.temp_tt05 !== undefined ? d.temp_tt05 : (d.holding_in_temp !== undefined ? d.holding_in_temp : d.temp_holding_in_tt04);
        valTt05.textContent = fmtNum(tt05Val, 2);
        // TT06 is Holding Outlet 1 (Legal Pasteurization Point)
        const tt06Val = d.temp_tt06 !== undefined ? d.temp_tt06 : (d.holding_out_temp !== undefined ? d.holding_out_temp : d.temp_holding_out1_tt05);
        valTt06.textContent = fmtNum(tt06Val, 2);
        // TT16 is Chiller Outlet
        const tt16Val = d.temp_tt16 !== undefined ? d.temp_tt16 : d.temp_chilling_tt08;
        valTt16.textContent = fmtNum(tt16Val, 2);
        valDeltaT.textContent = fmtNum(d.delta_t, 2);
        if (valSpHeatingBadge && d.sp_heating_temp) {
          valSpHeatingBadge.textContent = fmtNum(d.sp_heating_temp, 1) + "°C";
        }

        // 4. Thermal Profile (TT01 – TT16 & Delta T)
        valTt01.textContent = fmtNum(d.temp_tt01 !== undefined ? d.temp_tt01 : d.temp_product_in_tt01, 2);
        valTt02.textContent = fmtNum(d.temp_tt02, 2);
        valTt03.textContent = fmtNum(d.temp_tt03 !== undefined ? d.temp_tt03 : d.temp_regen_r2_tt03, 2);
        valTt04Sec.textContent = fmtNum(d.temp_tt04, 2);
        valTt05Full.textContent = fmtNum(tt05Val, 2);
        valTt06Full.textContent = fmtNum(tt06Val, 2);
        valTt07Sec.textContent = fmtNum(d.temp_tt07, 2);
        valTt08Full.textContent = fmtNum(d.temp_tt08 !== undefined ? d.temp_tt08 : d.temp_holding_out2_tt06, 2);
        valTt09Sec.textContent = fmtNum(d.temp_tt09, 2);
        valTt10.textContent = fmtNum(d.temp_tt10, 2);
        valTt11.textContent = fmtNum(d.temp_tt11, 2);
        valTt12.textContent = fmtNum(d.temp_tt12, 2);
        // TT13 & TT14 are Not Connected
        valTt13.textContent = "NC";
        valTt14.textContent = "NC";
        valTt15.textContent = fmtNum(d.temp_tt15, 2);
        valTt16Full.textContent = fmtNum(tt16Val, 2);
        valDeltaTFull.textContent = fmtNum(d.delta_t, 2);

        // 5. Hydraulics & Pressures (PT01 – PT06)
        valPt01.textContent = fmtNum(d.press_raw_milk_pt01, 2);
        valPt02.textContent = fmtNum(d.press_regen_r2_pt02, 2);
        valPt03.textContent = fmtNum(d.press_holding_in_pt03, 2);
        valPt04.textContent = fmtNum(d.press_chilled_milk_pt04, 2);
        valPt05.textContent = fmtNum(d.press_hot_water_pt05, 2);
        valPt06.textContent = fmtNum(d.press_chilling_pt06, 2);

        // 6. Controls, Levels & Volume
        valFeedFlowFull.textContent = fmtNum(flowVal, 1);
        valProductTotFull.textContent = fmtNum(d.product_tot, 1);
        valSteamCv.textContent = fmtNum(d.steam_cv, 1);
        valDeodoriserLevel.textContent = fmtNum(d.deodoriser_level, 1);
        valRegenEff.textContent = fmtNum(d.regen_efficiency, 1);

        // 7. Setpoints
        valSpHeatingTemp.textContent = fmtNum(d.sp_heating_temp, 1);
        valSpChillFdv.textContent = fmtNum(d.sp_chill_fdv_diversion, 1);
        valSpHeatingHys.textContent = fmtNum(d.sp_heating_fdv_hys, 1);
        valSpChillPress.textContent = fmtNum(d.sp_chilling_pressure, 1);
        valSpRegenPress.textContent = fmtNum(d.sp_regen_r1_pressure, 1);

        // 8. Actuators & Valves
        // HOT FDV
        const hotOpen = d.hot_fdv_open || d.fdv1_status === 1;
        if (hotOpen) {
          hotFdvPill.className = "valve-pill pos-forward";
          hotFdvPill.textContent = "FORWARD";
        } else {
          hotFdvPill.className = "valve-pill pos-divert";
          hotFdvPill.textContent = "DIVERTED";
        }
        hotFdvStatusText.textContent = "Reason: " + (d.hot_fdv_status || d.fdv1_reason || "All Ok");

        // CHILL FDV
        const chillOpen = d.chill_fdv_open || d.fdv2_status === 1;
        if (chillOpen) {
          chillFdvPill.className = "valve-pill pos-forward";
          chillFdvPill.textContent = "FORWARD";
        } else {
          chillFdvPill.className = "valve-pill pos-divert";
          chillFdvPill.textContent = "DIVERTED";
        }
        chillFdvStatusText.textContent = "Reason: " + (d.chill_fdv_status || d.fdv2_reason || "All Ok");

        // Force Modes
        if (d.force_circulation) {
          forceCircPill.className = "mode-pill mode-active";
          forceCircPill.textContent = "ACTIVE";
        } else {
          forceCircPill.className = "mode-pill mode-off";
          forceCircPill.textContent = "OFF";
        }

        if (d.force_forward) {
          forceFwdPill.className = "mode-pill mode-active";
          forceFwdPill.textContent = "BYPASS ACTIVE";
        } else {
          forceFwdPill.className = "mode-pill mode-off";
          forceFwdPill.textContent = "OFF";
        }

        // CIP
        if (d.cip_status === 1) {
          cipPill.className = "valve-pill pos-cip-active";
          cipPill.textContent = "ACTIVE";
        } else {
          cipPill.className = "valve-pill pos-cip-idle";
          cipPill.textContent = "STANDBY";
        }
        cipStep.textContent = "Phase: " + (d.cip_step || "None");
      }
    } catch (err) {
      console.warn("Poll current telemetry error:", err);
    }
  }

  // Poll trend history
  async function pollHistory() {
    if (!trendChart) return;
    try {
      const res = await fetch(`/api/history?minutes=${activeMinutes}`);
      if (!res.ok) return;
      const json = await res.json();
      if (json.status !== "ok" || !json.data) return;

      lastHistoryRecords = json.data;
      renderTrendData();
    } catch (err) {
      console.warn("Poll history error:", err);
    }
  }

  // Poll system diagnostics
  async function pollSystem() {
    try {
      const res = await fetch("/api/system");
      if (!res.ok) return;
      const json = await res.json();
      if (sysCpu) sysCpu.textContent = json.cpu_usage_pct + "%";
      if (sysTemp) sysTemp.textContent = json.cpu_temp_c ? json.cpu_temp_c + "°C" : "N/A";
      if (sysRam) sysRam.textContent = json.memory_used_mb + " / " + json.memory_total_mb + " MB";
      if (sysDisk) sysDisk.textContent = json.disk_free_gb + " GB";
    } catch (err) {
      // Diagnostic failure non-critical
    }
  }

  // Reports popover toggle
  if (btnReportsTrigger && reportsDropdown) {
    btnReportsTrigger.addEventListener("click", (e) => {
      e.stopPropagation();
      reportsDropdown.classList.toggle("hidden");
    });

    document.addEventListener("click", (e) => {
      if (!reportsDropdown.contains(e.target) && e.target !== btnReportsTrigger) {
        reportsDropdown.classList.add("hidden");
      }
    });

    // Shift and duration segmented buttons
    const segButtons = document.querySelectorAll("#reports-menu-popover .seg-btn");
    segButtons.forEach(btn => {
      btn.addEventListener("click", () => {
        segButtons.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        if (exportRange) {
          exportRange.value = btn.getAttribute("data-hours");
        }
      });
    });

    function getExportQuery() {
      const val = exportRange ? exportRange.value : "shift";
      if (val === "shift") return "shift=current";
      if (val === "shift1") return "shift=1";
      if (val === "shift2") return "shift=2";
      if (val === "shift3") return "shift=3";
      return `hours=${val}`;
    }

    // Download triggers
    if (btnExportCsv) {
      btnExportCsv.addEventListener("click", () => {
        window.location.href = `/api/export/csv?${getExportQuery()}`;
        reportsDropdown.classList.add("hidden");
      });
    }

    if (btnExportExcel) {
      btnExportExcel.addEventListener("click", () => {
        window.location.href = `/api/export/excel?${getExportQuery()}`;
        reportsDropdown.classList.add("hidden");
      });
    }

    if (btnExportPdf) {
      btnExportPdf.addEventListener("click", () => {
        window.location.href = `/api/export/pdf?${getExportQuery()}`;
        reportsDropdown.classList.add("hidden");
      });
    }
  }

  // Range buttons for Trend
  const rangeBtns = document.querySelectorAll(".chart-controls .btn-range");
  rangeBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      rangeBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeMinutes = parseInt(btn.getAttribute("data-mins"), 10) || 15;
      pollHistory();
    });
  });

  // Profile tabs for Trend
  const profileBtns = document.querySelectorAll(".btn-trend-profile");
  profileBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      profileBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const profile = btn.dataset.profile;
      setupProfile(profile);
    });
  });

  // Quick Action Buttons (Show All / Reset)
  const btnShowAll = document.getElementById("btn-trend-show-all");
  if (btnShowAll) {
    btnShowAll.addEventListener("click", () => {
      if (!trendChart) return;
      const chips = document.querySelectorAll(".trend-chip");
      chips.forEach((c, idx) => {
        c.classList.remove("inactive");
        trendChart.setDatasetVisibility(idx, true);
      });
      trendChart.update("none");
      updateTrendStats(lastHistoryRecords);
    });
  }

  const btnReset = document.getElementById("btn-trend-reset");
  if (btnReset) {
    btnReset.addEventListener("click", () => {
      setupProfile(activeProfile);
    });
  }

  // Dismiss Minimalist Loading Screen
  function dismissLoadingScreen() {
    const loader = document.getElementById("app-loading-screen");
    if (!loader) return;
    loader.classList.add("fade-out");
    setTimeout(() => {
      if (loader && loader.parentNode) loader.parentNode.removeChild(loader);
    }, 500);
  }

  // Dismiss loading screen smoothly after 1.2s splash
  setTimeout(dismissLoadingScreen, 1200);

  // Start initialization
  initChart();
  pollCurrent();
  pollHistory();
  pollSystem();

  const pollIntervalMs = window.POLL_INTERVAL_MS || 3000;
  setInterval(pollCurrent, pollIntervalMs);
  setInterval(pollHistory, 5000);
  setInterval(pollSystem, 10000);
});
