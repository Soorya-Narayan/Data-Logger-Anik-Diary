/**
 * Anik Dairy 10 KL Pasteurizer Dashboard Script
 * Handles real-time polling, Chart.js trend, and CSV / Excel / PDF data exports.
 */

document.addEventListener("DOMContentLoaded", () => {
  let trendChart = null;
  let activeMinutes = 15;

  // DOM Elements
  const clockDisplay = document.getElementById("clock-display");
  const stateBanner = document.getElementById("state-banner");
  const statusText = document.getElementById("status-text");
  const lastUpdateText = document.getElementById("last-update-text");

  const valFlow = document.getElementById("val-flow");
  const valHoldingIn = document.getElementById("val-holding-in");
  const valHoldingOut = document.getElementById("val-holding-out");
  const valProduct = document.getElementById("val-product");

  const fdv1Pill = document.getElementById("fdv1-pill");
  const fdv1Reason = document.getElementById("fdv1-reason");
  const fdv2Pill = document.getElementById("fdv2-pill");
  const fdv2Reason = document.getElementById("fdv2-reason");
  const cipPill = document.getElementById("cip-pill");
  const cipStep = document.getElementById("cip-step");

  const sysCpu = document.getElementById("sys-cpu");
  const sysTemp = document.getElementById("sys-temp");
  const sysRam = document.getElementById("sys-ram");
  const sysDisk = document.getElementById("sys-disk");

  const exportRange = document.getElementById("export-range");
  const btnExportCsv = document.getElementById("btn-export-csv");
  const btnExportExcel = document.getElementById("btn-export-excel");
  const btnExportPdf = document.getElementById("btn-export-pdf");

  // Digital Clock
  setInterval(() => {
    const now = new Date();
    clockDisplay.textContent = now.toLocaleTimeString();
  }, 1000);

  // Initialize Chart.js
  function initChart() {
    const ctx = document.getElementById("trendChart").getContext("2d");
    trendChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Holding In (°C)",
            data: [],
            borderColor: "#fb923c",
            backgroundColor: "rgba(251, 146, 60, 0.1)",
            borderWidth: 2,
            yAxisID: "yTemp",
            tension: 0.15,
            pointRadius: 0,
          },
          {
            label: "Holding Out (°C)",
            data: [],
            borderColor: "#38bdf8",
            backgroundColor: "rgba(56, 189, 248, 0.1)",
            borderWidth: 2,
            yAxisID: "yTemp",
            tension: 0.15,
            pointRadius: 0,
          },
          {
            label: "Milk Flow (L/hr)",
            data: [],
            borderColor: "#818cf8",
            backgroundColor: "rgba(99, 102, 241, 0.08)",
            borderWidth: 1.5,
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
        interaction: {
          mode: "index",
          intersect: false
        },
        scales: {
          x: {
            grid: { color: "rgba(255, 255, 255, 0.04)" },
            ticks: { color: "#94a3b8", maxTicksLimit: 7, font: { size: 10 } }
          },
          yTemp: {
            type: "linear",
            display: true,
            position: "left",
            title: { display: true, text: "Temp (°C)", color: "#94a3b8", font: { size: 10 } },
            grid: { color: "rgba(255, 255, 255, 0.06)" },
            ticks: { color: "#cbd5e1", font: { size: 10 } },
            min: 40,
            max: 100
          },
          yFlow: {
            type: "linear",
            display: true,
            position: "right",
            title: { display: true, text: "Flow (L/hr)", color: "#94a3b8", font: { size: 10 } },
            grid: { drawOnChartArea: false },
            ticks: { color: "#818cf8", font: { size: 10 } },
            min: 0,
            max: 40000
          }
        },
        plugins: {
          legend: {
            labels: { color: "#cbd5e1", boxWidth: 10, padding: 10, font: { size: 11 } }
          }
        }
      }
    });
  }

  // Update Telemetry Metrics
  async function pollCurrent() {
    try {
      const res = await fetch("/api/current");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const json = await res.json();

      if (json.status === "ok" && json.data) {
        const d = json.data;

        // Banner
        statusText.textContent = d.status || "UNKNOWN STATUS";
        const sampleTime = new Date(d.timestamp);
        lastUpdateText.textContent = "Last sample: " + sampleTime.toLocaleTimeString() + " (1s Interval)";

        // State banner coloring
        stateBanner.className = "state-banner";
        const st = (d.status || "").toUpperCase();
        if (st.includes("PRODUCTION ACCEPTED")) {
          stateBanner.classList.add("state-production");
        } else if (st.includes("CIRCULATION")) {
          stateBanner.classList.add("state-circulation");
        } else if (st.includes("CIP")) {
          stateBanner.classList.add("state-cip");
        } else if (st.includes("DIVERT") || st.includes("SUB-COOLING")) {
          stateBanner.classList.add("state-divert");
        }

        // Metrics
        valFlow.textContent = d.milk_flow !== null ? Number(d.milk_flow).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 1 }) : "--";
        valHoldingIn.textContent = d.holding_in_temp !== null ? Number(d.holding_in_temp).toFixed(2) : "--";
        valHoldingOut.textContent = d.holding_out_temp !== null ? Number(d.holding_out_temp).toFixed(2) : "--";
        valProduct.textContent = d.product || "--";

        // FDV 1
        if (d.fdv1_status === 1) {
          fdv1Pill.className = "valve-pill pos-forward";
          fdv1Pill.textContent = "FORWARD";
        } else {
          fdv1Pill.className = "valve-pill pos-divert";
          fdv1Pill.textContent = "DIVERTED";
        }
        fdv1Reason.textContent = "Reason: " + (d.fdv1_reason || "All Ok");

        // FDV 2
        if (d.fdv2_status === 1) {
          fdv2Pill.className = "valve-pill pos-forward";
          fdv2Pill.textContent = "FORWARD";
        } else {
          fdv2Pill.className = "valve-pill pos-divert";
          fdv2Pill.textContent = "DIVERTED";
        }
        fdv2Reason.textContent = "Reason: " + (d.fdv2_reason || "All Ok");

        // CIP
        if (d.cip_status === 1) {
          cipPill.className = "valve-pill pos-cip-active";
          cipPill.textContent = "ACTIVE";
        } else {
          cipPill.className = "valve-pill pos-cip-idle";
          cipPill.textContent = "STANDBY";
        }
        cipStep.textContent = "Step: " + (d.cip_step || "None");
      }
    } catch (err) {
      console.warn("Poll current telemetry error:", err);
    }
  }

  // Update Historical Trend Chart
  async function pollHistory() {
    if (!trendChart) return;
    try {
      const res = await fetch(`/api/history?minutes=${activeMinutes}`);
      if (!res.ok) return;
      const json = await res.json();
      if (json.status !== "ok" || !json.data) return;

      const labels = [];
      const dataIn = [];
      const dataOut = [];
      const dataFlow = [];

      json.data.forEach(pt => {
        const t = new Date(pt.timestamp);
        labels.push(t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
        dataIn.push(pt.holding_in_temp);
        dataOut.push(pt.holding_out_temp);
        dataFlow.push(pt.milk_flow);
      });

      trendChart.data.labels = labels;
      trendChart.data.datasets[0].data = dataIn;
      trendChart.data.datasets[1].data = dataOut;
      trendChart.data.datasets[2].data = dataFlow;
      trendChart.update();
    } catch (err) {
      console.warn("Error updating trend chart:", err);
    }
  }

  // System Diagnostics
  async function pollSystem() {
    try {
      const res = await fetch("/api/system");
      if (!res.ok) return;
      const d = await res.json();

      if (d.cpu_usage_pct !== undefined) sysCpu.textContent = d.cpu_usage_pct + "%";
      if (d.cpu_temp_c !== null && d.cpu_temp_c !== undefined) {
        sysTemp.textContent = d.cpu_temp_c + "°C";
      } else {
        sysTemp.textContent = "N/A";
      }
      if (d.memory_used_mb !== undefined) {
        sysRam.textContent = `${d.memory_used_mb} / ${d.memory_total_mb} MB`;
      }
      if (d.disk_free_gb !== undefined) {
        sysDisk.textContent = `${d.disk_free_gb} GB (${100 - d.disk_used_pct}%)`;
      }
    } catch (err) {
      // Ignore system health errors
    }
  }

  // Export handlers
  function triggerExport(format) {
    const hours = exportRange ? exportRange.value : 8;
    const url = `/api/export/${format}?hours=${hours}`;
    window.location.href = url;
  }

  if (btnExportCsv) {
    btnExportCsv.addEventListener("click", () => triggerExport("csv"));
  }
  if (btnExportExcel) {
    btnExportExcel.addEventListener("click", () => triggerExport("excel"));
  }
  if (btnExportPdf) {
    btnExportPdf.addEventListener("click", () => triggerExport("pdf"));
  }

  // Range Buttons Handler
  document.querySelectorAll(".btn-range").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".btn-range").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeMinutes = parseInt(btn.dataset.mins, 10);
      pollHistory();
    });
  });

  // Start polling loops
  initChart();
  pollCurrent();
  pollHistory();
  pollSystem();

  setInterval(pollCurrent, 1000);   // 1s live values
  setInterval(pollHistory, 5000);   // 5s chart refresh
  setInterval(pollSystem, 15000);   // 15s diagnostics
});
