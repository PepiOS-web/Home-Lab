# 2026-09-24 - Alertas operativas del HomeLab

## Cambios

- Se convirtio el resumen saneado del portal en metricas para el colector de texto de Node Exporter.
- Prometheus confirmo la recepcion de todas las series nuevas.
- Se crearon alertas para backup fallido, backup antiguo, colector detenido, temporizadores desactivados e intentos SSH rechazados.
- Las reglas se incorporaron al grupo de evaluacion de un minuto y reutilizan el canal privado de notificaciones existente.
- El exportador se incorporo al backup consistente.

## Seguridad

- Las metricas contienen exclusivamente numeros, marcas de tiempo y nombres estaticos de temporizadores.
- No incluyen usuarios, IP, puertos, huellas, cuentas ni nombres de dispositivos.
- El webhook de notificaciones permanece exclusivamente en la base de datos privada de Grafana.
- No se abrieron puertos ni se concedio acceso adicional a Docker, journal o Tailscale.

No se publican capturas de la configuracion del punto de contacto ni valores reales de las series.
