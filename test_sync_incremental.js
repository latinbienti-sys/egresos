'use strict';
// Descarga incremental: el panel publicado sirve de base y Odoo solo recibe
// los pagos tocados desde la ultima corrida. Se prueba el mergue, el sello de
// watermark y el respaldo a descarga completa si el recuento no cuadra.
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SCRIPT = path.resolve(__dirname, 'gastos_razon_pagos.py');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'sync-'));
const basePath = path.join(tmp, 'base.html');

let ok = 0, fallas = [];
const check = (d, c) => { if (c) { ok++; } else { fallas.push(d); console.log('FALLA:', d); } };

function baseHtml(rows) {
  const payload = { meta: {
    model: 'account.payment', reason_field: 'x_razonpagos',
    measure: 'amount', measure_co: 'amount_co', date_field: 'date',
    state_field: 'state', ptype_field: 'payment_type',
    total_records: rows.length, loaded_records: rows.length,
    truncated: false, watermark: rows.map(r => r.wd).sort().pop(),
    currencies: {}, companies: [], company_currencies: [],
  }, rows };
  return '<html><head></head><body><script>\nconst DATA = '
    + JSON.stringify(payload).replace(/<\//g, '<\\/') + ';\n</script></body></html>';
}

const CFG = {
  reason_field: 'x_razonpagos',
  reason_meta: { type: 'selection', selection: [['VENTA', 'Ingresos por ventas']] },
  measure: 'amount', measure_co: 'amount_co', date_field: 'date',
  state_field: 'state', ptype_field: 'payment_type', partner_field: 'partner_id',
  name_field: 'name', company_field: 'company_id', currency_field: 'currency_id',
  co_currency_field: 'company_currency_id', pubdate_field: 'x_fecha_de_publicacion',
  partner_type_field: 'partner_type', internal_field: 'is_internal_transfer',
};

const VIEJAS = [
  { id: 1, doc: 'OP/1', date: '2026-08-05', month: '2026-08', partner: 'A',
    reason: 'Ingresos por ventas', amount: 100.0, amountCo: 100.0, cur: 'USD',
    curCo: 'USD', comp: 'C', state: 'posted', ptype: 'inbound',
    pubdate: '2026-08-05 10:00:00', pubmonth: '2026-08', partnerType: 'customer',
    internal: false, isCustomer: true, isSupplier: false, wd: '2026-08-05 10:00:00' },
  { id: 2, doc: 'OP/2', date: '2026-09-10', month: '2026-09', partner: 'B',
    reason: 'Ingresos por ventas', amount: 200.0, amountCo: 200.0, cur: 'USD',
    curCo: 'USD', comp: 'C', state: 'draft', ptype: 'inbound',
    pubdate: '2026-09-10 10:00:00', pubmonth: '2026-09', partnerType: 'customer',
    internal: false, isCustomer: true, isSupplier: false, wd: '2026-09-10 10:00:00' },
  { id: 3, doc: 'OP/3', date: '2026-10-01', month: '2026-10', partner: 'C',
    reason: 'Ingresos por ventas', amount: 300.0, amountCo: 300.0, cur: 'USD',
    curCo: 'USD', comp: 'C', state: 'posted', ptype: 'inbound',
    pubdate: '2026-10-01 10:00:00', pubmonth: '2026-10', partnerType: 'customer',
    internal: false, isCustomer: true, isSupplier: false, wd: '2026-10-01 10:00:00' },
];

// Dos cambios: el 4 es nuevo y el 3 fue corregido en Odoo.
function raw(i, wd, amount) {
  return {
    id: i, name: 'OP/' + i, date: '2026-10-0' + i, partner_id: [1, 'P' + i],
    currency_id: [1, 'USD'], company_id: [1, 'C'],
    amount: amount === undefined ? 100 * i : amount,
    amount_co: amount === undefined ? 100 * i : amount,
    state: 'posted', payment_type: 'inbound', x_razonpagos: 'VENTA',
    x_fecha_de_publicacion: '2026-10-0' + i + ' 10:00:00',
    partner_type: 'customer', is_internal_transfer: false, write_date: wd,
  };
}
const DELTA = [raw(3, '2026-10-06 11:00:00', 350), raw(4, '2026-10-06 09:00:00')];

function run(nombre, opts) {
  const py = `
import json, importlib.util, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
spec = importlib.util.spec_from_file_location('g', r'${SCRIPT}')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
cfg = json.loads(r'${JSON.stringify(CFG)}')
delta = json.loads(r'${JSON.stringify(DELTA)}')
m.SYNC = ${JSON.stringify(opts.sync || 'auto')}
m.BASE_HTML = ${JSON.stringify(opts.base || '')}
m.detect_fields = lambda: cfg
m.fetch_currencies = lambda names: {}
TOTAL = ${opts.total}
def fetch_rows(c, extra_domain=None):
    if extra_domain:
        dominios = list(extra_domain)
        assert len(dominios) == 1, 'dominio delta inesperado: %r' % (extra_domain,)
        campo, operador, valor = dominios[0]
        assert (campo, operador) == ('write_date', '>'), 'dominio delta: %r' % (dominios[0],)
        sel = [r for r in delta if r['write_date'] > valor]
        return sel, len(sel), []
    llenas = []
    for i in range(1, TOTAL + 1):
        base = next((r for r in delta if r['id'] == i), None)
        llenas.append(base if base else {'id': i, 'name': 'OP/' + str(i),
            'date': '2026-10-01', 'partner_id': [1, 'P'], 'currency_id': [1, 'USD'],
            'company_id': [1, 'C'], 'amount': 100 * i, 'amount_co': 100 * i,
            'state': 'posted', 'payment_type': 'inbound', 'x_razonpagos': 'VENTA',
            'x_fecha_de_publicacion': '2026-10-01 10:00:00', 'partner_type': 'customer',
            'is_internal_transfer': False, 'write_date': '2026-10-01 10:00:00'})
    return llenas, TOTAL, []
m.fetch_rows = fetch_rows
m.call_kw = lambda model, method, args=None, kwargs=None: TOTAL
p = m.build_payload()
print(json.dumps({
  'sync': p['meta']['sync'], 'changed': p['meta']['sync_changed'],
  'watermark': p['meta']['watermark'], 'total': p['meta']['total_records'],
  'loaded': p['meta']['loaded_records'], 'truncated': p['meta']['truncated'],
  'ids': [r['id'] for r in p['rows']],
  'montos': {str(r['id']): r['amount'] for r in p['rows']},
}))
`;
  const out = execFileSync('python', ['-c', py], { stdio: ['pipe', 'pipe', 'pipe'] }).toString();
  return JSON.parse(out.trim().split('\n').pop());
}

// ---- 1. base previa + delta -> mergue -------------------------------------
fs.writeFileSync(basePath, baseHtml(VIEJAS), 'utf8');
let r = run('mergue', { base: basePath, total: 4 });
check('modo incremental', r.sync === 'incremental');
check('solo baja el delta a Odoo (2 filas)', r.changed === 2);
check('suma la fila nueva', r.ids.length === 4 && r.ids.includes(4));
check('fila nueva reemplaza a la vieja por id', new Set(r.ids).size === 4);
check('la correccion de Odoo se refleja', r.montos['3'] === 350.0);
check('las filas viejas no se tocan', r.montos['1'] === 100.0 && r.montos['2'] === 200.0);
check('orden por id descendente', r.ids[0] === 4);
check('total de Odoo en meta', r.total === 4 && r.loaded === 4);
check('no queda truncado', r.truncated === false);
check('watermark avanza al max write_date', r.watermark === '2026-10-06 11:00:00');

// ---- 2. recuento que no cuadra -> descarga completa ------------------------
r = run('recuento', { base: basePath, total: 5 });
check('si el recuento no cuadra vuelve a completa', r.sync === 'completa');
check('en la corrida completa se piden las 5', r.loaded === 5);

// ---- 3. sin base utilizable -> descarga completa ---------------------------
r = run('sin base', { base: path.join(tmp, 'no-existe.html'), total: 4 });
check('sin base previa se hace completa', r.sync === 'completa');
check('sin base se piden todas las filas', r.loaded === 4);

// ---- 4. SYNC=full ignora la base aunque exista -----------------------------
r = run('modo full', { base: basePath, total: 4, sync: 'full' });
check('GASTOS_SYNC=full ignora la base', r.sync === 'completa');

// ---- 5. una base truncada no sirve para mergear ---------------------------
fs.writeFileSync(basePath,
  baseHtml(VIEJAS).replace('"truncated":false', '"truncated":true'), 'utf8');
r = run('base truncada', { base: basePath, total: 4 });
check('base truncada obliga a completa', r.sync === 'completa');

// ---- 6. carga del panel publicado -----------------------------------------
fs.writeFileSync(basePath, baseHtml(VIEJAS), 'utf8');
const py2 = `
import json, importlib.util, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
spec = importlib.util.spec_from_file_location('g', r'${SCRIPT}')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.BASE_HTML = ${JSON.stringify(basePath)}
d = m.load_previous()
print(json.dumps({'rows': len(d['rows']), 'wm': d['meta']['watermark']}))
`;
const prev = JSON.parse(execFileSync('python', ['-c', py2]).toString().trim());
check('lee las filas del panel publicado', prev.rows === 3);
check('lee el watermark del panel publicado', prev.wm === '2026-10-01 10:00:00');

fs.rmSync(tmp, { recursive: true, force: true });
console.log(`${ok} OK / ${fallas.length} FALLA`);
process.exit(fallas.length ? 1 : 0);
