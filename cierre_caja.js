#!/usr/bin/env node
/* Cierre del dia de caja: PDF automatico + correo.
 *
 * Abre el panel ya generado (gastos_razon_pagos.html?reporte=AAAA-MM-DD) con el
 * navegador sin ventana y lo imprime a PDF: es el mismo "Reporte del dia (PDF)"
 * del boton del panel. No consulta Odoo: usa los datos que ya trae el HTML.
 *
 * Variables de entorno (GitHub: Settings > Secrets and variables > Actions):
 *   LATINBIEN_SMTP_USER  LATINBIEN_SMTP_PASS   (la misma cuenta del cierre de embudoventas)
 *   SMTP_HOST (por defecto smtp.gmail.com)  SMTP_PORT (por defecto 587, STARTTLS)
 *   MAIL_TO   (destinatarios separados por coma)  MAIL_FROM (opcional)
 *
 * Uso:
 *   node cierre_caja.js --dia 2026-11-06 --html panel.html --pdf cierres/caja_2026-11-06.pdf
 *   node cierre_caja.js --dia 2026-11-06 --pdf cierres/caja_2026-11-06.pdf --enviar
 *   node cierre_caja.js ... --enviar --prueba   # no envia: guarda el correo en cierre_caja_prueba.html
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { pathToFileURL } = require('url');

const args = process.argv.slice(2);
const val = k => (args.indexOf(k) !== -1 ? args[args.indexOf(k) + 1] : null);
const dia = val('--dia');
if (!/^\d{4}-\d{2}-\d{2}$/.test(dia || '')) { console.error('Uso: node cierre_caja.js --dia AAAA-MM-DD [--html panel.html] [--pdf salida.pdf] [--enviar] [--prueba]'); process.exit(2); }
const htmlPanel = path.resolve(val('--html') || path.join(__dirname, 'gastos_razon_pagos.html'));
const pdf = path.resolve(val('--pdf') || path.join(__dirname, 'cierres', `caja_${dia}.pdf`));
const opt = { enviar: args.includes('--enviar'), prueba: args.includes('--prueba') };

function navegador() {
  const candidatos = [
    process.env.CHROME_PATH,
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium-browser', '/usr/bin/chromium',
  ].filter(Boolean);
  const p = candidatos.find(c => fs.existsSync(c));
  if (!p) throw new Error('No se encontro Chrome ni Edge para generar el PDF');
  return p;
}

// Imprime el reporte del dia a PDF con el navegador sin ventana.
function generarPdf() {
  if (!fs.existsSync(htmlPanel)) throw new Error('No existe el panel: ' + htmlPanel);
  fs.mkdirSync(path.dirname(pdf), { recursive: true });
  const perfil = fs.mkdtempSync(path.join(os.tmpdir(), 'cierre-caja-'));
  const tmp = pdf + '.tmp.pdf';
  const url = pathToFileURL(htmlPanel).href + '?reporte=' + dia;
  try {
    execFileSync(navegador(), ['--headless=new', '--disable-gpu', ...(process.platform === 'linux' ? ['--no-sandbox'] : []), '--no-first-run', '--no-pdf-header-footer',
      `--user-data-dir=${perfil}`, '--virtual-time-budget=15000', `--print-to-pdf=${tmp}`, url], { stdio: 'ignore', timeout: 180000 });
  } finally { fs.rmSync(perfil, { recursive: true, force: true }); }
  if (!fs.existsSync(tmp) || fs.statSync(tmp).size < 1000) throw new Error('El navegador no genero el PDF del cierre');
  fs.renameSync(tmp, pdf);
  console.log(`[cierre] PDF generado: ${pdf} (${Math.round(fs.statSync(pdf).size / 1024)} KB)`);
}

async function enviar() {
  const DSEM = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
  const fecha = `${DSEM[new Date(dia + 'T12:00:00Z').getUTCDay()]} ${dia.slice(8, 10)}/${dia.slice(5, 7)}/${dia.slice(0, 4)}`;
  const asunto = `Cierre del día ${dia.slice(8, 10)}/${dia.slice(5, 7)} · Caja y egresos`;
  const cuerpo = `<!DOCTYPE html><html><body style="margin:0;background:#f4f6f9;font-family:Segoe UI,Arial,sans-serif;color:#1c2733">
<div style="max-width:640px;margin:0 auto;padding:16px">
  <div style="background:#17375e;color:#fff;padding:14px 18px;border-radius:10px 10px 0 0">
    <div style="font-size:18px;font-weight:700">Cierre del día · Caja</div>
    <div style="font-size:13px;opacity:.9">${fecha}</div>
  </div>
  <div style="background:#fff;border:1px solid #d3dae3;border-top:none;padding:16px 18px;border-radius:0 0 10px 10px;font-size:14px;line-height:1.6">
    Se adjunta el <b>PDF del cierre de caja</b> del día: ingresos, anticipos, egresos, pagos publicados, lo que queda para revisar y los últimos 7 días.
    <p style="font-size:12px;color:#8a939c;margin:12px 0 0">Foto fija generada automáticamente a las 20:30 (hora Venezuela) con la consulta de solo lectura a Odoo.</p>
  </div>
</div></body></html>`;
  if (opt.prueba) {
    fs.writeFileSync(path.join(__dirname, 'cierre_caja_prueba.html'), cuerpo);
    console.log(`[correo] PRUEBA (no enviado): ${asunto} | PDF ${fs.existsSync(pdf) ? 'adjunto' : 'no existe'}`);
    return;
  }
  const usuario = process.env.LATINBIEN_SMTP_USER || process.env.SMTP_USER;
  const clave = process.env.LATINBIEN_SMTP_PASS || process.env.SMTP_PASS;
  const para = process.env.MAIL_TO;
  if (!usuario || !clave) throw new Error('Faltan LATINBIEN_SMTP_USER / LATINBIEN_SMTP_PASS');
  if (!para) throw new Error('Falta MAIL_TO (destinatarios)');
  const nodemailer = require('nodemailer');
  const puerto = +(process.env.SMTP_PORT || 587);
  const t = nodemailer.createTransport({ host: process.env.SMTP_HOST || 'smtp.gmail.com', port: puerto, secure: puerto === 465, requireTLS: puerto !== 465, auth: { user: usuario, pass: clave } });
  const info = await t.sendMail({
    from: process.env.MAIL_FROM || `Caja Latinbien <${usuario}>`,
    to: para,
    subject: asunto,
    html: cuerpo,
    attachments: [{ filename: `cierre_caja_${dia}.pdf`, path: pdf }],
  });
  console.log(`[correo] enviado a ${para}: ${info.messageId}`);
}

(async () => {
  if (!opt.enviar || !fs.existsSync(pdf)) generarPdf();
  if (opt.enviar) await enviar();
})().catch(e => { console.error('[cierre] ERROR:', e.message); process.exit(1); });
