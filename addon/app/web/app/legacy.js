// Pieces of the 0.9 editor that the editor still uses, kept as they were: page reflow
// between orientations, breaking a widget apart, the widgets' own sensors,
// icon suggestions and the built-in presets.

export function reflowPageElements(p, toPortrait, disp) {
  const list = p && p.elements;
  if (!Array.isArray(list) || !list.length) return;

  // The canvas it's going to, from the add-on (elements.js DISPLAYS).
  const c = toPortrait ? disp.portrait : disp.landscape;
  const TW = c.w, TH = c.h;
  const safeH = c.h - c.band;
  const margin = c.margin;
  const usableW = TW - (margin * 2);

  // Group elements by type
  const grids = list.filter(e => e.type === "dynamic_grid");
  const icons = list.filter(e => e.type === "icon");
  const curves = list.filter(e => e.type === "curve");
  const lines = list.filter(e => e.type === "line");
  const numbers = list.filter(e => e.type === "number");
  const texts = list.filter(e => e.type === "text");

  if (grids.length) {
    grids.forEach(g => {
      g.x = margin;
      g.y = 16;
      g.w = usableW;
      g.h = safeH - 24;
    });
    return;
  }

  // Detect Clock page: single prominent time template + date
  const isClock = texts.some(t => String(t.value || "").includes("%H:%M") || String(t.value || "").includes("%I:%M"));

  // Detect 2-stat comparison page (e.g. temps: 2 numbers + 2 labels)
  const isTwoStat = (numbers.length === 2 && texts.length === 2) || (numbers.length === 2 && texts.length <= 3 && curves.length === 0);

  if (toPortrait) {
    // ==========================================
    // === REFLOW TO PORTRAIT (272w × 792h) ===
    // ==========================================
    if (isTwoStat) {
      // Two stacked cards with horizontal divider between them
      const sortedNums = [...numbers].sort((a, b) => a.x - b.x || a.y - b.y);
      const sortedTexts = [...texts].sort((a, b) => a.x - b.x || a.y - b.y);

      const cardH = Math.round((safeH - 40) / 2);
      const topMid = Math.round(cardH / 2);
      const botMid = cardH + 40 + Math.round(cardH / 2);

      // Card 1
      if (sortedTexts[0]) {
        sortedTexts[0].x = margin; sortedTexts[0].w = usableW; sortedTexts[0].align = "center";
        sortedTexts[0].y = Math.max(16, topMid - 60); sortedTexts[0].h = 36;
        if (sortedTexts[0].size && sortedTexts[0].size > 30) sortedTexts[0].size = 28;
      }
      if (sortedNums[0]) {
        sortedNums[0].x = margin; sortedNums[0].w = usableW; sortedNums[0].align = "center";
        sortedNums[0].y = topMid - 16; sortedNums[0].h = 92;
        if (sortedNums[0].size && sortedNums[0].size > 72) sortedNums[0].size = 68;
      }

      // Horizontal Divider
      const divLine = lines[0] || (lines.length ? lines[0] : null);
      if (divLine) {
        divLine.x = margin + 16; divLine.w = usableW - 32; divLine.h = 2;
        divLine.y = cardH + 18;
      }

      // Card 2
      if (sortedTexts[1]) {
        sortedTexts[1].x = margin; sortedTexts[1].w = usableW; sortedTexts[1].align = "center";
        sortedTexts[1].y = botMid - 60; sortedTexts[1].h = 36;
        if (sortedTexts[1].size && sortedTexts[1].size > 30) sortedTexts[1].size = 28;
      }
      if (sortedNums[1]) {
        sortedNums[1].x = margin; sortedNums[1].w = usableW; sortedNums[1].align = "center";
        sortedNums[1].y = botMid - 16; sortedNums[1].h = 92;
        if (sortedNums[1].size && sortedNums[1].size > 72) sortedNums[1].size = 68;
      }
      return;
    }

    if (isClock) {
      // Clock layout in portrait: Icon top, Time centered, Date below
      const timeEl = texts.find(t => String(t.value || "").includes("%H:%M") || String(t.value || "").includes("%I:%M"));
      const dateEl = texts.find(t => t !== timeEl);
      const iconEl = icons[0];

      const sections = [];
      if (iconEl) {
        const sz = Math.min(90, Math.round(TW * 0.32));
        iconEl.w = sz; iconEl.h = sz;
        iconEl.x = Math.round((TW - sz) / 2);
        sections.push({ el: iconEl, h: sz });
      }
      if (timeEl) {
        timeEl.x = margin; timeEl.w = usableW; timeEl.align = "center";
        timeEl.h = 96;
        timeEl.size = Math.min(timeEl.size || 88, 76);
        timeEl.bold = true;
        sections.push({ el: timeEl, h: 96 });
      }
      if (dateEl) {
        dateEl.x = margin; dateEl.w = usableW; dateEl.align = "center";
        dateEl.h = 42;
        dateEl.size = Math.min(dateEl.size || 32, 26);
        sections.push({ el: dateEl, h: 42 });
      }

      const totH = sections.reduce((s, x) => s + x.h, 0);
      const gap = Math.max(16, Math.min(36, Math.round((safeH - totH) / (sections.length + 1))));
      let yC = Math.max(margin, Math.round((safeH - (totH + gap * (sections.length - 1))) / 2));
      for (const s of sections) {
        s.el.y = yC;
        yC += s.h + gap;
      }
      return;
    }

    // Standard Hero Stat + Icon + Subtitle + Curve / Secondary
    const heroIcon = icons[0];
    const heroStat = numbers[0] || texts.find(t => (t.bold || (t.size || 0) >= 50)) || texts[0];
    const subtitle = texts.find(t => t !== heroStat && (t.size || 30) <= 36);
    const heroCurve = curves[0];
    const secondaries = [...numbers, ...texts].filter(e => e !== heroStat && e !== subtitle);

    const sections = [];

    // 1. Icon Section (Hero Visual)
    if (heroIcon) {
      const iconSide = Math.min(92, Math.max(64, Math.round(TW * 0.33)));
      heroIcon.w = iconSide; heroIcon.h = iconSide;
      heroIcon.x = Math.round((TW - iconSide) / 2);
      sections.push({ el: heroIcon, h: iconSide, gapAfter: 14 });
    }

    // 2. Hero Stat Section
    if (heroStat) {
      heroStat.x = margin; heroStat.w = usableW; heroStat.align = "center";
      heroStat.h = Math.min(100, Math.max(76, Math.round(TH * 0.12)));
      if (heroStat.size && heroStat.size > 72) heroStat.size = 68;
      sections.push({ el: heroStat, h: heroStat.h, gapAfter: 4 });
    }

    // 3. Subtitle Section
    if (subtitle) {
      subtitle.x = margin; subtitle.w = usableW; subtitle.align = "center";
      subtitle.h = 36;
      if (subtitle.size && subtitle.size > 28) subtitle.size = 26;
      sections.push({ el: subtitle, h: 36, gapAfter: 18 });
    }

    // 4. Divider Line (if lines exist or between stat and curve)
    if (lines.length > 0) {
      const lineEl = lines[0];
      lineEl.x = margin + 16; lineEl.w = usableW - 32; lineEl.h = 2;
      sections.push({ el: lineEl, h: 2, gapAfter: 18 });
    }

    // 5. Curve / Graph Section
    if (heroCurve) {
      heroCurve.x = margin; heroCurve.w = usableW;
      heroCurve.h = Math.min(150, Math.max(100, Math.round(TH * 0.18)));
      sections.push({ el: heroCurve, h: heroCurve.h, gapAfter: 16 });
    }

    // 6. Secondary Stats Section
    for (const sec of secondaries) {
      sec.x = margin; sec.w = usableW; sec.align = "center";
      sec.h = 36;
      if (sec.size && sec.size > 30) sec.size = 26;
      sections.push({ el: sec, h: 36, gapAfter: 12 });
    }

    // Cleanly distribute sections vertically within safe area
    const totalH = sections.reduce((sum, s) => sum + s.h, 0);
    const totalGaps = sections.reduce((sum, s, idx) => idx < sections.length - 1 ? sum + (s.gapAfter || 14) : sum, 0);
    const remSpace = safeH - (totalH + totalGaps);
    const extraPerGap = remSpace > 0 ? Math.min(18, Math.round(remSpace / (sections.length + 1))) : 0;
    let yC = Math.max(margin, Math.round((safeH - (totalH + totalGaps + extraPerGap * (sections.length - 1))) / 2));

    for (let i = 0; i < sections.length; i++) {
      const s = sections[i];
      s.el.y = Math.min(safeH - s.h, yC);
      yC += s.h + (s.gapAfter || 14) + extraPerGap;
    }

  } else {
    // ==========================================
    // === REFLOW TO LANDSCAPE (792w × 272h) ===
    // ==========================================
    if (isTwoStat) {
      // 2 horizontal columns with vertical divider
      const sortedNums = [...numbers].sort((a, b) => a.y - b.y || a.x - b.x);
      const sortedTexts = [...texts].sort((a, b) => a.y - b.y || a.x - b.x);
      const colW = Math.round((usableW - 40) / 2);
      const midX = margin + colW + 20;

      // Col 1 (left)
      if (sortedTexts[0]) {
        sortedTexts[0].x = margin + 16; sortedTexts[0].w = colW - 32; sortedTexts[0].align = "left";
        sortedTexts[0].y = 40; sortedTexts[0].h = 36; sortedTexts[0].size = 30;
      }
      if (sortedNums[0]) {
        sortedNums[0].x = margin + 10; sortedNums[0].w = colW - 20; sortedNums[0].align = "left";
        sortedNums[0].y = 86; sortedNums[0].h = 114;
      }

      // Vertical Divider
      const divLine = lines[0] || (lines.length ? lines[0] : null);
      if (divLine) {
        divLine.x = midX - 2; divLine.w = 4; divLine.y = 36; divLine.h = 160;
      }

      // Col 2 (right)
      if (sortedTexts[1]) {
        sortedTexts[1].x = midX + 24; sortedTexts[1].w = colW - 32; sortedTexts[1].align = "left";
        sortedTexts[1].y = 40; sortedTexts[1].h = 36; sortedTexts[1].size = 30;
      }
      if (sortedNums[1]) {
        sortedNums[1].x = midX + 18; sortedNums[1].w = colW - 20; sortedNums[1].align = "left";
        sortedNums[1].y = 86; sortedNums[1].h = 114;
      }
      return;
    }

    if (isClock) {
      const timeEl = texts.find(t => String(t.value || "").includes("%H:%M") || String(t.value || "").includes("%I:%M"));
      const dateEl = texts.find(t => t !== timeEl);
      const iconEl = icons[0];

      if (timeEl) {
        timeEl.x = margin + 8; timeEl.y = 20; timeEl.w = Math.round(usableW * 0.62);
        timeEl.h = 138; timeEl.size = 110; timeEl.bold = true; timeEl.align = "left";
      }
      if (dateEl) {
        dateEl.x = margin + 12; dateEl.y = 166; dateEl.w = Math.round(usableW * 0.65);
        dateEl.h = 44; dateEl.size = 36; dateEl.align = "left";
      }
      if (iconEl) {
        iconEl.w = 120; iconEl.h = 120;
        iconEl.x = TW - margin - 120; iconEl.y = 36;
      }
      return;
    }

    // Standard Landscape layout
    const heroIcon = icons[0];
    const heroStat = numbers[0] || texts.find(t => (t.bold || (t.size || 0) >= 50)) || texts[0];
    const subtitle = texts.find(t => t !== heroStat && (t.size || 30) <= 36);
    const heroCurve = curves[0];
    const secondaries = [...numbers, ...texts].filter(e => e !== heroStat && e !== subtitle);

    let leftCursor = margin;

    // 1. Icon on left
    if (heroIcon) {
      const iconSide = Math.min(116, Math.max(80, Math.round(TH * 0.44)));
      heroIcon.w = iconSide; heroIcon.h = iconSide;
      heroIcon.x = margin;
      heroIcon.y = Math.round((safeH - iconSide) / 2);
      leftCursor += iconSide + 20;
    }

    // 2. Middle column: Hero Stat + Subtitle
    const midW = heroCurve ? Math.round(usableW * 0.44) : (TW - margin - leftCursor);
    if (heroStat) {
      heroStat.x = leftCursor; heroStat.y = 28; heroStat.w = midW; heroStat.h = 126;
      heroStat.align = "left";
      if (heroStat.size && heroStat.size < 80) heroStat.size = 96;
    }
    if (subtitle) {
      subtitle.x = leftCursor + 4; subtitle.y = 164; subtitle.w = midW; subtitle.h = 42;
      subtitle.align = "left"; subtitle.size = 30;
    }

    // 3. Right column: Curve or Secondary Stat
    if (heroCurve) {
      const curveW = Math.min(280, Math.round(usableW * 0.38));
      heroCurve.x = TW - margin - curveW;
      heroCurve.y = 92;
      heroCurve.w = curveW;
      heroCurve.h = 90;
    }

    if (secondaries.length > 0) {
      const sec = secondaries[0];
      const secW = Math.min(300, Math.round(usableW * 0.38));
      sec.x = TW - margin - secW;
      sec.y = 164;
      sec.w = secW;
      sec.h = 42;
      sec.align = "right";
      sec.size = 28;
    }
  }
}

export const LEAGUE_TO_SLUG = {
  "soccer/eng.1": "premier_league",
  "premier_league": "premier_league",
  "epl": "premier_league",
  "soccer/uefa.champions": "champions_league",
  "champions_league": "champions_league",
  "ucl": "champions_league",
  "soccer/esp.1": "la_liga",
  "la_liga": "la_liga",
  "soccer/ger.1": "bundesliga",
  "bundesliga": "bundesliga",
  "soccer/ita.1": "serie_a",
  "serie_a": "serie_a",
  "soccer/usa.1": "mls",
  "mls": "mls",
  "basketball/nba": "nba",
  "nba": "nba",
  "basketball/wnba": "wnba",
  "wnba": "wnba",
  "football/nfl": "nfl",
  "nfl": "nfl",
  "football/college-football": "college_football",
  "baseball/mlb": "mlb",
  "mlb": "mlb",
  "hockey/nhl": "nhl",
  "nhl": "nhl"
};

export function getWidgetSensorId(el) {
  if (!el) return "";
  if (el.type === "sports_match") {
    const lg = String(el.league || "soccer/eng.1").trim().toLowerCase();
    const slug = LEAGUE_TO_SLUG[lg] || lg.replace(/[^a-z0-9]+/g, "_");
    return `sensor.epaper_sports_${slug}`;
  }
  if (el.type === "sports_racing") {
    const raw = String(el.series || "f1").trim().toLowerCase();
    const slug = ["fe", "formula_e", "formula-e", "formulae"].includes(raw) ? "fe"
      : ["nascar", "nascar-premier"].includes(raw) ? "nascar"
      : ["indycar", "irl"].includes(raw) ? "indycar" : "f1";
    return `sensor.epaper_racing_${slug}`;
  }
  if (el.type === "flight_tracker") {
    return "sensor.epaper_flights_overhead";
  }
  return "";
}

export function suggestIconForEntity(entityId, friendlyName = "") {
  const s = (entityId + " " + friendlyName).toLowerCase();
  if (s.includes("paw") || s.includes("cat") || s.includes("pet") || s.includes("dog")) return "mdi:paw";
  if (s.includes("bed") || s.includes("sleep") || s.includes("crib")) return "mdi:bed";
  if (s.includes("radiator") || s.includes("heater") || s.includes("heat") || s.includes("warm") || s.includes("blanket")) return "mdi:radiator";
  if (s.includes("floor") || s.includes("wall")) return "mdi:radiator";
  if (s.includes("light") || s.includes("lamp") || s.includes("spot")) return "mdi:lightbulb";
  if (s.includes("plug") || s.includes("outlet") || s.includes("socket")) return "mdi:power-socket-eu";
  if (s.includes("battery")) return "mdi:battery-charging";
  if (s.includes("solar") || s.includes("pv") || s.includes("sun")) return "mdi:white-balance-sunny";
  if (s.includes("temp") || s.includes("climate")) return "mdi:thermometer";
  if (s.includes("fan")) return "mdi:fan";
  if (s.includes("door") || s.includes("gate")) return "mdi:door";
  return "mdi:power";
}

export function explodeWidget(el) {
  if (!el) return [];
  const x = el.x || 0, y = el.y || 0, w = el.w || 760, h = el.h || 200;
  const sc = parseFloat(el.font_scale) || 1.0;
  const s = (v) => Math.max(10, Math.round(v * sc));
  const newEls = [];

  if (el.type === "weather_forecast") {
    const ent = el.entity || "weather.forecast_home";
    const mode = el.layout_mode || "auto";
    const isSplit = mode === "split" || (mode === "auto" && w >= 420 && w > h * 1.4);
    const leftW = isSplit ? Math.floor(w * 0.44) : w;

    newEls.push(
      { type: "icon", x: x + 8, y: y + 8, w: s(64), h: s(64), icon: "weather-partly-cloudy" },
      { type: "number", x: x + s(80), y: y + 4, w: Math.max(120, leftW - s(88)), h: s(74), size: s(64), weight: "black", entity: ent, show: "attribute", attribute: "temperature", format: "round", suffix: "°" },
      { type: "text", x: x + 8, y: y + s(86), w: leftW - 16, h: s(32), size: s(22), weight: "bold", entity: ent, show: "state", replace: { partlycloudy: "Partly Cloudy", clear_night: "Clear Night", rainy: "Rainy", sunny: "Sunny", cloudy: "Cloudy", pouring: "Heavy Rain", snowy: "Snowy", lightning_rainy: "Thunderstorm", windy: "Windy", fog: "Foggy" } },
      { type: "text", x: x + 8, y: y + s(126), w: Math.floor((leftW - 20) / 2), h: s(28), size: s(17), weight: "bold", entity: ent, show: "attribute", attribute: "humidity", format: "round", prefix: "HUM ", suffix: "%" },
      { type: "text", x: x + 12 + Math.floor((leftW - 20) / 2), y: y + s(126), w: Math.floor((leftW - 20) / 2), h: s(28), size: s(17), weight: "bold", entity: ent, show: "attribute", attribute: "wind_speed", format: "round", prefix: "WIND ", suffix: " km/h" }
    );
    if (isSplit && mode !== "hero_only") {
      newEls.push(
        { type: "line", x: x + leftW, y: y + 8, w: 2, h: h - 16, stroke: 2 },
        { type: "weather_forecast", x: x + leftW + 12, y: y, w: w - leftW - 12, h: h, entity: ent, layout_mode: "forecast_only", forecast_days: el.forecast_days || 4, font_scale: sc }
      );
    }
  } else if (el.type === "flight_tracker") {
    const ent = el.entity || "sensor.epaper_closest_aircraft";
    newEls.push(
      { type: "icon", x: x + 8, y: y + 10, w: s(40), h: s(40), icon: "mdi:airplane" },
      { type: "text", x: x + s(58), y: y + 6, w: Math.floor(w * 0.55), h: s(52), size: s(42), weight: "black", entity: ent, show: "state" },
      { type: "text", x: x + Math.floor(w * 0.62), y: y + 14, w: Math.floor(w * 0.36), h: s(32), size: s(22), weight: "bold", align: "right", entity: ent, show: "attribute", attribute: "country" },
      { type: "text", x: x + 8, y: y + s(64), w: w - 16, h: s(32), size: s(20), weight: "bold", entity: ent, show: "attribute", attribute: "model" },
      { type: "line", x: x + 8, y: y + s(102), w: w - 16, h: 2, stroke: 2 },
      { type: "text", x: x + 8, y: y + s(112), w: Math.floor(w / 3) - 12, h: s(18), size: s(12), weight: "bold", value: "DISTANCE" },
      { type: "number", x: x + 8, y: y + s(132), w: Math.floor(w / 3) - 12, h: s(40), size: s(30), weight: "black", entity: ent, show: "attribute", attribute: "distance_km", format: "1dp", suffix: " km" },
      { type: "text", x: x + Math.floor(w / 3) + 4, y: y + s(112), w: Math.floor(w / 3) - 12, h: s(18), size: s(12), weight: "bold", value: "ALTITUDE" },
      { type: "number", x: x + Math.floor(w / 3) + 4, y: y + s(132), w: Math.floor(w / 3) - 12, h: s(40), size: s(30), weight: "black", entity: ent, show: "attribute", attribute: "altitude_ft", format: "round", suffix: " ft" },
      { type: "text", x: x + Math.floor((w * 2) / 3) + 4, y: y + s(112), w: Math.floor(w / 3) - 12, h: s(18), size: s(12), weight: "bold", value: "GROUND SPEED" },
      { type: "number", x: x + Math.floor((w * 2) / 3) + 4, y: y + s(132), w: Math.floor(w / 3) - 12, h: s(40), size: s(30), weight: "black", entity: ent, show: "attribute", attribute: "speed_kts", format: "round", suffix: " kts" }
    );
  } else if (el.type === "calendar_agenda") {
    const ent = el.entity || "calendar.personal";
    newEls.push(
      { type: "icon", x: x + 8, y: y + 10, w: s(34), h: s(34), icon: "mdi:calendar-clock" },
      { type: "text", x: x + s(50), y: y + 12, w: w - s(58), h: s(30), size: s(20), weight: "black", entity: ent, show: "date_formatted", prefix: "UPCOMING · " },
      { type: "line", x: x + 8, y: y + s(48), w: w - 16, h: 3, stroke: 3 },
      { type: "text", x: x + 8, y: y + s(62), w: w - 16, h: s(46), size: s(32), weight: "black", entity: ent, show: "calendar_title" },
      { type: "text", x: x + 8, y: y + s(116), w: Math.floor(w * 0.5), h: s(28), size: s(18), weight: "bold", entity: ent, show: "days_until" },
      { type: "text", x: x + Math.floor(w * 0.5), y: y + s(116), w: Math.floor(w * 0.5) - 8, h: s(28), size: s(18), weight: "bold", align: "right", entity: ent, show: "attribute", attribute: "location" }
    );
  } else if (el.type === "sports_match") {
    const ent = el.entity || getWidgetSensorId(el);
    const colW = Math.floor(w * 0.35);
    const midW = w - colW * 2;
    newEls.push(
      { type: "text", x: x + 8, y: y + 6, w: Math.floor(w * 0.6), h: s(24), size: s(15), weight: "black", entity: ent, show: "attribute", attribute: "competition" },
      { type: "text", x: x + Math.floor(w * 0.6), y: y + 6, w: Math.floor(w * 0.4) - 8, h: s(24), size: s(15), weight: "black", align: "right", entity: ent, show: "attribute", attribute: "clock" },
      { type: "line", x: x + 8, y: y + s(34), w: w - 16, h: 2, stroke: 2 },
      { type: "text", x: x + 8, y: y + s(56), w: colW - 12, h: s(48), size: s(34), weight: "black", entity: ent, show: "attribute", attribute: "home_team" },
      { type: "text", x: x + colW, y: y + s(44), w: midW, h: s(64), size: s(52), weight: "black", align: "center", entity: ent, show: "state" },
      { type: "text", x: x + colW + midW + 4, y: y + s(56), w: colW - 12, h: s(48), size: s(34), weight: "black", align: "right", entity: ent, show: "attribute", attribute: "away_team" }
    );
  } else if (el.type === "sports_racing") {
    const ent = el.entity || getWidgetSensorId(el);
    newEls.push(
      { type: "icon", x: x + 8, y: y + 8, w: s(32), h: s(32), icon: "mdi:flag-checkered" },
      { type: "text", x: x + s(48), y: y + 10, w: Math.floor(w * 0.55), h: s(28), size: s(18), weight: "black", value: (el.title || "FORMULA 1 STANDINGS").toUpperCase() },
      { type: "text", x: x + Math.floor(w * 0.65), y: y + 10, w: Math.floor(w * 0.35) - 8, h: s(28), size: s(16), weight: "bold", align: "right", entity: ent, show: "attribute", attribute: "event_name" },
      { type: "line", x: x + 8, y: y + s(42), w: w - 16, h: 3, stroke: 3 },
      { type: "text", x: x + 8, y: y + s(56), w: w - 16, h: s(44), size: s(28), weight: "black", entity: ent, show: "state", prefix: "STATUS · " }
    );
  }

  return newEls;
}

export const CATEGORY_TERMS = {
  cat: ["cat", "paw", "dog", "pet", "bone"],
  paw: ["paw"],
  radiator: ["radiator", "heat", "fire", "warm", "blanket"],
  bed: ["bed", "sofa", "chair", "couch", "seat", "sleep"],
  power: ["power", "lightning", "socket", "outlet", "plug", "battery"],
  light: ["light", "lamp", "bulb", "brightness"],
  home: ["home", "house", "door", "window", "gate", "garage"],
  weather: ["weather", "sun", "cloud", "rain", "snowflake", "wind"],
  thermometer: ["thermometer", "temperature", "hvac", "climate"]
};

export const PRESET_ICONS = {
  event_countdown: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><path d="M12 14v4M10 16h4"/></svg>`,
  climate: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/></svg>`,
  solar: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>`,
  presence_door: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 20V6a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v14"/><path d="M2 20h20"/><circle cx="14" cy="12" r="1"/></svg>`,
  bin_day: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`,
  clock: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>`,
  dynamic_entities: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>`,
  calendar_month: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><circle cx="12" cy="15" r="1.5"/></svg>`,
  calendar_combo: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="8" height="16" rx="1.5"/><rect x="13" y="4" width="8" height="16" rx="1.5"/><line x1="15" y1="8" x2="19" y2="8"/><line x1="15" y1="12" x2="19" y2="12"/><line x1="15" y1="16" x2="19" y2="16"/></svg>`,
  weather_forecast: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>`,
  flight_tracker: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/></svg>`,
  flight_radar: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 1 0 10 10"/><path d="m12 12 5-5"/><circle cx="12" cy="12" r="2"/></svg>`,
  sports_racing: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>`,
  watch: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="14" rx="2"/><path d="M8 22h8M12 18v4"/><path d="m10 8 5 3-5 3z"/></svg>`,
  episode: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="14" rx="2"/><path d="M8 22h8M12 18v4"/><path d="m10 8 5 3-5 3z"/></svg>`,
  up_next: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="14" rx="2"/><path d="M8 22h8M12 18v4"/><path d="m10 8 5 3-5 3z"/></svg>`,
  sports_match: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m4.93 4.93 4.24 4.24M14.83 9.17l4.24-4.24M14.83 14.83l4.24 4.24M9.17 14.83l-4.24 4.24"/></svg>`
};

// The sensor a Jellyfin source makes; "watch" is the name it's seeded with.
const watchEnt = (ent) => ent || "sensor.epaper_watch";

export const PRESETS = [
  {
    id: "calendar_combo",
    title: "Month and agenda",
    desc: "This month's calendar on the left, the next events on the right.",
    asks: "calendar",
    makeElements: (ent) => [
      {
        type: "calendar_month",
        x: 16, y: 12, w: 368, h: 228,
        show_header: true,
        show_weekdays: true,
        first_weekday: 0,
        highlight_today: true,
        show_border: true,
        entity: ent || ""
      },
      {
        type: "calendar_agenda",
        x: 396, y: 12, w: 380, h: 228,
        title: "Coming up",
        max_events: 4,
        show_border: true,
        entity: ent || ""
      }
    ]
  },
  {
    id: "calendar_month",
    title: "Month",
    desc: "A wall calendar for this month, today marked, days with events dotted.",
    asks: "calendar",
    makeElements: (ent) => [
      {
        type: "calendar_month",
        x: 20, y: 14, w: 752, h: 222,
        show_header: true,
        show_weekdays: true,
        first_weekday: 0,
        highlight_today: true,
        show_border: true,
        entity: ent || ""
      }
    ]
  },
  {
    id: "weather_forecast",
    title: "Weather",
    desc: "Now and the next four days, from your Home Assistant weather.",
    asks: "weather",
    makeElements: (ent) => [
      {
        type: "weather_forecast",
        x: 18, y: 14, w: 756, h: 222,
        entity: ent || "weather.forecast_home",
        show_border: true
      }
    ]
  },
  {
    id: "flight_tracker",
    title: "Plane overhead",
    desc: "The nearest plane: flight, airline, height, speed and distance. Only shows while one is near.",
    asks: "",
    tier: "when",
    show_if: "{{ states('sensor.epaper_flights_overhead') | int(0) > 0 }}",
    makeElements: () => [
      {
        type: "flight_tracker",
        style: "card",
        x: 18, y: 14, w: 756, h: 222,
        radius: 35,
        auto_window: true,
        show_border: true
      }
    ]
  },
  {
    id: "flight_radar",
    title: "Planes on radar",
    desc: "A radar of the planes around you, with the nearest one's details. Only shows while one is near.",
    asks: "",
    tier: "when",
    show_if: "{{ states('sensor.epaper_flights_overhead') | int(0) > 0 }}",
    makeElements: () => [
      {
        type: "flight_tracker",
        style: "split",
        x: 18, y: 14, w: 756, h: 222,
        radius: 35,
        auto_window: true,
        show_border: true
      }
    ]
  },
  {
    id: "watch",
    title: "New to watch",
    desc: "The newest thing you haven't watched, and how much is new. Steps through each one. Only shows while there's something new.",
    asks: "jellyfin",
    tier: "when",
    showIf: (ent) => `{{ states('${watchEnt(ent)}_count') | int(0) > 0 }}`,
    makeElements: (ent) => [
      { type: "text", value: "new to watch", size: 26, bold: false, x: 40, y: 28, w: 300, h: 36, align: "left" },
      { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "detail", size: 26, bold: false, x: 452, y: 28, w: 300, h: 36, align: "right" },
      { type: "text", entity: watchEnt(ent), x: 40, y: 74, w: 712, h: 150, align: "left" }
    ]
  },
  {
    id: "episode",
    title: "Episode card",
    desc: "One new thing at a time: its name, which episode (or a film's year and length), and when it arrived.",
    asks: "jellyfin",
    tier: "when",
    showIf: (ent) => `{{ states('${watchEnt(ent)}_count') | int(0) > 0 }}`,
    makeElements: (ent) => [
      { type: "text", entity: watchEnt(ent), x: 40, y: 22, w: 712, h: 96, align: "left" },
      { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "about", size: 34, bold: false, x: 40, y: 128, w: 712, h: 46, align: "left" },
      { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "added_ago", prefix: "added ", size: 26, bold: false, x: 40, y: 188, w: 420, h: 36, align: "left" }
    ]
  },
  {
    id: "up_next",
    title: "Up next",
    desc: "Everything new on one screen: each name, its episode or count, and when it arrived.",
    asks: "jellyfin",
    tier: "when",
    showIf: (ent) => `{{ states('${watchEnt(ent)}_count') | int(0) > 0 }}`,
    makeElements: (ent) => [
      { type: "text", value: "up next", size: 26, bold: false, x: 40, y: 18, w: 300, h: 34, align: "left" },
      { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "count", suffix: " new", size: 26, bold: false, x: 452, y: 18, w: 300, h: 34, align: "right" },
      { type: "text", entity: watchEnt(ent), show: "attribute", attribute: "up_next", wrap: true, size: 26, bold: false, x: 40, y: 68, w: 712, h: 160, align: "left" }
    ]
  },
  {
    id: "sports_racing",
    title: "Formula 1",
    desc: "The top ten during a race weekend, with gaps and tyres; the next race the rest of the time.",
    asks: "",
    tier: "when",
    show_if: "{{ is_state('sensor.epaper_racing_f1', 'active') }}",
    makeElements: (ent) => [
      {
        type: "sports_racing",
        series: "f1",
        entity: ent || "",
        window_mode: "session",
        pre_buffer_hours: 2,
        post_buffer_hours: 2,
        auto_window: true,
        x: 18, y: 14, w: 756, h: 222,
        show_border: true
      }
    ]
  },
  {
    id: "sports_match",
    title: "Match score",
    desc: "The live score, clock and scorers. Shows on match days, from before kick-off to after the whistle.",
    asks: "",
    tier: "when",
    show_if: "{{ is_state('sensor.epaper_sports_premier_league', 'active') }}",
    makeElements: (ent) => [
      {
        type: "sports_match",
        league: "soccer/eng.1",
        team: "",
        entity: ent || "",
        pre_buffer_hours: 2,
        post_buffer_hours: 2,
        auto_window: true,
        x: 18, y: 14, w: 756, h: 222,
        show_border: true
      }
    ]
  },
  {
    id: "dynamic_entities",
    title: "What's on",
    desc: "Up to eight devices, showing only the ones that are on right now.",
    asks: "",
    tier: "when",
    makeElements: (ent) => [
      {
        type: "dynamic_grid",
        x: 20, y: 16, w: 752, h: 214,
        header_icon: "mdi:lightning-bolt",
        header_title: "On now",
        filter_state: "on",
        layout_mode: "grid",
        show_labels: "both",
        icon_size: "auto",
        secondary_mode: "runtime",
        items: [
          { entity: ent || "", name: "Spot 1", icon: "mdi:radiator" },
          { entity: "", name: "Spot 2", icon: "mdi:radiator" },
          { entity: "", name: "Spot 3", icon: "mdi:paw" },
          { entity: "", name: "Spot 4", icon: "mdi:bed" }
        ]
      }
    ]
  },
  {
    id: "event_countdown",
    title: "Countdown",
    desc: "Days until the next event in a calendar, and its date.",
    asks: "calendar",
    makeElements: (ent) => [
      { type: "icon", icon: "mdi:calendar-clock", x: 32, y: 40, w: 110, h: 110 },
      { type: "number", entity: ent || "", show: "days_until",
        suffix: " days", decimals: 0, x: 160, y: 24, w: 340, h: 130, align: "left" },
      { type: "text", value: "days until event", size: 30, bold: false, x: 164, y: 166, w: 320, h: 42, align: "left" },
      { type: "text", entity: ent || "", show: "date_formatted",
        prefix: "date: ", format: "day_date", size: 28, bold: false, x: 450, y: 166, w: 300, h: 42, align: "right" }
    ]
  },
  {
    id: "climate",
    title: "Room temperature",
    desc: "A temperature with a 24-hour curve.",
    asks: "sensor",
    makeElements: (ent) => [
      { type: "icon", icon: "mdi:thermometer", x: 32, y: 44, w: 116, h: 116 },
      { type: "number", entity: ent || "", show: "state",
        suffix: " °C", decimals: 1, x: 160, y: 30, w: 320, h: 128, align: "left" },
      { type: "text", value: "room climate", size: 30, bold: false, x: 164, y: 170, w: 320, h: 40, align: "left" },
      { type: "curve", entity: ent || "", hours: 24, x: 490, y: 100, w: 270, h: 86 }
    ]
  },
  {
    id: "solar",
    title: "Solar today",
    desc: "What the panels made today, with a 24-hour curve.",
    asks: "sensor",
    makeElements: (ent) => [
      { type: "icon", icon: "mdi:white-balance-sunny", x: 32, y: 44, w: 116, h: 116 },
      { type: "number", entity: ent || "", show: "state",
        suffix: " kWh", decimals: 1, x: 160, y: 30, w: 310, h: 128, align: "left" },
      { type: "text", value: "produced today", size: 30, bold: false, x: 164, y: 170, w: 320, h: 40, align: "left" },
      { type: "curve", entity: ent || "", hours: 24, x: 490, y: 100, w: 270, h: 86 }
    ]
  },
  {
    id: "presence_door",
    title: "Door or pet",
    desc: "Open or closed, in or out, and since when.",
    asks: "binary_sensor",
    makeElements: (ent) => [
      { type: "icon", icon: "mdi:door", x: 32, y: 44, w: 116, h: 116 },
      { type: "text", entity: ent || "", show: "state",
        replace: { "on": "Open", "off": "Closed" },
        size: 80, bold: true, x: 164, y: 30, w: 360, h: 128, align: "left" },
      { type: "text", entity: ent || "", show: "last_changed",
        format: "relative", prefix: "since ", size: 30, bold: false, x: 164, y: 170, w: 420, h: 40, align: "left" }
    ]
  },
  {
    id: "bin_day",
    title: "Bin day",
    desc: "Days until collection, and which bin.",
    asks: "calendar",
    makeElements: (ent) => [
      { type: "icon", icon: "mdi:trash-can", x: 32, y: 40, w: 110, h: 110 },
      { type: "number", entity: ent || "", show: "days_until",
        suffix: " days", decimals: 0, x: 160, y: 24, w: 340, h: 130, align: "left" },
      { type: "text", value: "until collection", size: 30, bold: false, x: 164, y: 166, w: 320, h: 42, align: "left" },
      { type: "text", entity: ent || "", show: "calendar_title",
        prefix: "type: ", size: 28, bold: false, x: 450, y: 166, w: 300, h: 42, align: "right" }
    ]
  },
  {
    id: "clock",
    title: "Clock",
    desc: "The time, very large, and today's date.",
    asks: "",
    makeElements: () => [
      { type: "text", value: "{{ now().strftime('%H:%M') }}", size: 110, bold: true, x: 40, y: 20, w: 450, h: 140, align: "left" },
      { type: "text", value: "{{ now().strftime('%A, %-d %B') }}", size: 36, bold: false, x: 44, y: 168, w: 500, h: 46, align: "left" },
      { type: "icon", icon: "mdi:clock-outline", x: 620, y: 40, w: 120, h: 120 }
    ]
  },
  {
    id: "energy_gauges",
    title: "Battery and solar",
    desc: "Home battery and house load as gauges, with today's solar as bars.",
    asks: "sensor",
    makeElements: (ent) => [
      { type: "box", x: 18, y: 14, w: 356, h: 218, fill: "outline", radius: 14, thickness: 3 },
      { type: "text", value: "ENERGY & STORAGE", size: 18, bold: true, invert: true, radius: 8, x: 34, y: 28, w: 210, h: 32, align: "center" },
      { type: "bar", entity: ent || "sensor.battery", title: "HOME BATTERY", bar_style: "segmented", segments: 10, min_val: 0, max_val: 100, suffix: "%", decimals: 0, show_label: true, x: 34, y: 74, w: 324, h: 66 },
      { type: "bar", entity: "sensor.grid_load", title: "HOUSE LOAD", bar_style: "solid", min_val: 0, max_val: 5000, suffix: " W", decimals: 0, show_label: true, x: 34, y: 152, w: 324, h: 64 },
      { type: "bar_chart", entity: ent || "sensor.solar_power", title: "24H GENERATION", hours: 24, bars: 12, show_labels: true, show_border: true, x: 390, y: 14, w: 384, h: 218 }
    ]
  },
  {
    id: "guest_wifi",
    title: "Guest Wi-Fi",
    desc: "A code guests scan with their phone camera to join your Wi-Fi.",
    asks: "",
    makeElements: () => [
      { type: "box", x: 18, y: 14, w: 756, h: 218, fill: "outline", radius: 16, thickness: 3 },
      { type: "icon", icon: "mdi:wifi", invert: true, radius: 14, x: 42, y: 38, w: 72, h: 72 },
      { type: "text", value: "GUEST WI-FI", size: 42, bold: true, x: 132, y: 36, w: 400, h: 52, align: "left" },
      { type: "text", value: "Point your phone camera at the QR code to connect automatically.", size: 22, bold: false, x: 132, y: 94, w: 410, h: 64, align: "left" },
      { type: "text", value: "NETWORK: MyGuestWiFi", size: 20, bold: true, pill: true, radius: 8, x: 42, y: 172, w: 310, h: 38, align: "center" },
      { type: "qr", qr_mode: "wifi", wifi_ssid: "MyGuestWiFi", wifi_password: "secretpassword", wifi_auth: "WPA", title: "SCAN TO JOIN", x: 568, y: 24, w: 184, h: 198 }
    ]
  }
];

PRESET_ICONS.energy_gauges = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="16" height="10" rx="2"/><line x1="22" y1="11" x2="22" y2="13"/><line x1="6" y1="10" x2="6" y2="14"/><line x1="10" y1="10" x2="10" y2="14"/></svg>`;
PRESET_ICONS.guest_wifi = `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3h-3zM18 18h3v3h-3z"/></svg>`;
