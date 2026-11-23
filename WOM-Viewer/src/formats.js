// Wurm Unlimited file formats for the browser: .wom models, .wom animations, DDS textures,
// mappings.txt, armor.xml, properties.xml.  No dependencies (also runs under Node for tests).

export class Reader {
  constructor(buf) { this.dv = new DataView(buf); this.b = new Uint8Array(buf); this.p = 0; }
  i32() { const v = this.dv.getInt32(this.p, true); this.p += 4; return v; }
  u8() { return this.b[this.p++]; }
  f(n) { const a = new Float32Array(n); for (let i = 0; i < n; i++) { a[i] = this.dv.getFloat32(this.p, true); this.p += 4; } return a; }
  s() { const n = this.i32(); const t = new TextDecoder('utf-8').decode(this.b.subarray(this.p, this.p + n)); this.p += n; return t; }
}

const MAT_PROPS = [['emissive', 4], ['shininess', 1], ['specular', 4], ['transparency', 4]];

/** .wom model -> {meshes:[{name, tangents, binormals, colors, pos, nrm, uv, idx, materials, skin}], joints} */
export function readWom(buf) {
  const r = new Reader(buf);
  const meshes = [];
  const nm = r.i32();
  if (nm < 0 || nm > 100000) throw new Error('not a model file');
  for (let m = 0; m < nm; m++) {
    const t = r.u8(), bn = r.u8(), c = r.u8();
    const name = r.s();
    const nv = r.i32();
    if (nv < 0 || nv > 10000000) throw new Error('bad vertex count');
    const stride = 8 + (c ? 3 : 0) + (t ? 3 : 0) + (bn ? 3 : 0);
    const pos = new Float32Array(nv * 3), nrm = new Float32Array(nv * 3), uv = new Float32Array(nv * 2);
    for (let i = 0; i < nv; i++) {
      const base = r.p;
      for (let k = 0; k < 3; k++) pos[i * 3 + k] = r.dv.getFloat32(base + k * 4, true);
      for (let k = 0; k < 3; k++) nrm[i * 3 + k] = r.dv.getFloat32(base + 12 + k * 4, true);
      uv[i * 2] = r.dv.getFloat32(base + 24, true); uv[i * 2 + 1] = r.dv.getFloat32(base + 28, true);
      r.p = base + stride * 4;
    }
    const ni = r.i32();
    const idx = new Uint32Array(ni);
    for (let i = 0; i < ni; i++) { idx[i] = r.dv.getUint16(r.p, true); r.p += 2; }
    const materials = [];
    const nmat = r.i32();
    for (let k = 0; k < nmat; k++) {
      const mat = { texture: r.s(), name: r.s(), enabled: r.u8() };
      for (const [key, n] of MAT_PROPS) mat[key] = r.u8() ? Array.from(r.f(n)) : null;
      materials.push(mat);
    }
    meshes.push({ name, tangents: t, binormals: bn, colors: c, pos, nrm, uv, idx, materials, skin: null });
  }
  const joints = [];
  const nj = r.i32();
  for (let j = 0; j < nj; j++) {
    joints.push({ parent: r.s(), name: r.s(), flag: r.u8(), bindWorld: r.f(16), bindLocal: r.f(16) });
  }
  for (const m of meshes) {
    if (r.p >= r.b.length) break;
    if (r.u8()) {
      const bones = [];
      const nb = r.i32();
      for (let b = 0; b < nb; b++) {
        const bone = { joint: r.s(), matrix: r.f(16), inverse: r.f(16), weights: [] };
        const nw = r.i32();
        for (let w = 0; w < nw; w++) { const vi = r.i32(); const wt = r.dv.getFloat32(r.p, true); r.p += 4; bone.weights.push([vi, wt]); }
        bones.push(bone);
      }
      m.skin = bones;
    }
  }
  if (r.p !== r.b.length) throw new Error('model parse ended at ' + r.p + ' of ' + r.b.length);
  return { meshes, joints };
}

/** animation .wom -> [{name, keys:[{m:Float32Array(16) local row-major, t}]}] */
export function readAnim(buf) {
  const r = new Reader(buf);
  const nb = r.i32();
  if (nb < 0 || nb > 10000) throw new Error('not an animation');
  const bones = [];
  for (let b = 0; b < nb; b++) {
    const name = r.s();
    const nk = r.i32();
    if (nk < 0 || nk > 1000000) throw new Error('not an animation');
    const keys = [];
    for (let k = 0; k < nk; k++) { const m = r.f(16); const t = r.f(1)[0]; keys.push({ m, t }); }
    bones.push({ name, keys });
  }
  if (r.p !== r.b.length) throw new Error('animation parse ended at ' + r.p);
  return bones;
}

export function womKind(buf) {
  try { readWom(buf); return 'model'; } catch (e) { /* */ }
  try { readAnim(buf); return 'anim'; } catch (e) { /* */ }
  return 'unknown';
}

// ---------------------------------------------------------------- DDS
function c565(c, out, o) {
  out[o] = ((c >> 11) & 31) * 255 / 31; out[o + 1] = ((c >> 5) & 63) * 255 / 63; out[o + 2] = (c & 31) * 255 / 31; out[o + 3] = 255;
}
function colorBlock(b, p, pal, forceFour) {
  const c0 = b[p] | (b[p + 1] << 8), c1 = b[p + 2] | (b[p + 3] << 8);
  c565(c0, pal, 0); c565(c1, pal, 4);
  if (c0 > c1 || forceFour) {
    for (let k = 0; k < 3; k++) { pal[8 + k] = (2 * pal[k] + pal[4 + k]) / 3; pal[12 + k] = (pal[k] + 2 * pal[4 + k]) / 3; }
    pal[11] = 255; pal[15] = 255;
  } else {
    for (let k = 0; k < 3; k++) { pal[8 + k] = (pal[k] + pal[4 + k]) / 2; pal[12 + k] = 0; }
    pal[11] = 255; pal[15] = 0;
  }
  return b[p + 4] | (b[p + 5] << 8) | (b[p + 6] << 16) | (b[p + 7] << 24);
}

/** DDS -> {width, height, data: Uint8ClampedArray RGBA (top row first), hasAlpha, format} (top mip only) */
export function decodeDDS(buf) {
  const b = new Uint8Array(buf), dv = new DataView(buf);
  if (dv.getUint32(0, true) !== 0x20534444) throw new Error('not a DDS file');
  const h = dv.getUint32(12, true), w = dv.getUint32(16, true);
  const pfFlags = dv.getUint32(80, true);
  let four = pfFlags & 4 ? String.fromCharCode(b[84], b[85], b[86], b[87]) : '';
  let off = 128;
  if (four === 'DX10') {
    const dxgi = dv.getUint32(128, true); off = 148;
    four = { 71: 'DXT1', 72: 'DXT1', 74: 'DXT3', 75: 'DXT3', 77: 'DXT5', 78: 'DXT5', 28: 'RGBA8', 29: 'RGBA8', 87: 'BGRA8', 88: 'BGRX8' }[dxgi] || ('DXGI' + dxgi);
  }
  const out = new Uint8ClampedArray(w * h * 4);
  let hasAlpha = false;
  if (four === 'DXT1' || four === 'DXT3' || four === 'DXT5') {
    const bs = four === 'DXT1' ? 8 : 16;
    const pal = new Float32Array(16), alpha = new Uint8Array(16);
    let p = off;
    for (let by = 0; by < h; by += 4) {
      for (let bx = 0; bx < w; bx += 4) {
        if (four === 'DXT3') {
          for (let i = 0; i < 8; i++) { const v = b[p + i]; alpha[i * 2] = (v & 15) * 17; alpha[i * 2 + 1] = (v >> 4) * 17; }
        } else if (four === 'DXT5') {
          const a0 = b[p], a1 = b[p + 1];
          const ap = [a0, a1];
          if (a0 > a1) for (let i = 1; i < 7; i++) ap.push(((7 - i) * a0 + i * a1) / 7);
          else { for (let i = 1; i < 5; i++) ap.push(((5 - i) * a0 + i * a1) / 5); ap.push(0, 255); }
          let bits = 0, nbits = 0, q = p + 2;
          for (let i = 0; i < 16; i++) {
            while (nbits < 3) { bits |= b[q++] << nbits; nbits += 8; }
            alpha[i] = ap[bits & 7]; bits >>= 3; nbits -= 3;
          }
        }
        const cp = four === 'DXT1' ? p : p + 8;
        const ind = colorBlock(b, cp, pal, four !== 'DXT1');
        for (let i = 0; i < 16; i++) {
          const x = bx + (i & 3), y = by + (i >> 2);
          if (x >= w || y >= h) continue;
          const sel = (ind >>> (2 * i)) & 3;
          const o = (y * w + x) * 4;
          out[o] = pal[sel * 4]; out[o + 1] = pal[sel * 4 + 1]; out[o + 2] = pal[sel * 4 + 2];
          out[o + 3] = four === 'DXT1' ? pal[sel * 4 + 3] : alpha[i];
          if (out[o + 3] < 255) hasAlpha = true;
        }
        p += bs;
      }
    }
  } else if (!four || four === 'RGBA8' || four === 'BGRA8' || four === 'BGRX8') {
    let bits = dv.getUint32(88, true), rm = dv.getUint32(92, true), gm = dv.getUint32(96, true), bm = dv.getUint32(100, true), am = dv.getUint32(104, true);
    if (four === 'RGBA8') { bits = 32; rm = 0xff; gm = 0xff00; bm = 0xff0000; am = 0xff000000; }
    if (four === 'BGRA8') { bits = 32; rm = 0xff0000; gm = 0xff00; bm = 0xff; am = 0xff000000; }
    if (four === 'BGRX8') { bits = 32; rm = 0xff0000; gm = 0xff00; bm = 0xff; am = 0; }
    if (!(pfFlags & 1) && !four) am = 0;
    const bpp = bits / 8;
    const shift = (m) => { if (!m) return [0, 0]; let s = 0; while (!((m >>> s) & 1)) s++; let n = 0; while ((m >>> (s + n)) & 1) n++; return [s, n]; };
    const S = [rm, gm, bm, am].map(shift);
    let p = off;
    for (let i = 0; i < w * h; i++) {
      let v = 0;
      for (let k = 0; k < bpp; k++) v |= b[p + k] << (8 * k);
      v >>>= 0;
      const ch = (m, [s, n]) => (m ? (((v & m) >>> s) * 255 / ((1 << n) - 1)) : 255);
      out[i * 4] = ch(rm, S[0]); out[i * 4 + 1] = ch(gm, S[1]); out[i * 4 + 2] = ch(bm, S[2]); out[i * 4 + 3] = ch(am, S[3]);
      if (out[i * 4 + 3] < 255) hasAlpha = true;
      p += bpp;
    }
  } else {
    throw new Error('unsupported DDS format ' + four);
  }
  return { width: w, height: h, data: out, hasAlpha, format: four || 'RGB' };
}

// ---------------------------------------------------------------- mappings.txt
export function parseMappings(text) {
  const out = [];
  let section = '';
  text.split(/\r?\n/).forEach((raw, i) => {
    const s = raw.trim();
    if (!s) return;
    if (s.startsWith('#') || s.startsWith('//')) {
      const t = s.replace(/^[#/\s]+/, '').replace(/[-#\s]+$/, '');
      if (t && !s.includes('=') && !/^[a-z]+(\.[\w-]+)+$/.test(t)) section = t;
      return;
    }
    const eq = s.indexOf('=');
    if (eq < 0) return;
    const key = s.slice(0, eq).trim();
    const val = s.slice(eq + 1).trim();
    const q = val.indexOf('?');
    const file = (q < 0 ? val : val.slice(0, q)).trim().replace(/\\/g, '/');
    const overrides = {};
    if (q >= 0) {
      for (const part of val.slice(q + 1).split('&')) {
        const e2 = part.indexOf('=');
        if (e2 < 0) continue;
        const k = part.slice(0, e2).trim(), v = part.slice(e2 + 1).trim();
        const dot = k.lastIndexOf('.');
        const mat = k.slice(0, dot), prop = k.slice(dot + 1);
        (overrides[mat] = overrides[mat] || {})[prop] = v;
      }
    }
    out.push({ line: i + 1, key, file, overrides, section });
  });
  return out;
}

// ---------------------------------------------------------------- XML helpers (DOMParser in browsers)
function kids(el) { return Array.from(el.children || []); }

/** armor.xml -> {items: {key: {group, variants: {variantName: {male:[ops], female:[ops], flags}}}}, base:{...}} */
export function parseArmor(doc) {
  const root = doc.documentElement;
  const items = {};
  for (const group of kids(root)) {
    for (const item of kids(group)) {
      const key = item.tagName;
      const variants = {};
      for (const v of kids(item)) {
        const entry = {};
        for (const g of kids(v)) {
          if (g.tagName !== 'male' && g.tagName !== 'female') continue;
          const ops = [], flags = {};
          let pendingMesh = null, pendingTex = null;
          for (const el of kids(g)) {
            const t = el.tagName, txt = (el.textContent || '').trim();
            if (t === 'meshPlace') pendingMesh = txt;
            else if (t === 'meshName') { ops.push({ type: 'mesh', place: pendingMesh, name: txt }); pendingMesh = null; }
            else if (t === 'texturePlace') pendingTex = txt;
            else if (t === 'texture') { ops.push({ type: 'tex', place: pendingTex, path: txt.replace(/\\/g, '/') }); pendingTex = null; }
            else flags[t] = txt || true;
          }
          entry[g.tagName] = { ops, flags };
        }
        variants[v.tagName] = entry;
      }
      items[key] = { group: group.tagName, variants };
    }
  }
  return items;
}

/** properties.xml -> {modelFileLower: {anims:[{name, file, flags}], props:{}}} */
export function parseProperties(doc) {
  const out = {};
  for (const model of kids(doc.documentElement)) {
    const entry = { anims: [], props: {}, offsets: {} };
    for (const sec of kids(model)) {
      if (sec.tagName === 'offsetToNull') {
        // <offsetToNull><NullHelmet><xPos/><yPos/><zPos/><xRot/><yRot/><zRot/> (metres, degrees)
        for (const nul of kids(sec)) {
          const o = {};
          for (const v of kids(nul)) { const n = parseFloat(v.textContent); if (!Number.isNaN(n)) o[v.tagName] = n; }
          entry.offsets[nul.tagName] = o;
        }
      } else if (sec.tagName === 'anim') {
        for (const a of kids(sec)) {
          const f = kids(a).find((e) => e.tagName === 'file');
          if (f) entry.anims.push({ name: a.tagName, file: f.textContent.trim().replace(/\\/g, '/') });
        }
      } else {
        for (const p of kids(sec)) {
          if (p.tagName === 'meshMask') {
            // <meshMask><mesh>wagon</mesh><mask>cart_m.dds</mask></meshMask>: dye mask for one mesh
            const mesh = kids(p).find((e) => e.tagName === 'mesh'), mask = kids(p).find((e) => e.tagName === 'mask');
            if (mesh && mask) (entry.meshMasks = entry.meshMasks || []).push({ mesh: mesh.textContent.trim(), mask: mask.textContent.trim() });
          } else entry.props[p.tagName] = (p.textContent || '').trim();
        }
      }
    }
    out[model.tagName.toLowerCase()] = entry;
  }
  return out;
}

// ------------------------------------------------------------------ .jar / .zip packs (read in place)
// The game's packs (graphics.jar ...) are zip files. Only the index is read when opening; each file is
// unpacked when it is used, so a large pack opens quickly and nothing is extracted to disk.
const ZIP_CACHE = new Map();   // small cache of unpacked files (the same texture is often asked twice)
export class ZipEntry {
  constructor(zip, name, method, csize, size, offset) {
    this.zip = zip; this._rel = name; this.name = name.split('/').pop();
    this.method = method; this.csize = csize; this.size = size; this.offset = offset; this.fromJar = zip.name;
  }
  async arrayBuffer() {
    const key = this.zip.name + '|' + this._rel;
    if (ZIP_CACHE.has(key)) { const b = ZIP_CACHE.get(key); ZIP_CACHE.delete(key); ZIP_CACHE.set(key, b); return b; }
    const head = new DataView(await this.zip.slice(this.offset, this.offset + 30).arrayBuffer());
    if (head.getUint32(0, true) !== 0x04034b50) throw new Error('bad zip entry ' + this._rel);
    const start = this.offset + 30 + head.getUint16(26, true) + head.getUint16(28, true);
    const raw = this.zip.slice(start, start + this.csize);
    let buf;
    if (this.method === 0) buf = await raw.arrayBuffer();
    else if (this.method === 8) buf = await new Response(raw.stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer();
    else throw new Error(`${this._rel}: zip method ${this.method} not supported`);
    ZIP_CACHE.set(key, buf);
    while (ZIP_CACHE.size > 12) ZIP_CACHE.delete(ZIP_CACHE.keys().next().value);
    return buf;
  }
  async text() { return new TextDecoder().decode(await this.arrayBuffer()); }
  async blob() { return new Blob([await this.arrayBuffer()]); }
  slice(a, b) { const self = this; return { arrayBuffer: async () => (await self.arrayBuffer()).slice(a, b) }; }
}
export async function openZip(file) {
  const tailLen = Math.min(file.size, 65557 + 20);
  const tailStart = file.size - tailLen;
  const tail = new DataView(await file.slice(tailStart).arrayBuffer());
  let eocd = -1;
  for (let i = tail.byteLength - 22; i >= 0; i--) if (tail.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new Error(file.name + ' is not a zip/jar file');
  let count = tail.getUint16(eocd + 10, true), cdSize = tail.getUint32(eocd + 12, true), cdOff = tail.getUint32(eocd + 16, true);
  if (count === 0xffff || cdSize === 0xffffffff || cdOff === 0xffffffff) {   // zip64 (packs over 4 GB)
    const loc = eocd - 20;
    if (loc >= 0 && tail.getUint32(loc, true) === 0x07064b50) {
      const z64off = Number(tail.getBigUint64(loc + 8, true));
      const z = new DataView(await file.slice(z64off, z64off + 56).arrayBuffer());
      count = Number(z.getBigUint64(32, true)); cdSize = Number(z.getBigUint64(40, true)); cdOff = Number(z.getBigUint64(48, true));
    }
  }
  const cd = new DataView(await file.slice(cdOff, cdOff + cdSize).arrayBuffer());
  const u8 = new Uint8Array(cd.buffer), dec = new TextDecoder();
  const out = [];
  for (let p = 0, n = 0; n < count && p + 46 <= cd.byteLength; n++) {
    if (cd.getUint32(p, true) !== 0x02014b50) break;
    const method = cd.getUint16(p + 10, true);
    let csize = cd.getUint32(p + 20, true), size = cd.getUint32(p + 24, true);
    const nl = cd.getUint16(p + 28, true), xl = cd.getUint16(p + 30, true), cl = cd.getUint16(p + 32, true);
    let off = cd.getUint32(p + 42, true);
    const name = dec.decode(u8.subarray(p + 46, p + 46 + nl)).replace(/\\/g, '/');
    for (let q = p + 46 + nl; q + 4 <= p + 46 + nl + xl;) {   // zip64 sizes / offset
      const id = cd.getUint16(q, true), len = cd.getUint16(q + 2, true);
      if (id === 1) {
        let r = q + 4;
        if (size === 0xffffffff) { size = Number(cd.getBigUint64(r, true)); r += 8; }
        if (csize === 0xffffffff) { csize = Number(cd.getBigUint64(r, true)); r += 8; }
        if (off === 0xffffffff) { off = Number(cd.getBigUint64(r, true)); }
      }
      q += 4 + len;
    }
    if (!name.endsWith('/')) out.push(new ZipEntry(file, name, method, csize, size, off));
    p += 46 + nl + xl + cl;
  }
  return out;
}

// ------------------------------------------------------------------ .obj (from wom_tool batch / wom2obj, or your own)
// Turns an .obj (+ .mtl, + the .womdata.json written next to it by wom_tool) back into the same shape
// readWom() returns. With .womdata.json the skeleton and skin weights come back: unchanged meshes keep
// them exactly, edited meshes take each vertex's weights from the nearest original vertex. A placement
// that wom2obj applied (hair/helmets put on the body) is undone.
export function readObj(objText, mtlText, womdata) {
  const P = [], T = [], N = [];
  const meshes = [];
  let cur = null, mat = null;
  const mtlTex = {};
  if (mtlText) {
    let name = null;
    for (const raw of mtlText.split(/\r?\n/)) {
      const l = raw.trim(); if (!l || l[0] === '#') continue;
      const [k, ...rest] = l.split(/\s+/);
      if (k === 'newmtl') name = rest.join(' ');
      else if (/^map_kd$/i.test(k) && name) mtlTex[name] = rest[rest.length - 1].replace(/\\/g, '/');
    }
  }
  const start = (name) => { cur = { name, keys: new Map(), pos: [], nrm: [], uv: [], idx: [], mat }; meshes.push(cur); };
  for (const raw of objText.split(/\r?\n/)) {
    const l = raw.trim(); if (!l || l[0] === '#') continue;
    const sp = l.indexOf(' '); const k = sp < 0 ? l : l.slice(0, sp); const a = sp < 0 ? '' : l.slice(sp + 1).trim();
    if (k === 'v') P.push(a.split(/\s+/).slice(0, 3).map(Number));
    else if (k === 'vt') { const t = a.split(/\s+/).map(Number); T.push([t[0], t[1] ?? 0]); }
    else if (k === 'vn') N.push(a.split(/\s+/).map(Number));
    else if (k === 'o' || k === 'g') start(a || 'mesh' + meshes.length);
    else if (k === 'usemtl') { mat = a; if (!cur || cur.idx.length) start((cur ? cur.name : 'mesh') + (cur && cur.idx.length ? '_' + a : '')); cur.mat = a; }
    else if (k === 'f') {
      if (!cur) start('mesh0');
      const vs = a.split(/\s+/).map((s) => {
        let key = cur.keys.get(s);
        if (key == null) {
          const [vi, ti, ni] = s.split('/').map((x) => (x ? Number(x) : null));
          const g = (arr, i) => (i == null ? null : arr[i < 0 ? arr.length + i : i - 1]);
          const p = g(P, vi) || [0, 0, 0], t = g(T, ti) || [0, 0], n = g(N, ni) || [0, 1, 0];
          key = cur.pos.length / 3; cur.keys.set(s, key);
          cur.pos.push(...p); cur.nrm.push(...n); cur.uv.push(t[0], 1 - t[1]);   // obj v is bottom-origin, wom top-origin
        }
        return key;
      });
      for (let i = 1; i + 1 < vs.length; i++) cur.idx.push(vs[0], vs[i], vs[i + 1]);
    }
  }
  const model = womdata && womdata.model;
  const orig = new Map((model ? model.meshes : []).map((m) => [m.name.toLowerCase(), m]));
  // undo the placement wom2obj applied (row-major 4x4)
  let inv = null;
  if (womdata && womdata.placement && womdata.placement.matrix) {
    const M = womdata.placement.matrix.flat();
    inv = invert4(M);
  }
  const out = [];
  for (const c of meshes) {
    if (!c.idx.length) continue;
    const nv = c.pos.length / 3;
    const pos = new Float32Array(c.pos), nrm = new Float32Array(c.nrm), uv = new Float32Array(c.uv);
    if (inv) for (let i = 0; i < nv; i++) {
      const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2];
      for (let r = 0; r < 3; r++) pos[i * 3 + r] = inv[r * 4] * x + inv[r * 4 + 1] * y + inv[r * 4 + 2] * z + inv[r * 4 + 3];
      const nx = nrm[i * 3], ny = nrm[i * 3 + 1], nz = nrm[i * 3 + 2];
      for (let r = 0; r < 3; r++) nrm[i * 3 + r] = inv[r * 4] * nx + inv[r * 4 + 1] * ny + inv[r * 4 + 2] * nz;
    }
    const o = orig.get(c.name.toLowerCase());
    let materials;
    if (o && o.materials && o.materials.length) {
      materials = o.materials.map((m) => ({ ...m }));
      // a texture changed in the .mtl wins over the original one
      const t = mtlTex[c.mat]; const stem = (s) => s.split('/').pop().replace(/\.[^.]+$/, '').toLowerCase();
      if (t && stem(t) !== stem(materials[0].texture || '')) materials[0].texture = t.split('/').pop();
    } else materials = [{ texture: (mtlTex[c.mat] || '').split('/').pop(), name: c.mat || 'material', enabled: 1, emissive: null, shininess: null, specular: null, transparency: null }];
    const mesh = { name: c.name, tangents: 0, binormals: 0, colors: 0, pos, nrm, uv, idx: new Uint32Array(c.idx), materials, skin: null, fromObj: true };
    if (o && o.skin) mesh.skin = transferSkin(o, pos);
    out.push(mesh);
  }
  const joints = model ? model.joints.map((j) => ({ parent: j.parent, name: j.name, flag: j.flag, bindWorld: new Float32Array(j.bind_world), bindLocal: new Float32Array(j.bind_local) })) : [];
  return { meshes: out, joints, fromObj: true, placed: !inv && !model };
}
function transferSkin(o, pos) {
  const nv = pos.length / 3, ov = o.verts.length;
  const bones = o.skin.map((b) => ({ joint: b.joint, matrix: new Float32Array(b.matrix), inverse: new Float32Array(b.inverse), weights: [] }));
  let same = nv === ov;
  if (same) for (let i = 0; i < nv && same; i++) { const p = o.verts[i].pos; if (Math.abs(p[0] - pos[i * 3]) + Math.abs(p[1] - pos[i * 3 + 1]) + Math.abs(p[2] - pos[i * 3 + 2]) > 1e-3) same = false; }
  if (same) { o.skin.forEach((b, k) => { bones[k].weights = b.weights.map((w) => [w[0], w[1]]); }); return bones; }
  // per original vertex: [[bone, weight]...], then nearest original vertex for each new one
  const per = Array.from({ length: ov }, () => []);
  o.skin.forEach((b, k) => b.weights.forEach(([vi, w]) => { if (per[vi]) per[vi].push([k, w]); }));
  for (let i = 0; i < nv; i++) {
    let best = 0, bd = Infinity;
    const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2];
    for (let j = 0; j < ov; j++) { const p = o.verts[j].pos; const d = (p[0] - x) ** 2 + (p[1] - y) ** 2 + (p[2] - z) ** 2; if (d < bd) { bd = d; best = j; } }
    for (const [k, w] of per[best]) bones[k].weights.push([i, w]);
  }
  return bones;
}
function invert4(m) {
  // general 4x4 inverse (row-major)
  const a = m, inv = new Array(16);
  inv[0] = a[5] * a[10] * a[15] - a[5] * a[11] * a[14] - a[9] * a[6] * a[15] + a[9] * a[7] * a[14] + a[13] * a[6] * a[11] - a[13] * a[7] * a[10];
  inv[4] = -a[4] * a[10] * a[15] + a[4] * a[11] * a[14] + a[8] * a[6] * a[15] - a[8] * a[7] * a[14] - a[12] * a[6] * a[11] + a[12] * a[7] * a[10];
  inv[8] = a[4] * a[9] * a[15] - a[4] * a[11] * a[13] - a[8] * a[5] * a[15] + a[8] * a[7] * a[13] + a[12] * a[5] * a[11] - a[12] * a[7] * a[9];
  inv[12] = -a[4] * a[9] * a[14] + a[4] * a[10] * a[13] + a[8] * a[5] * a[14] - a[8] * a[6] * a[13] - a[12] * a[5] * a[10] + a[12] * a[6] * a[9];
  inv[1] = -a[1] * a[10] * a[15] + a[1] * a[11] * a[14] + a[9] * a[2] * a[15] - a[9] * a[3] * a[14] - a[13] * a[2] * a[11] + a[13] * a[3] * a[10];
  inv[5] = a[0] * a[10] * a[15] - a[0] * a[11] * a[14] - a[8] * a[2] * a[15] + a[8] * a[3] * a[14] + a[12] * a[2] * a[11] - a[12] * a[3] * a[10];
  inv[9] = -a[0] * a[9] * a[15] + a[0] * a[11] * a[13] + a[8] * a[1] * a[15] - a[8] * a[3] * a[13] - a[12] * a[1] * a[11] + a[12] * a[3] * a[9];
  inv[13] = a[0] * a[9] * a[14] - a[0] * a[10] * a[13] - a[8] * a[1] * a[14] + a[8] * a[2] * a[13] + a[12] * a[1] * a[10] - a[12] * a[2] * a[9];
  inv[2] = a[1] * a[6] * a[15] - a[1] * a[7] * a[14] - a[5] * a[2] * a[15] + a[5] * a[3] * a[14] + a[13] * a[2] * a[7] - a[13] * a[3] * a[6];
  inv[6] = -a[0] * a[6] * a[15] + a[0] * a[7] * a[14] + a[4] * a[2] * a[15] - a[4] * a[3] * a[14] - a[12] * a[2] * a[7] + a[12] * a[3] * a[6];
  inv[10] = a[0] * a[5] * a[15] - a[0] * a[7] * a[13] - a[4] * a[1] * a[15] + a[4] * a[3] * a[13] + a[12] * a[1] * a[7] - a[12] * a[3] * a[5];
  inv[14] = -a[0] * a[5] * a[14] + a[0] * a[6] * a[13] + a[4] * a[1] * a[14] - a[4] * a[2] * a[13] - a[12] * a[1] * a[6] + a[12] * a[2] * a[5];
  inv[3] = -a[1] * a[6] * a[11] + a[1] * a[7] * a[10] + a[5] * a[2] * a[11] - a[5] * a[3] * a[10] - a[9] * a[2] * a[7] + a[9] * a[3] * a[6];
  inv[7] = a[0] * a[6] * a[11] - a[0] * a[7] * a[10] - a[4] * a[2] * a[11] + a[4] * a[3] * a[10] + a[8] * a[2] * a[7] - a[8] * a[3] * a[6];
  inv[11] = -a[0] * a[5] * a[11] + a[0] * a[7] * a[9] + a[4] * a[1] * a[11] - a[4] * a[3] * a[9] - a[8] * a[1] * a[7] + a[8] * a[3] * a[5];
  inv[15] = a[0] * a[5] * a[10] - a[0] * a[6] * a[9] - a[4] * a[1] * a[10] + a[4] * a[2] * a[9] + a[8] * a[1] * a[6] - a[8] * a[2] * a[5];
  let det = a[0] * inv[0] + a[1] * inv[4] + a[2] * inv[8] + a[3] * inv[12];
  det = det ? 1 / det : 0;
  return inv.map((v) => v * det);
}
