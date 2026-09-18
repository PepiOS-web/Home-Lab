# Arquitectura

## Vision general

```text
Equipos de la LAN
      |-- DNS 53 TCP/UDP --> AdGuard Home
      |                         `-- nombres *.home.arpa
      |
      | HTTPS 443
      v
Caddy (TLS interno y cabeceras de seguridad)
      |
      |-- 127.0.0.1:8080 -> Homepage
      |-- 127.0.0.1:3000 -> Grafana
      |-- 127.0.0.1:3001 -> Uptime Kuma
      |-- 127.0.0.1:20211 -> NetAlertX
      `-- 127.0.0.1:3002 -> Administracion de AdGuard Home

Servidor Ubuntu
  |-- Node Exporter: metricas del sistema
  |-- Prometheus: almacenamiento de series temporales
  |-- NetAlertX: inventario y eventos de red
  |-- Uptime Kuma: disponibilidad y latencia
  |-- AdGuard Home: DNS local y filtrado
  |-- Almacenamiento en HDD
  `-- Analisis de anomalias
             ^
             |
      Sensores futuros
```

## Almacenamiento

- SSD de 128 GB: sistema operativo y software.
- HDD de 1 TB: datos persistentes, metricas y futuras copias de seguridad; montado en `/srv/data`.

Las pruebas SMART extendidas del SSD y del HDD finalizaron sin errores. El HDD utiliza ext4 y se monta automaticamente mediante UUID.

## Evolucion prevista

La primera version sera totalmente local. Los sensores enviaran datos al servidor, que los almacenara y mostrara en un panel. La deteccion de anomalias se anadira cuando exista suficiente historial fiable.

## Flujo actual de metricas

```text
Linux y sensores termicos
          |
          v
Node Exporter -- cada 15 s --> Prometheus -- consultas --> Grafana
                                      |
                                      v
                         /srv/data/appdata/prometheus
```

Prometheus, Node Exporter y las interfaces web escuchan en la interfaz de bucle local. Caddy es el unico punto de entrada web y publica HTTPS 443 solo hacia la subred local.

Homepage proporciona un punto de entrada visual a los paneles. La primera version contiene enlaces y comprobaciones HTTP, pero no monta el socket de Docker ni almacena tokens de las APIs.

Los nombres `*.home.arpa` se resuelven mediante AdGuard Home. Durante las pruebas se pueden usar entradas locales temporales. Caddy emite certificados con una autoridad privada cuya clave nunca se publica.
