'use strict';
/* Herramientas PDF · interfaz */
const $ = (s, r = document) => r.querySelector(s);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const sleep = ms => new Promise(r => setTimeout(r, ms));
function el(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'value' || k === 'checked' || k === 'disabled') e[k] = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : document.createTextNode(kid));
  return e;
}
async function api(name, ...args) {
  if (window.__DEV__ || !window.pywebview) {
    const r = await fetch('/api/' + name, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(args) });
    const j = await r.json();
    if (j.error) throw new Error(j.error);
    return j.result;
  }
  return await window.pywebview.api[name](...args);
}
const extOf = p => { const m = /\.([^.\\/]+)$/.exec(p || ''); const e = m ? m[1].toLowerCase() : ''; return ({ jpeg: 'jpg', tif: 'tiff', heif: 'heic' })[e] || e; };

let INFO = {};
const S = { view: 'home', tool: null, files: [], opts: {}, pg: null, ed: null, form: null };

/* ───────── avisos y pantalla de espera ───────── */
let toastTimer;
function toast(msg, kind) {
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const t = el('div', { class: 'toast' + (kind === 'err' ? ' err' : ''), role: 'status' }, msg);
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), kind === 'err' ? 6000 : 3500);
}
function busy(on, msg) {
  let b = $('.busy');
  if (!on) { if (b) b.remove(); return; }
  if (!b) {
    b = el('div', { class: 'busy' }, el('div', { class: 'b' }, el('div', { class: 'spin' }), el('b', { id: 'busyT' }, 'Procesando…'), el('div', { id: 'busyM', style: 'color:var(--mute);margin-top:6px;font-size:14px' })));
    document.body.append(b);
  }
  if (msg != null) $('#busyM').textContent = msg;
}

/* ───────── herramientas ───────── */
const CATS = {
  'Organizar': '#FF6B57', 'Optimizar': '#34C98B', 'Convertir a PDF': '#5B9DFF', 'Convertir desde PDF': '#A78BFA',
  'Editar y firmar': '#FFB82E', 'Revisar': '#B6E35C', 'Seguridad': '#EC6BA5', 'Imágenes': '#22C7D6'
};
const sel = (k, label, choices, def, extra) => ({ t: 'select', k, label, choices, def, ...(extra || {}) });
const ocrLangChoices = () => {
  const have = INFO.ocr_langs || [], names = { spa: 'Español', eng: 'Inglés', fra: 'Francés', deu: 'Alemán', ita: 'Italiano', por: 'Portugués', cat: 'Catalán' };
  const out = [];
  if (have.includes('spa') && have.includes('eng')) out.push(['spa+eng', 'Español + inglés']);
  for (const l of have) out.push([l, names[l] || l]);
  return out.length ? out : [['eng', 'Inglés']];
};

const TOOLS = [
  { id: 'merge', cat: 'Organizar', icon: '🧩', title: 'Unir PDF', desc: 'Combina varios PDF en uno solo, en el orden que quieras.', exts: ['pdf'], multi: true, order: true, cta: 'Unir PDF',
    opts: [{ t: 'note', text: 'Arrastra las miniaturas (o usa los números) para cambiar el orden. Los PDF se unirán de izquierda a derecha.' }],
    check: (o, f) => f.length < 2 ? 'Añade al menos dos PDF.' : null },
  { id: 'split', cat: 'Organizar', icon: '✂️', title: 'Dividir PDF', desc: 'Separa un PDF por rangos de páginas o en páginas sueltas.', exts: ['pdf'], cta: 'Dividir PDF',
    opts: [
      sel('mode', 'Cómo dividir', [['ranges', 'Por rangos (un archivo por rango)'], ['every', 'Cada cierto número de páginas'], ['all', 'Una página por archivo'], ['extract', 'Extraer páginas en un solo PDF']], 'ranges'),
      { t: 'text', k: 'value', label: 'Páginas', ph: 'Ej.: 1-3, 5, 8-', def: '', show: o => o.mode === 'ranges' || o.mode === 'extract' },
      { t: 'number', k: 'n', label: 'Páginas por archivo', def: 2, min: 1, show: o => o.mode === 'every' },
      { t: 'note', text: 'Los resultados con varios archivos se guardan en una carpeta nueva dentro de Descargas.' }],
    check: o => (o.mode === 'ranges' || o.mode === 'extract') && !String(o.value || '').trim() ? 'Escribe los rangos de páginas, por ejemplo 1-3, 5.' : null },
  { id: 'organize', cat: 'Organizar', icon: '🗂️', title: 'Organizar páginas', desc: 'Reordena, gira y elimina páginas viendo las miniaturas.', exts: ['pdf'], kind: 'pages', apiTool: 'organize', cta: 'Guardar PDF',
    hint: 'Arrastra las páginas para ordenarlas. Con los botones de cada una puedes girarla o eliminarla.' },
  { id: 'delete', cat: 'Organizar', icon: '🗑️', title: 'Eliminar páginas', desc: 'Quita las páginas que no quieras de un PDF.', exts: ['pdf'], kind: 'pages', apiTool: 'organize', cta: 'Guardar PDF', ranges: true,
    hint: 'Pulsa el cubo 🗑 en las páginas que quieras quitar, o escribe un rango.' },
  { id: 'rotate', cat: 'Organizar', icon: '🔄', title: 'Girar páginas', desc: 'Gira todas las páginas o solo algunas.', exts: ['pdf'], kind: 'pages', apiTool: 'organize', cta: 'Guardar PDF', rotateAll: true,
    hint: 'Gira una página con sus botones, o todas a la vez con los de la derecha.' },

  { id: 'compress', cat: 'Optimizar', icon: '🗜️', title: 'Comprimir PDF', desc: 'Reduce el tamaño de tus PDF con la mejor calidad posible.', exts: ['pdf'], multi: true, cta: 'Comprimir',
    opts: [sel('level', 'Nivel de compresión', [['low', 'Baja: mejor calidad'], ['medium', 'Recomendada: equilibrio'], ['high', 'Alta: archivo más pequeño']], 'medium'),
      { t: 'note', text: 'Se reducen las imágenes del PDF. Si ya estaba optimizado, te lo diremos en vez de guardar un archivo peor.' }] },
  { id: 'repair', cat: 'Optimizar', icon: '🩹', title: 'Reparar PDF', desc: 'Intenta recuperar un PDF dañado que no se abre bien.', exts: ['pdf'], multi: true, cta: 'Reparar',
    opts: [{ t: 'note', text: 'Se vuelve a escribir el PDF corrigiendo errores de estructura. No siempre es posible recuperar archivos muy dañados.' }] },
  { id: 'ocr', cat: 'Optimizar', icon: '🔍', title: 'OCR: texto de escaneos', desc: 'Convierte un PDF escaneado en uno donde se puede buscar y copiar el texto.', exts: ['pdf'], multi: true, cta: 'Reconocer texto',
    opts: () => INFO.ocr ? [sel('lang', 'Idioma del documento', ocrLangChoices(), ocrLangChoices()[0][0]),
      sel('output', 'Resultado', [['pdf', 'PDF con texto buscable'], ['txt', 'Solo un archivo de texto (.txt)'], ['both', 'Las dos cosas']], 'pdf'),
      { t: 'note', text: 'Puede tardar un poco: cada página se analiza una por una.' }]
      : [{ t: 'note', warn: true, text: 'El reconocimiento de texto no está disponible en este equipo (falta Tesseract). Si usas la versión completa de la aplicación, debería venir incluido.' }],
    check: () => INFO.ocr ? null : 'El OCR no está disponible en este equipo.' },

  { id: 'img2pdf', cat: 'Convertir a PDF', icon: '🖼️', title: 'Imágenes a PDF', desc: 'Junta fotos o imágenes (JPG, PNG, HEIC…) en un solo PDF.', exts: ['jpg', 'png', 'webp', 'bmp', 'tiff', 'gif', 'heic'], multi: true, order: true, cta: 'Crear PDF',
    opts: [sel('page', 'Tamaño de página', [['a4', 'A4'], ['letter', 'Carta (Letter)'], ['original', 'Igual que la imagen']], 'a4'),
      sel('margin', 'Márgenes', [['small', 'Pequeños'], ['none', 'Sin márgenes'], ['big', 'Grandes']], 'small', { show: o => o.page !== 'original' }),
      { t: 'note', text: 'Cada imagen será una página. Arrástralas para cambiar el orden.' }] },
  { id: 'office2pdf', cat: 'Convertir a PDF', icon: '📄', title: 'Word, Excel y PowerPoint a PDF', desc: 'Convierte documentos de Office a PDF.', exts: ['doc', 'docx', 'odt', 'rtf', 'txt', 'xls', 'xlsx', 'ods', 'csv', 'ppt', 'pptx', 'odp'], multi: true, cta: 'Convertir a PDF',
    opts: () => INFO.office ? [{ t: 'note', text: 'Se usa LibreOffice para conservar el formato del documento.' }]
      : [{ t: 'note', warn: true, text: 'Para esta herramienta necesitas instalar LibreOffice (gratis): libreoffice.org/download. Después vuelve a abrir esta aplicación.' }],
    check: () => INFO.office ? null : 'Falta instalar LibreOffice.' },

  { id: 'pdf2img', cat: 'Convertir desde PDF', icon: '🏞️', title: 'PDF a JPG o PNG', desc: 'Guarda cada página de un PDF como imagen.', exts: ['pdf'], multi: true, cta: 'Convertir a imagen',
    opts: [sel('fmt', 'Formato', [['jpg', 'JPG (más ligero)'], ['png', 'PNG (sin pérdida)']], 'jpg'), sel('dpi', 'Calidad', [['100', 'Normal (100 ppp)'], ['150', 'Buena (150 ppp)'], ['220', 'Alta (220 ppp)'], ['300', 'Máxima (300 ppp)']], '150')] },
  { id: 'pdf2word', cat: 'Convertir desde PDF', icon: '📝', title: 'PDF a Word', desc: 'Convierte un PDF en un documento de Word editable.', exts: ['pdf'], multi: true, cta: 'Convertir a Word',
    opts: [{ t: 'note', text: 'Funciona mejor con PDF que tienen texto real. Si es un escaneo, usa primero la herramienta OCR.' }] },
  { id: 'pdf2xlsx', cat: 'Convertir desde PDF', icon: '📊', title: 'PDF a Excel', desc: 'Pasa las tablas de un PDF a una hoja de Excel con los números ya como números.', exts: ['pdf'], multi: true, cta: 'Convertir a Excel',
    opts: [sel('layout', 'Dónde poner las tablas', [['sheets', 'Una hoja por cada tabla'], ['one', 'Todas en una sola hoja']], 'sheets'),
      { t: 'checkbox', k: 'borderless', label: 'Las tablas no tienen líneas (buscar por la alineación del texto)', def: false },
      { t: 'note', text: 'Funciona con PDF que tienen texto real (no con escaneos; para eso usa antes OCR). Revisa el Excel: las tablas muy complejas pueden no salir perfectas.' }] },
  { id: 'pdf2txt', cat: 'Convertir desde PDF', icon: '🔤', title: 'PDF a texto', desc: 'Extrae todo el texto de un PDF en un archivo .txt.', exts: ['pdf'], multi: true, cta: 'Extraer texto', opts: [] },

  { id: 'imgconv', cat: 'Imágenes', icon: '🔁', title: 'Convertir imágenes', desc: 'Cambia el formato de tus fotos. Incluye HEIC del iPhone.', exts: ['jpg', 'png', 'webp', 'bmp', 'tiff', 'gif', 'heic'], multi: true, cta: 'Convertir',
    opts: [sel('target', 'Convertir a', [['jpg', 'JPG'], ['png', 'PNG'], ['webp', 'WEBP'], ['bmp', 'BMP'], ['tiff', 'TIFF']], 'jpg'),
      { t: 'range', k: 'quality', label: 'Calidad', def: 92, min: 50, max: 100, step: 1, show: o => o.target === 'jpg' || o.target === 'webp' }] },

  { id: 'edit', cat: 'Editar y firmar', icon: '✍️', title: 'Firmar y editar PDF', desc: 'Inserta tus firmas guardadas, textos, fechas o imágenes donde quieras.', exts: ['pdf'], kind: 'editor', cta: 'Guardar PDF firmado' },
  { id: 'fillform', cat: 'Editar y firmar', icon: '📋', title: 'Rellenar formulario', desc: 'Escribe en los campos de un PDF con formulario y guárdalo.', exts: ['pdf'], cta: 'Guardar PDF rellenado',
    opts: () => formOpts(), onFiles: () => loadForm(),
    check: () => !S.form ? 'Espera un momento, estoy leyendo el formulario.' : S.form.fields.length ? null : (S.form.error || 'Este PDF no tiene campos rellenables.'),
    prep: o => { const values = {}; for (const [k, v] of Object.entries(o)) if (k.startsWith('v:')) values[k.slice(2)] = v; return { values, flatten: !!o.flatten }; } },
  { id: 'watermark', cat: 'Editar y firmar', icon: '💧', title: 'Marca de agua', desc: 'Añade un texto como «CONFIDENCIAL» a todas las páginas.', exts: ['pdf'], multi: true, cta: 'Añadir marca de agua',
    opts: [{ t: 'text', k: 'text', label: 'Texto', def: 'CONFIDENCIAL' },
      sel('position', 'Posición', [['center', 'Centro'], ['top', 'Arriba'], ['bottom', 'Abajo']], 'center'),
      { t: 'range', k: 'size', label: 'Tamaño', def: 60, min: 16, max: 160, step: 2 },
      { t: 'range', k: 'opacity', label: 'Opacidad (%)', def: 25, min: 5, max: 100, step: 5 },
      { t: 'range', k: 'angle', label: 'Giro (grados)', def: 45, min: -90, max: 90, step: 5, show: o => o.position === 'center' },
      { t: 'color', k: 'color', label: 'Color', def: '#888888' }],
    check: o => String(o.text || '').trim() ? null : 'Escribe el texto de la marca de agua.',
    prep: o => ({ ...o, opacity: Number(o.opacity) / 100 }) },
  { id: 'numbers', cat: 'Editar y firmar', icon: '🔢', title: 'Numerar páginas', desc: 'Añade el número de página en el sitio que elijas.', exts: ['pdf'], multi: true, cta: 'Numerar páginas',
    opts: [sel('position', 'Posición', [['bottom-center', 'Abajo, centro'], ['bottom-right', 'Abajo, derecha'], ['bottom-left', 'Abajo, izquierda'], ['top-center', 'Arriba, centro'], ['top-right', 'Arriba, derecha'], ['top-left', 'Arriba, izquierda']], 'bottom-center'),
      sel('fmt', 'Formato', [['{n}', '1, 2, 3…'], ['Página {n}', 'Página 1'], ['Página {n} de {total}', 'Página 1 de 10'], ['{n} / {total}', '1 / 10']], '{n}'),
      { t: 'number', k: 'start', label: 'Empezar a contar en', def: 1, min: 0 },
      { t: 'number', k: 'size', label: 'Tamaño de letra', def: 11, min: 6, max: 40 },
      { t: 'number', k: 'margin', label: 'Distancia al borde (mm)', def: 12, min: 3, max: 60 },
      { t: 'checkbox', k: 'skip_first', label: 'No numerar la primera página (portada)', def: false }] },
  { id: 'crop', cat: 'Editar y firmar', icon: '📐', title: 'Recortar PDF', desc: 'Quita márgenes de todas las páginas.', exts: ['pdf'], multi: true, cta: 'Recortar',
    opts: [{ t: 'note', text: 'Indica cuántos milímetros quieres quitar en cada borde. Se aplica a todas las páginas.' },
      { t: 'number', k: 'top', label: 'Arriba (mm)', def: 0, min: 0 }, { t: 'number', k: 'bottom', label: 'Abajo (mm)', def: 0, min: 0 },
      { t: 'number', k: 'left', label: 'Izquierda (mm)', def: 0, min: 0 }, { t: 'number', k: 'right', label: 'Derecha (mm)', def: 0, min: 0 }],
    check: o => (Number(o.top) + Number(o.bottom) + Number(o.left) + Number(o.right)) > 0 ? null : 'Indica cuánto quieres recortar en algún borde.' },

  { id: 'compare', cat: 'Revisar', icon: '🔍', title: 'Comparar dos PDF', desc: 'Muestra en rojo y verde lo que ha cambiado entre dos versiones de un documento.', exts: ['pdf'], multi: true, order: true, ordLabels: ['Original', 'Modificado'], cta: 'Comparar',
    opts: [{ t: 'note', text: 'Elige dos PDF. El primero es el original y el segundo la versión modificada (puedes arrastrarlos para cambiar el orden).' },
      { t: 'note', text: 'El resultado es un PDF con un resumen y cada página marcada: rojo = ya no está, verde = es nuevo, gris = sin cambios.' }],
    check: (o, f) => f.length !== 2 ? 'Elige exactamente dos PDF: el original y el modificado.' : null },
  { id: 'redact', cat: 'Seguridad', icon: '🚫', title: 'Tachar datos sensibles', desc: 'Tapa con negro DNI, IBAN, correos, teléfonos o las palabras que elijas.', exts: ['pdf'], multi: true, cta: 'Tachar datos',
    opts: [{ t: 'note', text: 'Marca qué datos buscar. Se tapan con una caja negra de forma definitiva: las páginas afectadas se convierten en imagen para que el texto tapado no se pueda recuperar.' },
      { t: 'checkbox', k: 'k_dni', label: 'DNI y NIE', def: true }, { t: 'checkbox', k: 'k_iban', label: 'IBAN y cuentas bancarias', def: true },
      { t: 'checkbox', k: 'k_email', label: 'Correos electrónicos', def: true }, { t: 'checkbox', k: 'k_phone', label: 'Teléfonos', def: true },
      { t: 'checkbox', k: 'k_card', label: 'Tarjetas bancarias (16 dígitos)', def: true },
      { t: 'textarea', k: 'words', label: 'Otras palabras o frases (una por línea)', ph: 'Ej.: nombre de una persona, de una empresa…', def: '' },
      { t: 'note', text: 'Solo funciona con PDF que tienen texto real. Revisa siempre el resultado antes de enviarlo a nadie.' }],
    check: o => (['dni', 'iban', 'email', 'phone', 'card'].some(k => o['k_' + k]) || String(o.words || '').trim()) ? null : 'Marca qué datos quieres tachar o escribe alguna palabra.',
    prep: o => ({ kinds: ['dni', 'iban', 'email', 'phone', 'card'].filter(k => o['k_' + k]), words: String(o.words || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean) }) },
  { id: 'protect', cat: 'Seguridad', icon: '🔒', title: 'Proteger con contraseña', desc: 'Pide una contraseña para abrir tus PDF.', exts: ['pdf'], multi: true, cta: 'Proteger PDF',
    opts: [{ t: 'password', k: 'password', label: 'Contraseña', def: '' }, { t: 'password', k: 'password2', label: 'Repite la contraseña', def: '' },
      { t: 'note', text: 'Guarda bien la contraseña: si la pierdes, no se puede recuperar el documento.' }],
    check: o => !o.password ? 'Escribe una contraseña.' : o.password !== o.password2 ? 'Las dos contraseñas no coinciden.' : null,
    prep: o => ({ password: o.password }) },
  { id: 'unlock', cat: 'Seguridad', icon: '🔓', title: 'Quitar contraseña', desc: 'Quita la protección de un PDF cuya contraseña conoces.', exts: ['pdf'], multi: true, cta: 'Quitar contraseña',
    opts: [{ t: 'password', k: 'password', label: 'Contraseña del PDF', def: '' }, { t: 'note', text: 'Solo funciona si sabes la contraseña del documento.' }] },
];
/* Formularios PDF: los campos se leen del propio PDF */
function formOpts() {
  if (!S.files.length) return [{ t: 'note', text: 'Elige un PDF con formulario. Después podrás rellenar aquí sus campos.' }];
  if (!S.form) return [{ t: 'note', text: 'Leyendo el formulario…' }];
  if (S.form.error) return [{ t: 'note', warn: true, text: S.form.error }];
  if (!S.form.fields.length) return [{ t: 'note', warn: true, text: 'Este PDF no tiene campos rellenables. Para escribir encima de cualquier PDF usa «Firmar y editar».' }];
  const out = [{ t: 'note', text: `Campos del formulario: ${S.form.fields.length}. Rellena los que quieras y deja el resto en blanco.` }];
  for (const f of S.form.fields) {
    const label = f.name.length > 30 ? f.name.split(/[.\/]/).pop() : f.name, k = 'v:' + f.name;
    if (f.kind === 'check') out.push({ t: 'checkbox', k, label, def: !!f.value });
    else if (f.kind === 'choice') {
      const opts = [...(f.options || [])]; if (f.value && !opts.includes(f.value)) opts.unshift(f.value);
      out.push({ t: 'select', k, label, choices: [['', '—'], ...opts.map(x => [x, x])], def: f.value || '' });
    } else out.push({ t: f.multiline ? 'textarea' : 'text', k, label, def: f.value || '' });
  }
  out.push({ t: 'checkbox', k: 'flatten', label: 'Dejarlo fijo: que ya no se pueda editar', def: false });
  return out;
}
async function loadForm() {
  const f = S.files[0];
  S.form = null;
  for (const k of Object.keys(S.opts)) if (k.startsWith('v:')) delete S.opts[k];
  renderOptions();
  if (!f) return;
  let r; try { r = await api('form_fields', f.path); } catch (e) { r = { ok: false, error: e.message }; }
  if (S.files[0] !== f) return;
  S.form = r.ok ? { fields: r.fields } : { fields: [], error: r.error || 'No se pudo leer el formulario.' };
  for (const x of S.form.fields) S.opts['v:' + x.name] = x.kind === 'check' ? !!x.value : (x.value ?? '');
  renderOptions();
}
const getOpts = t => (typeof t.opts === 'function' ? t.opts() : (t.opts || []));
const defaultsOf = t => { const o = {}; for (const f of getOpts(t)) if (f.k) o[f.k] = f.def ?? ''; return o; };

/* ───────── navegación ───────── */
function go(view, tool) {
  S.view = view;
  if (tool !== undefined) S.tool = tool;
  document.querySelectorAll('.modal,.toast').forEach(m => m.remove());
  if (view === 'home') renderHome();
  else if (view === 'tool') {
    S.files = []; S.pg = null; S.ed = null; S.form = null; S.opts = defaultsOf(S.tool);
    renderTool();
  }
}

/* ───────── inicio ───────── */
function renderHome(filter = '') {
  const root = $('#app'); root.innerHTML = '';
  const input = el('input', { type: 'search', placeholder: 'Buscar herramienta…', 'aria-label': 'Buscar herramienta', value: filter });
  const home = el('div', { class: 'home' },
    el('div', { class: 'hero' },
      el('div', {}, el('div', { class: 'brand' }, el('div', { class: 'logo' }, el('i')), el('span', { class: 'chip' }, '100 % en tu ordenador · sin internet')), el('h1', {}, 'Herramientas ', el('span', {}, 'PDF')), el('p', {}, 'Todo lo que necesitas para tus documentos, sin subir nada a internet.')),
      el('div', { class: 'search' }, input)),
    el('div', { id: 'cats' }));
  root.append(home);
  const draw = () => {
    const q = input.value.trim().toLowerCase(), box = $('#cats'); box.innerHTML = '';
    let any = false;
    for (const [cat, color] of Object.entries(CATS)) {
      const list = TOOLS.filter(t => t.cat === cat && (!q || (t.title + ' ' + t.desc).toLowerCase().includes(q)));
      if (!list.length) continue; any = true;
      box.append(el('section', { class: 'cat' }, el('h2', {}, cat),
        el('div', { class: 'grid' }, list.map(t => el('button', { class: 'card', style: `--c:${color}`, onclick: () => go('tool', t) },
          el('div', { class: 'ico' }, t.icon), el('b', {}, t.title), el('small', {}, t.desc))))));
    }
    if (!any) box.append(el('div', { class: 'empty-search' }, 'No hay herramientas con ese nombre.'));
  };
  input.addEventListener('input', draw); draw();
  if (filter) { input.focus(); input.setSelectionRange(filter.length, filter.length); }
}

/* ───────── pantalla de herramienta ───────── */
const catColor = t => CATS[t.cat] || '#E8412D';
function topbar(t) {
  return el('div', { class: 'topbar', style: `--c:${catColor(t)}` },
    el('button', { class: 'btn sm', onclick: () => go('home') }, '← Herramientas'),
    el('div', { class: 't' }, el('div', { class: 'ico' }, t.icon), el('div', {}, el('h1', {}, t.title), el('p', {}, t.desc))));
}
function dropZone(t, onPick) {
  const exts = t.exts.map(e => e.toUpperCase()).join(', ');
  return el('div', { class: 'drop', id: 'dropzone' },
    el('div', { class: 'big-ico' }, '📂'),
    el('h2', {}, t.multi ? 'Arrastra tus archivos aquí' : 'Arrastra tu archivo aquí'),
    el('p', {}, 'o elígelos en tu ordenador'),
    el('button', { class: 'btn primary', onclick: onPick }, t.multi ? 'Seleccionar archivos' : 'Seleccionar archivo'),
    el('p', { style: 'font-size:13px;margin-top:6px' }, 'Formatos: ' + exts));
}
async function pickFor(t) {
  const paths = await api('pick_files', t.exts, !!t.multi);
  if (paths && paths.length) await addPaths(paths);
}

function renderTool() {
  const t = S.tool;
  if (t.kind === 'pages' || t.kind === 'editor') return renderVisualEntry();
  const root = $('#app'); root.innerHTML = '';
  const main = el('div', { class: 'main', id: 'main' }), opts = el('div', { class: 'opts', id: 'opts' }), cta = el('div', { class: 'cta' });
  const btn = el('button', { class: 'btn primary big', id: 'run', onclick: runFilesTool }, t.cta);
  cta.append(btn);
  root.append(el('div', { class: 'tool' }, topbar(t), main, el('div', { class: 'side' }, opts, cta)));
  renderOptions(); refreshFiles();
}

function renderOptions() {
  const box = $('#opts'); if (!box) return;
  box.innerHTML = ''; box.append(el('h3', {}, 'Opciones'));
  for (const o of getOpts(S.tool)) if (!o.show || o.show(S.opts)) box.append(fieldEl(o));
}
function fieldEl(o) {
  if (o.t === 'note') return el('div', { class: 'note' + (o.warn ? ' warn' : '') }, o.text);
  const rerender = getOpts(S.tool).some(x => x.show);
  const id = 'f_' + o.k;
  const set = v => { S.opts[o.k] = v; };
  if (o.t === 'checkbox') return el('div', { class: 'field check' }, el('input', { type: 'checkbox', id, checked: !!S.opts[o.k], onchange: e => { set(e.target.checked); if (rerender) renderOptions(); } }), el('label', { for: id }, o.label));
  let input;
  if (o.t === 'select') {
    input = el('select', { id, onchange: e => { set(e.target.value); if (rerender) renderOptions(); } }, o.choices.map(([v, l]) => el('option', { value: v, selected: String(S.opts[o.k]) === String(v) }, l)));
  } else if (o.t === 'range') {
    const rv = el('span', { class: 'rv' }, String(S.opts[o.k]));
    input = el('input', { type: 'range', id, min: o.min, max: o.max, step: o.step || 1, value: S.opts[o.k], oninput: e => { set(Number(e.target.value)); rv.textContent = e.target.value; } });
    return el('div', { class: 'field' }, el('label', { for: id }, o.label, rv), input);
  } else if (o.t === 'textarea') {
    input = el('textarea', { id, placeholder: o.ph || '', rows: o.rows || 4, value: S.opts[o.k] ?? '', oninput: e => set(e.target.value) });
  } else if (o.t === 'color') {
    input = el('input', { type: 'color', id, value: S.opts[o.k], oninput: e => set(e.target.value) });
  } else {
    input = el('input', { type: o.t === 'password' ? 'password' : o.t === 'number' ? 'number' : 'text', id, placeholder: o.ph || '', min: o.min, max: o.max, value: S.opts[o.k], autocomplete: 'off', oninput: e => set(o.t === 'number' ? e.target.value : e.target.value) });
  }
  return el('div', { class: 'field' }, el('label', { for: id }, o.label), input);
}

/* ───────── archivos ───────── */
async function addPaths(paths) {
  const t = S.tool;
  if (!t || S.view !== 'tool') { toast('Primero elige una herramienta.'); return; }
  const ok = paths.filter(p => t.exts.includes(extOf(p))), bad = paths.length - ok.length;
  if (bad) toast(`${bad} archivo(s) ignorado(s): esta herramienta solo acepta ${t.exts.map(e => e.toUpperCase()).join(', ')}.`, 'err');
  if (!ok.length) return;
  const list = t.multi ? ok : [ok[0]];
  const added = [];
  for (const p of list) {
    if (t.multi && S.files.some(f => f.path === p)) continue;
    let info;
    try { info = await api('file_info', p); } catch (e) { info = { ok: false, error: e.message }; }
    if (!info.ok) { toast(info.error || 'No se pudo leer el archivo.', 'err'); continue; }
    added.push(info);
  }
  if (!added.length) return;
  if (t.kind === 'pages' || t.kind === 'editor') {
    const f = added[0];
    if (f.encrypted) { toast('Este PDF está protegido con contraseña. Quítala primero con la herramienta «Quitar contraseña».', 'err'); return; }
    if (f.error || !f.pages) { toast(f.error || 'No se pudo abrir el PDF.', 'err'); return; }
    return t.kind === 'pages' ? openPages(f) : openEditor(f);
  }
  if (!t.multi) S.files = [];
  S.files.push(...added);
  refreshFiles();
  if (t.onFiles) t.onFiles();
  for (const f of added) api('preview', f.path, 150).then(d => { f.thumb = d; const img = document.querySelector(`[data-path="${CSS.escape(f.path)}"] .th`); if (img && d) { img.innerHTML = ''; img.append(el('img', { src: d, alt: '' })); } }).catch(() => { });
}
function blockMsg() {
  const t = S.tool;
  if (t.exts.includes('pdf') && t.id !== 'unlock' && S.files.some(f => f.encrypted)) return 'Hay un PDF protegido con contraseña. Quítala primero con «Quitar contraseña».';
  if (t.check) return t.check({ ...S.opts }, S.files);
  return null;
}
const prepOpts = () => (S.tool.prep ? S.tool.prep({ ...S.opts }) : { ...S.opts });

function refreshFiles() {
  const main = $('#main'), t = S.tool; if (!main) return;
  main.innerHTML = '';
  if (!S.files.length) main.append(dropZone(t, () => pickFor(t)));
  else {
    const list = el('div', { class: 'files', id: 'filelist' });
    S.files.forEach((f, i) => list.append(fileCard(f, i)));
    if (t.multi) list.append(el('button', { class: 'addmore', onclick: () => pickFor(t) }, '＋ Añadir más archivos'));
    main.append(el('p', { class: 'hintline' }, t.order ? 'Arrastra las miniaturas para cambiar el orden.' : `${S.files.length} archivo(s) listo(s). Cambia las opciones a la derecha y pulsa el botón.`), list);
    if (t.order) sortable(list, '.fcard', () => {
      const order = [...list.querySelectorAll('.fcard')].map(c => c.dataset.path);
      S.files.sort((a, b) => order.indexOf(a.path) - order.indexOf(b.path)); renumber();
    });
  }
  const run = $('#run'); if (run) run.disabled = !S.files.length;
}
const ordTxt = (t, i) => (t.ordLabels ? (t.ordLabels[i] || '—') : i + 1);
function renumber() { document.querySelectorAll('.fcard .ord').forEach((o, i) => o.textContent = ordTxt(S.tool, i)); }
function fileCard(f, i) {
  const t = S.tool;
  const th = el('div', { class: 'th' }, f.thumb ? el('img', { src: f.thumb, alt: '' }) : el('span', { class: 'ph' }, f.ext.toUpperCase()));
  const meta = [f.pages ? `${f.pages} pág.` : null, f.size_text].filter(Boolean).join(' · ');
  return el('div', { class: 'fcard', 'data-path': f.path },
    t.order ? el('div', { class: 'ord' }, ordTxt(t, i)) : null,
    el('button', { class: 'x', title: 'Quitar', 'aria-label': 'Quitar ' + f.name, onclick: () => { S.files = S.files.filter(x => x !== f); refreshFiles(); if (t.onFiles) t.onFiles(); } }, '✕'),
    th, el('div', { class: 'nm', title: f.name }, f.name), el('div', { class: 'mt' }, meta),
    f.encrypted && t.id !== 'unlock' ? el('div', { class: 'warn' }, '🔒 Protegido con contraseña') : null);
}

/* Reordenar arrastrando (sin HTML5 drag&drop, para no chocar con los archivos arrastrados desde Windows) */
function sortable(container, itemSel, onEnd) {
  let d = null;
  container.addEventListener('pointerdown', e => {
    const it = e.target.closest(itemSel);
    if (!it || e.button !== 0 || e.target.closest('button,input,select,a')) return;
    d = { it, x: e.clientX, y: e.clientY, moved: false };
  });
  window.addEventListener('pointermove', e => {
    if (!d) return;
    if (!d.moved) {
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 6) return;
      d.moved = true; d.it.classList.add('dragging'); document.body.classList.add('no-select');
    }
    const under = document.elementFromPoint(e.clientX, e.clientY)?.closest(itemSel);
    if (under && under !== d.it && under.parentNode === container) {
      if (d.it.compareDocumentPosition(under) & Node.DOCUMENT_POSITION_FOLLOWING) under.after(d.it); else under.before(d.it);
    }
  });
  const end = () => {
    if (!d) return;
    const moved = d.moved; d.it.classList.remove('dragging'); document.body.classList.remove('no-select'); d = null;
    if (moved) onEnd();
  };
  window.addEventListener('pointerup', end); window.addEventListener('pointercancel', end);
}

/* ───────── ejecutar ───────── */
async function runFilesTool() {
  const t = S.tool, msg = blockMsg();
  if (msg) { toast(msg, 'err'); return; }
  await runApi(t.apiTool || t.id, S.files.map(f => f.path), prepOpts(), () => go('tool', t));
}
async function runApi(tool, files, options, again) {
  busy(true, 'Preparando…');
  const poll = setInterval(async () => { try { const p = await api('progress'); if (p && p.msg) busy(true, p.msg); } catch (e) { } }, 400);
  let res;
  try { res = await api('run', tool, files, options); }
  catch (e) { res = { ok: false, outputs: [], messages: [], errors: [e.message || String(e)] }; }
  clearInterval(poll); busy(false);
  showResult(res, again);
}
function showResult(res, again) {
  const root = $('#app'); root.innerHTML = '';
  const good = res.ok, outs = res.outputs || [];
  const name = p => p.split(/[\\/]/).pop();
  const box = el('div', { class: 'result' + (good ? '' : ' bad') },
    el('div', { class: 'big' }, good ? '✓' : '✕'),
    el('h1', {}, good ? '¡Listo!' : 'No se pudo completar'),
    ...(res.messages || []).map(m => el('p', { class: 'msgs' }, m)),
    good ? el('p', { class: 'msgs' }, 'Guardado en tu carpeta de Descargas.') : null,
    (res.errors || []).length ? el('div', { class: 'errs' }, res.errors.map(e => el('div', {}, '• ' + e))) : null);
  if (outs.length) {
    const shown = outs.slice(0, 8);
    box.append(el('div', { class: 'outs' }, shown.map(p => el('div', {}, el('span', { title: p }, name(p)), el('button', { class: 'btn sm', onclick: () => api('open_path', p) }, 'Abrir'))),
      outs.length > shown.length ? el('div', {}, el('span', {}, `… y ${outs.length - shown.length} más`)) : null));
  }
  box.append(el('div', { class: 'actions' },
    outs.length ? el('button', { class: 'btn primary', onclick: () => api('open_folder', outs.length === 1 ? outs[0] : (res.folder || outs[0])) }, 'Mostrar en la carpeta') : null,
    el('button', { class: 'btn', onclick: again || (() => go('home')) }, good ? 'Hacer otro' : 'Volver a intentarlo'),
    el('button', { class: 'btn ghost', onclick: () => go('home') }, 'Todas las herramientas')));
  root.append(box);
}

/* ───────── organizar / eliminar / girar páginas ───────── */
function renderVisualEntry() {
  const t = S.tool, root = $('#app'); root.innerHTML = '';
  root.append(el('div', { class: 'tool single' }, topbar(t), el('div', { class: 'main', id: 'main' }, dropZone(t, () => pickFor(t)))));
}
let thumbToken = 0;
async function openPages(file) {
  const n = file.pages;
  S.pg = { path: file.path, name: file.name, n, items: Array.from({ length: n }, (_, i) => ({ i, rot: 0, del: false })) };
  renderPages(); await loadThumbs();
}
function renderPages() {
  const t = S.tool, root = $('#app'); root.innerHTML = '';
  const grid = el('div', { class: 'pages', id: 'pgrid' });
  S.pg.items.forEach(it => grid.append(tileEl(it)));
  const side = el('div', { class: 'side' }, el('div', { class: 'opts', id: 'pgside' }), el('div', { class: 'cta' }, el('button', { class: 'btn primary big', id: 'run', onclick: runPages }, t.cta)));
  root.append(el('div', { class: 'tool' }, topbar(t), el('div', { class: 'main' }, el('p', { class: 'hintline' }, t.hint), grid), side));
  sortable(grid, '.tile', () => { const order = [...grid.querySelectorAll('.tile')].map(x => +x.dataset.i); S.pg.items.sort((a, b) => order.indexOf(a.i) - order.indexOf(b.i)); updatePgSide(); });
  updatePgSide();
}
function tileEl(it) {
  const img = el('img', { alt: 'Página ' + (it.i + 1), style: 'display:none' }), ld = el('span', { class: 'ld' }, 'Cargando…');
  const tile = el('div', { class: 'tile' + (it.del ? ' removed' : ''), 'data-i': it.i },
    el('div', { class: 'box' }, ld, img), el('div', { class: 'num' }, 'Página ' + (it.i + 1)),
    el('div', { class: 'tb' },
      el('button', { title: 'Girar a la izquierda', 'aria-label': 'Girar a la izquierda', onclick: () => rotTile(it, -90) }, '↺'),
      el('button', { title: 'Girar a la derecha', 'aria-label': 'Girar a la derecha', onclick: () => rotTile(it, 90) }, '↻'),
      el('button', { class: 'del', title: 'Eliminar / recuperar', 'aria-label': 'Eliminar o recuperar página', onclick: () => { it.del = !it.del; tile.classList.toggle('removed', it.del); updatePgSide(); } }, '🗑')));
  it.el = tile; it.img = img; it.ld = ld;
  if (it.src) setThumb(it);
  img.style.transform = `rotate(${it.rot}deg)`;
  return tile;
}
function setThumb(it) { it.img.src = it.src; it.img.style.display = ''; it.ld.style.display = 'none'; }
function rotTile(it, d) { it.rot = ((it.rot + d) % 360 + 360) % 360; it.img.style.transform = `rotate(${it.rot}deg)`; }
async function loadThumbs() {
  const token = ++thumbToken, pg = S.pg;
  for (let s = 0; s < pg.n; s += 8) {
    if (token !== thumbToken || S.pg !== pg) return;
    const res = await api('thumbs', pg.path, s, 8, 170);
    if (!Array.isArray(res)) { toast('No se pudieron dibujar las miniaturas.', 'err'); return; }
    res.forEach((d, k) => { const it = pg.items.find(x => x.i === s + k); if (it) { it.src = d; if (it.img) setThumb(it); } });
  }
}
function updatePgSide() {
  const side = $('#pgside'); if (!side) return;
  const keep = S.pg.items.filter(x => !x.del).length, t = S.tool;
  side.innerHTML = '';
  side.append(el('h3', {}, 'Resumen'), el('div', { class: 'stat' }, el('b', {}, keep), ` de ${S.pg.n} páginas se guardarán`));
  if (t.ranges) {
    const inp = el('input', { type: 'text', placeholder: 'Ej.: 2-4, 7', id: 'delrange' });
    side.append(el('div', { class: 'field' }, el('label', { for: 'delrange' }, 'Eliminar por rango'), inp,
      el('button', { class: 'btn sm', style: 'margin-top:8px', onclick: () => markRange(inp.value) }, 'Marcar para eliminar')));
  }
  const q = el('div', { class: 'field' }, el('label', {}, 'Acciones rápidas'),
    el('div', { class: 'btnrow' },
      el('button', { class: 'btn sm', onclick: () => { S.pg.items.forEach(x => rotTile(x, -90)); } }, '↺ Girar todas'),
      el('button', { class: 'btn sm', onclick: () => { S.pg.items.forEach(x => rotTile(x, 90)); } }, '↻ Girar todas'),
      t.id === 'organize' ? el('button', { class: 'btn sm', onclick: reversePages }, '⇅ Invertir orden') : null,
      el('button', { class: 'btn sm', onclick: restorePages }, 'Deshacer cambios')));
  side.append(q);
  const run = $('#run'); if (run) run.disabled = keep === 0;
}
function markRange(text) {
  const n = S.pg.n, parts = String(text).split(/[;,]/).map(s => s.trim()).filter(Boolean); let marked = 0;
  for (const p of parts) {
    const m = /^(\d*)\s*-\s*(\d*)$/.exec(p); let a, b;
    if (m) { a = m[1] ? +m[1] : 1; b = m[2] ? +m[2] : n; } else if (/^\d+$/.test(p)) a = b = +p; else { toast(`Rango no válido: «${p}»`, 'err'); return; }
    if (a < 1 || b > n || a > b) { toast(`El rango «${p}» no es válido (el documento tiene ${n} páginas).`, 'err'); return; }
    for (let i = a; i <= b; i++) { const it = S.pg.items.find(x => x.i === i - 1); it.del = true; it.el.classList.add('removed'); marked++; }
  }
  updatePgSide();
}
function reversePages() { const g = $('#pgrid'); [...g.children].reverse().forEach(c => g.append(c)); S.pg.items.reverse(); updatePgSide(); }
function restorePages() {
  const g = $('#pgrid'); S.pg.items.sort((a, b) => a.i - b.i);
  S.pg.items.forEach(it => { it.rot = 0; it.del = false; it.el.classList.remove('removed'); it.img.style.transform = ''; g.append(it.el); });
  updatePgSide();
}
async function runPages() {
  const t = S.tool, g = $('#pgrid');
  const order = [...g.querySelectorAll('.tile')].map(x => +x.dataset.i);
  const pages = order.map(i => S.pg.items.find(x => x.i === i)).filter(x => !x.del).map(x => ({ i: x.i, rot: x.rot }));
  if (!pages.length) { toast('No quedaría ninguna página.', 'err'); return; }
  const suffix = t.id === 'delete' ? 'sin_paginas' : t.id === 'rotate' ? 'girado' : 'organizado';
  await runApi('organize', [S.pg.path], { pages, suffix }, () => go('tool', t));
}

/* ───────── editor: firmar y añadir textos ───────── */
async function openEditor(file) {
  S.ed = { path: file.path, name: file.name, n: file.pages, cur: 0, items: [], sel: null, cache: {}, sigs: [], nid: 1 };
  try { S.ed.sigs = await api('list_signatures'); } catch (e) { }
  renderEditor(); await showEdPage(0);
}
const scopePages = it => ({ all: [...Array(S.ed.n).keys()], first: [0], last: [S.ed.n - 1], this: [it.pg] })[it.scope];
const visibleOn = (it, p) => scopePages(it).includes(p);

function renderEditor() {
  const t = S.tool, root = $('#app'); root.innerHTML = '';
  const frame = el('div', { class: 'pageframe', id: 'frame' }, el('img', { id: 'pimg', alt: 'Página del documento' }));
  const bar = el('div', { class: 'stagebar' },
    el('button', { class: 'btn sm', id: 'prev', onclick: () => showEdPage(S.ed.cur - 1) }, '◀'), el('div', { class: 'pn', id: 'pn' }),
    el('button', { class: 'btn sm', id: 'next', onclick: () => showEdPage(S.ed.cur + 1) }, '▶'));
  const side = el('div', { class: 'side' }, el('div', { class: 'opts', id: 'edside' }), el('div', { class: 'cta' }, el('button', { class: 'btn primary big', id: 'run', onclick: runEditor }, t.cta)));
  root.append(el('div', { class: 'tool' }, topbar(t), el('div', { style: 'display:flex;flex-direction:column;min-height:0;overflow:hidden' }, bar, el('div', { class: 'stagewrap', id: 'stagewrap', onpointerdown: e => { if (e.target.id === 'stagewrap' || e.target.id === 'pimg') selectItem(null); } }, frame)), side));
  new ResizeObserver(() => frame.style.setProperty('--fw', frame.clientWidth + 'px')).observe(frame);
  renderEdSide();
}
async function showEdPage(i) {
  const ed = S.ed; if (!ed || i < 0 || i >= ed.n) return;
  ed.cur = i; $('#pn').textContent = `Página ${i + 1} de ${ed.n}`; $('#prev').disabled = i === 0; $('#next').disabled = i === ed.n - 1;
  if (!ed.cache[i]) {
    busy(true, 'Dibujando la página…');
    const r = await api('page_image', ed.path, i, 1100); busy(false);
    if (r.error) { toast(r.error, 'err'); return; }
    ed.cache[i] = r;
  }
  if (S.ed !== ed || ed.cur !== i) return;
  $('#pimg').src = ed.cache[i].data; drawItems(); $('#stagewrap').scrollTop = 0;
}
function drawItems() {
  const frame = $('#frame'); if (!frame) return;
  frame.querySelectorAll('.it').forEach(x => x.remove());
  for (const it of S.ed.items) if (visibleOn(it, S.ed.cur)) frame.append(itemEl(it));
}
function itemEl(it) {
  const d = el('div', { class: 'it ' + (it.type === 'text' ? 'text' : 'img') + (S.ed.sel === it.id ? ' sel' : ''), 'data-id': it.id });
  placeItem(d, it);
  if (it.type !== 'text') d.append(el('img', { src: it.src, alt: 'Firma o imagen' }));
  d.append(el('i', { class: 'rm', title: 'Quitar' }, '✕'));
  if (it.type !== 'text') d.append(el('i', { class: 'rs', title: 'Cambiar tamaño' }));
  d.addEventListener('pointerdown', e => {
    if (e.target.classList.contains('rm')) { removeItem(it.id); return; }
    e.preventDefault(); selectItem(it.id);
    const fr = $('#frame').getBoundingClientRect(), mode = e.target.classList.contains('rs') ? 'resize' : 'move';
    const st = { x: e.clientX, y: e.clientY, ix: it.x, iy: it.y, w: it.w };
    d.setPointerCapture(e.pointerId);
    const mv = ev => {
      const dx = (ev.clientX - st.x) / fr.width, dy = (ev.clientY - st.y) / fr.height;
      if (mode === 'move') {
        const wf = d.offsetWidth / fr.width, hf = d.offsetHeight / fr.height;
        it.x = clamp(st.ix + dx, 0, Math.max(0, 1 - wf)); it.y = clamp(st.iy + dy, 0, Math.max(0, 1 - hf));
      } else it.w = clamp(st.w + dx, 0.03, 1 - it.x);
      placeItem(d, it);
    };
    const up = () => { d.removeEventListener('pointermove', mv); d.removeEventListener('pointerup', up); d.removeEventListener('pointercancel', up); };
    d.addEventListener('pointermove', mv); d.addEventListener('pointerup', up); d.addEventListener('pointercancel', up);
  });
  return d;
}
function placeItem(d, it) {
  d.style.left = it.x * 100 + '%'; d.style.top = it.y * 100 + '%';
  if (it.type === 'text') { d.textContent = it.text; d.style.fontSize = `calc(var(--fw) * ${it.fs})`; d.style.color = it.color; for (const c of ['rm']) { } }
  else d.style.width = it.w * 100 + '%';
}
function refreshTextEl(it) {
  const d = document.querySelector(`.it[data-id="${it.id}"]`); if (!d) return;
  const rm = d.querySelector('.rm'); d.textContent = it.text; d.style.fontSize = `calc(var(--fw) * ${it.fs})`; d.style.color = it.color; if (rm) d.append(rm);
}
function selectItem(id) {
  S.ed.sel = id;
  document.querySelectorAll('.it').forEach(x => x.classList.toggle('sel', +x.dataset.id === id));
  renderEdSide();
}
function removeItem(id) { S.ed.items = S.ed.items.filter(x => x.id !== id); if (S.ed.sel === id) S.ed.sel = null; drawItems(); renderEdSide(); }
function addItem(o) {
  const it = { id: S.ed.nid++, type: 'image', x: 0.3, y: 0.4, w: 0.3, fs: 0.03, text: '', color: '#000000', scope: 'this', pg: S.ed.cur, ...o };
  S.ed.items.push(it); S.ed.sel = it.id; drawItems(); renderEdSide();
  /* aparece centrado en la parte de la página que se está viendo (si no, podría quedar fuera de pantalla) */
  const d = document.querySelector(`.it[data-id="${it.id}"]`), frame = $('#frame'), wrap = $('#stagewrap');
  if (d && frame && wrap) {
    const fr = frame.getBoundingClientRect(), wr = wrap.getBoundingClientRect();
    const wf = d.offsetWidth / fr.width, hf = d.offsetHeight / fr.height, k = ((S.ed.items.length - 1) % 5) * 0.02;
    const cy = ((Math.max(wr.top, fr.top) + Math.min(wr.bottom, fr.bottom)) / 2 - fr.top) / fr.height;
    it.x = clamp(0.5 - wf / 2 + k, 0, Math.max(0, 1 - wf)); it.y = clamp(cy - hf / 2 + k, 0, Math.max(0, 1 - hf)); placeItem(d, it);
  }
  return it;
}
function renderEdSide() {
  const ed = S.ed, side = $('#edside'); if (!side) return;
  const keepScroll = side.scrollTop; side.innerHTML = '';
  const sigBox = el('div', { class: 'sigs' });
  if (!ed.sigs.length) sigBox.append(el('div', { class: 'note', style: 'grid-column:1/-1;margin:0' }, 'Todavía no tienes firmas guardadas. Crea la primera: se guardará en este ordenador.'));
  for (const s of ed.sigs) sigBox.append(el('div', { class: 'sig', title: 'Insertar esta firma', onclick: () => addItem({ type: 'image', sig: s.id, src: s.data, w: Math.min(0.32, Math.max(0.16, s.w / s.h * 0.1)), x: 0.55, y: 0.8 }) },
    el('img', { src: s.data, alt: 'Firma guardada' }),
    el('i', { title: 'Borrar firma', onclick: async e => { e.stopPropagation(); if (confirm('¿Borrar esta firma guardada?')) { await api('delete_signature', s.id); ed.sigs = ed.sigs.filter(x => x !== s); renderEdSide(); } } }, '✕')));
  side.append(el('div', { class: 'sidesec' }, el('h4', {}, 'Mis firmas'), sigBox,
    el('div', { class: 'btnrow' }, el('button', { class: 'btn sm', onclick: openPad }, '✍️ Dibujar firma'), el('button', { class: 'btn sm', onclick: importSig }, '🖼️ Desde una foto'))));
  side.append(el('div', { class: 'sidesec' }, el('h4', {}, 'Añadir al documento'),
    el('div', { class: 'btnrow' },
      el('button', { class: 'btn sm', onclick: () => { addItem({ type: 'text', text: 'Texto', x: 0.1, y: 0.1 }); setTimeout(() => $('#txt')?.select(), 30); } }, 'Aa Texto'),
      el('button', { class: 'btn sm', onclick: () => addItem({ type: 'text', text: new Date().toLocaleDateString('es-ES'), x: 0.1, y: 0.9 }) }, '📅 Fecha de hoy'),
      el('button', { class: 'btn sm', onclick: addImage }, '🖼️ Imagen'))));
  const it = ed.items.find(x => x.id === ed.sel);
  if (it) {
    const sec = el('div', { class: 'sidesec' }, el('h4', {}, it.type === 'text' ? 'Texto seleccionado' : 'Elemento seleccionado'));
    if (it.type === 'text') {
      sec.append(el('div', { class: 'field' }, el('label', { for: 'txt' }, 'Texto'), el('textarea', { id: 'txt', oninput: e => { it.text = e.target.value; refreshTextEl(it); } }, it.text)),
        el('div', { class: 'field' }, el('label', { for: 'fsz' }, 'Tamaño'), el('input', { type: 'range', id: 'fsz', min: 0.012, max: 0.12, step: 0.002, value: it.fs, oninput: e => { it.fs = +e.target.value; refreshTextEl(it); } })),
        el('div', { class: 'field' }, el('label', { for: 'col' }, 'Color'), el('input', { type: 'color', id: 'col', value: it.color, oninput: e => { it.color = e.target.value; refreshTextEl(it); } })));
    }
    sec.append(el('div', { class: 'field' }, el('label', { for: 'scope' }, 'Mostrar en'),
      el('select', { id: 'scope', onchange: e => { it.scope = e.target.value; drawItems(); } },
        [['this', `Solo esta página (${it.pg + 1})`], ['all', 'Todas las páginas'], ['first', 'Primera página'], ['last', 'Última página']].map(([v, l]) => el('option', { value: v, selected: it.scope === v }, l)))),
      el('button', { class: 'btn sm', onclick: () => removeItem(it.id) }, '🗑 Quitar este elemento'));
    side.append(sec);
  } else if (ed.items.length) side.append(el('div', { class: 'note' }, 'Haz clic en un elemento del documento para editarlo. Arrástralo para moverlo; el círculo de la esquina cambia el tamaño.'));
  side.scrollTop = keepScroll;
  const run = $('#run'); if (run) run.disabled = !ed.items.length;
}
async function addImage() {
  const p = await api('pick_files', ['png', 'jpg', 'jpeg', 'webp', 'bmp'], false);
  if (!p || !p.length) return;
  const src = await api('preview', p[0], 500);
  if (!src) { toast('No se pudo abrir esa imagen.', 'err'); return; }
  addItem({ type: 'image', image: p[0], src, w: 0.3, x: 0.3, y: 0.3 });
}
async function importSig() {
  let r; try { r = await api('import_signature'); } catch (e) { toast(e.message, 'err'); return; }
  if (r.cancelled) return;
  if (!r.ok) { toast(r.error, 'err'); return; }
  await afterNewSig(r.id);
}
async function afterNewSig(id) {
  S.ed.sigs = await api('list_signatures');
  const s = S.ed.sigs.find(x => x.id === id);
  if (s) addItem({ type: 'image', sig: s.id, src: s.data, w: Math.min(0.32, Math.max(0.16, s.w / s.h * 0.1)), x: 0.55, y: 0.8 }); else renderEdSide();
  toast('Firma guardada. Ya la tienes disponible para otros documentos.');
}
function openPad() {
  let ink = '#111111', drawing = false, last = null, any = false;
  const cv = el('canvas', { id: 'pad', width: 1200, height: 480 });
  const ctx = cv.getContext('2d'); ctx.lineCap = ctx.lineJoin = 'round';
  const pos = e => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; };
  let mid = null;
  cv.addEventListener('pointerdown', e => {
    drawing = true; any = true; cv.setPointerCapture(e.pointerId); last = pos(e); mid = last;
    ctx.strokeStyle = ink; ctx.fillStyle = ink; ctx.lineWidth = 7; ctx.beginPath(); ctx.arc(last[0], last[1], 3.5, 0, 7); ctx.fill();
  });
  cv.addEventListener('pointermove', e => {
    if (!drawing) return;
    const p = pos(e), nm = [(last[0] + p[0]) / 2, (last[1] + p[1]) / 2];
    ctx.beginPath(); ctx.moveTo(mid[0], mid[1]); ctx.quadraticCurveTo(last[0], last[1], nm[0], nm[1]); ctx.stroke();
    mid = nm; last = p;
  });
  const endStroke = () => { if (drawing && last && mid) { ctx.beginPath(); ctx.moveTo(mid[0], mid[1]); ctx.lineTo(last[0], last[1]); ctx.stroke(); } drawing = false; };
  cv.addEventListener('pointerup', endStroke); cv.addEventListener('pointercancel', endStroke);
  const dots = ['#111111', '#1B2A9B'].map(c => el('button', { class: 'dot', style: `background:${c}`, 'aria-label': c === '#111111' ? 'Tinta negra' : 'Tinta azul', 'aria-pressed': c === ink ? 'true' : 'false', onclick: () => { ink = c; dots.forEach(x => x.setAttribute('aria-pressed', x === dots[c === '#111111' ? 0 : 1] ? 'true' : 'false')); } }));
  const close = () => m.remove();
  const m = el('div', { class: 'modal', onpointerdown: e => { if (e.target === m) close(); } },
    el('div', { class: 'box' }, el('h3', {}, 'Dibuja tu firma'), cv,
      el('div', { class: 'padtools' }, ...dots, el('button', { class: 'btn sm', style: 'margin-left:auto', onclick: () => { ctx.clearRect(0, 0, cv.width, cv.height); any = false; } }, 'Borrar')),
      el('div', { class: 'btnrow', style: 'justify-content:flex-end' }, el('button', { class: 'btn', onclick: close }, 'Cancelar'),
        el('button', { class: 'btn primary', onclick: async () => {
          if (!any) { toast('Dibuja tu firma primero.', 'err'); return; }
          const r = await api('save_signature', cv.toDataURL('image/png'));
          if (!r.ok) { toast(r.error, 'err'); return; }
          close(); await afterNewSig(r.id);
        } }, 'Guardar firma'))));
  document.body.append(m);
}
async function runEditor() {
  const ed = S.ed;
  if (!ed.items.length) { toast('Añade al menos una firma o un texto.', 'err'); return; }
  if (ed.items.some(i => i.type === 'text' && !i.text.trim())) { toast('Hay un texto vacío. Escríbelo o quítalo.', 'err'); return; }
  const items = ed.items.map(i => ({ type: i.type, x: i.x, y: i.y, w: i.w, fs: i.fs, text: i.text, color: i.color, sig: i.sig, image: i.image, pages: scopePages(i) }));
  await runApi('edit', [ed.path], { items }, () => go('tool', S.tool));
}

/* ───────── arrancar ───────── */
let hoverCount = 0;
window.__dropped = paths => { const dz = $('#dropzone'); if (dz) dz.classList.remove('over'); addPaths(paths); };
window.addEventListener('dragenter', () => { hoverCount++; const dz = $('#dropzone'); if (dz) dz.classList.add('over'); }, true);
window.addEventListener('dragleave', () => { hoverCount = Math.max(0, hoverCount - 1); if (!hoverCount) { const dz = $('#dropzone'); if (dz) dz.classList.remove('over'); } }, true);
window.addEventListener('drop', e => {
  hoverCount = 0; const dz = $('#dropzone'); if (dz) dz.classList.remove('over');
  if (window.__DEV__) {
    e.preventDefault();
    const fl = [...(e.dataTransfer ? e.dataTransfer.files : [])];
    if (fl.length) (async () => {
      const paths = [];
      for (const f of fl) {
        const r = await fetch('/upload?name=' + encodeURIComponent(f.name), { method: 'POST', body: f });
        const j = await r.json(); if (j.result) paths.push(j.result);
      }
      if (paths.length) addPaths(paths);
    })();
  }
}, true);
window.addEventListener('dragover', e => { if (window.__DEV__) e.preventDefault(); });
window.addEventListener('keydown', e => {
  if (S.view === 'tool' && S.ed && (e.key === 'Delete' || e.key === 'Supr') && S.ed.sel && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) removeItem(S.ed.sel);
  if (e.key === 'Escape') document.querySelectorAll('.modal').forEach(m => m.remove());
});

if (window.__PING__) { const ping = () => fetch('/ping', { method: 'POST' }).catch(() => {}); ping(); setInterval(ping, 2000); }
async function boot() {
  try { INFO = await api('info'); } catch (e) { INFO = {}; }
  renderHome();
}
if (window.__DEV__ || (window.pywebview && window.pywebview.api)) boot();
else {
  window.addEventListener('pywebviewready', boot, { once: true });
  setTimeout(() => { if (!$('#app').children.length) $('#app').append(el('div', { class: 'result bad' }, el('h1', {}, 'No se pudo iniciar'), el('p', { class: 'msgs' }, 'La ventana no se conectó con la aplicación. Cierra y vuelve a abrirla.'))); }, 6000);
}
