const state = {
  machineTypes: [],
  status: null,
  machines: { active: [], recent: [] },
  view: "active",
  loadFormDirty: false,
};

const $ = (id) => document.getElementById(id);

function numberValue(id) {
  const raw = $(id).value;
  if (raw === "") {
    return null;
  }
  return Number(raw);
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function payloadWithDuration(prefix) {
  const minimum = numberValue(`${prefix}Min`);
  const maximum = numberValue(`${prefix}Max`);
  if (minimum === null && maximum === null) {
    return null;
  }
  if (minimum === null || maximum === null) {
    throw new Error("duration min and max must be set together");
  }
  return { min: minimum, max: maximum };
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => toast.classList.remove("visible"), 2600);
}

function machineMixPayload() {
  const mix = {};
  state.machineTypes.forEach((type) => {
    const value = Number($(`mix-${type.name}`).value);
    if (value > 0) {
      mix[type.name] = value;
    }
  });
  return mix;
}

function renderMachineControls() {
  const mix = $("machineMix");
  mix.querySelectorAll(".mix-item").forEach((node) => node.remove());

  const manualType = $("manualType");
  manualType.replaceChildren();

  const anyOption = document.createElement("option");
  anyOption.value = "";
  anyOption.textContent = "Any";
  manualType.append(anyOption);

  state.machineTypes.forEach((type) => {
    const item = document.createElement("label");
    item.className = "mix-item";
    item.innerHTML = `<span>${type.display_name || type.name}</span><input id="mix-${type.name}" type="number" min="0" step="0.1" value="1">`;
    mix.append(item);

    const option = document.createElement("option");
    option.value = type.name;
    option.textContent = type.display_name || type.name;
    manualType.append(option);
  });
}

function renderLoadForm(status) {
  $("targetActive").value = status.target.target_active;
  $("spawnRate").value = status.target.spawn_rate_per_sec;
  $("faultProbability").value = status.target.fault_probability_per_minute;
  $("telemetryMs").value = status.target.telemetry_interval_ms ?? "";

  if (status.target.duration_seconds) {
    $("durationMin").value = status.target.duration_seconds.min;
    $("durationMax").value = status.target.duration_seconds.max;
  } else {
    $("durationMin").value = "";
    $("durationMax").value = "";
  }

  if (status.target.machine_mix) {
    Object.entries(status.target.machine_mix).forEach(([name, value]) => {
      const input = $(`mix-${name}`);
      if (input) {
        input.value = value;
      }
    });
  }
}

function renderStatus(options = {}) {
  const status = state.status;
  if (!status) {
    return;
  }
  $("activeCount").textContent = status.active_count;
  $("completedCount").textContent = status.completed_count;
  $("brokenCount").textContent = status.broken_count;
  $("failedCount").textContent = status.failed_count;
  $("spawnedCount").textContent = status.total_spawned;
  $("targetPill").textContent = `${status.tcp_target.host}:${status.tcp_target.port}`;

  if (options.syncForm || !state.loadFormDirty) {
    renderLoadForm(status);
  }
}

function formatAge(machine) {
  const age = Number(machine.age_seconds || 0);
  if (age < 60) {
    return `${age.toFixed(1)}s`;
  }
  return `${Math.floor(age / 60)}m ${Math.floor(age % 60)}s`;
}

function renderMachines() {
  const rows = $("machineRows");
  rows.replaceChildren();
  const machines = state.machines[state.view] || [];

  if (machines.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = `<td class="empty-row" colspan="7">No machines</td>`;
    rows.append(row);
    return;
  }

  machines.forEach((machine) => {
    const row = document.createElement("tr");
    const canBreak = state.view === "active" && !["broken", "failed", "stopping"].includes(machine.state);
    row.innerHTML = `
      <td>${machine.machine_id}</td>
      <td>${machine.machine_type}</td>
      <td><span class="state ${machine.state}">${machine.state}</span></td>
      <td>${formatAge(machine)}</td>
      <td>${machine.telemetry_count}</td>
      <td>${machine.fault_probability_per_minute}</td>
      <td>${canBreak ? `<button class="quiet danger-button" type="button" title="Break machine" data-break="${machine.machine_id}">Break</button>` : ""}</td>
    `;
    rows.append(row);
  });
}

async function refresh() {
  try {
    const [status, machines] = await Promise.all([
      request("/api/status"),
      request("/api/machines"),
    ]);
    state.status = status;
    state.machines = machines;
    renderStatus();
    renderMachines();
  } catch (error) {
    showToast(error.message);
  }
}

async function boot() {
  const config = await request("/api/config/machine-types");
  state.machineTypes = config.machine_types;
  renderMachineControls();
  await refresh();
  window.setInterval(refresh, 1000);
}

$("loadForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payload = {
      target_active: numberValue("targetActive"),
      spawn_rate_per_sec: numberValue("spawnRate"),
      machine_mix: machineMixPayload(),
      fault_probability_per_minute: numberValue("faultProbability") ?? 0,
    };
    const duration = payloadWithDuration("duration");
    const telemetry = numberValue("telemetryMs");
    if (duration) {
      payload.duration_seconds = duration;
    }
    if (telemetry !== null) {
      payload.telemetry_interval_ms = telemetry;
    }
    state.status = await request("/api/load", { method: "PUT", body: JSON.stringify(payload) });
    state.loadFormDirty = false;
    renderStatus({ syncForm: true });
    showToast("Load updated");
  } catch (error) {
    showToast(error.message);
  }
});

$("loadForm").addEventListener("input", () => {
  state.loadFormDirty = true;
});

$("manualForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payload = {
      count: numberValue("manualCount"),
      spawn_rate_per_sec: numberValue("manualSpawnRate"),
      fault_probability_per_minute: numberValue("manualFaultProbability") ?? 0,
    };
    const type = $("manualType").value;
    const duration = payloadWithDuration("manualDuration");
    if (type) {
      payload.machine_type = type;
    }
    if (duration) {
      payload.duration_seconds = duration;
    }
    const result = await request("/api/machines", { method: "POST", body: JSON.stringify(payload) });
    showToast(`Spawned ${result.created.length}`);
    await refresh();
  } catch (error) {
    showToast(error.message);
  }
});

$("stopButton").addEventListener("click", async () => {
  try {
    state.status = await request("/api/stop", { method: "POST" });
    state.loadFormDirty = false;
    renderStatus({ syncForm: true });
    showToast("Stopping machines");
  } catch (error) {
    showToast(error.message);
  }
});

document.querySelector(".tabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-view]");
  if (!button) {
    return;
  }
  state.view = button.dataset.view;
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab === button));
  renderMachines();
});

$("machineRows").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-break]");
  if (!button) {
    return;
  }
  try {
    await request(`/api/machines/${encodeURIComponent(button.dataset.break)}/break`, { method: "POST" });
    showToast("Machine broken");
    await refresh();
  } catch (error) {
    showToast(error.message);
  }
});

boot().catch((error) => showToast(error.message));
