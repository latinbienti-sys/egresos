# -*- coding: utf-8 -*-
"""
DASHBOARD DE GASTOS POR RAZON DE PAGOS - SOLO LECTURA / CONSULTA.

Genera gastos_razon_pagos.html: panel interactivo que responde
"¿En que se gasto el dinero?" agrupando por la Clasificacion / Concepto
de gasto (campo x_razonpagos) en lugar de por la jerarquia Ano > Mes > Dia.

NO MODIFICA NADA EN ODOO. Unicamente llamadas de lectura:
  fields_get, search_read, read
No crea, no edita, no borra registros. No instala modulos ni vistas.

Uso (PowerShell):
  $env:ODOO_BASE="https://tu-odoo.com"
  $env:ODOO_DB="basededatos"
  $env:ODOO_USER="usuario"
  $env:ODOO_PASSWORD="clave"
  python gastos_razon_pagos.py

Ajustes opcionales por variable de entorno:
  GASTOS_MODEL         default account.payment
  GASTOS_REASON_FIELD  default x_razonpagos
  GASTOS_LIMIT         default 20000 (topes de registros a traer)
  GASTOS_SYNC          auto|full. "auto" hace descarga incremental cuando hay
                       un panel previo: Odoo solo recibe la consulta de los
                       pagos que cambiaron desde la ultima corrida.
  GASTOS_BASE_HTML     ruta del panel previo que se usa como base incremental.
"""
import json
import os
import sys
import time
import urllib.request
import http.client
import http.cookiejar
from datetime import datetime

BASE = os.environ.get("ODOO_BASE", "")
DB = os.environ.get("ODOO_DB", "")
USER = os.environ.get("ODOO_USER", "")
PWD = os.environ.get("ODOO_PASSWORD", "")

MODEL = os.environ.get("GASTOS_MODEL", "account.payment")
REASON_FIELD = os.environ.get("GASTOS_REASON_FIELD", "x_razonpagos")
LIMIT = int(os.environ.get("GASTOS_LIMIT", "20000"))

MEASURE_CANDIDATES = ["amount", "amount_total", "debit", "balance"]
# Medida en MONEDA DE COMPANIA. En salidas viene negativa por convencion contable.
CO_CANDIDATES = ["amount_company_currency_signed", "amount_total_signed", "amount_signed"]
DATE_CANDIDATES = ["payment_date", "date", "invoice_date"]
# Fecha usada por el favorito "inglb" de Pagos para agrupar ingresos de clientes.
PUB_DATE_FIELD = os.environ.get("GASTOS_PUBDATE_FIELD", "x_fecha_de_publicacion")
SIN_CLASIFICAR = "(Sin clasificar)"
# Reintentos ante cortes de conexion en la descarga del dataset.
RPC_INTENTOS = int(os.environ.get("GASTOS_RPC_INTENTOS", "5"))
# Registros por peticion: respuesta acotada para que no se corte la descarga.
PAGE_SIZE = int(os.environ.get("GASTOS_PAGE_SIZE", "4000"))
# "auto": solo se consulta a Odoo lo que cambio desde la ultima corrida.
SYNC = os.environ.get("GASTOS_SYNC", "auto").lower()
# Panel publicado que se usa como base de la descarga incremental.
BASE_HTML = os.environ.get("GASTOS_BASE_HTML", "")

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def rpc(url, method, params):
    payload = {"jsonrpc": "2.0", "method": "call", "params": params, "id": 1}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    # La lectura completa del dataset son varios MB: una conexion que se corta
    # a mitad no debe tumbar toda la generacion, se reintenta con espera.
    ultimo = None
    for intento in range(RPC_INTENTOS):
        try:
            resp = opener.open(req, timeout=120)
            crudo = resp.read()
            return json.loads(crudo.decode())
        except (http.client.IncompleteRead, http.client.HTTPException, ConnectionError,
                TimeoutError, OSError) as exc:
            ultimo = exc
            print("  aviso: la llamada %s se corto (%s). Reintento %d/%d"
                  % (method, type(exc).__name__, intento + 1, RPC_INTENTOS),
                  file=sys.stderr)
            time.sleep(2 * (intento + 1))
    raise RuntimeError("Fallo la llamada %s tras %d intentos: %s"
                       % (method, RPC_INTENTOS, ultimo))


def call_kw(model, method, args=None, kwargs=None):
    if args is None:
        args = []
    if kwargs is None:
        kwargs = {}
    res = rpc(
        BASE + "/web/dataset/call_kw",
        model,
        {"model": model, "method": method, "args": args, "kwargs": kwargs},
    )
    if "error" in res:
        raise RuntimeError(json.dumps(res["error"], ensure_ascii=False)[:2000])
    return res["result"]


def pick(fields_get, candidates):
    for c in candidates:
        if c in fields_get:
            return c
    return False


def detect_fields():
    """Descubre los campos reales sin asumir nada. Solo lectura."""
    attrs = ["string", "type", "relation", "selection", "store", "currency_field"]
    fg = call_kw(MODEL, "fields_get", [], {"attributes": attrs})

    if REASON_FIELD not in fg:
        disponibles = sorted([k for k in fg if k.startswith("x_")])
        raise SystemExit(
            "ERROR: el campo '%s' no existe en %s.\n"
            "Campos x__ disponibles: %s\n"
            "Define GASTOS_REASON_FIELD con el nombre correcto."
            % (REASON_FIELD, MODEL, ", ".join(disponibles) or "(ninguno)")
        )

    return {
        "reason_field": REASON_FIELD,
        "reason_meta": fg[REASON_FIELD],
        "measure": pick(fg, MEASURE_CANDIDATES),
        "measure_co": pick(fg, CO_CANDIDATES),
        "date_field": pick(fg, DATE_CANDIDATES),
        "state_field": "state" if "state" in fg else False,
        "ptype_field": "payment_type" if "payment_type" in fg else False,
        "partner_field": "partner_id" if "partner_id" in fg else False,
        "name_field": "name" if "name" in fg else False,
        "company_field": "company_id" if "company_id" in fg else False,
        "currency_field": "currency_id" if "currency_id" in fg else False,
        "co_currency_field": "company_currency_id" if "company_currency_id" in fg else False,
        # Base de "pagos de clientes" (favorito inglb): se basa en el tipo de
        # partner y en una fecha de publicacion propia, no en payment_type/date.
        "pubdate_field": PUB_DATE_FIELD if PUB_DATE_FIELD in fg else False,
        "partner_type_field": "partner_type" if "partner_type" in fg else False,
        "internal_field": "is_internal_transfer" if "is_internal_transfer" in fg else False,
    }


def selection_map(meta):
    out = {}
    for item in (meta.get("selection") or []):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out[item[0]] = item[1]
        else:
            out[item] = str(item)
    return out


def fetch_separators():
    """Los separadores decimales no estan en res.currency, estan en res.lang."""
    lang_code = "es_VE"
    try:
        me = call_kw("res.users", "search_read", [[("id", "=", 1)]], {"fields": ["lang"]})
        if me and me[0].get("lang"):
            lang_code = me[0]["lang"]
    except Exception:
        pass
    try:
        rows = call_kw("res.lang", "search_read", [[("code", "in", [lang_code, "es_VE", "en_US"])]],
                       {"fields": ["name", "code", "decimal_separator", "thousands_sep"],
                        "limit": 10})
        for pref in (lang_code, "es_VE", "en_US"):
            for r in rows:
                if r.get("code") == pref:
                    return (r.get("decimal_separator") or ".",
                            r.get("thousands_sep") or ",")
    except Exception:
        pass
    return ".", ","


def fetch_currencies(names):
    """Simbolo y posicion de cada moneda usada, tal como los define Odoo."""
    if not names:
        return {}
    dec, thou = fetch_separators()
    recs = call_kw("res.currency", "search_read", [[("name", "in", list(names))]],
                   {"fields": ["name", "symbol", "position"], "limit": 50})
    out = {}
    for c in recs:
        out[c["name"]] = {
            "name": c["name"],
            "symbol": c.get("symbol") or c["name"],
            "position": c.get("position") or "after",
            "decimal_separator": dec,
            "thousands_sep": thou,
        }
    return out


def fetch_rows(cfg, extra_domain=None):
    fields = ["id", "write_date"]
    for key in ("measure", "measure_co", "date_field", "state_field", "ptype_field",
                "partner_field", "name_field", "company_field", "currency_field",
                "co_currency_field", "pubdate_field", "partner_type_field",
                "internal_field"):
        if cfg.get(key):
            fields.append(cfg[key])
    fields.append(cfg["reason_field"])
    fields = sorted(set(fields))

    base_domain = list(extra_domain or [])
    total = call_kw(MODEL, "search_count", [base_domain])
    # Paginacion por cursor sobre id. Con offset, los pagos que Odoo registra
    # durante la descarga desplazan las paginas y repiten filas; con "id < cursor"
    # el corte queda fijo. Se pide de mas nuevo a mas viejo para que un limite
    # se lleve los movimientos recientes.
    filas = []
    cursor = None
    objetivo = min(LIMIT, total or LIMIT)
    while len(filas) < objetivo:
        salto = min(PAGE_SIZE, objetivo - len(filas))
        # search_read recibe el dominio como primer argumento posicional.
        if cursor is None:
            args = [base_domain]
        else:
            args = [base_domain + [["id", "<", cursor]]]
        lote = call_kw(
            MODEL, "search_read", args,
            {"fields": fields, "limit": salto, "order": "id desc"},
        )
        if not lote:
            break
        filas.extend(lote)
        cursor = lote[-1]["id"]
        print("  descargados: %d" % len(filas), file=sys.stderr)
    rows = filas[:LIMIT] if LIMIT else filas
    # Red de seguridad: publicar un total inflado por filas repetidas seria
    # peor que avisar, asi que se corta la generacion si ocurre.
    vistos = set()
    repetidos = 0
    for r in rows:
        rid = r.get("id")
        if rid in vistos:
            repetidos += 1
        vistos.add(rid)
    if repetidos:
        raise RuntimeError(
            "La descarga devolvio %d registro(s) repetido(s). No se publica un "
            "total inflado; revisa la paginacion." % repetidos
        )
    return rows, total, fields


def resolve_reason_labels(cfg, raw_values):
    """Convierte el valor crudo de x_razonpagos a texto legible."""
    meta = cfg["reason_meta"]
    rtype = meta.get("type")
    uniq = {v for v in raw_values if v not in (None, False, "")}
    if rtype == "selection":
        smap = selection_map(meta)
        return {v: smap.get(v, str(v)) for v in uniq}
    if rtype == "many2one":
        ids = sorted({int(v) for v in uniq})
        if not ids:
            return {}
        try:
            recs = call_kw(meta.get("relation"), "read", [ids, ["display_name"]])
            return {r["id"]: r["display_name"] for r in recs}
        except Exception:
            return {}
    return {v: str(v) for v in uniq}


def load_previous():
    """Lee el panel ya publicado para reutilizar sus filas sin bajarlas de Odoo."""
    path = BASE_HTML or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "gastos_razon_pagos.html")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = f.read()
    except OSError:
        return None
    marker = "const DATA = "
    i = doc.find(marker)
    if i < 0:
        return None
    i += len(marker)
    j = doc.find("\n", i)
    if j < 0:
        return None
    blob = doc[i:j].strip()
    if blob.endswith(";"):
        blob = blob[:-1]
    try:
        data = json.loads(blob)
    except ValueError:
        return None
    if not isinstance(data, dict) or not data.get("rows"):
        return None
    meta = data.get("meta") or {}
    # Con un panel truncado o de otro esquema no se puede mergear con criterio.
    if meta.get("truncated") or meta.get("model") != MODEL:
        return None
    return {"meta": meta, "rows": data["rows"]}


def transform_rows(raw, cfg, reason_labels):
    """Filas crudas de Odoo al formato del panel (una sola transformacion)."""
    def rel(v):
        return v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else ""

    out = []
    for r in raw:
        val = r.get(cfg["reason_field"])
        # False / None / "" significa que el pago no tiene razon asignada.
        label = reason_labels.get(val, str(val)) if val else SIN_CLASIFICAR
        pid = r.get("partner_id")
        partner = pid[1] if isinstance(pid, (list, tuple)) and len(pid) > 1 else "(Sin proveedor)"
        dval = r.get(cfg["date_field"]) if cfg.get("date_field") else None
        dstr = str(dval) if dval else ""
        pval = r.get(cfg["pubdate_field"]) if cfg.get("pubdate_field") else None
        pstr = str(pval) if pval else ""
        # Base clientes: partner_type = customer y no es transferencia interna.
        ptype_partner = (r.get(cfg["partner_type_field"])
                         if cfg.get("partner_type_field") else "") or ""
        internal = bool(r.get(cfg["internal_field"])) if cfg.get("internal_field") else False
        is_customer = (ptype_partner == "customer") and not internal
        # Base proveedores: dominio del favorito "Gastoslb" de Proveedores/Pagos.
        is_supplier = (ptype_partner == "supplier") and not internal
        cur = rel(r.get("currency_id")) or "(vacia)"
        co = rel(r.get("company_id")) or "(vacia)"
        out.append({
            "id": r.get("id"),
            "doc": r.get("name") or ("#" + str(r.get("id"))),
            "date": dstr,
            "month": dstr[:7],
            "partner": partner,
            "reason": label,
            "amount": float(r.get(cfg["measure"]) or 0.0),
            "amountCo": float(r.get(cfg["measure_co"]) or 0.0) if cfg["measure_co"] else None,
            "cur": cur,
            "curCo": cur,
            "comp": co,
            "state": r.get(cfg["state_field"]) if cfg.get("state_field") else "",
            "ptype": r.get(cfg["ptype_field"]) if cfg.get("ptype_field") else "",
            # --- base de ingresos de clientes (favorito inglb) ---
            "pubdate": pstr,
            "pubmonth": pstr[:7],
            "partnerType": ptype_partner,
            "internal": internal,
            "isCustomer": is_customer,
            "isSupplier": is_supplier,
            # Sello de modificacion: marca desde donde sigue la proxima corrida.
            "wd": r.get("write_date") or "",
        })

    # La moneda de compania se deduce de los campos *_signed: si el pago esta en
    # VEF pero la compania es USD, la medida "co" viene en USD.
    for row, r in zip(out, raw):
        m = r.get(cfg["measure"]) or 0.0
        mc = r.get(cfg["measure_co"]) if cfg["measure_co"] else None
        if mc:
            row["curCo"] = row["cur"] if abs(mc - m) < 0.01 else _guess_company_currency(r)
    return out


def build_payload():
    cfg = detect_fields()
    print("Modelo:", MODEL)
    print("  Razon    :", cfg["reason_field"], "(%s)" % cfg["reason_meta"].get("type"))
    print("  Moneda pago      :", cfg["measure"])
    print("  Moneda compania  :", cfg["measure_co"] or "(no disponible)")
    print("  Fecha   :", cfg["date_field"])
    print("  Estado  :", cfg["state_field"] or "(sin estado)")
    print("  Tipo    :", cfg["ptype_field"] or "(sin tipo de pago)")

    total = call_kw(MODEL, "search_count", [[]])
    prev = load_previous() if SYNC == "auto" else None
    watermark = ((prev or {}).get("meta") or {}).get("watermark") or ""
    prev_rows = (prev or {}).get("rows") or []
    modo, out, tramo = "completa", [], None

    if prev and watermark and prev_rows:
        # Descarga incremental: Odoo solo recibe los pagos tocados desde la
        # ultima corrida. Todo lo demas se reutiliza tal cual del panel previo.
        delta_raw, _, _ = fetch_rows(cfg, [("write_date", ">", watermark)])
        delta_out = transform_rows(
            delta_raw, cfg,
            resolve_reason_labels(cfg, [r.get(cfg["reason_field"]) for r in delta_raw]))
        merged = {r["id"]: r for r in prev_rows}
        for row in delta_out:
            merged[row["id"]] = row
        rows = sorted(merged.values(), key=lambda r: r["id"] or 0, reverse=True)
        # Odoo puede borrar pagos y write_date no lo cuenta: si el recuento no
        # cuadra se descarta el truco y se baja todo, para no publicar fantasmas.
        if len(rows) == total:
            modo, out, tramo = "incremental", rows, delta_out
            print("Base previa: %d filas | nuevas o modificadas: %d"
                  % (len(prev_rows), len(delta_out)))
        else:
            print("  AVISO: el recuento no cuadra (%d en el panel, %d en Odoo)."
                  " Se ignora la base previa y se descarga todo." % (len(rows), total))
    else:
        print("  AVISO: sin base previa utilizable; se hace descarga completa.")

    if modo == "completa":
        raw, _, fields = fetch_rows(cfg)
        out = transform_rows(
            raw, cfg,
            resolve_reason_labels(cfg, [r.get(cfg["reason_field"]) for r in raw]))
        print("Registros encontrados:", total, "| descargados:", len(raw),
              "(limite %d)" % LIMIT)
        if total > len(raw):
            print("  AVISO: se descargaron solo %d de %d. Sube GASTOS_LIMIT."
                  % (len(raw), total))

    for row in out:
        if not row.get("curCo"):
            row["curCo"] = row["cur"]
    cur_names = {r["cur"] for r in out}
    co_names = {r["curCo"] for r in out}
    companies = {r["comp"] for r in out}
    currencies = fetch_currencies(cur_names | co_names)
    for code in (cur_names | co_names) - set(currencies):
        currencies[code] = {"name": code, "symbol": code, "position": "after",
                            "decimal_separator": ".", "thousands_sep": ","}

    # El sello avanza solo: una fila vieja conserva su write_date original.
    sellados = [r.get("wd") for r in out if r.get("wd")]
    watermark = max([watermark] + sellados) if sellados else watermark

    return {
        "meta": {
            "model": MODEL,
            "reason_field": cfg["reason_field"],
            "reason_label": cfg["reason_meta"].get("string") or cfg["reason_field"],
            "reason_type": cfg["reason_meta"].get("type"),
            "measure": cfg["measure"],
            "measure_label": "Monto del pago",
            "measure_co": cfg["measure_co"],
            "measure_co_label": "Monto en moneda de compania",
            "date_field": cfg["date_field"],
            "pubdate_field": cfg["pubdate_field"] or "",
            "partner_type_field": cfg["partner_type_field"] or "",
            "internal_field": cfg["internal_field"] or "",
            "state_field": cfg["state_field"],
            "ptype_field": cfg["ptype_field"],
            "total_records": total,
            "loaded_records": len(out),
            "truncated": total > len(out),
            "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "sync": modo,
            "sync_changed": len(tramo or []),
            "watermark": watermark,
            "currencies": currencies,
            "companies": sorted(companies),
            "company_currencies": sorted(co_names),
        },
        "rows": out,
    }


def _guess_company_currency(payment_rec):
    """Moneda de compania declarada en el propio pago."""
    v = payment_rec.get("company_currency_id")
    if isinstance(v, (list, tuple)) and len(v) > 1:
        return v[1]
    return v or ""


HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Gastos por Razon de Pago</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         background:#eef1f6; color:#1a1a1a; }
  .topbar { background:linear-gradient(135deg,#213C83,#15295e); color:#fff; padding:18px 24px; }
  .topbar h1 { margin:0; font-size:22px; }
  .topbar p { margin:4px 0 0; color:#cbd5e8; font-size:13px; }
  .wrap { max-width:1420px; margin:20px auto; padding:0 18px; }
  .filters { background:#fff; border-radius:12px; padding:14px 16px; margin-bottom:18px;
             box-shadow:0 2px 10px rgba(0,0,0,.06);
             display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end; }
  .f { display:flex; flex-direction:column; gap:4px; }
  .f label { font-size:10px; text-transform:uppercase; letter-spacing:.5px; color:#8892a8; font-weight:700; }
  .f select, .f input { padding:8px 10px; border:1px solid #ccd2e0; border-radius:8px;
                        font-size:13.5px; font-family:inherit; background:#fff; }
  .chk { display:flex; align-items:center; gap:6px; font-size:12.5px; font-weight:600;
         color:#213C83; padding:8px 4px; cursor:pointer; }
  .chk input { width:15px; height:15px; accent-color:#213C83; }
  .note { width:100%; font-size:11.5px; color:#8892a8; margin-top:2px; }
  .note b { color:#b45309; }
  .tag { display:inline-block; background:#eef1f8; color:#213C83; border-radius:4px;
         padding:1px 7px; font-size:11px; font-weight:700; margin-left:6px; }
  .quick { display:flex; gap:6px; margin-left:auto; }
  .tools { display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end; margin-bottom:12px; }
  .btn { border:none; background:#eef1f8; color:#213C83; border-radius:8px; padding:8px 13px;
         font-weight:700; font-size:12.5px; cursor:pointer; font-family:inherit; }
  .btn:hover { background:#213C83; color:#fff; }
  .btn.p { background:#213C83; color:#fff; }
  .btn.p:hover { background:#15295e; }
  .chips { display:flex; flex-wrap:wrap; gap:7px; margin-top:12px;
           padding-top:12px; border-top:1px solid #eef1f8; }
  .chip { border:2px solid #d7deee; background:#fff; color:#213C83; border-radius:30px;
          padding:6px 14px; font-weight:700; font-size:12.5px; cursor:pointer; }
  .chip.active { background:#213C83; color:#fff; border-color:#213C83; }
  .kpis { display:flex; gap:14px; flex-wrap:wrap; margin-bottom:20px; }
  .kpi { flex:1; min-width:158px; background:#fff; border-radius:12px; padding:16px 18px;
         box-shadow:0 2px 10px rgba(0,0,0,.06); }
  .kpi b { font-size:25px; display:block; letter-spacing:-.5px; }
  .kpi span { color:#666; font-size:12.5px; }
  .kpi small { color:#999; font-size:11px; display:block; margin-top:4px; }
  .grid { display:grid; grid-template-columns: 4fr 7fr; gap:18px; align-items:start; }
  @media (max-width:1050px) { .grid { grid-template-columns:1fr; } }
  .card { background:#fff; border-radius:12px; padding:16px 18px;
          box-shadow:0 3px 12px rgba(0,0,0,.06); }
  .card h3 { margin:0 0 4px; font-size:15px; color:#213C83; }
  .hint { color:#8892a8; font-size:11.5px; margin:0 0 10px; }
  .chart-box { position:relative; height:330px; }
  .tw { max-height:560px; overflow-y:auto; }
  .alerta { color:#a4262c; }
  table .r { text-align:right; font-variant-numeric:tabular-nums; }
  table tr.sub td { background:#f6f8fc; border-top:2px solid #d7deee; }
  table tr.tot td { background:#213C83; color:#fff; font-weight:700; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { background:#f0f3fa; text-align:left; padding:9px 10px; font-size:11px;
       text-transform:uppercase; letter-spacing:.4px; color:#213C83;
       position:sticky; top:0; z-index:2; }
  td { padding:7px 10px; border-bottom:1px solid #eef1f8; }
  tr:hover td { background:#fafcff; }
  .num { text-align:right; white-space:nowrap; }
  .tgl { width:18px; height:18px; border:1px solid #ccd2e0; border-radius:4px; background:#fff;
         cursor:pointer; font-size:12px; line-height:1; color:#213C83; padding:0;
         transition:transform .12s; }
  .tgl.open { transform:rotate(90deg); }
  .leaf { width:18px; display:inline-block; text-align:center; color:#ccd2e0; }
  .lvl { font-size:9px; text-transform:uppercase; letter-spacing:.4px; color:#8892a8;
         background:#f0f3fa; padding:1px 6px; border-radius:3px; margin-right:6px; }
  .lbl { display:flex; align-items:center; }
  .bar { height:4px; background:#eef1f8; border-radius:2px; margin-top:4px; overflow:hidden;
         min-width:70px; }
  .bar i { display:block; height:100%; background:#213C83; border-radius:2px; }
  .tot td { font-weight:700; background:#f0f3fa; border-top:2px solid #d7deee; }
  .empty { padding:26px; text-align:center; color:#999; }
  .warn { background:#fef3c7; border:1px solid #fde68a; color:#92400e; padding:10px 14px;
          border-radius:10px; font-size:12.5px; margin-bottom:16px; }
  .foot { text-align:center; color:#8892a8; font-size:12px; padding:22px; }
  code { background:#eef1f8; padding:1px 5px; border-radius:3px; font-size:11px; }
</style>
</head>
<body>
<div class="topbar">
  <h1>&#129181; ¿En qué se gastó el dinero?</h1>
  <p id="sub"></p>
</div>

<div class="wrap">
  <div id="warn"></div>

  <div class="filters">
    <div class="f"><label>Desde</label><input type="date" id="fFrom"></div>
    <div class="f"><label>Hasta</label><input type="date" id="fTo"></div>
    <div class="f"><label>Estado</label>
      <select id="fState">
        <option value="posted">Publicado</option>
        <option value="draft">Borrador</option>
        <option value="all">Todos</option>
      </select>
    </div>
    <div class="f" id="wrapPtype"><label>Tipo de pago</label>
      <select id="fPtype">
        <option value="outbound">Salidas (egresos)</option>
        <option value="inbound">Entradas (ingresos)</option>
        <option value="all">Ambos</option>
      </select>
    </div>
    <div class="f"><label>Base</label>
      <select id="fBase">
        <option value="customer">Clientes (favorito inglb)</option>
        <option value="supplier">Proveedores (favorito Gastoslb)</option>
        <option value="flow">Flujo de pagos (payment_type)</option>
      </select>
    </div>
    <div class="f"><label>Usar fecha</label>
      <select id="fDate">
        <option value="pub">Fecha de publicacion</option>
        <option value="pay">Fecha del pago</option>
      </select>
    </div>
    <div class="f"><label>Medir en</label>
      <select id="fMeasure">
        <option value="co">Moneda de compania (USD)</option>
        <option value="tx">Moneda del pago</option>
      </select>
    </div>
    <div class="f" id="wrapCur"><label>Moneda del pago</label>
      <select id="fCur"></select>
    </div>
    <div class="f"><label>Compania</label>
      <select id="fComp"><option value="">Todas</option></select>
    </div>
    <label class="chk" title="En salidas, la contabilidad registra el monto de compania con signo negativo">
      <input type="checkbox" id="fNeg"> Mostrar signo contable (negativo)
    </label>
    <label class="chk" id="wrapNoDate"
      title="Hay pagos sin fecha de publicacion. Esta opcion los conserva aunque se filtre por rango.">
      <input type="checkbox" id="fNoDate" checked> Incluir pagos sin fecha
    </label>
    <div class="quick">
      <button class="btn" onclick="setPreset('today')">Hoy</button>
      <button class="btn" onclick="setPreset('month')">Este mes</button>
      <button class="btn" onclick="setPreset('year')">Este año</button>
      <button class="btn" onclick="setPreset('all')">Todo</button>
      <button class="btn p" onclick="exportCsv()">Exportar CSV</button>
      <button class="btn p" onclick="reporteDia()"
        title="Resumen del dia en PDF: ingresos, anticipos, egresos y pagos publicados">Reporte del día (PDF)</button>
    </div>
    <div class="note" id="note"></div>
    <div class="chips" id="chips"></div>
  </div>

  <div class="kpis" id="kpis"></div>

  <div class="card" style="margin-bottom:20px">
    <h3>Historico por razon de pago</h3>
    <p class="hint" id="histHint"></p>
    <div class="tools">
      <div class="f"><label>Razones con serie propia</label>
        <select id="fTop">
          <option value="8">8 mas altas</option>
          <option value="12">12 mas altas</option>
          <option value="20">20 mas altas</option>
          <option value="0">Todas</option>
        </select>
      </div>
      <div class="quick">
        <button class="btn" onclick="clearReason()">Quitar filtro de razon</button>
      </div>
    </div>
    <div class="chart-box" style="height:400px"><canvas id="hist"></canvas></div>
  </div>

  <div class="card" style="margin-bottom:20px">
    <h3 id="hAno">Cierre por ano y mes</h3>
    <p class="hint" id="anoHint"></p>
    <div class="tw"><table id="tbAno"></table></div>
  </div>

  <div class="grid">
    <div class="card">
      <h3 id="hDonut">Distribucion</h3>
      <p class="hint">Clic en una porcion para filtrar la tabla.</p>
      <div class="chart-box"><canvas id="donut"></canvas></div>
    </div>
    <div class="card">
      <h3>Detalle y desglose</h3>
      <p class="hint">Expande una categoria para ver proveedores y documentos.</p>
      <div class="tw">
        <table>
          <thead>
            <tr>
              <th>Concepto</th>
              <th class="num">Monto</th>
              <th>Tipo</th>
              <th class="num">%</th>
              <th class="num">Cant.</th>
            </tr>
          </thead>
          <tbody id="tb"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<div class="foot">
  Datos obtenidos via JSON-RPC en modo <strong>solo lectura</strong>.
  No se creo, modifico ni elimino ningun registro en Odoo.
</div>

<script>
const DATA = __DATA__;
const M = DATA.meta;
const ROWS = DATA.rows;
let expanded = {};
let childCache = {};
let activeReason = null;
let chart = null;

document.getElementById('sub').textContent =
  M.model + ' · agrupado por ' + M.reason_label + ' (' + M.reason_field + ') · ' +
  M.loaded_records + ' registros · ' + M.companies.length + ' companias · generado ' + M.generated;
document.getElementById('hDonut').textContent = 'Distribucion por ' + M.reason_label;

if (M.truncated) {
  document.getElementById('warn').innerHTML =
    '<b>Atencion:</b> Odoo tiene <b>' + M.total_records + '</b> registros y solo se trajeron <b>' +
    M.loaded_records + '</b>. Los totales pueden estar incompletos. Sube la variable GASTOS_LIMIT.';
}
if (!M.ptype_field) {
  document.getElementById('wrapPtype').style.display = 'none';
}
if (!M.measure_co) {
  const o = document.getElementById('fMeasure').querySelector('option[value="co"]');
  if (o) o.disabled = true;
  document.getElementById('fMeasure').value = 'tx';
}

// Monedas del pago, con la mas frecuente por defecto
const curCount = {};
ROWS.forEach(r => { curCount[r.cur] = (curCount[r.cur] || 0) + 1; });
const curKeys = Object.keys(curCount).sort((a, b) => curCount[b] - curCount[a]);
const selCur = document.getElementById('fCur');
curKeys.forEach(c => {
  const op = document.createElement('option');
  op.value = c; op.textContent = c + ' (' + curCount[c] + ')';
  selCur.appendChild(op);
});

const selComp = document.getElementById('fComp');
M.companies.forEach(c => {
  const op = document.createElement('option');
  op.value = c; op.textContent = c;
  selComp.appendChild(op);
});

function syncMeasureUI() {
  document.getElementById('wrapCur').style.display = isCo() ? 'none' : '';
  const ck = curKey();
  document.getElementById('note').innerHTML = isCo()
    ? 'Midiendo en <b>moneda de compania</b> (' + ck + '), comparable entre companias. ' +
      'En pagos de salida Odoo guarda este monto en <b>negativo</b>; desmarca la casilla para verlo como gasto positivo.'
    : 'Midiendo en la <b>moneda del pago</b> (' + ck + '). Solo se comparan pagos de la misma moneda.';
}

function toggleMeasure() {
  syncMeasureUI();
  rerender();
}

// ---- Moneda y medida ---------------------------------------------------
// La base tiene varias companias con distintas monedas (VEF y USD), asi que
// sumar "amount" sin mas mezclaarsetas currencies. Por defecto se mide en
// MONEDA DE COMPANIA, que es comparable entre companias.
function curDef(code) {
  return M.currencies[code] ||
    { name: code || '?', symbol: code || '?', position: 'after',
      decimal_separator: '.', thousands_sep: ',' };
}

function fmt(v, code) {
  const c = curDef(code);
  const n = Number(v) || 0;
  const neg = n < 0;
  const parts = Math.abs(n).toFixed(2).split('.');
  const miles = c.thousands_sep || ',';
  const dec = c.decimal_separator || '.';
  const int = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, miles);
  const txt = int + (parts[1] ? dec + parts[1] : '');
  const body = c.position === 'before' ? c.symbol + ' ' + txt : txt + ' ' + c.symbol;
  return (neg ? '-' : '') + body;
}

function isCo() { return document.getElementById('fMeasure').value === 'co'; }

// Base de seleccion: clientes (favorito inglb de Pagos), proveedores
// (favorito Gastoslb de Proveedores/Pagos) o flujo de pagos.
// El tipo de pago manda: cada favorito esta anclado a un partner_type, asi que
// el preset evita rotular los egresos con el criterio de los ingresos.
function baseVal() { return document.getElementById('fBase').value; }
function baseCustomer() { return baseVal() === 'customer'; }
function baseSupplier() { return baseVal() === 'supplier'; }
function ptypeEl() { return document.getElementById('fPtype'); }
// Salidas => Gastoslb (partner_type = supplier); Entradas => inglb (customer);
// Ambos => payment_type, que si distingue la direccion del movimiento.
function baseForPtype(pt) {
  if (pt === 'inbound') return 'customer';
  if (pt === 'outbound') return 'supplier';
  return 'flow';
}
// Los favoritos no son simmetricos. Leidos de ir.filters en Odoo:
//   Gastoslb: partner_type=supplier, is_internal_transfer=False, state=posted
//   inglb:    partner_type=customer, is_internal_transfer=False   (sin estado)
// Decision del usuario: el panel muestra solo pagos publicados en las dos
// bases. El favorito inglb de Odoo no trae filtro de estado, asi que su
// listado suma tambien borradores y cancelados; el panel lo declara aparte.
function stateForBase() { return 'posted'; }
function syncBaseWithPtype() {
  document.getElementById('fBase').value = baseForPtype(ptypeEl().value);
  document.getElementById('fState').value = stateForBase();
}
// Los ingresos de clientes se agrupan por fecha de publicacion, no por date.
function usePubDate() { return document.getElementById('fDate').value === 'pub'; }

// Fecha y mes que aplican a la fila segun el criterio elegido.
function rowDate(r) { return usePubDate() ? (r.pubdate || '') : (r.date || ''); }
function rowMonth(r) { return rowDate(r).slice(0, 7); }

// Sentido del flujo de caja, para no mezclar ingresos con gastos.
function isInbound(r) { return r.ptype === 'inbound'; }
function isOutbound(r) { return r.ptype === 'outbound'; }
// Descuentos y devoluciones restan al ingreso: son el contra de una venta.
// Etiqueta de flujo de un grupo de pagos.
function flowOf(rows) {
  if (!rows || !rows.length) return 'Ajuste';
  let inb = 0, outb = 0;
  rows.forEach(r => { if (isInbound(r)) inb++; else if (isOutbound(r)) outb++; });
  if (inb && outb) return 'Mixto';
  if (inb) return 'Entrada';
  if (outb) return 'Salida';
  return 'Ajuste';
}
function reasonOf(r) { return String(r.reason || '').toUpperCase(); }
// Ingreso por venta de mercancia.
function isVenta(r) {
  const k = reasonOf(r);
  return k.indexOf('VENTA') !== -1;
}
// Anticipos y Adelantos de clientes.
function isAnticipo(r) {
  const k = reasonOf(r);
  return k.indexOf('ANTICIPO') !== -1 || k.indexOf('ADELANTO') !== -1;
}
// Un ajuste solo descuenta cuando el pago es a un cliente: en el flujo de
// pagos tambien existen ajustes de proveedores que no son descuentos de venta.
function isDiscountOrReturn(r) {
  if (baseCustomer() && !r.isCustomer) return false;
  return isDiscountReason(r);
}
function isDiscountReason(r) {
  const k = String(r.reason || '').toUpperCase();
  return k.indexOf('DESCUENT') !== -1 || k.indexOf('DEVOL') !== -1 || k.indexOf('PROMO') !== -1;
}
function signed() { return document.getElementById('fNeg').checked; }

// Moneda en la que se esta midiendo ahora mismo.
function curKey() {
  if (isCo()) {
    const f = document.getElementById('fComp').value;
    if (f) {
      const r = ROWS.find(x => x.comp === f);
      if (r && r.curCo) return r.curCo;
    }
    return (M.company_currencies.length === 1 ? M.company_currencies[0] : 'USD');
  }
  return document.getElementById('fCur').value;
}

// Valor de una fila segun la medida elegida. Por defecto el gasto se muestra
// positivo; con "signo contable" se respeta el signo que guarda Odoo.
function val(r) {
  const co = isCo();
  let v = co ? (r.amountCo === null ? 0 : r.amountCo) : r.amount;
  if (!signed()) v = Math.abs(v);
  return v;
}

function money(v) { return fmt(v, curKey()); }
function pct(v) { return (Number(v) || 0).toFixed(1) + '%'; }

function filtered() {
  const from = document.getElementById('fFrom').value;
  const to = document.getElementById('fTo').value;
  const st = document.getElementById('fState').value;
  const pt = document.getElementById('fPtype').value;
  const cu = document.getElementById('fCur').value;
  const co = document.getElementById('fComp').value;
  const cust = baseCustomer();
  const supl = baseSupplier();
  return ROWS.filter(r => {
    // En base clientes/proveedores solo entran pagos del tipo de socio
    // correspondiente que no sean transferencias internas (favoritos inglb y
    // Gastoslb). La base de flujo no usa partner_type.
    if (cust && !r.isCustomer) return false;
    if (supl && !r.isSupplier) return false;
    const d = rowDate(r);
    const conRango = !!(from || to);
    // Con un rango activo, un pago sin fecha en el criterio elegido no puede
    // evaluarse. Se conserva solo si el interruptor esta activo, de modo que
    // esos pagos nunca desaparecen en silencio.
    if (conRango) {
      if (!d) {
        if (!document.getElementById('fNoDate').checked) return false;
      } else {
        if (from && d < from) return false;
        // El campo de fecha entrega "YYYY-MM-DD" sin hora, pero las fechas de
        // publicacion traen hora: si el extremo superior no la trae se compara
        // solo el dia, de modo que el ultimo dia del rango entre completo
        // (antes se perdian, por ejemplo, los pagos del 31 de octubre).
        if (to && (to.length === 10 ? d.slice(0, 10) > to : d > to)) return false;
      }
    }
    if (st !== 'all' && r.state !== st) return false;
    // El tipo de flujo solo aplica a la base de flujo: en clientes y proveedores
    // manda partner_type, que es lo que definen los favoritos.
    if (!cust && !supl && M.ptype_field && pt !== 'all' && r.ptype !== pt) return false;
    if (!isCo() && cu && r.cur !== cu) return false;
    if (co && r.comp !== co) return false;
    if (activeReason !== null && r.reason !== activeReason) return false;
    return true;
  });
}

function group(rows, keyFn) {
  const m = new Map();
  rows.forEach(r => {
    const k = keyFn(r);
    if (!m.has(k)) m.set(k, { key: k, label: k, value: 0, count: 0, rows: [] });
    const g = m.get(k);
    g.value += val(r);
    g.count += 1;
    g.rows.push(r);
  });
  return Array.from(m.values());
}

function groupByDoc(rows) {
  const m = new Map();
  rows.forEach(r => {
    if (!m.has(r.doc)) m.set(r.doc, { key: r.doc, label: r.doc, value: 0, count: 0, rows: [] });
    const g = m.get(r.doc);
    g.value += val(r);
    g.count += 1;
    g.rows.push(r);
  });
  return Array.from(m.values());
}

function decorate(nodes, level, parentPath, parentValue, total) {
  return nodes.map(n => ({
    ...n,
    label: n.key,
    // Las filas se necesitan para construir el siguiente nivel del desglose.
    rows: n.rows,
    flow: flowOf(n.rows),
    path: parentPath + '|L' + level + ':' + n.key,
    level: level,
    parentValue: parentValue,
    pct: total ? (n.value / total) * 100 : 0
  }));
}

function flatRows(nodes) {
  const out = [];
  (function walk(list, depth) {
    list.forEach(n => {
      out.push({ ...n, depth: depth });
      const kids = childCache[n.path];
      if (expanded[n.path] && kids && kids.length) walk(kids, depth + 1);
    });
  })(nodes, 0);
  return out;
}

// Nivel 0 = Razon de pago, Nivel 1 = Proveedor, Nivel 2 = Documento
function buildChildren(node) {
  if (!node.rows || !node.rows.length) return [];
  if (node.level === 0) {
    return decorate(group(node.rows, r => r.partner), 1, node.path, node.value, state.total);
  }
  return decorate(groupByDoc(node.rows), 2, node.path, node.value, state.total);
}

function toggle(node) {
  if (expanded[node.path]) { delete expanded[node.path]; render(); return; }
  if (!childCache[node.path]) childCache[node.path] = buildChildren(node);
  expanded[node.path] = true;
  render();
}

// Al cambiar los filtros el conjunto de filas cambia, asi que el desglose
// previamente expandido dejaria de cuadrar.
function resetExpansion() {
  expanded = {};
  childCache = {};
}
function rerender() { resetExpansion(); render(); }

const state = { rows: [], total: 0, count: 0 };
// Avisos de carga (fechas imposibles, pagos sin fecha). Se reconstruyen al
// cambiar el criterio de fecha, asi que se guardan aparte del aviso de fecha.
let AVISOS_BASE = '';

function render() {
  const rows = filtered();
  const total = rows.reduce((a, r) => a + val(r), 0);
  state.total = total;
  state.count = rows.length;

  const byReason = group(rows, r => r.reason).sort((a, b) => b.value - a.value);
  state.rows = decorate(byReason, 0, '', 0, total);

  renderChips(byReason, total);
  renderKpis(rows, byReason, total);
  renderPorAno(rows);
  renderDonut(byReason, total);
  renderHistory();
  renderTable(total);
}

// Cierre por ano y mes, con subtotal por ano: el mismo agrupamiento que
// x_fecha_de_publicacion:year / :month de los favoritos inglb y Gastoslb.
const MES_NOMBRE = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];

function renderPorAno(rows) {
  const porMes = new Map();
  let sinFecha = 0, sinFechaMonto = 0;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    const m = rowMonth(r);
    if (!m) { sinFecha++; sinFechaMonto += Math.abs(val(r)); continue; }
    if (!porMes.has(m)) porMes.set(m, { valor: 0, n: 0 });
    const g = porMes.get(m);
    g.valor += Math.abs(val(r));
    g.n++;
  }
  const meses = Array.from(porMes.keys()).sort();
  const anios = [];
  const porAno = new Map();
  for (let i = 0; i < meses.length; i++) {
    const a = meses[i].slice(0, 4);
    if (!porAno.has(a)) { porAno.set(a, { valor: 0, n: 0 }); anios.push(a); }
    const g = porMes.get(meses[i]);
    const acc = porAno.get(a);
    acc.valor += g.valor; acc.n += g.n;
  }
  anios.sort();

  let h = '<thead><tr><th>Año</th><th>Mes</th><th class="r">Pagos</th>' +
          '<th class="r">Monto</th></tr></thead><tbody>';
  let granTotal = 0, granN = 0;
  for (let i = 0; i < anios.length; i++) {
    const a = anios[i];
    const acc = porAno.get(a);
    const delAnio = meses.filter(m => m.slice(0, 4) === a);
    for (let j = 0; j < delAnio.length; j++) {
      const m = delAnio[j];
      const g = porMes.get(m);
      const esUlt = j === delAnio.length - 1;
      h += '<tr' + (esUlt ? ' class="sub"' : '') + '>' +
           (j === 0 ? '<td><b>' + a + '</b></td>' : '<td></td>') +
           '<td>' + MESES[Number(m.slice(5, 7)) - 1] + ' ' + m.slice(5) + '</td>' +
           '<td class="r">' + g.n + '</td>' +
           '<td class="r">' + money(g.valor) + '</td></tr>';
      if (esUlt) {
        h += '<tr class="sub"><td></td><td><b>Total ' + a + '</b></td>' +
             '<td class="r"><b>' + acc.n + '</b></td>' +
             '<td class="r"><b>' + money(acc.valor) + '</b></td></tr>';
      }
    }
    granTotal += acc.valor; granN += acc.n;
  }
  if (sinFecha) {
    h += '<tr class="sub"><td><b>—</b></td><td><b>Sin fecha</b></td>' +
         '<td class="r"><b>' + sinFecha + '</b></td>' +
         '<td class="r"><b>' + money(sinFechaMonto) + '</b></td></tr>';
    granTotal += sinFechaMonto; granN += sinFecha;
  }
  h += '<tr class="tot"><td></td><td>Total general</td>' +
       '<td class="r">' + granN + '</td>' +
       '<td class="r">' + money(granTotal) + '</td></tr></tbody>';
  document.getElementById('tbAno').innerHTML = h;

  const nom = baseSupplier() ? 'Gastoslb (proveedores)'
           : baseCustomer() ? 'inglb (clientes)' : 'flujo de pagos';
  document.getElementById('hAno').textContent = 'Cierre por ano y mes — ' + nom;
  // El favorito inglb de Odoo no filtra por estado: su listado suma tambien
  // borradores y cancelados. El panel muestra solo publicados, asi que se dice
  // en la misma tarjeta que es la que se compara contra Odoo.
  const notaEstado = (baseCustomer() && document.getElementById('fState').value !== 'all')
    ? ' <b>Ojo:</b> el favorito inglb de Odoo <u>no</u> filtra por estado, asi que su listado ' +
      'de 2026 suma tambien borradores y cancelados y da mas pagos que este panel. Aqui solo se ' +
      'cuentan los <b>publicados</b>: pon "Todos" en Estado para reproducir el favorito.'
    : '';
  document.getElementById('anoHint').innerHTML = (usePubDate()
    ? 'Agrupado por <b>fecha de publicacion</b> (ano / mes), el mismo criterio con el que ' +
      'Odoo agrupa los favoritos inglb y Gastoslb. ' +
      (sinFecha ? sinFecha + ' pago(s) sin fecha quedan fuera de los cortes por mes y se listan al final.'
                : 'Todos los pagos tienen fecha.')
    : '<b class="alerta">Estas cifras usan la fecha del pago, no la de publicacion.</b> ' +
      'Odoo agrupa los favoritos inglb y Gastoslb por fecha de publicacion, asi que los ' +
      'totales por ano <b>no coincidiran</b> con el listado de Odoo. ' +
      'Vuelve a "Fecha de publicacion" para comparar. ' +
      (sinFecha ? sinFecha + ' pago(s) sin fecha quedan fuera de los cortes por mes y se listan al final.'
                : 'Todos los pagos tienen fecha.')) + notaEstado;
  document.getElementById('sub').textContent =
    granN + ' pagos · ' + money(granTotal);
}

function renderChips(byReason, total) {
  const el = document.getElementById('chips');
  el.innerHTML = '';
  const label = document.createElement('div');
  label.style.cssText = 'width:100%;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#8892a8;font-weight:700;margin-bottom:2px';
  label.textContent = 'Filtrar por ' + M.reason_label;
  el.appendChild(label);
  if (activeReason !== null) {
    const clr = document.createElement('button');
    clr.className = 'btn';
    clr.textContent = 'Limpiar: ' + activeReason;
    clr.onclick = () => { activeReason = null; render(); };
    el.appendChild(clr);
  }
  byReason.forEach(g => {
    const b = document.createElement('button');
    b.className = 'chip' + (g.key === activeReason ? ' active' : '');
    b.textContent = g.key + '  ' + money(g.value);
    b.onclick = () => { activeReason = (activeReason === g.key ? null : g.key); render(); };
    el.appendChild(b);
  });
}

// Desglose del lado del dinero: bruto, ajustes que restan y salidas.
// Se calculan siempre sobre importes absolutos para que el signo no dependa
// de como venga el dato en Odoo.
// Componentes del ingreso, con el criterio del favorito "inglb":
//   ventas + anticipos - descuentos/devoluciones = ingreso neto
// El signo se fuerza con Math.abs porque en Odoo los descuentos llegan positivos.
// Totales por favorito dentro de un conjunto de filas ya filtrado. Reproduce
// exactamente el conjunto de "Salidas" (Gastoslb: isSupplier) y el de
// "Entradas" (inglb: isCustomer), para poder comparar en "Ambos".
function baseTotals(rows) {
  let egresos = 0, ingresos = 0, nEg = 0, nIng = 0;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    if (r.isSupplier) { egresos += val(r); nEg++; }
    else if (r.isCustomer) { ingresos += val(r); nIng++; }
  }
  return { egresos: egresos, ingresos: ingresos, nEg: nEg, nIng: nIng };
}

function breakdown(rows) {
  const co = isCo();
  const cust = baseCustomer();
  let ventas = 0, anticipos = 0, desc = 0, eg = 0, otros = 0;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    const raw = co ? (r.amountCo === null ? 0 : r.amountCo) : r.amount;
    const v = Math.abs(raw);
    const entra = cust ? true : isInbound(r);
    if (entra) {
      if (isDiscountOrReturn(r)) desc += v;
      else if (isAnticipo(r)) anticipos += v;
      else if (isVenta(r)) ventas += v;
      else otros += v;
    } else if (cust || isOutbound(r)) {
      eg += v;
    }
  }
  const bruto = ventas + anticipos + otros;
  const neto = bruto - desc;
  return { ventas: ventas, anticipos: anticipos, otros: otros, desc: desc,
           bruto: bruto, neto: neto, egresos: eg, balance: neto - eg };
}

// Tarjeta con los pagos que no tienen fecha en el criterio elegido. Se
// declaran en el panel para que ninguno se pierda en silencio.
function cardSinFecha(rows, card) {
  const sinFecha = rows.filter(r => !rowDate(r));
  if (!sinFecha.length) return '';
  const mto = sinFecha.reduce((a, r) => a + Math.abs(val(r)), 0);
  return card('Sin fecha de publicacion', money(sinFecha.length),
              money(mto) + ' · no entran en cortes mensuales');
}

function renderKpis(rows, byReason, total) {
  const pt = document.getElementById('fPtype').value;
  const card = (label, value, note) =>
    '<div class="kpi"><span>' + label + '</span><b>' + value + '</b>' +
    (note ? '<small>' + note + '</small>' : '') + '</div>';
  let html = '';

  if (baseCustomer()) {
    const k = breakdown(rows);
    html =
      card('Ingresos por ventas', money(k.ventas), 'Ventas a clientes') +
      card('Anticipos de clientes', money(k.anticipos), 'Adelantos cobrados') +
      (k.otros ? card('Otros ingresos', money(k.otros), 'Sin clasificar') : '') +
      card('Total ingresos', money(k.bruto), 'Suma de los ingresos') +
      card('Descuentos y devoluciones', money(k.desc), 'Restan del total') +
      card('Ingreso neto', money(k.neto), 'Total ingresos - descuentos') +
      (k.egresos ? card('Total gastos / egresos', money(k.egresos), 'Salidas') : '') +
      (k.egresos ? card('Margen / balance', money(k.balance),
                        k.balance >= 0 ? 'Superávit' : 'Déficit') : '') +
      card('Categorías', byReason.length, 'en ' + M.reason_label) +
      cardSinFecha(rows, card);
    document.getElementById('kpis').innerHTML = html;
    return;
  }

  const avg = rows.length ? total / rows.length : 0;
  const top = byReason[0];
  const esIngreso = pt === 'inbound' && !baseCustomer() && !baseSupplier();
  const esEgreso = baseSupplier() || (pt === 'outbound' && !baseCustomer());
  const rotuloTotal = baseSupplier() ? 'Total de egresos (Gastoslb)'
                   : esEgreso ? 'Total de egresos'
                   : esIngreso ? 'Total de ingresos' : 'Total analizado';
  const rotuloMayor = esIngreso ? 'Mayor ingreso' : 'Mayor gasto';
  // En "Ambos" se separan los dos totales para poder contrastarlos con lo que
  // muestra cada base por su cuenta: mismo conjunto de Salidas y de Entradas.
  const par = (pt === 'all' && !baseSupplier()) ? baseTotals(rows) : null;
  html =
    card(rotuloTotal, money(total), rows.length + ' registros') +
    (par ? card('Total de egresos', money(par.egresos),
                par.nEg + ' pagos · coincide con Salidas (Gastoslb)') +
           card('Total de ingresos', money(par.ingresos),
                par.nIng + ' pagos · coincide con Entradas (inglb)') : '') +
    card('Ticket promedio', money(avg), 'por pago') +
    card('Categorías', byReason.length, 'en ' + M.reason_label) +
    (top ? card(rotuloMayor, money(top.value),
                top.key + ' · ' + pct(top.value / total * 100)) : '');

  if (esIngreso) {
    const k = breakdown(rows);
    html += card('Descuentos y devoluciones', money(k.desc), 'Restan al ingreso') +
            card('Ingreso neto', money(k.neto), 'Bruto - descuentos');
  }

  html += cardSinFecha(rows, card);

  // Aviso de coherencia: el criterio de clientes no trae la direccion del
  // pago, asi que sin cambiar la base a flujo el filtro no puede aplicarse.
  if ((baseCustomer() || baseSupplier()) && pt !== 'all') {
    const nom = baseSupplier() ? 'Proveedores' : 'Clientes';
    const otro = baseSupplier() ? 'Clientes' : 'Proveedores';
    html += card('Criterio por socio, no por direccion', money(0),
                 'La base ' + nom + ' no usa payment_type: es el dominio del ' +
                 'favorito. Para filtrar por direccion usa Flujo de pagos; ' +
                 'para los ingresos usa ' + otro + '.');
  } else if (esEgreso || pt === 'all') {
    const dir = rows.reduce((a, r) => {
      if (isInbound(r)) a.inb++; else if (isOutbound(r)) a.outb++;
      return a;
    }, { inb: 0, outb: 0 });
    const otros = rows.length - dir.inb - dir.outb;
    const nota = otros
      ? 'Sin payment_type: ' + otros + ' registro(s)'
      : dir.inb && dir.outb
        ? dir.inb + ' entradas y ' + dir.outb + ' salidas'
        : dir.inb ? 'Todas entradas' : 'Todas salidas';
    html += card('Control de direccion', money(rows.length), nota);
  }

  document.getElementById('kpis').innerHTML = html;
}

const PALETTE = ['#213C83', '#dc2626', '#059669', '#d97706', '#7c3aed',
                 '#0891b2', '#db2777', '#65a30d', '#ea580c', '#4f46e5',
                 '#0d9488', '#be123c', '#a16207', '#15803d', '#9333ea',
                 '#1d4ed8', '#b91c1c', '#047857', '#c2410c', '#6d28d9',
                 '#0e7490', '#a21caf', '#4d7c0f', '#9f1239', '#1e40af',
                 '#3f6212', '#7e22ce', '#0f766e'];

// ---- Grafico historico -------------------------------------------------
let hist = null;

// Un solo eje, siempre por ano-mes ("Oct 2026"). Cada barra es un mes
// concreto, de modo que nunca se confunde un mes de 2026 con el mismo mes de 2025.
const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
               'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

function bucketOf(d) {
  if (!d || d.length < 7) return 'sin-fecha';
  return d.slice(0, 7);   // "2026-10"
}

// "2026-10" -> "Oct 2026", para leer el eje sin effort.
function labelOf(bucket) {
  if (bucket === 'sin-fecha') return 'Sin fecha';
  const y = bucket.slice(0, 4), m = parseInt(bucket.slice(5, 7), 10);
  return (MESES[m - 1] || '?') + ' ' + y;
}

// Un pago con fecha imposible (corrupta en la base) no debe crear un cubo
// propio "sin-fecha" que aplaste el resto del eje.
function saneDate(d) {
  return !!d && d.length >= 7 && parseInt(d.slice(0, 4), 10) <= new Date().getFullYear() + 1;
}

function renderHistory() {
  const rows = filtered();
  const topN = parseInt(document.getElementById('fTop').value, 10) || 0;

  const totals = new Map();
  rows.forEach(r => totals.set(r['reason'], (totals.get(r['reason']) || 0) + val(r)));
  const ranked = Array.from(totals.entries()).sort((a, b) => b[1] - a[1]).map(e => e[0]);
  const keep = topN ? ranked.slice(0, topN) : ranked.slice();
  const keepSet = new Set(keep);
  const nRest = ranked.length - keep.length;

  const usable = rows.filter(r => saneDate(rowDate(r)));
  const buckets = Array.from(new Set(usable.map(r => bucketOf(rowDate(r))))).sort();

  const acc = new Map();
  keep.forEach(k => acc.set(k, new Map()));
  let restMap = new Map();
  usable.forEach(r => {
    const b = bucketOf(rowDate(r));
    const v = val(r);
    if (keepSet.has(r['reason'])) {
      const m = acc.get(r['reason']);
      m.set(b, (m.get(b) || 0) + v);
    } else {
      restMap.set(b, (restMap.get(b) || 0) + v);
    }
  });

  const datasets = keep.map((k, i) => ({
    label: k,
    data: buckets.map(b => acc.get(k).get(b) || 0),
    backgroundColor: PALETTE[i % PALETTE.length],
    borderWidth: 0,
  }));
  if (nRest > 0) {
    datasets.push({
      label: 'Otras (' + nRest + ')',
      data: buckets.map(b => restMap.get(b) || 0),
      backgroundColor: '#cbd5e1',
      borderWidth: 0,
    });
  }

  if (hist) { hist.destroy(); hist = null; }
  const canvas = document.getElementById('hist');
  if (!buckets.length || !datasets.length) {
    // Destruir el grafico anterior no basta: hay que limpiar el lienzo entero.
    canvas.getContext('2d').clearRect(0, 0, canvas.width || 300, canvas.height || 150);
    document.getElementById('histHint').textContent =
      'Sin datos en el rango y los filtros seleccionados.';
    return;
  }

  hist = new Chart(canvas.getContext('2d'), {
    type: 'bar',
    data: { labels: buckets.map(labelOf), datasets: datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { stacked: true, ticks: { font: { size: 10 }, maxRotation: 60, autoSkip: true,
                                     autoSkipPadding: 8 } },
        y: { stacked: true, beginAtZero: !signed(), ticks: { font: { size: 10 },
             callback: v => fmt(v, curKey()) } },
      },
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 11, padding: 8, font: { size: 10.5 } } },
        tooltip: {
          callbacks: {
            label(it) {
              const t = it.dataset.data.reduce((a, v) => a + (Number(v) || 0), 0);
              return ' ' + it.dataset.label + ': ' + fmt(it.raw, curKey()) +
                     ' (' + (t ? it.raw / t * 100 : 0).toFixed(1) + '%)';
            },
            footer(items) {
              const t = items.reduce((a, i) => a + (Number(i.raw) || 0), 0);
              return 'Total: ' + fmt(t, curKey());
            }
          }
        }
      },
      onClick(_e, els) {
        if (!els.length) return;
        const k = datasets[els[0].datasetIndex].label;
        if (k.startsWith('Otras')) return;
        activeReason = (activeReason === k ? null : k);
        render();
      }
    }
  });

  document.getElementById('histHint').innerHTML =
    'Un solo eje por <b>ano-mes</b>, en <b>' + curKey() + '</b>: cada barra es un mes ' +
    'concreto. ' + keep.length + ' razon(es) con serie propia' +
    (nRest > 0 ? ', el resto agrupado en «Otras»' : '') +
    '. Clic en un bloque para filtrar por esa razon. Fechas imposibles excluidas: ' +
    (rows.length - usable.length) + '.';
}

function clearReason() { activeReason = null; render(); }

function centerPlugin(caption, value) {
  return {
    id: 'center',
    afterDatasetsDraw(c) {
      const meta = c.getDatasetMeta(0);
      const area = c.chartArea;
      if (!meta.data.length || !area) return;
      const x = (area.left + area.right) / 2;
      const y = (area.top + area.bottom) / 2;
      const ctx = c.ctx;
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#8892a8';
      ctx.font = '600 11px sans-serif';
      ctx.fillText(caption, x, y - 12);
      ctx.fillStyle = '#1a1a1a';
      ctx.font = '700 17px sans-serif';
      ctx.fillText(value, x, y + 9);
      ctx.restore();
    }
  };
}

function slicePlugin() {
  return {
    id: 'slices',
    afterDatasetsDraw(c) {
      const meta = c.getDatasetMeta(0);
      const data = c.data.datasets[0].data;
      const total = data.reduce((a, v) => a + (Number(v) || 0), 0);
      if (!total) return;
      const ctx = c.ctx;
      ctx.save();
      meta.data.forEach((arc, i) => {
        const p = ((Number(data[i]) || 0) / total) * 100;
        if (p < 4) return;
        const r = (arc.innerRadius + arc.outerRadius) / 2;
        const a = (arc.startAngle + arc.endAngle) / 2;
        ctx.fillStyle = '#fff';
        ctx.font = '700 11px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(p.toFixed(0) + '%', arc.x + Math.cos(a) * r, arc.y + Math.sin(a) * r);
      });
      ctx.restore();
    }
  };
}

function renderDonut(byReason, total) {
  const el = document.getElementById('donut');
  if (chart) { chart.destroy(); chart = null; }
  const rows = byReason.filter(g => g.value > 0);
  chart = new Chart(el.getContext('2d'), {
    type: 'doughnut',
    data: {
      labels: rows.map(r => r.key),
      datasets: [{
        data: rows.map(r => r.value),
        backgroundColor: PALETTE.slice(0, rows.length),
        borderColor: '#fff', borderWidth: 2, hoverOffset: 6
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '58%',
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 11, padding: 10, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label(it) {
              const vals = it.dataset.data;
              const t = vals.reduce((a, v) => a + (Number(v) || 0), 0);
              const v = Number(it.raw) || 0;
              return ' ' + it.label + ': ' + money(v) + ' (' + (t ? v / t * 100 : 0).toFixed(1) + '%)';
            }
          }
        }
      },
      onClick(_e, els) {
        if (els.length) {
          const k = rows[els[0].index].key;
          activeReason = (activeReason === k ? null : k);
          render();
        }
      }
    },
    plugins: [slicePlugin(), centerPlugin('Total', money(total))]
  });
}

function renderTable(total) {
  const rows = flatRows(state.rows);
  const tb = document.getElementById('tb');
  if (!rows.length) {
    tb.innerHTML = '<tr><td colspan="5" class="empty">Sin registros para los filtros seleccionados.</td></tr>';
    return;
  }
  let html = '';
  rows.forEach(n => {
    const pad = n.depth ? 18 + n.depth * 18 : 0;
    html += '<tr>';
    html += '<td><div class="lbl" style="padding-left:' + pad + 'px">';
    if (n.level < 2) {
      html += '<button class="tgl' + (expanded[n.path] ? ' open' : '') + '" onclick="toggleByPath(\'' +
              n.path.replace(/'/g, "\\'") + '\')">&rsaquo;</button>';
    } else {
      html += '<span class="leaf">&bull;</span>';
    }
    if (n.level === 1) html += '<span class="lvl">Proveedor</span>';
    if (n.level === 2) html += '<span class="lvl">Documento</span>';
    html += '<span>' + escapeHtml(n.label) + '</span></div></td>';
    html += '<td class="num">' + money(n.value) + '</td>';
    html += '<td>' + escapeHtml(n.flow || 'Ajuste') + '</td>';
    html += '<td class="num">' + pct(n.pct) + '<div class="bar"><i style="width:' +
              Math.min(n.pct, 100) + '%"></i></div></td>';
    html += '<td class="num">' + n.count + '</td></tr>';
  });
  html += '<tr class="tot"><td>Total</td><td class="num">' + money(total) +
          '</td><td></td><td class="num">100.0%</td><td class="num">' + state.count + '</td></tr>';
  tb.innerHTML = html;
}

function toggleByPath(path) {
  const find = nodes => {
    for (const n of nodes) {
      if (n.path === path) return n;
      const kids = childCache[n.path];
      if (kids) {
        const r = find(kids);
        if (r) return r;
      }
    }
    return null;
  };
  const node = find(state.rows);
  if (node) toggle(node);
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function setPreset(kind) {
  const dates = ROWS.map(r => rowDate(r)).filter(Boolean).sort();
  if (kind === 'all') {
    document.getElementById('fFrom').value = dates[0] || '';
    document.getElementById('fTo').value = dates[dates.length - 1] || '';
  } else if (kind === 'today') {
    const hoy = localDay(new Date());
    document.getElementById('fFrom').value = hoy;
    document.getElementById('fTo').value = hoy;
  } else {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    document.getElementById('fFrom').value = kind === 'month' ? y + '-' + m + '-01' : y + '-01-01';
    document.getElementById('fTo').value = kind === 'month' ? y + '-' + m + '-31' : y + '-12-31';
  }
  rerender();
}

// ---- Reporte del dia (PDF) ---------------------------------------------
// Cierre de caja del dia. Solo lee los datos ya cargados en el panel: no
// consulta ni modifica Odoo. Las fechas se llevan a hora de Venezuela.
const TZ_REPORTE = 'America/Caracas';
const FMT_DIA = (function () {
  try { return new Intl.DateTimeFormat('en-CA', { timeZone: TZ_REPORTE, year: 'numeric',
                                                  month: '2-digit', day: '2-digit' }); }
  catch (_) { return null; }
})();
// Dia en hora de Venezuela, "YYYY-MM-DD".
function localDay(d) {
  if (FMT_DIA) return FMT_DIA.format(d);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' +
         String(d.getDate()).padStart(2, '0');
}
// La fecha de publicacion llega de Odoo en UTC ("2026-11-05 22:10:56"): se pasa
// a hora local para que lo publicado de noche no caiga en el dia siguiente.
function pubLocalDay(r) {
  if (r._pd !== undefined) return r._pd;
  const p = r.pubdate || '';
  let out = '';
  if (p.length >= 16) {
    const d = new Date(p.replace(' ', 'T') + 'Z');
    out = isNaN(d) ? p.slice(0, 10) : localDay(d);
  } else if (p.length >= 10) {
    out = p.slice(0, 10);
  }
  r._pd = out;
  return out;
}
// Dia del reporte: el elegido si Desde = Hasta; si no, hoy.
function diaReporte() {
  const f = document.getElementById('fFrom').value;
  const t = document.getElementById('fTo').value;
  return (f && f === t) ? f : localDay(new Date());
}
function sumarDias(dia, n) {
  const d = new Date(dia + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function resumenDia(dia) {
  const comp = document.getElementById('fComp').value;
  const coCur = (function () {
    if (comp) { const r = ROWS.find(x => x.comp === comp); if (r && r.curCo) return r.curCo; }
    return (M.company_currencies.length === 1 ? M.company_currencies[0] : 'USD');
  })();
  // Siempre en moneda de compania y en positivo, como los totales del panel.
  const v = r => Math.abs(r.amountCo === null || r.amountCo === undefined ? r.amount : r.amountCo);
  const delDia = ROWS.filter(r => (!comp || r.comp === comp) && (r.isCustomer || r.isSupplier) &&
                                  (pubLocalDay(r) === dia || (r.date || '').slice(0, 10) === dia));
  const pub = delDia.filter(r => r.state === 'posted' && pubLocalDay(r) === dia);
  // Pagado en el dia: fecha de pago del dia, publicado o no (sin cancelados/rechazados).
  const pag = delDia.filter(r => (r.date || '').slice(0, 10) === dia && r.state !== 'cancel' && r.state !== 'rejected');

  // Categoria de un cobro a cliente, con el criterio inglb.
  const catIng = r => isDiscountReason(r) ? 'desc' : isAnticipo(r) ? 'ant' : isVenta(r) ? 'venta' : 'otros';

  // Ingresos (criterio inglb: ventas + anticipos + otros - descuentos) y egresos
  // (criterio Gastoslb, agrupados por razon) de un conjunto de pagos.
  const resumir = rows => {
    const ing = { ventas: 0, anticipos: 0, otros: 0, desc: 0, nV: 0, nA: 0, nO: 0, nD: 0 };
    const ingPorRazon = {};
    rows.filter(r => r.isCustomer).forEach(r => {
      const x = v(r);
      if (isDiscountReason(r)) { ing.desc += x; ing.nD++; }
      else if (isAnticipo(r)) { ing.anticipos += x; ing.nA++; }
      else if (isVenta(r)) { ing.ventas += x; ing.nV++; }
      else { ing.otros += x; ing.nO++; }
      const k = catIng(r);
      if (!ingPorRazon[k]) ingPorRazon[k] = {};
      ingPorRazon[k][r.reason] = (ingPorRazon[k][r.reason] || 0) + 1;
    });
    ing.bruto = ing.ventas + ing.anticipos + ing.otros;
    ing.neto = ing.bruto - ing.desc;
    const egRows = rows.filter(r => r.isSupplier);
    const egTotal = egRows.reduce((a, r) => a + v(r), 0);
    const porRazon = new Map();
    egRows.forEach(r => {
      if (!porRazon.has(r.reason)) porRazon.set(r.reason, { razon: r.reason, monto: 0, n: 0 });
      const g = porRazon.get(r.reason); g.monto += v(r); g.n++;
    });
    return { ing: ing, ingPorRazon: ingPorRazon, egN: egRows.length, egTotal: egTotal,
             balance: ing.neto - egTotal,
             porRazon: Array.from(porRazon.values()).sort((a, b) => b.monto - a.monto) };
  };
  const P = resumir(pub);

  // Por lado:
  //   Pagado hoy    = pagos con fecha de pago del dia (sin cancelados/rechazados).
  //   Publicado hoy = pagos publicados con fecha de publicacion del dia, con las
  //                   fechas de pago a las que corresponden.
  //   En espera     = pagos con fecha de pago del dia aun sin publicar.
  const control = (lado, cat) => {
    const deLado = r => (lado === 'eg' ? r.isSupplier : r.isCustomer) && (!cat || catIng(r) === cat);
    const b = { pag: [0, 0], pub: [0, 0], esp: [0, 0] };
    const fechasPago = {};
    delDia.forEach(r => {
      if (!deLado(r)) return;
      const x = v(r);
      const fp = (r.date || '').slice(0, 10);
      if (fp === dia && r.state !== 'cancel' && r.state !== 'rejected') {
        b.pag[0]++; b.pag[1] += x;
        if (r.state !== 'posted') { b.esp[0]++; b.esp[1] += x; }
      }
      if (r.state === 'posted' && pubLocalDay(r) === dia) {
        b.pub[0]++; b.pub[1] += x;
        if (fp) fechasPago[fp] = true;
      }
    });
    return { b: b, fechasPago: Object.keys(fechasPago).sort() };
  };

  // Publicado en el dia en el nivel superior (ultimos 7 dias); lo pagado en `pag`
  // (resumen y secciones de la hoja 1).
  return { dia: dia, comp: comp, cur: coCur, ing: P.ing, egN: P.egN, egTotal: P.egTotal,
           ingPorRazon: P.ingPorRazon,
           ctlIngCat: { venta: control('ing', 'venta'), ant: control('ing', 'ant'),
                        otros: control('ing', 'otros'), desc: control('ing', 'desc') },
           balance: P.balance, porRazon: P.porRazon,
           pag: resumir(pag),
           ctlEg: control('eg'), ctlIng: control('ing') };
}

const DIA_SEMANA = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
const MESES_LARGO = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
                     'septiembre', 'octubre', 'noviembre', 'diciembre'];
function diaSemana(dia) { return DIA_SEMANA[new Date(dia + 'T12:00:00Z').getUTCDay()]; }
function ddmm(dia) { return dia.slice(8, 10) + '/' + dia.slice(5, 7); }
// ["2026-11-03","2026-11-04"] -> "03 y 04 de noviembre"
function listaFechas(fechas) {
  const porMes = [];
  fechas.forEach(f => {
    const k = f.slice(0, 7);
    let g = porMes.find(x => x.k === k);
    if (!g) { g = { k: k, dias: [] }; porMes.push(g); }
    g.dias.push(f.slice(8, 10));
  });
  const y = arr => arr.length > 1 ? arr.slice(0, -1).join(', ') + ' y ' + arr[arr.length - 1] : arr[0];
  return y(porMes.map(g => y(g.dias) + ' de ' + MESES_LARGO[Number(g.k.slice(5, 7)) - 1]));
}

// Arma el HTML del cierre de un dia (lo usa el boton y el PDF automatico).
function htmlReporteDia(dia) {
  const R = resumenDia(dia);
  const D = R.pag; // lo pagado en el dia: resumen y secciones de la hoja 1
  const m = x => fmt(x, R.cur);
  const e = escapeHtml;
  const fechaTxt = diaSemana(R.dia) + ' ' + ddmm(R.dia) + '/' + R.dia.slice(0, 4);
  const ahora = new Date();
  let generado;
  try {
    generado = new Intl.DateTimeFormat('sv-SE', { timeZone: TZ_REPORTE, year: 'numeric', month: '2-digit',
      day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(ahora);
  } catch (_) { generado = ahora.toISOString().slice(0, 16).replace('T', ' '); }

  // Ultimos 7 dias, terminando en el dia del reporte.
  const semana = [];
  for (let i = 6; i >= 0; i--) semana.push(resumenDia(sumarDias(R.dia, -i)));

  // Valor 0 en gris claro, como en el cierre de ejecutivos.
  const num = (x, fmtFn) => x ? (fmtFn ? fmtFn(x) : x) : '<span class="z">' + (fmtFn ? fmtFn(0) : 0) + '</span>';
  const coletilla = ctl => {
    const otras = ctl.fechasPago.filter(f => f !== R.dia);
    if (!otras.length) return ctl.b.pub[0] ? 'Pagos de hoy' : '<span class="z">–</span>';
    return (ctl.fechasPago.indexOf(R.dia) !== -1 ? 'Incluye pagos del ' : 'Pagos del ') + listaFechas(otras);
  };

  // Para revisar: solo lo que pide accion o explica una cifra.
  const avisos = [];
  if (R.ctlEg.b.esp[0]) avisos.push('<b>Pagos a proveedores</b>: ' + R.ctlEg.b.esp[0] +
    ' pagado(s) hoy sin publicar por <b>' + m(R.ctlEg.b.esp[1]) + '</b>.');
  if (R.ctlIng.b.esp[0]) avisos.push('<b>Cobros a clientes</b>: ' + R.ctlIng.b.esp[0] +
    ' cobrado(s) hoy sin publicar por <b>' + m(R.ctlIng.b.esp[1]) + '</b>.');
  const otrasEg = R.ctlEg.fechasPago.filter(f => f !== R.dia);
  if (otrasEg.length) avisos.push('<b>Egresos publicados hoy</b>: corresponden a pagos del ' +
    listaFechas(otrasEg) + '.');
  if (D.balance < 0) avisos.push('<b>Balance del día</b>: déficit de ' + m(-D.balance) + '.');

  const kpi = (label, valor, cls) =>
    '<div class="k' + (cls ? ' ' + cls : '') + '"><span>' + label + '</span><b>' + valor + '</b></div>';

  const encabezado = (hoja, total) =>
    '<div class="hd"><div><h1>Cierre del día · Caja</h1><div class="fecha">' + fechaTxt + '</div></div>' +
    '<div class="hdr"><div class="sello">FOTO FIJA · NO SE MODIFICA</div>' +
    '<div class="gen">Generado ' + e(generado) + ' (hora Venezuela) · Pagos (Odoo) · ' +
    (R.comp ? e(R.comp) + ' · ' : '') + 'Montos en ' + e(R.cur) + ' · Hoja ' + hoja + ' de ' + total +
    '</div></div></div>';
  const pie = '<div class="pie"><span>Latinbien · Caja y egresos</span>' +
    '<span>Consulta de solo lectura a Odoo</span></div>';

  // --- Hoja 1: resumen, pagado vs publicado y egresos por razon -----------
  const filaCtl = (nombre, ctl, cls) =>
    '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td class="n">' + nombre + '</td>' +
    '<td class="r g1">' + num(ctl.b.pag[0]) + '</td><td class="r">' + num(ctl.b.pag[1], m) + '</td>' +
    '<td class="r g1">' + num(ctl.b.pub[0]) + '</td><td class="r">' + num(ctl.b.pub[1], m) + '</td>' +
    '<td class="c">' + coletilla(ctl) + '</td>' +
    '<td class="r g1">' + (ctl.b.esp[0] ? '<b class="rojo">' + ctl.b.esp[0] + '</b>' : num(0)) + '</td>' +
    '<td class="r">' + (ctl.b.esp[0] ? '<b class="rojo">' + m(ctl.b.esp[1]) + '</b>' : num(0, m)) + '</td></tr>';
  const maxRazon = D.porRazon.length ? D.porRazon[0].monto : 0;

  // ¿De donde vinieron los ingresos? ventas, anticipos y descuentos por separado.
  const razonesDe = k => Object.keys(D.ingPorRazon[k] || {}).sort().map(e).join(', ') || '<span class="z">–</span>';
  const catsIng = [
    ['Ingresos por ventas', 'venta', D.ing.ventas, D.ing.nV, false],
    ['Anticipos de clientes', 'ant', D.ing.anticipos, D.ing.nA, false],
    ['Otros ingresos', 'otros', D.ing.otros, D.ing.nO, false],
    ['Descuentos y devoluciones (restan)', 'desc', D.ing.desc, D.ing.nD, true],
  ].filter(c => c[2] || c[1] === 'venta' || c[1] === 'ant');
  const maxIng = Math.max.apply(null, [0].concat(catsIng.map(c => c[2])));
  const tablaIngresos = !(D.ing.bruto || D.ing.desc) ? '' :
    '<h2>¿De dónde vinieron los ingresos? <small>cobros a clientes pagados hoy (fecha de pago)</small></h2>' +
    '<table class="t"><thead><tr><th>Concepto</th><th>Razón de pago en Odoo</th><th class="r">Pagos</th>' +
    '<th class="r">Monto</th><th class="r">% del bruto</th><th style="width:28%"></th></tr></thead><tbody>' +
    catsIng.map(c => '<tr><td class="n"' + (c[4] ? ' style="color:#b91c1c"' : '') + '>' + c[0] + '</td><td class="c">' +
      razonesDe(c[1]) + '</td><td class="r">' + num(c[3]) + '</td><td class="r' + (c[4] ? ' rojo' : '') + '">' +
      (c[2] ? (c[4] ? '-' : '') + m(c[2]) : num(0, m)) + '</td><td class="r">' +
      (D.ing.bruto ? (c[2] / D.ing.bruto * 100).toFixed(1) : '0.0') + '%</td><td><div class="bar"><i style="width:' +
      (maxIng ? c[2] / maxIng * 100 : 0).toFixed(1) + '%;background:' + (c[4] ? '#b91c1c' : '#23955a') +
      '"></i></div></td></tr>').join('') +
    '<tr class="tot"><td>Ingreso neto</td><td class="c" style="font-weight:400">ventas + anticipos − descuentos</td>' +
    '<td class="r">' + (D.ing.nV + D.ing.nA + D.ing.nO + D.ing.nD) + '</td><td class="r">' + m(D.ing.neto) +
    '</td><td></td><td></td></tr></tbody></table>';

  const hoja1 =
    '<section class="hoja">' + encabezado(1, 2) +
    '<div class="kp">' +
      kpi('Ingresos por ventas', m(D.ing.ventas)) +
      kpi('Anticipos de clientes', m(D.ing.anticipos)) +
      (D.ing.otros ? kpi('Otros ingresos', m(D.ing.otros)) : '') +
      kpi('Descuentos y devol.', '-' + m(D.ing.desc)) +
      kpi('Ingreso neto', m(D.ing.neto), 'pos') +
      kpi('Egresos pagados', m(D.egTotal), 'neg') +
      kpi('Balance del día', m(D.balance), D.balance >= 0 ? 'pos' : 'neg') +
      kpi('Pagos en espera', String(R.ctlEg.b.esp[0] + R.ctlIng.b.esp[0]),
          (R.ctlEg.b.esp[0] + R.ctlIng.b.esp[0]) ? 'neg' : '') +
    '</div>' +
    '<p class="mini" style="margin:-4px 0 8px">Resumen con lo <b>pagado hoy</b> (fecha de pago), incluidos los pagos que aún esperan publicarse.</p>' +
    (avisos.length ? '<div class="rev"><div class="revt">Para revisar</div><ul>' +
      avisos.map(a => '<li>' + a + '</li>').join('') + '</ul></div>' : '') +

    '<h2>Pagado vs. publicado</h2>' +
    '<table class="t"><thead>' +
      '<tr class="grp"><th></th><th colspan="2" class="ga">Pagado hoy</th>' +
      '<th colspan="3" class="gb">Publicado hoy</th><th colspan="2" class="gc">En espera</th></tr>' +
      '<tr><th>Concepto</th><th class="r g1">Pagos</th><th class="r">Monto</th>' +
      '<th class="r g1">Pagos</th><th class="r">Monto</th><th>Corresponde a</th>' +
      '<th class="r g1">Pagos</th><th class="r">Monto</th></tr></thead><tbody>' +
      filaCtl('Egresos (pagos a proveedores)', R.ctlEg) +
      filaCtl('<b>Ingresos (cobros a clientes)</b>', R.ctlIng, 'fuerte') +
      filaCtl('&nbsp;&nbsp;&nbsp;· Ingresos por ventas', R.ctlIngCat.venta, 'subi') +
      filaCtl('&nbsp;&nbsp;&nbsp;· Anticipos de clientes', R.ctlIngCat.ant, 'subi') +
      (R.ctlIngCat.otros.b.pag[0] || R.ctlIngCat.otros.b.pub[0]
        ? filaCtl('&nbsp;&nbsp;&nbsp;· Otros ingresos', R.ctlIngCat.otros, 'subi') : '') +
      (R.ctlIngCat.desc.b.pag[0] || R.ctlIngCat.desc.b.pub[0]
        ? filaCtl('&nbsp;&nbsp;&nbsp;· Descuentos y devoluciones (restan)', R.ctlIngCat.desc, 'subi') : '') +
    '</tbody></table>' +
    '<p class="mini"><b>Pagado hoy</b>: pagos con fecha de pago de hoy. <b>Publicado hoy</b>: pagos publicados hoy, ' +
    'aunque se hayan pagado otro día. <b>En espera</b>: pagados hoy y todavía sin publicar (borrador o en aprobación).</p>' +

    tablaIngresos +
    (D.porRazon.length
      ? '<h2>¿En qué se fueron los egresos? <small>egresos pagados hoy (fecha de pago) por razón de pago</small></h2>' +
        '<table class="t"><thead><tr><th>Razón de pago</th><th class="r">Pagos</th><th class="r">Monto</th>' +
        '<th class="r">%</th><th style="width:38%"></th></tr></thead><tbody>' +
        D.porRazon.map(g => '<tr><td class="n">' + e(g.razon) + '</td><td class="r">' + g.n + '</td><td class="r">' +
          m(g.monto) + '</td><td class="r">' + (D.egTotal ? (g.monto / D.egTotal * 100).toFixed(1) : '0.0') +
          '%</td><td><div class="bar"><i style="width:' + (maxRazon ? g.monto / maxRazon * 100 : 0).toFixed(1) +
          '%"></i></div></td></tr>').join('') +
        '<tr class="tot"><td>Total egresos</td><td class="r">' + D.egN + '</td><td class="r">' + m(D.egTotal) +
        '</td><td class="r">100.0%</td><td></td></tr></tbody></table>'
      : '') +
    pie + '</section>';

  // --- Hoja 2: ultimos 7 dias ---------------------------------------------
  // Arriba lo pagado (fecha de pago, igual que la hoja 1); abajo lo publicado como control.
  const filasPagado = [
    ['Ingresos por ventas', s => s.pag.ing.ventas, 'a'],
    ['Anticipos de clientes', s => s.pag.ing.anticipos, 'a'],
    ['Ingreso neto', s => s.pag.ing.neto, 'a', true],
    ['Egresos pagados', s => s.pag.egTotal, 'b', true],
    ['Balance del día', s => s.pag.balance, 'bal', true],
  ];
  const filasPublicado = [
    ['Ingresos por ventas', s => s.ing.ventas, 'a'],
    ['Anticipos de clientes', s => s.ing.anticipos, 'a'],
    ['Ingreso neto', s => s.ing.neto, 'a', true],
    ['Egresos publicados', s => s.egTotal, 'b', true],
    ['Balance del día', s => s.balance, 'bal', true],
    ['Egresos en espera de publicar', s => s.ctlEg.b.esp[1], 'c'],
  ];
  const celda = (x, tipo, max) => {
    if (tipo === 'bal') return '<td class="r ' + (x < 0 ? 'rojo' : x > 0 ? 'verde' : '') + '">' + (x ? m(x) : '<span class="z">0</span>') + '</td>';
    if (!x) return '<td class="r"><span class="z">0</span></td>';
    const a = max ? Math.max(0.08, x / max * 0.85) : 0;
    const col = tipo === 'a' ? '35,149,90' : tipo === 'c' ? '224,123,36' : '45,93,159';
    return '<td class="r" style="background:rgba(' + col + ',' + a.toFixed(2) + ');' +
           (a > 0.5 ? 'color:#fff;font-weight:700' : '') + '">' + m(x) + '</td>';
  };
  const cabeceraSemana = primera => '<thead><tr><th>' + primera + '</th>' +
    semana.map(s => '<th class="r' + (s.dia === R.dia ? ' hoy' : '') + '">' + diaSemana(s.dia).slice(0, 3) + ' ' +
                    ddmm(s.dia) + '</th>').join('') + '<th class="r tt">Total 7 días</th></tr></thead>';
  const tablaDias = filas =>
    '<table class="t sem">' + cabeceraSemana('Concepto') + '<tbody>' +
    filas.map(f => {
      const vals = semana.map(f[1]);
      const max = Math.max.apply(null, vals.map(Math.abs));
      const tot = vals.reduce((a, x) => a + x, 0);
      return '<tr' + (f[3] ? ' class="fuerte"' : '') + '><td class="n">' + f[0] + '</td>' +
        vals.map(x => celda(x, f[2], max)).join('') +
        '<td class="r tt' + (f[2] === 'bal' ? (tot < 0 ? ' rojo' : ' verde') : '') + '"><b>' + m(tot) + '</b></td></tr>';
    }).join('') + '</tbody></table>';

  // Egresos pagados de la semana por razon (las razones de mayor monto).
  const razonesSem = new Map();
  semana.forEach((s, i) => s.pag.porRazon.forEach(g => {
    if (!razonesSem.has(g.razon)) razonesSem.set(g.razon, { razon: g.razon, dias: [0, 0, 0, 0, 0, 0, 0], tot: 0 });
    const x = razonesSem.get(g.razon); x.dias[i] += g.monto; x.tot += g.monto;
  }));
  let topRaz = Array.from(razonesSem.values()).sort((a, b) => b.tot - a.tot);
  if (topRaz.length > 8) {
    const resto = topRaz.slice(7);
    const otras = { razon: 'Otras (' + resto.length + ' razones)', dias: [0, 0, 0, 0, 0, 0, 0], tot: 0 };
    resto.forEach(x => { x.dias.forEach((d, i) => { otras.dias[i] += d; }); otras.tot += x.tot; });
    topRaz = topRaz.slice(0, 7).concat([otras]);
  }
  const maxRaz = Math.max.apply(null, [0].concat(topRaz.map(x => Math.max.apply(null, x.dias))));
  const tablaRazSem = !topRaz.length ? '' :
    '<h2>Egresos pagados por razón — últimos 7 días <small>más oscuro = más monto pagado</small></h2>' +
    '<table class="t sem">' + cabeceraSemana('Razón de pago') + '<tbody>' +
    topRaz.map(x => '<tr><td class="n">' + e(x.razon) + '</td>' + x.dias.map(d => celda(d, 'b', maxRaz)).join('') +
      '<td class="r tt"><b>' + m(x.tot) + '</b></td></tr>').join('') + '</tbody></table>';

  const hoja2 =
    '<section class="hoja">' + encabezado(2, 2) +
    '<h2>Caja — últimos 7 días · pagado <small>fecha de pago · más oscuro = más monto · en verde ingresos, en azul egresos</small></h2>' +
    tablaDias(filasPagado) + tablaRazSem +
    '<h2>Control — últimos 7 días · publicado <small>fecha de publicación, igual que el panel</small></h2>' +
    tablaDias(filasPublicado) +
    '<p class="mini"><b>Ingresos</b>: favorito inglb (clientes). <b>Egresos</b>: favorito Gastoslb (proveedores). ' +
    '<b>Pagado</b>: pagos con fecha de pago del día (hora de Venezuela), incluidos los que aún esperan publicarse. ' +
    '<b>Publicado</b>: pagos publicados en el día, aunque se hayan pagado otro día.</p>' +
    pie + '</section>';

  const css =
    '@page{size:A4 landscape;margin:10mm 12mm}*{box-sizing:border-box}' +
    'body{font-family:Helvetica,Arial,sans-serif;color:#1f2937;margin:0;font-size:11px;' +
    '-webkit-print-color-adjust:exact;print-color-adjust:exact}' +
    '.hoja{page-break-after:always;padding:4px 2px}.hoja:last-child{page-break-after:auto}' +
    '.hd{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid #17375e;' +
    'padding-bottom:6px;margin-bottom:10px}' +
    '.hd h1{margin:0;font-size:22px;color:#17375e}.fecha{font-size:14px;color:#1f2937;margin-top:2px}' +
    '.hdr{text-align:right}.sello{display:inline-block;border:1.5px solid #17375e;color:#17375e;border-radius:5px;' +
    'padding:3px 9px;font-weight:700;font-size:10.5px;letter-spacing:.6px;margin-bottom:5px}' +
    '.gen{color:#6b7280;font-size:10.5px}' +
    '.kp{display:flex;gap:7px;margin-bottom:9px}.k{flex:1;border:1px solid #c9d3e3;border-radius:6px;padding:6px 9px}' +
    '.k span{display:block;color:#4b5563;font-size:10px}.k b{font-size:16px;color:#17375e}' +
    '.k.pos b{color:#15803d}.k.neg b{color:#b91c1c}' +
    '.rev{background:#fdecec;border:1px solid #f5c2c2;border-radius:6px;padding:7px 12px;margin-bottom:10px}' +
    '.revt{color:#b91c1c;font-weight:700;margin-bottom:3px}.rev ul{margin:0;padding-left:0;list-style:none;columns:2}' +
    '.rev li{margin:2px 0}.rev li:before{content:"• "}' +
    'h2{font-size:13.5px;color:#17375e;margin:12px 0 4px}h2 small{font-size:10.5px;color:#6b7280;font-weight:400;margin-left:6px}' +
    'table.t{width:100%;border-collapse:collapse}.t th{background:#eef2f8;color:#374151;font-size:10px;font-weight:700;' +
    'padding:5px 7px;text-align:left;border-bottom:1px solid #c9d3e3}.t td{padding:5px 7px;border-bottom:1px solid #e5e9f0}' +
    '.t tr.grp th{color:#fff;text-align:center;font-size:10.5px;border:0}.ga{background:#2d5d9f!important}' +
    '.gb{background:#23955a!important}.gc{background:#e07b24!important}' +
    '.g1{border-left:2px solid #c9d3e3}.r{text-align:right;white-space:nowrap}.n{white-space:nowrap}' +
    '.c{color:#374151}.z{color:#c3cad6}.rojo{color:#b91c1c}.verde{color:#15803d}' +
    '.t tr.tot td{font-weight:700;background:#eef2f8;border-top:1.5px solid #17375e}' +
    '.t tr.subi td{color:#4b5563;font-size:10.5px;padding-top:3px;padding-bottom:3px}.t tr.fuerte td.n{font-weight:700}.tt{border-left:2px solid #c9d3e3}.t th.hoy{color:#17375e;text-decoration:underline}' +
    '.t th.r{text-align:right}.sem td.r,.sem th.r{text-align:center}.sem td.n{text-align:left}.sem td{padding:3px 6px}' +
    '.bar{height:9px;background:#eef2f8;border-radius:2px}.bar i{display:block;height:100%;background:#2d5d9f;border-radius:2px}' +
    '.mini{color:#6b7280;font-size:10px;margin:5px 0 0}' +
    '.pie{display:flex;justify-content:space-between;color:#9ca3af;font-size:9.5px;border-top:1px solid #e5e9f0;' +
    'padding-top:5px;margin-top:10px}' +
    '.noprint{text-align:right;margin:8px}@media print{.noprint{display:none}}' +
    '.noprint button{background:#17375e;color:#fff;border:0;border-radius:6px;padding:8px 14px;font-weight:700;cursor:pointer}';

  const html = '<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">' +
    '<title>cierre_caja_' + R.dia + '</title><style>' + css + '</style></head><body>' +
    '<div class="noprint"><button onclick="window.print()">Guardar como PDF / Imprimir</button></div>' +
    hoja1 + hoja2 + '</body></html>';
  return html;
}

function reporteDia() {
  const html = htmlReporteDia(diaReporte());
  const w = window.open('', '_blank');
  if (!w) { alert('El navegador bloqueó la ventana del reporte. Permite ventanas emergentes para este sitio.'); return; }
  w.document.open();
  w.document.write(html);
  w.document.close();
  setTimeout(function () { try { w.focus(); w.print(); } catch (_) {} }, 400);
}

function exportCsv() {
  const rows = flatRows(state.rows);
  const enc = s => '"' + String(s == null ? '' : s).replace(/"/g, '""') + '"';
  const cols = ['Nivel', 'Detalle', 'Monto', 'Moneda', 'Tipo', '% Total', 'Cantidad'];
  let csv = cols.join(',') + '\n';
  rows.forEach(n => {
    csv += [n.level + 1, enc(n.label), n.value.toFixed(2), enc(curKey()),
            enc(n.flow || 'Ajuste'), n.pct.toFixed(2), n.count].join(',') + '\n';
  });
  csv += ['', '"TOTAL"', state.total.toFixed(2), enc(curKey()),
          '', '100.00', state.count].join(',') + '\n';
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'gastos_razon_pagos.csv';
  a.click();
}

// Los dos favoritos de Odoo agrupan por x_fecha_de_publicacion. Si el panel
// pasa a la fecha del pago, el corte por ano/mes deja de ser comparable con Odoo
// y se avisa en vez de dejar que las cifras parezcan un dato de Odoo.
function refreshDateWarn() {
  const w = document.getElementById('warn');
  const partes = [];
  if (!usePubDate()) {
    partes.push('<b class="alerta">Ojo:</b> estas cifras usan la <b>fecha del pago</b>. ' +
      'Los favoritos inglb y Gastoslb de Odoo agrupan por <b>fecha de publicacion</b>, ' +
      'asi que los totales por ano y mes no coincidiran con el listado de Odoo.');
  }
  w.innerHTML = partes.join('<br>') + (partes.length && AVISOS_BASE ? '<br>' : '') + AVISOS_BASE;
}

['fFrom', 'fTo', 'fState', 'fCur', 'fComp', 'fNeg', 'fBase', 'fDate'].forEach(id => {
  document.getElementById(id).addEventListener('change', function () {
    refreshDateWarn();
    rerender();
  });
});
document.getElementById('fMeasure').addEventListener('change', toggleMeasure);
// Cambiar el tipo de pago reajusta la base y vuelve a dibujar.
ptypeEl().addEventListener('change', function () {
  syncBaseWithPtype();
  activeReason = null;
  refreshDateWarn();
  rerender();
});
document.getElementById('fNoDate').addEventListener('change', rerender);

(function init() {
  const dates = ROWS.map(r => rowDate(r)).filter(saneDate).sort();
  document.getElementById('fFrom').value = dates[0] || '';
  document.getElementById('fTo').value = dates[dates.length - 1] || '';

  let avisos = '';
  const bad = ROWS.filter(r => rowDate(r) && !saneDate(rowDate(r))).length;
  if (bad) {
    avisos += '<b>Ojo:</b> ' + bad + ' pago(s) tienen una fecha imposible (anio muy lejano). ' +
      'Quedan fuera del rango por defecto para no distorsionar el historico.<br>';
  }
  // Los pagos sin fecha ya se declaran en la tarjeta de corte por ano/mes y en
  // su propio KPI, asi que no se repiten como aviso general al cargar.
  AVISOS_BASE = avisos;
  document.getElementById('warn').innerHTML = avisos;

  syncMeasureUI();
  syncBaseWithPtype();
  render();
  refreshDateWarn();

  // ?reporte=AAAA-MM-DD: la pagina se reemplaza por el cierre de ese dia, para
  // imprimirlo a PDF sin ventana (cierre_caja.js en GitHub Actions).
  const qs = typeof location !== 'undefined' ? location.search : '';
  const diaPdf = (qs.match(/[?&]reporte=(\d{4}-\d{2}-\d{2})/) || [])[1];
  if (diaPdf) {
    const html = htmlReporteDia(diaPdf);
    setTimeout(function () { document.open(); document.write(html); document.close(); }, 0);
  }
})();
</script>
</body>
</html>
"""


def main():
    if not BASE or not DB or not USER or not PWD:
        sys.exit(
            "ERROR: faltan variables de entorno.\n"
            "  $env:ODOO_BASE / ODOO_DB / ODOO_USER / ODOO_PASSWORD"
        )

    auth = rpc(
        BASE + "/web/session/authenticate",
        "call",
        {"db": DB, "login": USER, "password": PWD},
    )
    res = auth.get("result", {})
    if not res.get("uid"):
        print("Fallo de autenticacion:")
        print(json.dumps(auth, ensure_ascii=False)[:500])
        sys.exit(1)
    print("Autenticado:", res.get("name"), "| db:", res.get("db"))

    payload = build_payload()
    # "</" se escapa para que un nombre de proveedor o documento que contenga
    # "</script>" no pueda cerrar la etiqueta y romper el HTML.
    data_js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html_doc = HTML.replace("__DATA__", data_js)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gastos_razon_pagos.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print("Dashboard generado:", out)
    print("Registros en el HTML:", len(payload["rows"]))
    print("Odoo NO fue modificado.")


if __name__ == "__main__":
    main()