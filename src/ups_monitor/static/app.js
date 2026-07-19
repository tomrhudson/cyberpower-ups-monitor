const state = {
  devices: [],
  selectedSerial: null,
  hours: 24,
  history: [],
};

const elements = {
  heroTitle: document.querySelector("#heroTitle"),
  heroCopy: document.querySelector("#heroCopy"),
  onlineCount: document.querySelector("#onlineCount"),
  batteryCount: document.querySelector("#batteryCount"),
  offlineCount: document.querySelector("#offlineCount"),
  deviceGrid: document.querySelector("#deviceGrid"),
  eventList: document.querySelector("#eventList"),
  chartTitle: document.querySelector("#chartTitle"),
  chart: document.querySelector("#historyChart"),
  emptyChart: document.querySelector("#emptyChart"),
  refreshLabel: document.querySelector("#refreshLabel"),
  refreshButton: document.querySelector("#refreshButton"),
};

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

async function refresh() {
  elements.refreshButton.disabled = true;
  try {
    const [summary, fleet, events] = await Promise.all([
      getJSON("/api/v1/summary"),
      getJSON("/api/v1/devices"),
      getJSON("/api/v1/events?limit=30"),
    ]);
    state.devices = fleet.devices;
    renderSummary(summary);

    if (
      state.devices.length &&
      !state.devices.some((device) => device.serial === state.selectedSerial)
    ) {
      const firstOnline = state.devices.find((device) => device.online);
      state.selectedSerial = (firstOnline || state.devices[0]).serial;
    }
    renderDevices();
    renderEvents(events.events);
    if (state.selectedSerial) await loadHistory();
    elements.refreshLabel.textContent = `Updated ${formatTime(new Date())}`;
  } catch (error) {
    elements.heroTitle.textContent = "Monitor unavailable";
    elements.heroCopy.textContent =
      "The dashboard could not load its local API. It will retry automatically.";
    elements.refreshLabel.textContent = "Connection failed";
  } finally {
    elements.refreshButton.disabled = false;
  }
}

function renderSummary(summary) {
  elements.onlineCount.textContent = `${summary.online}/${summary.total}`;
  elements.batteryCount.textContent = summary.on_battery;
  elements.offlineCount.textContent = summary.offline;

  if (summary.total === 0) {
    elements.heroTitle.textContent = "Ready for collectors";
    elements.heroCopy.textContent =
      "The monitor is running. Device cards will come alive as the Mac collectors report.";
  } else if (summary.all_ok) {
    elements.heroTitle.textContent = "Utility power is steady";
    elements.heroCopy.textContent =
      "Every configured UPS is reporting normally and remains on utility power.";
  } else if (summary.on_battery > 0) {
    elements.heroTitle.textContent = `${summary.on_battery} UPS ${
      summary.on_battery === 1 ? "is" : "units are"
    } on battery`;
    elements.heroCopy.textContent =
      "Review remaining runtime and the recent PowerPanel event log.";
  } else if (summary.offline > 0) {
    elements.heroTitle.textContent = `${summary.offline} collector ${
      summary.offline === 1 ? "needs" : "collectors need"
    } attention`;
    elements.heroCopy.textContent =
      "Online UPS units remain healthy. An offline card may indicate a sleeping or disconnected Mac.";
  } else {
    elements.heroTitle.textContent = "Power warning detected";
    elements.heroCopy.textContent =
      "One or more UPS units reported a condition that needs review.";
  }
}

function renderDevices() {
  elements.deviceGrid.replaceChildren(
    ...state.devices.map((device) => createDeviceCard(device)),
  );
}

function createDeviceCard(device) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = `device-card ${
    device.serial === state.selectedSerial ? "selected" : ""
  }`;
  card.dataset.serial = device.serial;
  card.setAttribute("aria-label", `Show history for ${device.name}`);

  const charge = numberOrNull(device.battery_charge);
  const chargeText = charge === null ? "—" : `${Math.round(charge)}%`;
  const gaugeLevel = charge === null ? 0 : Math.max(0, Math.min(charge, 100)) * 3.6;
  const statusLabel = statusText(device.status);
  const age = device.received_at
    ? `Updated ${relativeTime(device.received_at)}`
    : "Waiting for first report";
  const collector =
    device.collector ||
    (device.expected_collectors || []).join(" / ") ||
    "Collector pending";

  card.innerHTML = `
    <div class="device-header">
      <div>
        <h3>${escapeHTML(device.name)}</h3>
        <p class="device-model">${escapeHTML(device.model || "Unknown model")}</p>
      </div>
      <span class="status-pill ${escapeHTML(device.status)}">${escapeHTML(statusLabel)}</span>
    </div>
    <div class="device-primary">
      <div class="battery-gauge" style="--level:${gaugeLevel}deg">
        <span>
          <strong>${chargeText}</strong>
          <small>Battery</small>
        </span>
      </div>
      <div class="runtime-block">
        <strong>${formatRuntime(device.runtime_minutes)}</strong>
        <span>Estimated runtime</span>
      </div>
    </div>
    <div class="metric-row">
      <div>
        <strong>${formatMetric(device.output_voltage, "V")}</strong>
        <small>Output</small>
      </div>
      <div>
        <strong>${formatMetric(device.power_watts, "W")}</strong>
        <small>Avg power</small>
      </div>
      <div>
        <strong>${formatMetric(device.load_percent, "%")}</strong>
        <small>Load</small>
      </div>
    </div>
    <div class="device-footer">
      <span>${escapeHTML(age)}</span>
      <span title="${escapeHTML(collector)}">${escapeHTML(collector)}</span>
    </div>
  `;

  card.addEventListener("click", async () => {
    state.selectedSerial = device.serial;
    renderDevices();
    await loadHistory();
  });
  return card;
}

function renderEvents(events) {
  if (!events.length) {
    elements.eventList.innerHTML =
      '<li class="event-empty">No PowerPanel events have been received.</li>';
    return;
  }
  const deviceNames = new Map(
    state.devices.map((device) => [device.serial, device.name]),
  );
  elements.eventList.replaceChildren(
    ...events.map((event) => {
      const item = document.createElement("li");
      item.className = event.severity || "info";
      const title = document.createElement("strong");
      title.textContent = event.description;
      const details = document.createElement("span");
      details.textContent = `${deviceNames.get(event.serial) || event.serial} · ${formatDateTime(
        event.event_time,
      )}`;
      item.append(title, details);
      return item;
    }),
  );
}

async function loadHistory() {
  const selected = state.devices.find(
    (device) => device.serial === state.selectedSerial,
  );
  if (!selected) return;
  elements.chartTitle.textContent = selected.name;
  const payload = await getJSON(
    `/api/v1/devices/${encodeURIComponent(selected.serial)}/history?hours=${state.hours}&limit=4000`,
  );
  state.history = payload.samples;
  drawChart();
}

function drawChart() {
  const canvas = elements.chart;
  const samples = state.history;
  elements.emptyChart.hidden = samples.length > 1;
  canvas.hidden = samples.length <= 1;
  if (samples.length <= 1) return;

  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);

  const width = rect.width;
  const height = rect.height;
  const padding = { top: 14, right: 46, bottom: 28, left: 36 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const timestamps = samples.map((item) => new Date(item.received_at).getTime());
  const minTime = Math.min(...timestamps);
  const maxTime = Math.max(...timestamps);
  const powerValues = samples
    .map((item) => numberOrNull(item.power_watts))
    .filter((value) => value !== null);
  const maxPower = Math.max(100, ...powerValues) * 1.1;

  context.strokeStyle = "rgba(143, 165, 183, 0.12)";
  context.fillStyle = "#71889a";
  context.font = "10px ui-sans-serif, system-ui";
  context.lineWidth = 1;

  for (let index = 0; index <= 4; index += 1) {
    const y = padding.top + (plotHeight / 4) * index;
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.stroke();
    context.fillText(`${100 - index * 25}%`, 3, y + 3);
  }

  const xFor = (time) =>
    padding.left +
    ((time - minTime) / Math.max(maxTime - minTime, 1)) * plotWidth;
  const batteryY = (value) =>
    padding.top + (1 - Math.max(0, Math.min(value, 100)) / 100) * plotHeight;
  const powerY = (value) =>
    padding.top + (1 - Math.max(0, value) / maxPower) * plotHeight;

  drawLine(context, samples, timestamps, "battery_charge", xFor, batteryY, "#42d392");
  drawLine(context, samples, timestamps, "power_watts", xFor, powerY, "#55b9ff");

  const startLabel = new Date(minTime).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  const endLabel = new Date(maxTime).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  context.fillText(startLabel, padding.left, height - 7);
  const endWidth = context.measureText(endLabel).width;
  context.fillText(endLabel, width - padding.right - endWidth, height - 7);
  context.fillText(
    `${Math.round(maxPower)}W`,
    width - padding.right + 8,
    padding.top + 3,
  );
}

function drawLine(context, samples, timestamps, field, xFor, yFor, color) {
  context.beginPath();
  context.strokeStyle = color;
  context.lineWidth = 2;
  context.lineJoin = "round";
  context.lineCap = "round";
  let drawing = false;
  samples.forEach((sample, index) => {
    const value = numberOrNull(sample[field]);
    if (value === null) {
      drawing = false;
      return;
    }
    const x = xFor(timestamps[index]);
    const y = yFor(value);
    if (!drawing) {
      context.moveTo(x, y);
      drawing = true;
    } else {
      context.lineTo(x, y);
    }
  });
  context.stroke();
}

function formatRuntime(value) {
  const minutes = numberOrNull(value);
  if (minutes === null) return "—";
  if (minutes >= 120) {
    return `${(minutes / 60).toFixed(minutes >= 600 ? 0 : 1)} <small>hours</small>`;
  }
  return `${Math.round(minutes)} <small>minutes</small>`;
}

function formatMetric(value, unit) {
  const number = numberOrNull(value);
  if (number === null) return "—";
  const digits = Number.isInteger(number) ? 0 : 1;
  return `${number.toFixed(digits)}${unit}`;
}

function statusText(status) {
  return {
    online: "Utility",
    on_battery: "On battery",
    warning: "Warning",
    unknown: "Unknown",
    offline: "Offline",
  }[status] || status;
}

function relativeTime(value) {
  const date = new Date(value);
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function formatDateTime(value) {
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatTime(date) {
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.querySelectorAll("[data-hours]").forEach((button) => {
  button.addEventListener("click", async () => {
    state.hours = Number(button.dataset.hours);
    document
      .querySelectorAll("[data-hours]")
      .forEach((item) => item.classList.toggle("active", item === button));
    await loadHistory();
  });
});

elements.refreshButton.addEventListener("click", refresh);
window.addEventListener("resize", () => {
  if (state.history.length > 1) drawChart();
});

refresh();
setInterval(refresh, 30_000);
