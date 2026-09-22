# Seguridad

## Medidas aplicadas

- Acceso remoto con clave SSH Ed25519 protegida por frase de paso.
- UFW deniega conexiones entrantes por defecto.
- Caddy es la unica entrada web, limitada a HTTPS 443 desde la LAN.
- Grafana, Homepage, Uptime Kuma y la interfaz de NetAlertX escuchan en loopback.
- La administracion de AdGuard Home escucha en loopback; DNS 53 TCP/UDP se limita a la LAN mediante enlace y firewall.
- Prometheus y Node Exporter no se publican en la LAN.
- Los contenedores web usan `no-new-privileges` cuando es compatible.
- La autoridad privada de Caddy y sus claves permanecen fuera del repositorio.
- Sistema actualizado tras la instalacion.
- Los paneles de administracion no deben publicarse directamente en Internet.
- SSH solo admite claves publicas, desactiva contrasenas y deniega el acceso directo de root.
- SSH se limita en UFW a la LAN y a la interfaz privada de Tailscale.
- Tailscale anuncia solo una ruta `/32` al servidor; no funciona como Exit Node.
- Tailscale SSH esta desactivado: se utiliza OpenSSH dentro del tunel cifrado.
- La politica de Tailscale limita al propietario los puertos 443, 53 TCP/UDP y 22.
- Los dispositivos nuevos de Tailscale requieren aprobacion.

## Pendiente

- Configurar actualizaciones de seguridad automaticas.
- Revisar periodicamente usuarios, puertos y registros.
- Replicar las copias de seguridad cifradas fuera del servidor.
- Revisar periodicamente los dispositivos, usuarios y politicas de Tailscale.

## Informacion que no debe publicarse

- Claves privadas o contenido de `authorized_keys`.
- Contrasenas, tokens y secretos Wi-Fi.
- Archivos `.env` reales.
- IP publica, numeros de serie y direcciones MAC.
- Certificados privados, claves de Caddy, bases de datos y archivos de backup.
- Direcciones de Tailscale, identificadores de cuenta, nombres reales de dispositivos y enlaces de autenticacion.

## SSH endurecido

La configuracion de referencia se encuentra en
[`infrastructure/ssh/00-homelab-hardening.conf`](../infrastructure/ssh/00-homelab-hardening.conf).
Antes de recargar SSH siempre se valida con `sudo sshd -t` y se conserva abierta una sesion funcional mientras se prueba una segunda conexion.

La frase de paso protege la clave privada del equipo cliente. No se almacena en el servidor ni en este repositorio.
