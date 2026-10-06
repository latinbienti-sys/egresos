// Pruebas de la base de ingresos de clientes (favorito "inglb" de Pagos).
// Criterio: partner_type = customer, sin transferencias internas, fecha de
// publicacion, y los descuentos se restan aunque en Odoo lleguen positivos.
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(__dirname + '/gastos_razon_pagos.html', 'utf8');
const js = html.split('<script>')[1].split('</script>')[0];

let ok = 0, fail = 0;
function check(name, cond, extra) {
  if (cond) { ok++; console.log('  OK   ' + name); }
  else { fail++; console.log('  FALLA ' + name + (extra ? ' -> ' + extra : '')); }
}
function near(a, b) { return Math.abs(a - b) < 0.005; }
const money = (x) => Number(x).toLocaleString('en-US',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const charts = []; const els = {};
function mk(id) {
  if (!els[id]) els[id] = { id, value: '', innerHTML: '', textContent: '', style: {}, children: [],
    addEventListener() {}, click() {}, appendChild(c) { this.children.push(c); },
    getContext: () => ({ clearRect() {} }), width: 800, height: 400 };
  return els[id];
}
els.fState = mk('fState'); els.fState.value = 'posted';
// Entradas: el preset del panel lleva la base a clientes al abrir.
els.fPtype = mk('fPtype'); els.fPtype.value = 'inbound';
els.fMeasure = mk('fMeasure'); els.fMeasure.value = 'co';
els.fNeg = mk('fNeg'); els.fNeg.checked = false;
els.fBase = mk('fBase'); els.fBase.value = 'flow';
els.fDate = mk('fDate'); els.fDate.value = 'pub';
['fCur', 'fComp'].forEach(k => els[k] = mk(k));
els.fFrom = mk('fFrom');
els.fTo = mk('fTo');
els.fTop = mk('fTop'); els.fTop.value = '8';
['hist', 'donut', 'tb', 'chips', 'kpis', 'warn', 'sub'].forEach(k => els[k] = mk(k));

const sb = { console, Intl, Date, Math, JSON, Number, String, Array, Object, Map, Set, charts,
  document: { getElementById: mk, createElement: () => mk('c' + Math.random()) },
  Chart: function (c, cfg) { charts.push(cfg); this.destroy = () => {}; } };
sb.globalThis = sb; vm.createContext(sb);
vm.runInContext(js, sb);
const run = (c) => vm.runInContext(c, sb);
const M = run('M');
const ROWS = run('ROWS');

console.log('\nBase de ingresos de clientes (favorito inglb)');

check('el payload trae el campo de fecha de publicacion',
  M.pubdate_field === 'x_fecha_de_publicacion', M.pubdate_field);
check('el payload trae partner_type', M.partner_type_field === 'partner_type', M.partner_type_field);
check('las filas exponen pubdate/pubmonth',
  'pubdate' in ROWS[0] && 'pubmonth' in ROWS[0]);
check('las filas exponen isCustomer', 'isCustomer' in ROWS[0]);
check('existe el selector de base', !!els.fBase);
check('existe el selector de fecha', !!els.fDate);

const conCampo = ROWS.filter(r => r.pubdate).length;
check('la mayoria tiene fecha de publicacion', conCampo > ROWS.length * 0.8,
  conCampo + '/' + ROWS.length);
check('hay clientes identified', ROWS.filter(r => r.isCustomer).length > 0);

check('baseCustomer() activo por defecto al elegir Entradas',
  run('baseCustomer()') === true);
check('usePubDate() activo por defecto en el fixture', run('usePubDate()') === true);

console.log('\nPreset base segun tipo de pago');
// Salidas usa el dominio del favorito Gastoslb: partner_type = supplier.
check('Salidas obligan a la base de proveedores',
  run('baseForPtype("outbound")') === 'supplier');
check('Entradas obligan a la base de clientes',
  run('baseForPtype("inbound")') === 'customer');
check('Ambos se miden por flujo de pagos',
  run('baseForPtype("all")') === 'flow');
['outbound', 'inbound', 'all'].forEach(pt => {
  els.fPtype.value = pt;
  run('syncBaseWithPtype()');
  const esperado = pt === 'inbound' ? 'customer' : pt === 'outbound' ? 'supplier' : 'flow';
  check('al elegir "' + pt + '" la base queda en "' + esperado + '"',
    els.fBase.value === esperado, els.fBase.value);
});
// Volver al escenario de ingresos con el que arranca esta suite.
els.fPtype.value = 'inbound';
run('syncBaseWithPtype()');
check('tras el recorrido la base vuelve a clientes', els.fBase.value === 'customer');

console.log('\nClasificacion de conceptos');
const mkRow = (reason) => run(`({ reason: ${JSON.stringify(reason)}, isCustomer: true,
  partnerType: 'customer', internal: false, ptype: 'inbound', amount: 0, amountCo: 0 })`);
check('VENTAS es venta', run('isVenta') (mkRow('INGRESOS POR VENTAS')) === true);
check('ANTICIPO es anticipo', run('isAnticipo')(mkRow('ANTICIPO DE CLIENTE')) === true);
check('DESCUENTOSDFC es descuento',
  run('isDiscountReason')(mkRow('DESCUENTOSDFC')) === true);
check('PROMODESCUENTOS es descuento',
  run('isDiscountReason')(mkRow('PROMODESCUENTOS')) === true);
check('DEVOLUCIONES es descuento',
  run('isDiscountReason')(mkRow('DEVOLUCIONES')) === true);
check('ventas NO es descuento',
  run('isDiscountReason')(mkRow('INGRESOS POR VENTAS')) === false);
check('anticipos NO es descuento',
  run('isDiscountReason')(mkRow('ANTICIPO DE CLIENTE')) === false);
check('un descuento de proveedor no resta en base clientes',
  run('isDiscountOrReturn')({ reason: 'DESCUENTOSDFC', isCustomer: false }) === false);

console.log('\nRegla de signo: descuentos llegan positivos en Odoo');
const descPos = run('breakdown')([
  { reason: 'INGRESOS POR VENTAS', isCustomer: true, amountCo: 1000, amount: 1000, ptype: 'inbound' },
  { reason: 'ANTICIPO DE CLIENTE', isCustomer: true, amountCo: 500, amount: 500, ptype: 'inbound' },
  { reason: 'DESCUENTOSDFC', isCustomer: true, amountCo: 120, amount: 120, ptype: 'inbound' }
]);
check('ventas = 1000', near(descPos.ventas, 1000), descPos.ventas);
check('anticipos = 500', near(descPos.anticipos, 500), descPos.anticipos);
check('descuentos = 120 (positivo en origen)', near(descPos.desc, 120), descPos.desc);
check('total ingresos = ventas + anticipos = 1500', near(descPos.bruto, 1500), descPos.bruto);
check('total ingresos NO descuenta todavia', near(descPos.bruto, 1620) === false, descPos.bruto);
check('neto = total ingresos - descuentos = 1380',
  near(descPos.neto, 1380), descPos.neto);
check('neto NO resta dos veces', !near(descPos.neto, 1260), descPos.neto);

const descNeg = run('breakdown')([
  { reason: 'INGRESOS POR VENTAS', isCustomer: true, amountCo: 1000, amount: 1000, ptype: 'inbound' },
  { reason: 'DEVOLUCIONES', isCustomer: true, amountCo: -200, amount: -200, ptype: 'inbound' }
]);
check('una devolucion ya negativa en origen tambien resta 200',
  near(descNeg.desc, 200) && near(descNeg.neto, 800), descNeg.neto);
check('el total de ingresos ignora los descuentos',
  near(descNeg.bruto, 1000), descNeg.bruto);

console.log('\nFiltro por rango de fecha');
els.fFrom.value = '2026-10-01';
els.fTo.value = '2026-10-31';
run('render();');
const oct = run('breakdown(filtered())');
const octRows = run('filtered().length');
const octAll = ROWS.filter(r => r.isCustomer && r.state === 'posted' && r.pubmonth === '2026-10');
check('el rango de octubre acota los registros', octRows === octAll.length,
  octRows + ' vs ' + octAll.length);
check('los registros sin fecha de publicacion quedan fuera del rango',
  run('filtered().every(r => r.pubdate)') === true);

// Las cifras cambian cada vez que Odoo registra movimientos, asi que se
// comprueba el invariante y no un snapshot.
check('octubre: hay ventas', oct.ventas > 0, oct.ventas);
check('octubre: hay anticipos', oct.anticipos > 0, oct.anticipos);
check('octubre: hay descuentos', oct.desc > 0, oct.desc);
check('octubre: total ingresos = ventas + anticipos + otros',
  near(oct.bruto, oct.ventas + oct.anticipos + oct.otros),
  oct.bruto + ' vs ' + (oct.ventas + oct.anticipos + oct.otros));
check('octubre: el total de ingresos es mayor al neto por los descuentos',
  oct.bruto > oct.neto);
check('octubre: total ingresos - descuentos = ingreso neto',
  near(oct.neto, oct.bruto - oct.desc), oct.neto + ' vs ' + (oct.bruto - oct.desc));
check('octubre: el neto es mayor que las ventas por el efecto de los anticipos',
  oct.neto > oct.ventas);
check('octubre: los pagos contados coinciden con los del payload',
  octRows === octAll.length);

console.log('\nOctubre 2026 (cifras vivas, se reimprimen para revision)');
console.log('  ventas           = ' + money(oct.ventas));
console.log('  anticipos        = ' + money(oct.anticipos));
console.log('  TOTAL INGRESOS   = ' + money(oct.bruto));
console.log('  descuentos       = ' + money(oct.desc));
console.log('  ingreso neto     = ' + money(oct.neto));
console.log('  pagos            = ' + octRows);

console.log('\nKPI de ingresos');
const kpi = els.kpis.innerHTML;
check('muestra Ingresos por ventas', kpi.includes('Ingresos por ventas'));
check('muestra Anticipos de clientes', kpi.includes('Anticipos de clientes'));
check('muestra el total de ingresos', kpi.includes('Total ingresos'));
check('muestra Descuentos y devoluciones', kpi.includes('Descuentos y devoluciones'));
check('muestra Ingreso neto', kpi.includes('Ingreso neto'));
check('el total de ingresos aparece antes que el neto',
  kpi.indexOf('Total ingresos') < kpi.indexOf('Ingreso neto'));
check('explica que el descuento resta del total',
  kpi.includes('Total ingresos - descuentos'));

console.log('\nBase de flujo (payment_type) sigue disponible');
// "Ambos" es el tipo de pago que corresponde a la base de flujo.
els.fPtype.value = 'all';
run('syncBaseWithPtype()');
check('"Ambos" selecciona la base de flujo', run('baseCustomer()') === false);
run('render();');
const ambos = run('filtered()');
check('en base flujo no se filtran los pagos por isCustomer',
  ambos.some(r => !r.isCustomer), ambos.length + ' registros');
check('en base flujo conviven entradas y salidas',
  ambos.some(r => r.ptype === 'inbound') && ambos.some(r => r.ptype === 'outbound'));
const soloEgresos = ambos.filter(r => r.ptype === 'outbound');
check('las salidas nunca traen monto positivo (convencion contable)',
  soloEgresos.length > 0 &&
  soloEgresos.every(r => (r.amountCo || 0) <= 0), soloEgresos.length);
check('las entradas nunca traen monto negativo',
  ambos.filter(r => r.ptype === 'inbound').every(r => (r.amountCo || 0) >= 0));

// Volver a Entradas debe devolver el criterio de clientes.
els.fPtype.value = 'inbound';
run('syncBaseWithPtype()');
els.fDate.value = 'pub';
run('render();');
check('al volver a Entradas la base vuelve a clientes',
  run('baseCustomer()') === true);
check('al volver a clientes vuelve a acotar',
  run('filtered().every(r => r.isCustomer)') === true);

console.log('\n' + ok + ' OK / ' + fail + ' FALLA');
process.exit(fail ? 1 : 0);