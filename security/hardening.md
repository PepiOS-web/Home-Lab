# Seguridad

## Medidas aplicadas

- Acceso remoto con clave SSH Ed25519 protegida por frase de paso.
- UFW deniega conexiones entrantes por defecto.
- Caddy es la unica entrada web, limitada a HTTPS 443 desde la LAN.
- Grafana, Homepage, Uptime Kuma y la interfaz de NetAlertX escuchan en loopback.
- Prometheus y Node Exporter no se publican en la LAN.
- Los contenedores web usan `no-new-privileges` cuando es compatible.
- La autoridad privada de Caddy y sus claves permanecen fuera del repositorio.
- Sistema actualizado tras la instalacion.
- Los paneles de administracion no deben publicarse directamente en Internet.

## Pendiente

- Confirmar el acceso por clave desde una segunda sesion antes de desactivar contrasenas SSH.
- Configurar actualizaciones de seguridad automaticas.
- Revisar periodicamente usuarios, puertos y registros.
- Replicar las copias de seguridad cifradas fuera del servidor.
- Usar VPN antes de habilitar cualquier acceso desde Internet.
- Restringir SSH a la LAN o a una VPN cuando se complete el acceso remoto seguro.

## Informacion que no debe publicarse

- Claves privadas o contenido de `authorized_keys`.
- Contrasenas, tokens y secretos Wi-Fi.
- Archivos `.env` reales.
- IP publica, numeros de serie y direcciones MAC.
- Certificados privados, claves de Caddy, bases de datos y archivos de backup.
