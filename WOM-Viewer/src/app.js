// Wurm Unlimited model viewer - runs in the browser, reads the user's own game folder.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { encodeGif, encodeAvi } from 'wom-export';
import { readWom, readAnim, decodeDDS, parseMappings, parseArmor, parseProperties, openZip, readObj } from 'wom-formats';

const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...children) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v; else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'html') e.innerHTML = v; else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children) if (c != null) e.append(c);
  return e;
};
const TIERS = ['256', '512', '1024', '2048'];
const HEAD_RE = /^(backpart|upperface\d+|lowerface\d+|nose\d+)mesh$/i;
const BEARD_RE = /^facialhair\d+mesh$/i;
const HIDDEN_RE = /(boundingbox|pickingbox)/i;
const BODY_PLACES = ['torso', 'tasset', 'UA', 'LA', 'hand', 'legs', 'LL', 'foot'];
const OUTER_RE = /^(hood|cape|tabard|chaincoif)\d*/i;
// where each armour/cloth texture goes on the 2048 body texture: [x, y, w, h] (left/right limbs = 2 cells)
const CELLS = {
  torso: [[0, 0, 1020, 699]], tasset: [[0, 699, 1020, 391]],
  ua: [[1100, 0, 474, 378], [1574, 0, 474, 378]], la: [[1100, 378, 474, 528], [1574, 378, 474, 528]],
  legs: [[1100, 906, 948, 506]], ll: [[1080, 1412, 484, 636], [1564, 1412, 484, 636]],
  hand: [[0, 1090, 350, 342], [350, 1090, 350, 342]], foot: [[700, 1090, 400, 188], [700, 1278, 400, 188]],
  tabarddown: [[672, 1466, 264, 582]], cape: [[936, 1466, 164, 582]],
};
const SLOTS = [
  ['Head', /\.head\b|helm|coif|hood|hat|mask|crown/i], ['Torso', /torso|jacket|shirt|vest|chest|robe/i],
  ['Arms', /sleeve|arm\b|arms/i], ['Hands', /hand|glove|gauntlet/i], ['Legs', /\.legs?\b|pants|leggings|trouser/i],
  ['Feet', /foot|feet|boot|shoe/i], ['Tabard', /tabard/i], ['Back', /cape|cloak|back/i],
  ['Neck', /necklace|medallion|amulet|pendant|\.n\.rift/i], ['Belt', /belt/i], ['Other', /./],
];
// jewellery worn as models (from mappings.txt or your custom objects), on these bones
const JEWEL_SLOTS = [
  ['Left ring', 'LeftHandMiddle1', /^model\.decoration\.ring(\.|$)|(^|\/)ring[^/]*\.(wom|obj)$/i],
  ['Right ring', 'RightHandMiddle1', /^model\.decoration\.ring(\.|$)|(^|\/)ring[^/]*\.(wom|obj)$/i],
  ['Left bracelet', 'LeftHand', /^model\.decoration\.armring(\.|$)|(^|\/)bracelet[^/]*\.(wom|obj)$/i],
  ['Right bracelet', 'RightHand', /^model\.decoration\.armring(\.|$)|(^|\/)bracelet[^/]*\.(wom|obj)$/i],
  ['Left earring', 'Head', /earring/i], ['Right earring', 'Head', /earring/i],   // none in the game: shown only for custom ones
];
const FACE_LAYERS = [ // [ui name, mappings key, mesh group or null]
  ['Head type (face)', 'upperFace', 'upperFace'], ['Chin (lower face)', 'lowerFace', 'lowerFace'], ['Nose', 'nose', 'nose'],
  ['Complexion', 'complexion', null], ['Eye shape', 'eyeType', null], ['Eye colour', 'eyeColor', null],
  ['Eyebrows', 'eyebrow', null], ['Facial hair', 'facialHair', null],
];

// ------------------------------------------------------------------ status / progress
const status = {
  set(msg, frac = null) {
    $('#status').hidden = false;
    $('#status-text').textContent = msg;
    const bar = $('#status-bar');
    if (frac == null) { bar.classList.add('indet'); bar.style.setProperty('--p', '30%'); } else { bar.classList.remove('indet'); bar.style.setProperty('--p', Math.round(frac * 100) + '%'); }
  },
  done(msg) { $('#status').hidden = true; if (msg) toast(msg); },
};
function toast(msg, ms = 3500) {
  const t = el('div', { class: 'toast' }, msg); $('#toasts').append(t); setTimeout(() => t.remove(), ms);
}
const tick = () => new Promise((r) => setTimeout(r, 0));

// ------------------------------------------------------------------ virtual file system
class GameFiles {
  constructor() { this.files = new Map(); this.byStem = new Map(); this.orig = new Map(); this.root = ''; }
  async add(fileList, onProgress) {
    let n = 0;
    for (const f of fileList) {
      let rel = (f.webkitRelativePath || f._rel || f.name).replace(/\\/g, '/');
      this.files.set(rel.toLowerCase(), f);
      if (++n % 2000 === 0) { onProgress && onProgress(n); await tick(); }
    }
    // drop the picked folder's own name so paths look like the game's ("player/...")
    const firsts = new Set([...this.files.keys()].map((k) => k.split('/')[0]));
    if (firsts.size === 1) {
      const top = [...firsts][0];
      const re = new Map();
      for (const [k, f] of this.files) re.set(k.includes('/') ? k.slice(top.length + 1) : k, f);
      this.files = re; this.root = top;
    }
    this.orig.clear();
    for (const [k, f] of this.files) {
      let o = (f.webkitRelativePath || f._rel || f.name).replace(/\\/g, '/');
      if (this.root && o.toLowerCase().startsWith(this.root + '/')) o = o.slice(this.root.length + 1);
      this.orig.set(k, o);
    }
    this.byStem.clear();
    for (const k of this.files.keys()) {
      const base = k.split('/').pop(), stem = base.replace(/\.[^.]+$/, '');
      if (!this.byStem.has(stem)) this.byStem.set(stem, []);
      this.byStem.get(stem).push(k);
    }
  }
  get(path) { return this.files.get(normPath(path).toLowerCase()) || null; }
  has(path) { return this.files.has(normPath(path).toLowerCase()); }
  list(ext) { return [...this.files.keys()].filter((k) => k.endsWith(ext)).sort().map((k) => this.orig.get(k) || k); }
  findByName(name) { const n = name.toLowerCase(); return [...this.files.keys()].filter((k) => k.split('/').pop() === n); }
  /** texture by name: same folder first, then the chosen resolution tier, then any */
  findTexture(name, fromDir, tier) {
    const base = name.replace(/\\/g, '/').split('/').pop().toLowerCase();
    const stem = base.replace(/\.[^.]+$/, '');
    const direct = normPath((fromDir ? fromDir + '/' : '') + name).toLowerCase();
    if (this.files.has(direct)) return direct;
    const c = (this.byStem.get(stem) || []).filter((k) => /\.(dds|png|jpe?g|tga|bmp)$/.test(k));
    if (!c.length) return null;
    const rank = (k) => {
      const parts = k.split('/');
      const t = parts.find((p) => TIERS.includes(p));
      const sameDir = k.slice(0, k.lastIndexOf('/')) === (fromDir || '').toLowerCase();
      const tierScore = !t ? 5 : t === tier ? 0 : (+t > +tier ? 1 + TIERS.indexOf(t) : 10 - TIERS.indexOf(t));
      const sameExt = k.endsWith(base.slice(base.lastIndexOf('.'))) ? 0 : 1;
      return [sameDir ? 0 : 1, tierScore, sameExt, k.length];
    };
    c.sort((a, b) => { const ra = rank(a), rb = rank(b); for (let i = 0; i < ra.length; i++) if (ra[i] !== rb[i]) return ra[i] - rb[i]; return 0; });
    return c[0];
  }
  async buffer(path) { const f = this.get(path); return f ? f.arrayBuffer() : null; }
  async text(path) { const f = this.get(path); return f ? f.text() : null; }
}
function normPath(p) {
  const out = [];
  for (const s of p.replace(/\\/g, '/').split('/')) { if (!s || s === '.') continue; if (s === '..') out.pop(); else out.push(s); }
  return out.join('/');
}
const dirOf = (p) => (p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '');
const EXTRA = 'extra:';
function getFile(path) {
  if (path.startsWith(EXTRA)) return S.useOverlay ? S.overlay.get(path.slice(EXTRA.length)) : null;
  // a .wom in an extra folder at the same path (e.g. player/hair/femaleHair01.wom) replaces the game's
  if (S.useOverlay && /\.(wom|obj)$/i.test(path)) { const o = S.overlay.findFile(path) || S.overlay.get(path); if (o) return o; }
  return S.fs.get(path) || (S.useOverlay ? S.overlay.get(path) : null);
}
/** a model file as readWom() returns it; .obj files (with their .mtl and .womdata.json) are converted */
async function readModel(path) {
  const f = getFile(path); if (!f) return null;
  const name = f._okey || f._rel || f.webkitRelativePath || f.name || path;
  if (!/\.obj$/i.test(name)) return readWom(await f.arrayBuffer());
  const text = await f.text();
  const dir = dirOf(f._okey ? f._okey : path);
  const sib = (n) => (f._okey ? S.overlay.get((dir ? dir + '/' : '') + n) : S.fs.get((dir ? dir + '/' : '') + n));
  const ml = /^mtllib\s+(.+)$/m.exec(text); const mtlF = ml ? sib(ml[1].trim()) : null;
  const wd = sib(name.split('/').pop().replace(/\.obj$/i, '') + '.womdata.json');
  let womdata = null; if (wd) { try { womdata = JSON.parse(await wd.text()); } catch (e) { console.warn(e); } }
  const w = readObj(text, mtlF ? await mtlF.text() : '', womdata);
  w.objFile = name;
  return w;
}
async function readBuf(path) { const f = getFile(path); return f ? f.arrayBuffer() : null; }

// ------------------------------------------------------------------ replacement textures (an _upscaled or _obj folder)
class TextureOverlay {
  // Custom folders / custom objects (and, separately, the upscale folder) laid over the game files.
  // The folder added last wins. A folder named "player_obj", "player_wom" or "player_upscaled" stands
  // for the game's "player" folder, so its files line up with the game paths.
  constructor() { this.clear(); }
  clear() { this.byKey = new Map(); this.files = new Map(); this.orig = new Map(); this.layer = new Map(); this.kinds = []; this.names = []; this.count = 0; this._idx = null; this._fidx = null; this.version = (this.version || 0) + 1; }
  get name() { return this.names.join(' + '); }
  kindOf(key) { return this.kinds[this.layer.get(key)] || ''; }
  async add(fileList, kind = 'cf') {
    const li = this.names.length;
    let name = '';
    for (const f of fileList) {
      const o = (f.webkitRelativePath || f._rel || f.name).replace(/\\/g, '/');
      const parts = o.split('/');
      const top = parts.length > 1 ? parts[0] : '';
      name = name || top || 'files';
      const m = /^(.*)_(obj|wom|upscaled|glb)$/i.exec(top);
      const rest = parts.length > 1 ? parts.slice(1).join('/') : o;
      const origInner = m ? m[1] + '/' + rest : rest;
      const inner = origInner.toLowerCase();
      f._okey = inner;
      this.files.delete(inner); this.files.set(inner, f); this.orig.set(inner, origInner); this.layer.set(inner, li);
      if (!/\.(dds|png|jpe?g|tga|bmp)$/.test(inner)) continue;
      const key = inner.replace(/\.[^./]+$/, '');   // without extension (an _obj copy may be .png where the game has .dds)
      if (!this.byKey.has(key)) this.count++;
      this.byKey.delete(key); this.byKey.set(key, f);
    }
    this.names.push(name || 'folder'); this.kinds.push(kind);
    this._idx = null; this._fidx = null; this.version++;
  }
  /** model files (.wom / .obj), not animations */
  models() { return [...this.files.keys()].filter((k) => /\.(wom|obj)$/.test(k) && !/(^|\/)anim\//.test(k)).sort().map((k) => this.orig.get(k)); }
  get(rel) { return this.files.get(rel.toLowerCase()) || null; }
  findByName(name) { const n = name.toLowerCase(); return [...this.files.keys()].filter((k) => k.split('/').pop() === n).sort((a, b) => a.split('/').length - b.split('/').length); }
  /** texture by file name anywhere in the folders (for models that live in them) */
  byName(name) {
    const stem = name.replace(/\\/g, '/').split('/').pop().toLowerCase().replace(/\.[^.]+$/, '');
    let hit = null;
    for (const [k] of this.files) if (/\.(dds|png|jpe?g|tga|bmp)$/.test(k) && k.split('/').pop().replace(/\.[^.]+$/, '') === stem) hit = k;   // last = newest folder
    return hit;
  }
  /** suffix index: every ending of every path -> newest value */
  _build(entries) {
    const idx = new Map();
    for (const [k, v] of entries) { const p = k.split('/'); for (let i = 0; i < p.length; i++) idx.set(p.slice(i).join('/'), v); }
    return idx;
  }
  /** game texture path -> replacement File, matching the longest common ending of the path */
  find(gamePath) {
    if (!this.count) return null;
    this._idx ||= this._build(this.byKey);
    const parts = gamePath.toLowerCase().replace(/\.[^./]+$/, '').split('/');
    for (let i = 0; i < parts.length; i++) { const f = this._idx.get(parts.slice(i).join('/')); if (f) return f; }
    return null;
  }
  /** game model path (.wom) -> [key, File] of a replacing .wom or .obj; folder + file name must match */
  findFileKey(gamePath) {
    if (!this.files.size) return null;
    if (!this._fidx) {
      const ms = [...this.files.keys()].filter((k) => /\.(wom|obj)$/.test(k));
      ms.sort((a, b) => (this.layer.get(a) - this.layer.get(b)) || (a.endsWith('.obj') - b.endsWith('.obj')));   // newest folder, then .obj, win
      this._fidx = this._build(ms.map((k) => [k.replace(/\.(wom|obj)$/, ''), k]));
    }
    const parts = gamePath.toLowerCase().replace(/\.(wom|obj)$/, '').split('/');
    for (let i = 0; i < parts.length - 1; i++) { const k = this._fidx.get(parts.slice(i).join('/')); if (k) return [k, this.files.get(k)]; }
    return null;
  }
  findFile(gamePath) { const r = this.findFileKey(gamePath); return r ? r[1] : null; }
}

// ------------------------------------------------------------------ app state
const S = {
  fs: new GameFiles(), mappings: [], mapPrefix: '', mapIndex: new Map(), armor: null, armorDir: '', props: {},
  tier: '2048', texCache: new Map(), current: null, mixer: null, action: null, last: performance.now(),
  animCache: new Map(), overlay: new TextureOverlay(), useOverlay: true, upscale: new TextureOverlay(), useUpscale: false, tierUI: '2048', memory: loadMemory(), jarName: '', mountMemory: {}, dyeMemory: {}, metalMemory: {}, useNormalMaps: true, flipNormalGreen: false, shine: 'gloss', cleanEdges: true,
};

const qs = new URLSearchParams(location.search);
const CMP = { on: false, mode: 'wipe', split: 0.5, twin: null, sig: '', gen: 0, timer: 0, left: { src: 'jar', tier: '2048' } };
function loadMemory() { try { return JSON.parse(localStorage.getItem('womviewer.memory') || '{}'); } catch (e) { return {}; } }
// ------------------------------------------------------------------ three.js scene
const renderer = new THREE.WebGLRenderer({ canvas: $('#view'), antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x2b2f36);
const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 2000);
camera.position.set(2.5, 2, 3.5);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 1, 0); controls.enableDamping = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
let grid = new THREE.GridHelper(10, 20, 0x667080, 0x3a404a); scene.add(grid);
function resize() {
  const c = renderer.domElement, w = c.clientWidth, h = c.clientHeight;
  if (c.width !== Math.floor(w * renderer.getPixelRatio()) || c.height !== Math.floor(h * renderer.getPixelRatio())) {
    renderer.setSize(w, h, false); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
  }
}
// Highlights. "classic" is three.js's Blinn-Phong. "gloss" swaps in a microfacet highlight (GGX
// distribution, Smith-Schlick shadowing, Schlick Fresnel; the textbook Cook-Torrance terms), with the
// roughness taken from each material's WOM shininess: tight and bright for shiny metal, broad and soft
// for cloth and skin, and a brighter rim at grazing angles.
THREE.ShaderChunk.lights_phong_pars_fragment = THREE.ShaderChunk.lights_phong_pars_fragment
  .replace('void RE_Direct_BlinnPhong', `#ifdef VIEWER_GLOSS
vec3 viewerGloss( const in vec3 L, const in vec3 V, const in vec3 N, const in vec3 F0, const in float shininess ) {
	float rough = clamp( pow( 2.0 / ( max( shininess, 2.0 ) + 2.0 ), 0.25 ), 0.08, 1.0 );
	float a2 = rough * rough * rough * rough;
	vec3 H = normalize( L + V );
	float nh = saturate( dot( N, H ) ), nl = saturate( dot( N, L ) ), nv = max( saturate( dot( N, V ) ), 1e-3 ), vh = saturate( dot( V, H ) );
	float den = nh * nh * ( a2 - 1.0 ) + 1.0;
	float D = a2 / ( PI * den * den );
	float k = rough * rough * 0.5;
	float G = ( nl / ( nl * ( 1.0 - k ) + k ) ) * ( nv / ( nv * ( 1.0 - k ) + k ) );
	vec3 F = F_Schlick( F0, 1.0, vh );
	return min( F * ( G * D ) / max( 4.0 * nl * nv, 1e-3 ), vec3( 40.0 ) );
}
#endif
void RE_Direct_BlinnPhong`)
  .replace('BRDF_BlinnPhong( directLight.direction, geometryViewDir, geometryNormal, material.specularColor, material.specularShininess )',
    `
#ifdef VIEWER_GLOSS
	viewerGloss( directLight.direction, geometryViewDir, geometryNormal, material.specularColor, material.specularShininess )
#else
	BRDF_BlinnPhong( directLight.direction, geometryViewDir, geometryNormal, material.specularColor, material.specularShininess )
#endif
	`);
try { const L = JSON.parse(localStorage.getItem('womviewer.look') || '{}'); if (L.shine) S.shine = L.shine; if (typeof L.cleanEdges === 'boolean') S.cleanEdges = L.cleanEdges; } catch (e) { /* defaults */ }
function saveLook() { try { localStorage.setItem('womviewer.look', JSON.stringify({ shine: S.shine, cleanEdges: S.cleanEdges })); } catch (e) { /* ignore */ } }
function syncShine() {
  const want = S.shine === 'gloss';
  scene.traverse((o) => {
    if (!o.isMesh) return;
    for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
      if (!m || !m.isMeshPhongMaterial || m.userData.gloss === want) continue;
      m.defines = { ...(m.defines || {}) }; if (want) m.defines.VIEWER_GLOSS = ''; else delete m.defines.VIEWER_GLOSS;
      m.userData.gloss = want; m.needsUpdate = true;
    }
  });
}
function renderView() {
  syncShine();
  if (CMP.on && CMP.twin && S.current && CMP.twin.of === S.current) renderCompare();
  else renderer.render(scene, camera);
}
function loop() {
  requestAnimationFrame(loop);
  if (S.exporting) return;   // the exporter drives the frames itself
  resize();
  const now = performance.now(); const dt = Math.min(0.1, (now - S.last) / 1000); S.last = now;
  if (S.mixer) {
    S.mixer.update(dt);
    if (S.action) {
      const d = S.action.getClip().duration || 1;
      const t = S.action.time % d;
      const sl = $('#anim-time'); if (sl && !sl.matches(':active')) sl.value = String(t / d * 1000);
      const lab = $('#anim-clock'); if (lab) lab.textContent = t.toFixed(2) + ' / ' + d.toFixed(2) + ' s';
    }
  }
  controls.update();
  renderView();
}
loop();


// ------------------------------------------------------------------ export: picture, animated GIF, AVI
const EXPORT = { size: 'view', fps: 24 };
function hideHelpers() {
  const keep = STUDIO.objs.map((o) => [o.marker.visible, o.aim.visible]);
  STUDIO.objs.forEach((o) => { o.marker.visible = false; o.aim.visible = false; });
  return () => STUDIO.objs.forEach((o, i) => { [o.marker.visible, o.aim.visible] = keep[i]; });
}
function exportSize() {
  const c = renderer.domElement, W = c.width, H = c.height;
  const want = EXPORT.size === 'view' ? W : Number(EXPORT.size);
  const k = Math.min(1, want / W);
  return [Math.max(2, Math.round(W * k / 2) * 2), Math.max(2, Math.round(H * k / 2) * 2)];
}
function baseName() { return S.current ? S.current.path.split('/').pop().replace(/\.(wom|obj)$/i, '') : 'view'; }
function saveBlob(blob, name) { const a = el('a', { href: URL.createObjectURL(blob), download: name }); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); }
async function exportPng() {
  const restore = hideHelpers(); renderView();
  const [w, h] = exportSize(), t = document.createElement('canvas'); t.width = w; t.height = h;
  t.getContext('2d').drawImage(renderer.domElement, 0, 0, w, h);
  restore();
  t.toBlob((b) => saveBlob(b, baseName() + '.png'), 'image/png');
}
/** step the playing animation frame by frame (3 loops) and save it as an animated GIF or an AVI */
async function exportAnim(kind) {
  const act = S.action; if (!act || !S.mixer) { toast('Play an animation first'); return; }
  const clip = act.getClip(), speed = Math.abs(act.timeScale) || 1;
  const fps = kind === 'gif' ? Math.min(EXPORT.fps, 25) : EXPORT.fps;
  const n = Math.max(1, Math.round(clip.duration / speed * fps)) * 3;
  const [w, h] = exportSize();
  const t = document.createElement('canvas'); t.width = w; t.height = h; const tc = t.getContext('2d', { willReadFrequently: true });
  S.exporting = true; const restore = hideHelpers(); const was = act.paused;
  const frames = [];
  try {
    for (let i = 0; i < n; i++) {
      act.paused = false; act.time = ((i / fps) * speed) % clip.duration; S.mixer.update(0);
      if (CMP.twin && CMP.twin.mixer) syncTwin();
      controls.update(); renderView();
      tc.drawImage(renderer.domElement, 0, 0, w, h);
      if (kind === 'gif') frames.push(tc.getImageData(0, 0, w, h).data);
      else frames.push(new Uint8Array(await (await new Promise((res) => t.toBlob(res, 'image/jpeg', 0.92))).arrayBuffer()));
      if (i % 4 === 0) { status.set(`Recording ${kind.toUpperCase()} frame ${i + 1}/${n}`, i / n); await tick(); }
    }
    status.set('Encoding ' + kind.toUpperCase());
    await tick();
    const data = kind === 'gif' ? encodeGif(frames, w, h, Math.round(100 / fps)) : encodeAvi(frames, w, h, fps);
    saveBlob(new Blob([data], { type: kind === 'gif' ? 'image/gif' : 'video/avi' }), `${baseName()}_${(S.animInfo ? S.animInfo.name : clip.name).replace(/\.wom$/i, '')}.${kind}`);
    status.done(`Saved ${kind.toUpperCase()}: ${w}x${h}, ${n} frames at ${fps} fps (3 loops), ${(data.length / 1e6).toFixed(1)} MB`);
  } catch (e) { status.done(); toast('Export failed: ' + e.message); }
  finally { act.paused = was; restore(); S.exporting = false; }
}
function renderExportPanel(P) {
  const anim = !!S.action;
  P.append(section('Export',
    select('Size', [['view', 'as shown'], ['1920', '1920 wide'], ['1280', '1280 wide'], ['960', '960 wide'], ['640', '640 wide'], ['480', '480 wide']], EXPORT.size, (v) => { EXPORT.size = v; }),
    select('Frames per second', [['15', '15'], ['20', '20'], ['24', '24'], ['30', '30']], String(EXPORT.fps), (v) => { EXPORT.fps = Number(v); }),
    el('div', { class: 'btns' },
      el('button', { onclick: exportPng }, 'Picture (.png)'),
      el('button', { onclick: () => exportAnim('gif') }, 'Animation (.gif)'),
      el('button', { onclick: () => exportAnim('avi') }, 'Animation (.avi)')),
    el('p', { class: 'hint' }, (anim ? 'Animations are recorded frame by frame: the playing animation 3 times, at its speed. ' : 'Play an animation to save it as .gif or .avi. ') +
      'Light markers are left out. GIF is at most 25 fps and 256 colours (use 640 or 480 wide to keep it small); AVI is Motion-JPEG.')));
}

// ------------------------------------------------------------------ photo studio lighting
// Lights are placed around the model like studio lamps: angle around it, height (elevation) and
// distance (in model sizes), all relative to the model's centre, so a setup works for a ring or a ship.
const STUDIO = {
  focus: { c: new THREE.Vector3(0, 1, 0), r: 2, floor: 0 },
  ambient: 0.35, ambientRGB: [200, 210, 230], ground: 0.5, selected: 0, keys: true,
  background: [43, 47, 54], floor: 'grid', tone: 'none', exposure: 1.0, markers: true,
  lights: [], objs: [], hemi: null, floorMesh: null, open: { env: true },
};
const STUDIO_TYPES = [['point', 'bulb (point)'], ['spot', 'spotlight'], ['sun', 'sun (directional)']];
function studioLight(o = {}) {
  return { on: true, type: 'point', rgb: [255, 255, 255], power: 1.0, angle: 35, height: 40, dist: 2.0, range: 0, cone: 30, inner: 18, shadow: false, turn: 0, tilt: 0, ...o };
}
const STUDIO_PRESETS = {
  'One white light (default)': { ambient: 0.35, ambientRGB: [200, 210, 230], lights: [studioLight()] },
  'Classic three-point': { ambient: 0.2, ambientRGB: [200, 210, 230], lights: [
    studioLight({ angle: 40, height: 35, power: 1.1 }),
    studioLight({ angle: -55, height: 15, power: 0.45, rgb: [200, 220, 255] }),
    studioLight({ angle: 170, height: 45, power: 0.9, type: 'spot', cone: 35, inner: 20 })] },
  'Torch-lit night': { ambient: 0.06, ambientRGB: [60, 70, 110], background: [12, 14, 22], lights: [
    studioLight({ angle: 60, height: 10, dist: 1.2, power: 1.4, rgb: [255, 140, 50], shadow: true }),
    studioLight({ angle: -120, height: 50, dist: 3, power: 0.25, rgb: [110, 130, 255] })] },
  'Moonlight': { ambient: 0.1, ambientRGB: [70, 85, 130], background: [10, 13, 24], lights: [
    studioLight({ type: 'sun', angle: -30, height: 55, power: 0.8, rgb: [160, 180, 255] })] },
  'Neon (two dyed rims)': { ambient: 0.05, ambientRGB: [40, 30, 60], background: [8, 6, 14], tone: 'aces', lights: [
    studioLight({ angle: 120, height: 20, dist: 1.4, power: 1.6, rgb: [255, 40, 200] }),
    studioLight({ angle: -120, height: 20, dist: 1.4, power: 1.6, rgb: [30, 230, 255] }),
    studioLight({ angle: 0, height: 60, dist: 2.5, power: 0.25 })] },
  'Daylight': { ambient: 0.7, ambientRGB: [190, 215, 255], background: [150, 180, 215], lights: [
    studioLight({ type: 'sun', angle: 35, height: 50, power: 1.3, rgb: [255, 244, 225] })] },
};
function studioPreset(name) {
  const p = STUDIO_PRESETS[name]; if (!p) return;
  Object.assign(STUDIO, { ambient: 0.35, ambientRGB: [200, 210, 230], background: [43, 47, 54], tone: 'none', exposure: 1.0 },
    JSON.parse(JSON.stringify({ ...p, lights: undefined })), { lights: p.lights.map((l) => ({ ...l })) });
  applyStudio();
}
const rgbColor = (rgb) => new THREE.Color().setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, THREE.SRGBColorSpace);
function studioPos(l) {
  const { c, r } = STUDIO.focus, a = THREE.MathUtils.degToRad(l.angle), h = THREE.MathUtils.degToRad(l.height);
  const d = l.dist * r;
  return new THREE.Vector3(c.x + Math.sin(a) * Math.cos(h) * d, c.y + Math.sin(h) * d, c.z + Math.cos(a) * Math.cos(h) * d);
}
function applyStudio() {
  // rebuild the light objects only when the count or a type changed; otherwise just update them
  const sig = STUDIO.lights.map((l) => l.type).join(',');
  if (STUDIO.sig !== sig) {
    for (const o of STUDIO.objs) { scene.remove(o.light); if (o.light.target) scene.remove(o.light.target); scene.remove(o.marker); scene.remove(o.aim); o.light.dispose && o.light.dispose(); }
    STUDIO.objs = STUDIO.lights.map((l) => {
      const light = l.type === 'sun' ? new THREE.DirectionalLight() : l.type === 'spot' ? new THREE.SpotLight() : new THREE.PointLight();
      if (light.target) scene.add(light.target);
      const marker = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), new THREE.MeshBasicMaterial());
      marker.userData.studioMarker = true;
      const aim = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), new THREE.LineBasicMaterial());
      scene.add(light, marker, aim);
      return { light, marker, aim };
    });
    STUDIO.sig = sig;
  }
  if (!STUDIO.hemi) { STUDIO.hemi = new THREE.HemisphereLight(); scene.add(STUDIO.hemi); }
  const { c, r, floor } = STUDIO.focus;
  const amb = rgbColor(STUDIO.ambientRGB);
  STUDIO.hemi.color.copy(amb); STUDIO.hemi.groundColor.copy(amb).multiplyScalar(STUDIO.ground);
  STUDIO.hemi.intensity = STUDIO.ambient * 3;
  STUDIO.lights.forEach((l, i) => {
    const { light, marker, aim } = STUDIO.objs[i];
    light.visible = l.on; light.color.copy(rgbColor(l.rgb));
    light.position.copy(studioPos(l));
    // aim: starts pointing at the model's centre, then turned left/right and tilted up/down
    const toC = c.clone().sub(light.position), len = toC.length() || r;
    const dir = toC.clone().normalize();
    dir.applyAxisAngle(new THREE.Vector3(0, 1, 0), THREE.MathUtils.degToRad(-(l.turn || 0)));
    const side = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0));
    if (side.lengthSq() > 1e-6) dir.applyAxisAngle(side.normalize(), THREE.MathUtils.degToRad(l.tilt || 0));
    const tgt = light.position.clone().addScaledVector(dir, len);
    if (light.target) { light.target.position.copy(tgt); light.target.updateMatrixWorld(); }
    aim.geometry.setFromPoints([light.position, light.position.clone().addScaledVector(dir, Math.min(len, r * 0.6))]);
    aim.material.color.copy(rgbColor(l.rgb));
    aim.visible = STUDIO.markers && l.on && l.type !== 'point';
    if (l.type === 'sun') light.intensity = l.power * 3;
    else { light.intensity = l.power * 4 * Math.pow(l.dist * r, 2); light.decay = 2; light.distance = l.range > 0 ? l.range * r : 0; }
    // point/spot: intensity scaled with distance so "power 1" looks the same on a ring and on a ship
    if (l.type === 'spot') {   // outer angle = cone edge, inner angle = where the fade to the edge starts
      const outer = Math.max(2, Math.min(89, l.cone)), inner = Math.max(0, Math.min(outer, l.inner ?? outer * 0.6));
      light.angle = THREE.MathUtils.degToRad(outer); light.penumbra = 1 - inner / outer;
    }
    light.castShadow = !!l.shadow && l.on;
    if (light.castShadow) {
      light.shadow.mapSize.set(1024, 1024); light.shadow.bias = -0.0005; light.shadow.normalBias = r * 0.002;
      const cam = light.shadow.camera;
      if (cam.isOrthographicCamera) { cam.left = cam.bottom = -r * 1.2; cam.right = cam.top = r * 1.2; }
      cam.near = r * 0.02; cam.far = r * (l.dist + 3); cam.updateProjectionMatrix && cam.updateProjectionMatrix();
    }
    marker.visible = STUDIO.markers && l.on; marker.scale.setScalar(r * 0.03);
    marker.material.color.copy(rgbColor(l.rgb)); marker.position.copy(light.position);
  });
  scene.background = rgbColor(STUDIO.background);
  renderer.toneMapping = { none: THREE.NoToneMapping, aces: THREE.ACESFilmicToneMapping, agx: THREE.AgXToneMapping, neutral: THREE.NeutralToneMapping }[STUDIO.tone] ?? THREE.NoToneMapping;
  renderer.toneMappingExposure = STUDIO.exposure;
  // floor: grid helper, a solid floor that catches shadows, or nothing
  grid.visible = STUDIO.floor === 'grid';
  if (!STUDIO.floorMesh) {
    STUDIO.floorMesh = new THREE.Mesh(new THREE.CircleGeometry(1, 64), new THREE.MeshStandardMaterial({ roughness: 0.95 }));
    STUDIO.floorMesh.rotation.x = -Math.PI / 2; scene.add(STUDIO.floorMesh);
  }
  const fm = STUDIO.floorMesh;
  fm.visible = STUDIO.floor === 'solid' || STUDIO.floor === 'shadow';
  fm.material = STUDIO.floor === 'shadow' ? (STUDIO.shadowMat ||= new THREE.ShadowMaterial({ opacity: 0.45 })) : (STUDIO.solidMat ||= new THREE.MeshStandardMaterial({ roughness: 0.95 }));
  if (STUDIO.floor === 'solid') fm.material.color.copy(rgbColor(STUDIO.background)).multiplyScalar(1.25);
  fm.position.set(c.x, floor - r * 0.001, c.z); fm.scale.setScalar(r * 6); fm.receiveShadow = true;
  const anyShadow = STUDIO.lights.some((l) => l.on && l.shadow);
  if (renderer.shadowMap.enabled !== anyShadow) {   // materials must recompile when shadows switch on/off
    renderer.shadowMap.enabled = anyShadow;
    scene.traverse((o) => { if (o.isMesh && o.material) [].concat(o.material).forEach((m) => { m.needsUpdate = true; }); });
  }
  STUDIO.objs.forEach((o, i) => { o.marker.scale.setScalar(r * (i === STUDIO.selected ? 0.045 : 0.03)); });
  for (const c of [S.current, CMP.twin]) if (c) c.base.group.traverse((o) => { if (o.isMesh) { o.castShadow = anyShadow; o.receiveShadow = anyShadow; } });
}
function rgbToHsl(rgb) {
  const c = new THREE.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255), h = {}; c.getHSL(h);
  return [Math.round(h.h * 360), Math.round(h.s * 100), Math.round(h.l * 100)];
}
function hslToRgb(h, s, l) { const c = new THREE.Color().setHSL(h / 360, s / 100, l / 100); return [c.r, c.g, c.b].map((x) => Math.round(x * 255)); }
// photo-mode keys for the open light: A/D around, W/S closer/further, R/F up/down, Shift = bigger steps
window.addEventListener('keydown', (e) => {
  if (!STUDIO.keys || e.ctrlKey || e.metaKey || e.altKey) return;
  const a = document.activeElement;
  if (a && (a.tagName === 'TEXTAREA' || a.tagName === 'SELECT' || (a.tagName === 'INPUT' && !/^(range|checkbox|color)$/.test(a.type)))) return;
  const l = STUDIO.lights[STUDIO.selected]; if (!l) return;
  const st = e.shiftKey ? 10 : 2;
  const moves = { a: () => { l.angle -= st; }, d: () => { l.angle += st; },
    r: () => { l.height = Math.min(89, l.height + st); }, f: () => { l.height = Math.max(-89, l.height - st); },
    w: () => { l.dist = Math.max(0.3, +(l.dist - st * 0.025).toFixed(3)); }, s: () => { l.dist = Math.min(6, +(l.dist + st * 0.025).toFixed(3)); },
    arrowleft: () => { l.turn = Math.max(-90, (l.turn || 0) - st); }, arrowright: () => { l.turn = Math.min(90, (l.turn || 0) + st); },
    arrowup: () => { l.tilt = Math.min(90, (l.tilt || 0) + st); }, arrowdown: () => { l.tilt = Math.max(-90, (l.tilt || 0) - st); } };
  const m = moves[e.key.toLowerCase()]; if (!m) return;
  e.preventDefault(); m();
  l.angle = ((l.angle + 540) % 360) - 180;
  applyStudio();
  clearTimeout(STUDIO.keyTimer); STUDIO.keyTimer = setTimeout(renderPanels, 250);
});
function placeLightAtCamera(l) {   // like a photo mode: the light starts where you are looking from
  const { c, r } = STUDIO.focus, v = camera.position.clone().sub(c), d = v.length() || r;
  l.dist = Math.max(0.3, Math.min(6, d / r));
  l.height = THREE.MathUtils.radToDeg(Math.asin(Math.max(-1, Math.min(1, v.y / d))));
  l.angle = THREE.MathUtils.radToDeg(Math.atan2(v.x, v.z));
}
function renderStudioPanel(P) {
  const live = (fn) => (e) => { fn(e); applyStudio(); };            // update the scene while dragging
  const rebuild = (fn) => (e) => { fn(e); applyStudio(); renderPanels(); };
  const slider = (label, min, max, step, val, fn) => {
    const out = el('span', { class: 'kv val' }, String(val));
    return el('label', { class: 'row' }, el('span', {}, label),
      el('input', { type: 'range', min, max, step, value: val, oninput: live((e) => { fn(Number(e.target.value)); out.textContent = e.target.value; }) }), out);
  };
  const hex = (rgb) => '#' + rgb.map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');
  const rgbRow = (label, rgb) => {
    const nums = rgb.map((v, i) => el('input', { type: 'number', min: 0, max: 255, value: v, class: 'rgb',
      onchange: rebuild((e) => { rgb[i] = Math.max(0, Math.min(255, Number(e.target.value) || 0)); }) }));
    return el('div', { class: 'row' }, el('span', {}, label), el('div', { class: 'dyepick nomargin' },
      el('input', { type: 'color', value: hex(rgb), oninput: live((e) => { const v = e.target.value; [1, 3, 5].forEach((k, i) => { rgb[i] = parseInt(v.slice(k, k + 2), 16); nums[i].value = rgb[i]; }); }) }), ...nums));
  };
  // hue / saturation / luminance like a game photo mode; they drive the same RGB values
  const hslRows = (l) => {
    const hsl = rgbToHsl(l.rgb);
    const set = (i) => (v) => { hsl[i] = v; const c = hslToRgb(...hsl); for (let k = 0; k < 3; k++) l.rgb[k] = c[k]; };
    const bar = (row, css) => { row.classList.add('hslrow'); row.querySelector('input').style.background = css; return row; };
    return [bar(slider('Hue', 0, 360, 1, hsl[0], set(0)), 'linear-gradient(90deg,#f00,#ff0,#0f0,#0ff,#00f,#f0f,#f00)'),
      bar(slider('Saturation', 0, 100, 1, hsl[1], set(1)), `linear-gradient(90deg,#808080,hsl(${hsl[0]},100%,50%))`),
      bar(slider('Luminance', 0, 100, 1, hsl[2], set(2)), `linear-gradient(90deg,#000,hsl(${hsl[0]},${hsl[1]}%,50%),#fff)`)];
  };
  const presets = el('select', { onchange: (e) => { if (e.target.value) { studioPreset(e.target.value); renderPanels(); } } },
    el('option', { value: '' }, 'Load a setup…'), ...Object.keys(STUDIO_PRESETS).map((k) => el('option', { value: k }, k)));
  const body = [
    el('div', { class: 'row' }, el('span', {}, 'Setups'), presets),
    el('details', { class: 'sub', open: STUDIO.open.env, ontoggle: (e) => { STUDIO.open.env = e.target.open; } }, el('summary', {}, 'Scene'),
      slider('Ambient', 0, 1.5, 0.01, STUDIO.ambient, (v) => { STUDIO.ambient = v; }),
      rgbRow('Ambient colour', STUDIO.ambientRGB),
      rgbRow('Background', STUDIO.background),
      select('Floor', [['grid', 'grid'], ['solid', 'solid floor'], ['shadow', 'shadow catcher only'], ['none', 'none']], STUDIO.floor, (v) => { STUDIO.floor = v; applyStudio(); }),
      select('Tone mapping', [['none', 'none (plain)'], ['aces', 'filmic (ACES)'], ['agx', 'AgX (soft highlights)'], ['neutral', 'neutral']], STUDIO.tone, (v) => { STUDIO.tone = v; applyStudio(); renderPanels(); }),
      STUDIO.tone !== 'none' ? slider('Exposure', 0.1, 3, 0.05, STUDIO.exposure, (v) => { STUDIO.exposure = v; }) : null,
      check('Show light markers (hidden in screenshots)', STUDIO.markers, (v) => { STUDIO.markers = v; applyStudio(); }),
      check('Move the open light with keys: A/D around · W/S nearer/further · R/F up/down · arrow keys turn and tilt it (Shift = big steps)', STUDIO.keys, (v) => { STUDIO.keys = v; })),
  ];
  STUDIO.lights.forEach((l, i) => {
    STUDIO.open[i] ??= i === 0;
    body.push(el('details', { class: 'sub', open: STUDIO.open[i], ontoggle: (e) => { STUDIO.open[i] = e.target.open; if (e.target.open && STUDIO.selected !== i) { STUDIO.selected = i; applyStudio(); } } },
      el('summary', {}, el('span', { class: 'swatch', style: `background:${hex(l.rgb)}` }), ` Light ${i + 1} · ${STUDIO_TYPES.find((t) => t[0] === l.type)[1]}${l.on ? '' : ' (off)'}`),
      check('On', l.on, (v) => { l.on = v; applyStudio(); renderPanels(); }),
      select('Type', STUDIO_TYPES, l.type, (v) => { l.type = v; applyStudio(); renderPanels(); }),
      check('Shadow', l.shadow, (v) => { l.shadow = v; applyStudio(); }),
      rgbRow('Colour (RGB)', l.rgb),
      ...hslRows(l),
      slider('Brightness', 0, 4, 0.05, l.power, (v) => { l.power = v; }),
      slider('Around (°)', -180, 180, 1, l.angle, (v) => { l.angle = v; }),
      slider('Height (°)', -89, 89, 1, l.height, (v) => { l.height = v; }),
      l.type !== 'sun' ? slider('Distance', 0.3, 6, 0.05, l.dist, (v) => { l.dist = v; }) : null,
      l.type !== 'sun' ? slider('Range (0 = ∞)', 0, 10, 0.1, l.range, (v) => { l.range = v; }) : null,
      l.type !== 'point' ? slider('Turn (°)', -90, 90, 1, l.turn || 0, (v) => { l.turn = v; }) : null,
      l.type !== 'point' ? slider('Tilt (°)', -90, 90, 1, l.tilt || 0, (v) => { l.tilt = v; }) : null,
      l.type !== 'point' ? el('div', { class: 'btns' }, el('button', { onclick: () => { l.turn = 0; l.tilt = 0; applyStudio(); renderPanels(); } }, 'Aim at model')) : null,
      l.type === 'spot' ? slider('Outer angle (°)', 3, 89, 1, l.cone, (v) => { l.cone = v; if (l.inner > v) l.inner = v; }) : null,
      l.type === 'spot' ? slider('Inner angle (°)', 0, 89, 1, l.inner, (v) => { l.inner = Math.min(v, l.cone); }) : null,
      el('div', { class: 'btns' },
        el('button', { title: 'Move this light to where the camera is', onclick: () => { placeLightAtCamera(l); applyStudio(); renderPanels(); } }, 'Place at camera'),
        el('button', { onclick: () => { STUDIO.lights.splice(i + 1, 0, { ...l, rgb: [...l.rgb], angle: l.angle + 60 }); applyStudio(); renderPanels(); } }, 'Copy'),
        el('button', { onclick: () => { STUDIO.lights.splice(i, 1); applyStudio(); renderPanels(); } }, 'Remove'))));
  });
  body.push(el('div', { class: 'btns' },
    el('button', { onclick: () => { if (STUDIO.lights.length >= 8) return toast('8 lights is the limit here'); STUDIO.lights.push(studioLight({ angle: -40 })); STUDIO.open[STUDIO.lights.length - 1] = true; applyStudio(); renderPanels(); } }, '+ Add light'),
    el('button', { onclick: () => { studioPreset('One white light (default)'); renderPanels(); } }, 'Reset')),
    el('p', { class: 'hint' }, 'Lights circle the model: "Around" turns them round it (0 = in front), "Height" raises them, "Distance" and "Range" are in model sizes. Colour as 0-255 RGB (to match dyed lamps from the game) or hue / saturation / luminance. Up to 8 lights; shadows are per light and slower. The open light has the bigger marker and is the one the keys move. Spotlights and suns show a line for where they point: Turn and Tilt aim them away from the model\'s centre (a bulb shines all ways, so it has no aim).'));
  P.append(section('Lighting (photo studio)', ...body));
}
studioPreset('One white light (default)');


// ------------------------------------------------------------------ compare: game files vs extra folders
// The left side is built from the game files only (.jar or game folder); the right side is the normal
// view with your extra folders (custom models, upscaled textures). Same camera, lights and settings.
function twinSig(cur) {
  return JSON.stringify([CMP.left, S.upscale.version, cur.path, cur.overrides, S.tier, cur.gender, cur.underclothes, cur.outfit, cur.outfitVariant, cur.outfitDye, cur.armourDyeStrength,
    cur.hair, cur.hairColor, cur.hairFit, cur.face, cur.faceLayersOn, cur.meshOverride, cur.dye, cur.mount, cur.metal, cur.jewel, cur.kingdom, S.overlay.version, S.useNormalMaps, S.flipNormalGreen, S.cleanEdges]);
}
function dropTwin() {
  const t = CMP.twin; CMP.twin = null; CMP.sig = '';
  if (t) { scene.remove(t.base.group); t.base.group.traverse((o) => { if (o.geometry) o.geometry.dispose(); }); }
}
function scheduleTwin() {
  if (!CMP.on) return;
  clearTimeout(CMP.timer); CMP.timer = setTimeout(buildTwin, 250);
}
async function buildTwin() {
  if (CMP.building) { CMP.again = true; return; }   // one build at a time: it swaps the global file/texture settings
  CMP.building = true;
  try { do { CMP.again = false; await buildTwinOnce(); } while (CMP.again); } finally { CMP.building = false; }
}
async function buildTwinOnce() {
  const cur = S.current;
  if (!CMP.on || !cur) { dropTwin(); updateCompareUI(); return; }
  if (cur.path.startsWith(EXTRA) && CMP.left.src === 'jar') { dropTwin(); updateCompareUI('This model is only in your custom folder, so the game\'s .jar has nothing to compare it with. Set the left side to "custom folder".'); return; }
  const sig = twinSig(cur);
  if (CMP.twin && CMP.twin.of === cur && CMP.sig === sig) return;
  const gen = ++CMP.gen;
  const was = { o: S.useOverlay, t: S.tier, u: S.useUpscale };
  CMP.main = was;
  let twin = null;
  try {
    // the left side's own files and texture size while it is built
    S.useOverlay = CMP.left.src === 'cf';
    S.useUpscale = CMP.left.tier === '4096' && S.upscale.count > 0; S.tier = CMP.left.tier === '4096' ? '2048' : CMP.left.tier;
    const base = await buildModel(await readModel(cur.path), cur.path, cur.overrides);
    twin = { ...cur, base, attached: {}, of: cur };
    if (twin.dyeMasks) await applyDye(twin);
    if (twin.mount) await applyMount(twin);
    if (twin.metal) applyTints(twin);
    if (twin.character && S.armor) await dressCharacter(twin);
  } catch (e) { console.warn('compare', e); }
  finally { S.useOverlay = was.o; S.tier = was.t; S.useUpscale = was.u; CMP.main = null; }
  if (!twin) return;
  if (gen !== CMP.gen || S.current !== cur || !CMP.on) { twin.base.group.traverse((o) => { if (o.geometry) o.geometry.dispose(); }); return; }
  dropTwin();
  CMP.twin = twin; CMP.sig = sig;
  twin.base.group.visible = false; scene.add(twin.base.group);
  applyStudio();
  updateCompareUI();
}
function syncTwin() {
  const cur = S.current, t = CMP.twin;
  for (const [k, m] of cur.base.meshes) { const o = t.base.meshes.get(k); if (o) o.visible = m.visible; }
  // play the same animation at the same time
  if (S.action && t.base.skel) {
    const clip = S.action.getClip();
    if (t.clip !== clip) { if (t.mixer) t.mixer.stopAllAction(); t.mixer = new THREE.AnimationMixer(t.base.group); t.action = t.mixer.clipAction(clip); t.action.play(); t.clip = clip; }
    t.action.time = S.action.time; t.mixer.update(0);
  } else if (t.mixer) { t.mixer.stopAllAction(); t.mixer = null; t.clip = null; if (t.base.skel && !t.base.skel.shared) t.base.skel.skeleton.pose(); }
}
function renderCompare() {
  const cur = S.current, t = CMP.twin, c = renderer.domElement, w = c.clientWidth, h = c.clientHeight;
  syncTwin();
  const show = (left) => { t.base.group.visible = left; cur.base.group.visible = !left; };
  renderer.setScissorTest(true);
  if (CMP.mode === 'side') {
    const hw = Math.floor(w / 2), asp = camera.aspect;
    camera.aspect = hw / Math.max(1, h); camera.updateProjectionMatrix();
    show(true); renderer.setViewport(0, 0, hw, h); renderer.setScissor(0, 0, hw, h); renderer.render(scene, camera);
    show(false); renderer.setViewport(hw, 0, w - hw, h); renderer.setScissor(hw, 0, w - hw, h); renderer.render(scene, camera);
    camera.aspect = asp; camera.updateProjectionMatrix();
  } else {
    const x = Math.round(w * CMP.split);
    renderer.setViewport(0, 0, w, h);
    show(true); renderer.setScissor(0, 0, x, h); renderer.render(scene, camera);
    show(false); renderer.setScissor(x, 0, w - x, h); renderer.render(scene, camera);
  }
  renderer.setScissorTest(false); renderer.setViewport(0, 0, w, h);
  cur.base.group.visible = true; t.base.group.visible = false;
}
function updateCompareUI(msg) {
  const bar = $('#cmp'); bar.hidden = !CMP.on;
  $('#compare-btn').classList.toggle('on', CMP.on);
  bar.classList.toggle('side', CMP.mode === 'side');
  $('#cmp-line').style.left = (CMP.mode === 'side' ? 50 : CMP.split * 100) + '%';
  $('#cmp-msg').textContent = CMP.on ? (msg || (CMP.twin ? '' : 'Building the left side…')) : '';
  const srcName = (src, tier, up) => (src === 'cf' ? 'Game + custom' : 'Game .jar') + ' · ' + (tier === '4096' && up ? '4096 (upscaled)' : tier);
  $('#cmp .cmp-tag.l').textContent = srcName(CMP.left.src, CMP.left.tier, S.upscale.count);
  const m = CMP.main || { o: S.useOverlay, u: S.useUpscale };
  $('#cmp .cmp-tag.r').textContent = srcName(m.o && S.overlay.files.size ? 'cf' : 'jar', S.tierUI, m.u);
  $('#cmp-msg').hidden = !$('#cmp-msg').textContent;
}
function tierOptions() {
  const o = TIERS.map((t) => [t, t]);
  if (S.upscale.count) o.push(['4096', '4096 (upscale folder)']);
  return o;
}
function setCompare(on) {
  CMP.on = on;
  if (!on) { clearTimeout(CMP.timer); dropTwin(); }
  updateCompareUI(); renderPanels();
  if (on) buildTwin();
}
{ // dragging the wipe line
  let drag = false;
  const line = $('#cmp-line');
  line.addEventListener('pointerdown', (e) => { if (CMP.mode !== 'wipe') return; drag = true; line.setPointerCapture(e.pointerId); e.stopPropagation(); e.preventDefault(); });
  line.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const r = renderer.domElement.getBoundingClientRect();
    CMP.split = Math.max(0.02, Math.min(0.98, (e.clientX - r.left) / r.width)); updateCompareUI();
  });
  line.addEventListener('pointerup', () => { drag = false; });
}

// ------------------------------------------------------------------ textures
// Fully clear pixels in hair, leaf and lace textures usually hold black (or junk) colour. Smoothing and
// the smaller texture sizes blend that into the visible edge, which gives a dark rim. This fills the
// colour (not the alpha) of every clear pixel with the average of the nearest visible pixels: halve
// the picture repeatedly averaging only visible pixels, then fill each clear pixel from the finest
// level that has colour there.
function bleedClearPixels(canvas) {
  const w = canvas.width, h = canvas.height, ctx = canvas.getContext('2d', { willReadFrequently: true });
  const img = ctx.getImageData(0, 0, w, h), d = img.data, CLEAR = 16;
  let any = false; for (let i = 3; i < d.length; i += 4) if (d[i] < CLEAR) { any = true; break; }
  if (!any) return;
  // level 0: colour sums and counts of visible pixels
  const levels = [];
  let lw = w, lh = h, sum = new Float32Array(w * h * 3), cnt = new Float32Array(w * h);
  for (let i = 0, j = 0; i < w * h; i++, j += 4) if (d[j + 3] >= CLEAR) { sum[i * 3] = d[j]; sum[i * 3 + 1] = d[j + 1]; sum[i * 3 + 2] = d[j + 2]; cnt[i] = 1; }
  levels.push({ w: lw, h: lh, sum, cnt });
  while (lw > 1 || lh > 1) {
    const nw = Math.max(1, lw >> 1), nh = Math.max(1, lh >> 1), ns = new Float32Array(nw * nh * 3), nc = new Float32Array(nw * nh);
    for (let y = 0; y < lh; y++) for (let x = 0; x < lw; x++) {
      const a = y * lw + x, b = Math.min(nh - 1, y >> 1) * nw + Math.min(nw - 1, x >> 1);
      nc[b] += cnt[a]; ns[b * 3] += sum[a * 3]; ns[b * 3 + 1] += sum[a * 3 + 1]; ns[b * 3 + 2] += sum[a * 3 + 2];
    }
    lw = nw; lh = nh; sum = ns; cnt = nc; levels.push({ w: lw, h: lh, sum, cnt });
  }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const j = (y * w + x) * 4; if (d[j + 3] >= CLEAR) continue;
    for (let l = 1; l < levels.length; l++) {
      const L = levels[l], k = Math.min(L.h - 1, (y * L.h / h) | 0) * L.w + Math.min(L.w - 1, (x * L.w / w) | 0);
      if (L.cnt[k] > 0) { d[j] = L.sum[k * 3] / L.cnt[k]; d[j + 1] = L.sum[k * 3 + 1] / L.cnt[k]; d[j + 2] = L.sum[k * 3 + 2] / L.cnt[k]; break; }
    }
  }
  ctx.putImageData(img, 0, 0);
}
async function loadImage(path) {
  const key = (S.useOverlay && S.overlay.count ? 'x' : 'g') + (S.useUpscale && S.upscale.count ? 'u' : '') + (S.cleanEdges ? 'e' : '') + '|' + path.toLowerCase();
  if (S.texCache.has(key)) return S.texCache.get(key);
  const p = (async () => {
    const game = getFile(path);
    let over = null;
    if (!path.startsWith(EXTRA)) {
      const cf = S.useOverlay ? S.overlay.find(path) : null;
      const up = S.useUpscale ? S.upscale.find(path) : null;
      // a custom folder file that is just a copy of the game's (same size) doesn't hide the upscaled one
      over = cf && up ? ((game && cf.size === game.size) ? up : cf) : (cf || up);
    }
    const f = over || game; if (!f) return null;
    const fname = over ? (over._rel || over.webkitRelativePath || over.name) : path;
    let canvas, hasAlpha = false, ratio = 1;
    try {
      if (/\.dds$/i.test(fname)) {
        const d = decodeDDS(await f.arrayBuffer());
        canvas = document.createElement('canvas'); canvas.width = d.width; canvas.height = d.height;
        canvas.getContext('2d').putImageData(new ImageData(d.data, d.width, d.height), 0, 0);
        hasAlpha = d.hasAlpha;
      } else {
        const bmp = await createImageBitmap(f.blob ? await f.blob() : f);
        canvas = document.createElement('canvas'); canvas.width = bmp.width; canvas.height = bmp.height;
        const ctx = canvas.getContext('2d'); ctx.drawImage(bmp, 0, 0);
        if (/\.(png|tga)$/i.test(path)) {
          const a = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
          for (let i = 3; i < a.length; i += 4) if (a[i] < 255) { hasAlpha = true; break; }
        }
      }
      if (over && game && /\.dds$/i.test(path)) {
        // how much bigger the replacement is than the game's own file (for placing armour pieces)
        const hb = new DataView(await game.slice(0, 20).arrayBuffer());
        const gw = hb.getUint32(16, true);
        if (gw) ratio = canvas.width / gw;
      }
    } catch (e) { console.warn('texture', fname, e); toast('Could not read texture ' + fname + ': ' + e.message); return null; }
    if (hasAlpha && S.cleanEdges && !/(_pm|_n)\.[^./]+$/i.test(path)) { try { bleedClearPixels(canvas); } catch (e) { console.warn('edges', e); } }
    return { canvas, hasAlpha, path, ratio, replaced: !!over };
  })();
  S.texCache.set(key, p);
  return p;
}
function canvasTexture(canvas) {
  const t = new THREE.CanvasTexture(canvas);
  t.flipY = false; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.needsUpdate = true;
  return t;
}
const rgb = (a) => new THREE.Color(a[0], a[1], a[2]);
const nums = (s) => String(s).split(',').map(Number).filter((x) => !Number.isNaN(x));

async function makeMaterial(mat, modelDir, override) {
  const m = { ...mat };
  if (override) {
    if (override.texture) m.texture = override.texture;
    if (override.specular) m.specular = nums(override.specular);
    if (override.shininess) m.shininess = [Number(override.shininess)];
    if (override.emissive) m.emissive = nums(override.emissive);
  }
  const params = { color: 0xffffff, side: THREE.DoubleSide };
  let info = null;
  if (m.texture) {
    let path = null;
    if (modelDir.startsWith(EXTRA) || modelDir === EXTRA.slice(0, -1)) {
      const k = S.overlay.byName(m.texture); if (k) path = EXTRA + k;
    }
    path = path || S.fs.findTexture(m.texture, modelDir.startsWith(EXTRA) ? '' : modelDir, S.tier);
    if (!path) { const k = S.overlay.byName(m.texture); if (k) path = EXTRA + k; }
    info = path ? await loadImage(path) : null;
    if (!info) toast('Texture not found: ' + m.texture);
  }
  if (info) { params.map = canvasTexture(info.canvas); if (info.hasAlpha) params.alphaTest = 0.5; } else params.color = 0x9aa0a8;
  // normal map found by name like the game: <texture>_n next to the colour texture (e.g. Dog.dds -> Dog_n.dds)
  if (info && S.useNormalMaps) {
    const stem = info.path.replace(/\.[^./]+$/, '');
    for (const ext of ['.dds', '.png', '.tga']) {
      const np = stem + '_n' + ext;
      if (getFile(np) || S.fs.has(np)) {
        const ninfo = await loadImage(np);
        if (ninfo) {
          const nt = new THREE.CanvasTexture(ninfo.canvas);
          nt.flipY = false; nt.colorSpace = THREE.NoColorSpace; nt.wrapS = nt.wrapT = THREE.RepeatWrapping;
          params.normalMap = nt; params.normalScale = new THREE.Vector2(1, S.flipNormalGreen ? 1 : -1);
        }
        break;
      }
    }
  }
  if (m.specular) params.specular = rgb(m.specular); else params.specular = new THREE.Color(0.1, 0.1, 0.1);
  if (m.shininess) params.shininess = Math.max(1, m.shininess[0]);
  if (m.emissive) params.emissive = rgb(m.emissive);
  const out = new THREE.MeshPhongMaterial(params);
  out.userData = { source: m, texPath: info ? info.path : null };
  return out;
}

// ------------------------------------------------------------------ model building
const rowMajor = (a) => new THREE.Matrix4().set(...a);

function buildSkeleton(joints) {
  const bones = joints.map((j) => { const b = new THREE.Bone(); b.name = j.name; return b; });
  const byName = new Map(bones.map((b) => [b.name, b]));
  const roots = [];
  joints.forEach((j, i) => {
    rowMajor(j.bindLocal).decompose(bones[i].position, bones[i].quaternion, bones[i].scale);
    const p = j.parent && byName.get(j.parent);
    if (p) p.add(bones[i]); else roots.push(bones[i]);
  });
  const inverses = joints.map((j) => rowMajor(j.bindWorld).invert());
  return { bones, byName, roots, skeleton: new THREE.Skeleton(bones, inverses) };
}

function buildGeometry(m, boneIndex) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(m.pos, 3));
  g.setAttribute('normal', new THREE.BufferAttribute(m.nrm, 3));
  g.setAttribute('uv', new THREE.BufferAttribute(m.uv, 2));
  const nv = m.pos.length / 3;
  g.setIndex(new THREE.BufferAttribute(nv < 65536 ? new Uint16Array(m.idx) : m.idx, 1));
  if (m.skin && boneIndex) {
    const lists = Array.from({ length: nv }, () => []);
    for (const b of m.skin) { const bi = boneIndex.get(b.joint); if (bi == null) continue; for (const [vi, w] of b.weights) if (vi < nv) lists[vi].push([bi, w]); }
    const si = new Uint16Array(nv * 4), sw = new Float32Array(nv * 4);
    lists.forEach((l, v) => {
      l.sort((a, b) => b[1] - a[1]); const top = l.slice(0, 4); const s = top.reduce((a, x) => a + x[1], 0) || 1;
      top.forEach(([bi, w], k) => { si[v * 4 + k] = bi; sw[v * 4 + k] = w / s; });
      if (!top.length) sw[v * 4] = 1;
    });
    g.setAttribute('skinIndex', new THREE.BufferAttribute(si, 4));
    g.setAttribute('skinWeight', new THREE.BufferAttribute(sw, 4));
  }
  g.computeBoundingBox(); g.computeBoundingSphere();
  return g;
}

/** build a model; skeleton = existing skeleton info to bind to (for hair/helmets sharing the character's bones) */
async function buildModel(wom, path, overrides, shareSkeleton) {
  const group = new THREE.Group(); group.name = path;
  const dir = dirOf(path);
  let skel = null;
  if (wom.joints.length) {
    if (shareSkeleton) {
      // bind to the character's bones by name; inverses from this model's own bind pose
      const bones = wom.joints.map((j) => shareSkeleton.byName.get(j.name) || null);
      if (bones.every(Boolean)) {
        const inverses = wom.joints.map((j) => rowMajor(j.bindWorld).invert());
        skel = { bones, byName: shareSkeleton.byName, roots: [], skeleton: new THREE.Skeleton(bones, inverses), shared: true };
      }
    }
    if (!skel) { skel = buildSkeleton(wom.joints); skel.roots.forEach((r) => group.add(r)); }
  }
  const boneIndex = skel ? new Map(wom.joints.map((j, i) => [j.name, i])) : null;
  const meshes = new Map();
  const ovLower = {};
  for (const [k, v] of Object.entries(overrides || {})) ovLower[k.toLowerCase()] = v;
  const matCache = new Map();
  let i = 0;
  for (const m of wom.meshes) {
    if (++i % 10 === 0) status.set('Building ' + path.split('/').pop() + ' (' + i + '/' + wom.meshes.length + ' meshes)', i / wom.meshes.length);
    const mat0 = m.materials[0] || { texture: '', name: 'default' };
    const mkey = (mat0.name || '') + '|' + mat0.texture;
    if (!matCache.has(mkey)) matCache.set(mkey, makeMaterial(mat0, dir, ovLower[(mat0.name || '').toLowerCase()]));
    const material = await matCache.get(mkey);
    const skinned = !!(m.skin && skel);
    const geo = buildGeometry(m, skinned ? boneIndex : null);
    const mesh = skinned ? new THREE.SkinnedMesh(geo, material) : new THREE.Mesh(geo, material);
    mesh.name = m.name;
    if (skinned) { mesh.bind(skel.skeleton, new THREE.Matrix4()); mesh.frustumCulled = false; }
    const lname = m.name.toLowerCase();
    mesh.visible = !HIDDEN_RE.test(lname) && !(lname.includes('lod') && !lname.includes('lod0'));
    group.add(mesh);
    meshes.set(lname, mesh);
  }
  return { group, meshes, skel, wom, path };
}

function frame(obj) {
  obj.updateMatrixWorld(true);
  const box = new THREE.Box3();
  obj.traverse((o) => { if (o.isMesh && o.visible && o.geometry.boundingBox) { const b = o.geometry.boundingBox.clone().applyMatrix4(o.matrixWorld); box.union(b); } });
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
  const r = Math.max(size.x, size.y, size.z) || 1;
  controls.target.copy(c);
  camera.position.copy(c).add(new THREE.Vector3(0.6, 0.35, 1).normalize().multiplyScalar(r * 1.9));
  camera.near = r / 200; camera.far = r * 200; camera.updateProjectionMatrix();
  scene.remove(grid);
  const step = Math.pow(10, Math.floor(Math.log10(r)));
  grid = new THREE.GridHelper(step * 20, 20, 0x667080, 0x3a404a); grid.position.y = box.min.y; scene.add(grid);
  STUDIO.focus = { c: c.clone(), r, floor: box.min.y };
  applyStudio();
}

// ------------------------------------------------------------------ animations
function clipFromAnim(name, bones, boneNames) {
  const p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3(), M = new THREE.Matrix4();
  let missing = 0;
  const per = [];
  for (const b of bones) {
    if (!b.keys.length) continue;
    if (!boneNames.has(b.name)) { missing++; continue; }
    const times = [], pv = [], qs = [];
    let prev = null;
    for (const k of b.keys) {
      M.set(...k.m).decompose(p, q, s);
      if (prev && prev.dot(q) < 0) q.set(-q.x, -q.y, -q.z, -q.w);
      prev = q.clone();
      times.push(k.t); pv.push(p.x, p.y, p.z); qs.push(q.clone());
    }
    per.push({ name: b.name, times, pv, qs });
  }
  // The game's animations end with one extra key that snaps back towards the rest (T) pose. Drop it when
  // that last step is far bigger than the steps before it, so loops don't flash the T pose.
  const end = Math.max(...per.map((x) => x.times[x.times.length - 1] ?? 0));
  let lastJump = 0, before = 0;
  for (const x of per) {
    const n = x.qs.length; if (n < 4 || x.times[n - 1] !== end) continue;
    lastJump = Math.max(lastJump, x.qs[n - 2].angleTo(x.qs[n - 1]));
    for (let i = Math.max(0, n - 7); i < n - 2; i++) before = Math.max(before, x.qs[i].angleTo(x.qs[i + 1]));
  }
  const dropLast = lastJump > THREE.MathUtils.degToRad(30) && lastJump > before * 1.3;
  const tracks = [];
  for (const x of per) {
    let n = x.times.length;
    if (dropLast && n > 1 && x.times[n - 1] === end) n--;
    const qv = []; for (let i = 0; i < n; i++) qv.push(x.qs[i].x, x.qs[i].y, x.qs[i].z, x.qs[i].w);
    tracks.push(new THREE.VectorKeyframeTrack(x.name + '.position', x.times.slice(0, n), x.pv.slice(0, n * 3)));
    tracks.push(new THREE.QuaternionKeyframeTrack(x.name + '.quaternion', x.times.slice(0, n), qv));
  }
  return { clip: new THREE.AnimationClip(name, -1, tracks), missing, droppedEnd: dropLast };
}
async function playAnim(name, file) {
  const cur = S.current; if (!cur || !cur.base.skel) return;
  const key = file.toLowerCase();
  status.set('Loading animation ' + name);
  let bones = S.animCache.get(key);
  if (!bones) {
    const buf = await readBuf(file);
    if (!buf) { status.done(); toast('Animation file not found: ' + file); return; }
    try { bones = readAnim(buf); } catch (e) { status.done(); toast(file + ' is not an animation file'); return; }
    S.animCache.set(key, bones);
  }
  const { clip } = clipFromAnim(name, bones, cur.base.skel.byName);
  S.animInfo = { name, file };
  stopAnim(false);
  S.mixer = new THREE.AnimationMixer(cur.base.group);
  S.action = S.mixer.clipAction(clip);
  S.action.setLoop($('#anim-loop') && !$('#anim-loop').checked ? THREE.LoopOnce : THREE.LoopRepeat);
  S.action.clampWhenFinished = true;
  S.action.timeScale = Number(($('#anim-speed') || { value: 1 }).value);
  S.action.play();
  status.done();
  const lab = $('#anim-name'); if (lab) lab.textContent = name;
}
function stopAnim(reset = true) {
  if (S.mixer) { S.mixer.stopAllAction(); S.mixer = null; S.action = null; }
  if (reset && S.current && S.current.base.skel && !S.current.base.skel.shared) S.current.base.skel.skeleton.pose();
  const lab = $('#anim-name'); if (lab) lab.textContent = 'bind pose';
}

// ------------------------------------------------------------------ mappings helpers
function computeMapPrefix() {
  const counts = new Map();
  for (const e of S.mappings) {
    const parts = e.file.split('/');
    for (let i = 0; i < parts.length; i++) {
      const t = parts.slice(i).join('/');
      if (S.fs.has(t) || S.overlay.files.has(t.toLowerCase()) || (/\.wom$/i.test(t) && S.overlay.findFile(t))) { const pre = parts.slice(0, i).join('/').toLowerCase(); counts.set(pre, (counts.get(pre) || 0) + 1); break; }
    }
  }
  let best = '', bc = -1;
  for (const [k, v] of counts) if (v > bc || (v === bc && k.length < best.length)) { best = k; bc = v; }
  S.mapPrefix = best ? best + '/' : '';
  S.mapIndex.clear();
  for (const e of S.mappings) S.mapIndex.set(e.key, e);
}
/** game path from mappings ("player/x.wom") -> path in the picked folder, or null */
function gamePath(p) {
  let x = normPath(p);
  if (S.mapPrefix && x.toLowerCase().startsWith(S.mapPrefix)) x = x.slice(S.mapPrefix.length);
  if (S.fs.has(x)) return S.fs.orig.get(x.toLowerCase()) || x;
  if (S.useOverlay && (S.overlay.files.has(x.toLowerCase()) || (/\.wom$/i.test(x) && S.overlay.findFile(x)) || S.overlay.find(x))) return x;
  return null;
}
function mappingsFor(path) {
  const l = path.toLowerCase();
  return S.mappings.filter((e) => { const g = gamePath(e.file); return g && g.toLowerCase() === l; });
}

// ------------------------------------------------------------------ character (player) dressing
function isCharacter(wom) {
  return wom.joints.some((j) => j.name === 'Head') && wom.meshes.some((m) => /^torso\d+mesh$/i.test(m.name));
}
function armorPath(p) {
  // armor.xml paths are relative to armor.xml's folder; the game inserts the resolution folder after "textures/"
  const rel = normPath((S.armorDir ? S.armorDir + '/' : '') + p);
  const m = rel.match(/^(.*?textures)\/(.*)$/i);
  const tries = [];
  if (m) { tries.push(m[1] + '/' + S.tier + '/' + m[2]); for (const t of [...TIERS].reverse()) if (t !== S.tier) tries.push(m[1] + '/' + t + '/' + m[2]); }
  tries.push(rel);
  for (const t of tries) if (S.fs.has(t)) return t;
  return S.fs.findTexture(p.split('/').pop(), dirOf(rel), S.tier);
}
function itemSide(item, gender, variant) {
  const v = item.variants[variant] || item.variants.default || Object.values(item.variants)[0];
  if (!v) return null;
  return v[gender] || v.male || v.female || null;
}
function slotOf(key) { for (const [name, re] of SLOTS) if (re.test(key)) return name; return 'Other'; }

async function composeBody(ch) {
  let size = Number(S.tier);
  {
    const bside = S.armor && S.armor.baseSkin && itemSide(S.armor.baseSkin, ch.gender, 'default');
    const op = bside && bside.ops.find((o) => o.type === 'tex');
    const bp = op && armorPath(op.path); const bimg = bp && await loadImage(bp);
    if (bimg && bimg.replaced) size = Math.min(8192, Math.round(size * bimg.ratio));
  }
  const body = document.createElement('canvas'); body.width = body.height = size;
  const outer = document.createElement('canvas'); outer.width = outer.height = size;
  const bctx = body.getContext('2d'), octx = outer.getContext('2d');
  const sc = size / 2048;
  const base = S.armor ? S.armor['baseSkin'] : null, cloth = S.armor ? S.armor['baseCloth'] : null;
  const g = ch.gender;
  const drawFull = async (item) => {
    const side = item && itemSide(item, g, 'default'); if (!side) return false;
    for (const op of side.ops) if (op.type === 'tex') {
      const p = armorPath(op.path); const img = p && await loadImage(p);
      if (img) { bctx.drawImage(img.canvas, 0, 0, size, size); return true; }
    }
    return false;
  };
  let ok = await drawFull(base);
  if (ok) {
    const px = bctx.getImageData(Math.round(400 * sc), Math.round(300 * sc), Math.max(1, Math.round(64 * sc)), Math.max(1, Math.round(64 * sc))).data;
    let r = 0, gg = 0, b = 0; for (let i = 0; i < px.length; i += 4) { r += px[i]; gg += px[i + 1]; b += px[i + 2]; }
    const n = px.length / 4; ch.skinColour = new THREE.Color(r / n / 255, gg / n / 255, b / n / 255).convertSRGBToLinear();
  }
  if (!ok) { // no armor.xml: use the model's own texture
    const t = ch.base.wom.meshes.find((m) => /^torso/i.test(m.name))?.materials[0]?.texture;
    const p = t && S.fs.findTexture(t, dirOf(ch.base.path), S.tier); const img = p && await loadImage(p);
    if (img) bctx.drawImage(img.canvas, 0, 0, size, size);
  }
  if (ch.underclothes) await drawFull(cloth);
  for (const [slot] of SLOTS) {
    const key = ch.outfit[slot];
    if (!key || !S.armor[key]) continue;
    const side = itemSide(S.armor[key], g, ch.outfitVariant[key] || 'default'); if (!side) continue;
    for (const op of side.ops) {
      if (op.type !== 'tex') continue;
      const cells = CELLS[(op.place || '').toLowerCase()];
      const p = armorPath(op.path); const img = p && await loadImage(p);
      if (!img) { toast('Texture not found: ' + op.path); continue; }
      if (!cells) { if (/skin|cloth/i.test(op.place)) bctx.drawImage(img.canvas, 0, 0, size, size); continue; }
      const tierOf = (p.split('/').find((x) => TIERS.includes(x))) || '2048';
      const k = (2048 / Number(tierOf)) * sc / (img.ratio || 1);
      const dye = ch.outfitDye && ch.outfitDye[slot];
      const src = dye ? tintCanvas(img.canvas, dye, ch.armourDyeStrength ?? 0.5) : img.canvas;
      for (const [x, y] of cells) {
        bctx.drawImage(src, x * sc, y * sc, img.canvas.width * k, img.canvas.height * k);
        octx.drawImage(src, x * sc, y * sc, img.canvas.width * k, img.canvas.height * k);
      }
    }
  }
  return { body, outer };
}

// Armour dye. The dye colour is the colour the piece takes on; the texture keeps its own detail: each
// pixel is made lighter or darker than the dye by how much lighter or darker it is than the area
// around it (a blurred copy). So a white dye comes out white, not grey, and stitching and dents stay.
// Strength mixes between the piece's own colours (0) and the full dye (1).
const lum = (r, g, b) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
function tintCanvas(src, rgb, strength) {
  const w = src.width, h = src.height;
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const x = c.getContext('2d', { willReadFrequently: true }); x.drawImage(src, 0, 0);
  const sw = Math.max(1, w >> 4), sh = Math.max(1, h >> 4), b = document.createElement('canvas'); b.width = sw; b.height = sh;
  const bx = b.getContext('2d'); bx.imageSmoothingQuality = 'high'; bx.drawImage(src, 0, 0, sw, sh);
  const big = document.createElement('canvas'); big.width = w; big.height = h;
  const gx = big.getContext('2d', { willReadFrequently: true }); gx.imageSmoothingQuality = 'high'; gx.drawImage(b, 0, 0, w, h);
  const img = x.getImageData(0, 0, w, h), d = img.data, bl = gx.getImageData(0, 0, w, h).data;
  for (let i = 0; i < d.length; i += 4) {
    if (!d[i + 3]) continue;
    const detail = Math.min(1.35, Math.max(0.3, lum(d[i], d[i + 1], d[i + 2]) / Math.max(10, lum(bl[i], bl[i + 1], bl[i + 2]))));
    for (let k = 0; k < 3; k++) d[i + k] = Math.min(255, d[i + k] + (rgb[k] * detail - d[i + k]) * strength);
  }
  x.putImageData(img, 0, 0);
  return c;
}

// The face texture: the head type (textures/<size>/Face/Default/<gender>/headType) is the whole face
// with the ears and a see-through eye opening. The eye white and the iris (eyeColor, Default or Hots)
// go under that opening, the eye shape (eyelids and lashes, with its own opening) on top of it.
const FACE_POS = { eyeType: [0, 356], nose: [0, 356], lowerFace: [0, 516], eyebrow: [20, 335], complexion: [0, 356], facialHair: [0, 247] };
const FACE_GEOM = new WeakMap();
function alphaInfo(canvas) {
  if (FACE_GEOM.has(canvas)) return FACE_GEOM.get(canvas);
  const w = canvas.width, h = canvas.height, a = canvas.getContext('2d').getImageData(0, 0, w, h).data;
  const clear = new Uint8Array(w * h); let x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let i = 0; i < w * h; i++) {
    if (a[i * 4 + 3] < 128) clear[i] = 1;
    else { const x = i % w, y = (i / w) | 0; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  }
  // see-through pixels not reachable from the border = the opening(s)
  const out = new Uint8Array(w * h), st = [];
  for (let x = 0; x < w; x++) { st.push(x, (h - 1) * w + x); }
  for (let y = 0; y < h; y++) { st.push(y * w, y * w + w - 1); }
  while (st.length) { const i = st.pop(); if (out[i] || !clear[i]) continue; out[i] = 1; const x = i % w; if (x > 0) st.push(i - 1); if (x < w - 1) st.push(i + 1); if (i >= w) st.push(i - w); if (i < w * (h - 1)) st.push(i + w); }
  let n = 0, sx = 0, sy = 0, hx0 = w, hy0 = h, hx1 = -1, hy1 = -1;
  for (let i = 0; i < w * h; i++) if (clear[i] && !out[i]) { const x = i % w, y = (i / w) | 0; n++; sx += x; sy += y; if (x < hx0) hx0 = x; if (x > hx1) hx1 = x; if (y < hy0) hy0 = y; if (y > hy1) hy1 = y; }
  const info = { box: x1 >= 0 ? { x0, y0, x1, y1, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 } : null,
    hole: n > 10 ? { x0: hx0, y0: hy0, x1: hx1, y1: hy1, cx: sx / n, cy: sy / n } : null };
  FACE_GEOM.set(canvas, info);
  return info;
}
/** the chosen hair colour as a CSS colour (average of the game's hairColorN texture), or null */
async function hairTint(ch) {
  if (ch.hairColor === '' || ch.hairColor == null) return null;
  const ce = S.mapIndex.get(`hairColor${ch.hairColor}Default`); const cp = ce && gamePath(ce.file);
  const img = cp && await loadImage(cp); if (!img) return null;
  const c = img.canvas.getContext('2d').getImageData(0, 0, img.canvas.width, img.canvas.height).data;
  let r = 0, g = 0, b = 0, n = 0; for (let i = 0; i < c.length; i += 16) { r += c[i]; g += c[i + 1]; b += c[i + 2]; n++; }
  return `rgb(${Math.round(r / n)},${Math.round(g / n)},${Math.round(b / n)})`;
}
/** the game's own file for a path (no custom / upscale folder), as a canvas */
async function gameCanvas(path) {
  const f = S.fs.get(path); if (!f) return null;
  try {
    if (/\.dds$/i.test(path)) {
      const d = decodeDDS(await f.arrayBuffer());
      const c = document.createElement('canvas'); c.width = d.width; c.height = d.height;
      c.getContext('2d').putImageData(new ImageData(d.data, d.width, d.height), 0, 0); return c;
    }
    const bmp = await createImageBitmap(f.blob ? await f.blob() : f);
    const c = document.createElement('canvas'); c.width = bmp.width; c.height = bmp.height; c.getContext('2d').drawImage(bmp, 0, 0); return c;
  } catch (e) { return null; }
}
/** average colour change (per channel) from the game's file to the replacement, over a rectangle given in
 *  0..1 of the image, counting only solid skin-bright pixels */
function shiftOf(now, orig, r = [0, 0, 1, 1], mask = null) {
  const w = Math.max(1, Math.round(orig.width * r[2])), h = Math.max(1, Math.round(orig.height * r[3]));
  const grab = (c) => { const t = document.createElement('canvas'); t.width = w; t.height = h;
    t.getContext('2d').drawImage(c, r[0] * c.width, r[1] * c.height, r[2] * c.width, r[3] * c.height, 0, 0, w, h); return t.getContext('2d').getImageData(0, 0, w, h).data; };
  const a = grab(now), b = grab(orig), m = mask ? grab(mask) : null;
  const sa = [0, 0, 0], sb = [0, 0, 0]; let n = 0;
  for (let i = 0; i < a.length; i += 4) {
    if (a[i + 3] < 250 || b[i + 3] < 250 || (m && m[i + 3] < 250)) continue;
    if (b[i] + b[i + 1] + b[i + 2] < 150) continue;
    for (let c = 0; c < 3; c++) { sa[c] += a[i + c]; sb[c] += b[i + c]; } n++;
  }
  return n < 30 ? [1, 1, 1] : sa.map((v, c) => v / Math.max(1, sb[c]));
}
/** a copy of an image with each channel multiplied */
function tinted(canvas, g) {
  const t = document.createElement('canvas'); t.width = canvas.width; t.height = canvas.height;
  const tc = t.getContext('2d'); tc.drawImage(canvas, 0, 0);
  const d = tc.getImageData(0, 0, t.width, t.height);
  for (let i = 0; i < d.data.length; i += 4) for (let c = 0; c < 3; c++) d.data[i + c] = Math.min(255, d.data[i + c] * g[c]);
  tc.putImageData(d, 0, 0); return t;
}
/** the pupil of an iris texture: middle of its darkest opaque pixels */
function pupilOf(canvas) {
  const w = canvas.width, h = canvas.height, d = canvas.getContext('2d').getImageData(0, 0, w, h).data;
  const lum = []; for (let i = 0; i < w * h; i++) if (d[i * 4 + 3] > 200) lum.push([d[i * 4] + d[i * 4 + 1] + d[i * 4 + 2], i]);
  if (!lum.length) return null;
  lum.sort((a, b) => a[0] - b[0]);
  const n = Math.max(1, Math.round(lum.length * 0.06)); let sx = 0, sy = 0;
  for (let j = 0; j < n; j++) { sx += lum[j][1] % w; sy += (lum[j][1] / w) | 0; }
  return { cx: sx / n, cy: sy / n };
}
async function composeFace(ch) {
  const fem = ch.gender === 'female', K = ch.kingdom === 'Hots' ? 'Hots' : 'Default';
  const tiers = [S.tier, ...[...TIERS].reverse().filter((t) => t !== S.tier)];
  const find = (keys) => { for (const t of tiers) for (const k of keys(t)) { const e = S.mapIndex.get(k); if (e) { const p = gamePath(e.file); if (p) return p; } } return null; };
  const keyFor = (layer, n) => find((t) => {
    const v = `${layer}${n}`;
    if (layer === 'eyeColor') return fem ? [`${v}.female${K}.${t}`, `${v}.femaleDefault.${t}`, `${v}${K}.${t}`, `${v}Default.${t}`] : [`${v}${K}.${t}`, `${v}Default.${t}`];
    return fem ? [`${v}.female.${t}`, `${v}.${t}`] : [`${v}.${t}`];
  });
  const on = (k) => ch.faceLayersOn[k] !== false && ch.face[k] != null && ch.face[k] !== '';
  const used = [], skipped = [];
  ch.faceUsed = used; ch.faceSkipped = skipped;
  const baseP = keyFor('upperFace', on('upperFace') ? ch.face.upperFace : 0);
  const base = baseP && await loadImage(baseP);
  if (!base) return null;
  const W = base.canvas.width, H = base.canvas.height;
  const canvas = document.createElement('canvas'); canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d');
  const hole = alphaInfo(base.canvas).hole;
  const scaleOf = (img) => (base.ratio || 1) / (img.ratio || 1);
  const name = (p) => p.split('/').pop();
  // a layer the size of the head texture covers it all; a smaller one is centred on the eye opening
  const drawAt = (img, cx, cy, ref) => {
    const k = scaleOf(img), r = ref || alphaInfo(img.canvas).box || { cx: img.canvas.width / 2, cy: img.canvas.height / 2 };
    ctx.drawImage(img.canvas, cx - r.cx * k, cy - r.cy * k, img.canvas.width * k, img.canvas.height * k);
  };
  const full = (img) => Math.abs(img.canvas.width * scaleOf(img) - W) < 3 && Math.abs(img.canvas.height * scaleOf(img) - H) < 3;
  if (hole) {   // 1) under the head: eye white, then the iris
    // the pupil goes to the middle of the eye shape's opening, a little above it (as in the game's
    // own composed faces, textures/DefaultLoad); without an eye shape, the head's opening
    let ex = hole.cx, ey = hole.cy;
    const esp = on('eyeType') ? keyFor('eyeType', ch.face.eyeType) : null; const es = esp && await loadImage(esp);
    if (es && !full(es)) { const eh = alphaInfo(es.canvas).hole; if (eh) { const k = scaleOf(es), k0 = W / 1024; ex = FACE_POS.eyeType[0] * k0 + eh.cx * k; ey = FACE_POS.eyeType[1] * k0 + eh.cy * k; } }
    ey -= 4 * (W / 1024);
    ctx.fillStyle = '#e4ddd6'; ctx.fillRect(hole.x0 - 3, hole.y0 - 3, hole.x1 - hole.x0 + 6, hole.y1 - hole.y0 + 6);
    const wp = find((t) => (fem ? [`eyeWhite.female.${t}`, `eyeWhite.${t}`] : [`eyeWhite.${t}`]));
    const white = wp && await loadImage(wp);
    if (white) { if (full(white)) ctx.drawImage(white.canvas, 0, 0, W, H); else drawAt(white, ex, ey); used.push('eye white: ' + name(wp)); }
    if (on('eyeColor')) {
      const ip = keyFor('eyeColor', ch.face.eyeColor); const iris = ip && await loadImage(ip);
      if (iris) { if (full(iris)) ctx.drawImage(iris.canvas, 0, 0, W, H); else drawAt(iris, ex, ey, pupilOf(iris.canvas)); used.push('Eye colour (' + K + '): ' + name(ip)); }
    }
  }
  ctx.drawImage(base.canvas, 0, 0, W, H);   // 2) the head type
  used.push('Head type: ' + name(baseP));
  // 3) the other layers at their places; the eye shape last but the brows and beard so lids sit on top
  const k0 = W / 1024;
  let baseOrig = null;
  const place = async (ui, layer) => {
    if (!on(layer)) return null;
    const p = keyFor(layer, ch.face[layer]); if (!p) return null;
    const img = await loadImage(p); if (!img) return null;
    if (full(img)) { ctx.drawImage(img.canvas, 0, 0, W, H); used.push(ui + ': ' + name(p)); return img; }
    const pos = FACE_POS[layer];
    if (!pos) { skipped.push(`${ui} (${name(p)})`); return null; }
    const k = scaleOf(img);
    if (layer === 'facialHair') return { img, p };   // drawn below, in the hair colour
    let src = img.canvas;
    // upscaled (or edited) face pieces can come out a slightly different shade than the head under them
    // (the AI shifts colours a little per image). Give the piece the same colour change the head had
    // at that spot, compared with the game's own files, so they blend as they do in the game.
    if (['nose', 'lowerFace', 'eyeType', 'eyebrow', 'complexion'].includes(layer) && (img.replaced || base.replaced)) {
      const hOrig = base.replaced ? (baseOrig ||= await gameCanvas(baseP)) : null;
      const pOrig = img.replaced ? await gameCanvas(p) : null;
      const r = [pos[0] * k0 / W, pos[1] * k0 / H, img.canvas.width * k / W, img.canvas.height * k / H];
      const hs = hOrig ? shiftOf(base.canvas, hOrig, r, null) : [1, 1, 1];
      const ps = pOrig ? shiftOf(img.canvas, pOrig) : [1, 1, 1];
      const g = hs.map((v, c) => Math.max(0.7, Math.min(1.4, v / ps[c])));
      if (g.some((v) => Math.abs(v - 1) > 0.01)) src = tinted(img.canvas, g);
    }
    ctx.drawImage(src, pos[0] * k0, pos[1] * k0, img.canvas.width * k, img.canvas.height * k);
    used.push(ui + ': ' + name(p));
    return img;
  };
  await place('Complexion', 'complexion');
  await place('Nose', 'nose');
  await place('Chin (lower face)', 'lowerFace');
  await place('Eye shape', 'eyeType');
  await place('Eyebrows', 'eyebrow');
  // facial hair (men): one texture for the stubble painted on the face and the beard meshes
  // (facialHair2-7Mesh, whose UVs point at the right side of the face texture); greyscale, so it
  // takes the hair colour
  ch.beardCanvas = null;
  const fh = ch.gender === 'male' ? await place('Facial hair', 'facialHair') : null;
  if (fh) {
    const k = scaleOf(fh.img), pos = FACE_POS.facialHair;
    const tint = await hairTint(ch);
    const t = document.createElement('canvas'); t.width = fh.img.canvas.width; t.height = fh.img.canvas.height;
    const tc = t.getContext('2d'); tc.drawImage(fh.img.canvas, 0, 0);
    if (tint) { tc.globalCompositeOperation = 'multiply'; tc.fillStyle = tint; tc.fillRect(0, 0, t.width, t.height); tc.globalCompositeOperation = 'destination-in'; tc.drawImage(fh.img.canvas, 0, 0); }
    ctx.drawImage(t, pos[0] * k0, pos[1] * k0, t.width * k, t.height * k);   // stubble on the skin
    const bc = document.createElement('canvas'); bc.width = W; bc.height = H;
    bc.getContext('2d').drawImage(t, pos[0] * k0, pos[1] * k0, t.width * k, t.height * k);
    ch.beardCanvas = bc;   // see-through texture for the beard meshes
    used.push('Facial hair: ' + name(fh.p));
  }
  return canvas;
}

function meshFor(ch, nameLower) { return ch.base.meshes.get(nameLower) || null; }
function placeMeshes(ch, meshName) {
  const n = meshName.toLowerCase();
  return [n + 'mesh', n + 'lmesh', n + 'rmesh'].map((k) => meshFor(ch, k)).filter(Boolean);
}

async function dressCharacter(ch) {
  status.set('Dressing character');
  // 1) mesh visibility
  const want = {};
  for (const p of BODY_PLACES) want[p.toLowerCase()] = p + '00';
  const extra = [];
  const flags = {};
  for (const key of Object.values(ch.outfit)) {
    if (!key || !S.armor || !S.armor[key]) continue;
    const side = itemSide(S.armor[key], ch.gender, ch.outfitVariant[key] || 'default'); if (!side) continue;
    Object.assign(flags, side.flags);
    for (const op of side.ops) if (op.type === 'mesh') {
      const pl = (op.place || '').toLowerCase();
      if (BODY_PLACES.map((x) => x.toLowerCase()).includes(pl)) want[pl] = op.name; else extra.push(op.name);
    }
  }
  for (const m of ch.base.meshes.values()) {
    const n = m.name.toLowerCase();
    if (HIDDEN_RE.test(n)) { m.visible = false; continue; }
    m.visible = false;
  }
  for (const [pl, name] of Object.entries(want)) {
    let ms = placeMeshes(ch, name);
    if (!ms.length) ms = placeMeshes(ch, pl + '00');
    ms.forEach((m) => (m.visible = true));
  }
  for (const name of extra) placeMeshes(ch, name).forEach((m) => (m.visible = true));
  // a helmet's model is named in mappings.txt under the same key (armor.xml only has its flags):
  // if it can't be found, keep the head and hair rather than showing an empty head
  ch.helmetPath = helmetPath(ch); ch.helmetMissing = !!(ch.outfit.Head && !ch.helmetPath);
  if (ch.helmetMissing) { delete flags.removeHead; flags.showHair = true; toast('No model found for ' + ch.outfit.Head + ' (looked in mappings.txt)'); }
  const headHidden = !!flags.removeHead;
  if (!headHidden) {
    ['backpartmesh', `upperface${ch.face.upperFace}mesh`, `lowerface${ch.face.lowerFace}mesh`, `nose${ch.face.nose}mesh`]
      .forEach((k) => { const m = meshFor(ch, k); if (m) m.visible = true; });
    if (ch.gender === 'male' && ch.face.facialHair && ch.faceLayersOn.facialHair !== false) { const m = meshFor(ch, `facialhair${ch.face.facialHair}mesh`); if (m) m.visible = true; }
  }
  // manual overrides from the mesh list
  for (const [n, v] of Object.entries(ch.meshOverride)) { const m = meshFor(ch, n); if (m) m.visible = v; }
  // 2) textures
  const { body, outer } = await composeBody(ch);
  const face = await composeFace(ch);
  const bodyTex = canvasTexture(body), outerTex = canvasTexture(outer), faceTex = face ? canvasTexture(face) : null;
  const old = ch.materials || [];
  const bodyMat = new THREE.MeshPhongMaterial({ map: bodyTex, side: THREE.DoubleSide, specular: new THREE.Color(0.08, 0.08, 0.08), shininess: 12 });
  const outerMat = new THREE.MeshPhongMaterial({ map: outerTex, side: THREE.DoubleSide, alphaTest: 0.5, specular: new THREE.Color(0.08, 0.08, 0.08), shininess: 12 });
  let faceMat;
  if (faceTex) faceMat = new THREE.MeshPhongMaterial({ map: faceTex, side: THREE.DoubleSide, specular: new THREE.Color(0.05, 0.05, 0.05), shininess: 8 });
  else {
    // no face textures: plain skin colour taken from the nude texture's chest area
    const skin = ch.skinColour || new THREE.Color(0.85, 0.66, 0.55);
    faceMat = new THREE.MeshPhongMaterial({ color: skin, side: THREE.DoubleSide, specular: new THREE.Color(0.05, 0.05, 0.05), shininess: 8 });
  }
  const beardMat = ch.beardCanvas ? new THREE.MeshPhongMaterial({ map: canvasTexture(ch.beardCanvas), side: THREE.DoubleSide, alphaTest: 0.25, specular: new THREE.Color(0.03, 0.03, 0.03), shininess: 4 }) : faceMat;
  for (const m of ch.base.meshes.values()) {
    const n = m.name;
    if (HIDDEN_RE.test(n)) continue;
    m.material = BEARD_RE.test(n) ? beardMat : HEAD_RE.test(n) ? faceMat : OUTER_RE.test(n) ? outerMat : bodyMat;
  }
  ch.materials = [bodyMat, outerMat, faceMat].concat(beardMat !== faceMat ? [beardMat] : []);
  old.forEach((mt) => { if (mt.map) mt.map.dispose(); mt.dispose(); });
  ch.bodyCanvas = body; ch.faceCanvas = face;
  // 3) hair + helmet attachments
  await updateHair(ch, flags);
  await updateHelmet(ch);
  await updateJewels(ch);
  status.done();
}

async function attachModel(ch, path, boneName, slotName, overrides = null) {
  let wom; try { wom = await readModel(path); } catch (e) { toast(path + ': ' + e.message); return null; }
  if (!wom) { toast('Not found: ' + path); return null; }
  const share = wom.joints.length && wom.joints.every((j) => ch.base.skel.byName.has(j.name)) ? ch.base.skel : null;
  const m = await buildModel(wom, path, overrides, share);
  if (share && m.skel && m.skel.shared && ch.hairFit !== 'own') {
    // fit with the CHARACTER's rest pose: the attached mesh is taken to be modelled in the body's space
    const bodyInv = new Map(ch.base.skel.skeleton.bones.map((b, i) => [b.name, ch.base.skel.skeleton.boneInverses[i]]));
    m.skel.skeleton.boneInverses = m.skel.skeleton.bones.map((b) => bodyInv.get(b.name).clone());
  }
  if (share) ch.base.group.add(m.group);
  else {
    const bone = ch.base.skel.byName.get(boneName) || ch.base.skel.byName.get('NullHelmet') || ch.base.skel.byName.get('Head');
    // an .obj without .womdata.json may have been exported sitting on the body (wom2obj places hair and
    // helmets there): judge that from the file's own coordinates, before it is put on the bone
    let placed = false, bi = null;
    if (wom.placed) {
      bi = ch.base.skel.skeleton.boneInverses[ch.base.skel.skeleton.bones.indexOf(bone)];
      m.group.updateMatrixWorld(true);
      const c = new THREE.Box3().setFromObject(m.group).getCenter(new THREE.Vector3());
      const bindPos = bi ? new THREE.Vector3().setFromMatrixPosition(bi.clone().invert()) : null;
      placed = !!bi && c.distanceTo(bindPos) < c.length();
    }
    bone.add(m.group);
    if (placed) { m.group.applyMatrix4(bi); m.group.userData.offset = 'placed'; m.group.userData.slot = slotName; return m; }
    // properties.xml <offsetToNull><NullX> placement for this file (helmets, hats, held items)
    const prop = S.props[path.split('/').pop().toLowerCase()];
    const o = prop && prop.offsets && (prop.offsets[bone.name] || prop.offsets[boneName]);
    if (o) {
      const d = Math.PI / 180;
      m.group.position.set(o.xPos || 0, o.yPos || 0, o.zPos || 0);
      m.group.rotation.set((o.xRot || 0) * d, (o.yRot || 0) * d, (o.zRot || 0) * d, 'XYZ');
    }
    m.group.userData.offset = o || null;
  }
  m.group.userData.slot = slotName;
  return m;
}
function detach(ch, slot) {
  if (!ch.attached[slot]) return;
  const g = ch.attached[slot].group; g.parent && g.parent.remove(g);
  g.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
  ch.attached[slot] = null;
}
async function updateHair(ch, flags) {
  detach(ch, 'hair');
  if (ch.hair === '' || ch.hair == null) return;
  if (flags.removeHead || (ch.outfit.Head && !flags.showHair)) return;
  let p;
  if (String(ch.hair).startsWith(EXTRA)) { if (!S.useOverlay) return; p = ch.hair; }
  else {
    const key = ch.gender === 'female' ? `hair${ch.hair}.female` : `hair${ch.hair}`;
    const e = S.mapIndex.get(key); p = e && gamePath(e.file);
    if (!p) { toast('Hair ' + key + ' not found in your folder'); return; }
  }
  // hair files are static meshes modelled around the NullHelmet bone (same origin as helmets)
  ch.attached.hair = await attachModel(ch, p, 'NullHelmet', 'hair');
  if (ch.attached.hair && ch.hairColor !== '') {
    const ce = S.mapIndex.get(`hairColor${ch.hairColor}Default`); const cp = ce && gamePath(ce.file);
    const img = cp && await loadImage(cp);
    if (img) {
      const c = img.canvas.getContext('2d').getImageData(0, 0, img.canvas.width, img.canvas.height).data;
      let r = 0, gg = 0, b = 0, n = 0; for (let i = 0; i < c.length; i += 16) { r += c[i]; gg += c[i + 1]; b += c[i + 2]; n++; }
      const col = new THREE.Color(r / n / 255, gg / n / 255, b / n / 255).convertSRGBToLinear();
      ch.attached.hair.group.traverse((o) => { if (o.isMesh) { o.material = o.material.clone(); o.material.color = col; } });
    }
  }
}
async function updateJewels(ch) {
  ch.jewel = ch.jewel || {};
  for (const [slot, bone] of JEWEL_SLOTS) {
    detach(ch, 'j:' + slot);
    const v = ch.jewel[slot]; if (!v) continue;
    if (v.startsWith(EXTRA)) { if (S.useOverlay) ch.attached['j:' + slot] = await attachModel(ch, v, bone, 'j:' + slot); continue; }
    const e = S.mapIndex.get(v); const p = e && gamePath(e.file);
    if (p) ch.attached['j:' + slot] = await attachModel(ch, p, bone, 'j:' + slot, e.overrides);
    else toast('No model found for ' + v);
  }
}
/** the model for the chosen head item: mappings key + ".equipped.<gender>", the key itself, then shorter keys
 *  (model.armour.head.greathelmWolf.iron -> model.armour.head.greathelmWolf) */
function helmetPath(ch) {
  const key = ch.outfit.Head;
  if (!key) return null;
  if (key.startsWith(EXTRA)) return key;
  const parts = key.split('.');
  for (let n = parts.length; n >= 4; n--) {
    const k = parts.slice(0, n).join('.');
    for (const kk of [`${k}.equipped.${ch.gender}`, `${k}.equipped`, k]) {
      const e = S.mapIndex.get(kk); const p = e && gamePath(e.file);
      if (p && /\.(wom|obj)$/i.test(p)) return p;
    }
  }
  return null;
}
async function updateHelmet(ch) {
  detach(ch, 'helmet');
  const p = ch.helmetPath;
  if (p && p.startsWith(EXTRA) && !S.useOverlay) return;
  if (p) ch.attached.helmet = await attachModel(ch, p, 'NullHelmet', 'helmet');
}



// ------------------------------------------------------------------ dyes / paint masks
// properties.xml: <mask>x_pm.dds</mask> (whole model) or <meshMask><mesh/><mask/></meshMask> (one mesh).
// Mask colours: yellow (red+green) = main / wood dye, blue = cloth dye, black = never dyed.
function dyeInfo(cur) {
  const prop = S.props[cur.path.split('/').pop().toLowerCase()];
  if (!prop) return null;
  const list = [];
  if (prop.meshMasks && prop.meshMasks.length) {
    for (const mm of prop.meshMasks) list.push({ mesh: mm.mesh.toLowerCase(), mask: mm.mask });
  } else if (prop.props && prop.props.mask) list.push({ mesh: null, mask: prop.props.mask });
  return list.length ? list : null;
}
function dyeDefaults() {
  return { main: false, mainRGB: [176, 52, 40], cloth: false, clothRGB: [40, 72, 160], mode: 'detail', strength: 1 };
}
async function applyDye(cur) {
  const info = cur.dyeMasks; if (!info) return;
  const d = cur.dye;
  for (const { mesh, mask } of info) {
    const mp = S.fs.findTexture(mask, dirOf(cur.path), S.tier) || (S.overlay.byName(mask) ? EXTRA + S.overlay.byName(mask) : null);
    const mimg = mp && await loadImage(mp);
    if (!mimg) { toast('Dye mask not found: ' + mask); continue; }
    const mtex = new THREE.CanvasTexture(mimg.canvas);
    mtex.flipY = false; mtex.colorSpace = THREE.NoColorSpace; mtex.wrapS = mtex.wrapT = THREE.RepeatWrapping;
    for (const m of cur.base.meshes.values()) {
      const n = m.name.toLowerCase();
      if (HIDDEN_RE.test(n)) continue;
      if (mesh && !(n === mesh + 'mesh' || n === mesh || (n.startsWith(mesh) && n.includes('lod')))) continue;
      if (!m.userData.undyed) m.userData.undyed = m.material.userData.tintFrom && m.material.userData.ownedBy === m.uuid ? m.material.userData.tintFrom : m.material;
      const base = m.userData.undyed;
      if (!d.main && !d.cloth) { m.material = base; continue; }
      const mat = base.clone();
      const toLin = (rgb) => new THREE.Color().setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, THREE.SRGBColorSpace);
      const u = {
        dyeMask: { value: mtex }, dye1: { value: toLin(d.mainRGB) }, dye2: { value: toLin(d.clothRGB) },
        dyeOn1: { value: d.main ? 1 : 0 }, dyeOn2: { value: d.cloth ? 1 : 0 },
        dyeStrength: { value: d.strength }, dyeMode: { value: d.mode === 'layer' ? 1 : d.mode === 'detail' ? 2 : 0 },
      };
      mat.onBeforeCompile = (sh) => {
        Object.assign(sh.uniforms, u);
        sh.fragmentShader = sh.fragmentShader
          .replace('#include <common>', '#include <common>\nuniform sampler2D dyeMask; uniform vec3 dye1; uniform vec3 dye2; uniform float dyeOn1; uniform float dyeOn2; uniform float dyeStrength; uniform int dyeMode;')
          .replace('#include <map_fragment>', `#include <map_fragment>
            #ifdef USE_MAP
            vec4 dm = texture2D(dyeMask, vMapUv);
            float w1 = clamp(max(dm.r, dm.g) - dm.b * 0.0, 0.0, 1.0) * dyeOn1 * dyeStrength;
            float w2 = dm.b * dyeOn2 * dyeStrength;
            vec3 c0 = diffuseColor.rgb;
            // detail: this pixel's brightness against the blurred surroundings (a small mip level)
            vec3 cBlur = texture2D(map, vMapUv, 5.0).rgb;
            float detail = clamp(dot(c0, vec3(0.2126, 0.7152, 0.0722)) / max(dot(cBlur, vec3(0.2126, 0.7152, 0.0722)), 0.02), 0.3, 1.35);
            vec3 t1 = dyeMode == 1 ? dye1 : dyeMode == 2 ? min(dye1 * detail, vec3(1.0)) : c0 * dye1 * 2.0;
            vec3 t2 = dyeMode == 1 ? dye2 : dyeMode == 2 ? min(dye2 * detail, vec3(1.0)) : c0 * dye2 * 2.0;
            diffuseColor.rgb = mix(mix(c0, t1, w1), t2, w2);
            #endif`);
      };
      mat.customProgramCacheKey = () => 'dye';
      mat.needsUpdate = true;
      m.material = mat;
    }
  }
  applyTints(cur);
}
function renderDyePanel(P, cur) {
  const d = cur.dye;
  const redo = async () => { S.dyeMemory[cur.path.toLowerCase()] = JSON.parse(JSON.stringify(d)); await applyDye(cur); renderPanels(); };
  const hex = (rgb) => '#' + rgb.map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');
  const colorRow = (label, onKey, rgbKey) => {
    const nums = rgbKey && d[rgbKey].map((v, i) => el('input', { type: 'number', min: 0, max: 255, value: v, class: 'rgb',
      onchange: (e) => { d[rgbKey][i] = Math.max(0, Math.min(255, Number(e.target.value) || 0)); d[onKey] = true; redo(); } }));
    return el('div', { class: 'dyerow' },
      el('label', { class: 'row chk' }, el('input', { type: 'checkbox', checked: d[onKey], onchange: (e) => { d[onKey] = e.target.checked; redo(); } }), el('span', {}, label)),
      el('div', { class: 'dyepick' }, el('input', { type: 'color', value: hex(d[rgbKey]), onchange: (e) => {
        const v = e.target.value; d[rgbKey] = [1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16)); d[onKey] = true; redo(); } }),
      el('span', { class: 'kv' }, 'R G B'), ...nums));
  };
  const masks = cur.dyeMasks.map((x) => (x.mesh ? x.mesh + ': ' : '') + x.mask).join(', ');
  P.append(section('Dye (paint mask)',
    colorRow('Main / wood dye (yellow in mask)', 'main', 'mainRGB'),
    colorRow('Cloth dye (blue in mask)', 'cloth', 'clothRGB'),
    select('Blend', [['detail', 'true colour, keeps the texture detail'], ['layer', 'colour layer (transparency)'], ['multiply', 'multiply x2']], d.mode, (v) => { d.mode = v; redo(); }),
    el('label', { class: 'row' }, el('span', {}, 'Strength'), el('input', { type: 'range', min: 0, max: 1, step: 0.05, value: d.strength,
      onchange: (e) => { d.strength = Number(e.target.value); redo(); } })),
    el('p', { class: 'hint' }, 'Mask from properties.xml: ' + masks + '. Dye colours are 0-255 RGB like the game. "True colour" gives the dye\'s own colour (white stays white) and keeps the texture\'s light and shade; the other two are the older blends to compare with.')));
}

// ------------------------------------------------------------------ metal look and gear colours
// Metal colours are the commonly published reflectance colours for real metals (iron, gold, silver,
// copper…); alloys and the game's own metals are picked by eye. "rough" is 0 (mirror) to 1 (dull).
const METALS = {
  iron: { rgb: [0.56, 0.57, 0.58], rough: 0.5 }, steel: { rgb: [0.62, 0.63, 0.65], rough: 0.32 },
  gold: { rgb: [1.0, 0.71, 0.29], rough: 0.24 }, silver: { rgb: [0.95, 0.93, 0.88], rough: 0.2 },
  copper: { rgb: [0.95, 0.64, 0.54], rough: 0.34 }, bronze: { rgb: [0.8, 0.56, 0.34], rough: 0.4 },
  brass: { rgb: [0.88, 0.75, 0.42], rough: 0.3 }, lead: { rgb: [0.52, 0.54, 0.58], rough: 0.62 },
  zinc: { rgb: [0.64, 0.67, 0.7], rough: 0.45 }, tin: { rgb: [0.76, 0.77, 0.79], rough: 0.38 },
  adamantine: { rgb: [0.38, 0.48, 0.68], rough: 0.22 }, glimmersteel: { rgb: [0.82, 0.72, 0.5], rough: 0.2 },
  seryll: { rgb: [0.74, 0.3, 0.24], rough: 0.24 }, 'moon metal': { rgb: [0.8, 0.83, 0.9], rough: 0.2 },
  electrum: { rgb: [0.93, 0.83, 0.56], rough: 0.24 },
};
// which meshes look like metal: by mesh name or texture name
const METAL_RE = /metal|iron|steel|chain|plate|blade|sword|axe|hammer|anvil|lock|nail|shoe|helm|buckle|rivet|lamp|bell|coin|spike|stud|shovel|knife|spear|mace|ingot|wire|gold|silver|copper|bronze|brass/i;
function metalDefaults() { return { metal: '', parts: 'metal' }; }
function metalTargets(cur) {
  return [...cur.base.meshes.values()].filter((m) => !HIDDEN_RE.test(m.name.toLowerCase())).filter((m) => {
    if (cur.metal.parts === 'all') return true;
    const t = (m.material && m.material.userData && m.material.userData.texPath) || '';
    return METAL_RE.test(m.name) || METAL_RE.test(t.split('/').pop());
  });
}
const GEAR_PARTS = [['barding', 'Barding', /_bardingmesh$/i], ['saddle', 'Saddle', /^saddlemesh$/i], ['bridle', 'Bridle', /^bridlemesh$/i], ['bags', 'Saddle bags', /^bagmesh$/i]];
// Give the mesh its own copy of its material (meshes of one model share them), keeping any dye shader.
function ownMaterial(m) {
  if (m.material.userData.ownedBy === m.uuid) return m.material;
  const src = m.material, c = src.clone();
  c.onBeforeCompile = src.onBeforeCompile; c.customProgramCacheKey = src.customProgramCacheKey;
  c.userData = { ...src.userData, ownedBy: m.uuid, tintFrom: src };
  m.material = c; return c;
}
// Colour a whole mesh the way the dye does: the colour it takes on, with the texture's own detail kept.
// keepColoured: for metal, strongly coloured pixels (a red plume, painted bits) are changed less than
// the greyish or metal-coloured ones.
function gearTint(mat, rgb, keepColoured) {
  const u = { gearRGB: { value: rgb.isColor ? rgb : new THREE.Color().setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, THREE.SRGBColorSpace) }, gearKeep: { value: keepColoured ? 1 : 0 } };
  const prev = mat.onBeforeCompile, prevKey = mat.customProgramCacheKey;
  mat.onBeforeCompile = (sh, r) => {
    if (prev) prev(sh, r);
    Object.assign(sh.uniforms, u);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform vec3 gearRGB; uniform float gearKeep;')
      .replace('#include <map_fragment>', `#include <map_fragment>
        #ifdef USE_MAP
        { vec3 gBlur = texture2D(map, vMapUv, 5.0).rgb;
          float gDet = clamp(dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722)) / max(dot(gBlur, vec3(0.2126, 0.7152, 0.0722)), 0.02), 0.3, 1.35);
          float gMx = max(diffuseColor.r, max(diffuseColor.g, diffuseColor.b)), gMn = min(diffuseColor.r, min(diffuseColor.g, diffuseColor.b));
          float gSat = gMx > 0.0 ? (gMx - gMn) / gMx : 0.0;
          float gW = gearKeep > 0.5 ? 1.0 - smoothstep(0.72, 0.92, gSat) : 1.0;
          diffuseColor.rgb = mix(diffuseColor.rgb, min(gearRGB * gDet, vec3(1.0)), gW); }
        #else
        diffuseColor.rgb = gearRGB;
        #endif`);
  };
  mat.customProgramCacheKey = () => (prevKey ? prevKey.call(mat) : '') + '|gear';
  mat.needsUpdate = true;
}
// Re-done after every dye, mount or metal change: undo the earlier tints, then apply the current ones.
function applyTints(cur) {
  for (const m of cur.base.meshes.values()) {
    if (m.material && m.material.userData.tintFrom && m.material.userData.ownedBy === m.uuid) m.material = m.material.userData.tintFrom;
  }
  if (cur.metal && cur.metal.metal && METALS[cur.metal.metal]) {
    const M = METALS[cur.metal.metal];
    for (const m of metalTargets(cur)) {
      const mat = ownMaterial(m);
      // the metal's own colour, with the texture's light and shade kept (like the dye)
      gearTint(mat, new THREE.Color(M.rgb[0], M.rgb[1], M.rgb[2]).multiplyScalar(0.85), true);
      mat.specular = new THREE.Color(M.rgb[0], M.rgb[1], M.rgb[2]).multiplyScalar(0.9);
      mat.shininess = Math.max(4, 2 / Math.pow(Math.max(0.05, M.rough), 4) - 2);
    }
  }
  if (cur.mount) {
    for (const [key, , re] of GEAR_PARTS) {
      const rgb = cur.mount['dye_' + key]; if (!rgb) continue;
      for (const m of cur.base.meshes.values()) if (re.test(m.name)) gearTint(ownMaterial(m), rgb);
    }
  }
}
function renderMetalPanel(P, cur) {
  const g = cur.metal;
  const redo = () => { S.metalMemory[cur.path.toLowerCase()] = { ...g }; applyTints(cur); renderPanels(); };
  const n = g.metal ? metalTargets(cur).length : 0;
  P.append(section('Metal look',
    select('Metal', [['', 'as the model comes'], ...Object.keys(METALS).map((k) => [k, k])], g.metal, (v) => { g.metal = v; redo(); }),
    select('Parts', [['metal', 'parts that look like metal (by name)'], ['all', 'the whole model']], g.parts, (v) => { g.parts = v; redo(); }),
    el('p', { class: 'hint' }, (g.metal ? n + ' part' + (n === 1 ? '' : 's') + ' changed. ' : '') + 'Shows the object in another metal: colour, highlight colour and how sharp the shine is. Best with "Highlights: realistic" in the Model section.')));
}

// ------------------------------------------------------------------ mount gear (horse, hell horse, unicorn…)
// The game picks these meshes itself (properties.xml only says <canHaveMountItems/>), so the viewer
// offers whatever gear meshes the opened model actually contains.
const BARDINGS = [['cloth', 'Cloth_barding'], ['leather', 'Leather_barding'], ['chain', 'Chain_barding']];
function isMount(wom) {
  const n = new Set(wom.meshes.map((m) => m.name.toLowerCase()));
  return n.has('bodymeshmesh') && (n.has('saddlemesh') || BARDINGS.some(([, b]) => n.has(b.toLowerCase() + 'mesh')));
}
function mountDefaults() {
  return { barding: '', body: 'auto', saddle: false, bags: false, xmas: false, bridle: false, shoes: false,
    shoeTex: '', chainTex: '' };
}
function mountOptions(cur) {
  const has = (n) => cur.base.meshes.has(n.toLowerCase());
  const dir = dirOf(cur.path).toLowerCase();
  const near = [...S.fs.files.keys()].filter((k) => dirOf(k) === dir);
  return {
    bardings: BARDINGS.filter(([, b]) => has(b + 'Mesh')),
    bodies: ['01', '02', '03'].filter((n) => has('BodyBarded' + n + 'Mesh')),
    saddle: has('saddleMesh'), bags: has('bagMesh'), xmas: has('xmasMesh'), bridle: has('bridleMesh'),
    shoes: has('horseshoe1Mesh'),
    shoeTex: near.filter((k) => /\/shoe[^/]*\.(png|dds)$/.test(k)).map((k) => S.fs.orig.get(k) || k),
    chainTex: near.filter((k) => /\/chain_barding_[^/]+\.(dds|png)$/.test(k)).map((k) => S.fs.orig.get(k) || k),
  };
}
async function applyMount(cur) {
  const g = cur.mount, M = (n) => cur.base.meshes.get(n.toLowerCase());
  const gear = ['bodyMeshMesh', 'bodylavaMesh', 'saddleMesh', 'bagMesh', 'xmasMesh', 'bridleMesh',
    'horseshoe1Mesh', 'horseshoe2Mesh', 'horseshoe3Mesh', 'horseshoe4Mesh',
    ...BARDINGS.map(([, b]) => b + 'Mesh'), ...['01', '02', '03'].flatMap((n) => ['BodyBarded' + n + 'Mesh', 'bodylavabarded' + n + 'Mesh'])];
  gear.forEach((n) => { const m = M(n); if (m) m.visible = false; });
  const show = (n) => { const m = M(n); if (m) m.visible = true; };
  if (g.barding) {
    const idx = BARDINGS.findIndex(([k]) => k === g.barding);
    const body = g.body === 'auto' ? '0' + (idx + 1) : g.body;
    if (M('BodyBarded' + body + 'Mesh')) { show('BodyBarded' + body + 'Mesh'); show('bodylavabarded' + body + 'Mesh'); }
    else { show('bodyMeshMesh'); show('bodylavaMesh'); }
    show(BARDINGS[idx][1] + 'Mesh');
  } else { show('bodyMeshMesh'); show('bodylavaMesh'); }
  if (g.saddle) show('saddleMesh');
  if (g.bags) show('bagMesh');
  if (g.xmas) show('xmasMesh');
  if (g.bridle) show('bridleMesh');
  if (g.shoes) ['1', '2', '3', '4'].forEach((n) => show('horseshoe' + n + 'Mesh'));
  // texture swaps (chain barding metal, horseshoe metal)
  const swap = async (meshNames, tex) => {
    for (const n of meshNames) {
      const m = M(n); if (!m) continue;
      if (!m.userData.origMaterial) m.userData.origMaterial = m.material;
      if (!tex) { m.material = m.userData.origMaterial; continue; }
      const src = m.userData.origMaterial.userData.source || {};
      m.material = await makeMaterial({ ...src, texture: tex.split('/').pop() }, dirOf(cur.path), null);
    }
  };
  await swap(['Chain_bardingMesh'], g.chainTex);
  await swap(['horseshoe1Mesh', 'horseshoe2Mesh', 'horseshoe3Mesh', 'horseshoe4Mesh'], g.shoeTex);
  for (const [n, v] of Object.entries(cur.meshOverride || {})) { const m = M(n); if (m) m.visible = v; }
  applyTints(cur);
}
function renderMountPanel(P, cur) {
  const o = mountOptions(cur), g = cur.mount;
  const redo = async () => { S.mountMemory[cur.path.toLowerCase()] = { ...g }; await applyMount(cur); renderPanels(); };
  const rows = [];
  if (o.bardings.length) {
    rows.push(select('Barding', [['', 'none'], ...o.bardings.map(([k]) => [k, k])], g.barding, (v) => { g.barding = v; redo(); }));
    if (o.bodies.length) rows.push(select('Body under barding', [['auto', 'auto (cloth 01, leather 02, chain 03)'], ...o.bodies.map((n) => [n, 'BodyBarded' + n])], g.body, (v) => { g.body = v; redo(); }));
    if (o.chainTex.length) rows.push(select('Chain metal', [['', 'model\'s own'], ...o.chainTex.map((t) => [t, t.split('/').pop().replace(/^chain_barding_|_512|\.(dds|png)$/gi, '') || t])], g.chainTex, (v) => { g.chainTex = v; redo(); }));
  }
  if (o.saddle) rows.push(check('Saddle', g.saddle, (v) => { g.saddle = v; redo(); }));
  if (o.bags) rows.push(check('Saddle bags', g.bags, (v) => { g.bags = v; redo(); }));
  if (o.xmas) rows.push(check('Christmas sack', g.xmas, (v) => { g.xmas = v; redo(); }));
  if (o.bridle) rows.push(check('Bridle', g.bridle, (v) => { g.bridle = v; redo(); }));
  if (o.shoes) {
    rows.push(check('Horseshoes', g.shoes, (v) => { g.shoes = v; redo(); }));
    if (o.shoeTex.length > 1) rows.push(select('Shoe metal', [['', 'model\'s own'], ...o.shoeTex.map((t) => [t, t.split('/').pop().replace(/\.(png|dds)$/i, '')])], g.shoeTex, (v) => { g.shoeTex = v; redo(); }));
  }
  const hex = (rgb) => '#' + rgb.map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');
  for (const [key, label, re] of GEAR_PARTS) {
    if (![...cur.base.meshes.values()].some((m) => re.test(m.name))) continue;
    const k = 'dye_' + key, v = g[k];
    rows.push(el('div', { class: 'dyepick' },
      el('label', { class: 'row chk' }, el('input', { type: 'checkbox', checked: !!v, onchange: (e) => { g[k] = e.target.checked ? (g.lastGear || [120, 40, 30]) : null; redo(); } }), el('span', {}, label + ' colour')),
      el('input', { type: 'color', value: hex(v || g.lastGear || [120, 40, 30]), onchange: (e) => {
        const c = e.target.value; g.lastGear = [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16)); g[k] = g.lastGear; redo(); } })));
  }
  P.append(section('Mount gear', ...rows, el('p', { class: 'hint' }, 'Only the gear meshes inside this model are offered. Coat colours are in the Item / variant menu. Which barded body goes with which barding isn\'t stored in the files: "auto" pairs them by number; switch it if the game looks different.')));
}

// ------------------------------------------------------------------ settings remembered per object
const CHAR_FIELDS = ['gender', 'underclothes', 'outfit', 'outfitVariant', 'outfitDye', 'armourDyeStrength', 'hair', 'hairColor', 'hairFit', 'face', 'faceLayersOn', 'meshOverride', 'kingdom', 'jewel'];
function memKey(cur) { return (cur.path + (cur.itemKey ? '|' + cur.itemKey : '')).toLowerCase(); }
function saveMemory(cur) {
  const m = {};
  if (cur.character) { m.char = {}; for (const k of CHAR_FIELDS) if (cur[k] !== undefined) m.char[k] = JSON.parse(JSON.stringify(cur[k])); }
  else m.hidden = [...cur.base.meshes.values()].filter((x) => !x.visible && !HIDDEN_RE.test(x.name) && !/lod[1-9]/i.test(x.name)).map((x) => x.name);
  if (S.action && S.animInfo) m.anim = S.animInfo;
  S.memory[memKey(cur)] = m;
  try { localStorage.setItem('womviewer.memory', JSON.stringify(S.memory)); } catch (e) { /* storage off: keep it for this session */ }
}
async function resetObject() {
  const cur = S.current; if (!cur) return;
  delete S.memory[memKey(cur)]; delete S.dyeMemory[cur.path.toLowerCase()]; delete S.mountMemory[cur.path.toLowerCase()]; delete S.metalMemory[cur.path.toLowerCase()];
  try { localStorage.setItem('womviewer.memory', JSON.stringify(S.memory)); } catch (e) { /* ignore */ }
  await openModel(cur.path, cur.overrides, cur.itemKey, { noSave: true });
}

// ------------------------------------------------------------------ loading a model
async function openModel(path, overrides = null, itemKey = null, opts = {}) {
  status.set('Reading ' + path, 0);
  if (!getFile(path)) { status.done(); toast('File not found: ' + path); return; }
  let wom;
  try { wom = await readModel(path); } catch (e) {
    const buf = await readBuf(path);
    try { readAnim(buf); } catch (e2) { status.done(); toast(path + ': ' + e.message); return; }
    status.done();
    if (S.current && S.current.base.skel) { await playAnim(path.split('/').pop(), path); toast('Playing animation ' + path.split('/').pop()); } else toast('That is an animation file: open a character first, then click it to play it.');
    return;
  }
  if (S.current && !opts.noSave) saveMemory(S.current);
  stopAnim(false);
  if (S.current) { scene.remove(S.current.base.group); S.current.base.group.traverse((o) => { if (o.geometry) o.geometry.dispose(); }); }
  dropTwin(); if (CMP.on) updateCompareUI();
  const base = await buildModel(wom, path, overrides);
  scene.add(base.group);
  const cur = { base, path, itemKey, overrides, character: isCharacter(wom), meshOverride: {} };
  S.current = cur;
  const dm = dyeInfo(cur);
  if (dm) {
    cur.dyeMasks = dm;
    cur.dye = { ...dyeDefaults(), ...(S.dyeMemory[path.toLowerCase()] || {}) };
    await applyDye(cur);
  }
  if (!cur.character && isMount(wom)) {
    cur.mount = { ...mountDefaults(), ...(S.mountMemory[path.toLowerCase()] || {}) };
    await applyMount(cur);
  }
  if (!cur.character) { cur.metal = { ...metalDefaults(), ...(S.metalMemory[path.toLowerCase()] || {}) }; applyTints(cur); }
  if (cur.character) {
    Object.assign(cur, {
      gender: /female/i.test(path) ? 'female' : 'male', underclothes: true, outfit: {}, outfitVariant: {}, hair: '', hairColor: '',
      face: { upperFace: 0, lowerFace: 0, nose: 0, complexion: '', eyeType: 0, eyeColor: 0, eyebrow: 0, hairType: '', facialHair: '' },
      faceLayersOn: Object.fromEntries(FACE_LAYERS.map(([, k]) => [k, true])), meshOverride: {}, attached: {}, hairFit: 'body',
    });
    const mem = S.memory[memKey(cur)];
    if (mem && mem.char) Object.assign(cur, JSON.parse(JSON.stringify(mem.char)));
    if (S.armor) await dressCharacter(cur);
  }
  const mem = S.memory[memKey(cur)];
  if (mem && mem.hidden) for (const m of cur.base.meshes.values()) if (mem.hidden.includes(m.name)) m.visible = false;
  cur.remembered = !!mem;
  frame(base.group);
  status.done();
  if (mem && mem.anim && cur.base.skel) await playAnim(mem.anim.name, mem.anim.file);
  renderPanels();
  $('#title').textContent = (itemKey ? itemKey + '  →  ' : '') + path;
}

// ------------------------------------------------------------------ UI: left list
function renderList() {
  const tab = document.querySelector('#tabs .on').dataset.tab;
  const q = $('#search').value.trim().toLowerCase();
  const ul = $('#list'); ul.textContent = '';
  let rows = [];
  if (tab === 'files') {
    const anims = new Set(); for (const v of Object.values(S.props)) for (const a of v.anims) anims.add(a.file.toLowerCase());
    const isAnim = (p) => /(^|\/)anim\//i.test(p) || anims.has(p.toLowerCase());
    const used = new Set();
    const tag = (k) => (S.overlay.kindOf(k) === 'obj' ? ' (custom)' : ' (CF)');
    const all = S.fs.list('.wom').filter((p) => !isAnim(p)).map((p) => {
      const hit = S.useOverlay ? S.overlay.findFileKey(p) : null;
      if (hit) used.add(hit[0]);
      return { label: p + (hit ? tag(hit[0]) : ''), sub: hit ? S.overlay.names[S.overlay.layer.get(hit[0])] + ': ' + S.overlay.orig.get(hit[0]) : '', act: () => openModel(p), k: p.toLowerCase() };
    });
    if (S.useOverlay) for (const p of S.overlay.models()) {
      const k = p.toLowerCase(); if (used.has(k) || isAnim(p)) continue;
      all.push({ label: p + tag(k), sub: S.overlay.names[S.overlay.layer.get(k)] + (S.overlay.kindOf(k) === 'obj' ? ' (new object)' : ''), act: () => openModel(EXTRA + p), k });
    }
    all.sort((a, b) => (a.k < b.k ? -1 : a.k > b.k ? 1 : 0));
    rows = all.filter((r) => !q || r.label.toLowerCase().includes(q) || r.sub.toLowerCase().includes(q));
  } else if (tab === 'items') {
    rows = S.mappings.filter((e) => /\.wom$/i.test(e.file)).map((e) => ({ e, g: gamePath(e.file) })).filter((x) => x.g)
      .filter((x) => !q || x.e.key.toLowerCase().includes(q) || x.g.toLowerCase().includes(q))
      .map(({ e, g }) => ({ label: e.key, sub: g + (Object.keys(e.overrides).length ? '  ✦ variant' : ''), act: () => openModel(g, e.overrides, e.key) }));
  } else {
    const anims = new Map();
    for (const [, v] of Object.entries(S.props)) for (const a of v.anims) anims.set(a.file.toLowerCase(), a);
    rows = S.fs.list('.wom').filter((p) => /(^|\/)anim\//i.test(p)).filter((p) => !q || p.toLowerCase().includes(q))
      .map((p) => ({ label: p.split('/').pop(), sub: p, act: () => (S.current && S.current.base.skel ? playAnim(p.split('/').pop(), p) : toast('Open a character model first')) }));
  }
  $('#count').textContent = rows.length + ' shown';
  for (const r of rows.slice(0, 800)) {
    ul.append(el('li', { onclick: (ev) => { ul.querySelectorAll('li.sel').forEach((x) => x.classList.remove('sel')); ev.currentTarget.classList.add('sel'); r.act(); } },
      el('div', { class: 'l' }, r.label), r.sub ? el('div', { class: 's' }, r.sub) : null));
  }
  if (rows.length > 800) ul.append(el('li', { class: 'more' }, `${rows.length - 800} more - type in the search box to narrow down`));
  if (!S.fs.files.size && !S.overlay.files.size) ul.append(el('li', { class: 'more' }, 'Click "Open game\'s .jar files" and pick graphics.jar from <game>/packs to start.'));
}

// ------------------------------------------------------------------ UI: right panels
// open/closed state of each panel, kept while settings change and between visits
const PANELS = (() => { try { return JSON.parse(localStorage.getItem('womviewer.panels') || '{}'); } catch (e) { return {}; } })();
function panelKey(title) { return String(title).replace(/\s*\(.*$/, '').trim(); }
function section(title, ...body) {
  const k = panelKey(title);
  return el('details', { open: PANELS[k] ?? true, class: 'panel', ontoggle: (e) => {
    PANELS[k] = e.target.open; try { localStorage.setItem('womviewer.panels', JSON.stringify(PANELS)); } catch (err) { /* ignore */ } } },
  el('summary', {}, title), ...body);
}
function select(label, options, value, onchange) {
  const s = el('select', { onchange: (e) => onchange(e.target.value) });
  for (const [v, t] of options) { const o = el('option', { value: v }, t); if (String(v) === String(value)) o.selected = true; s.append(o); }
  return el('label', { class: 'row' }, el('span', {}, label), s);
}
function check(label, value, onchange) {
  return el('label', { class: 'row chk' }, el('input', { type: 'checkbox', checked: value, onchange: (e) => onchange(e.target.checked) }), el('span', {}, label));
}

function renderPanels() {
  const P = $('#panels'); P.textContent = '';
  const cur = S.current;
  if (!cur) { P.append(el('p', { class: 'hint' }, 'Pick a model or an item on the left.')); return; }
  const wom = cur.base.wom;
  P.append(el('div', { class: 'topbar' },
    el('button', { title: 'Forget the settings kept for this object and show it as it comes', onclick: resetObject }, 'Default'),
    el('span', { class: 'kv' }, 'Settings are kept per object while you switch.')));
  P.append(section('Model', el('div', { class: 'kv' }, `${wom.meshes.length} meshes · ${wom.joints.length} bones${wom.meshes.some((m) => m.skin) ? ' · skinned' : ''}`),
    el('div', { class: 'btns' },
      el('button', { onclick: () => frame(cur.base.group) }, 'Frame'),
      el('button', { onclick: screenshot }, 'Screenshot'),
      el('button', { onclick: () => { cur.base.group.traverse((o) => { if (o.isMesh) o.material.wireframe = !o.material.wireframe; }); } }, 'Wireframe')),
    check('Normal maps (<texture>_n)', S.useNormalMaps, async (v) => { S.useNormalMaps = v; await openModel(cur.path, cur.overrides, cur.itemKey); }),
    S.useNormalMaps ? check('Flip normal map green', S.flipNormalGreen, async (v) => { S.flipNormalGreen = v; await openModel(cur.path, cur.overrides, cur.itemKey); }) : null,
    select('Highlights', [['gloss', 'realistic (sharp on metal, soft on cloth)'], ['classic', 'classic (plain Phong)']], S.shine, (v) => { S.shine = v; saveLook(); }),
    check('Clean see-through edges (hair, leaves)', S.cleanEdges, async (v) => { S.cleanEdges = v; saveLook(); await openModel(cur.path, cur.overrides, cur.itemKey); })));
  if (CMP.on) P.append(section('Compare',
    select('View', [['wipe', 'wipe (drag the line)'], ['side', 'side by side']], CMP.mode, (v) => { CMP.mode = v; updateCompareUI(); }),
    select('Left side files', [['jar', 'game .jar only'], ['cf', 'game .jar + custom folder']], CMP.left.src, (v) => { CMP.left.src = v; scheduleTwin(); updateCompareUI(); }),
    select('Left side textures', tierOptions(), CMP.left.tier, (v) => { CMP.left.tier = v; scheduleTwin(); updateCompareUI(); }),
    el('p', { class: 'hint' }, 'Right side: what the header shows (files: ' + (S.useOverlay && S.overlay.files.size ? 'game + ' + S.overlay.name : 'game .jar') + ', textures: ' + (S.tierUI === '4096' ? '4096 from the upscale folder' : S.tierUI) + '). E.g. left "game .jar only · 2048" against right "custom folder · 4096". Outfit, hair, dyes, animation and lights are the same on both sides.'),
    el('div', { class: 'btns' }, el('button', { onclick: () => setCompare(false) }, 'Stop comparing'))));
  renderStudioPanel(P);
  renderExportPanel(P);
  scheduleTwin();

  // texture/material variants from mappings.txt
  const vars = mappingsFor(cur.path);
  if (vars.length) {
    const opts = [['', '(the .wom\'s own textures)'], ...vars.map((e) => [e.key, e.key.replace(/^model\./, '') + (Object.keys(e.overrides).length ? '' : ' (no overrides)')])];
    P.append(section('Item / variant (mappings.txt)', select('Item', opts, cur.itemKey || '', async (k) => {
      const e = S.mapIndex.get(k); await openModel(cur.path, e ? e.overrides : null, k || null);
    }), el('p', { class: 'hint' }, `${vars.length} game item(s) use this file.`)));
  }

  if (cur.character) renderCharacterPanels(P, cur);
  if (cur.mount) renderMountPanel(P, cur);
  if (cur.dyeMasks) renderDyePanel(P, cur);
  if (cur.metal) renderMetalPanel(P, cur);

  // animations
  if (cur.base.skel) {
    const file = cur.path.split('/').pop().toLowerCase();
    const prop = S.props[file];
    const list = prop ? prop.anims.map((a) => ({ name: a.name, file: gamePath(a.file) || normPath(dirOf(cur.path) + '/' + a.file) })) : [];
    const seen = new Set();
    const uniq = list.filter((a) => S.fs.has(a.file) && !seen.has(a.name) && seen.add(a.name));
    const animSel = el('select', { size: 8, class: 'animlist', onchange: (e) => { const a = uniq[e.target.selectedIndex]; if (a) playAnim(a.name, a.file); } });
    uniq.forEach((a) => animSel.append(el('option', {}, a.name + '  (' + a.file.split('/').pop() + ')')));
    P.append(section('Animation',
      el('div', { class: 'kv' }, el('b', { id: 'anim-name' }, S.action ? S.action.getClip().name : 'bind pose'), ' ', el('span', { id: 'anim-clock' }, '')),
      el('input', { type: 'range', id: 'anim-time', min: 0, max: 1000, value: 0, oninput: (e) => { if (S.action) { S.action.paused = true; S.action.time = e.target.value / 1000 * S.action.getClip().duration; S.mixer.update(0); } } }),
      el('div', { class: 'btns' },
        el('button', { onclick: () => { if (S.action) S.action.paused = !S.action.paused; } }, 'Play / pause'),
        el('button', { onclick: () => stopAnim(true) }, 'Bind pose')),
      el('label', { class: 'row' }, el('span', {}, 'Speed'), el('input', { type: 'range', id: 'anim-speed', min: 0.1, max: 2, step: 0.05, value: 1, oninput: (e) => { if (S.action) S.action.timeScale = Number(e.target.value); } })),
      check('Loop', true, (v) => { if (S.action) S.action.setLoop(v ? THREE.LoopRepeat : THREE.LoopOnce); }),
      uniq.length ? animSel : el('p', { class: 'hint' }, prop ? 'None of this model\'s animations are in your folder.' : 'No properties.xml entry for this model. Use the Animations tab to try any animation file.'),
      uniq.length ? el('p', { class: 'hint' }, `${uniq.length} animation(s) from properties.xml.`) : null));
  }

  // meshes
  const box = el('div', { class: 'meshes' });
  const metas = [...cur.base.meshes.values()];
  for (const m of metas) {
    box.append(check(m.name, m.visible, (v) => { m.visible = v; if (cur.character || cur.mount) cur.meshOverride[m.name.toLowerCase()] = v; }));
  }
  const det = section(`Meshes (${metas.length})`, el('div', { class: 'btns' },
    el('button', { onclick: () => { metas.forEach((m) => (m.visible = !HIDDEN_RE.test(m.name))); renderPanels(); } }, 'All'),
    el('button', { onclick: () => { metas.forEach((m) => (m.visible = false)); renderPanels(); } }, 'None')), box);
  det.open = PANELS.Meshes ?? (!cur.character && metas.length < 40);
  P.append(det);
}

function renderCharacterPanels(P, ch) {
  const redo = async () => { await dressCharacter(ch); renderPanels(); };
  if (!S.armor) P.append(section('Character', el('p', { class: 'hint warn' }, 'armor.xml was not found in your folder, so outfits, faces and body layering are off. Open the folder that contains armor.xml (e.g. "player").')));
  const num = (n) => Array.from({ length: n }, (_, i) => [i, String(i)]);
  const faceRows = [];
  for (const [ui, k, meshGroup] of FACE_LAYERS) {
    if (k === 'facialHair' && ch.gender === 'female') continue;
    const opts = meshGroup ? num(8) : [['', 'none'], ...num(8)];
    if (k === 'complexion' || k === 'facialHair') opts.splice(1, 1); // these start at 1
    faceRows.push(el('div', { class: 'facerow' }, select(ui, opts, ch.face[k], (v) => { ch.face[k] = v === '' ? '' : Number(v); redo(); }),
      el('input', { type: 'checkbox', title: 'show this layer', checked: ch.faceLayersOn[k], onchange: (e) => { ch.faceLayersOn[k] = e.target.checked; redo(); } })));
  }
  const hairOpts = [['', 'none']];
  for (let i = 0; i < 10; i++) { const key = ch.gender === 'female' ? `hair${i}.female` : `hair${i}`; const e = S.mapIndex.get(key); if (e && gamePath(e.file)) hairOpts.push([i, `${i}: ${e.file.split('/').pop()}`]); }
  // new hairs from the custom folder / custom objects: named like the game's (femaleHair08, male_hair06)
  const hairRe = ch.gender === 'female' ? /^femalehair\d+\.(wom|obj)$/i : /^male_?hair\d+\.(wom|obj)$/i;
  for (const m of S.overlay.models()) {
    if (!hairRe.test(m.split('/').pop())) continue;
    const k = m.toLowerCase();
    const replaces = [...S.fs.files.keys()].some((g) => g.endsWith('.wom') && S.overlay.findFileKey(g)?.[0] === k);
    if (!replaces) hairOpts.push([EXTRA + m, (S.overlay.kindOf(k) === 'obj' ? 'custom: ' : '(CF) ') + m.split('/').pop()]);
  }
  P.append(section('Character',
    select('Body', [['female', 'female'], ['male', 'male']], ch.gender, (v) => { ch.gender = v; redo(); }),
    check('Under-clothes (baseCloth)', ch.underclothes, (v) => { ch.underclothes = v; redo(); }),
    select('Hair', hairOpts, ch.hair, (v) => { ch.hair = v === '' ? '' : (v.startsWith(EXTRA) ? v : Number(v)); redo(); }),
    select('Hair colour', [['', 'texture as is'], ...num(8)], ch.hairColor, (v) => { ch.hairColor = v === '' ? '' : Number(v); redo(); }),
    select('Hair fit', [['body', 'character\'s skeleton'], ['own', 'hair file\'s own skeleton']], ch.hairFit, (v) => { ch.hairFit = v; redo(); }),
    el('div', { class: 'btns' },
      el('button', { onclick: () => downloadCanvas(ch.bodyCanvas, 'body_texture.png') }, 'Save body texture'),
      el('button', { onclick: () => ch.faceCanvas ? downloadCanvas(ch.faceCanvas, 'face_texture.png') : toast('No face texture') }, 'Save face texture'))));
  P.append(section('Face (mappings.txt)',
    select('Eye colours', [['Default', 'Default'], ['Hots', 'HOTS kingdom']], ch.kingdom || 'Default', (v) => { ch.kingdom = v; redo(); }),
    ...faceRows,
    el('p', { class: 'hint' }, (ch.faceUsed && ch.faceUsed.length ? 'Layers: ' + ch.faceUsed.join(' · ') + '.' : 'No face textures found (needs mappings.txt and the textures/…/Face folders).') + ' Untick a layer to see what it adds.' +
      (ch.faceSkipped && ch.faceSkipped.length ? ' Not placed yet (smaller than the face texture, position unknown): ' + ch.faceSkipped.join(' · ') + '.' : ''))));
  if (S.armor) {
    const bySlot = {};
    for (const [key, item] of Object.entries(S.armor)) {
      if (item.group === 'base' || item.group === 'weapons') continue;
      const side = itemSide(item, ch.gender, 'default'); if (!side) continue;
      (bySlot[slotOf(key)] = bySlot[slotOf(key)] || []).push(key);
    }
    const rows = [];
    for (const [slot] of SLOTS) {
      const keys = (bySlot[slot] || []).sort();
      if (!keys.length) continue;
      const extraOpts = slot === 'Head' ? S.overlay.models().map((m) => [EXTRA + m, 'extra: ' + m]) : [];
      rows.push(select(slot, [['', 'none'], ...extraOpts, ...keys.map((k) => [k, k.replace(/^model\.(armour|clothing|decoration)\./, '') + '  [' + S.armor[k].group + ']'])], ch.outfit[slot] || '', (v) => { ch.outfit[slot] = v || null; redo(); }));
      const k = ch.outfit[slot];
      if (k && S.armor[k] && slot !== 'Head') {
        ch.outfitDye = ch.outfitDye || {};
        const d = ch.outfitDye[slot];
        const hex = (rgb) => '#' + rgb.map((x) => x.toString(16).padStart(2, '0')).join('');
        rows.push(el('div', { class: 'dyepick' },
          el('label', { class: 'row chk' }, el('input', { type: 'checkbox', checked: !!d, onchange: (e) => { ch.outfitDye[slot] = e.target.checked ? (ch.lastDye || [150, 30, 30]) : null; redo(); } }), el('span', {}, 'dye')),
          el('input', { type: 'color', value: hex(d || ch.lastDye || [150, 30, 30]), onchange: (e) => {
            const v = e.target.value; ch.lastDye = [1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16)); ch.outfitDye[slot] = ch.lastDye; redo(); } }),
          el('span', { class: 'kv' }, d ? d.join(' ') : '')));
      }
      if (k && S.armor[k] && Object.keys(S.armor[k].variants).length > 1) {
        rows.push(select('  design', Object.keys(S.armor[k].variants).map((v) => [v, v]), ch.outfitVariant[k] || 'default', (v) => { ch.outfitVariant[k] = v; redo(); }));
      }
    }
    rows.push(el('label', { class: 'row' }, el('span', {}, 'Armour dye strength'), el('input', { type: 'range', min: 0, max: 1, step: 0.05, value: ch.armourDyeStrength ?? 0.5,
      onchange: (e) => { ch.armourDyeStrength = Number(e.target.value); redo(); } })));
    // rings and earrings: models on the hand / head bones
    for (const [slot, , re] of JEWEL_SLOTS) {
      const opts = S.mappings.filter((e) => re.test(e.key) && /\.(wom|obj)$/i.test(e.file) && gamePath(e.file)).map((e) => [e.key, e.key.replace(/^model\.decoration\./, '')]);
      for (const m of S.overlay.models()) if (re.test(m)) opts.push([EXTRA + m, (S.overlay.kindOf(m.toLowerCase()) === 'obj' ? 'custom: ' : '(CF) ') + m.split('/').pop()]);
      ch.jewel = ch.jewel || {};
      const sel = select(slot, [['', opts.length ? 'none' : 'none (no items in your files)'], ...opts], ch.jewel[slot] || '', (v) => { ch.jewel[slot] = v || null; redo(); });
      if (!opts.length) { if (/earring/i.test(slot)) continue; sel.querySelector('select').disabled = true; }
      rows.push(sel);
    }
    P.append(section('Outfit (armor.xml)', ...rows, el('div', { class: 'btns' }, el('button', { onclick: () => { ch.outfit = {}; ch.jewel = {}; redo(); } }, 'Undress')),
      el('p', { class: 'hint' }, 'Layers like the game: nude → under-clothes → armour pieces in their body areas. Helmets go on the NullHelmet bone, placed with the <offsetToNull> values from the helmet folder\'s properties.xml' +
        (ch.attached && ch.attached.helmet ? (ch.attached.helmet.group.userData.offset ? ' (offset found).' : ' (no offset found for this helmet).') : '.'))));
  }
}

function downloadCanvas(c, name) {
  if (!c) return;
  c.toBlob((b) => { const a = el('a', { href: URL.createObjectURL(b), download: name }); document.body.append(a); a.click(); a.remove(); });
}
function screenshot() {
  const vis = STUDIO.objs.map((o) => [o.marker.visible, o.aim.visible]);
  STUDIO.objs.forEach((o) => { o.marker.visible = false; o.aim.visible = false; }); renderer.render(scene, camera);
  downloadCanvas(renderer.domElement, (S.current ? S.current.path.split('/').pop().replace(/\.wom$/i, '') : 'view') + '.png');
  STUDIO.objs.forEach((o, i) => { [o.marker.visible, o.aim.visible] = vis[i]; });
}

// ------------------------------------------------------------------ the .jar over http (wom_tool.py viewer serves it)
// Acts like a File for openZip: only the byte ranges that are needed are fetched.
class RangeFile {
  constructor(url, size, name) { this.url = url; this.size = size; this.name = name; }
  slice(a = 0, b = this.size) {
    const url = this.url, end = Math.min(b, this.size) - 1;
    const get = () => fetch(url, { headers: { Range: `bytes=${a}-${end}` } });
    return { size: end - a + 1, arrayBuffer: async () => (await get()).arrayBuffer(), stream: () => {
      const ts = new TransformStream(); get().then((r) => r.body.pipeTo(ts.writable)); return ts.readable; } };
  }
}
async function openJarUrl(url) {
  status.set('Opening ' + url);
  const r = await fetch(url, { method: 'HEAD' });
  if (!r.ok) { status.done(); toast('Could not open ' + url); return; }
  await loadJars([new RangeFile(url, Number(r.headers.get('Content-Length')), decodeURIComponent(url.split('/').pop()))]);
}

// remember the picked graphics.jar (Chrome/Edge): next time one click reopens it
const JARDB = {
  db() { return new Promise((res, rej) => { const q = indexedDB.open('womviewer', 1); q.onupgradeneeded = () => q.result.createObjectStore('h'); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); }); },
  async put(v) { try { const d = await this.db(); await new Promise((res) => { const t = d.transaction('h', 'readwrite'); t.objectStore('h').put(v, 'jars'); t.oncomplete = res; t.onerror = res; }); } catch (e) { /* not available */ } },
  async get() { try { const d = await this.db(); return await new Promise((res) => { const q = d.transaction('h').objectStore('h').get('jars'); q.onsuccess = () => res(q.result || null); q.onerror = () => res(null); }); } catch (e) { return null; } },
};
async function pickJars() {
  const hs = await window.showOpenFilePicker({ multiple: true, types: [{ description: 'Wurm Unlimited packs', accept: { 'application/java-archive': ['.jar', '.zip'] } }] });
  await JARDB.put(hs);
  await loadJars(await Promise.all(hs.map((h) => h.getFile())));
  showReopen(hs);
}
function showReopen(hs) {
  const b = $('#reopen-jar');
  if (!hs || !hs.length) { b.hidden = true; return; }
  b.hidden = false; b.textContent = 'Reopen ' + hs.map((h) => h.name).join(' + ');
  b.onclick = async () => {
    for (const h of hs) if ((await h.queryPermission({ mode: 'read' })) !== 'granted' && (await h.requestPermission({ mode: 'read' })) !== 'granted') { toast('The browser did not allow reading ' + h.name); return; }
    try { await loadJars(await Promise.all(hs.map((h) => h.getFile()))); } catch (e) { toast('Could not reopen: ' + e.message + ' - pick the .jar again'); }
  };
}

// ------------------------------------------------------------------ opening the game files and your folders
async function loadJars(fileList) {
  // .jar packs (zip files) are read in place. Picking the whole game folder uses its packs/*.jar.
  let jars = fileList.filter((f) => /\.(jar|zip)$/i.test(f.name) && !/^sound/i.test(f.name));
  const packs = jars.filter((f) => /(^|\/)packs\//i.test((f.webkitRelativePath || f._rel || '').replace(/\\/g, '/')));
  if (packs.length) jars = packs;
  if (!jars.length) { toast('No .jar file picked (graphics.jar is in <game>/packs)'); return; }
  const entries = [];
  for (const j of jars) {
    status.set('Reading the index of ' + j.name, 0);
    try { entries.push(...await openZip(j)); } catch (e) { toast(j.name + ': ' + e.message); }
  }
  if (!entries.length) { status.done(); return; }
  S.fs = new GameFiles(); S.texCache.clear(); S.animCache.clear();
  status.set('Indexing ' + entries.length + ' files', 0);
  await S.fs.add(entries, (n) => status.set('Indexing files ' + n + '/' + entries.length, n / entries.length));
  S.jarName = jars.map((j) => j.name).join(' + ');
  await reloadConfig();
  updateSourceUI();
  status.done(`${S.jarName}: ${S.fs.files.size} files · ${S.fs.list('.wom').length} .wom · mappings: ${S.mappings.length ? S.mappings.length + ' lines' : 'not found'} · armor.xml: ${S.armor ? 'yes' : 'no'}`);
  renderList();
  if (S.current) await openModel(S.current.path, S.current.overrides, S.current.itemKey);
}

/** mappings.txt / armor.xml / properties.xml from the .jar, with the custom folder's on top */
async function reloadConfig() {
  const xml = (t) => new DOMParser().parseFromString(t, 'application/xml');
  const shallowFs = (n) => S.fs.findByName(n).sort((a, b) => a.split('/').length - b.split('/').length)[0];
  const cfFile = (n) => { if (!S.useOverlay) return null; const k = S.overlay.findByName(n).filter((x) => S.overlay.kindOf(x) === 'cf').pop(); return k ? [k, S.overlay.get(k)] : null; };
  const objMaps = S.useOverlay ? S.overlay.findByName('mappings.txt').filter((x) => S.overlay.kindOf(x) === 'obj') : [];
  // mappings: the game's, then the custom folder's mappings.txt or mappings_matched.txt (same key = custom wins)
  let maps = [];
  const mt = shallowFs('mappings.txt');
  if (mt) maps = parseMappings(await S.fs.text(mt));
  S.mapSource = mt ? 'game' : '';
  const cm = cfFile('mappings.txt') || cfFile('mappings_matched.txt');
  if (cm) {
    const byKey = new Map(maps.map((e) => [e.key, e]));
    for (const e of parseMappings(await cm[1].text())) byKey.set(e.key, e);
    maps = [...byKey.values()]; S.mapSource = (S.mapSource ? 'game + ' : '') + 'custom ' + cm[0].split('/').pop();
  }
  for (const k of objMaps) {   // custom objects' own mappings.txt lines (paths are inside that folder)
    const dir = dirOf(S.overlay.orig.get(k));
    const byKey = new Map(maps.map((e) => [e.key, e]));
    for (const e of parseMappings(await S.overlay.get(k).text())) { e.file = normPath((dir ? dir + '/' : '') + e.file); byKey.set(e.key, e); }
    maps = [...byKey.values()]; S.mapSource = (S.mapSource ? S.mapSource + ' + ' : '') + 'custom object ' + k;
  }
  S.mappings = maps;
  S.armor = null;
  const ax = shallowFs('armor.xml'); const cax = cfFile('armor.xml');
  try {
    if (ax) { S.armor = parseArmor(xml(await S.fs.text(ax))); S.armorDir = dirOf(ax); }
    else if (cax) { S.armor = parseArmor(xml(await cax[1].text())); S.armorDir = dirOf(cax[0]); }
  } catch (e) { toast('armor.xml: ' + e.message); }
  S.props = {};
  const addProps = async (dir, text) => {
    try { const d = parseProperties(xml(text));
      for (const [k, v] of Object.entries(d)) { v.anims.forEach((a) => { a.file = normPath(dir + '/' + a.file); }); S.props[k] = v; } } catch (e) { console.warn(dir, e); }
  };
  for (const px of S.fs.findByName('properties.xml')) await addProps(dirOf(px), await S.fs.text(px));
  if (S.useOverlay) for (const k of S.overlay.findByName('properties.xml')) if (S.overlay.kindOf(k) === 'cf') await addProps(dirOf(S.overlay.orig.get(k)), await S.overlay.get(k).text());
  computeMapPrefix();
}

/** loose (extracted) game files as the base instead of a .jar (used by the automated test page) */
async function loadLoose(files) {
  S.fs = new GameFiles(); S.texCache.clear(); S.animCache.clear();
  await S.fs.add(files); S.jarName = S.fs.root || 'folder';
  await reloadConfig(); updateSourceUI(); renderList();
}
function updateSourceUI() {
  $('#folder-name').textContent = S.jarName ? S.jarName + ' (read in place)' : '';
  $('#folder-name').title = $('#folder-name').textContent;
  const box = $('#overlay-box');
  box.hidden = !S.overlay.files.size && !S.upscale.count;
  const parts = [];
  S.overlay.names.forEach((n, i) => parts.push((S.overlay.kinds[i] === 'obj' ? 'custom: ' : 'CF: ') + n));
  if (S.upscale.count) parts.push('upscale: ' + S.upscale.name + ' (' + S.upscale.count + ')');
  $('#overlay-name').textContent = parts.join(' · ');
  box.title = 'Your folders over the game files (the last one added wins): ' + parts.join(', ');
  // 4096 = textures from the upscale folder
  const sel = $('#tier');
  sel.textContent = '';
  for (const [v, t] of tierOptions()) { const o = el('option', { value: v }, t); if (v === S.tierUI) o.selected = true; sel.append(o); }
  if (CMP.on) updateCompareUI();
}
function setTier(v) {
  S.tierUI = v; S.useUpscale = v === '4096' && S.upscale.count > 0; S.tier = v === '4096' ? '2048' : v;
}
async function reopen() {
  if (!S.current) return;
  await openModel(S.current.path, S.current.overrides, S.current.itemKey);
}

if (window.showOpenFilePicker) {   // pick through the File System Access API so the choice can be remembered
  $('#open-jar').addEventListener('click', (e) => { e.preventDefault(); pickJars().catch((err) => { if (err.name !== 'AbortError') toast(err.message); }); });
  // the jar picked last time: loads by itself when the browser still allows it, else one click
  JARDB.get().then(async (hs) => {
    if (!hs || !hs.length || qs.get('jar')) return;
    showReopen(hs);
    try {
      if ((await Promise.all(hs.map((h) => h.queryPermission({ mode: 'read' })))).every((p) => p === 'granted')) $('#reopen-jar').click();
      else status.done('Click "' + $('#reopen-jar').textContent + '" to load the game files again (the browser asks once), or start the viewer with "WOM Viewer.bat".');
    } catch (e) { /* not allowed here */ }
  });
} else if (!qs.get('jar')) {
  status.done('Tip: start the viewer with "WOM Viewer.bat" (or python wom_viewer.py) to load graphics.jar by itself. This browser can\'t remember picked files.');
}
$('#open-jar').addEventListener('change', (e) => { if (e.target.files.length) loadJars(Array.from(e.target.files)); e.target.value = ''; });
// custom folder: e.g. player_obj from the converter (.obj, .wom, textures, mappings), listed with (CF)
$('#open-folder').addEventListener('change', async (e) => {
  const files = Array.from(e.target.files); e.target.value = '';
  if (!files.length) return;
  if (!S.fs.files.size && files.some((f) => /(^|\/)packs\/graphics\.jar$/i.test(f.webkitRelativePath || ''))) { await loadJars(files); return; }   // they picked the game folder
  status.set('Reading custom folder (' + files.length + ' files)');
  await S.overlay.add(files, 'cf'); S.useOverlay = true; $('#overlay-on').checked = true; S.texCache.clear();
  await reloadConfig(); updateSourceUI(); renderList();
  status.done(`Custom folder "${S.overlay.names[S.overlay.names.length - 1]}": ${S.overlay.models().length} models, ${S.overlay.count} textures` + (S.mapSource ? ' · mappings: ' + S.mapSource : ''));
  await reopen();
});
// custom object: a folder with new or replacing objects (e.g. NewHair/femaleHair08.obj = an extra hair)
$('#open-overlay').addEventListener('change', async (e) => {
  const files = Array.from(e.target.files); e.target.value = '';
  if (!files.length) return;
  await S.overlay.add(files, 'obj'); S.useOverlay = true; $('#overlay-on').checked = true; S.texCache.clear();
  await reloadConfig(); updateSourceUI(); renderList();
  status.done(`Custom objects "${S.overlay.names[S.overlay.names.length - 1]}": ${S.overlay.models().length} models in all`);
  await reopen();
});
// upscale folder: the output of "upscale" (its 2048 folders, or the plain folders where there are none) = the 4096 option
$('#open-upscale').addEventListener('change', async (e) => {
  const files = Array.from(e.target.files).filter((f) => /\.(dds|png|jpe?g|tga|bmp)$/i.test(f.name)); e.target.value = '';
  if (!files.length) { toast('No textures in that folder'); return; }
  S.upscale.clear(); await S.upscale.add(files, 'up');
  setTier('4096'); S.texCache.clear(); updateSourceUI();
  status.done(`Upscale folder "${S.upscale.name}": ${S.upscale.count} textures, shown as the 4096 option`);
  await reopen();
});
$('#overlay-clear').addEventListener('click', async () => {
  S.overlay.clear(); S.upscale.clear(); setTier(S.tierUI === '4096' ? '2048' : S.tierUI); S.texCache.clear();
  await reloadConfig(); updateSourceUI(); renderList();
  status.done('Custom folders, custom objects and upscale folder removed');
  if (S.current && S.current.path.startsWith(EXTRA)) return;
  await reopen();
});
$('#compare-btn').addEventListener('click', () => setCompare(!CMP.on));
$('#overlay-on').addEventListener('change', async (e) => {
  S.useOverlay = e.target.checked; S.texCache.clear(); await reloadConfig(); renderList();
  await reopen();
});
$('#tier').addEventListener('change', async (e) => { setTier(e.target.value); S.texCache.clear(); if (CMP.on) updateCompareUI(); await reopen(); });
$('#search').addEventListener('input', () => renderList());
document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('#tabs button').forEach((x) => x.classList.remove('on')); b.classList.add('on'); renderList();
}));
$('#about-btn').addEventListener('click', () => { $('#about').hidden = !$('#about').hidden; });
// drag and drop a folder
const dz = $('#viewport');
dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('drop'); });
dz.addEventListener('dragleave', () => dz.classList.remove('drop'));
dz.addEventListener('drop', async (e) => {
  e.preventDefault(); dz.classList.remove('drop');
  const items = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  const files = [];
  const walk = async (entry, path) => {
    if (entry.isFile) { const f = await new Promise((r, j) => entry.file(r, j)); f._rel = path + entry.name; files.push(f); if (files.length % 500 === 0) status.set('Reading dropped folder: ' + files.length + ' files'); }
    else if (entry.isDirectory) {
      const rd = entry.createReader();
      for (;;) { const batch = await new Promise((r, j) => rd.readEntries(r, j)); if (!batch.length) break; for (const c of batch) await walk(c, path + entry.name + '/'); }
    }
  };
  for (const it of items) await walk(it, '');
  if (files.some((f) => /\.jar$/i.test(f.name))) await loadJars(files);
  else if (files.length) { await S.overlay.add(files, 'cf'); S.useOverlay = true; S.texCache.clear(); await reloadConfig(); updateSourceUI(); renderList(); status.done('Custom folder added'); await reopen(); }
});

renderList(); renderPanels();

// ?jar=<url>: the .jar served by "python wom_viewer.py" (found through Steam)
if (qs.get('jar')) openJarUrl(qs.get('jar'));
// test hook: ?testlist=<url of JSON {base, files:[...]}> loads files over http (used for automated checks)
if (qs.get('testlist')) {
  (async () => {
    const spec = await (await fetch(qs.get('testlist'))).json();
    const files = [];
    for (const rel of spec.files) {
      const blob = await (await fetch(spec.base + rel)).blob();
      const f = new File([blob], rel.split('/').pop()); f._rel = rel; files.push(f);
    }
    await loadLoose(files);
    window.__ready = true;
  })();
}
window.WV = { S, CMP, setCompare, setTier, loadLoose, reloadConfig, updateSourceUI, openModel, playAnim, stopAnim, dressCharacter, renderPanels, camera, controls, frame, THREE, STUDIO, applyStudio, applyMount, applyTints, applyDye };
