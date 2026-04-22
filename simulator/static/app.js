const state = {
  machineTypes: [],
  status: null,
  machines: { backends: [], active: [], recent: [] },
  backends: [],
  view: "active",
  loadFormDirty: false,
};

const $ = (id) => document.getElementById(id);

function formatDuration(machine) {
  const seconds = Number(machine.duration_seconds || 0);
  return `${seconds.toFixed(1)}s`;
}

function numberValue(id) {
  const el = $(id);
  if (!el) {
    return null;
  }
  const raw = el.value;
  if (raw === "") {
    return null;
  }
  return Number(raw);
}

function stateBadge(machine) {
  const map = {
    completed: { letter: "c", className: "completed" },
    broken: { letter: "b", className: "broken" },
    failed: { letter: "f", className: "failed" },
    running: { letter: "r", className: "running" },
    stopping: { letter: "s", className: "stopping" },
    starting: { letter: "s", className: "starting" },
  };

  const item = map[machine.state] || map.running;
  return `<span class="state-badge ${item.className}" title="${machine.state}">${item.letter}</span>`;
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
    const input = $(`mix-${type.name}`);
    if (!input) {
      return;
    }
    const value = Number(input.value);
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
  const root = $("machineTables");
  root.replaceChildren();

  const machines = state.machines[state.view] || [];
  const backends = state.backends.length
    ? [...state.backends]
    : [...new Set(machines.map((m) => m.backend_addr).filter(Boolean))];

  const grouped = new Map(backends.map((b) => [b, []]));

  machines.forEach((machine) => {
    const backend = machine.backend_addr || "unknown";
    if (!grouped.has(backend)) {
      grouped.set(backend, []);
    }
    grouped.get(backend).push(machine);
  });

  backends.forEach((backend) => {
    const items = grouped.get(backend) || [];

    const card = document.createElement("section");
    card.className = "backend-card";

    card.innerHTML = `
      <div class="backend-head">
        <h3>${backend}</h3>
        <span>${items.length}</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Type</th>
              <th>State</th>
              <th>Age</th>
              <th>Dur</th>
              <th>Max</th>
              <th></th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    `;

    const tbody = card.querySelector("tbody");

    if (items.length === 0) {
      const row = document.createElement("tr");
      row.innerHTML = `<td colspan="6" class="empty-row">No machines</td>`;
      tbody.append(row);
    } else {
      items.forEach((machine) => {
        const row = document.createElement("tr");
        const canBreak =
          state.view === "active" &&
          !["broken", "failed", "stopping"].includes(machine.state);

        row.innerHTML = `
          <td>${machine.machine_type}</td>
          <td>${stateBadge(machine)}</td>
          <td>${formatAge(machine)}</td>
          <td>${formatDuration(machine)}</td>
          <td>${machine.max_duration_seconds ?? "-"}</td>
          <td>${
            canBreak
              ? `<button class="quiet danger-button" data-break="${machine.machine_id}">Break</button>`
              : ""
          }</td>
        `;
        tbody.append(row);
      });
    }

    root.append(card);
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
    state.backends = machines.backends || [];
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
    };
    
    const duration = payloadWithDuration("duration");
    const telemetry = numberValue("telemetryMs");

    if (duration) {
      payload.duration_seconds = duration;
    }
    if (telemetry !== null) {
      payload.telemetry_interval_ms = telemetry;
    }

    state.status = await request("/api/load", {
      method: "PUT",
      body: JSON.stringify(payload),
    });

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
    };

    const type = $("manualType").value;
    const duration = payloadWithDuration("manualDuration");
    const maxDuration = numberValue("manualMaxDuration");
    if (duration && maxDuration !== null && maxDuration < duration.max) {
      showToast("Warning: max dur is below duration");
    }
    if (type) {
      payload.machine_type = type;
    }
    if (duration) {
      payload.duration_seconds = duration;
    }
    if (maxDuration !== null) {
      payload.max_duration_seconds = maxDuration;
    }

    const result = await request("/api/machines", {
      method: "POST",
      body: JSON.stringify(payload),
    });

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

$("machineTables").addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-break]");
  if (!btn) {
    return;
  }

  try {
    await request(`/api/machines/${encodeURIComponent(btn.dataset.break)}/break`, {
      method: "POST",
    });
    showToast("Machine broken");
    await refresh();
  } catch (error) {
    showToast(error.message);
  }
});

boot().catch((error) => showToast(error.message));