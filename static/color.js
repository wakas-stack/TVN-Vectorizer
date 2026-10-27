// Colour maths for the Pantone page: sRGB <-> CIE Lab (D50, as in the Pantone books) and CIEDE2000.
"use strict";
(function (root) {
  // sRGB primaries adapted to D50 with Bradford (Lindbloom), and the inverse
  const RGB_TO_XYZ = [[0.4360747, 0.3850649, 0.1430804], [0.2225045, 0.7168786, 0.0606169], [0.0139322, 0.0971045, 0.7141733]];
  const XYZ_TO_RGB = [[3.1338561, -1.6168667, -0.4906146], [-0.9787684, 1.9161415, 0.0334540], [0.0719453, -0.2289914, 1.4052427]];
  const WHITE = [0.96422, 1.0, 0.82521];
  const EPS = 216 / 24389, KAPPA = 24389 / 27;

  const mul = (m, v) => m.map((r) => r[0] * v[0] + r[1] * v[1] + r[2] * v[2]);
  const toLinear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const fromLinear = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

  function parseHex(s) {
    const m = String(s).trim().replace(/^#/, "").match(/^([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (!m) return null;
    let h = m[1].toLowerCase();
    if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    return "#" + h;
  }
  const hexToRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const rgbToHex = (rgb) => "#" + rgb.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

  // CMYK in percent, by the plain device formula (no press profile)
  const cmykToRgb = ([c, m, y, k]) => [c, m, y].map((v) => Math.round(255 * (1 - v / 100) * (1 - k / 100)));
  function rgbToCmyk(rgb) {
    const [r, g, b] = rgb.map((v) => v / 255), k = 1 - Math.max(r, g, b);
    if (k >= 1) return [0, 0, 0, 100];
    return [...[r, g, b].map((v) => Math.round(((1 - v - k) / (1 - k)) * 100)), Math.round(k * 100)];
  }

  function rgbToLab(rgb) {
    const xyz = mul(RGB_TO_XYZ, rgb.map((v) => toLinear(v / 255)));
    const f = xyz.map((v, i) => { const t = v / WHITE[i]; return t > EPS ? Math.cbrt(t) : (KAPPA * t + 16) / 116; });
    return [116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])];
  }

  // returns { rgb: [0..255]x3 clipped, inGamut }
  function labToRgb(lab) {
    const [L, a, b] = lab;
    const fy = (L + 16) / 116, fx = fy + a / 500, fz = fy - b / 200;
    const inv = (f) => (f ** 3 > EPS ? f ** 3 : (116 * f - 16) / KAPPA);
    const xyz = [inv(fx) * WHITE[0], (L > KAPPA * EPS ? fy ** 3 : L / KAPPA) * WHITE[1], inv(fz) * WHITE[2]];
    const lin = mul(XYZ_TO_RGB, xyz);
    const inGamut = lin.every((v) => v >= -0.001 && v <= 1.001);
    const rgb = lin.map((v) => Math.min(255, Math.max(0, fromLinear(Math.min(1, Math.max(0, v))) * 255)));
    return { rgb, inGamut };
  }

  // CIEDE2000 (Sharma, Wu & Dalal 2005)
  function deltaE2000(l1, l2) {
    const [L1, a1, b1] = l1, [L2, a2, b2] = l2;
    const rad = Math.PI / 180, deg = 180 / Math.PI;
    const C1 = Math.hypot(a1, b1), C2 = Math.hypot(a2, b2), Cb = (C1 + C2) / 2;
    const G = 0.5 * (1 - Math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)));
    const a1p = (1 + G) * a1, a2p = (1 + G) * a2;
    const C1p = Math.hypot(a1p, b1), C2p = Math.hypot(a2p, b2);
    const h = (b, a) => { if (b === 0 && a === 0) return 0; const v = Math.atan2(b, a) * deg; return v < 0 ? v + 360 : v; };
    const h1p = h(b1, a1p), h2p = h(b2, a2p);
    const dLp = L2 - L1, dCp = C2p - C1p;
    let dhp = 0;
    if (C1p * C2p !== 0) { dhp = h2p - h1p; if (dhp > 180) dhp -= 360; else if (dhp < -180) dhp += 360; }
    const dHp = 2 * Math.sqrt(C1p * C2p) * Math.sin((dhp / 2) * rad);
    const Lbp = (L1 + L2) / 2, Cbp = (C1p + C2p) / 2;
    let hbp = h1p + h2p;
    if (C1p * C2p !== 0) {
      if (Math.abs(h1p - h2p) <= 180) hbp /= 2;
      else hbp = h1p + h2p < 360 ? (hbp + 360) / 2 : (hbp - 360) / 2;
    }
    const T = 1 - 0.17 * Math.cos((hbp - 30) * rad) + 0.24 * Math.cos(2 * hbp * rad)
      + 0.32 * Math.cos((3 * hbp + 6) * rad) - 0.2 * Math.cos((4 * hbp - 63) * rad);
    const dTheta = 30 * Math.exp(-(((hbp - 275) / 25) ** 2));
    const Rc = 2 * Math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7));
    const Sl = 1 + (0.015 * (Lbp - 50) ** 2) / Math.sqrt(20 + (Lbp - 50) ** 2);
    const Sc = 1 + 0.045 * Cbp, Sh = 1 + 0.015 * Cbp * T;
    const Rt = -Math.sin(2 * dTheta * rad) * Rc;
    return Math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh));
  }

  function verdict(de) {
    if (de < 1) return { label: "Same", tone: "same", text: "no visible difference" };
    if (de < 2) return { label: "Near identical", tone: "close", text: "visible only side by side, to a trained eye" };
    if (de < 3.5) return { label: "Very close", tone: "close", text: "a slight difference side by side" };
    if (de < 5) return { label: "Close", tone: "mid", text: "a clear difference side by side" };
    return { label: "Similar", tone: "far", text: "a different colour, nearest available" };
  }

  const api = { parseHex, hexToRgb, rgbToHex, cmykToRgb, rgbToCmyk, rgbToLab, labToRgb, deltaE2000, verdict };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ColorMath = api;
})(typeof window !== "undefined" ? window : globalThis);
