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
    if (window.Chart) {
      Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Plus Jakarta Sans", sans-serif';
    }
    const ctx = document.getElementById("trendChart").getContext("2d");
    trendChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Holding In (°C)",
            data: [],
            borderColor: "#ea580c",
            backgroundColor: "rgba(234, 88, 12, 0.08)",
            borderWidth: 2,
            yAxisID: "yTemp",
            tension: 0.15,
            pointRadius: 0,
          },
          {
            label: "Holding Out (°C)",
            data: [],
            borderColor: "#0284c7",
            backgroundColor: "rgba(2, 132, 199, 0.08)",
            borderWidth: 2,
            yAxisID: "yTemp",
            tension: 0.15,
            pointRadius: 0,
          },
          {
            label: "Milk Flow (L/hr)",
            data: [],
            borderColor: "#4f46e5",
            backgroundColor: "rgba(79, 70, 229, 0.06)",
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
            grid: { color: "rgba(0, 0, 0, 0.06)" },
            ticks: { color: "#64748b", maxTicksLimit: 7, font: { size: 10 } }
          },
          yTemp: {
            type: "linear",
            display: true,
            position: "left",
            title: { display: true, text: "Temp (°C)", color: "#475569", font: { size: 10, weight: "bold" } },
            grid: { color: "rgba(0, 0, 0, 0.06)" },
            ticks: { color: "#334155", font: { size: 10 } },
            min: 40,
            max: 100
          },
          yFlow: {
            type: "linear",
            display: true,
            position: "right",
            title: { display: true, text: "Flow (L/hr)", color: "#475569", font: { size: 10, weight: "bold" } },
            grid: { drawOnChartArea: false },
            ticks: { color: "#4f46e5", font: { size: 10 } },
            min: 0,
            max: 40000
          }
        },
        plugins: {
          legend: {
            labels: { color: "#1e293b", boxWidth: 10, padding: 10, font: { size: 11, weight: "bold" } }
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

  // =========================================================================
  // Liquid Glass Reports Popover & Segmented Controls
  // =========================================================================
  const btnReportsMenu = document.getElementById("btn-reports-menu");
  const reportsPopover = document.getElementById("reports-menu-popover");
  const reportsWrapper = document.getElementById("reports-dropdown-wrapper");
  const segButtons = document.querySelectorAll(".segmented-control .seg-btn");

  if (btnReportsMenu && reportsPopover) {
    btnReportsMenu.addEventListener("click", (e) => {
      e.stopPropagation();
      reportsPopover.classList.toggle("hidden");
    });

    document.addEventListener("click", (e) => {
      if (reportsWrapper && !reportsWrapper.contains(e.target)) {
        reportsPopover.classList.add("hidden");
      }
    });
  }

  segButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      segButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      if (exportRange) {
        exportRange.value = btn.dataset.hours;
      }
    });
  });

  // Export handlers
  function triggerExport(format) {
    const hours = exportRange ? exportRange.value : 8;
    if (reportsPopover) reportsPopover.classList.add("hidden");
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

  // =========================================================================
  // PLC Remote Configuration & Tag Auto-Discovery Handlers
  // =========================================================================
  const btnOpenSettings = document.getElementById("btn-open-settings");
  const btnCloseSettings = document.getElementById("btn-close-settings");
  const settingsModal = document.getElementById("settings-modal");
  const cfgPlcIp = document.getElementById("cfg-plc-ip");
  const btnScanNetwork = document.getElementById("btn-scan-network");
  const btnFetchTags = document.getElementById("btn-fetch-tags");
  const discoveryStatus = document.getElementById("discovery-status");
  const discoveredDevicesList = document.getElementById("discovered-devices-list");
  const btnTestRead = document.getElementById("btn-test-read");
  const btnSavePlcConfig = document.getElementById("btn-save-plc-config");
  const cfgTargetMode = document.getElementById("cfg-target-mode");
  const testReadOutput = document.getElementById("test-read-output");

  const fields = [
    "milk_flow", "holding_in_temp", "holding_out_temp", "product",
    "status", "fdv1_status", "fdv2_status", "cip_status"
  ];

  const btnMinimizeKiosk = document.getElementById("btn-minimize-kiosk");
  if (btnMinimizeKiosk) {
    btnMinimizeKiosk.addEventListener("click", async () => {
      // Exit browser fullscreen if active
      if (document.fullscreenElement) {
        try {
          await document.exitFullscreen();
        } catch (e) {
          console.warn("Fullscreen exit error:", e);
        }
      }
      // Send backend signal to minimize on Wayland / desktop
      try {
        await fetch("/api/system/minimize-kiosk", { method: "POST" });
      } catch (err) {
        console.warn("Minimize API error:", err);
      }
    });
  }

  // Open modal & load current config
  if (btnOpenSettings) {
    btnOpenSettings.addEventListener("click", async () => {
      settingsModal.classList.remove("hidden");
      try {
        const res = await fetch("/api/plc/current-config");
        if (res.ok) {
          const d = await res.json();
          if (d.ip) cfgPlcIp.value = d.ip;
          if (d.mode) cfgTargetMode.value = d.mode.toLowerCase();
          if (d.tags) {
            fields.forEach(f => {
              const inp = document.getElementById(`tag-${f}`);
              if (inp && d.tags[f]) inp.value = d.tags[f];
            });
          }
        }
      } catch (err) {
        console.warn("Could not fetch current PLC config:", err);
      }
    });
  }

  // Close modal
  if (btnCloseSettings) {
    btnCloseSettings.addEventListener("click", () => {
      settingsModal.classList.add("hidden");
    });
  }
  if (settingsModal) {
    settingsModal.addEventListener("click", (e) => {
      if (e.target === settingsModal) settingsModal.classList.add("hidden");
    });
  }

  // 1. Scan Subnet
  if (btnScanNetwork) {
    btnScanNetwork.addEventListener("click", async () => {
      discoveryStatus.className = "status-msg";
      discoveryStatus.textContent = "Scanning subnet via EtherNet/IP broadcast (port 44818)...";
      discoveredDevicesList.classList.add("hidden");
      discoveredDevicesList.innerHTML = "";

      try {
        const res = await fetch("/api/plc/discover");
        const json = await res.json();
        const devs = json.devices || [];

        if (devs.length === 0) {
          discoveryStatus.className = "status-msg error";
          discoveryStatus.textContent = "No EtherNet/IP devices detected. Ensure Ethernet cable is connected to PLC switch.";
        } else {
          discoveryStatus.className = "status-msg success";
          discoveryStatus.textContent = `Found ${devs.length} device(s) on network! Click an IP to select:`;
          discoveredDevicesList.classList.remove("hidden");

          devs.forEach(dev => {
            const item = document.createElement("div");
            item.style.cssText = "padding: 4px 6px; cursor: pointer; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between;";
            item.innerHTML = `<strong>${dev.ip}</strong> <span>${dev.product_name} (${dev.vendor})</span>`;
            item.addEventListener("click", () => {
              cfgPlcIp.value = dev.ip;
              discoveryStatus.textContent = `Selected PLC IP: ${dev.ip}`;
            });
            discoveredDevicesList.appendChild(item);
          });
        }
      } catch (err) {
        discoveryStatus.className = "status-msg error";
        discoveryStatus.textContent = "Scan request failed: " + err.message;
      }
    });
  }

  // 2. Auto-Detect Tags from PLC
  if (btnFetchTags) {
    btnFetchTags.addEventListener("click", async () => {
      const ip = cfgPlcIp.value.trim();
      if (!ip) {
        discoveryStatus.className = "status-msg error";
        discoveryStatus.textContent = "Please enter or select a valid PLC IP address.";
        return;
      }

      discoveryStatus.className = "status-msg";
      discoveryStatus.textContent = `Connecting to Micro850 at ${ip} and querying tag database...`;

      try {
        const res = await fetch(`/api/plc/tags?ip=${encodeURIComponent(ip)}`);
        const data = await res.json();

        if (!data.success && (!data.tags || data.tags.length === 0)) {
          discoveryStatus.className = "status-msg error";
          discoveryStatus.textContent = `Error: ${data.error || "No tags returned. Is the Micro850 reachable?"}`;
          return;
        }

        discoveryStatus.className = "status-msg success";
        discoveryStatus.textContent = `Extracted ${data.total_tags} tags from PLC! Recommended mappings pre-selected.`;

        // Populate dropdowns for each field
        fields.forEach(f => {
          const inp = document.getElementById(`tag-${f}`);
          const sel = document.getElementById(`sel-${f}`);
          if (!sel) return;

          sel.innerHTML = `<option value="">-- Select PLC Tag --</option>`;
          data.tags.forEach(t => {
            const opt = document.createElement("option");
            opt.value = t.name;
            opt.textContent = `${t.name} (${t.data_type})`;
            sel.appendChild(opt);
          });

          // Set suggestion if available
          const suggested = data.suggestions ? data.suggestions[f] : null;
          if (suggested) {
            sel.value = suggested;
            if (inp) inp.value = suggested;
          }

          // Unhide select and hide manual input
          sel.classList.remove("hidden");
          if (inp) inp.classList.add("hidden");

          sel.addEventListener("change", () => {
            if (inp) inp.value = sel.value;
          });
        });

      } catch (err) {
        discoveryStatus.className = "status-msg error";
        discoveryStatus.textContent = "Failed to query PLC: " + err.message;
      }
    });
  }

  // 3. Test Live Read
  function getCurrentTagMapping() {
    const map = {};
    fields.forEach(f => {
      const inp = document.getElementById(`tag-${f}`);
      const sel = document.getElementById(`sel-${f}`);
      const val = (sel && !sel.classList.contains("hidden") && sel.value) ? sel.value : (inp ? inp.value.trim() : "");
      if (val) map[f] = val;
    });
    return map;
  }

  if (btnTestRead) {
    btnTestRead.addEventListener("click", async () => {
      const ip = cfgPlcIp.value.trim();
      const tags = getCurrentTagMapping();
      testReadOutput.classList.remove("hidden");
      testReadOutput.innerHTML = "<em>Sending CIP Read requests to PLC...</em>";

      try {
        const res = await fetch("/api/plc/test-read", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ip, tags })
        });
        const d = await res.json();
        let html = "";

        if (d.results && Object.keys(d.results).length > 0) {
          html += "<div style='color: #16a34a; font-weight: bold;'>Read Success:</div>";
          for (const [k, v] of Object.entries(d.results)) {
            html += `<div>[OK] ${k} (${v.tag}) = <strong>${v.value}</strong></div>`;
          }
        }
        if (d.errors && Object.keys(d.errors).length > 0) {
          html += "<div style='color: #dc2626; font-weight: bold; margin-top: 4px;'>Read Errors:</div>";
          for (const [k, v] of Object.entries(d.errors)) {
            html += `<div>[FAIL] ${k} (${v.tag}) = ${v.status}</div>`;
          }
        }
        if (!html) html = `<span style='color: #dc2626;'>${d.error || "No tags could be read."}</span>`;
        testReadOutput.innerHTML = html;
      } catch (err) {
        testReadOutput.innerHTML = `<span style='color: #dc2626;'>Test read error: ${err.message}</span>`;
      }
    });
  }

  // 4. Save and Apply Config
  if (btnSavePlcConfig) {
    btnSavePlcConfig.addEventListener("click", async () => {
      const ip = cfgPlcIp.value.trim();
      const tags = getCurrentTagMapping();
      const mode = cfgTargetMode.value;

      btnSavePlcConfig.disabled = true;
      btnSavePlcConfig.textContent = "Saving...";

      try {
        const res = await fetch("/api/plc/save-config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ip, tags, mode })
        });
        const d = await res.json();
        if (d.success) {
          alert(`Configuration saved successfully!\nMode: ${mode.toUpperCase()}\nPLC IP: ${ip}\nPoller service restarted.`);
          settingsModal.classList.add("hidden");
          setTimeout(() => window.location.reload(), 1000);
        } else {
          alert("Error saving configuration: " + (d.error || "Unknown error"));
        }
      } catch (err) {
        alert("Failed to save: " + err.message);
      } finally {
        btnSavePlcConfig.disabled = false;
        btnSavePlcConfig.textContent = "💾 Save & Apply Config";
      }
    });
  }

  // Start polling loops
  initChart();
  pollCurrent();
  pollHistory();
  pollSystem();

  setInterval(pollCurrent, 1000);   // 1s live values
  setInterval(pollHistory, 5000);   // 5s chart refresh
  setInterval(pollSystem, 15000);   // 15s diagnostics
});

