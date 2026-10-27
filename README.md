# HomeLab

Proyecto personal para convertir un portatil reutilizado en un servidor domestico seguro, monitorizado y ampliable. El objetivo final es integrar sistemas, redes, ciberseguridad, sensores electronicos y deteccion de anomalias mediante IA.

## Estado actual

- Ubuntu Server 24.04 LTS instalado en el SSD.
- Administracion remota mediante SSH con clave Ed25519.
- Firewall UFW activo y limitado inicialmente a OpenSSH.
- Conexion Wi-Fi operativa tras reinicios.
- Direccion IPv4 local estatica configurada para la administracion del servidor.
- Suspension, hibernacion y accion de cierre de tapa desactivadas.
- Pruebas SMART extendidas completadas sin errores en el SSD y el HDD.
- HDD de 1 TB preparado en ext4 y montado automaticamente en `/srv/data`.
- Docker Engine y Docker Compose instalados desde el repositorio oficial y verificados con un contenedor de prueba.
- Uptime Kuma desplegado para supervisar disponibilidad y latencia.
- NetAlertX desplegado para descubrimiento local e inventario de dispositivos.
- Prometheus y Node Exporter recopilando metricas del servidor cada 15 segundos.
- Grafana desplegado con el dashboard Node Exporter Full.
- Temperaturas Linux exportadas automaticamente cada minuto mediante systemd.
- Alertas de temperatura, disponibilidad, almacenamiento y memoria enviadas a Discord.
- Copias consistentes diarias con verificacion SHA-256 y rotacion automatica.
- Portal local Homepage para centralizar el acceso a los servicios.
- Proxy inverso Caddy con HTTPS interno para todos los paneles web.
- Interfaces web enlazadas a loopback; solo HTTPS 443 se publica en la LAN.
- AdGuard Home proporciona DNS local, bloqueo de dominios y resolucion de los nombres `*.home.arpa`.
- Acceso remoto privado mediante Tailscale, sin publicar paneles ni SSH en Internet.
- SSH acepta exclusivamente claves publicas y bloquea el acceso directo de root.
- Ubuntu instala automaticamente solo las actualizaciones de seguridad permitidas, sin reinicios automaticos.
- Prototipo ambiental ESP8266 con DHT11 integrado en Prometheus, Grafana y Homepage.
- Firmware ESPHome actualizable mediante OTA y secretos excluidos del repositorio.

## AstroLearner y operacion preparada

El repositorio incluye dos aplicaciones locales de AstroLearner y procedimientos
de mantenimiento. Su presencia en Git no confirma que cada revision este
activada en el servidor:

- [Factory](infrastructure/docker/astrolearner-factory/README.md): borradores
  revisables, voz y montaje local, staging separado y clips opcionales importados.
  No incluye publicacion automatica ni un modelo de generacion de video.
- [ISS Live](infrastructure/docker/astrolearner-iss-live/README.md): control manual,
  metadatos editables, salud de la senal, musica y recuperacion de la misma emision
  ante cortes de transporte. El envio adicional a Starvios es opcional.
- [Captura de camara](infrastructure/docker/astrolearner-iss-live/BROWSER-CAMERA.md):
  navegador aislado y comprobaciones previas; requiere validar permisos de uso,
  disponibilidad y rendimiento de la fuente antes de emitir.
- [Panel orbital y musica melodica](infrastructure/docker/astrolearner-iss-live/STREAM-UPGRADE.md):
  actualizacion preparada con respaldo de mapa y activacion controlada.
- [Backup](docs/backups.md) y [mantenimiento manual](docs/manual-maintenance.md):
  snapshot de datos ISS para evitar detener su emisor durante la copia y
  actualizacion conservadora de paquetes del host.

El [registro del 27 de octubre](docs/journal/2026-10-27-astrolearner-y-operacion.md)
resume los cambios y las comprobaciones que siguen dependiendo del servidor.

## Hardware base

| Componente | Especificacion |
|---|---|
| Equipo | Acer Aspire VX5-591G reutilizado |
| Procesador | Intel Core i7-7700HQ |
| Memoria | 8 GB RAM |
| Disco del sistema | SSD Kingston de 128 GB |
| Almacenamiento | HDD Toshiba de 1 TB |
| Red | Ethernet y Wi-Fi |

Los numeros de serie, credenciales, direcciones MAC y otros identificadores no se publican.

## Objetivos

1. Construir una base Linux estable y accesible en remoto.
2. Preparar almacenamiento persistente para servicios y copias de seguridad.
3. Desplegar servicios aislados con contenedores.
4. Monitorizar recursos, red, temperaturas y disponibilidad.
5. Incorporar sensores ambientales y electricos.
6. Detectar comportamientos anomalos mediante modelos de IA.

## Documentacion

- [English project summary](docs/summary-en.md)
- [Arquitectura](docs/architecture.md)
- [Hoja de ruta](docs/roadmap.md)
- [Seguridad](security/hardening.md)
- [Auditoria y adaptador endurecido A9/V720](security/a9-v720-security-review.md)
- [Problemas y soluciones](docs/troubleshooting.md)
- [Diario de progreso](docs/journal/README.md)
- [Despliegue de Uptime Kuma](infrastructure/docker/uptime-kuma/compose.yaml)
- [Monitorizacion de red](docs/network-monitoring.md)
- [Guia de comandos](docs/command-reference.md)
- [Despliegue de NetAlertX](infrastructure/docker/netalertx/compose.yaml)
- [Monitorizacion del sistema](docs/system-monitoring.md)
- [Despliegue de Prometheus, Node Exporter y Grafana](infrastructure/docker/monitoring/compose.yaml)
- [Copias de seguridad](docs/backups.md)
- [Portal local](docs/portal.md)
- [HTTPS local con Caddy](docs/https-local.md)
- [DNS local con AdGuard Home](docs/dns-local.md)
- [Acceso remoto seguro con Tailscale](docs/remote-access.md)
- [Actualizaciones automaticas de seguridad](docs/automatic-security-updates.md)
- [Mantenimiento manual del host](docs/manual-maintenance.md)
- [Sensor ambiental ESP8266](docs/environmental-sensor.md)
- [Adaptador local endurecido A9/V720](infrastructure/docker/a9-v720-hardened/README.md)

## Seguridad del repositorio

Este repositorio nunca debe contener contrasenas, claves SSH privadas, secretos Wi-Fi, tokens, IP publicas ni archivos `.env` reales. Los ejemplos usan valores como `<SERVER_IP>`.

## Licencia

Publicado bajo la licencia MIT.
