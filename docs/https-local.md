# HTTPS local con Caddy

## Objetivo

Caddy es el unico punto de entrada para los paneles web. Escucha en HTTPS 443 sobre la direccion privada del servidor y reenvia las solicitudes a servicios enlazados exclusivamente a loopback.

| Nombre local | Destino interno |
|---|---|
| `portal.home.arpa` | Homepage en `127.0.0.1:8080` y Grafana en `/grafana/` hacia `127.0.0.1:3000` |
| `grafana.home.arpa` | Compatibilidad con enlaces anteriores; Grafana usa como URL canonica `portal.home.arpa/grafana/` |
| `kuma.home.arpa` | `127.0.0.1:3001` |
| `network.home.arpa` | `127.0.0.1:20211` |
| `dns.home.arpa` | `127.0.0.1:3002` |

`home.arpa` es el dominio reservado para redes domesticas. Los registros se crean en el DNS local. Como alternativa temporal, pueden declararse en el archivo `hosts` de cada cliente.

Grafana se sirve desde el mismo origen que Homepage. Esta disposicion permite que el dashboard autenticado funcione dentro del portal en navegadores de escritorio y moviles sin habilitar acceso anonimo ni depender de cookies de terceros.

Antes del despliegue se copia `.env.example` como `.env` y se reemplaza la direccion TEST-NET por la direccion privada del servidor. El `.env` real permanece ignorado por Git.

## Autoridad local

`tls internal` crea una autoridad privada. Los clientes deben instalar unicamente su certificado publico `root.crt` en el almacen de confianza. `root.key`, `intermediate.key` y las claves de cada sitio nunca deben salir del servidor ni entrar en Git.

Firefox puede utilizar el almacen de Windows habilitando `security.enterprise_roots.enabled`. En iOS se instala el perfil del certificado publico y se activa su confianza total desde los ajustes del sistema.

## Firewall

UFW permite HTTPS 443 solo desde la subred local. Los puertos 3000, 3001, 3002, 8080 y 20211 no tienen reglas de entrada. Una regla adicional y limitada permite que la red Docker de Uptime Kuma consulte Caddy en 443. AdGuard Home publica DNS 53 TCP/UDP por separado y solo para la LAN.

Las direcciones reales dependen de cada instalacion. Los ejemplos del repositorio usan `192.0.2.10`, perteneciente a TEST-NET-1 y no enrutable.

## Verificacion

```bash
sudo docker compose -f /srv/data/compose/caddy/compose.yaml config
sudo docker compose -f /srv/data/compose/caddy/compose.yaml run --rm caddy \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo ss -lntup | grep -E ':53|:443|:3000|:3001|:3002|:8080|:20211'
sudo ufw status numbered
```

Una restauracion debe conservar `/srv/data/appdata/caddy`; generar una autoridad diferente obligaria a reinstalar confianza en todos los clientes.
