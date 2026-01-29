const els = {
  speed: document.getElementById('speed'),
  speedBig: document.getElementById('speed_big'),
  upper: document.getElementById('upper_speed'),
  speedMeas: document.getElementById('speed_meas'),
  throttle: document.getElementById('throttle'),
  driveMode: document.getElementById('drive_mode'),
  soc: document.getElementById('soc'),
  tb: document.getElementById('tb'),
  ibatt: document.getElementById('ibatt'),
  vbatt: document.getElementById('vbatt'),
  battV: document.getElementById('batt_v'),
  battA: document.getElementById('batt_a'),
  socSmall: document.getElementById('soc_small'),
  packW: document.getElementById('pack_w'),
  motorW: document.getElementById('motor_w'),
  motorA: document.getElementById('motor_a'),
  solarW: document.getElementById('solar_w'),
  speedKmh: document.getElementById('speed_kmh'),
  wheelW: document.getElementById('wheel_w'),
  sKm: document.getElementById('s_km'),
  ghi: document.getElementById('ghi'),
  tcell: document.getElementById('tcell'),
  tamb: document.getElementById('tamb'),
  wind: document.getElementById('wind'),
  slope: document.getElementById('slope'),
  planDt: document.getElementById('plan_dt'),
  lowerDt: document.getElementById('lower_dt'),
  forecastK: document.getElementById('forecast_k'),
  secNext: document.getElementById('sec_next'),
  sysState: document.getElementById('sys_state'),
  sysDiag: document.getElementById('sys_diag'),
  mpcState: document.getElementById('mpc_state'),
  health: document.getElementById('health'),
  clock: document.getElementById('clock'),
  socRing: document.getElementById('socRing'),
  mpcBadge: document.getElementById('mpc_badge'),
  driveBadge: document.getElementById('drive_badge'),
};

const canvases = {
  speed: document.getElementById('speedCanvas'),
  throttle: document.getElementById('throttleCanvas'),
  plan: document.getElementById('planCanvas'),
  lower: document.getElementById('lowerCanvas'),
  battery: document.getElementById('batteryCanvas'),
  motor: document.getElementById('motorCanvas'),
  solar: document.getElementById('solarCanvas'),
  speedPower: document.getElementById('speedPowerCanvas'),
};

const history = {
  speed: [],
  upper: [],
  throttle: [],
  soc: [],
  battV: [],
  battA: [],
  packW: [],
  motorW: [],
  motorA: [],
  solarW: [],
  wheelW: [],
  max: 900,
};

function fmt(val, digits = 1) {
  if (val === null || val === undefined || !Number.isFinite(val)) return '--';
  return val.toFixed(digits);
}

function pushHistory(arr, val) {
  if (!Number.isFinite(val)) return;
  arr.push(val);
  if (arr.length > history.max) arr.shift();
}

function drawPlot(canvas, seriesList, colors) {
  const ctx = canvas.getContext('2d');
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (w === 0 || h === 0) return;
  canvas.width = w;
  canvas.height = h;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = 'rgba(10,14,20,0.8)';
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = 'rgba(255,255,255,0.08)';
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const y = (h / 4) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
  let min = Infinity;
  let max = -Infinity;
  seriesList.forEach((s) => {
    s.forEach((v) => {
      min = Math.min(min, v);
      max = Math.max(max, v);
    });
  });
  if (!Number.isFinite(min) || !Number.isFinite(max)) return;
  if (Math.abs(max - min) < 1e-6) {
    max += 1;
    min -= 1;
  }
  seriesList.forEach((series, idx) => {
    if (series.length < 2) return;
    ctx.strokeStyle = colors[idx] || '#fff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    series.forEach((v, i) => {
      const x = (i / (series.length - 1)) * (w - 6) + 3;
      const y = h - ((v - min) / (max - min)) * (h - 10) - 5;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
}

function updateClock() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const ss = String(now.getSeconds()).padStart(2, '0');
  els.clock.textContent = `${hh}:${mm}:${ss}`;
}

function applyState(data) {
  const vLower = data.speed_cmd_kmh;
  const vUpper = data.upper_speed_cmd_kmh;
  const vMeas = data.speed_meas_kmh;
  const throttle = data.throttle_cmd_pct;
  let soc = data.soc;
  if (Number.isFinite(soc) && soc > 1.5) soc = soc / 100.0;

  els.speed.textContent = fmt(vLower, 1);
  els.speedBig.textContent = fmt(vLower, 0);
  els.upper.textContent = fmt(vUpper, 1);
  els.speedMeas.textContent = fmt(vMeas, 1);
  els.throttle.textContent = fmt(throttle, 1);
  els.driveMode.textContent = data.drive_mode || '--';
  els.soc.textContent = fmt(soc * 100, 1);
  els.tb.textContent = fmt(data.Tb_C, 1);
  els.ibatt.textContent = fmt(data.batt_current_a, 1);
  els.vbatt.textContent = fmt(data.batt_voltage_v, 1);
  els.battV.textContent = fmt(data.batt_voltage_v, 1);
  els.battA.textContent = fmt(data.batt_current_a, 1);
  els.socSmall.textContent = fmt(soc * 100, 1);
  els.packW.textContent = fmt(data.pack_w, 0);
  els.motorW.textContent = fmt(data.motor_w, 0);
  els.motorA.textContent = fmt(data.motor_a, 1);
  els.solarW.textContent = fmt(data.solar_w, 0);
  els.speedKmh.textContent = fmt(vLower, 1);
  els.wheelW.textContent = fmt(data.wheel_w, 0);
  els.sKm.textContent = fmt(data.s_km, 1);
  els.ghi.textContent = fmt(data.G_poa, 0);
  els.tcell.textContent = fmt(data.Tcell_C, 1);
  els.tamb.textContent = fmt(data.Tamb_C, 1);
  els.wind.textContent = fmt(data.headwind_ms, 1);
  els.slope.textContent = fmt(data.slope_pct, 2);
  els.planDt.textContent = fmt(data.plan_dt, 0);
  els.lowerDt.textContent = fmt(data.lower_dt, 2);
  els.forecastK.textContent = fmt(data.forecast_k, 0);
  els.secNext.textContent = fmt(data.sec_to_next, 0);
  els.sysState.textContent = data.system_state || '--';
  els.sysDiag.textContent = data.system_diag || '--';
  els.mpcState.textContent = data.mpc_state || '--';
  els.health.textContent = fmt(data.system_health, 2);

  els.socRing.style.setProperty('--soc', Math.max(0, Math.min(1, soc || 0)));
  els.mpcBadge.textContent = data.mpc_state || 'MPC';
  els.driveBadge.textContent = data.drive_mode || 'DRIVE';

  pushHistory(history.speed, vLower);
  pushHistory(history.upper, vUpper);
  pushHistory(history.throttle, throttle);
  pushHistory(history.soc, (soc || 0) * 100);
  pushHistory(history.battV, data.batt_voltage_v);
  pushHistory(history.battA, data.batt_current_a);
  pushHistory(history.packW, data.pack_w);
  pushHistory(history.motorW, data.motor_w);
  pushHistory(history.motorA, data.motor_a);
  pushHistory(history.solarW, data.solar_w);
  pushHistory(history.wheelW, data.wheel_w);

  drawPlot(canvases.speed, [history.speed, history.upper], ['#ff2d2d', '#2de2e6']);
  drawPlot(canvases.throttle, [history.throttle], ['#f7c14a']);
  drawPlot(canvases.battery, [history.battV, history.battA, history.soc], ['#2de2e6', '#f7c14a', '#ff2d2d']);
  drawPlot(canvases.motor, [history.motorW, history.motorA], ['#ff2d2d', '#2de2e6']);
  drawPlot(canvases.solar, [history.solarW], ['#f7c14a']);
  drawPlot(canvases.speedPower, [history.speed, history.wheelW], ['#2de2e6', '#ff2d2d']);

  if (Array.isArray(data.plan_upper)) {
    drawPlot(canvases.plan, [data.plan_upper], ['#2de2e6']);
  }
  if (Array.isArray(data.plan_lower)) {
    drawPlot(canvases.lower, [data.plan_lower], ['#ff2d2d']);
  }
}

async function fetchState() {
  try {
    const res = await fetch('/api/state', { cache: 'no-store' });
    const data = await res.json();
    applyState(data);
  } catch (err) {
    // ignore fetch errors
  }
}

setInterval(fetchState, 200);
setInterval(updateClock, 1000);
updateClock();
