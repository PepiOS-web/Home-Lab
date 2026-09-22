# 2026-09-22 - Portal dinamico y actividad saneada

## Cambios

- Se creo un colector local que resume actividad SSH, clientes VPN activos y estado del backup.
- Se eliminaron del resumen IP, puertos, huellas de claves y nombres de dispositivos.
- El JSON se genera atomicamente cada minuto mediante un servicio `oneshot` y un temporizador endurecido.
- Homepage recibe el archivo como un montaje de solo lectura y no obtiene acceso al journal, Docker ni Tailscale.
- Se incorporaron dos widgets `customapi` sin credenciales.
- Se reorganizo la cuadricula y se aplico CSS local adaptable y sin recursos externos.
- Se incorporaron el colector y sus unidades al backup consistente.

## Verificacion

- El endpoint interno respondio `HTTP 200` desde el contenedor.
- El temporizador quedo activo y habilitado.
- El backup incluyo el script y ambas unidades de systemd.
- Todos los contenedores y servicios volvieron a quedar activos.

El JSON generado y las capturas reales no se publican.
