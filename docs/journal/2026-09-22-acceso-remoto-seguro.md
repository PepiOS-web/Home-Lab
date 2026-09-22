# 2026-09-22 - Acceso remoto seguro

## Cambios

- Se instalo Tailscale desde su repositorio oficial firmado.
- Se habilito una ruta restringida `/32` dirigida solo al servidor.
- Se configuro DNS dividido para el dominio interno `home.arpa`.
- Se sustituyo la politica permisiva inicial por una regla limitada al propietario y a HTTPS, DNS y SSH.
- Se mantuvieron desactivados Exit Node y Tailscale SSH.
- UFW se limito a la LAN y a los puertos necesarios de la interfaz Tailscale.
- OpenSSH se endurecio para aceptar exclusivamente claves publicas y denegar root.
- La configuracion recuperable se incorporo al backup, excluyendo la identidad privada de Tailscale.

## Verificacion

- Acceso HTTPS y resolucion DNS comprobados desde un cliente remoto autorizado.
- Acceso OpenSSH comprobado mediante una clave Ed25519 protegida por frase de paso.
- Servicios, contenedores, firewall y ruta privada verificados despues de actualizar el sistema.
- Exit Node confirmado como desactivado.
- Se anadio a Homepage un enlace simple a la consola oficial de Tailscale, sin tokens ni integracion API.
- Se anadio a Homepage un enlace simple al panel interno de AdGuard Home.

No se incluyen direcciones reales, identificadores, capturas, claves ni enlaces de autenticacion.
