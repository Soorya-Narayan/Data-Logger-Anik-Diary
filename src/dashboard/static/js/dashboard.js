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
  const valTt04 = document.getElementById("val-tt04");
  const valTt05 = document.getElementById("val-tt05");
  const valTt08 = document.getElementById("val-tt08");
  const valDeltaT = document.getElementById("val-delta-t");
  const valSpHeatingBadge = document.getElementById("val-sp-heating-badge");

  // Thermal Profile (TT01 – TT09 & Delta T)
  const valTt01 = document.getElementById("val-tt01");
  const valTt03 = document.getElementById("val-tt03");
  const valTt04Full = document.getElementById("val-tt04-full");
  const valTt05Full = document.getElementById("val-tt05-full");
  const valTt06 = document.getElementById("val-tt06");
  const valTt07 = document.getElementById("val-tt07");
  const valTt08Full = document.getElementById("val-tt08-full");
  const valTt09 = document.getElementById("val-tt09");
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

  // Chart initialization
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
        datasets: [
          {
            label: "Holding Outlet TT05 (°C)",
            data: [],
            borderColor: "#D7262D",
            backgroundColor: "rgba(215, 38, 45, 0.08)",
            borderWidth: 2.2,
            yAxisID: "yTemp",
            tension: 0.15,
            pointRadius: 0,
          },
          {
            label: "Product In TT01 (°C)",
            data: [],
            borderColor: "#C28E3A",
            backgroundColor: "rgba(194, 142, 58, 0.08)",
            borderWidth: 1.8,
            yAxisID: "yTemp",
            tension: 0.15,
            pointRadius: 0,
          },
          {
            label: "Chilling TT08 (°C)",
            data: [],
            borderColor: "#0284C7",
            backgroundColor: "rgba(2, 132, 199, 0.08)",
            borderWidth: 1.8,
            yAxisID: "yTemp",
            tension: 0.15,
            pointRadius: 0,
          },
          {
            label: "Feed Flow (L/H)",
            data: [],
            borderColor: "#006837",
            backgroundColor: "rgba(0, 104, 55, 0.08)",
            borderWidth: 1.8,
            fill: true,
            yAxisID: "yFlow",
            tension: 0.15,
            pointRadius: 0,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            grid: { color: "rgba(21, 34, 56, 0.05)" },
            ticks: { color: "#64748b", maxTicksLimit: 7, font: { size: 10 } }
          },
          yTemp: {
            type: "linear",
            position: "left",
            title: { display: true, text: "Temperature (°C)", color: "#D7262D", font: { weight: "bold", size: 11 } },
            suggestedMin: 0,
            suggestedMax: 100,
            grid: { color: "rgba(21, 34, 56, 0.05)" },
            ticks: { color: "#152238" }
          },
          yFlow: {
            type: "linear",
            position: "right",
            title: { display: true, text: "Flow Rate (L/H)", color: "#006837", font: { weight: "bold", size: 11 } },
            suggestedMin: 0,
            suggestedMax: 30000,
            grid: { drawOnChartArea: false },
            ticks: { color: "#006837" }
          }
        },
        plugins: {
          legend: {
            labels: { color: "#152238", boxWidth: 12, padding: 12, font: { size: 11, weight: "bold" } }
          }
        }
      }
    });
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
        valTt04.textContent = fmtNum(d.temp_holding_in_tt04, 2);
        valTt05.textContent = fmtNum(d.temp_holding_out1_tt05 !== undefined ? d.temp_holding_out1_tt05 : d.holding_out_temp, 2);
        valTt08.textContent = fmtNum(d.temp_chilling_tt08, 2);
        valDeltaT.textContent = fmtNum(d.delta_t, 2);
        if (valSpHeatingBadge && d.sp_heating_temp) {
          valSpHeatingBadge.textContent = fmtNum(d.sp_heating_temp, 1) + "°C";
        }

        // 4. Thermal Profile (TT01 – TT09 & Delta T)
        valTt01.textContent = fmtNum(d.temp_product_in_tt01 !== undefined ? d.temp_product_in_tt01 : d.holding_in_temp, 2);
        valTt03.textContent = fmtNum(d.temp_regen_r2_tt03, 2);
        valTt04Full.textContent = fmtNum(d.temp_holding_in_tt04, 2);
        valTt05Full.textContent = fmtNum(d.temp_holding_out1_tt05 !== undefined ? d.temp_holding_out1_tt05 : d.holding_out_temp, 2);
        valTt06.textContent = fmtNum(d.temp_holding_out2_tt06, 2);
        valTt07.textContent = fmtNum(d.temp_chilled_milk_tt07, 2);
        valTt08Full.textContent = fmtNum(d.temp_chilling_tt08, 2);
        valTt09.textContent = fmtNum(d.temp_hot_water_tt09, 2);
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

      const labels = [];
      const dataTt05 = [];
      const dataTt01 = [];
      const dataTt08 = [];
      const dataFlow = [];

      json.data.forEach(pt => {
        const t = new Date(pt.timestamp);
        labels.push(t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
        dataTt05.push(pt.temp_holding_out1_tt05 !== undefined && pt.temp_holding_out1_tt05 !== null ? pt.temp_holding_out1_tt05 : pt.holding_out_temp);
        dataTt01.push(pt.temp_product_in_tt01 !== undefined && pt.temp_product_in_tt01 !== null ? pt.temp_product_in_tt01 : pt.holding_in_temp);
        dataTt08.push(pt.temp_chilling_tt08);
        dataFlow.push(pt.feed_flow !== undefined && pt.feed_flow !== null ? pt.feed_flow : pt.milk_flow);
      });

      trendChart.data.labels = labels;
      trendChart.data.datasets[0].data = dataTt05;
      trendChart.data.datasets[1].data = dataTt01;
      trendChart.data.datasets[2].data = dataTt08;
      trendChart.data.datasets[3].data = dataFlow;
      trendChart.update("none");
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

    // Duration segmented buttons
    const segButtons = document.querySelectorAll("#export-segmented .seg-btn");
    segButtons.forEach(btn => {
      btn.addEventListener("click", () => {
        segButtons.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        exportRange.value = btn.getAttribute("data-hours");
      });
    });

    // Download triggers
    if (btnExportCsv) {
      btnExportCsv.addEventListener("click", () => {
        const hours = exportRange ? exportRange.value : 8;
        window.location.href = `/api/export/csv?hours=${hours}`;
        reportsDropdown.classList.add("hidden");
      });
    }

    if (btnExportExcel) {
      btnExportExcel.addEventListener("click", () => {
        const hours = exportRange ? exportRange.value : 8;
        window.location.href = `/api/export/excel?hours=${hours}`;
        reportsDropdown.classList.add("hidden");
      });
    }

    if (btnExportPdf) {
      btnExportPdf.addEventListener("click", () => {
        const hours = exportRange ? exportRange.value : 8;
        window.location.href = `/api/export/pdf?hours=${hours}`;
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
