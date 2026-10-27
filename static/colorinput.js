// Hex / RGB / CMYK input for the Pantone and Thread match pages.
// RGB and CMYK fill #hexInput with the colour they make, so the page's own matching is unchanged.
// CMYK is read as printed with the Coated FOGRA39 profile (static/cmyk-fogra39.json, made by
// make_cmyk_table.py); the plain formula is used only if that table cannot be loaded.
"use strict";
(function (root) {
  const C = root.ColorMath;
  const $ = (s) => document.querySelector(s);
  const FIELDS = { rgb: ["R", "G", "B"], cmyk: ["C", "M", "Y", "K"] };
  const MAX = { rgb: 255, cmyk: 100 };

  // the press table: Lab (relative colorimetric) and screen sRGB on a grid per ink
  let PRESS = null;
  const pressReady = fetch("/static/cmyk-fogra39.json").then((r) => r.json()).then((d) => {
    const bytes = (b64) => Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
    PRESS = { name: d.name, n: d.grid, lab: bytes(d.lab), rgb: bytes(d.rgb) };
  }).catch(() => { /* plain formula instead */ });

  // CMYK in percent -> 3 values, interpolated between the 16 surrounding grid points
  function pressLookup(table, cmyk) {
    const n = PRESS.n, t = cmyk.map((v) => (v / 100) * (n - 1));
    const i0 = t.map((v) => Math.min(Math.floor(v), n - 2)), f = t.map((v, j) => v - i0[j]);
    const out = [0, 0, 0];
    for (let corner = 0; corner < 16; corner++) {
      let w = 1, idx = 0;
      for (let j = 0; j < 4; j++) {
        const bit = (corner >> j) & 1;
        w *= bit ? f[j] : 1 - f[j];
        idx = idx * n + i0[j] + bit;
      }
      if (w) for (let ch = 0; ch < 3; ch++) out[ch] += w * table[idx * 3 + ch];
    }
    return out;
  }
  const pressLab = (cmyk) => { const v = pressLookup(PRESS.lab, cmyk); return [v[0] * 100 / 255, v[1] - 128, v[2] - 128]; };

  function setup(onChange) {
    const CI = { mode: "hex", values: { rgb: [228, 0, 43], cmyk: [0, 100, 81, 4] } };

    // the number boxes for each mode
    for (const mode of ["rgb", "cmyk"]) {
      const row = $(`#${mode}Row`);
      row.insertAdjacentHTML("afterbegin", FIELDS[mode].map((f, i) =>
        `<label class="ci-field"><span>${f}</span><input type="number" inputmode="numeric" min="0" max="${MAX[mode]}" step="1" data-i="${i}" aria-label="${f}">${mode === "cmyk" ? "<i>%</i>" : ""}</label>`).join(""));
      row.querySelectorAll("input").forEach((inp) => {
        inp.addEventListener("input", () => fromFields(mode));
        // pasting "228, 0, 43" or "0 100 81 4" into one box fills them all
        inp.addEventListener("paste", (e) => {
          const nums = (e.clipboardData?.getData("text") || "").match(/\d+(\.\d+)?/g);
          if (!nums || nums.length < FIELDS[mode].length) return;
          e.preventDefault();
          CI.values[mode] = nums.slice(0, FIELDS[mode].length).map((n) => clamp(+n, mode));
          fillFields(mode); fromFields(mode);
        });
      });
    }
    const clamp = (v, mode) => Math.min(MAX[mode], Math.max(0, Math.round(Number.isFinite(v) ? v : 0)));

    function fillFields(mode) {
      $(`#${mode}Row`).querySelectorAll("input").forEach((inp, i) => { inp.value = CI.values[mode][i]; });
    }
    function hexOf(mode) {
      const v = CI.values[mode];
      if (mode === "rgb") return C.rgbToHex(v);
      return C.rgbToHex(PRESS ? pressLookup(PRESS.rgb, v) : C.cmykToRgb(v));
    }
    function fromFields(mode) {
      const inputs = [...$(`#${mode}Row`).querySelectorAll("input")];
      if (inputs.some((inp) => inp.value === "")) return;     // still typing
      CI.values[mode] = inputs.map((inp) => clamp(+inp.value, mode));
      inputs.forEach((inp, i) => { if (+inp.value !== CI.values[mode][i]) inp.value = CI.values[mode][i]; });
      const hex = hexOf(mode);
      $(`#${mode}Row .ci-out`).innerHTML = `<span class="chip" style="background:${hex}"></span>${hex.toUpperCase()}`
        + (mode === "cmyk" ? `<span class="ci-profile">${PRESS ? "as printed: " + PRESS.name : "plain conversion (press profile not loaded)"}</span>` : "");
      $("#hexInput").value = hex.toUpperCase();
      onChange();
    }

    function setMode(mode, keep) {
      // start RGB or CMYK from the colour already entered
      if (mode !== "hex" && !keep) {
        const first = $("#hexInput").value.split(/[\s,;]+/).map(C.parseHex).find(Boolean);
        if (first) CI.values[mode] = mode === "rgb" ? C.hexToRgb(first) : C.rgbToCmyk(C.hexToRgb(first));
      }
      CI.mode = mode;
      document.querySelectorAll(".ci-modes button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
      $("#hexRow").hidden = mode !== "hex";
      $("#rgbRow").hidden = mode !== "rgb";
      $("#cmykRow").hidden = mode !== "cmyk";
      if (mode === "hex") { onChange(); $("#hexInput").focus(); return; }
      fillFields(mode); fromFields(mode);
      $(`#${mode}Row input`).focus();
    }
    document.querySelectorAll(".ci-modes button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

    const isCmyk = (hex) => CI.mode === "cmyk" && hex.toLowerCase() === hexOf("cmyk");
    // the CMYK typed in, shown with your colour (only for the colour it made)
    CI.note = (hex) => isCmyk(hex)
      ? `<div class="mono">CMYK ${CI.values.cmyk.join(", ")}${PRESS ? " · FOGRA39" : ""}</div>` : "";
    // the printed colour of the CMYK typed in, for matching against Pantone's measured Lab
    CI.printLab = (hex) => (PRESS && isCmyk(hex) ? pressLab(CI.values.cmyk) : null);
    // ?rgb=228,0,43 or ?cmyk=0,100,81,4 in the address
    CI.urlPart = () => (CI.mode === "hex" ? null : `${CI.mode}=${CI.values[CI.mode].join(",")}`);
    CI.fromURL = (q) => {
      for (const mode of ["rgb", "cmyk"]) {
        const v = q.get(mode)?.split(",").map(Number);
        if (v && v.length === FIELDS[mode].length && v.every(Number.isFinite)) {
          CI.values[mode] = v.map((n) => clamp(n, mode));
          $("#hexInput").value = hexOf(mode).toUpperCase();
          CI.start = mode;
          return true;
        }
      }
      return false;
    };
    CI.init = () => { if (CI.start) setMode(CI.start, true); };
    // once the press table is in, CMYK already on screen is converted again with it
    pressReady.then(() => { if (CI.mode === "cmyk" && PRESS) fromFields("cmyk"); });
    return CI;
  }

  root.ColorInput = { setup };
})(window);
