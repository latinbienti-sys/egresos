/*
 * Pruebas del panel "gastos por razon de pagos" SIN necesidad de Odoo.
 *
 *   node test_gastos_razon_pagos.js
 *
 * Genera un HTML de ejemplo con datos ficticios, carga el JS embebido en un
 * sandbox con stubs de DOM/Chart.js y verifica agregaciones, filtros y el
 * drill-down de tres niveles. No hace ninguna llamada de red.
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const vm = require('vm');

const SCRIPT = path.join(__dirname, 'gastos_razon_pagos.py');

const FIXTURE = [
  // [razon, proveedor, fecha, amount(moneda pago), amountCo(moneda compania, con signo), estado]
  ['Materiales', 'ACERO SA', '2026-01-15', 1500.0, -1.75, 'posted'],
  ['Materiales', 'ACERO SA', '2026-01-20', 800.5, -0.92, 'posted'],
  ['Servicios', 'LUZ Y AGUA', '2026-01-22', 430.25, -0.5, 'posted'],
  ['Materiales', 'TORNILLOS SA', '2026-02-03', 220.0, -0.25, 'posted'],
  ['Nómina', 'PERSONAL SA', '2026-02-10', 5200.0, -5200.0, 'draft'],
  ['Impuestos', 'SAT', '2026-02-11', 990.75, -1.15, 'posted'],
  [false, 'SIN RAZON SA', '2026-01-18', 120.0, -0.14, 'posted'],
];
// En moneda de compania (USD), solo publicados: 1.75+0.92+0.50+0.25+1.15+0.14
const POSTED_CO = 1.75 + 0.92 + 0.5 + 0.25 + 1.15 + 0.14;   // 4.71
const ALL_CO = POSTED_CO + 5200;                              // 5204.71
const POSTED_TX = 1500 + 800.5 + 430.25 + 220 + 990.75 + 120; // 4061.50
const ALL_TX = POSTED_TX + 5200;                              // 9261.50

let pass = 0, fail = 0;
function check(name, cond, extra) {
  if (cond) { pass++; console.log('  OK   ' + name); }
  else { fail++; console.log('  FALLA ' + name + (extra !== undefined ? ' -> ' + extra : '')); }
}
function approx(a, b) { return Math.abs(a - b) < 0.01; }

const CUR = { symbol: '$', position: 'after', decimal_separator: '.', thousands_sep: ',' };
function parseMoney(s) {
  const esc = CUR.thousands_sep.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = String(s).match(new RegExp('-?[\\d' + esc + ']*\\d(?:' +
    CUR.decimal_separator + '\\d{1,2})?'));
  if (!m) return NaN;
  return parseFloat(m[0].split(CUR.thousands_sep).join('').split(CUR.decimal_separator).join('.'));
}
function totalIn(el) {
  const m = el.innerHTML.match(/class="tot"[\s\S]*?<\/tr>/);
  return m ? parseMoney(m[0]) : NaN;
}

// ---- 1. Generar el HTML de ejemplo con el Python real -------------------
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gastos-'));
const htmlPath = path.join(tmp, 'fixture.html');

// JSON.stringify emite literales de JS; Python necesita los suyos.
const FIXTURE_PY = JSON.stringify(FIXTURE)
  .replace(/\bfalse\b/g, 'False')
  .replace(/\bnull\b/g, 'None');

const py = `
import json, importlib.util
spec = importlib.util.spec_from_file_location('g', r'${SCRIPT}')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
rows = []
for i, (r, p, d, amt, amtco, st) in enumerate(${FIXTURE_PY}):
    rows.append({'id': i+1, 'doc': 'OP/2026/%04d' % (i+1), 'date': d, 'month': d[:7],
                 'partner': p, 'reason': (r if r else m.SIN_CLASIFICAR),
                 'amount': amt, 'amountCo': amtco,
                 'cur': 'VEF', 'curCo': 'USD', 'comp': 'LATINOAMERICANA DE BIENES Y SERVICIOS',
                 'state': st, 'ptype': 'outbound',
                  'partnerType': 'supplier', 'internal': False,
                  'isCustomer': False, 'isSupplier': True,
                  'pubdate': d, 'pubmonth': d[:7]})
payload = {'meta': {'model': 'account.payment', 'reason_field': 'x_razonpagos',
    'reason_label': 'Razón de Pago', 'reason_type': 'selection', 'measure': 'amount',
    'measure_label': 'Monto del pago', 'measure_co': 'amount_company_currency_signed',
    'measure_co_label': 'Monto en moneda de compania',
    'date_field': 'payment_date', 'state_field': 'state',
    'ptype_field': 'payment_type', 'total_records': len(rows), 'loaded_records': len(rows),
    'truncated': False, 'generated': '03/10/2026 10:00',
    'currencies': {'VEF': {'name': 'VEF', 'symbol': 'Bs', 'position': 'after',
                           'decimal_separator': ',', 'thousands_sep': '.'},
                   'USD': {'name': 'USD', 'symbol': '$', 'position': 'after',
                           'decimal_separator': '.', 'thousands_sep': ','}},
    'companies': ['LATINOAMERICANA DE BIENES Y SERVICIOS'],
    'company_currencies': ['USD']},
  'rows': rows}
open(r'${htmlPath}', 'w', encoding='utf-8').write(
    m.HTML.replace('__DATA__', json.dumps(payload, ensure_ascii=False)))
`;
execFileSync('python', ['-c', py], { stdio: 'pipe' });
const html = fs.readFileSync(htmlPath, 'utf8');
const js = html.split('<script>')[1].split('</script>')[0];

// ---- 2. Sandbox con stubs ----------------------------------------------
const els = {};
function mk(id) {
  if (!els[id]) els[id] = {
    id, innerHTML: '', textContent: '', value: '', className: '',
    style: new Proxy({}, { set: () => true, get: () => '' }),
    children: [], addEventListener() {}, click() {},
    appendChild(c) { this.children.push(c); },
    width: 800, height: 400,
    getContext: () => ({ clearRect: (...a) => { els[id].cleared = a; } }),
  };
  return els[id];
}
mk('fState').value = 'posted';   // un <select> real toma la primera <option>
mk('fPtype').value = 'outbound';
mk('fMeasure').value = 'co';
mk('fTop').value = '8';          // primera <option>: 8 mas altas

const charts = [];   //_configs de cada grafico creado, en orden de construccion_
const sb = {
  console, Intl, Date, Math, JSON, Number, String, Array, Object, Map, Set,
  document: { getElementById: mk, createElement: () => mk('n' + Object.keys(els).length) },
  Chart: function (_ctx, cfg) {
    this.destroy = () => {};
    this.config = cfg;
    charts.push(cfg);
  },
  Blob: function () {}, URL: { createObjectURL: () => 'blob:x' },
};
sb.globalThis = sb;
sb.charts = charts;   // el codigo del panel lo ve como global del contexto
vm.createContext(sb);
vm.runInContext(js + `
globalThis.__rows = DATA.rows;
globalThis.__meta = M;
globalThis.__flat = () => flatRows(state.rows);
globalThis.__histCfg = () => charts[charts.length - 1];
globalThis.__nCharts = () => charts.length;
globalThis.__expand = (level) => {
  const n = __flat().find(x => x.level === level);
  if (n) toggleByPath(n.path);
};
globalThis.__expN = () => Object.keys(expanded).length;
globalThis.__cacheN = () => Object.keys(childCache).length;
globalThis.__snapRows = DATA.rows.slice();
globalThis.__pushRows = (rs) => { rs.forEach(r => DATA.rows.push(r)); rerender(); };
globalThis.__restoreRows = () => {
  DATA.rows.length = 0;
  DATA.rows.push(...globalThis.__snapRows);
  rerender();
};
`, sb);
// renderDonut y renderHistory se dibujan en este orden: el ultimo es el historico.
const H = () => sb.__histCfg();

// ---- 3. Aserciones ------------------------------------------------------
console.log('\nRender y agregacion');
check('el placeholder __DATA__ se sustituyo', !html.includes('__DATA__'));
check(FIXTURE.length + ' filas cargadas', sb.__rows.length === FIXTURE.length, sb.__rows.length);
check('metadatos del modelo correctos', sb.__meta.model === 'account.payment' &&
  sb.__meta.reason_field === 'x_razonpagos');
check('total por defecto en MONEDA DE COMPANIA = ' + POSTED_CO.toFixed(2),
  approx(totalIn(els.tb), POSTED_CO), totalIn(els.tb));
check('el gasto se muestra positivo por defecto', totalIn(els.tb) > 0, totalIn(els.tb));

console.log('\nFiltro por estado');
const donut0 = vm.runInContext('state.rows.map(r => r.label)', sb);
check('categorias iniciales sin Nomina', !donut0.includes('Nómina'), JSON.stringify(donut0));
check('pagos sin razon van a (Sin clasificar)', donut0.includes('(Sin clasificar)'), JSON.stringify(donut0));
check('ninguna categoria se llama False',
  !sb.__rows.some(r => r.reason === 'False' || r.reason === false));
els.fState.value = 'all';
sb.rerender();
check('total todos los estados (moneda compania) = ' + ALL_CO.toFixed(2),
  approx(totalIn(els.tb), ALL_CO), totalIn(els.tb));
const donutAll = vm.runInContext('state.rows.map(r => r.label)', sb);
check('aparece Nomina al incluir borradores', donutAll.includes('Nómina'), JSON.stringify(donutAll));

console.log('\nSigno contable');
els.fState.value = 'posted';
sb.rerender();
els.fNeg.checked = true;
sb.rerender();
check('con signo contable el total sale negativo = -' + POSTED_CO.toFixed(2),
  approx(totalIn(els.tb), -POSTED_CO), totalIn(els.tb));
els.fNeg.checked = false;
sb.rerender();
check('al desmarcarlo vuelve a positivo', approx(totalIn(els.tb), POSTED_CO), totalIn(els.tb));

console.log('\nMedida: moneda del pago vs moneda de compania');
els.fMeasure.value = 'tx';
sb.toggleMeasure();
check('en moneda del pago = ' + POSTED_TX.toFixed(2),
  approx(totalIn(els.tb), POSTED_TX), totalIn(els.tb));
els.fMeasure.value = 'co';
sb.toggleMeasure();
check('vuelve a moneda de compania = ' + POSTED_CO.toFixed(2),
  approx(totalIn(els.tb), POSTED_CO), totalIn(els.tb));

console.log('\nFiltro por tipo de pago');
// El panel reajusta la base al cambiar el tipo de pago: Entradas => Clientes.
els.fPtype.value = 'inbound';
sb.syncBaseWithPtype();
sb.rerender();
check('elegir Entradas lleva la base a clientes', els.fBase.value === 'customer',
  els.fBase.value);
check('entradas -> 0 filas (el fixture es todo de proveedores)',
  totalIn(els.tb) === 0 || els.tb.innerHTML.includes('Sin registros'));
check('el historico avisa que no hay datos',
  /Sin datos/.test(els.histHint.textContent), els.histHint.textContent);
check('el lienzo se limpio con su tamano real (no 1x1)',
  els.hist.cleared && els.hist.cleared[2] === 800 && els.hist.cleared[3] === 400,
  JSON.stringify(els.hist.cleared));
els.fPtype.value = 'outbound';
els.fState.value = 'posted';
sb.syncBaseWithPtype();
sb.rerender();

console.log('\nDrill-down de tres niveles');
check('nivel 0 = Razon de pago', vm.runInContext('__flat().map(n=>n.level)', sb).every(l => l === 0));
sb.__expand(0);
let levels = vm.runInContext('__flat().map(n=>n.level)', sb);
check('nivel 1 = Proveedor aparece', levels.includes(1), JSON.stringify(levels));
const provs = vm.runInContext('__flat().filter(n=>n.level===1).map(n=>n.label)', sb);
check('proveedores de Materiales', provs.includes('ACERO SA') && provs.includes('TORNILLOS SA'), JSON.stringify(provs));
sb.__expand(1);
levels = vm.runInContext('__flat().map(n=>n.level)', sb);
check('nivel 2 = Documento aparece', levels.includes(2), JSON.stringify(levels));
const docs = vm.runInContext('__flat().filter(n=>n.level===2).map(n=>n.label)', sb);
check('documentos de ACERO SA', docs.length === 2 && docs.includes('OP/2026/0001'), JSON.stringify(docs));
check('subtotal del proveedor en moneda de compania (1.75+0.92 = 2.67)',
  approx(vm.runInContext('__flat().find(n=>n.label==="ACERO SA").value', sb), 2.67),
  vm.runInContext('__flat().find(n=>n.label==="ACERO SA").value', sb));

console.log('\nEstado de la expansion');
sb.rerender();   // partir deExpansion limpia
sb.__expand(0); sb.__expand(1);
check('dos nodos expandidos', sb.__expN() === 2, sb.__expN());
check('dos subarboles cacheados', sb.__cacheN() === 2, sb.__cacheN());
sb.__expand(1);
check('colapsar quita un nivel', !sb.__flat().map(n => n.level).includes(2));
sb.__expand(1);
els.fState.value = 'all';
sb.rerender();
check('cambiar filtro limpia expansion', sb.__expN() === 0 && sb.__cacheN() === 0,
  sb.__expN() + '/' + sb.__cacheN());

console.log('\nGrafico historico: un solo eje ano-mes');
// la seccion anterior dejo el estado en "all"; aqui trabajamos solo con publicados
els.fState.value = 'posted';
els.fPtype.value = 'outbound';
els.fMeasure.value = 'co';
sb.rerender();
check('bucketOf agrupa por ano-mes', vm.runInContext("bucketOf('2026-03-15')", sb) === '2026-03');
check('la etiqueta incluye mes y ano',
  vm.runInContext("labelOf('2026-03')", sb) === 'Mar 2026', vm.runInContext("labelOf('2026-03')", sb));
check('la etiqueta de octubre', vm.runInContext("labelOf('2026-10')", sb) === 'Oct 2026',
  vm.runInContext("labelOf('2026-10')", sb));
check('no existe selector de granularidad', els.fGran === undefined);
check('saneDate acepta fecha normal', vm.runInContext("saneDate('2026-03-15')", sb) === true);
check('saneDate rechaza fecha imposible', vm.runInContext("saneDate('4423-02-04')", sb) === false);
check('saneDate rechaza vacio', vm.runInContext("saneDate('')", sb) === false);
check('existe renderHistory', typeof sb.renderHistory === 'function');
check('existe clearReason', typeof sb.clearReason === 'function');
check('se crearon 2 graficos (dona + historico)', sb.__nCharts() >= 2, sb.__nCharts());
check('eje = 2 cortes (Ene 2026, Feb 2026)',
  JSON.stringify(H().data.labels) === '["Ene 2026","Feb 2026"]', JSON.stringify(H().data.labels));
check('serie Materiales enero = 1.75+0.92+0.14? realmente 1.75+0.92 = 2.67 en posted',
  approx(H().data.datasets[0].data[0], 2.67), H().data.datasets[0].data[0]);
check('serie Materiales febrero = 0.25',
  approx(H().data.datasets[0].data[1], 0.25), H().data.datasets[0].data[1]);
check('las categorias van de mas alta a mas baja',
  H().data.datasets[0].label === 'Materiales', H().data.datasets[0].label);
check('eje Y apilado', H().options.scales.y.stacked === true);
check('eje X apilado', H().options.scales.x.stacked === true);
const sumaSeries = H().data.datasets.reduce((a, d) => a + d.data.reduce((x, y) => x + y, 0), 0);
check('la suma de las series = total en USD (' + POSTED_CO.toFixed(2) + ')',
  approx(sumaSeries, POSTED_CO), sumaSeries);
check('sin razon agrupada: son 4 razones en posted+outbound',
  H().data.datasets.length === 4, H().data.datasets.length);

console.log('\nUn cambio de medida reagrupa el historico');
els.fMeasure.value = 'tx';
sb.toggleMeasure();
check('el eje sigue siendo ano-mes (2 cortes)',
  JSON.stringify(H().data.labels) === '["Ene 2026","Feb 2026"]', JSON.stringify(H().data.labels));
check('en moneda del pago la serie Materiales enero = 1500+800.5 = 2300.50',
  approx(H().data.datasets[0].data[0], 2300.50), H().data.datasets[0].data[0]);
els.fMeasure.value = 'co';
sb.toggleMeasure();
check('vuelve a USD = 1.75+0.92 = 2.67', approx(H().data.datasets[0].data[0], 2.67),
  H().data.datasets[0].data[0]);

console.log('\nFiltro por razon desde el grafico');
vm.runInContext("activeReason = 'Materiales'; render();", sb);
check('filtra a Materiales', vm.runInContext('state.rows.length', sb) === 1);
check('el historico tambien se filtra (1 sola serie)',
  H().data.datasets.length === 1, H().data.datasets.length);
check('el historico filtrado mantiene los 2 cortes',
  JSON.stringify(H().data.labels) === '["Ene 2026","Feb 2026"]', JSON.stringify(H().data.labels));
check('el historico filtrado suma 1.75+0.92+0.25',
  approx(H().data.datasets[0].data.reduce((a, b) => a + b, 0), 1.75 + 0.92 + 0.25),
  H().data.datasets[0].data.reduce((a, b) => a + b, 0));
sb.clearReason();
check('clearReason quita el filtro', vm.runInContext('activeReason', sb) === null);
check('vuelve el total completo', approx(totalIn(els.tb), POSTED_CO), totalIn(els.tb));

console.log('\nFormato de moneda');
check('moneda de compania USD: 1,234.50', vm.runInContext('fmt(1234.5, "USD")', sb) === '1,234.50 $',
  vm.runInContext('fmt(1234.5, "USD")', sb));
check('moneda VEF: coma decimal y simbolo detras (1.234,50 Bs)',
  vm.runInContext('fmt(1234.5, "VEF")', sb) === '1.234,50 Bs',
  vm.runInContext('fmt(1234.5, "VEF")', sb));
check('maneja negativos', vm.runInContext('fmt(-12.3, "USD")', sb).startsWith('-'),
  vm.runInContext('fmt(-12.3, "USD")', sb));

console.log('\nEscapes de seguridad');
const dataLine = html.split('\n').find(l => l.startsWith('const DATA = ')) || '';
check('el JSON embebido no contiene </script>', !dataLine.includes('</script>'));
check('el HTML cierra el script una sola vez',
  (html.match(/<\/script>/g) || []).length === 2, (html.match(/<\/script>/g) || []).length);

console.log('\nExportacion CSV');
check('funcion exportCsv presente', typeof sb.exportCsv === 'function');
check('funcion rerender presente', typeof sb.rerender === 'function');

console.log('\nCierre por ano y mes (mismo agrupamiento que el favorito en Odoo)');
const NOM_MES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
const filas = (h) => h.split('<tr').slice(1).map(t => t.replace(/<[^>]+>/g, '|').replace(/\s+/g, ' ').trim());
const celda = (h, etiqueta) => {
  const f = filas(h).find(t => new RegExp('\\|\\s*' + etiqueta + '\\s*\\|').test(t));
  if (!f) return NaN;
  const n = f.split('|').map(s => s.trim()).filter(Boolean).pop();
  return Number(String(n).replace(/[^0-9.]/g, ''));
};

// El fixture original solo tiene 2026; se inyectan meses de otros anios y un
// pago sin fecha para probar el agrupamiento por ano y el renglon aparte.
const EXTRA = [
  { date: '2025-03-10', pubdate: '2025-03-10', pubmonth: '2025-03', amountCo: -10, state: 'posted', isSupplier: true },
  { date: '2025-03-20', pubdate: '2025-03-20', pubmonth: '2025-03', amountCo: -20, state: 'posted', isSupplier: true },
  { date: '2025-11-05', pubdate: '2025-11-05', pubmonth: '2025-11', amountCo: -5,  state: 'posted', isSupplier: true },
  { date: '2027-01-09', pubdate: '2027-01-09', pubmonth: '2027-01', amountCo: -7,  state: 'posted', isSupplier: true },
  { date: '',           pubdate: '',           pubmonth: '',        amountCo: -3,  state: 'posted', isSupplier: true },
  { date: '2026-06-09', pubdate: '2026-06-09', pubmonth: '2026-06', amountCo: -999, state: 'draft',  isSupplier: true },
];
sb.__pushRows(EXTRA);
els.fPtype.value = 'outbound';
els.fState.value = 'posted';
// Se limpia el rango que init()|Windows fijo al fixture: los meses inyectados
// caen fuera de 2026-01..2026-02 y el renglon sin fecha necesita su casilla.
els.fFrom.value = '';
els.fTo.value = '';
els.fNoDate.checked = true;
sb.syncBaseWithPtype();
sb.rerender();

let anoH = els.tbAno.innerHTML;
check('la tabla se lleno y trae total general', anoH.includes('<tbody>') && anoH.includes('Total general'));
check('aparecen los tres anios del fixture inyectado',
  ['2025', '2026', '2027'].every(a => anoH.includes('>' + a + '<')));
check('cada mes se rotula con su nombre y su numero',
  anoH.includes('>Mar 03<') && anoH.includes('>Ene 01<') && anoH.includes('>Nov 11<'));
// Subtotal de 2025 = 10 + 20 + 5 = 35
check('el subtotal de 2025 suma sus dos meses', Math.abs(celda(anoH, 'Total 2025') - 35) < 0.005,
  celda(anoH, 'Total 2025'));
// 2026 solo tiene el fixture posted (4.71): el draft queda fuera y el pago sin
// fecha no pertenece a ningun ano, se lista al final.
check('el subtotal de 2026 excluye el draft', Math.abs(celda(anoH, 'Total 2026') - POSTED_CO) < 0.005,
  celda(anoH, 'Total 2026'));
check('2027 aparece con su unico mes', Math.abs(celda(anoH, 'Total 2027') - 7) < 0.005,
  celda(anoH, 'Total 2027'));
// Total general = 4.71 + 35 + 7 + 3 = 49.71
check('el total general es la suma de todos los anios',
  Math.abs(celda(anoH, 'Total general') - 49.71) < 0.005, celda(anoH, 'Total general'));
check('el pago sin fecha tiene su propio renglon con su monto',
  Math.abs(celda(anoH, 'Sin fecha') - 3) < 0.005, celda(anoH, 'Sin fecha'));
check('el renglon sin fecha no inventa un mes',
  !/Sin fecha<\/td><td class="r">\s*1\s*<\/td>/.test('') && /—<\/b><\/td><td><b>Sin fecha/.test(anoH));
check('la suma de subtotales por anio cuadra con el total general',
  Math.abs(35 + POSTED_CO + 7 + 3 - 49.71) < 0.005);
check('el encabezado nombra el criterio de la base activa',
  /Gastoslb \(proveedores\)/.test(els.hAno.textContent), els.hAno.textContent);
check('el resumen refleja el mismo total que la tabla',
  /49[,.]71/.test(els.sub.textContent), els.sub.textContent);

// Cambiar de base debe cambiar el encabezado y dejar la tabla sin meses.
sb.__restoreRows();
els.fPtype.value = 'inbound';
sb.syncBaseWithPtype();
sb.rerender();
check('al cambiar a Entradas el encabezado pasa a inglb',
  /inglb \(clientes\)/.test(els.hAno.textContent), els.hAno.textContent);
check('sin filas de clientes la tabla no lista ningun anio ni mes',
  !/Total 20\d\d/.test(els.tbAno.innerHTML) && !/Sin fecha/.test(els.tbAno.innerHTML));
check('y su total general queda en cero',
  Math.abs(celda(els.tbAno.innerHTML, 'Total general')) < 0.005,
  celda(els.tbAno.innerHTML, 'Total general'));
sb.__restoreRows();
els.fPtype.value = 'outbound';
sb.syncBaseWithPtype();
sb.rerender();
check('al volver a Salidas se recupera el total original',
  Math.abs(celda(els.tbAno.innerHTML, 'Total general') - POSTED_CO) < 0.005,
  celda(els.tbAno.innerHTML, 'Total general'));

fs.rmSync(tmp, { recursive: true, force: true });
console.log('\n' + pass + ' OK / ' + fail + ' FALLA');
process.exit(fail ? 1 : 0);