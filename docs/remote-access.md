# Acceso remoto seguro con Tailscale

## Objetivo

Acceder a los paneles y a OpenSSH desde dispositivos autorizados sin abrir puertos en el router ni publicar los servicios en Internet.

## Diseno aplicado

- Tailscale esta instalado en el servidor y en cada cliente autorizado.
- Los dispositivos nuevos requieren aprobacion.
- El servidor anuncia solamente su propia direccion mediante una ruta `/32`.
- No se anuncia la LAN completa.
- No hay Exit Node configurado ni seleccionado.
- Tailscale SSH esta desactivado; OpenSSH funciona dentro del tunel cifrado.
- El DNS dividido envia exclusivamente `home.arpa` al AdGuard Home del servidor.
- UFW acepta en `tailscale0` solo HTTPS 443, DNS 53 TCP/UDP y SSH 22.
- Una politica adicional de Tailscale limita esos accesos al propietario de la red privada.

La politica publica de ejemplo esta en
[`infrastructure/tailscale/policy.hujson`](../infrastructure/tailscale/policy.hujson). Usa una direccion TEST-NET y nunca debe sustituirse en Git por la direccion real.

## Comprobaciones de seguridad

En el servidor:

```bash
sudo tailscale debug prefs | sed -n \
  -e '/"RouteAll"/p' \
  -e '/"ExitNodeID"/p' \
  -e '/"ExitNodeIP"/p' \
  -e '/"RunSSH"/p' \
  -e '/"AdvertiseRoutes"/,+3p'

sudo ufw status numbered
sudo sshd -T | grep -E \
  '^(passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|permitrootlogin|authenticationmethods)'
```

El resultado esperado es:

- `RouteAll` desactivado.
- `ExitNodeID` y `ExitNodeIP` vacios.
- `RunSSH` desactivado.
- Una unica ruta `/32` correspondiente al servidor.
- SSH con clave publica, sin contrasena y sin acceso directo de root.

Desde Windows, fuera de la LAN y con Tailscale conectado:

```powershell
Test-NetConnection 192.0.2.10 -Port 443
Resolve-DnsName portal.home.arpa -Server 192.0.2.10
ssh homelab
```

`192.0.2.10` es solo un ejemplo documental. Las pruebas reales se hacen con la direccion privada configurada.

## Certificados

Tailscale cifra el transporte, pero el navegador tambien valida el HTTPS emitido por Caddy. Cada dispositivo cliente debe confiar en el certificado publico de la autoridad local. Nunca se copia ni se comparte `root.key`.

## Recuperacion

El backup conserva la configuracion necesaria de SSH, UFW y del repositorio de paquetes de Tailscale, pero excluye la identidad privada del nodo. Tras restaurar:

1. Instalar o verificar Tailscale.
2. Autenticar el servidor como un dispositivo nuevo.
3. Aprobar el dispositivo y la ruta `/32`.
4. Aplicar la politica privada.
5. Confirmar que no existe Exit Node y probar DNS, HTTPS y SSH.

## Datos que nunca se publican

- Direcciones de Tailscale o IP publica.
- Identificador de la cuenta y nombres reales de los dispositivos.
- Enlaces de autenticacion.
- Capturas del panel de administracion.
- Claves SSH, certificados privados, tokens o backups.
