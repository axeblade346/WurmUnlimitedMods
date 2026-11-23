// ------------------------------------------------------------------ exporters: animated GIF and MJPEG AVI
// GIF: one palette for the whole clip (popular colours), LZW, loops forever.
export function encodeGif(frames, w, h, delayCs) {
  // palette from a sample of all frames, 5 bits per channel buckets
  const counts = new Map();
  const step = Math.max(1, Math.floor(frames.length / 12));
  for (let f = 0; f < frames.length; f += step) {
    const d = frames[f];
    for (let i = 0; i < d.length; i += 4 * 3) {
      const k = ((d[i] >> 3) << 10) | ((d[i + 1] >> 3) << 5) | (d[i + 2] >> 3);
      counts.set(k, (counts.get(k) || 0) + 1);
    }
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 256).map(([k]) => [((k >> 10) & 31) * 8 + 4, ((k >> 5) & 31) * 8 + 4, (k & 31) * 8 + 4]);
  while (top.length < 256) top.push([0, 0, 0]);
  const cache = new Int16Array(32768).fill(-1);
  const nearest = (r, g, b) => {
    const k = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);
    let c = cache[k]; if (c >= 0) return c;
    let best = 0, bd = 1e9;
    for (let i = 0; i < 256; i++) { const p = top[i]; const dd = (p[0] - r) ** 2 * 2 + (p[1] - g) ** 2 * 4 + (p[2] - b) ** 2 * 3; if (dd < bd) { bd = dd; best = i; } }
    cache[k] = best; return best;
  };
  const out = [];
  const bytes = (...a) => { for (const x of a) out.push(x & 255); };
  const word = (v) => bytes(v, v >> 8);
  const str = (t) => { for (const ch of t) out.push(ch.charCodeAt(0)); };
  str('GIF89a'); word(w); word(h); bytes(0xf7, 0, 0);            // global table, 256 colours
  for (const p of top) bytes(p[0], p[1], p[2]);
  bytes(0x21, 0xff, 11); str('NETSCAPE2.0'); bytes(3, 1); word(0); bytes(0);   // loop forever
  for (const d of frames) {
    bytes(0x21, 0xf9, 4, 0x04, delayCs & 255, delayCs >> 8, 0, 0);            // frame delay
    bytes(0x2c); word(0); word(0); word(w); word(h); bytes(0);
    const idx = new Uint8Array(w * h);
    for (let i = 0, j = 0; j < idx.length; i += 4, j++) idx[j] = nearest(d[i], d[i + 1], d[i + 2]);
    lzw(idx, 8, out);
  }
  bytes(0x3b);
  return new Uint8Array(out);
}
function lzw(idx, minSize, out) {
  out.push(minSize);
  const clear = 1 << minSize, eoi = clear + 1;
  let size = minSize + 1, next = eoi + 1;
  let dict = new Map();
  const buf = []; let cur = 0, bits = 0;
  const emit = (code) => {
    cur |= code << bits; bits += size;
    while (bits >= 8) { buf.push(cur & 255); cur >>= 8; bits -= 8; }
  };
  emit(clear);
  let prefix = idx[0];
  for (let i = 1; i < idx.length; i++) {
    const c = idx[i], key = prefix * 4096 + c;
    const hit = dict.get(key);
    if (hit !== undefined) { prefix = hit; continue; }
    emit(prefix);
    if (next < 4096) { dict.set(key, next++); if (next > (1 << size) && size < 12) size++; }
    else { emit(clear); dict = new Map(); size = minSize + 1; next = eoi + 1; }
    prefix = c;
  }
  emit(prefix); emit(eoi);
  if (bits > 0) buf.push(cur & 255);
  for (let i = 0; i < buf.length; i += 255) { const n = Math.min(255, buf.length - i); out.push(n); for (let j = 0; j < n; j++) out.push(buf[i + j]); }
  out.push(0);
}

// AVI with Motion-JPEG frames (plays in Windows' Films & TV / Media Player, VLC, editors)
export function encodeAvi(jpegs, w, h, fps) {
  const n = jpegs.length;
  const pad = (x) => x + (x & 1);
  const moviSize = 4 + jpegs.reduce((a, j) => a + 8 + pad(j.length), 0);
  const hdrlSize = 4 + (8 + 56) + (8 + 4 + (8 + 56) + (8 + 40));
  const idxSize = 16 * n;
  const total = 4 + (8 + hdrlSize) + (8 + moviSize) + (8 + idxSize);
  const buf = new ArrayBuffer(8 + total), dv = new DataView(buf), u8 = new Uint8Array(buf);
  let p = 0;
  const fcc = (s) => { for (let i = 0; i < 4; i++) dv.setUint8(p++, s.charCodeAt(i)); };
  const u32 = (v) => { dv.setUint32(p, v >>> 0, true); p += 4; };
  const u16 = (v) => { dv.setUint16(p, v, true); p += 2; };
  const maxJ = Math.max(...jpegs.map((j) => j.length));
  fcc('RIFF'); u32(total); fcc('AVI ');
  fcc('LIST'); u32(hdrlSize); fcc('hdrl');
  fcc('avih'); u32(56);
  u32(Math.round(1e6 / fps)); u32(maxJ * fps); u32(0); u32(0x10); u32(n); u32(0); u32(1); u32(maxJ); u32(w); u32(h); u32(0); u32(0); u32(0); u32(0);
  fcc('LIST'); u32(4 + (8 + 56) + (8 + 40)); fcc('strl');
  fcc('strh'); u32(56);
  fcc('vids'); fcc('MJPG'); u32(0); u16(0); u16(0); u32(0); u32(1); u32(fps); u32(0); u32(n); u32(maxJ); u32(0xffffffff); u32(0);
  u16(0); u16(0); u16(w); u16(h);
  fcc('strf'); u32(40);
  u32(40); u32(w); u32(h); u16(1); u16(24); fcc('MJPG'); u32(w * h * 3); u32(0); u32(0); u32(0); u32(0);
  fcc('LIST'); u32(moviSize); const moviStart = p; fcc('movi');
  const offs = [];
  for (const j of jpegs) {
    offs.push(p - moviStart);
    fcc('00dc'); u32(j.length); u8.set(j, p); p += j.length; if (j.length & 1) u8[p++] = 0;
  }
  fcc('idx1'); u32(idxSize);
  jpegs.forEach((j, i) => { fcc('00dc'); u32(0x10); u32(offs[i]); u32(j.length); });
  return u8;
}
