# DNS local con AdGuard Home

## Objetivo

AdGuard Home proporciona resolucion DNS y filtrado para los equipos de la red domestica. Los nombres de los paneles `*.home.arpa` apuntan al servidor sin depender del archivo `hosts` de cada dispositivo.

La version documentada es `v0.107.76`. DNS escucha en el puerto 53 TCP y UDP de la direccion privada del servidor. La administracion escucha solamente en `127.0.0.1:3002` y se publica mediante Caddy como `https://dns.home.arpa`.

## Registros locales

Los DNS rewrites asignan cada nombre al servidor. Este ejemplo usa una direccion TEST-NET, nunca la direccion real:

| Dominio | Respuesta de ejemplo |
|---|---|
| `portal.home.arpa` | `192.0.2.10` |
| `grafana.home.arpa` | `192.0.2.10` |
| `kuma.home.arpa` | `192.0.2.10` |
| `network.home.arpa` | `192.0.2.10` |
| `dns.home.arpa` | `192.0.2.10` |

## Despliegue gradual

La primera prueba configura manualmente el DNS en un ordenador y un telefono. El router conserva su configuracion anterior hasta comprobar estabilidad, filtrado, resolucion externa y recuperacion. La distribucion por DHCP se hara despues y mantendra un procedimiento para volver temporalmente al DNS automatico.

En Windows, la recuperacion de una interfaz configurada manualmente es:

```bat
netsh interface ipv4 set dnsservers name="<INTERFACE_NAME>" source=dhcp
ipconfig /flushdns
```

En iOS se selecciona de nuevo la configuracion DNS automatica de la red Wi-Fi. Para abrir los paneles HTTPS, cada cliente instala y confia solo en el certificado publico de la autoridad de Caddy. Las claves privadas nunca se copian.

## Seguridad y privacidad

- UFW permite el puerto 53 TCP/UDP solo desde la subred local.
- La interfaz administrativa no se expone directamente a la LAN.
- El registro de consultas puede revelar dominios visitados; su retencion debe ser limitada y su acceso, privado.
- Los archivos de configuracion, datos, registros y copias de seguridad no se publican.
- El contenedor utiliza `no-new-privileges` y una imagen versionada.

## Supervision y copias

Uptime Kuma realiza cada minuto una consulta DNS de tipo A a AdGuard Home y comprueba que un nombre local devuelve la direccion esperada. El script de backup detiene AdGuard Home junto con los servicios que escriben datos, archiva `/srv/data/appdata` y `/srv/data/compose`, verifica SHA-256 y vuelve a iniciar los contenedores.

## Verificacion

```bash
sudo docker compose -f /srv/data/compose/adguardhome/compose.yaml config
nslookup portal.home.arpa <SERVER_IP>
nslookup example.com <SERVER_IP>
sudo ss -lntup | grep ':53 '
sudo ufw status numbered
```
