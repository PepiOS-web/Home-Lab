# HTTPS local y reduccion de superficie expuesta

## Objetivo

Sustituir el acceso directo a cada puerto por un unico punto de entrada HTTPS para la red local.

## Trabajo realizado

- Se desplego Caddy con una version fijada, sistema de archivos de solo lectura y capacidades reducidas.
- Se crearon nombres `*.home.arpa` para Homepage, Grafana, Uptime Kuma y NetAlertX.
- Se instalo la autoridad publica de Caddy en el cliente de administracion.
- Homepage, Grafana y Uptime Kuma se enlazaron a loopback.
- NetAlertX conservo `network_mode: host` para el descubrimiento, pero su interfaz web se limito mediante `LISTEN_ADDR=127.0.0.1`.
- Se retiraron de UFW las reglas de acceso directo a 3000, 8080 y 20211.
- Uptime Kuma recibio la autoridad publica como volumen de solo lectura para verificar el portal sin ignorar errores TLS.
- El backup diario se amplio para detener, incluir y reiniciar Homepage y Caddy.

## Resultado

La LAN solo accede a los paneles mediante HTTPS 443. Prometheus, Node Exporter y los puertos web internos no se publican directamente. Las pruebas del proxy devolvieron respuestas HTTP validas y el backup finalizo con SHA-256 correcto.

## Privacidad

La documentacion utiliza nombres locales y direcciones TEST-NET. No incluye direcciones reales, MAC, capturas de inventario, certificados, claves, bases de datos, webhooks ni archivos de backup.
